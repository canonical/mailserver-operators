#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Dovecot IMAP/POP3 mail server charm."""

import logging
import shutil
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
        self.framework.observe(self.on.install, self._reconcile)
        self.framework.observe(self.on.upgrade_charm, self._reconcile)
        self.framework.observe(self.on.clear_queue_action, self._on_clear_queue_action)

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
            match exc.errors():
                case [{"loc": ("mailname",), "msg": msg}]:
                    self.unit.status = BlockedStatus(f"Invalid mailname: {msg}")
                case [{"loc": ("postmaster_address",), "msg": msg}]:
                    self.unit.status = BlockedStatus(f"Invalid postmaster-address: {msg}")
                case [{"loc": ("primary_unit",), "msg": msg}]:
                    self.unit.status = BlockedStatus(f"Invalid primary-unit: {msg}")
                case _:
                    self.unit.status = BlockedStatus(
                        "Invalid charm configuration, check logs for details"
                    )
            return False

    def _reconcile(self, event):
        """Reconcile charm state for install, upgrade, and config-changed events."""
        self.unit.status = MaintenanceStatus("Configuring charm")
        if not (dovecot_config := self._get_dovecot_config()):
            return
        self._install()
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
        if systemd.service_running("dovecot"):
            systemd.service_reload("dovecot", restart_on_failure=True)
        else:
            systemd.service_start("dovecot")
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
            logger.warning(f"Failed to validate dovecot configuration: {e}")
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
            if systemd.service_running("postfix"):
                systemd.service_reload("postfix", restart_on_failure=True)
            else:
                systemd.service_start("postfix")
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to configure postfix: {e}")
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


if __name__ == "__main__":  # pragma: nocover
    main(DovecotCharm)
