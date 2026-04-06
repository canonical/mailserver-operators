#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Dovecot IMAP/POP3 mail server charm."""

import logging
import shutil
import subprocess  # nosec
from pathlib import Path

import jinja2
from charmhelpers.core import host
from charmlibs import apt
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus

logger = logging.getLogger(__name__)


class DovecotCharm(CharmBase):
    """Dovecot IMAP/POP3 mail server charm."""

    def __init__(self, *args):
        super().__init__(*args)

        # Events
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.clear_queue_action, self._on_clear_queue_action)

        # Paths
        self.mail_root = "/srv/mail"
        self.encrypted_mountpoint = "/srv"
        self.templates_dir = self.charm_dir.joinpath("templates")

        # Template system
        self.jinja = jinja2.Environment(
            loader=jinja2.FileSystemLoader(self.templates_dir), autoescape=True
        )

        # Dovecot config
        self.dovecot_conf_template = "dovecot.conf.tmpl"
        self.dovecot_conf_target = "/etc/dovecot/conf.d/99-local-dovecot-charm.conf"

        # Procmail config
        self.procmailrc_template = "procmailrc.tmpl"
        self.procmailrc_target = "/etc/procmailrc"

        self.required_packages = [
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

    @property
    def cron_mailto(self):
        """Validate and return configured cron-mailto."""
        if not self.config["cron-mailto"]:
            self.unit.status = BlockedStatus("cron-mailto is required")
        return self.config["cron-mailto"]

    @property
    def mailname(self):
        """Validate and return configured mailname."""
        if not self.config["mailname"]:
            self.unit.status = BlockedStatus("mailname is required")
        return self.config["mailname"]

    @property
    def postmaster_address(self):
        """Validate and return configured postmaster-address."""
        if not self.config["postmaster-address"]:
            self.unit.status = BlockedStatus("postmaster-address is required")
        return self.config["postmaster-address"]

    @property
    def primary_unit(self):
        """Validate and return configured primary-unit."""
        if not self.config["primary-unit"]:
            self.unit.status = BlockedStatus("primary-unit is required")
        return self.config["primary-unit"]

    def _config_is_valid(self):
        """Return True if all required config options are set."""
        return all(
            [
                self.cron_mailto,
                self.mailname,
                self.postmaster_address,
                self.primary_unit,
            ]
        )

    @property
    def _is_primary(self):
        """Return True if this unit is the configured primary unit."""
        return self.unit.name == self.primary_unit

    def _on_install(self, event):
        """Install and configure charm."""
        if not self._config_is_valid():
            return
        self._install()
        self.unit.status = ActiveStatus()

    def _on_config_changed(self, event):
        """Handle changed configuration."""
        self.unit.status = MaintenanceStatus("Configuring charm")
        if not self._config_is_valid():
            return
        self._install()
        self.unit.status = ActiveStatus()

    def _install(self):
        """Perform basic installation."""
        self.unit.status = MaintenanceStatus("Installing required dependencies")
        apt.update()
        apt.add_package(self.required_packages)
        self._open_ports()
        self._setup_dovecot()
        self._setup_procmail()
        shutil.copy("/etc/hostname", "/etc/mailname")
        self.unit.status = MaintenanceStatus("Charm install done")

    def _open_ports(self):
        """Open mail ports."""
        self.unit.open_port("tcp", 143)
        self.unit.open_port("tcp", 993)
        self.unit.open_port("tcp", 110)
        self.unit.open_port("tcp", 995)
        self.unit.open_port("tcp", 4190)
        self.unit.open_port("tcp", 9900)

    def _setup_dovecot(self):
        """Set up and configure dovecot."""
        self.unit.status = MaintenanceStatus("Setting up and configuring dovecot")
        template_context = {
            "dovecot_chroot": self.encrypted_mountpoint,
            "mail_root": self.mail_root,
            "mailname": self.config.get("mailname", ""),
            "postmaster_address": self.config.get("postmaster-address", ""),
        }
        template = self.jinja.get_template(self.dovecot_conf_template)
        contents = template.render(template_context)
        host.write_file(self.dovecot_conf_target, contents, perms=0o644)
        if self._systemctl("is-enabled", "dovecot"):
            self._systemctl("restart", "dovecot")
        self.unit.status = MaintenanceStatus("Dovecot configuration updated")

    def _setup_procmail(self):
        """Set up and configure procmail default file."""
        self.unit.status = MaintenanceStatus("Setting up and configuring procmail")

        # Ensure mail_root exists with permissions for delivery
        mail_root = Path(self.mail_root)
        mail_root.mkdir(parents=True, exist_ok=True)
        mail_root.chmod(0o1777)

        template_context = {
            "mail_root": self.mail_root,
        }
        template = self.jinja.get_template(self.procmailrc_template)
        contents = template.render(template_context)
        host.write_file(self.procmailrc_target, contents, perms=0o644)

        # Configure Postfix to use procmail
        try:
            # The command and arguments are fixed literals with no user-controlled input.
            subprocess.run(
                ["/usr/sbin/postconf", "-e", 'mailbox_command=/usr/bin/procmail -a "$EXTENSION"'],
                check=True,
                capture_output=True,
            )  # nosec B603
            self._systemctl("restart", "postfix")
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to configure postfix: {e}")

        self.unit.status = MaintenanceStatus("Procmail configuration updated")

    def _systemctl(self, *args):
        """Run the requested systemctl command."""
        cmd = ["systemctl"]
        cmd.extend(args)
        logger.debug("running: %s", " ".join(cmd))
        # The command and arguments are fixed literals with no user-controlled input.
        subprocess.run(cmd, capture_output=True, check=True)  # nosec B603

    def _on_clear_queue_action(self, event):
        """Handle the clear-queue action."""
        queue_to_clear = event.params.get("queue", "deferred")
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
            logger.error(f"Failed to clear Postfix queue: {e.stderr}")
            event.fail(f"Failed to run postsuper: {e.stderr}")


if __name__ == "__main__":  # pragma: nocover
    main(DovecotCharm)
