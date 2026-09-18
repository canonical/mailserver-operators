# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import secrets
import socket
import typing

import jubilant
import pytest
from opcli.pytest_plugin import CharmPathList

from . import baculum
from .helpers import setup_gdpr_test_user, teardown_gdpr_test_user

logger = logging.getLogger(__name__)

APP_NAME = "dovecot"
# Charm mailname — must match the value passed in deploy config so tests can
# construct the correct SMTP recipient addresses (@example.com).
MAILNAME = "example.com"

DEPLOY_CONSTRAINTS = {"virt-type": "virtual-machine", "mem": "2048M", "cores": "2"}
BACKUP_SECRET_NAME = "dovecot-backup-key"  # nosec B105  # juju secret label, not a password
LUKS_SECRET_NAME = "dovecot-luks-key"  # nosec B105  # juju secret label, not a password

DOVECOT_OLD_APP = "dovecot-old"
DOVECOT_OLD_REVISION = 17
DOVECOT_OLD_CHANNEL = "latest/edge"

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

# S3 backend (microceph radosgw) is provisioned on the runner host by the spread
# prepare script tests/integration/s3-installation.sh.
S3_ACCESS_KEY = "my-lovely-key"
S3_SECRET_KEY = "this-is-very-secret"  # nosec B105
S3_BUCKET = "bacula"
S3_RGW_PORT = 7480


def _get_charm_path(request: pytest.FixtureRequest) -> str:
    """Resolve the Dovecot charm path only when deployment is required."""
    charm_paths = typing.cast(dict[str, CharmPathList], request.getfixturevalue("charm_paths"))
    return charm_paths["dovecot"].path


def _host_ip() -> typing.Optional[str]:
    """Return the host's primary outbound IP, reachable from juju units."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return None


def _deploy_dovecot(
    juju: jubilant.Juju,
    app: str,
    charm: str,
    tls_charm: str,
    fd_app: str,
    backup_secret: str,
    luks_secret: str,
    *,
    channel: str | None = None,
    revision: int | None = None,
) -> None:
    """Deploy a Dovecot app and wire up LUKS, TLS, backup secret, and Bacula fd."""
    if not juju.status().apps.get(app):
        juju.deploy(
            charm,
            app=app,
            channel=channel,
            revision=revision,
            config={
                "mailname": MAILNAME,
                "postmaster-address": f"postmaster@{MAILNAME}",
                "primary-unit": f"{app}/0",
                "luks-auto-provisioning": True,
            },
            constraints=DEPLOY_CONSTRAINTS,
        )
    juju.grant_secret(LUKS_SECRET_NAME, app)
    juju.grant_secret(BACKUP_SECRET_NAME, app)
    juju.config(app, {"luks-key": luks_secret, "backup-encryption-key": backup_secret})
    try:
        juju.integrate(f"{app}:certificates", f"{tls_charm}:certificates")
    except jubilant.CLIError:
        logging.info("TLS relation already present for %s", app)
    for endpoint in ("juju-info", "backup"):
        try:
            juju.integrate(f"{app}:{endpoint}", f"{fd_app}:{endpoint}")
        except jubilant.CLIError:
            logging.info("%s relation already present for %s", endpoint, app)


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


@pytest.fixture(scope="module")
def dovecot_charm(
    juju: jubilant.Juju,
    request: pytest.FixtureRequest,
    tls_charm: str,
    backup_secret: str,
    bacula_fd: str,
    luks_secret: str,
) -> str:
    """Build and deploy the charm."""
    charm = _get_charm_path(request)
    charm_path = charm if charm.startswith(("./", "/")) else f"./{charm}"
    _deploy_dovecot(juju, APP_NAME, charm_path, tls_charm, bacula_fd, backup_secret, luks_secret)
    juju.wait(
        lambda status: jubilant.all_active(status, APP_NAME, tls_charm),
        timeout=10 * 60,
    )
    return APP_NAME


@pytest.fixture(scope="module")
def dovecot_charm_manual_storage(
    juju: jubilant.Juju,
    request: pytest.FixtureRequest,
    tls_charm: str,
) -> str:
    """Build and deploy the charm."""
    charm_name = f"{APP_NAME}-manual"
    logging.info(f"Checking for existing application {charm_name}...")

    if not juju.status().apps.get(charm_name):
        logging.info(f"Application {charm_name} not found, proceeding with deployment.")

        charm = _get_charm_path(request)
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
def backup_secret(juju: jubilant.Juju) -> str:
    """Create the backup encryption secret shared by all Dovecot deployments."""
    backup_key = secrets.token_hex(16)
    return juju.add_secret(BACKUP_SECRET_NAME, {"backup-key": backup_key})


@pytest.fixture(scope="module")
def luks_secret(juju: jubilant.Juju) -> str:
    """Create the LUKS key secret shared by all Dovecot deployments."""
    luks_key = secrets.token_hex(16)
    return juju.add_secret(LUKS_SECRET_NAME, {"key": luks_key})


@pytest.fixture(scope="module")
def bacula_fd(juju: jubilant.Juju) -> str:
    fd_app = "bacula-fd"
    if fd_app not in juju.status().apps:
        juju.deploy(fd_app, channel="latest/edge")
    return fd_app


@pytest.fixture(scope="module")
def dovecot_old(
    juju: jubilant.Juju,
    tls_charm: str,
    bacula_fd: str,
    backup_secret: str,
    luks_secret: str,
) -> str:
    """Deploy a published, backup-capable revision of the Dovecot charm."""
    _deploy_dovecot(
        juju,
        DOVECOT_OLD_APP,
        "dovecot",
        tls_charm,
        bacula_fd,
        backup_secret,
        luks_secret,
        channel=DOVECOT_OLD_CHANNEL,
        revision=DOVECOT_OLD_REVISION,
    )

    juju.wait(
        lambda status: jubilant.all_active(status, DOVECOT_OLD_APP, tls_charm),
        timeout=20 * 60,
    )
    return DOVECOT_OLD_APP


@pytest.fixture(scope="session")
def s3_address(pytestconfig: pytest.Config) -> str:
    """Provide the S3 service IP address used in integration tests.

    Defaults to the host's primary outbound IP so that juju units can reach the
    microceph radosgw provisioned on the runner host by the s3-installation.sh
    spread prepare script. Can be overridden with --s3-address.
    """
    address = pytestconfig.getoption("--s3-address", default=None) or _host_ip()
    if not address:
        raise RuntimeError("Could not determine S3 address; pass --s3-address explicitly")
    return address


@pytest.fixture(scope="module")
def bacula_server(juju: jubilant.Juju, bacula_fd: str, s3_address: str) -> str:
    """Deploy and integrate the full Bacula server stacks."""
    server_app = "bacula-server"
    database_app = "bacula-database"

    if server_app not in juju.status().apps:
        logging.info("Deploying bacula-server...")
        juju.deploy(server_app, channel="latest/edge")
    if database_app not in juju.status().apps:
        logging.info("Deploying bacula-database (postgresql)...")
        juju.deploy("postgresql", database_app, channel="14/stable")
    if "s3-integrator" not in juju.status().apps:
        logging.info("Deploying s3-integrator...")
        juju.deploy("s3-integrator")

    juju.wait(lambda status: jubilant.all_agents_idle(status, "s3-integrator"), timeout=600)

    juju.config(
        "s3-integrator",
        {
            "endpoint": f"http://{s3_address}:{S3_RGW_PORT}",
            "bucket": S3_BUCKET,
            "s3-uri-style": "path",
        },
    )
    juju.run(
        unit="s3-integrator/0",
        action="sync-s3-credentials",
        params={"access-key": S3_ACCESS_KEY, "secret-key": S3_SECRET_KEY},
    )

    for endpoint in ("bacula-database", "s3-integrator", bacula_fd):
        try:
            juju.integrate(server_app, endpoint)
        except jubilant.CLIError:
            logging.info(f"{server_app}:{endpoint} relation already present")

    juju.wait(jubilant.all_active, timeout=20 * 60)
    return server_app


@pytest.fixture(scope="module", name="baculum")
def baculum_client(juju: jubilant.Juju, bacula_server: str) -> baculum.Baculum:
    """Initialize a Baculum API client against the bacula-server unit."""
    unit_name = next(iter(juju.status().apps[bacula_server].units))
    username = "test-admin"
    password = juju.run(
        unit_name,
        "create-api-user",
        params={"username": username},
        wait=60,
    ).results["password"]
    address = next(iter(juju.status().apps[bacula_server].units.values())).public_address
    return baculum.Baculum(f"http://{address}:9096/api/v2", username=username, password=password)


@pytest.fixture(scope="module")
def dovecot_charm_dual_unit(
    juju: jubilant.Juju,
    request: pytest.FixtureRequest,
    tls_charm: str,
) -> str:
    """Build and deploy the charm."""
    logging.info(f"Checking for existing application {APP_NAME}...")
    luks_key = secrets.token_hex(16)

    if not juju.status().apps.get(APP_NAME):
        logging.info(f"Application {APP_NAME} not found, proceeding with deployment.")

        charm = _get_charm_path(request)
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
