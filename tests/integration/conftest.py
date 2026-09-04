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
import json
import logging
import pathlib
import socket
import typing
from collections.abc import Generator
from secrets import token_hex

import jubilant
import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from helpers import (
    integrate_once as _integrate_once,
)
from helpers import (
    sha512_dovecot_password as _sha512_dovecot_password,
)
from opcli.pytest_plugin import CharmPathList

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
TEST_SMTP_USER = "e2euser"
TEST_SMTP_PASSWORD = token_hex(16)

# parents[0]=tests/integration, parents[1]=tests, parents[2]=mailserver-operators/
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
OPENDKIM_SNAP_DIR = _REPO_ROOT / "opendkim-snap"

SMTP_PORT = 587
AUTHORIZED_SENDER = f"authorized@{TEST_DOMAIN}"


# ---------------------------------------------------------------------------
# pytest CLI options
# ---------------------------------------------------------------------------
def pytest_addoption(parser: pytest.Parser) -> None:
    """Register extra CLI options consumed by the integration suite."""
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


def _get_charm_path(request: pytest.FixtureRequest, charm_name: str) -> str:
    """Resolve a charm path only when its application needs deployment."""
    charm_paths = typing.cast(dict[str, CharmPathList], request.getfixturevalue("charm_paths"))
    return charm_paths[charm_name].path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", name="juju")
def juju_fixture(request: pytest.FixtureRequest) -> Generator[jubilant.Juju, None, None]:
    """Session-scoped Juju client in a temporary model for integration tests."""
    logging.getLogger("jubilant.wait").setLevel(logging.WARNING)

    def _show_debug_log(juju: jubilant.Juju) -> None:
        if request.session.testsfailed:
            print(juju.debug_log(limit=2000), end="")

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


@pytest.fixture(scope="session", name="postfix_stack")
def postfix_stack_fixture(
    juju: jubilant.Juju,
    postfix_relay_app: str,
    postfix_relay_configurator_app: str,
) -> typing.Dict[str, str]:
    """Deploy postfix-relay + postfix-relay-configurator configured for sender_login enforcement.

    Returns a dict with ``postfix_relay_ip``.
    """
    _integrate_once(
        juju,
        f"{postfix_relay_app}:juju-info",
        f"{postfix_relay_configurator_app}:juju-info",
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
    return {"postfix_relay_app": postfix_relay_app, "postfix_relay_ip": relay_ip}


# ---------------------------------------------------------------------------
# Deploy: opendkim
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", name="opendkim_app")
def deploy_opendkim_fixture(
    juju: jubilant.Juju,
    request: pytest.FixtureRequest,
) -> str:
    """Deploy opendkim and optionally replace the store snap with a local build."""
    if not juju.status().apps.get(OPENDKIM_APP):
        juju.deploy(_get_charm_path(request, "opendkim"), OPENDKIM_APP)
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
    self_signed_app: str,
    juju: jubilant.Juju,
    request: pytest.FixtureRequest,
) -> str:
    """Deploy dovecot and wire up TLS."""
    luks_key = token_hex(16)

    if not juju.status().apps.get(DOVECOT_APP):
        secret_id = juju.cli("add-secret", "dovecot-luks-key", f"key={luks_key}").strip()
        juju.deploy(
            _get_charm_path(request, "dovecot"),
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
    self_signed_app: str,
    juju: jubilant.Juju,
    request: pytest.FixtureRequest,
) -> str:
    """Deploy postfix-relay and integrate with TLS provider."""
    if not juju.status().apps.get(POSTFIX_RELAY_APP):
        juju.deploy(
            _get_charm_path(request, "postfix-relay"),
            app=POSTFIX_RELAY_APP,
            config={
                "relay_domains": f"- {TEST_DOMAIN}",
                "enable_smtp_auth": "true",
                "smtp_auth_users": yaml.dump(
                    [f"{TEST_SMTP_USER}:{_sha512_dovecot_password(TEST_SMTP_PASSWORD)}"]
                ),
                "enable_reject_unknown_sender_domain": "false",
            },
        )

    _integrate_once(juju, f"{POSTFIX_RELAY_APP}:certificates", f"{self_signed_app}:certificates")

    juju.wait(
        lambda status: status.apps[POSTFIX_RELAY_APP].is_active,
        timeout=15 * 60,
    )
    logger.info("postfix-relay is active")
    return POSTFIX_RELAY_APP


@pytest.fixture(scope="session", name="postfix_relay_configurator_app")
def deploy_postfix_relay_configurator_fixture(
    juju: jubilant.Juju,
    request: pytest.FixtureRequest,
) -> str:
    """Deploy postfix-relay-configurator."""
    if not juju.status().apps.get(CONFIGURATOR_APP):
        juju.deploy(
            _get_charm_path(request, "postfix-relay-configurator"),
            app=CONFIGURATOR_APP,
            config={
                "sender_login_maps": yaml.dump({AUTHORIZED_SENDER: TEST_SMTP_USER}),
            },
        )
    else:
        juju.config(
            CONFIGURATOR_APP, {"sender_login_maps": yaml.dump({AUTHORIZED_SENDER: TEST_SMTP_USER})}
        )
    logger.info("postfix-relay-configurator deployed")
    return CONFIGURATOR_APP


# ---------------------------------------------------------------------------
# Deploy: postfix-relay-configurator (subordinate)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", name="configurator_app")
def deploy_configurator_fixture(
    postfix_stack: typing.Dict[str, str],
    opendkim_app: str,
    dovecot_app: str,
    juju: jubilant.Juju,
) -> str:
    """Deploy the postfix-relay-configurator subordinate and configure SMTP routing.

    The configurator's ``transport_maps`` is set to route mail for TEST_DOMAIN
    to dovecot's Postfix on port 25, which delivers locally to dovecot via LMTP
    Unix socket.
    """
    # Resolve dovecot's IP after it is active.
    status = juju.status()
    dovecot_unit = next(iter(status.apps[dovecot_app].units.values()))
    dovecot_ip = dovecot_unit.public_address
    logger.info("Routing %s → smtp:[%s]:25", TEST_DOMAIN, dovecot_ip)
    _integrate_once(juju, f"{postfix_stack['postfix_relay_app']}:milter", f"{opendkim_app}:milter")

    configurator_config = {
        "relay_access_sources": yaml.dump({"192.0.2.0/24": "OK"}),
        "relay_recipient_maps": yaml.dump(
            {
                f"noreply@{TEST_DOMAIN}": f"postmaster@{TEST_DOMAIN}",
                f"{TEST_SMTP_USER}@{TEST_DOMAIN}": "OK",
            }
        ),
        "restrict_recipients": yaml.dump({"blocked-recipient@example.invalid": "REJECT"}),
        "restrict_senders": yaml.dump({"blocked-sender@example.invalid": "REJECT"}),
        "sender_login_maps": yaml.dump(
            {
                AUTHORIZED_SENDER: TEST_SMTP_USER,
                "auth-only@example.invalid": "nobody",
                f"{TEST_SMTP_USER}@{TEST_DOMAIN}": f"{TEST_SMTP_USER}@{TEST_DOMAIN}",
            }
        ),
        "transport_maps": yaml.dump({TEST_DOMAIN: f"smtp:[{dovecot_ip}]:25"}),
    }

    juju.config(CONFIGURATOR_APP, configurator_config)

    # Wait for both to be active.
    def _both_active(status: jubilant.Status) -> bool:
        if not status.apps.get(postfix_stack["postfix_relay_app"]):
            return False
        if not status.apps[postfix_stack["postfix_relay_app"]].is_active:
            return False
        for unit in status.apps[postfix_stack["postfix_relay_app"]].units.values():
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
    return CONFIGURATOR_APP


# ---------------------------------------------------------------------------
# Configure opendkim with DKIM keys for TEST_DOMAIN
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", name="opendkim_configured")
def configure_opendkim_fixture(
    opendkim_app: str,
    postfix_stack: typing.Dict[str, str],
    configurator_app: str,
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
    relay_unit = next(iter(status.apps[postfix_stack["postfix_relay_app"]].units.values()))
    juju.exec(
        machine=relay_unit.machine,
        command=f"echo '{machine_ip_address} {TEST_DOMAIN}' | sudo tee -a /etc/hosts",
    )

    juju.wait(
        lambda status: jubilant.all_active(
            status, opendkim_app, postfix_stack["postfix_relay_app"]
        ),
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
    postfix_stack: typing.Dict[str, str],
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
            status,
            dovecot_app,
            postfix_stack["postfix_relay_app"],
            opendkim_configured,
            SELF_SIGNED_APP,
        ),
        timeout=5 * 60,
    )

    status = juju.status()
    dovecot_ip = next(iter(status.apps[dovecot_app].units.values())).public_address

    logger.info(
        "Mail stack ready — dovecot: %s, postfix-relay: %s",
        dovecot_ip,
        postfix_stack["postfix_relay_ip"],
    )
    return {
        "dovecot_app": dovecot_app,
        "opendkim_app": opendkim_configured,
        "configurator_app": configurator_app,
        "dovecot_ip": dovecot_ip,
        **postfix_stack,
    }
