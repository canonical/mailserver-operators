#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Dovecot IMAP/POP3 mail server charm."""

import logging
import os
import shutil
import stat
import subprocess  # nosec
import typing
from pathlib import Path

import jinja2
import ops
from charmhelpers.core import host
from charmlibs import apt, systemd
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus

from dovecot_config import DovecotConfig, DovecotConfigInvalidError

logger = logging.getLogger(__name__)

# Paths
MAIL_ROOT = "/srv/mail"
ENCRYPTED_MOUNTPOINT = "/srv"
TEMPLATES_DIR = Path(__file__).parent.parent.joinpath("templates")

# Dovecot config
DOVECOT_CONF_TEMPLATE = "dovecot.conf.tmpl"
DOVECOT_CONF_TARGET = "/etc/dovecot/conf.d/99-local-dovecot-charm.conf"

# Procmail config
PROCMAILRC_TEMPLATE = "procmailrc.tmpl"
PROCMAILRC_TARGET = "/etc/procmailrc"
REQUIRED_PACKAGES = [
    "cron",
    "cryptsetup",
    "dovecot-imapd",
    "dovecot-lmtpd",
    "dovecot-managesieved",
    "dovecot-pop3d",
    "dovecot-sieve",
    "etckeeper",
    "getmail6",
    "mailutils",
    "mutt",
    "procmail",
    "ubuntu-advantage-desktop-daemon",
    "vacation",
]

HOSTNAME_FILE = "/etc/hostname"
MAILNAME_FILE = "/etc/mailname"

PEER_RELATION_NAME = "replicas"


class DovecotCharm(CharmBase):
    """Dovecot IMAP/POP3 mail server charm."""

    def __init__(self, *args):
        super().__init__(*args)

        # Events
        self.framework.observe(self.on.config_changed, self._reconcile)
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.upgrade_charm, self._reconcile)
        self.framework.observe(self.on.clear_queue_action, self._on_clear_queue_action)
        self.framework.observe(
            self.on.mail_data_storage_attached, self._on_mail_data_storage_attached
        )
        self.framework.observe(
            self.on.mail_data_storage_detaching, self._on_mail_data_storage_detaching
        )

        self.framework.observe(
            self.on[PEER_RELATION_NAME].relation_created,
            self._on_peer_relation_created,
        )
        # Template system
        self.jinja = jinja2.Environment(
            loader=jinja2.FileSystemLoader(TEMPLATES_DIR), autoescape=True
        )

    def get_units(self):
        """Return a list of all units in the application."""
        peer_relation = typing.cast(ops.Relation, self.model.get_relation(PEER_RELATION_NAME))
        if not peer_relation:
            logger.warning(
                f"primary unit: {self.unit.name} is running without peer relation {PEER_RELATION_NAME}"
            )
            return [self.unit.name]

        units = [unit.name for unit in peer_relation.units]
        if self.unit.name not in units:
            units.append(self.unit.name)
        return units

    def _on_peer_relation_created(self, event):
        """Handle peer relation created event."""
        relation_data = event.relation.data[self.unit]
        relation_data["unit-name"] = self.unit.name

    def _get_dovecot_config(self):
        """Return the DovecotConfig if all required config options are set, false otherwise."""
        try:
            return DovecotConfig.from_charm(self)
        except DovecotConfigInvalidError as exc:
            logger.exception(f"Configuration validation error: {exc}")
            msg = ", ".join([str(*err["loc"]) for err in exc.errors()])
            self.unit.status = BlockedStatus(
                f"Invalid charm configuration, check logs for details: {msg}"
            )
            return False

    def _on_install(self, event):
        """Handle install event."""
        self.unit.status = MaintenanceStatus("Installing packages")
        if not self._get_dovecot_config():
            return
        self._install()
        self._reconcile(event)

    def _reconcile(self, event):
        """Reconcile charm state for install, upgrade, and config-changed events."""
        self.unit.status = MaintenanceStatus("Configuring charm")
        if not (dovecot_config := self._get_dovecot_config()):
            return
        self._configure(dovecot_config)
        self.unit.status = ActiveStatus()

    def _install(self):
        """Perform basic installation."""
        self.unit.status = MaintenanceStatus("Installing required dependencies")
        apt.update()
        apt.add_package(REQUIRED_PACKAGES)
        shutil.copy(HOSTNAME_FILE, MAILNAME_FILE)
        self.unit.status = MaintenanceStatus("Charm installation done")

    def _configure(self, dovecot_config: DovecotConfig):
        """Perform basic configuration."""
        self._setup_dovecot(dovecot_config)
        self._setup_procmail()
        self._open_ports()

    def _open_ports(self):
        """Open mail ports."""
        self.unit.open_port("tcp", 143)
        self.unit.open_port("tcp", 993)
        self.unit.open_port("tcp", 110)
        self.unit.open_port("tcp", 995)
        self.unit.open_port("tcp", 4190)
        self.unit.open_port("tcp", 9900)

    def _setup_dovecot(self, dovecot_config: DovecotConfig):
        """Set up and configure dovecot."""
        self.unit.status = MaintenanceStatus("Setting up and configuring dovecot")
        template_context = {
            "dovecot_chroot": ENCRYPTED_MOUNTPOINT,
            "mail_root": MAIL_ROOT,
            "mailname": dovecot_config.mailname,
            "postmaster_address": dovecot_config.postmaster_address,
        }
        template = self.jinja.get_template(DOVECOT_CONF_TEMPLATE)
        contents = template.render(template_context)
        host.write_file(DOVECOT_CONF_TARGET, contents, perms=0o644)
        if not self._validate_dovecot_config(dovecot_config):
            self.unit.status = BlockedStatus(
                "Invalid Dovecot configuration, check logs for details"
            )
            return
        systemd.service_reload("dovecot", restart_on_failure=True)
        self.unit.status = MaintenanceStatus("Dovecot configuration updated")

    def _validate_dovecot_config(self, config: DovecotConfig) -> bool:
        """Validate the Dovecot configuration."""
        try:
            # The command and arguments are fixed literals with no user-controlled input.
            subprocess.run(
                ["/usr/bin/doveconf", "-c", DOVECOT_CONF_TARGET],
                check=True,
                capture_output=True,
            )  # nosec B603
            return True
        except subprocess.CalledProcessError as e:
            logger.exception(f"Failed to validate dovecot configuration: {e}")
            return False

    def _setup_procmail(self):
        """Set up and configure procmail default file."""
        self.unit.status = MaintenanceStatus("Setting up and configuring procmail")

        # Ensure mail_root exists with permissions for delivery
        mail_root = Path(MAIL_ROOT)
        mail_root.mkdir(parents=True, exist_ok=True)
        mail_root.chmod(0o1777)

        template_context = {
            "mail_root": MAIL_ROOT,
        }
        template = self.jinja.get_template(PROCMAILRC_TEMPLATE)
        contents = template.render(template_context)
        host.write_file(PROCMAILRC_TARGET, contents, perms=0o644)

        # Configure Postfix to use procmail
        try:
            # The command and arguments are fixed literals with no user-controlled input.
            subprocess.run(
                ["/usr/sbin/postconf", "-e", 'mailbox_command=/usr/bin/procmail -a "$EXTENSION"'],
                check=True,
                capture_output=True,
            )  # nosec B603
            systemd.service_reload("postfix", restart_on_failure=True)
        except subprocess.CalledProcessError as e:
            logger.exception(f"Failed to configure postfix: {e}")
            self.unit.status = BlockedStatus(f"Failed to configure postfix: {e.stderr}")
            return

    def _on_clear_queue_action(self, event):
        """Handle the clear-queue action."""
        queue_to_clear = event.params.get("queue", "deferred")

        if queue_to_clear not in ("deferred", "all"):
            event.fail("Invalid queue parameter, must be 'deferred' or 'all'")
            return
        command = ["postsuper", "-d", "ALL"]

        if queue_to_clear == "all":
            logger.warning("Running clear-queue action: DELETING ALL mail from Postfix queue.")
        else:
            command.append("deferred")
            logger.info("Running clear-queue action: Deleting deferred mail from Postfix queue.")

        try:
            # The command and arguments are fixed literals with no user-controlled input.
            result = subprocess.run(command, check=True, capture_output=True, text=True)  # nosec B603
            event.set_results({"status": "success", "output": result.stdout})
        except subprocess.CalledProcessError as e:
            logger.exception(f"Failed to clear Postfix queue: {e.stderr}")
            event.fail(f"Failed to run postsuper: {e.stderr}")

    def _mail_storage_mounted(self):
        """Return True if mail storage is mounted."""
        return os.path.ismount(MAIL_ROOT)

    def _on_mail_data_storage_attached(self, event):
        """Handle storage attached event."""
        if self._mail_storage_mounted():
            self.unit.status = ActiveStatus()
        else:
            self.unit.status = BlockedStatus("mail-data not mounted")
            event.defer()
            # return

        if shutil.which("cryptsetup") is None:
            logger.info("cryptsetup not installed, deferring storage setup")
            event.defer()
            return

        dev_path = event.storage.location
        if not dev_path:
            logger.error("Storage attached but no location found")
            return

        try:
            self._setup_luks_storage(dev_path)
            self.unit.status = ActiveStatus()
        except subprocess.CalledProcessError as e:
            logger.exception(f"Failed to setup LUKS storage: {e}")
            self.unit.status = BlockedStatus("Failed to setup LUKS storage")
        except RuntimeError as e:
            logger.exception(f"Storage validation failed: {e}")
            self.unit.status = BlockedStatus(str(e))

    def _on_mail_data_storage_detaching(self, event):
        """Handle storage detaching event."""
        try:
            if self._mail_storage_mounted():
                subprocess.run(["umount", MAIL_ROOT], check=True)  # noqa: S607

            if os.path.exists("/dev/mapper/mail-data"):
                subprocess.run(["cryptsetup", "luksClose", "mail-data"], check=True)  # noqa: S607
        except subprocess.CalledProcessError as e:
            logger.exception(f"Failed to detach storage: {e}")

    def _setup_luks_storage(self, dev_path):  # noqa: C901
        """Set up LUKS encryption on device using keyfile."""
        keyfile = "/etc/dovecot-charm.key"
        mapper_name = "mail-data"
        mapper_path = f"/dev/mapper/{mapper_name}"

        if not os.path.exists(dev_path):
            raise RuntimeError(f"Device {dev_path} does not exist")

        mode = os.stat(dev_path).st_mode
        if not stat.S_ISBLK(mode):
            raise RuntimeError(f"{dev_path} is not a valid block device")

        if not os.path.exists(keyfile):
            logger.info(f"Generating keyfile at {keyfile}...")
            subprocess.run(
                ["dd", "if=/dev/urandom", f"of={keyfile}", "bs=512", "count=8"],  # noqa: S607
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            os.chmod(keyfile, 0o400)
            logger.info("Keyfile generated successfully")

        try:
            subprocess.run(
                ["cryptsetup", "isLuks", dev_path],  # noqa: S607
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info(f"{dev_path} is already a LUKS device")
        except subprocess.CalledProcessError:
            logger.info(f"Formatting {dev_path} as LUKS with keyfile...")
            subprocess.run(
                ["cryptsetup", "luksFormat", dev_path, "--key-file", keyfile, "--batch-mode"],  # noqa: S607
                check=True,
                capture_output=True,
            )
            logger.info("LUKS format completed")

        if not os.path.exists(mapper_path):
            logger.info(f"Opening LUKS device {dev_path}...")
            subprocess.run(
                ["cryptsetup", "open", dev_path, mapper_name, "--key-file", keyfile],  # noqa: S607
                check=True,
                capture_output=True,
            )
            logger.info(f"LUKS device opened as {mapper_path}")

            subprocess.run(["dmsetup", "mknodes"], check=True, capture_output=True)  # noqa: S607
            logger.info("Device mapper nodes refreshed")

        has_fs = False
        try:
            result = subprocess.run(
                ["blkid", mapper_path],  # noqa: S607
                check=True,
                capture_output=True,
                text=True,
            )
            if 'TYPE="ext4"' in result.stdout:
                has_fs = True
                logger.info(f"{mapper_path} already has ext4 filesystem")
        except subprocess.CalledProcessError:
            logger.info(f"{mapper_path} has no filesystem")

        if not has_fs:
            logger.info(f"Formatting {mapper_path} as ext4...")
            subprocess.run(["mkfs.ext4", "-m", "0", mapper_path], check=True, capture_output=True)  # noqa: S607
            logger.info("ext4 filesystem created")

        self._configure_file("/etc/crypttab", f"{mapper_name} {dev_path} {keyfile} luks,discard,noauto\n")
        self._configure_file("/etc/fstab", f"{mapper_path} {MAIL_ROOT} ext4 defaults,noauto 0 2\n")

        if not os.path.exists(MAIL_ROOT):
            os.makedirs(MAIL_ROOT)

        if not self._mail_storage_mounted():
            logger.info(f"Mounting {mapper_path} to {MAIL_ROOT}...")
            subprocess.run(["mount", mapper_path, MAIL_ROOT], check=True)  # noqa: S607
            os.chmod(MAIL_ROOT, 0o1777)  # noqa: S103
            logger.info(f"Successfully mounted to {MAIL_ROOT}")

    def _configure_file(self, path, entry):
        """Add an entry to a config file if it doesn't already exist."""
        if os.path.exists(path):
            with open(path) as f:
                if entry in f.read():
                    logger.info(f"Entry already exists in {path}")
                    return

        logger.info(f"Adding entry to {path}")
        with open(path, "a") as f:
            f.write(entry)
        logger.info(f"{path} configured")


if __name__ == "__main__":  # pragma: nocover
    main(DovecotCharm)
