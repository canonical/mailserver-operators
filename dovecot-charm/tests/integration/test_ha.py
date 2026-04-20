# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from typing import cast

import jubilant
import pytest


def _get_unit_hostname(status, app_name, unit_name):
    """Helper to get unit hostname from status."""
    try:
        machine = status.apps[app_name].units[unit_name].machine
        return status.machines[machine].hostname
    except KeyError:
        logging.error(f"Unit {unit_name} not found in status.")
        return None


@pytest.mark.timeout(1800)
def test_ha_failover(juju, dovecot_charm):
    status = juju.status()
    if len(status.apps[dovecot_charm].units) < 2:
        logging.info("Adding the second unit...")
        juju.add_unit(dovecot_charm, num_units=1)

    def two_units_active(status):
        app = status.apps.get(dovecot_charm)
        if not app:
            return False
        if len(app.units) < 2:
            return False
        return jubilant.all_active(status)

    logging.info("Waiting for 2 units to be active...")
    juju.wait(two_units_active, timeout=600)

    status = juju.status()
    units = list(status.apps[dovecot_charm].units.keys())
    units.sort(key=lambda x: int(x.split("/")[-1]))

    primary = units[0]
    secondary = units[1]

    logging.info(f"Primary: {primary}, Secondary: {secondary}")

    juju.config(dovecot_charm, {"primary-unit": primary})
    juju.wait(jubilant.all_active, timeout=300)

    logging.info("Verifying SSH key exchange...")

    cmd = "cat /root/.ssh/authorized_keys | wc -l"

    result_primary = juju.exec(cmd, unit=primary)
    logging.info(f"Primary authorized_keys count: {result_primary.stdout.strip()}")
    assert int(result_primary.stdout.strip()) >= 1

    result_secondary = juju.exec(cmd, unit=secondary)
    logging.info(f"Secondary authorized_keys count: {result_secondary.stdout.strip()}")
    assert int(result_secondary.stdout.strip()) >= 1

    logging.info("Verifying sync script on Primary...")

    status = juju.status()
    secondary_hostname = _get_unit_hostname(status, dovecot_charm, secondary)
    logging.info(f"Secondary hostname: {secondary_hostname}")

    script_path = "/usr/local/bin/sync-to-secondary.sh"
    cmd = f"cat {script_path}"
    script_content = juju.exec(cmd, unit=primary).stdout

    logging.info(f"Sync script content on Primary:\n{script_content}")
    assert secondary_hostname in script_content, (
        "Secondary hostname not found in sync script on Primary"
    )

    logging.info("Running force-sync on Primary...")

    # Create a test Maildir so the sync script has something to sync.
    # Without this, the script exits 1 because no Maildir directories exist.
    juju.exec("mkdir -p /srv/mail/testuser/Maildir/{new,cur,tmp}", unit=primary)

    task = juju.run(unit=primary, action="force-sync", wait=100)
    assert task.status == "completed"
    assert task.results["result"] == "Sync completed successfully"

    with pytest.raises(jubilant.TaskError) as exc_info:
        juju.run(unit=secondary, action="force-sync", wait=100)
    assert cast(jubilant.TaskError, exc_info.value).task.status == "failed"
    logging.info("force-sync on Secondary correctly failed.")

    logging.info("HA Failover test passed.")
