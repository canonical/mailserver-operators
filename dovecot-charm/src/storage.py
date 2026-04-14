# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Storage management for Dovecot charm."""

import logging
import os
import shutil
import stat
import subprocess  # nosec

from constants import MAIL_ROOT, MAPPER_NAME, MAPPER_PATH
from exceptions import StorageError
from utils import configure_file

logger = logging.getLogger(__name__)


def _mail_storage_mounted():
    """Return True if mail storage is mounted."""
    return os.path.ismount(MAIL_ROOT)


def ensure_storage_ready(charm) -> None:
    """Ensure mail storage is attached and LUKS-mounted if required.

    Raises:
        StorageError: If storage is not ready and charm should enter Blocked.
    """
    if not (dovecot_config := charm._get_dovecot_config()):
        return

    if not dovecot_config.manage_luks:
        if _mail_storage_mounted():
            return
        raise StorageError("mail-data not mounted; manage-luks disabled")

    if shutil.which("cryptsetup") is None:
        logger.warning("cryptsetup not installed, deferring storage setup")
        return

    storages = charm.model.storages["mail-data"]
    if not storages:
        logger.error("Storage attached but no location found")
        return
    dev_path = storages[0].location
    if not dev_path:
        logger.error("Storage attached but no location found")
        return

    try:
        setup_luks_storage(dovecot_config.luks_key, dev_path)
    except subprocess.CalledProcessError as e:
        logger.exception(f"Failed to setup LUKS storage: {e}")
        raise StorageError("Failed to setup LUKS storage") from e
    except RuntimeError as e:
        logger.exception(f"Storage validation failed: {e}")
        raise StorageError(str(e)) from e


def teardown_detaching_storage(charm) -> None:
    """Unmount and close LUKS device if storage is detaching."""
    sss = charm.model.storages.get("mail-data")
    if sss:
        return
    try:
        if not (dovecot_config := charm._get_dovecot_config()):
            logger.warning("Cannot determine if manage-luks is enabled during storage detachment")
            return
        if dovecot_config.manage_luks and _mail_storage_mounted():
            subprocess.run(["/usr/bin/umount", MAIL_ROOT], check=True)

        if os.path.exists("/dev/mapper/mail-data"):
            subprocess.run(["/usr/sbin/cryptsetup", "luksClose", "mail-data"], check=True)
    except subprocess.CalledProcessError as e:
        logger.exception(f"Failed to detach storage: {e}")


def setup_luks_storage(key: str, dev_path) -> None:
    """Set up LUKS encryption on a block device using the supplied passphrase.

    Idempotent: if MAIL_ROOT is already mounted, returns immediately.
    Otherwise validates the device, ensures a LUKS container exists and is
    open, ensures an ext4 filesystem exists inside it, and mounts it.

    Args:
        key: Plaintext passphrase used as the LUKS key.  Passed to cryptsetup
            via stdin so it is never written to disk or exposed in /proc.
        dev_path: Path to the block device to encrypt (e.g. ``/dev/sdb``).

    Raises:
        RuntimeError: If any step fails — see individual helpers for details.
    """
    if _mail_storage_mounted():
        logger.info("mail-data already mounted, skipping LUKS setup")
        return
    key_bytes = key.encode()
    _validate_block_device(dev_path)
    _ensure_luks_container(key_bytes, dev_path)
    _ensure_filesystem()
    _ensure_mounted()


def _validate_block_device(dev_path) -> None:
    """Confirm dev_path exists and is a block device.

    Raises:
        RuntimeError: If dev_path does not exist or is not a block device.
    """
    if not os.path.exists(dev_path):
        raise RuntimeError(f"Device {dev_path} does not exist")
    if not stat.S_ISBLK(os.stat(dev_path).st_mode):
        raise RuntimeError(f"{dev_path} is not a valid block device")


def _ensure_luks_container(key_bytes: bytes, dev_path) -> None:
    """Ensure dev_path is a LUKS container and is open at MAPPER_PATH.

    Formats with luksFormat if not already a LUKS device.
    Opens with cryptsetup open if MAPPER_PATH does not yet exist.

    Raises:
        RuntimeError: If luksFormat or cryptsetup open fails.
    """
    is_luks = (
        subprocess.run(
            ["/usr/sbin/cryptsetup", "isLuks", dev_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )

    if is_luks:
        logger.info(f"{dev_path} is already a LUKS device")
    else:
        logger.info(f"Formatting {dev_path} as LUKS...")
        try:
            subprocess.run(
                [
                    "/usr/sbin/cryptsetup",
                    "luksFormat",
                    dev_path,
                    "--key-file",
                    "-",
                    "--batch-mode",
                ],
                input=key_bytes,
                check=True,
                capture_output=True,
            )
            logger.info("LUKS format completed")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to format {dev_path} as LUKS: {e}") from e

    if not os.path.exists(MAPPER_PATH):
        logger.info(f"Opening LUKS device {dev_path}...")
        try:
            subprocess.run(
                ["/usr/sbin/cryptsetup", "open", dev_path, MAPPER_NAME, "--key-file", "-"],
                input=key_bytes,
                check=True,
                capture_output=True,
            )
            logger.info(f"LUKS device opened as {MAPPER_PATH}")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to open LUKS device {dev_path}: {e}") from e


def _ensure_filesystem() -> None:
    """Ensure MAPPER_PATH contains an ext4 filesystem.

    Runs dmsetup mknodes first to guarantee device nodes are visible.
    Creates an ext4 filesystem if one is not already present.

    Raises:
        RuntimeError: If dmsetup mknodes or mkfs.ext4 fails.
    """
    try:
        subprocess.run(["/usr/sbin/dmsetup", "mknodes"], check=True, capture_output=True)
        logger.info("Device mapper nodes refreshed")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to refresh device mapper nodes: {e}") from e

    has_fs = False
    try:
        result = subprocess.run(
            ["/usr/sbin/blkid", MAPPER_PATH],
            check=True,
            capture_output=True,
            text=True,
        )
        if 'TYPE="ext4"' in result.stdout:
            has_fs = True
            logger.info(f"{MAPPER_PATH} already has ext4 filesystem")
    except subprocess.CalledProcessError:
        logger.info(f"{MAPPER_PATH} has no filesystem")

    if not has_fs:
        logger.info(f"Formatting {MAPPER_PATH} as ext4...")
        try:
            subprocess.run(
                ["/usr/sbin/mkfs.ext4", "-m", "0", MAPPER_PATH], check=True, capture_output=True
            )
            logger.info("ext4 filesystem created")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to format filesystem on {MAPPER_PATH}: {e}") from e


def _ensure_mounted() -> None:
    """Write fstab entry and mount MAPPER_PATH at MAIL_ROOT.

    Raises:
        RuntimeError: If mount fails.
    """
    configure_file("/etc/fstab", f"{MAPPER_PATH} {MAIL_ROOT} ext4 defaults,noauto,nofail 0 2\n")

    if not os.path.exists(MAIL_ROOT):
        os.makedirs(MAIL_ROOT)

    logger.info(f"Mounting {MAPPER_PATH} to {MAIL_ROOT}...")
    try:
        subprocess.run(["/usr/bin/mount", MAPPER_PATH, MAIL_ROOT], check=True)
        os.chmod(MAIL_ROOT, 0o1777)  # noqa: S103 # nosec B103
        logger.info(f"Successfully mounted to {MAIL_ROOT}")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to mount {MAPPER_PATH} to {MAIL_ROOT}: {e}") from e
