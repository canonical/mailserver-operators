# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Shared fixtures and configuration for integration tests."""

import logging
import typing
from collections.abc import Generator

import jubilant
import pytest
import yaml

from helpers import integrate_once, select_charm_file, sha512_dovecot_password

logger = logging.getLogger(__name__)


POSTFIX_RELAY_APP = "postfix-relay"
CONFIGURATOR_APP = "postfix-relay-configurator"
SELF_SIGNED_APP = "self-signed-certificates"

TEST_DOMAIN = "mailstack.internal"
SMTP_PORT = 587


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add integration test command-line options."""
    parser.addoption(
        "--charm-file",
        action="append",
        default=[],
        help="Path to charm file (can be used multiple times)",
    )
    parser.addoption(
        "--use-existing",
        action="store_true",
        default=False,
        help="Use existing model instead of creating a temporary one",
    )
    parser.addoption(
        "--model",
        default=None,
        help="Specific model name to use",
    )
    parser.addoption(
        "--keep-models",
        action="store_true",
        default=False,
        help="Keep temporary models after tests complete",
    )

@pytest.fixture(scope="module", name="juju")
def juju_fixture(request: pytest.FixtureRequest) -> Generator[jubilant.Juju, None, None]:
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


@pytest.fixture(scope="module", name="postfix_stack")
def postfix_stack_fixture(
    juju: jubilant.Juju,
    pytestconfig: pytest.Config,
) -> typing.Dict[str, str]:
    """Deploy postfix-relay + postfix-relay-configurator configured for sender_login enforcement.

    Returns a dict with ``postfix_relay_ip``.
    """
    if not juju.status().apps.get(SELF_SIGNED_APP):
        juju.deploy(SELF_SIGNED_APP, channel="latest/stable")
    juju.wait(
        lambda status: status.apps[SELF_SIGNED_APP].is_active,
        error=jubilant.any_error,
        timeout=10 * 60,
    )

    # --- postfix-relay ---
    auth_password = "test-password"
    if not juju.status().apps.get(POSTFIX_RELAY_APP):
        charm_path = select_charm_file(pytestconfig, "postfix-relay_")
        if not charm_path.startswith(("./", "/")):
            charm_path = f"./{charm_path}"
        juju.deploy(
            charm_path,
            app=POSTFIX_RELAY_APP,
            config={
                "relay_domains": f"- {TEST_DOMAIN}",
                "enable_smtp_auth": "true",
                "smtp_auth_users": yaml.dump(
                    [f"testuser:{sha512_dovecot_password(auth_password)}"]
                ),
                "enable_reject_unknown_sender_domain": "false",
            },
        )
    integrate_once(
        juju,
        f"{POSTFIX_RELAY_APP}:certificates",
        f"{SELF_SIGNED_APP}:certificates",
    )

    # --- postfix-relay-configurator ---
    authorized_sender = f"authorized@{TEST_DOMAIN}"
    if not juju.status().apps.get(CONFIGURATOR_APP):
        charm_path = select_charm_file(pytestconfig, "postfix-relay-configurator_")
        if not charm_path.startswith(("./", "/")):
            charm_path = f"./{charm_path}"
        juju.deploy(
            charm_path,
            app=CONFIGURATOR_APP,
            config={
                "sender_login_maps": yaml.dump({authorized_sender: "testuser"}),
            },
        )
    integrate_once(
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
