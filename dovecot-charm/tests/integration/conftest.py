# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import typing

import jubilant
import pytest
import requests

logger = logging.getLogger(__name__)

APP_NAME = "dovecot-charm"


@pytest.fixture(scope="session", name="juju")
def juju_fixture(request: pytest.FixtureRequest):
    """Pytest fixture that wraps jubilant.with_model."""
    use_existing = request.config.getoption("--use-existing", default=False)
    if use_existing:
        juju = jubilant.Juju()
        juju.model_config()
        yield juju
        return

    model = request.config.getoption("--model")
    if model:
        juju = jubilant.Juju(model=model)
        juju.model_config()
        yield juju
        return

    keep_models = typing.cast(bool, request.config.getoption("--keep-models"))
    with jubilant.temp_model(keep=keep_models) as juju:
        juju.wait_timeout = 10 * 60
        juju.model_config()
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
        )

    logging.info("Waiting for active status...")
    juju.wait(jubilant.all_active, timeout=10 * 60)
    return APP_NAME


@pytest.fixture(scope="module", name="session_with_retry")
def session_with_retry_fixture():
    """Return a requests session."""
    session = requests.Session()
    return session


@pytest.fixture(scope="module", name="loki_app_name")
def loki_app_name_fixture() -> str:
    """Return the name of the loki application deployed for tests."""
    return "loki-k8s"


@pytest.fixture(scope="module", name="grafana_app_name")
def grafana_app_name_fixture() -> str:
    """Return the name of the grafana application deployed for tests."""
    return "grafana-k8s"


@pytest.fixture(scope="module", name="prometheus_app_name")
def prometheus_app_name_fixture() -> str:
    """Return the name of the prometheus application deployed for tests."""
    return "prometheus-k8s"


@pytest.fixture(scope="module", name="prometheus_app")
def deploy_prometheus_fixture(
    juju: jubilant.Juju,
    prometheus_app_name: str,
) -> str:
    """Deploy prometheus."""
    if not juju.status().apps.get(prometheus_app_name):
        juju.deploy(
            prometheus_app_name,
            channel="1/stable",
            revision=129,
            base="ubuntu@20.04",
            trust=True,
        )
    juju.wait(
        lambda status: status.apps[prometheus_app_name].is_active,
        error=jubilant.any_blocked,
        timeout=6 * 60,
    )
    return prometheus_app_name


@pytest.fixture(scope="module", name="loki_app")
def deploy_loki_fixture(
    juju: jubilant.Juju,
    loki_app_name: str,
) -> str:
    """Deploy loki."""
    if not juju.status().apps.get(loki_app_name):
        juju.deploy(loki_app_name, channel="1/stable", trust=True)
    juju.wait(
        lambda status: status.apps[loki_app_name].is_active,
        error=jubilant.any_blocked,
    )
    return loki_app_name


@pytest.fixture(scope="module", name="cos_apps")
def deploy_cos_fixture(
    juju: jubilant.Juju,
    loki_app: str,
    prometheus_app: str,
    grafana_app_name: str,
) -> typing.Dict[str, str]:
    """Deploy the cos applications."""
    if not juju.status().apps.get(grafana_app_name):
        juju.deploy(
            grafana_app_name,
            channel="1/stable",
            revision=82,
            base="ubuntu@20.04",
            trust=True,
        )
        juju.wait(
            lambda status: jubilant.all_active(status, loki_app, prometheus_app, grafana_app_name)
        )
        juju.integrate(
            f"{prometheus_app}:grafana-source",
            f"{grafana_app_name}:grafana-source",
        )
        juju.integrate(
            f"{loki_app}:grafana-source",
            f"{grafana_app_name}:grafana-source",
        )
    return {
        "loki_app": loki_app,
        "prometheus_app": prometheus_app,
        "grafana_app": grafana_app_name,
    }
