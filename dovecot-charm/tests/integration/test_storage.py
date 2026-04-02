# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import jubilant


def test_luks_storage_automatic(juju: jubilant.Juju, dovecot_charm: str):
    """Test automatic LUKS setup with keyfile."""
    status = juju.status()
    unit_name = list(status.apps[dovecot_charm].units.keys())[0]
    logging.info(f"Targeting unit: {unit_name}")

    logging.info("Waiting for charm to be active with storage attached...")
    juju.wait(jubilant.all_active, timeout=600)

    logging.info("Verifying keyfile exists...")
    keyfile_check = juju.exec("ls", "-l", "/etc/dovecot-charm.key", unit=unit_name)
    logging.info(f"Keyfile: {keyfile_check}")

    perms = juju.exec("stat", "-c", "'%a'", "/etc/dovecot-charm.key", unit=unit_name)
    assert perms.stdout.strip() == "400", f"Keyfile permissions should be 400, got {perms.stdout}"

    logging.info("Verifying LUKS setup...")
    juju.exec("ls -l /dev/mapper/mail-data", unit=unit_name)
    juju.exec("cryptsetup status mail-data", unit=unit_name)

    mount_output = juju.exec("mount | grep /srv/mail", unit=unit_name)
    logging.info(f"Mount: {mount_output}")
    assert "/dev/mapper/mail-data" in mount_output.stdout
    assert "/srv/mail" in mount_output.stdout

    juju.exec("touch /srv/mail/test_storage_write", unit=unit_name)
    juju.exec("rm /srv/mail/test_storage_write", unit=unit_name)

    logging.info("Verifying crypttab configuration...")
    crypttab = juju.exec("cat /etc/crypttab", unit=unit_name)
    assert "mail-data" in crypttab.stdout
    assert "/etc/dovecot-charm.key" in crypttab.stdout
    assert "luks" in crypttab.stdout
    logging.info(f"crypttab: {crypttab.stdout}")

    logging.info("Verifying fstab configuration...")
    fstab = juju.exec("cat /etc/fstab", unit=unit_name)
    assert "/dev/mapper/mail-data" in fstab.stdout
    assert "/srv/mail" in fstab.stdout
    logging.info(
        f"fstab entry found: {[line for line in fstab.stdout.splitlines() if 'mail-data' in line]}"
    )

    logging.info("Automatic LUKS storage verification passed.")
