#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Dovecot IMAP/POP3 mail server charm."""

import logging
import os
import shutil
import socket
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

from charms.tls_certificates_interface.v4.tls_certificates import (
    CertificateAvailableEvent,
    CertificateRequestAttributes,
    TLSCertificatesRequiresV4,
)

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
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(self.on.replicas_relation_changed, self._on_replicas_changed)
        self.framework.observe(self.on.force_sync_action, self._on_force_sync)

        self.framework.observe(
            self.on[PEER_RELATION_NAME].relation_created,
            self._on_peer_relation_created,
        )
        # Template system
        self.jinja = jinja2.Environment(
            loader=jinja2.FileSystemLoader(TEMPLATES_DIR), autoescape=True
        )

        # Sync to secondary
        self.sync_smtp_aliases_target = "/usr/local/bin/sync-smtp-aliases.sh"
        self.sync_to_secondary_target = "/usr/local/bin/sync-to-secondary.sh"
        self.sync_to_secondary_cronjob_target = "/etc/cron.d/sync-to-secondary"
        self.sync_to_secondary_template = "sync-to-secondary.sh.tmpl"
        self.sync_to_secondary_cronjob_template = "sync-to-secondary_cron.tmpl"

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

    @property
    def _is_primary(self):
        """Return True if this unit is the configured primary unit."""
        return self.unit.name == self.config.get("primary-unit", "")

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
        self._setup_ssh_keys()
        if self._is_primary:
            self._install_mail_sync_script()
            self._setup_mail_sync_cronjob()
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
                subprocess.run(["umount", self.mail_root], check=True)  # noqa: S607

            if self._manage_luks and os.path.exists("/dev/mapper/mail-data"):
                subprocess.run(["cryptsetup", "luksClose", "mail-data"], check=True)  # noqa: S607
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
                ["dd", "if=/dev/urandom", f"of={keyfile}", "bs=512", "count=8"],  # noqa: S607
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            os.chmod(keyfile, 0o400)
            logger.info("Keyfile generated successfully")

        is_luks = False
        try:
            subprocess.run(
                ["cryptsetup", "isLuks", dev_path],  # noqa: S607
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

        self._configure_crypttab(mapper_name, dev_path, keyfile)
        self._configure_fstab(mapper_path, self.mail_root)

        if not os.path.exists(self.mail_root):
            os.makedirs(self.mail_root)

        if not os.path.ismount(self.mail_root):
            logger.info(f"Mounting {mapper_path} to {self.mail_root}...")
            subprocess.run(["mount", mapper_path, self.mail_root], check=True)  # noqa: S607
            os.chmod(self.mail_root, 0o1777)  # noqa: S103
            logger.info(f"Successfully mounted to {self.mail_root}")

    def _configure_crypttab(self, mapper_name, dev_path, keyfile):
        """Configure /etc/crypttab for persistent LUKS mapping."""
        crypttab_path = "/etc/crypttab"
        entry = f"{mapper_name} {dev_path} {keyfile} luks,discard,noauto\n"

        if os.path.exists(crypttab_path):
            with open(crypttab_path) as f:
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
            with open(fstab_path) as f:
                if mount_point in f.read():
                    logger.info("fstab entry already exists")
                    return

        logger.info(f"Adding fstab entry for {mount_point}")
        with open(fstab_path, "a") as f:
            f.write(entry)
        logger.info("fstab configured")

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
            os.system(f'ssh-keygen -t ed25519 -N "" -f {key_file}')  # noqa: S605

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
        cmd = "sed -i 's/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config"
        os.system(cmd)  # noqa: S605
        os.system("systemctl restart ssh")  # noqa: S605, S607

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

    def _on_certificate_available(self, event: CertificateAvailableEvent):
        """Handle TLS certificate available event."""
        mailname = self.config.get("mailname", "")
        if not mailname:
            logger.warning("Certificate available but mailname not configured")
            return

        self.tls_cert_dir.mkdir(parents=True, exist_ok=True)

        cert_path = self.tls_cert_dir / f"{mailname}.pem"
        key_path = self.tls_cert_dir / f"{mailname}.key"

        cert_content = str(event.certificate.certificate)
        if event.certificate.ca:
            cert_content += "\n" + str(event.certificate.ca)

        cert_path.write_text(cert_content)
        cert_path.chmod(0o644)
        logger.info(f"Certificate written to {cert_path}")

        private_key = self._tls.private_key
        if private_key:
            key_path.write_text(str(private_key))
            key_path.chmod(0o600)
            logger.info(f"Private key written to {key_path}")

        if self._systemctl("is-enabled", "dovecot"):
            self._systemctl("restart", "dovecot")
            logger.info("Dovecot restarted with new TLS certificate")


if __name__ == "__main__":  # pragma: nocover
    main(DovecotCharm)
