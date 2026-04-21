# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import typing
from secrets import token_hex

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
    tls_charm: str,
) -> str:
    """Build and deploy the charm."""
    logging.info(f"Checking for existing application {APP_NAME}...")
    luks_key = token_hex(16)

    if not juju.status().apps.get(APP_NAME):
        logging.info(f"Application {APP_NAME} not found, proceeding with deployment.")

        secret_id = juju.cli("add-secret", "dovecot-luks-key", f"key={luks_key}").strip()
        logging.info(f"Created LUKS secret: {secret_id}")

        config = {
            "mailname": "example.com",
            "postmaster-address": "postmaster@example.com",
            "primary-unit": f"{APP_NAME}/0",
            "luks-auto-provisioning": True,
            "luks-key": secret_id,
        }
        charm_path = charm if charm.startswith(("./", "/")) else f"./{charm}"
        juju.deploy(
            charm_path,
            app=APP_NAME,
            config=config,
            constraints={"virt-type": "virtual-machine"},
            trust=True,
        )
    juju.cli("grant-secret", "dovecot-luks-key", APP_NAME)
    try:
        logging.info("Adding TLS relation...")
        juju.integrate(f"{APP_NAME}:certificates", f"{tls_charm}:certificates")
    except Exception:
        logging.info("TLS relation already there...")
    logging.info("Waiting for active status...")
    juju.wait(
        lambda status: jubilant.all_active(status, APP_NAME, tls_charm),
        timeout=10 * 60,
    )
    return APP_NAME


@pytest.fixture(scope="module")
def dovecot_charm_manual_storage(
    charm: str,
    juju: jubilant.Juju,
    tls_charm: str,
) -> str:
    """Build and deploy the charm."""
    charm_name = f"{APP_NAME}-manual"
    logging.info(f"Checking for existing application {charm_name}...")

    if not juju.status().apps.get(charm_name):
        logging.info(f"Application {charm_name} not found, proceeding with deployment.")

        config = {
            "mailname": "example.com",
            "postmaster-address": "postmaster@example.com",
            "primary-unit": f"{charm_name}/0",
            "luks-auto-provisioning": False,
        }
        charm_path = charm if charm.startswith(("./", "/")) else f"./{charm}"
        juju.deploy(
            charm_path,
            app=charm_name,
            config=config,
            constraints={"virt-type": "virtual-machine"},
            trust=True,
        )

    try:
        logging.info("Adding TLS relation...")
        juju.integrate(f"{charm_name}:certificates", f"{tls_charm}:certificates")
    except Exception:
        logging.info("TLS relation already there...")

    logging.info("Waiting for blocked status...")
    juju.wait(
        lambda status: status.apps[charm_name].is_blocked,
        timeout=10 * 60,
    )
    return charm_name


@pytest.fixture(scope="module")
def tls_charm(juju: jubilant.Juju) -> str:
    tls_app = "self-signed-certificates"
    if tls_app not in juju.status().apps:
        logging.info("Deploying self-signed-certificates...")
        juju.deploy(tls_app, channel="latest/stable")
    else:
        logging.info(f"{tls_app} already deployed, skipping deployment.")

    return tls_app
