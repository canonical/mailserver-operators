# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for the full-stack mailserver integration tests.

Topology
--------
                         ┌─────────────────────┐
  test runner ──587──►   │   postfix-relay      │ ◄─milter─► opendkim
  (smtplib)              │   + configurator     │             (DKIM sign)
                         └──────────┬──────────┘
                                    │ LMTP :24
                                    ▼
                              dovecot (IMAP)
                                    │
                         ◄──993──── │
  test runner (imaplib)             │
  verifies DKIM-Signature header    │
  and subject in delivered mail     ┘

TLS for postfix-relay is provided by self-signed-certificates (CharmHub).
"""

import base64
import hashlib
import logging
import pathlib
from secrets import token_hex
import socket
import typing
from collections.abc import Generator
import json

import jubilant
import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Charm / app names
# ---------------------------------------------------------------------------
DOVECOT_APP = "dovecot"
POSTFIX_RELAY_APP = "postfix-relay"
OPENDKIM_APP = "opendkim"
CONFIGURATOR_APP = "postfix-relay-configurator"
SELF_SIGNED_APP = "self-signed-certificates"

# Domain used throughout the test suite
TEST_DOMAIN = "mailstack.internal"
SMTP_PORT = 587
E2E_SMTP_USER = "e2euser"
E2E_SMTP_PASSWORD = "e2e-password"

# parents[0]=tests/integration, parents[1]=tests, parents[2]=mailserver-operators/
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
OPENDKIM_SNAP_DIR = _REPO_ROOT / "opendkim-snap"


# ---------------------------------------------------------------------------
# pytest CLI options
# ---------------------------------------------------------------------------
def pytest_addoption(parser: pytest.Parser) -> None:
    """Register extra CLI options consumed by the integration suite."""
    parser.addoption(
        "--charm-file",
        action="append",
        default=[],
        help=("Path to a pre-built .charm file. Pass this option multiple times (one per charm)."),
    )
    parser.addoption(
        "--keep-models",
        action="store_true",
        default=False,
        help="Keep Juju models after tests complete (useful for debugging).",
    )
    parser.addoption(
        "--model",
        action="store",
        default=None,
        help="Use an existing Juju model by name instead of creating a temp model.",
    )
    parser.addoption(
        "--use-existing",
        action="store_true",
        default=False,
        help="Attach to the current Juju model without deploying anything new.",
    )



# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
def _sha512_dovecot_password(password: str) -> str:
    """Generate a SSHA512 password hash compatible with dovecot."""
    salt = b"mailtest"
    digest = hashlib.sha512(password.encode() + salt).digest()
    return "{SSHA512}" + base64.b64encode(digest + salt).decode()


def _integrate_once(juju: jubilant.Juju, endpoint_a: str, endpoint_b: str) -> None:
    """Call ``juju integrate`` tolerating 'already related' errors."""
    try:
        juju.integrate(endpoint_a, endpoint_b)
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "already exists" not in msg and "already related" not in msg:
            raise
        logger.debug("Relation %s ↔ %s already exists, skipping", endpoint_a, endpoint_b)


def _select_charm_file(pytestconfig: pytest.Config, marker: str) -> str:
    """Select charm file matching marker from --charm-file options."""
    charm_files: list[str] = pytestconfig.getoption("--charm-file", default=[])
    for path in charm_files:
        if marker in pathlib.Path(path).name.lower():
            return path
    use_existing = pytestconfig.getoption("--use-existing", default=False)
    if use_existing:
        return ""
    provided = ", ".join(charm_files) if charm_files else "<none>"
    raise AssertionError(f"Missing --charm-file matching '{marker}'. Provided: {provided}.")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", name="juju")
def juju_fixture(
    request: pytest.FixtureRequest,
) -> Generator[jubilant.Juju, None, None]:
    """Session-scoped Juju client pointing at a temporary (or named) model."""

    def _show_debug_log(juju: jubilant.Juju) -> None:
        if request.session.testsfailed:
            log = juju.debug_log(limit=2000)
            print(log, end="")

    use_existing = request.config.getoption("--use-existing", default=False)
    if use_existing:
        juju = jubilant.Juju()
        juju.model_config({"automatically-retry-hooks": True})
        yield juju
        _show_debug_log(juju)
        return

    model = request.config.getoption("--model")
    if model:
        juju = jubilant.Juju(model=model)
        juju.model_config({"automatically-retry-hooks": True})
        yield juju
        _show_debug_log(juju)
        return

    keep_models = typing.cast(bool, request.config.getoption("--keep-models"))
    with jubilant.temp_model(keep=keep_models) as juju:
        juju.wait_timeout = 15 * 60
        juju.model_config({"automatically-retry-hooks": True})
        yield juju
        _show_debug_log(juju)
        return


# ---------------------------------------------------------------------------
# Machine IP (test runner)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", name="machine_ip_address")
def machine_ip_address_fixture() -> str:
    """IP address of the machine running the tests.

    Used to configure /etc/hosts on Juju units so TEST_DOMAIN resolves to
    the test runner (where mailcatcher or similar sinks may be listening),
    and also to tell postfix-relay where to forward mail.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    logger.info("Test runner IP: %s", ip)
    return ip


# ---------------------------------------------------------------------------
# Charm-file fixtures
# ---------------------------------------------------------------------------
def _select_charm_file_for_app(pytestconfig: pytest.Config, app_name: str) -> str:
    """Return a charm file path matching *app_name* from repeated --charm-file args."""
    charm_files = typing.cast(list[str], pytestconfig.getoption("--charm-file"))
    use_existing = pytestconfig.getoption("--use-existing", default=False)

    # Match more specific names first to avoid postfix-relay matching configurator.
    match_order = (
        (CONFIGURATOR_APP, "postfix-relay-configurator"),
        (POSTFIX_RELAY_APP, "postfix-relay"),
        (DOVECOT_APP, "dovecot"),
        (OPENDKIM_APP, "opendkim"),
    )

    app_to_path: dict[str, str] = {}
    for path in charm_files:
        name = pathlib.Path(path).name.lower()
        for app, marker in match_order:
            if marker in name:
                app_to_path[app] = path
                break

    selected = app_to_path.get(app_name)
    if selected:
        return selected

    if use_existing:
        # In --use-existing mode, deployment may be skipped if apps already exist.
        return ""

    provided = ", ".join(charm_files) if charm_files else "<none>"
    raise AssertionError(
        f"Missing --charm-file for {app_name}. Provided: {provided}. "
        "Pass one --charm-file per charm artifact."
    )


@pytest.fixture(scope="session", name="dovecot_charm_file")
def dovecot_charm_file_fixture(pytestconfig: pytest.Config) -> str:
    """Absolute path to the pre-built dovecot .charm file."""
    return _select_charm_file_for_app(pytestconfig, DOVECOT_APP)


@pytest.fixture(scope="session", name="postfix_relay_charm_file")
def postfix_relay_charm_file_fixture(pytestconfig: pytest.Config) -> str:
    """Absolute path to the pre-built postfix-relay .charm file."""
    return _select_charm_file_for_app(pytestconfig, POSTFIX_RELAY_APP)


@pytest.fixture(scope="session", name="opendkim_charm_file")
def opendkim_charm_file_fixture(pytestconfig: pytest.Config) -> str:
    """Absolute path to the pre-built opendkim .charm file."""
    return _select_charm_file_for_app(pytestconfig, OPENDKIM_APP)


@pytest.fixture(scope="session", name="configurator_charm_file")
def configurator_charm_file_fixture(pytestconfig: pytest.Config) -> str:
    """Absolute path to the pre-built postfix-relay-configurator .charm file."""
    return _select_charm_file_for_app(pytestconfig, CONFIGURATOR_APP)


# ---------------------------------------------------------------------------
# DKIM key generation helper
# ---------------------------------------------------------------------------
def generate_dkim_keypair(domain: str, selector: str) -> typing.Tuple[str, str]:
    """Generate a DKIM keypair using the Python cryptography library.

    Args:
        domain: The signing domain (e.g. ``mailstack.internal``).
        selector: The DKIM selector (e.g. ``default``).

    Returns:
        A ``(txt_record, private_key_pem)`` tuple where ``txt_record`` is a
        DNS TXT record string and ``private_key_pem`` is a PEM-encoded RSA
        private key.
    """
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    pub_der = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    pub_b64 = base64.b64encode(pub_der).decode()
    txt_record = (
        f'{selector}._domainkey\tIN\tTXT\t( "v=DKIM1; h=sha256; k=rsa; "\n'
        f'\t"p={pub_b64}" )\n'
        f"; ----- DKIM key {selector} for {domain}\n"
    )
    return txt_record, private_key_pem


# ---------------------------------------------------------------------------
# Deploy: self-signed-certificates (TLS provider for postfix-relay / dovecot)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", name="self_signed_app")
def deploy_self_signed_certs_fixture(juju: jubilant.Juju) -> str:
    """Deploy self-signed-certificates from CharmHub."""
    if not juju.status().apps.get(SELF_SIGNED_APP):
        juju.deploy(SELF_SIGNED_APP, channel="latest/stable")
    juju.wait(
        lambda status: status.apps[SELF_SIGNED_APP].is_active,
        error=jubilant.any_error,
        timeout=10 * 60,
    )
    logger.info("self-signed-certificates is active")
    return SELF_SIGNED_APP


@pytest.fixture(scope="module", name="postfix_stack")
def postfix_stack_fixture(
    juju: jubilant.Juju,
    pytestconfig: pytest.Config,
    self_signed_app: str,
) -> typing.Dict[str, str]:
    """Deploy postfix-relay + postfix-relay-configurator configured for sender_login enforcement.

    Returns a dict with ``postfix_relay_ip``.
    """
    # --- postfix-relay ---
    auth_password = "test-password"
    if not juju.status().apps.get(POSTFIX_RELAY_APP):
        charm_path = _select_charm_file(pytestconfig, "postfix-relay_")
        if not charm_path.startswith(("./", "/")):
            charm_path = f"./{charm_path}"
        juju.deploy(
            charm_path,
            app=POSTFIX_RELAY_APP,
            config={
                "relay_domains": f"- {TEST_DOMAIN}",
                "enable_smtp_auth": "true",
                "smtp_auth_users": yaml.dump(
                    [f"testuser:{_sha512_dovecot_password(auth_password)}"]
                ),
                "enable_reject_unknown_sender_domain": "false",
            },
        )
    _integrate_once(
        juju,
        f"{POSTFIX_RELAY_APP}:certificates",
        f"{self_signed_app}:certificates",
    )

    # --- postfix-relay-configurator ---
    authorized_sender = f"authorized@{TEST_DOMAIN}"
    if not juju.status().apps.get(CONFIGURATOR_APP):
        charm_path = _select_charm_file(pytestconfig, "postfix-relay-configurator_")
        if not charm_path.startswith(("./", "/")):
            charm_path = f"./{charm_path}"
        juju.deploy(
            charm_path,
            app=CONFIGURATOR_APP,
            config={
                "sender_login_maps": yaml.dump({authorized_sender: "testuser"}),
            },
        )
    _integrate_once(
        juju,
        f"{POSTFIX_RELAY_APP}:juju-info",
        f"{CONFIGURATOR_APP}:juju-info",
    )

    # Wait for both to be active.
    def _both_active(status: jubilant.Status) -> bool:
        if not status.apps.get(POSTFIX_RELAY_APP):
            return False
        if not status.apps[POSTFIX_RELAY_APP].is_active:
            return False
        for unit in status.apps[POSTFIX_RELAY_APP].units.values():
            subs = unit.subordinates or {}
            conf_subs = {k: v for k, v in subs.items() if CONFIGURATOR_APP in k}
            if not conf_subs:
                return False
            for sub in conf_subs.values():
                if sub.workload_status.current != "active":
                    return False
        return True

    juju.wait(_both_active, error=jubilant.any_error, timeout=15 * 60)
    logger.info("postfix-relay + configurator active for maps tests")

    status = juju.status()
    relay_ip = next(iter(status.apps[POSTFIX_RELAY_APP].units.values())).public_address
    logger.info("postfix-relay IP: %s", relay_ip)
    return {"postfix_relay_ip": relay_ip}


# ---------------------------------------------------------------------------
# Deploy: opendkim
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", name="opendkim_app")
def deploy_opendkim_fixture(
    opendkim_charm_file: str,
    juju: jubilant.Juju,
) -> str:
    """Deploy opendkim and optionally replace the store snap with a local build."""
    if not juju.status().apps.get(OPENDKIM_APP):
        charm_path = (
            opendkim_charm_file
            if opendkim_charm_file.startswith(("./", "/"))
            else f"./{opendkim_charm_file}"
        )
        juju.deploy(charm_path, OPENDKIM_APP)
        # Charm starts blocked (not yet configured) or waiting for milter relation.
        juju.wait(
            lambda status: (
                status.apps[OPENDKIM_APP].is_blocked
                or status.apps[OPENDKIM_APP].app_status.current == "waiting"
            ),
            timeout=10 * 60,
        )

    _replace_opendkim_snap(juju, OPENDKIM_APP)
    return OPENDKIM_APP


def _replace_opendkim_snap(juju: jubilant.Juju, app_name: str) -> None:
    """Replace the store-installed opendkim snap with a locally-built one if present."""
    snap_files = sorted(OPENDKIM_SNAP_DIR.glob("opendkim_*.snap"))
    if not snap_files:
        logger.warning(
            "No locally-built opendkim snap found in %s — using store version",
            OPENDKIM_SNAP_DIR,
        )
        return

    snap_path = snap_files[-1]
    snap_name = snap_path.name
    logger.info("Replacing opendkim snap with local build: %s", snap_path)

    status = juju.status()
    for unit_name in status.apps[app_name].units:
        juju.scp(snap_path, f"{unit_name}:/tmp/{snap_name}")
        juju.exec(
            "sudo",
            "snap",
            "install",
            "--dangerous",
            f"/tmp/{snap_name}",  # nosec B108
            unit=unit_name,
        )
        logger.info("Installed local opendkim snap on %s", unit_name)


# ---------------------------------------------------------------------------
# Deploy: dovecot
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", name="dovecot_app")
def deploy_dovecot_fixture(
    dovecot_charm_file: str,
    self_signed_app: str,
    juju: jubilant.Juju,
) -> str:
    """Deploy dovecot and wire up TLS."""
    luks_key = token_hex(16)

    if not juju.status().apps.get(DOVECOT_APP):
        charm_path = (
            dovecot_charm_file
            if dovecot_charm_file.startswith(("./", "/"))
            else f"./{dovecot_charm_file}"
        )
        secret_id = juju.cli("add-secret", "dovecot-luks-key", f"key={luks_key}").strip()
        juju.deploy(
            charm_path,
            app=DOVECOT_APP,
            config={
                "mailname": TEST_DOMAIN,
                "postmaster-address": f"postmaster@{TEST_DOMAIN}",
                "primary-unit": f"{DOVECOT_APP}/0",
                "luks-auto-provisioning": True,
                "luks-key": secret_id,
            },
            constraints={"virt-type": "virtual-machine"},
            trust=True,
        )
    juju.cli("grant-secret", "dovecot-luks-key", DOVECOT_APP)

    # Relate to TLS provider if not already related.
    _integrate_once(juju, f"{DOVECOT_APP}:certificates", f"{self_signed_app}:certificates")

    juju.wait(
        lambda status: status.apps[DOVECOT_APP].is_active,
        error=jubilant.any_error,
        timeout=15 * 60,
    )
    logger.info("dovecot is active")
    return DOVECOT_APP


# ---------------------------------------------------------------------------
# Deploy: postfix-relay
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", name="postfix_relay_app")
def deploy_postfix_relay_fixture(
    postfix_relay_charm_file: str,
    self_signed_app: str,
    opendkim_app: str,
    juju: jubilant.Juju,
    pytestconfig: pytest.Config,
) -> str:
    """Deploy postfix-relay and integrate with TLS provider and opendkim milter."""
    if not juju.status().apps.get(POSTFIX_RELAY_APP):
        charm_path = (
            postfix_relay_charm_file
            if postfix_relay_charm_file.startswith(("./", "/"))
            else f"./{postfix_relay_charm_file}"
        )
        juju.deploy(
            charm_path,
            app=POSTFIX_RELAY_APP,
            config={
                "relay_domains": f"- {TEST_DOMAIN}",
                "enable_smtp_auth": "true",
                "smtp_auth_users": yaml.dump(
                    [f"{E2E_SMTP_USER}:{_sha512_dovecot_password(E2E_SMTP_PASSWORD)}"]
                ),
                "enable_reject_unknown_sender_domain": "false",
            },
        )

    _integrate_once(juju, f"{POSTFIX_RELAY_APP}:certificates", f"{self_signed_app}:certificates")
    _integrate_once(juju, f"{POSTFIX_RELAY_APP}:milter", f"{opendkim_app}:milter")

    juju.wait(
        lambda status: (
            status.apps[POSTFIX_RELAY_APP].is_active
            and status.apps[opendkim_app].app_status.current in {"blocked", "active"}
        ),
        timeout=15 * 60,
    )
    logger.info("postfix-relay is active (opendkim is blocked or already active)")
    return POSTFIX_RELAY_APP


# ---------------------------------------------------------------------------
# Deploy: postfix-relay-configurator (subordinate)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", name="configurator_app")
def deploy_configurator_fixture(
    configurator_charm_file: str,
    postfix_relay_app: str,
    dovecot_app: str,
    juju: jubilant.Juju,
) -> str:
    """Deploy the postfix-relay-configurator subordinate and configure LMTP routing.

    The configurator's ``transport_maps`` is set to route mail for TEST_DOMAIN
    to dovecot's LMTP port (24) so that postfix-relay delivers locally to dovecot.
    """
    # Resolve dovecot's IP after it is active.
    status = juju.status()
    dovecot_unit = next(iter(status.apps[dovecot_app].units.values()))
    dovecot_ip = dovecot_unit.public_address
    logger.info("Routing %s → lmtp:inet:%s:24", TEST_DOMAIN, dovecot_ip)

    configurator_config = {
        "relay_access_sources": yaml.dump({"192.0.2.0/24": "OK"}),
        "relay_recipient_maps": yaml.dump(
            {f"noreply@{TEST_DOMAIN}": f"postmaster@{TEST_DOMAIN}"}
        ),
        "restrict_recipients": yaml.dump({"blocked-recipient@example.invalid": "REJECT"}),
        "restrict_senders": yaml.dump({"blocked-sender@example.invalid": "REJECT"}),
        "sender_login_maps": yaml.dump(
            {
                "auth-only@example.invalid": "nobody",
                f"{E2E_SMTP_USER}@{TEST_DOMAIN}": f"{E2E_SMTP_USER}@{TEST_DOMAIN}",
            }
        ),
        "transport_maps": yaml.dump({TEST_DOMAIN: f"lmtp:inet:{dovecot_ip}:24"}),
    }

    if not juju.status().apps.get(CONFIGURATOR_APP):
        charm_path = (
            configurator_charm_file
            if configurator_charm_file.startswith(("./", "/"))
            else f"./{configurator_charm_file}"
        )
        juju.deploy(
            charm_path,
            app=CONFIGURATOR_APP,
            config=configurator_config,
        )
    else:
        juju.config(CONFIGURATOR_APP, configurator_config)

    _integrate_once(juju, f"{postfix_relay_app}:juju-info", f"{CONFIGURATOR_APP}:juju-info")

    # Wait for both to be active.
    def _both_active(status: jubilant.Status) -> bool:
        if not status.apps.get(postfix_relay_app):
            return False
        if not status.apps[POSTFIX_RELAY_APP].is_active:
            return False
        for unit in status.apps[POSTFIX_RELAY_APP].units.values():
            subs = unit.subordinates or {}
            conf_subs = {k: v for k, v in subs.items() if CONFIGURATOR_APP in k}
            if not conf_subs:
                return False
            for sub in conf_subs.values():
                if sub.workload_status.current != "active":
                    return False
        return True

    juju.wait(_both_active, error=jubilant.any_error, timeout=15 * 60)
    logger.info("postfix-relay-configurator subordinate is active")
    return CONFIGURATOR_APP


# ---------------------------------------------------------------------------
# Configure opendkim with DKIM keys for TEST_DOMAIN
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", name="opendkim_configured")
def configure_opendkim_fixture(
    opendkim_app: str,
    postfix_relay_app: str,
    machine_ip_address: str,
    juju: jubilant.Juju,
) -> str:
    """Generate a DKIM keypair and configure opendkim for TEST_DOMAIN.

    Returns the opendkim app name once the app is active.
    """

    selector = "default"
    keyname = f"{TEST_DOMAIN.replace('.', '-')}-{selector}"
    _, private_key = generate_dkim_keypair(domain=TEST_DOMAIN, selector=selector)

    # Store private key as a Juju secret.
    try:
        secret_id = juju.add_secret("mailstack-dkim-secret", {keyname: private_key})
    except jubilant.CLIError as exc:
        if "already exists" in exc.stderr:
            secret_info = juju.show_secret("mailstack-dkim-secret")
            secret_id = secret_info.uri
            juju.update_secret(secret_id, {keyname: private_key})
        else:
            logger.error("Failed to add secret: %s %s", exc.stderr, exc.stdout)
            raise

    juju.cli("grant-secret", secret_id, opendkim_app)

    keytable = [
        [
            f"{selector}._domainkey.{TEST_DOMAIN}",
            f"{TEST_DOMAIN}:{selector}:/etc/dkimkeys/{keyname}.private",
        ]
    ]
    signingtable = [[f"*@{TEST_DOMAIN}", f"{selector}._domainkey.{TEST_DOMAIN}"]]
    juju.config(
        opendkim_app,
        {
            "keytable": json.dumps(keytable),
            "signingtable": json.dumps(signingtable),
            "private-keys": secret_id,
            "mode": "s",
        },
    )

    # Inject TEST_DOMAIN → test-runner IP in /etc/hosts on the postfix-relay unit
    # so that Postfix can resolve the domain when it looks up the MX / transport.
    status = juju.status()
    relay_unit = next(iter(status.apps[postfix_relay_app].units.values()))
    juju.exec(
        machine=relay_unit.machine,
        command=f"echo '{machine_ip_address} {TEST_DOMAIN}' | sudo tee -a /etc/hosts",
    )

    juju.wait(
        lambda status: jubilant.all_active(status, opendkim_app, postfix_relay_app),
        timeout=5 * 60,
        delay=5,
    )
    logger.info("opendkim configured and active with DKIM keys for %s", TEST_DOMAIN)
    return opendkim_app


# ---------------------------------------------------------------------------
# Full stack fixture — depends on everything
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", name="mail_stack")
def mail_stack_fixture(
    juju: jubilant.Juju,
    dovecot_app: str,
    postfix_relay_app: str,
    opendkim_configured: str,
    configurator_app: str,
) -> typing.Dict[str, str]:
    """Ensure the complete mail stack is up and return a dict of app names and IPs.

    Returns a mapping with keys:
        ``dovecot_app``, ``postfix_relay_app``, ``opendkim_app``,
        ``configurator_app``, ``dovecot_ip``, ``postfix_relay_ip``.
    """
    juju.wait(
        lambda status: jubilant.all_active(
            status, dovecot_app, postfix_relay_app, opendkim_configured, SELF_SIGNED_APP
        ),
        timeout=5 * 60,
    )

    status = juju.status()
    dovecot_ip = next(iter(status.apps[dovecot_app].units.values())).public_address
    relay_ip = next(iter(status.apps[postfix_relay_app].units.values())).public_address

    logger.info("Mail stack ready — dovecot: %s, postfix-relay: %s", dovecot_ip, relay_ip)
    return {
        "dovecot_app": dovecot_app,
        "postfix_relay_app": postfix_relay_app,
        "opendkim_app": opendkim_configured,
        "configurator_app": configurator_app,
        "dovecot_ip": dovecot_ip,
        "postfix_relay_ip": relay_ip,
    }

