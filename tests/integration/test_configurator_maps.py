# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for postfix-relay-configurator sender_login_maps enforcement.

These tests deploy only postfix-relay + postfix-relay-configurator (no Dovecot
or OpenDKIM required) to verify that the configurator correctly writes
sender_login maps and that postfix enforces them.
"""

import base64
import hashlib
import logging
import pathlib
import smtplib
import ssl
import typing
from collections.abc import Generator

import jubilant
import pytest
import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App / domain constants
# ---------------------------------------------------------------------------
POSTFIX_RELAY_APP = "postfix-relay-maps"
CONFIGURATOR_APP = "postfix-relay-configurator-maps"
SELF_SIGNED_APP = "self-signed-certificates"

TEST_DOMAIN = "mailstack.internal"
SMTP_PORT = 587

AUTH_USER = "testuser"
AUTH_PASSWORD = "test-password"
AUTHORIZED_SENDER = f"authorized@{TEST_DOMAIN}"
SPOOFED_SENDER = f"spoofed@{TEST_DOMAIN}"
RECIPIENT = f"recipient@{TEST_DOMAIN}"

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _sha512_dovecot_password(password: str) -> str:
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
    charm_files: list[str] = pytestconfig.getoption("--charm-file", default=[])
    for path in charm_files:
        if marker in pathlib.Path(path).name.lower():
            return path
    use_existing = pytestconfig.getoption("--use-existing", default=False)
    if use_existing:
        return ""
    provided = ", ".join(charm_files) if charm_files else "<none>"
    raise AssertionError(
        f"Missing --charm-file matching '{marker}'. Provided: {provided}."
    )


# ---------------------------------------------------------------------------
# Session fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module", name="maps_juju")
def maps_juju_fixture(request: pytest.FixtureRequest) -> Generator[jubilant.Juju, None, None]:
    """Module-scoped Juju client in a temporary model for configurator map tests."""

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

    model = request.config.getoption("--model", default=None)
    if model:
        juju = jubilant.Juju(model=model)
        juju.model_config({"automatically-retry-hooks": True})
        yield juju
        _show_debug_log(juju)
        return

    keep_models = typing.cast(bool, request.config.getoption("--keep-models", default=False))
    with jubilant.temp_model(keep=keep_models) as juju:
        juju.wait_timeout = 15 * 60
        juju.model_config({"automatically-retry-hooks": True})
        yield juju
        _show_debug_log(juju)


@pytest.fixture(scope="module", name="maps_stack")
def maps_stack_fixture(
    maps_juju: jubilant.Juju,
    pytestconfig: pytest.Config,
) -> typing.Dict[str, str]:
    """Deploy postfix-relay + postfix-relay-configurator configured for sender_login enforcement.

    Returns a dict with ``postfix_relay_ip``.
    """
    juju = maps_juju

    # --- self-signed-certificates (TLS for postfix-relay) ---
    if not juju.status().apps.get(SELF_SIGNED_APP):
        juju.deploy(SELF_SIGNED_APP, channel="latest/stable")
    juju.wait(
        lambda status: status.apps[SELF_SIGNED_APP].is_active,
        error=jubilant.any_error,
        timeout=10 * 60,
    )

    # --- postfix-relay ---
    if not juju.status().apps.get(POSTFIX_RELAY_APP):
        charm_path = _select_charm_file(pytestconfig, "postfix-relay")
        if not charm_path.startswith(("./", "/")):
            charm_path = f"./{charm_path}"
        juju.deploy(
            charm_path,
            app=POSTFIX_RELAY_APP,
            config={
                "relay_domains": f"- {TEST_DOMAIN}",
                "enable_smtp_auth": "true",
                "smtp_auth_users": yaml.dump(
                    [f"{AUTH_USER}:{_sha512_dovecot_password(AUTH_PASSWORD)}"]
                ),
                "enable_reject_unknown_sender_domain": "false",
            },
        )
    _integrate_once(
        juju,
        f"{POSTFIX_RELAY_APP}:certificates",
        f"{SELF_SIGNED_APP}:certificates",
    )

    # --- postfix-relay-configurator ---
    if not juju.status().apps.get(CONFIGURATOR_APP):
        charm_path = _select_charm_file(pytestconfig, "postfix-relay-configurator")
        if not charm_path.startswith(("./", "/")):
            charm_path = f"./{charm_path}"
        juju.deploy(
            charm_path,
            app=CONFIGURATOR_APP,
            config={
                "sender_login_maps": yaml.dump(
                    {AUTHORIZED_SENDER: AUTH_USER}
                ),
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
# Tests
# ---------------------------------------------------------------------------
class TestSenderLoginMapEnforcement:
    """Verify that sender_login_maps written by the configurator are enforced by postfix."""

    def test_sender_login_map_enforcement(self, maps_stack: typing.Dict[str, str]) -> None:
        """Authenticated user can send from authorized address but not from a spoofed one."""
        relay_ip = maps_stack["postfix_relay_ip"]

        # --- Success case: send from authorized address ---
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        with smtplib.SMTP(relay_ip, SMTP_PORT, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ctx)
            smtp.ehlo()
            smtp.login(AUTH_USER, AUTH_PASSWORD)
            smtp.sendmail(
                from_addr=AUTHORIZED_SENDER,
                to_addrs=[RECIPIENT],
                msg=(
                    f"From: {AUTHORIZED_SENDER}\r\n"
                    f"To: {RECIPIENT}\r\n"
                    "Subject: test authorized sender\r\n"
                    "\r\n"
                    "This message should be accepted.\r\n"
                ),
            )
            logger.info("Success case: message from %s accepted", AUTHORIZED_SENDER)

        # --- Failure case: send from spoofed address ---
        with smtplib.SMTP(relay_ip, SMTP_PORT, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ctx)
            smtp.ehlo()
            smtp.login(AUTH_USER, AUTH_PASSWORD)
            with pytest.raises(smtplib.SMTPSenderRefused) as exc_info:
                smtp.sendmail(
                    from_addr=SPOOFED_SENDER,
                    to_addrs=[RECIPIENT],
                    msg=(
                        f"From: {SPOOFED_SENDER}\r\n"
                        f"To: {RECIPIENT}\r\n"
                        "Subject: test spoofed sender\r\n"
                        "\r\n"
                        "This message should be rejected.\r\n"
                    ),
                )
            logger.info(
                "Failure case: message from %s rejected with code %s",
                SPOOFED_SENDER,
                exc_info.value.smtp_code,
            )
            assert exc_info.value.smtp_code == 553, (
                f"Expected 553 Sender address rejected, got {exc_info.value.smtp_code}: "
                f"{exc_info.value.smtp_error}"
            )
