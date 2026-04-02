#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Dovecot IMAP/POP3 mail server charm."""

import logging
import os
import shutil
import socket
import stat
import subprocess
from pathlib import Path

import jinja2
from charmhelpers.core import host
from charms.grafana_agent.v0.cos_agent import COSAgentProvider
from charms.tls_certificates_interface.v4.tls_certificates import (
    CertificateAvailableEvent,
    CertificateRequestAttributes,
    TLSCertificatesRequiresV4,
)
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
        self.framework.observe(
            self.on.mail_data_storage_attached, self._on_mail_data_storage_attached
        )
        self.framework.observe(
            self.on.mail_data_storage_detaching, self._on_mail_data_storage_detaching
        )
        self.framework.observe(self.on.update_status, self._on_update_status)

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

        # TLS certificates directory
        self.tls_cert_dir = Path("/etc/dovecot/private")

        # TLS certificates integration
        self._tls = None
        mailname = self.config.get("mailname", "")
        if mailname:
            self._tls = TLSCertificatesRequiresV4(
                charm=self,
                relationship_name="certificates",
                certificate_requests=[
                    CertificateRequestAttributes(
                        common_name=mailname,
                        sans_dns=frozenset([mailname]),
                    )
                ],
                refresh_events=[self.on.config_changed],
            )
            self.framework.observe(
                self._tls.on.certificate_available, self._on_certificate_available
            )

        # COS observability integration
        self._grafana_agent = COSAgentProvider(
            self,
            relation_name="cos-agent",
            metrics_endpoints=[
                {"path": "/metrics", "port": 9900},
            ],
            metrics_rules_dir="./src/prometheus_alert_rules",
            logs_rules_dir="./src/loki_alert_rules",
            dashboard_dirs=["./src/grafana_dashboards"],
            refresh_events=[self.on.config_changed],
        )

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

    @property
    def _manage_luks(self):
        """Return True if the charm should manage LUKS encryption."""
        return bool(self.config.get("manage-luks", True))

    def _mail_storage_mounted(self):
        """Return True if mail storage is mounted."""
        return os.path.ismount(self.mail_root)

    def _on_mail_data_storage_attached(self, event):
        """Handle storage attached event."""
        if not self._manage_luks:
            if self._mail_storage_mounted():
                self.unit.status = ActiveStatus()
            else:
                self.unit.status = BlockedStatus("mail-data not mounted; manage-luks disabled")
                event.defer()
            return

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
            logger.error(f"Failed to setup LUKS storage: {e}")
            self.unit.status = BlockedStatus("Failed to setup LUKS storage")
        except RuntimeError as e:
            logger.error(f"Storage validation failed: {e}")
            self.unit.status = BlockedStatus(str(e))

    def _on_mail_data_storage_detaching(self, event):
        """Handle storage detaching event."""
        try:
            if os.path.ismount(self.mail_root):
                subprocess.run(["umount", self.mail_root], check=True)

            if self._manage_luks and os.path.exists("/dev/mapper/mail-data"):
                subprocess.run(["cryptsetup", "luksClose", "mail-data"], check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to detach storage: {e}")

    def _on_update_status(self, event):
        """Handle update-status event."""
        if not self._manage_luks:
            if self._mail_storage_mounted():
                self.unit.status = ActiveStatus()
            else:
                self.unit.status = BlockedStatus("mail-data not mounted; manage-luks disabled")

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
                ["dd", "if=/dev/urandom", f"of={keyfile}", "bs=512", "count=8"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            os.chmod(keyfile, 0o400)
            logger.info("Keyfile generated successfully")

        is_luks = False
        try:
            subprocess.run(
                ["cryptsetup", "isLuks", dev_path],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            is_luks = True
            logger.info(f"{dev_path} is already a LUKS device")
        except subprocess.CalledProcessError:
            logger.info(f"{dev_path} is not a LUKS device")

        if not is_luks:
            logger.info(f"Formatting {dev_path} as LUKS with keyfile...")
            subprocess.run(
                ["cryptsetup", "luksFormat", dev_path, "--key-file", keyfile, "--batch-mode"],
                check=True,
                capture_output=True,
            )
            logger.info("LUKS format completed")

        if not os.path.exists(mapper_path):
            logger.info(f"Opening LUKS device {dev_path}...")
            subprocess.run(
                ["cryptsetup", "open", dev_path, mapper_name, "--key-file", keyfile],
                check=True,
                capture_output=True,
            )
            logger.info(f"LUKS device opened as {mapper_path}")

            subprocess.run(["dmsetup", "mknodes"], check=True, capture_output=True)
            logger.info("Device mapper nodes refreshed")

        has_fs = False
        try:
            result = subprocess.run(
                ["blkid", mapper_path],
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
            subprocess.run(["mkfs.ext4", "-m", "0", mapper_path], check=True, capture_output=True)
            logger.info("ext4 filesystem created")

        self._configure_crypttab(mapper_name, dev_path, keyfile)
        self._configure_fstab(mapper_path, self.mail_root)

        if not os.path.exists(self.mail_root):
            os.makedirs(self.mail_root)

        if not os.path.ismount(self.mail_root):
            logger.info(f"Mounting {mapper_path} to {self.mail_root}...")
            subprocess.run(["mount", mapper_path, self.mail_root], check=True)
            os.chmod(self.mail_root, 0o1777)
            logger.info(f"Successfully mounted to {self.mail_root}")

    def _configure_crypttab(self, mapper_name, dev_path, keyfile):
        """Configure /etc/crypttab for persistent LUKS mapping."""
        crypttab_path = "/etc/crypttab"
        entry = f"{mapper_name} {dev_path} {keyfile} luks,discard,noauto\n"

        if os.path.exists(crypttab_path):
            with open(crypttab_path, "r") as f:
                if mapper_name in f.read():
                    logger.info("crypttab entry already exists")
                    return

        logger.info(f"Adding crypttab entry for {mapper_name}")
        with open(crypttab_path, "a") as f:
            f.write(entry)
        logger.info("crypttab configured")

    def _configure_fstab(self, mapper_path, mount_point):
        """Configure /etc/fstab for persistent mounting."""
        fstab_path = "/etc/fstab"
        entry = f"{mapper_path} {mount_point} ext4 defaults,noauto 0 2\n"

        if os.path.exists(fstab_path):
            with open(fstab_path, "r") as f:
                if mount_point in f.read():
                    logger.info("fstab entry already exists")
                    return

        logger.info(f"Adding fstab entry for {mount_point}")
        with open(fstab_path, "a") as f:
            f.write(entry)
        logger.info("fstab configured")

    def _on_certificate_available(self, event: CertificateAvailableEvent):
        """Handle TLS certificate available event."""
        mailname = self.config.get("mailname", "")
        if not mailname:
            logger.warning("Certificate available but mailname is not configured")
            return

        self.tls_cert_dir.mkdir(parents=True, exist_ok=True)

        cert_path = self.tls_cert_dir / f"{mailname}.pem"
        key_path = self.tls_cert_dir / f"{mailname}.key"

        cert_content = str(event.certificate)
        if event.ca:
            cert_content += "\n" + str(event.ca)
        if event.chain:
            for chain_cert in event.chain:
                cert_content += "\n" + str(chain_cert)
        host.write_file(str(cert_path), cert_content, perms=0o644)

        if self._tls:
            private_key = self._tls.private_key
            if private_key:
                host.write_file(str(key_path), str(private_key), perms=0o600)
            else:
                logger.error("No private key available from TLS library")
                return

        logger.info(f"TLS certificate written to {cert_path}")
        logger.info(f"TLS private key written to {key_path}")

        if self._systemctl("is-enabled", "dovecot"):
            self._systemctl("restart", "dovecot")
        self.unit.status = ActiveStatus()


if __name__ == "__main__":  # pragma: nocover
    main(DovecotCharm)
