# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import time
from secrets import token_hex

import jubilant
import pytest


def test_luks_storage_automatic(juju: jubilant.Juju, dovecot_charm: str):
    """Test automatic LUKS setup with keyfile."""
    status = juju.status()
    unit_name = next(iter(status.apps[dovecot_charm].units.keys()))
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


def test_luks_storage_manual(juju: jubilant.Juju, dovecot_charm_manual: str):
    """Test manual LUKS setup with pre-formatted LUKS device."""
    luks_device_name = "mail-data"
    luks_passphrase = token_hex(16)

    # Wait for unit to start and storage to attach (but not active - it will be blocked until we set up LUKS)
    logging.info("Waiting for unit and storage to be attached...")
    max_attempts = 30
    attempts = 0
    dev_path = None

    while attempts < max_attempts and dev_path is None:
        try:
            status = juju.status()
            # Check if storage is attached
            if not status.storage or "mail-data/0" not in status.storage.storage:
                logging.info("Waiting for storage to attach...")
                attempts += 1
                time.sleep(5)
                continue

            storage_info = status.storage.storage["mail-data/0"]
            if storage_location := storage_info.attachments.units.get(f"{dovecot_charm_manual}/0"):
                dev_path = storage_location.location
                logging.info(f"Found attached storage at {dev_path}")
            else:
                logging.info("Storage not yet attached to unit...")
                attempts += 1
                time.sleep(5)
        except Exception as e:
            logging.info(f"Fetching status: {e}, retrying...")
            attempts += 1
            time.sleep(5)

    if not dev_path or not f"{dovecot_charm_manual}/0":
        pytest.fail(
            f"Could not find storage device after {max_attempts} attempts. dev_path={dev_path}, unit_name={f'{dovecot_charm_manual}/0'}"
        )

    logging.info(f"Using device: {dev_path} on unit: {f'{dovecot_charm_manual}/0'}")

    # Format device with LUKS manually
    logging.info(f"Formatting {dev_path} with LUKS...")
    format_cmd = f"echo -n '{luks_passphrase}' | cryptsetup luksFormat {dev_path} --batch-mode -"
    juju.exec(format_cmd, unit=f"{dovecot_charm_manual}/0")

    # Open the LUKS device
    logging.info(f"Opening LUKS device as {luks_device_name}...")
    open_cmd = f"echo -n '{luks_passphrase}' | cryptsetup luksOpen {dev_path} {luks_device_name} -"
    juju.exec(open_cmd, unit=f"{dovecot_charm_manual}/0")

    # Create ext4 filesystem
    logging.info("Creating ext4 filesystem...")
    juju.exec(f"mkfs.ext4 -F /dev/mapper/{luks_device_name}", unit=f"{dovecot_charm_manual}/0")

    # Create mount point and mount
    logging.info("Mounting encrypted device...")
    juju.exec("mkdir -p /srv/mail", unit=f"{dovecot_charm_manual}/0")
    juju.exec(f"mount /dev/mapper/{luks_device_name} /srv/mail", unit=f"{dovecot_charm_manual}/0")

    # Configure crypttab and fstab for persistent mounting
    logging.info("Configuring crypttab...")
    juju.exec(
        f"echo '{luks_device_name} {dev_path} none luks' >> /etc/crypttab",
        unit=f"{dovecot_charm_manual}/0",
    )

    logging.info("Configuring fstab...")
    juju.exec(
        f"echo '/dev/mapper/{luks_device_name} /srv/mail ext4 defaults 0 2' >> /etc/fstab",
        unit=f"{dovecot_charm_manual}/0",
    )

    # Now that storage is properly set up, trigger charm reconciliation and wait for active
    logging.info("Triggering charm reconciliation...")
    juju.config(dovecot_charm_manual, {"primary-unit": f"{dovecot_charm_manual}/0"})

    logging.info("Waiting for charm to become active...")
    juju.wait(jubilant.all_active, timeout=300)

    # Verify LUKS device status
    logging.info("Verifying LUKS device is properly configured...")
    cryptsetup_status = juju.exec(
        f"cryptsetup status {luks_device_name}", unit=f"{dovecot_charm_manual}/0"
    )
    logging.info(f"Cryptsetup status: {cryptsetup_status.stdout}")
    assert (
        "active" in cryptsetup_status.stdout.lower()
        or "is active" in cryptsetup_status.stdout.lower()
    )

    # Verify mount point
    logging.info("Verifying mount point...")
    mount_output = juju.exec("mount | grep /srv/mail", unit=f"{dovecot_charm_manual}/0")
    logging.info(f"Mount: {mount_output}")
    assert f"/dev/mapper/{luks_device_name}" in mount_output.stdout
    assert "/srv/mail" in mount_output.stdout

    # Test write access to verify filesystem is properly mounted
    logging.info("Testing write access to mounted filesystem...")
    juju.exec("touch /srv/mail/test_manual_luks_write", unit=f"{dovecot_charm_manual}/0")
    juju.exec("rm /srv/mail/test_manual_luks_write", unit=f"{dovecot_charm_manual}/0")

    # Verify crypttab configuration
    logging.info("Verifying crypttab configuration...")
    crypttab = juju.exec("cat /etc/crypttab", unit=f"{dovecot_charm_manual}/0")
    assert luks_device_name in crypttab.stdout
    assert dev_path in crypttab.stdout
    assert "luks" in crypttab.stdout
    logging.info(f"crypttab configured correctly: {crypttab.stdout}")

    # Verify fstab configuration
    logging.info("Verifying fstab configuration...")
    fstab = juju.exec("cat /etc/fstab", unit=f"{dovecot_charm_manual}/0")
    assert f"/dev/mapper/{luks_device_name}" in fstab.stdout
    assert "/srv/mail" in fstab.stdout
    logging.info(
        f"fstab entry found: {[line for line in fstab.stdout.splitlines() if luks_device_name in line]}"
    )

    logging.info("Manual LUKS storage verification passed.")

    # Cleanup
    logging.info("Cleaning up deployment...")
    juju.remove_application(dovecot_charm_manual)
