# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Storage management for Dovecot charm."""

from __future__ import annotations

import logging
import os
import stat
import subprocess  # nosec
import typing
from pathlib import Path

from ops.model import ModelError

from constants import MAIL_ROOT, MAPPER_NAME, MAPPER_PATH, STORAGE_DEV_PATH_FILE
from exceptions import StorageError, StorageSetupError
from utils import configure_file

if typing.TYPE_CHECKING:
    from charm import DovecotCharm
    from dovecot_config import DovecotConfig

logger = logging.getLogger(__name__)


class StorageManager:
    """Manages mail storage lifecycle: LUKS provisioning and teardown.

    Injected into DovecotCharm so unit tests can substitute a no-op
    implementation without patching module-level functions.
    """

    def __init__(self, charm: DovecotCharm) -> None:
        self._charm = charm

    def ensure_storage_ready(self, dovecot_config: DovecotConfig) -> None:
        """Ensure mail storage is attached and LUKS-mounted if required.

        Raises:
            StorageError: If storage is not ready and charm should enter Blocked.
            ConfigurationError: Propagated from _get_dovecot_config if config invalid.
        """
        if not dovecot_config.luks_auto_provisioning:
            if self._mail_storage_mounted():
                return
            raise StorageError("mail-data not mounted; luks-auto-provisioning disabled")

        dev_path = self._resolve_dev_path()
        if dev_path is None:
            return

        self._save_storage_dev_path(dev_path)

        try:
            self.setup_luks_storage(dovecot_config.luks_key, dev_path)
        except subprocess.CalledProcessError as e:
            logger.exception(f"Failed to setup LUKS storage: {e}")
            raise StorageError("Failed to setup LUKS storage") from e
        except StorageSetupError as e:
            logger.exception(f"Storage validation failed: {e}")
            raise StorageError(str(e)) from e

    def teardown_detaching_storage(self) -> None:
        """Unmount and close LUKS device if storage is detaching.

        Raises:
            StorageError: Always raised when storage has detached, to put the
                unit into Blocked status indicating that mail storage is required.
        """
        if self._charm.model.storages.get("mail-data"):
            return
        try:
            dovecot_config = self._charm._get_dovecot_config()
            if dovecot_config.luks_auto_provisioning and self._mail_storage_mounted():
                subprocess.run(["/usr/bin/umount", MAIL_ROOT], check=True)

            if self._mapper_exists():
                subprocess.run(["/usr/sbin/cryptsetup", "luksClose", MAPPER_NAME], check=True)
        except subprocess.CalledProcessError as e:
            logger.exception(f"Failed to detach storage: {e}")
        raise StorageError("Mail storage (mail-data) detached; storage is necessary for operation")

    def setup_luks_storage(self, key: str, dev_path) -> None:
        """Set up LUKS encryption on a block device using the supplied passphrase.

        Idempotent: if MAIL_ROOT is already mounted, returns immediately.
        Otherwise validates the device, ensures a LUKS container exists and is
        open, ensures an ext4 filesystem exists inside it, and mounts it.

        Args:
            key: Plaintext passphrase used as the LUKS key.  Passed to cryptsetup
                via stdin so it is never written to disk or exposed in /proc.
            dev_path: Path to the block device to encrypt (e.g. ``/dev/sdb``).

        Raises:
            StorageSetupError: If any step fails.
        """
        if self._mail_storage_mounted():
            logger.info("mail-data already mounted, skipping LUKS setup")
            return
        key_bytes = key.encode()
        self._validate_block_device(dev_path)
        self._ensure_luks_container(key_bytes, dev_path)
        self._ensure_filesystem()
        self._ensure_mounted()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _save_storage_dev_path(self, dev_path) -> None:
        """Persist *dev_path* to disk so it survives a VM reboot."""
        path = Path(STORAGE_DEV_PATH_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(dev_path))
        logger.info(f"Saved storage device path to {STORAGE_DEV_PATH_FILE}")

    def _load_storage_dev_path(self) -> str | None:
        """Return the previously-saved block-device path, or *None* if not found."""
        path = Path(STORAGE_DEV_PATH_FILE)
        if path.exists():
            dev_path = path.read_text().strip()
            if dev_path:
                logger.info(f"Loaded storage device path from {STORAGE_DEV_PATH_FILE}: {dev_path}")
                return dev_path
        return None

    def _mail_storage_mounted(self) -> bool:
        """Return True if mail storage is mounted."""
        return os.path.ismount(MAIL_ROOT)

    def _mapper_exists(self) -> bool:
        """Return True if the LUKS mapper device node exists."""
        return os.path.exists(MAPPER_PATH)

    def _is_luks_device(self, dev_path: str) -> bool:
        """Return True if *dev_path* exists and contains a LUKS header."""
        result = subprocess.run(
            ["/usr/sbin/cryptsetup", "isLuks", dev_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return result.returncode == 0

    def _resolve_dev_path(self) -> str | None:
        """Return the block-device path for the mail-data storage, or *None* to defer.

        Tries ``storages[0].location`` first.  On ``ModelError`` (Juju storage
        API not yet re-provisioned after a VM reboot) falls back to the path
        persisted at the last ``storage-attached`` event.  Returns *None* in any
        of these cases:

        * No storage object present yet.
        * ``ModelError`` and no saved path.
        * Reboot fallback path: device does not yet contain a LUKS header
          (storage not yet fully attached by Juju).
        """
        storages = self._charm.model.storages.get("mail-data")
        if not storages:
            logger.warning("Storage not yet provisioned, deferring LUKS setup")
            return None

        try:
            dev_path = str(storages[0].location)
            if dev_path:
                return dev_path
        except ModelError:
            pass

        dev_path = self._load_storage_dev_path()
        if not dev_path:
            logger.warning(
                "Storage location not yet available and no saved path, deferring LUKS setup"
            )
            return None
        logger.info(f"Using saved storage device path for LUKS recovery: {dev_path}")

        if not self._is_luks_device(dev_path):
            logger.warning(f"Device {dev_path} not yet a LUKS device, deferring LUKS setup")
            return None

        return dev_path

    def _validate_block_device(self, dev_path) -> None:
        """Confirm dev_path exists and is a block device.

        Raises:
            StorageSetupError: If dev_path does not exist or is not a block device.
        """
        if not os.path.exists(dev_path):
            raise StorageSetupError(f"Device {dev_path} does not exist")
        if not stat.S_ISBLK(os.stat(dev_path).st_mode):
            raise StorageSetupError(f"{dev_path} is not a valid block device")

    def _ensure_luks_container(self, key_bytes: bytes, dev_path) -> None:
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

        if not self._mapper_exists():
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

    def _ensure_filesystem(self) -> None:
        """Ensure MAPPER_PATH contains an ext4 filesystem.

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
                    ["/usr/sbin/mkfs.ext4", "-m", "0", MAPPER_PATH],
                    check=True,
                    capture_output=True,
                )
                logger.info("ext4 filesystem created")
            except subprocess.CalledProcessError as e:
                raise StorageSetupError(
                    f"Failed to format filesystem on {MAPPER_PATH}: {e}"
                ) from e

    def _ensure_mounted(self) -> None:
        """Write fstab entry and mount MAPPER_PATH at MAIL_ROOT.

        Raises:
            StorageSetupError: If mount fails.
        """
        configure_file(
            "/etc/fstab", f"{MAPPER_PATH} {MAIL_ROOT} ext4 defaults,noauto,nofail 0 2\n"
        )

        if not os.path.exists(MAIL_ROOT):
            os.makedirs(MAIL_ROOT)

        logger.info(f"Mounting {MAPPER_PATH} to {MAIL_ROOT}...")
        try:
            subprocess.run(["/usr/bin/mount", MAPPER_PATH, MAIL_ROOT], check=True)
            os.chmod(MAIL_ROOT, 0o1777)  # noqa: S103 # nosec B103
            logger.info(f"Successfully mounted to {MAIL_ROOT}")
        except subprocess.CalledProcessError as e:
            raise StorageSetupError(f"Failed to mount {MAPPER_PATH} to {MAIL_ROOT}: {e}") from e
