# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Storage management for Dovecot charm."""

import logging
import os
import shutil
import stat
import subprocess  # nosec
from pathlib import Path

from ops.model import ModelError

from constants import MAIL_ROOT, MAPPER_NAME, MAPPER_PATH, STORAGE_DEV_PATH_FILE
from exceptions import StorageError, StorageSetupError
from utils import configure_file

logger = logging.getLogger(__name__)


def _save_storage_dev_path(dev_path) -> None:
    """Persist *dev_path* to disk so it survives a VM reboot.

    The file is written to STORAGE_DEV_PATH_FILE.  Parent directories are
    created if they do not yet exist.
    """
    path = Path(STORAGE_DEV_PATH_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(dev_path))
    logger.info(f"Saved storage device path to {STORAGE_DEV_PATH_FILE}")


def _load_storage_dev_path() -> str | None:
    """Return the previously-saved block-device path, or *None* if not found."""
    path = Path(STORAGE_DEV_PATH_FILE)
    if path.exists():
        dev_path = path.read_text().strip()
        if dev_path:
            logger.info(f"Loaded storage device path from {STORAGE_DEV_PATH_FILE}: {dev_path}")
            return dev_path
    return None


def _mail_storage_mounted():
    """Return True if mail storage is mounted."""
    return os.path.ismount(MAIL_ROOT)


def _is_luks_device(dev_path: str) -> bool:
    """Return True if *dev_path* exists and contains a LUKS header.

    Used as the readiness probe before attempting to open or format the device.
    A loop-backed device may exist as a node (os.path.exists passes) but not
    yet be backed by the image if Juju has not yet run losetup; cryptsetup
    isLuks will correctly return non-zero in that case.
    """
    result = subprocess.run(
        ["/usr/sbin/cryptsetup", "isLuks", dev_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _resolve_dev_path(charm) -> str | None:
    """Return the block-device path for the mail-data storage, or *None* to defer.

    Tries ``storages[0].location`` first.  On ``ModelError`` (storage not yet
    re-provisioned after a VM reboot) falls back to the path persisted at the
    last ``storage-attached`` event.  Returns *None* in any of these cases:

    * No storage object present yet.
    * ``ModelError`` and no saved path.
    * Device does not yet contain a LUKS header (loop image not yet attached).
    """
    storages = charm.model.storages.get("mail-data")
    if not storages:
        logger.warning("Storage not yet provisioned, deferring LUKS setup")
        return None

    try:
        dev_path = str(storages[0].location)
    except ModelError:
        dev_path = _load_storage_dev_path()
        if not dev_path:
            logger.warning(
                "Storage location not yet available and no saved path, deferring LUKS setup"
            )
            return None
        logger.info(f"Using saved storage device path for LUKS recovery: {dev_path}")

    if not dev_path:
        logger.warning("Storage location empty, deferring LUKS setup")
        return None

    # The device path from Juju is often a /dev/disk/by-uuid/... symlink.
    # That symlink (and the underlying loop device) may not be fully ready
    # at start-hook time even if os.path.exists() passes — the loop image
    # may not yet be attached.  Use `cryptsetup isLuks` as the readiness
    # probe: it succeeds only when the device is attached AND already contains
    # a LUKS header.  On first deploy storage-attached fires before start so
    # the device is always ready; on reboot this correctly defers until
    # storage-attached re-fires after Juju re-attaches the loop.
    if not _is_luks_device(dev_path):
        logger.warning(f"Device {dev_path} not yet a LUKS device, deferring LUKS setup")
        return None

    return dev_path


def ensure_storage_ready(charm) -> None:
    """Ensure mail storage is attached and LUKS-mounted if required.

    Raises:
        StorageError: If storage is not ready and charm should enter Blocked.
        ConfigurationError: Propagated from _get_dovecot_config if config invalid.
    """
    dovecot_config = charm._get_dovecot_config()

    if not dovecot_config.luks_auto_provisioning:
        if _mail_storage_mounted():
            return
        raise StorageError("mail-data not mounted; luks-auto-provisioning disabled")

    if shutil.which("cryptsetup") is None:
        logger.warning("cryptsetup not installed, deferring storage setup")
        return

    dev_path = _resolve_dev_path(charm)
    if dev_path is None:
        return

    # Persist the path so future reboots can recover without storage-get.
    _save_storage_dev_path(dev_path)

    try:
        setup_luks_storage(dovecot_config.luks_key, dev_path)
    except subprocess.CalledProcessError as e:
        logger.exception(f"Failed to setup LUKS storage: {e}")
        raise StorageError("Failed to setup LUKS storage") from e
    except StorageSetupError as e:
        logger.exception(f"Storage validation failed: {e}")
        raise StorageError(str(e)) from e


def teardown_detaching_storage(charm) -> None:
    """Unmount and close LUKS device if storage is detaching."""
    sss = charm.model.storages.get("mail-data")
    if sss:
        return
    try:
        if not (dovecot_config := charm._get_dovecot_config()):
            logger.warning("Cannot determine if luks-auto-provisioning is enabled during storage detachment")
            return
        if dovecot_config.luks_auto_provisioning and _mail_storage_mounted():
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
        StorageSetupError: If any step fails — see individual helpers for details.
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
        StorageSetupError: If dev_path does not exist or is not a block device.
    """
    if not os.path.exists(dev_path):
        raise StorageSetupError(f"Device {dev_path} does not exist")
    if not stat.S_ISBLK(os.stat(dev_path).st_mode):
        raise StorageSetupError(f"{dev_path} is not a valid block device")


def _ensure_luks_container(key_bytes: bytes, dev_path) -> None:
    """Ensure dev_path is a LUKS container and is open at MAPPER_PATH.

    Formats with luksFormat if not already a LUKS device.
    Opens with cryptsetup open if MAPPER_PATH does not yet exist.

    Raises:
        StorageSetupError: If luksFormat or cryptsetup open fails.
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
            raise StorageSetupError(f"Failed to format {dev_path} as LUKS: {e}") from e

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
            raise StorageSetupError(f"Failed to open LUKS device {dev_path}: {e}") from e


def _ensure_filesystem() -> None:
    """Ensure MAPPER_PATH contains an ext4 filesystem.

    Runs dmsetup mknodes first to guarantee device nodes are visible.
    Creates an ext4 filesystem if one is not already present.

    Raises:
        StorageSetupError: If dmsetup mknodes or mkfs.ext4 fails.
    """
    try:
        subprocess.run(["/usr/sbin/dmsetup", "mknodes"], check=True, capture_output=True)
        logger.info("Device mapper nodes refreshed")
    except subprocess.CalledProcessError as e:
        raise StorageSetupError(f"Failed to refresh device mapper nodes: {e}") from e

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
            raise StorageSetupError(f"Failed to format filesystem on {MAPPER_PATH}: {e}") from e


def _ensure_mounted() -> None:
    """Write fstab entry and mount MAPPER_PATH at MAIL_ROOT.

    Raises:
        StorageSetupError: If mount fails.
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
        raise StorageSetupError(f"Failed to mount {MAPPER_PATH} to {MAIL_ROOT}: {e}") from e
