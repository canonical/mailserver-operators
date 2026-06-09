# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import secrets
import typing

import jubilant
import pytest

from .helpers import setup_gdpr_test_user, teardown_gdpr_test_user

logger = logging.getLogger(__name__)

APP_NAME = "dovecot"
# Charm mailname — must match the value passed in deploy config so tests can
# construct the correct SMTP recipient addresses (@example.com).
MAILNAME = "example.com"

# GDPR action test constants
MAIL_ROOT = "/srv/mail"
GDPR_ARCHIVE_DIR = f"{MAIL_ROOT}/archives"
GDPR_TAKEOUT_DIR = f"{MAIL_ROOT}/takeout"
GDPR_TEST_USER = "gdpr-testuser"
GDPR_TEST_PASSWORD = secrets.token_hex(16)

# create-mail-user action test constants
CREATE_MAIL_USER_TEST_USER = "cmu-testuser"
CREATE_MAIL_USER_TEST_MAILBOX = "cmu-testuser@example.com"
CREATE_MAIL_USER_TEST_PASSWORD = secrets.token_hex(16)


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
    with jubilant.temp_model(keep=keep_models, config={"automatically-retry-hooks": True}) as juju:
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
    luks_key = secrets.token_hex(16)

    if not juju.status().apps.get(APP_NAME):
        logging.info(f"Application {APP_NAME} not found, proceeding with deployment.")

        secret_id = juju.cli("add-secret", "dovecot-luks-key", f"key={luks_key}").strip()
        logging.info(f"Created LUKS secret: {secret_id}")

        config = {
            "mailname": MAILNAME,
            "postmaster-address": f"postmaster@{MAILNAME}",
            "primary-unit": f"{APP_NAME}/0",
            "luks-auto-provisioning": True,
            "luks-key": secret_id,
        }
        charm_path = charm if charm.startswith(("./", "/")) else f"./{charm}"
        juju.deploy(
            charm_path,
            app=APP_NAME,
            config=config,
            constraints={"virt-type": "virtual-machine", "mem": "2048M", "cores": "2"},
        )
    juju.cli("grant-secret", "dovecot-luks-key", APP_NAME)
    try:
        logging.info("Adding TLS relation...")
        juju.integrate(f"{APP_NAME}:certificates", f"{tls_charm}:certificates")
    except jubilant.CLIError:
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
            "mailname": MAILNAME,
            "postmaster-address": f"postmaster@{MAILNAME}",
            "primary-unit": f"{charm_name}/0",
            "luks-auto-provisioning": False,
        }
        charm_path = charm if charm.startswith(("./", "/")) else f"./{charm}"
        juju.deploy(
            charm_path,
            app=charm_name,
            config=config,
            constraints={"virt-type": "virtual-machine", "mem": "2048M", "cores": "2"},
        )
    try:
        logging.info("Adding TLS relation...")
        juju.integrate(f"{charm_name}:certificates", f"{tls_charm}:certificates")
    except jubilant.CLIError:
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
        juju.deploy(tls_app, channel="1/stable")
    else:
        logging.info(f"{tls_app} already deployed, skipping deployment.")

    juju.wait(
        lambda status: status.apps[tls_app].is_active,
        timeout=10 * 60,
    )
    return tls_app


@pytest.fixture(scope="module")
def dovecot_charm_dual_unit(
    charm: str,
    juju: jubilant.Juju,
    tls_charm: str,
) -> str:
    """Build and deploy the charm."""
    logging.info(f"Checking for existing application {APP_NAME}...")
    luks_key = secrets.token_hex(16)

    if not juju.status().apps.get(APP_NAME):
        logging.info(f"Application {APP_NAME} not found, proceeding with deployment.")

        secret_id = juju.cli("add-secret", "dovecot-luks-key", f"key={luks_key}").strip()
        logging.info(f"Created LUKS secret: {secret_id}")

        config = {
            "mailname": MAILNAME,
            "postmaster-address": f"postmaster@{MAILNAME}",
            "primary-unit": f"{APP_NAME}/0",
            "luks-auto-provisioning": True,
            "luks-key": secret_id,
        }
        charm_path = charm if charm.startswith(("./", "/")) else f"./{charm}"
        # Deploy the primary unit only; the second unit is added after the primary
        # is fully active to avoid concurrent install load and peer-relation races.
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
    except jubilant.CLIError:
        logging.info("TLS relation already there...")

    logging.info("Waiting for primary unit to be active...")
    juju.wait(
        lambda status: jubilant.all_active(status, APP_NAME, tls_charm),
        timeout=10 * 60,
    )

    if len(juju.status().apps[APP_NAME].units) < 2:
        logging.info("Adding the second unit...")
        juju.add_unit(APP_NAME, num_units=1)

    def two_units_active(status):
        app = status.apps.get(APP_NAME)
        if not app or len(app.units) < 2:
            return False
        return jubilant.all_active(status)

    logging.info("Waiting for 2 units to be active...")
    juju.wait(two_units_active, timeout=10 * 60)
    return APP_NAME


@pytest.fixture()
def gdpr_test_user(juju: jubilant.Juju, dovecot_charm: str):
    """Create a GDPR test user with one message; tear down after the test."""
    unit_name = f"{dovecot_charm}/0"
    setup_gdpr_test_user(juju, unit_name, GDPR_TEST_USER, GDPR_TEST_PASSWORD)
    yield unit_name, GDPR_TEST_USER
    teardown_gdpr_test_user(juju, unit_name, GDPR_TEST_USER)
    juju.exec(f"rm -f {GDPR_ARCHIVE_DIR}/{GDPR_TEST_USER}.tar.gz", unit=unit_name)
    juju.exec(f"rm -rf {GDPR_ARCHIVE_DIR}/{GDPR_TEST_USER}", unit=unit_name)
    juju.exec(f"rm -f {GDPR_TAKEOUT_DIR}/{GDPR_TEST_USER}-takeout.tar.gz", unit=unit_name)


@pytest.fixture()
def create_mail_user_cleanup(juju: jubilant.Juju, dovecot_charm: str):
    """Tear down users created by create-mail-user tests."""
    unit_name = f"{dovecot_charm}/0"
    yield unit_name
    for user in (CREATE_MAIL_USER_TEST_USER, CREATE_MAIL_USER_TEST_MAILBOX):
        juju.exec(f"userdel -r {user} 2>/dev/null || true", unit=unit_name)
