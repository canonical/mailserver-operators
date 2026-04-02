#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Dovecot IMAP/POP3 mail server charm."""

import logging
import os
import shutil
import socket
import subprocess
from pathlib import Path

import jinja2
from charmhelpers.core import host
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus

from charms.operator_libs_linux.v0 import apt

logger = logging.getLogger(__name__)


class DovecotCharm(CharmBase):
    """Dovecot IMAP/POP3 mail server charm."""

    def __init__(self, *args):
        super().__init__(*args)

        # Events
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.clear_queue_action, self._on_clear_queue_action)
        self.framework.observe(self.on.gdpr_archive_action, self._on_gdpr_archive)
        self.framework.observe(self.on.gdpr_delete_action, self._on_gdpr_delete)
        self.framework.observe(self.on.gdpr_takeout_action, self._on_gdpr_takeout)
        self.framework.observe(self.on.replicas_relation_changed, self._on_replicas_changed)
        self.framework.observe(self.on.force_sync_action, self._on_force_sync)

        # Paths
        self.mail_root = "/srv/mail"
        self.encrypted_mountpoint = "/srv"
        self.templates_dir = self.charm_dir.joinpath("templates")

        # Template system
        self.jinja = jinja2.Environment(loader=jinja2.FileSystemLoader(self.templates_dir))

        # Dovecot config
        self.dovecot_conf_template = "dovecot.conf.tmpl"
        self.dovecot_conf_target = "/etc/dovecot/conf.d/99-local-dovecot-charm.conf"

        # Procmail config
        self.procmailrc_template = "procmailrc.tmpl"
        self.procmailrc_target = "/etc/procmailrc"

        # GDPR archive/takeout directories
        self.gdpr_archive_dir = "/srv/mail/archives"
        self.gdpr_takeout_dir = "/tmp/gdpr-takeout"

        # Sync to secondary
        self.sync_smtp_aliases_target = "/usr/local/bin/sync-smtp-aliases.sh"
        self.sync_to_secondary_target = "/usr/local/bin/sync-to-secondary.sh"
        self.sync_to_secondary_cronjob_target = "/etc/cron.d/sync-to-secondary"
        self.sync_to_secondary_template = "sync-to-secondary.sh.tmpl"
        self.sync_to_secondary_cronjob_template = "sync-to-secondary_cron.tmpl"

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
        logger.warning("setting up ssh")
        self._setup_ssh_keys()
        logger.warning("finished setting up ssh")
        if self._is_primary:
            self._install_mail_sync_script()
            self._setup_mail_sync_cronjob()
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
            subprocess.run(
                ["postconf", "-e", 'mailbox_command=/usr/bin/procmail -a "$EXTENSION"'],
                check=True,
            )
            self._systemctl("restart", "postfix")
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to configure postfix: {e}")

        self.unit.status = MaintenanceStatus("Procmail configuration updated")

    def _systemctl(self, *args):
        """Run the requested systemctl command."""
        cmd = ["systemctl"]
        cmd.extend(args)
        logger.debug("running: %s", " ".join(cmd))
        subprocess.run(cmd, capture_output=True, check=True)

    def _on_clear_queue_action(self, event):
        """Handle the clear-queue action."""
        queue_to_clear = event.params["queue"]
        command = ["postsuper", "-d", "ALL"]

        if queue_to_clear == "all":
            logger.warning("Running clear-queue action: DELETING ALL mail from Postfix queue.")
        else:
            command.append("deferred")
            logger.info("Running clear-queue action: Deleting deferred mail from Postfix queue.")

        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True)
            event.set_results({"status": "success", "output": result.stdout})
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to clear Postfix queue: {e.stderr}")
            event.fail(f"Failed to run postsuper: {e.stderr}")

    def _on_gdpr_archive(self, event):
        """Archive a user's mailbox for long-term retention."""
        username = event.params["username"]
        compress = event.params.get("compress", True)
        archive_dir = f"{self.gdpr_archive_dir}/{username}"

        logger.info(f"GDPR archive: archiving mailbox for user '{username}'")

        try:
            os.makedirs(archive_dir, exist_ok=True)

            subprocess.run(
                ["doveadm", "backup", "-u", username, f"mdbox:{archive_dir}/"],
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info(f"Mailbox for '{username}' backed up to {archive_dir}")

            result_path = archive_dir
            if compress:
                tar_path = f"{self.gdpr_archive_dir}/{username}.tar.gz"
                subprocess.run(
                    ["tar", "-czf", tar_path, "-C", self.gdpr_archive_dir, username],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                shutil.rmtree(archive_dir)
                result_path = tar_path
                logger.info(f"Archive compressed to {tar_path}")

            event.set_results({"status": "success", "path": result_path})
        except subprocess.CalledProcessError as e:
            msg = f"Failed to archive mailbox for '{username}': {e.stderr}"
            logger.error(msg)
            event.fail(msg)

    def _on_gdpr_delete(self, event):
        """Permanently delete a user's mailbox (GDPR right to erasure)."""
        username = event.params["username"]
        confirm = event.params.get("confirm", False)

        if not confirm:
            event.fail("Deletion not confirmed. Set confirm=true to proceed.")
            return

        logger.warning(f"GDPR delete: permanently deleting mailbox for user '{username}'")

        try:
            subprocess.run(
                ["doveadm", "expunge", "-u", username, "mailbox", "*", "all"],
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info(f"All mail expunged for user '{username}'")

            user_mail_dir = os.path.join(self.mail_root, username)
            if os.path.exists(user_mail_dir):
                shutil.rmtree(user_mail_dir)
                logger.info(f"Mail directory removed: {user_mail_dir}")

            event.set_results(
                {"status": "success", "message": f"Mailbox for '{username}' deleted"}
            )
        except subprocess.CalledProcessError as e:
            msg = f"Failed to delete mailbox for '{username}': {e.stderr}"
            logger.error(msg)
            event.fail(msg)

    def _on_gdpr_takeout(self, event):
        """Export a user's mail data in a portable format (GDPR data portability)."""
        username = event.params["username"]
        export_format = event.params.get("format", "maildir")
        export_dir = f"{self.gdpr_takeout_dir}/{username}"

        logger.info(f"GDPR takeout: exporting mailbox for user '{username}' as {export_format}")

        try:
            os.makedirs(export_dir, exist_ok=True)

            if export_format == "maildir":
                subprocess.run(
                    [
                        "doveadm",
                        "sync",
                        "-u",
                        username,
                        f"maildir:{export_dir}/:LAYOUT=fs",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            else:
                mbox_path = f"{export_dir}/{username}.mbox"
                result = subprocess.run(
                    [
                        "doveadm",
                        "fetch",
                        "-u",
                        username,
                        "text",
                        "mailbox",
                        "*",
                        "all",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                with open(mbox_path, "w") as f:
                    f.write(result.stdout)

            tar_path = f"{self.gdpr_takeout_dir}/{username}-takeout.tar.gz"
            subprocess.run(
                ["tar", "-czf", tar_path, "-C", self.gdpr_takeout_dir, username],
                check=True,
                capture_output=True,
                text=True,
            )
            shutil.rmtree(export_dir)

            logger.info(f"Takeout export created at {tar_path}")
            event.set_results({"status": "success", "path": tar_path})
        except subprocess.CalledProcessError as e:
            msg = f"Failed to export mailbox for '{username}': {e.stderr}"
            logger.error(msg)
            event.fail(msg)

    @property
    def _secondary_hostname(self):
        """Return the hostname/IP of the secondary unit."""
        relation = self.model.get_relation("replicas")
        if not relation:
            return None

        for unit in relation.units:
            return (
                relation.data[unit].get("hostname")
                or relation.data[unit].get("private-address")
                or relation.data[unit].get("ingress-address")
            )

        return None

    def _setup_ssh_keys(self):
        """Generate SSH key and share public key via peer relation."""
        ssh_dir = Path("/root/.ssh")
        ssh_dir.mkdir(mode=0o700, exist_ok=True)
        key_file = ssh_dir / "id_ed25519"

        if not key_file.exists():
            logger.warning("keyfile not there")
            os.system(f'ssh-keygen -t ed25519 -N "" -f {key_file}')

        pub_key = (ssh_dir / "id_ed25519.pub").read_text().strip()
        relation = self.model.get_relation("replicas")
        if relation:
            relation.data[self.unit]["public_key"] = pub_key
            relation.data[self.unit]["hostname"] = socket.gethostname()

        config_file = ssh_dir / "config"
        if not config_file.exists():
            config_file.write_text("Host *\n    StrictHostKeyChecking no\n")
            config_file.chmod(0o600)

    def _on_replicas_changed(self, event):
        """Handle replicas relation changed — sync SSH authorized_keys."""
        authorized_keys = []
        relation = self.model.get_relation("replicas")

        for unit in relation.units:
            pk = relation.data[unit].get("public_key")
            if pk:
                authorized_keys.append(pk)

        our_pk = relation.data[self.unit].get("public_key")
        if our_pk:
            authorized_keys.append(our_pk)

        auth_file = Path("/root/.ssh/authorized_keys")
        auth_file.write_text("\n".join(authorized_keys))
        auth_file.chmod(0o600)

        self._ensure_root_ssh_configs()

    def _ensure_root_ssh_configs(self):
        """Ensure PermitRootLogin is set in sshd_config."""
        os.system(
            "sed -i 's/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config"
        )
        os.system("systemctl restart ssh")

    def _install_mail_sync_script(self):
        """Install mail pool synchronization script."""
        self.unit.status = MaintenanceStatus("Installing mail pool synchronization script")
        template_context = {
            "secondary_hostname": self._secondary_hostname,
            "mail_root": self.mail_root,
        }
        template = self.jinja.get_template(self.sync_to_secondary_template)
        contents = template.render(template_context)
        host.write_file(self.sync_to_secondary_target, contents, perms=0o755)
        self.unit.status = MaintenanceStatus("Mail pool synchronization installed")

    def _setup_mail_sync_cronjob(self):
        """Set up mail pool synchronization cronjob."""
        self.unit.status = MaintenanceStatus("Setting up mail pool synchronization cronjob")
        template_context = {
            "schedule": self.config.get("sync-schedule", "*/30 * * * *"),
        }
        template = self.jinja.get_template(self.sync_to_secondary_cronjob_template)
        contents = template.render(template_context)
        host.write_file(self.sync_to_secondary_cronjob_target, contents, perms=0o644)
        self._systemctl("restart", "cron")
        self.unit.status = MaintenanceStatus("Mail pool synchronization cronjob has been set up")

    def _on_force_sync(self, event):
        """Force synchronization with secondary unit."""
        if not self._is_primary:
            event.fail("This action can only be run on the primary unit.")
            return

        if not self._secondary_hostname:
            event.fail("No secondary unit found to sync to.")
            return

        try:
            cmd = [self.sync_to_secondary_target]
            logger.info(f"Running manual sync: {' '.join(cmd)}")
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            event.set_results({"result": "Sync completed successfully"})
        except subprocess.CalledProcessError as e:
            msg = f"Sync failed: {e.stderr}"
            logger.error(msg)
            event.fail(msg)


if __name__ == "__main__":  # pragma: nocover
    main(DovecotCharm)
