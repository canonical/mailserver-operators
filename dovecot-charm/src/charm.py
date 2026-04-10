#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Dovecot charm."""

import logging
import os
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
from ops.model import BlockedStatus, MaintenanceStatus

from constants import (
    DOVECOT_CONF_TARGET,
    DOVECOT_CONF_TEMPLATE,
    ENCRYPTED_MOUNTPOINT,
    HOSTNAME_FILE,
    LUKS_ENCRYPTION_FILE,
    MAIL_ROOT,
    MAILNAME_FILE,
    PEER_RELATION_NAME,
    PROCMAILRC_TARGET,
    PROCMAILRC_TEMPLATE,
    REQUIRED_PACKAGES,
    TEMPLATES_DIR,
)
from dovecot_config import DovecotConfig, DovecotConfigInvalidError
from storage import handle_mail_storage_attached, handle_mail_storage_detaching

logger = logging.getLogger(__name__)


class DovecotCharm(CharmBase):
    """Dovecot IMAP/POP3 mail server charm."""

    def __init__(self, *args):
        super().__init__(*args)

        # Events
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.config_changed, self._reconcile)
        self.framework.observe(self.on.upgrade_charm, self._reconcile)
        self.framework.observe(self.on.clear_queue_action, self._on_clear_queue_action)
        self.framework.observe(
            self.on.get_encryption_key_action,
            self.get_luks_encryption_key,
        )
        self.framework.observe(self.on.mail_data_storage_attached, self._reconcile)
        self.framework.observe(self.on.mail_data_storage_detaching, self._reconcile)

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
        handle_mail_storage_attached(self)
        handle_mail_storage_detaching(self)
        if not shutil.which("doveconf"):
            logger.warning("Dovecot not installed yet, deferring configuration")
            return
        self._configure(dovecot_config)

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
            )
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
            )
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
            result = subprocess.run(command, check=True, capture_output=True, text=True)
            event.set_results({"status": "success", "output": result.stdout})
        except subprocess.CalledProcessError as e:
            logger.exception(f"Failed to clear Postfix queue: {e.stderr}")
            event.fail(f"Failed to run postsuper: {e.stderr}")

    def get_luks_encryption_key(self, event):
        """Return the generated LUKS key when automatic LUKS management is enabled."""
        if not (dovecot_config := self._get_dovecot_config()):
            return
        if not dovecot_config.manage_luks:
            event.fail("Cannot retrieve key: manage-luks is disabled")
            return

        if not os.path.exists(LUKS_ENCRYPTION_FILE):
            event.fail("Cannot retrieve key: encryption key is not available yet")
            return

        try:
            with open(LUKS_ENCRYPTION_FILE, "rb") as f:
                key_hex = f.read().hex()
            event.set_results({"status": "success", "encoding": "hex", "key": key_hex})
        except OSError as e:
            logger.exception(f"Failed to read encryption key: {e}")
            event.fail(f"Cannot retrieve key: failed to read keyfile: {e}")


if __name__ == "__main__":  # pragma: nocover
    main(DovecotCharm)
