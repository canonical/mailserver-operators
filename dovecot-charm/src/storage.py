# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Storage management for Dovecot charm."""

import logging
import os
import shutil
import stat
import subprocess  # nosec

from ops.model import BlockedStatus

from constants import LUKS_ENCRYPTION_FILE, MAIL_ROOT, MAPPER_NAME, MAPPER_PATH
from tools import configure_file

logger = logging.getLogger(__name__)


def _mail_storage_mounted():
    """Return True if mail storage is mounted."""
    return os.path.ismount(MAIL_ROOT)


def handle_mail_storage_attached(charm) -> bool:
    """Handle storage attached event.

    Returns True if it is safe to proceed with charm configuration, False if
    the unit has been placed in a blocked state and configuration should be
    skipped.
    """
    if not (dovecot_config := charm._get_dovecot_config()):
        return False

    if not dovecot_config.manage_luks:
        if _mail_storage_mounted():
            return True
        charm.unit.status = BlockedStatus("mail-data not mounted; manage-luks disabled")
        return False

    if shutil.which("cryptsetup") is None:
        logger.warning("cryptsetup not installed, deferring storage setup")
        return True

    storages = charm.model.storages["mail-data"]
    if not storages:
        logger.error("Storage attached but no location found")
        return True
    dev_path = storages[0].location
    if not dev_path:
        logger.error("Storage attached but no location found")
        return True

    try:
        setup_luks_storage(charm, dev_path)
        return True
    except subprocess.CalledProcessError as e:
        logger.exception(f"Failed to setup LUKS storage: {e}")
        charm.unit.status = BlockedStatus("Failed to setup LUKS storage")
        return False
    except RuntimeError as e:
        logger.exception(f"Storage validation failed: {e}")
        charm.unit.status = BlockedStatus(str(e))
        return False


def handle_mail_storage_detaching(charm):
    """Handle storage detaching."""
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


def setup_luks_storage(charm, dev_path):  # noqa: C901
    """Set up LUKS encryption on device using keyfile."""
    if not os.path.exists(dev_path):
        raise RuntimeError(f"Device {dev_path} does not exist")

    mode = os.stat(dev_path).st_mode
    if not stat.S_ISBLK(mode):
        raise RuntimeError(f"{dev_path} is not a valid block device")

    if not os.path.exists(LUKS_ENCRYPTION_FILE):
        logger.info(f"Generating keyfile at {LUKS_ENCRYPTION_FILE}...")
        try:
            subprocess.run(
                [
                    "/usr/bin/dd",
                    "if=/dev/urandom",
                    f"of={LUKS_ENCRYPTION_FILE}",
                    "bs=512",
                    "count=8",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            os.chmod(LUKS_ENCRYPTION_FILE, 0o400)
            logger.info("Keyfile generated successfully")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to generate encryption keyfile: {e}") from e

    try:
        subprocess.run(
            ["/usr/sbin/cryptsetup", "isLuks", dev_path],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info(f"{dev_path} is already a LUKS device")
    except subprocess.CalledProcessError:
        logger.info(f"Formatting {dev_path} as LUKS with keyfile...")
        try:
            subprocess.run(
                [
                    "/usr/sbin/cryptsetup",
                    "luksFormat",
                    dev_path,
                    "--key-file",
                    LUKS_ENCRYPTION_FILE,
                    "--batch-mode",
                ],
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
                [
                    "/usr/sbin/cryptsetup",
                    "open",
                    dev_path,
                    MAPPER_NAME,
                    "--key-file",
                    LUKS_ENCRYPTION_FILE,
                ],
                check=True,
                capture_output=True,
            )
            logger.info(f"LUKS device opened as {MAPPER_PATH}")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to open LUKS device {dev_path}: {e}") from e

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

    configure_file(
        "/etc/crypttab",
        f"{MAPPER_NAME} {dev_path} {LUKS_ENCRYPTION_FILE} luks,discard,auto\n",
    )
    configure_file("/etc/fstab", f"{MAPPER_PATH} {MAIL_ROOT} ext4 defaults,auto 0 2\n")

    if not os.path.exists(MAIL_ROOT):
        os.makedirs(MAIL_ROOT)

    if not _mail_storage_mounted():
        logger.info(f"Mounting {MAPPER_PATH} to {MAIL_ROOT}...")
        try:
            subprocess.run(["/usr/bin/mount", MAPPER_PATH, MAIL_ROOT], check=True)
            os.chmod(MAIL_ROOT, 0o1777)  # noqa: S103 # nosec B103
            logger.info(f"Successfully mounted to {MAIL_ROOT}")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to mount {MAPPER_PATH} to {MAIL_ROOT}: {e}") from e
