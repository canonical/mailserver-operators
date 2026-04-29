# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import contextlib
import logging
import time
from secrets import token_hex

import jubilant
import pytest


def test_luks_storage_auto_provisioning(juju: jubilant.Juju, dovecot_charm: str):
    """Test automatic LUKS setup with user-supplied secret key."""
    status = juju.status()
    unit_name = next(iter(status.apps[dovecot_charm].units.keys()))
    logging.info(f"Targeting unit: {unit_name}")

    logging.info("Waiting for charm to be active with storage attached...")
    juju.wait(jubilant.all_active, timeout=10 * 60)

    logging.info("Verifying LUKS setup...")
    juju.exec("ls -l /dev/mapper/mail-data", unit=unit_name)
    juju.exec("cryptsetup status mail-data", unit=unit_name)

    mount_output = juju.exec("mount | grep /srv/mail", unit=unit_name)
    logging.info(f"Mount: {mount_output}")
    assert "/dev/mapper/mail-data" in mount_output.stdout
    assert "/srv/mail" in mount_output.stdout

    juju.exec("touch /srv/mail/test_storage_write", unit=unit_name)
    juju.exec("rm /srv/mail/test_storage_write", unit=unit_name)

    logging.info("Verifying fstab configuration...")
    fstab = juju.exec("cat /etc/fstab", unit=unit_name)
    assert "/dev/mapper/mail-data" in fstab.stdout
    assert "/srv/mail" in fstab.stdout
    logging.info(
        f"fstab entry found: {[line for line in fstab.stdout.splitlines() if 'mail-data' in line]}"
    )

    logging.info("Automatic LUKS storage verification passed.")


def test_luks_storage_manual_provisioning(juju: jubilant.Juju, dovecot_charm_manual_storage: str):
    """Test manual LUKS setup with pre-formatted LUKS device."""
    luks_device_name = "mail-data"
    luks_passphrase = token_hex(16)
    unit_name = f"{dovecot_charm_manual_storage}/0"

    # Wait for unit to start and storage to attach (but not active - it will be blocked until we set up LUKS)
    logging.info("Waiting for unit and storage to be attached...")
    max_attempts = 30
    attempts = 0
    dev_path = None

    while attempts < max_attempts and dev_path is None:
        try:
            status = juju.status()
            # Check if storage is attached
            if not status.storage or not getattr(status.storage, "storage", None):
                logging.info("Waiting for storage to attach...")
                attempts += 1
                time.sleep(5)
                continue

            for storage_id, storage_info in status.storage.storage.items():
                if not storage_id.startswith("mail-data/"):
                    continue

                if storage_location := storage_info.attachments.units.get(unit_name):
                    dev_path = storage_location.location
                    logging.info(f"Found attached storage at {dev_path} from {storage_id}")
                    break

            if dev_path is None:
                logging.info("Storage not yet attached to unit...")
                attempts += 1
                time.sleep(5)
        except Exception as e:
            logging.info(f"Fetching status: {e}, retrying...")
            attempts += 1
            time.sleep(5)

    if not dev_path:
        pytest.fail(
            f"Could not find storage device after {max_attempts} attempts. dev_path={dev_path}, unit_name={unit_name}"
        )

    logging.info(f"Using device: {dev_path} on unit: {unit_name}")

    # Format device with LUKS manually
    logging.info(f"Formatting {dev_path} with LUKS...")
    format_cmd = f"echo -n '{luks_passphrase}' | cryptsetup luksFormat {dev_path} --batch-mode -"
    juju.exec(format_cmd, unit=unit_name)

    # Open the LUKS device
    logging.info(f"Opening LUKS device as {luks_device_name}...")
    open_cmd = f"echo -n '{luks_passphrase}' | cryptsetup luksOpen {dev_path} {luks_device_name} -"
    juju.exec(open_cmd, unit=unit_name)

    # Create ext4 filesystem
    logging.info("Creating ext4 filesystem...")
    juju.exec(f"mkfs.ext4 -F /dev/mapper/{luks_device_name}", unit=unit_name)

    # Create mount point and mount
    logging.info("Mounting encrypted device...")
    juju.exec("mkdir -p /srv/mail", unit=unit_name)
    juju.exec(f"mount /dev/mapper/{luks_device_name} /srv/mail", unit=unit_name)

    # Configure crypttab and fstab for persistent mounting
    logging.info("Configuring crypttab...")
    juju.exec(
        f"echo '{luks_device_name} {dev_path} none luks' >> /etc/crypttab",
        unit=unit_name,
    )

    logging.info("Configuring fstab...")
    juju.exec(
        f"echo '/dev/mapper/{luks_device_name} /srv/mail ext4 defaults 0 2' >> /etc/fstab",
        unit=unit_name,
    )

    # Now that storage is properly set up, trigger charm reconciliation and wait for active
    logging.info("Triggering charm reconciliation...")
    juju.config(dovecot_charm_manual_storage, {"mailname": "example1.com"})

    logging.info("Waiting for charm to become active...")
    juju.wait(jubilant.all_active, timeout=5 * 60)

    # Verify LUKS device status
    logging.info("Verifying LUKS device is properly configured...")
    cryptsetup_status = juju.exec(f"cryptsetup status {luks_device_name}", unit=unit_name)
    logging.info(f"Cryptsetup status: {cryptsetup_status.stdout}")
    assert (
        "active" in cryptsetup_status.stdout.lower()
        or "is active" in cryptsetup_status.stdout.lower()
    )

    # Verify mount point
    logging.info("Verifying mount point...")
    mount_output = juju.exec("mount | grep /srv/mail", unit=unit_name)
    logging.info(f"Mount: {mount_output}")
    assert f"/dev/mapper/{luks_device_name}" in mount_output.stdout
    assert "/srv/mail" in mount_output.stdout

    # Test write access to verify filesystem is properly mounted
    logging.info("Testing write access to mounted filesystem...")
    juju.exec("touch /srv/mail/test_manual_luks_write", unit=unit_name)
    juju.exec("rm /srv/mail/test_manual_luks_write", unit=unit_name)

    # Verify fstab configuration
    logging.info("Verifying fstab configuration...")
    fstab = juju.exec("cat /etc/fstab", unit=f"{dovecot_charm_manual_storage}/0")
    assert f"/dev/mapper/{luks_device_name}" in fstab.stdout
    assert "/srv/mail" in fstab.stdout
    logging.info(
        f"fstab entry found: {[line for line in fstab.stdout.splitlines() if luks_device_name in line]}"
    )

    logging.info("Manual LUKS storage verification passed.")

    # Cleanup
    logging.info("Cleaning up deployment...")
    juju.remove_application(dovecot_charm_manual_storage)


def test_data_persists_across_restart(juju: jubilant.Juju, dovecot_charm: str):
    """Data written to /srv/mail survives a VM reboot and charm re-settle."""
    unit_name = f"{dovecot_charm}/0"
    sentinel = "/srv/mail/persistence_test_sentinel"

    # Write sentinel file and confirm it exists before reboot
    juju.exec(f"touch {sentinel}", unit=unit_name)
    juju.exec(f"test -f {sentinel}", unit=unit_name)
    logging.info(f"Sentinel written: {sentinel}")

    # Reboot — SSH connection drops before command returns, all three are expected
    logging.info("Rebooting unit...")
    with contextlib.suppress(jubilant.CLIError, jubilant.TaskError, TimeoutError):
        juju.exec("sudo reboot", unit=unit_name)

    # Wait for charm to re-settle after reboot
    logging.info("Waiting for charm to re-settle...")
    # After reboot the Juju controller connection drops while the VM restarts.
    # Poll juju status until it succeeds before calling juju.wait(), otherwise
    # jubilant raises CLIError immediately on the first status attempt.
    deadline = time.monotonic() + 10 * 60
    while time.monotonic() < deadline:
        try:
            juju.status()
            break
        except jubilant.CLIError:
            time.sleep(5)
    juju.wait(jubilant.all_active, timeout=10 * 60)

    # After reboot the Juju storage API may not yet be re-provisioned when the
    # start hook fires; the charm defers and retries until LUKS open + mount
    # succeeds.  Poll until /srv/mail is mounted.
    logging.info("Waiting for /srv/mail to be mounted post-reboot...")
    deadline = time.monotonic() + 120
    mounted = False
    while time.monotonic() < deadline:
        try:
            juju.exec("mountpoint -q /srv/mail", unit=unit_name)
            mounted = True
            break
        except (jubilant.CLIError, jubilant.TaskError):
            time.sleep(5)
    assert mounted, "/srv/mail was not mounted within 120s of active status"

    # Assert storage still mounted
    mount_output = juju.exec("mount | grep /srv/mail", unit=unit_name)
    assert "/dev/mapper/mail-data" in mount_output.stdout
    assert "/srv/mail" in mount_output.stdout
    logging.info(f"Mount verified: {mount_output.stdout.strip()}")

    # Assert LUKS container still open
    juju.exec("cryptsetup status mail-data", unit=unit_name)
    logging.info("LUKS container open after reboot")

    # Assert sentinel still present — data survived
    juju.exec(f"test -f {sentinel}", unit=unit_name)
    logging.info("Sentinel file present after reboot — data persisted")
