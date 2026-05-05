# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for charm integration tests."""

import logging
import pathlib
import typing
from collections.abc import Generator

import jubilant
import pytest

logger = logging.getLogger(__name__)

OPENDKIM_SNAP_DIR = pathlib.Path(__file__).resolve().parents[3] / "opendkim-snap"


@pytest.fixture(scope="module", name="opendkim_charm")
def opendkim_charm_fixture(pytestconfig: pytest.Config):
    """Get value from parameter charm-file."""
    charm = pytestconfig.getoption("--charm-file")
    use_existing = pytestconfig.getoption("--use-existing", default=False)
    if not use_existing:
        assert charm, "--charm-file must be set"
    return charm


@pytest.fixture(scope="module", name="opendkim_app")
def deploy_opendkim_fixture(
    opendkim_charm: str,
    juju: jubilant.Juju,
) -> str:
    """Deploy opendkim and replace the store snap with the locally-built one."""
    deploy_opendkim_name = "opendkim"

    if not juju.status().apps.get(deploy_opendkim_name):
        juju.deploy(
            f"./{opendkim_charm}",
            deploy_opendkim_name,
        )
        # Wait for the charm to settle (blocked because not configured, or waiting).
        juju.wait(
            lambda status: (
                status.apps[deploy_opendkim_name].is_blocked
                or status.apps[deploy_opendkim_name].app_status.current == "waiting"
            ),
            timeout=10 * 60,
        )

    _replace_snap_on_unit(juju, deploy_opendkim_name)

    return deploy_opendkim_name


def _configure_dns(juju: jubilant.Juju, unit_name: str) -> None:
    """Configure DNS on the machine so opendkim.testkey can resolve DKIM TXT records.

    Args:
        juju: The Juju client.
        unit_name: The unit name.
    """
    dns_setup = "echo 'nameserver 8.8.8.8' | sudo tee /etc/resolv.conf.tail > /dev/null && sudo chattr -i /etc/resolv.conf 2>/dev/null || true && sudo cat /etc/resolv.conf.tail >> /etc/resolv.conf || true"
    juju.exec(dns_setup, unit=unit_name)
    logger.info("Configured DNS on unit %s", unit_name)


def _replace_snap_on_unit(juju: jubilant.Juju, app_name: str) -> None:
    """Replace the store-installed opendkim snap with the locally-built one.

    Finds the snap artifact built by setup-integration-tests.sh, copies it
    to each unit's machine, and installs it with --dangerous.

    Args:
        juju: The Juju client.
        app_name: The application name.
    """
    snap_files = sorted(OPENDKIM_SNAP_DIR.glob("opendkim_*.snap"))
    if not snap_files:
        logger.warning(
            "No locally-built opendkim snap found in %s; skipping replacement", OPENDKIM_SNAP_DIR
        )
        return

    snap_path = snap_files[-1]
    snap_name = snap_path.name
    logger.info("Replacing opendkim snap on units with %s", snap_path)

    status = juju.status()
    for unit_name, unit in status.apps[app_name].units.items():
        machine = unit.machine
        _configure_dns(juju, unit_name)
        # Copy snap to the machine
        juju.scp(snap_path, f"{unit_name}:/tmp/{snap_name}")
        # Install with --dangerous, replacing the store version
        juju.exec(
            "sudo",
            "snap",
            "install",
            "--dangerous",
            f"/tmp/{snap_name}",  # nosec B108 — Juju copies resources to /tmp
            unit=unit_name,
        )
        logger.info("Replaced opendkim snap on unit %s (machine %s)", unit_name, machine)


@pytest.fixture(scope="module", name="smtp_relay_app")
def deploy_smtp_relay_fixture(
    opendkim_app: str,
    juju: jubilant.Juju,
) -> str:
    """Deploy smtp-relay and integrate with dkim."""
    smtp_relay_app_name = "smtp-relay"

    if not juju.status().apps.get(smtp_relay_app_name):
        juju.deploy(smtp_relay_app_name, smtp_relay_app_name)
        juju.integrate(smtp_relay_app_name, opendkim_app)
        juju.wait(
            lambda status: (
                jubilant.all_active(status, smtp_relay_app_name)
                and jubilant.all_blocked(status, opendkim_app)
            ),
            timeout=10 * 60,
        )
    return smtp_relay_app_name


@pytest.fixture(scope="session", name="juju")
def juju_fixture(request: pytest.FixtureRequest) -> Generator[jubilant.Juju, None, None]:
    """Pytest fixture that wraps :meth:`jubilant.with_model`."""

    def _show_debug_log(juju: jubilant.Juju):
        """Print debug logs."""
        if request.session.testsfailed:
            log = juju.debug_log(limit=1000)
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
        juju.wait_timeout = 10 * 60
        juju.model_config({"automatically-retry-hooks": True})
        yield juju
        _show_debug_log(juju)
        return
