#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Dovecot IMAP/POP3 mail server charm."""

import logging
import shutil
import subprocess  # nosec
import typing
from pathlib import Path
from pwd import getpwnam

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
        self.framework.observe(self.on.create_mail_user_action, self._on_create_mail_user_action)

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

    def _on_create_mail_user_action(self, event):
        """Create or update local mail users for integration and operations workflows."""
        username = str(event.params.get("username", "")).strip()
        password = str(event.params.get("password", ""))
        mailbox_user = str(event.params.get("mailbox-user", "")).strip()

        if not username:
            event.fail("Parameter 'username' is required.")
            return
        if not password:
            event.fail("Parameter 'password' is required.")
            return

        users_to_manage = [username]
        if mailbox_user and mailbox_user != username:
            users_to_manage.append(mailbox_user)

        created_users: list[str] = []
        updated_users: list[str] = []

        try:
            for user in users_to_manage:
                if self._system_user_exists(user):
                    updated_users.append(user)
                else:
                    self._create_system_user(user)
                    created_users.append(user)
                self._ensure_user_in_mail_group(user)
                self._set_system_user_password(user, password)
        except (subprocess.CalledProcessError, KeyError, FileNotFoundError) as exc:
            event.fail(f"Failed to manage users: {exc}")
            return

        event.set_results(
            {
                "status": "success",
                "created": ",".join(created_users),
                "updated": ",".join(updated_users),
            }
        )

    @staticmethod
    def _system_user_exists(username: str) -> bool:
        """Return whether a local system user exists."""
        try:
            getpwnam(username)
            return True
        except KeyError:
            return False

    @staticmethod
    def _create_system_user(username: str) -> None:
        """Create a local system user, allowing mailbox-style names if needed."""
        command = ["/usr/sbin/useradd", "-m", username]
        if "@" in username:
            command.insert(1, "--badname")
        subprocess.run(command, check=True, capture_output=True, text=True)  # nosec B603

    @staticmethod
    def _ensure_user_in_mail_group(username: str) -> None:
        """Ensure the user is a member of the mail group."""
        subprocess.run(
            ["/usr/sbin/usermod", "-aG", "mail", username],
            check=True,
            capture_output=True,
            text=True,
        )  # nosec B603

    @staticmethod
    def _set_system_user_password(username: str, password: str) -> None:
        """Set the password for the local system user."""
        subprocess.run(
            ["/usr/sbin/chpasswd"],
            check=True,
            capture_output=True,
            text=True,
            input=f"{username}:{password}",
        )  # nosec B603

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
