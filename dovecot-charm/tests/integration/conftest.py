# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import typing

import jubilant
import pytest

logger = logging.getLogger(__name__)

APP_NAME = "dovecot-charm"


@pytest.fixture(scope="session", name="juju")
def juju_fixture(request: pytest.FixtureRequest):
    """Pytest fixture that wraps jubilant.with_model."""
    use_existing = request.config.getoption("--use-existing", default=False)
    if use_existing:
        juju = jubilant.Juju()
        yield juju
        return

    model = request.config.getoption("--model")
    if model:
        juju = jubilant.Juju(model=model)
        yield juju
        return

    keep_models = typing.cast(bool, request.config.getoption("--keep-models"))
    with jubilant.temp_model(keep=keep_models) as juju:
        juju.wait_timeout = 10 * 60
        yield juju
        return


@pytest.fixture(scope="module", name="charm")
def charm_fixture(pytestconfig: pytest.Config) -> str:
    """Get value from parameter charm-file."""
    charm = pytestconfig.getoption("--charm-file")
    assert charm, "--charm-file must be set"
    return charm


@pytest.fixture(scope="module")
def dovecot_charm(
    charm: str,
    juju: jubilant.Juju,
) -> str:
    """Build and deploy the charm."""
    logging.info(f"Checking for existing application {APP_NAME}...")

    if not juju.status().apps.get(APP_NAME):
        logging.info(f"Application {APP_NAME} not found, proceeding with deployment.")

        config = {
            "mailname": "example.com",
            "postmaster-address": "postmaster@example.com",
            "primary-unit": f"{APP_NAME}/0",
        }
        charm_path = charm if charm.startswith(("./", "/")) else f"./{charm}"
        juju.deploy(
            charm_path,
            app=APP_NAME,
            config=config,
            constraints={"virt-type": "virtual-machine"},
            trust=True,
            log=False,
        )

    logging.info("Waiting for active status...")
    juju.wait(jubilant.all_active, timeout=10 * 60)
    return APP_NAME
