# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for charm integration tests."""

import typing
from collections.abc import Generator

import jubilant
import pytest


@pytest.fixture(scope="module", name="postfix_relay_charm")
def postfix_relay_charm_fixture(pytestconfig: pytest.Config):
    """Get value from parameter charm-file."""
    charm = pytestconfig.getoption("--charm-file")
    use_existing = pytestconfig.getoption("--use-existing", default=False)
    if not use_existing:
        assert charm, "--charm-file must be set"
    return charm


@pytest.fixture(scope="module", name="postfix_relay_app")
def deploy_postfix_relay_fixture(
    postfix_relay_charm: str,
    juju: jubilant.Juju,
) -> str:
    """Deploy postfix-relay."""
    postfix_relay_app_name = "postfix-relay"

    if not juju.status().apps.get(postfix_relay_app_name):
        juju.deploy(
            f"./{postfix_relay_charm}",
            postfix_relay_app_name,
        )

    # Ensure self-signed-certificates is deployed, but make the operation idempotent.
    if not juju.status().apps.get("self-signed-certificates"):
        try:
            juju.deploy("self-signed-certificates")
        except Exception as exc:
            # Ignore benign "already exists" style errors; re-raise anything else.
            if "already exists" not in str(exc):
                raise

    # Integrate postfix-relay with self-signed-certificates, tolerating an existing relation.
    try:
        juju.integrate(
            postfix_relay_app_name,
            "self-signed-certificates",
        )
    except Exception as exc:
        # Ignore errors that indicate the relation already exists; re-raise others.
        message = str(exc)
        if "already exists" not in message and "already related" not in message:
            raise

    juju.wait(
        lambda status: status.apps[postfix_relay_app_name].is_active,
        error=jubilant.any_blocked,
        timeout=10 * 60,
    )
    return postfix_relay_app_name


@pytest.fixture(scope="session", name="juju")
def juju_fixture(request: pytest.FixtureRequest) -> Generator[jubilant.Juju, None, None]:
    """Pytest fixture that wraps :meth:`jubilant.with_model`."""

    def show_debug_log(juju: jubilant.Juju):
        if request.session.testsfailed:
            log = juju.debug_log(limit=1000)
            print(log, end="")

    use_existing = request.config.getoption("--use-existing", default=False)
    if use_existing:
        juju = jubilant.Juju()
        yield juju
        show_debug_log(juju)
        return

    model = request.config.getoption("--model")
    if model:
        juju = jubilant.Juju(model=model)
        yield juju
        show_debug_log(juju)
        return

    keep_models = typing.cast(bool, request.config.getoption("--keep-models"))
    with jubilant.temp_model(keep=keep_models) as juju:
        juju.wait_timeout = 10 * 60
        yield juju
        show_debug_log(juju)
        return
