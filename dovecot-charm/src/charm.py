#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Dovecot IMAP/POP3 mail server charm."""

import logging
import shutil
import subprocess  # nosec
from pathlib import Path
from typing import Any, Mapping

import jinja2
from charmhelpers.core import host
from charmlibs import apt
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus
from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    ValidationError,
    field_validator,
)

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


class DovecotConfig(BaseModel):
    """Pydantic model for validating charm configuration."""

    model_config = ConfigDict(str_strip_whitespace=True)

    cron_mailto: EmailStr = Field(..., description="Email address for cron output")
    mailname: str = Field(..., description="Mailname for the server")
    postmaster_address: EmailStr = Field(..., description="Postmaster email address")
    primary_unit: str = Field(..., description="Name of the primary unit")

    @field_validator("mailname", "postmaster_address", "primary_unit", mode="before")
    @classmethod
    def _reject_empty_values(cls, value: Any) -> Any:
        """Ensure string config values are not empty or whitespace-only."""
        if isinstance(value, str) and not value.strip():
            raise ValueError("must not be empty")
        return value

    @classmethod
    def from_charm(cls, config: Mapping[str, Any]) -> "DovecotConfig":
        """Create a DovecotConfig instance from charm configuration."""
        try:
            return cls(
                cron_mailto=config.get("cron-mailto"),
                mailname=config.get("mailname"),
                postmaster_address=config.get("postmaster-address"),
                primary_unit=config.get("primary-unit"),
            )
        except ValidationError as e:
            logger.exception(f"Configuration validation error: {e}")
            raise


class DovecotCharm(CharmBase):
    """Dovecot IMAP/POP3 mail server charm."""

    def __init__(self, *args):
        super().__init__(*args)

        # Events
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.clear_queue_action, self._on_clear_queue_action)

        # Template system
        self.jinja = jinja2.Environment(
            loader=jinja2.FileSystemLoader(TEMPLATES_DIR), autoescape=True
        )

    def _get_dovecot_config(self):
        """Return True if all required config options are set."""
        try:
            return DovecotConfig.from_charm(self.config)
        except ValidationError as exc:
            match exc.errors():
                case [{"loc": ("cron_mailto",), "msg": msg}]:
                    self.unit.status = BlockedStatus(f"Invalid cron-mailto: {msg}")
                case [{"loc": ("mailname",), "msg": msg}]:
                    self.unit.status = BlockedStatus(f"Invalid mailname: {msg}")
                case [{"loc": ("postmaster_address",), "msg": msg}]:
                    self.unit.status = BlockedStatus(f"Invalid postmaster-address: {msg}")
                case [{"loc": ("primary_unit",), "msg": msg}]:
                    self.unit.status = BlockedStatus(f"Invalid primary-unit: {msg}")
                case _:
                    self.unit.status = BlockedStatus("Invalid charm configuration")
            return False

    @property
    def _is_primary(self):
        """Return True if this unit is the configured primary unit."""
        return self.unit.name == DovecotConfig.from_charm(self.config).primary_unit

    def _on_install(self, event):
        """Install and configure charm."""
        if not self._get_dovecot_config():
            return
        self._install()
        self.unit.status = ActiveStatus()

    def _on_config_changed(self, event):
        """Handle changed configuration."""
        self.unit.status = MaintenanceStatus("Configuring charm")
        if not (dovecot_config := self._get_dovecot_config()):
            return
        self._config(dovecot_config)
        self.unit.status = ActiveStatus()

    def _install(self):
        """Perform basic installation."""
        self.unit.status = MaintenanceStatus("Installing required dependencies")
        apt.update()
        apt.add_package(REQUIRED_PACKAGES)
        shutil.copy("/etc/hostname", "/etc/mailname")
        self.unit.status = MaintenanceStatus("Charm install done")

    def _config(self, dovecot_config: DovecotConfig):
        """Perform basic installation."""
        self._setup_dovecot(dovecot_config)
        self._setup_procmail()
        self.unit.status = MaintenanceStatus("Charm configuration done")

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
        if self._systemctl("is-enabled", "dovecot"):
            self._systemctl("restart", "dovecot")
        self.unit.status = MaintenanceStatus("Dovecot configuration updated")

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
            self._systemctl("restart", "postfix")
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to configure postfix: {e}")

        self.unit.status = MaintenanceStatus("Procmail configuration updated")

    def _systemctl(self, *args):
        """Run the requested systemctl command."""
        cmd = ["systemctl"]
        cmd.extend(args)
        logger.debug("running: %s", " ".join(cmd))
        try:
            # The command and arguments are fixed literals with no user-controlled input.
            subprocess.run(cmd, capture_output=True, check=True)  # nosec B603
        except subprocess.CalledProcessError as e:
            logger.exception(f"Command '{' '.join(cmd)}' failed: {e.stderr}")
            raise

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
            logger.exception(f"Failed to clear Postfix queue: {e.stderr}")
            event.fail(f"Failed to run postsuper: {e.stderr}")


if __name__ == "__main__":  # pragma: nocover
    main(DovecotCharm)
