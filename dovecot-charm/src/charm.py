#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Dovecot charm."""

import logging
import shutil
import socket
import subprocess  # nosec
import typing
from pathlib import Path

import jinja2
import ops
from charmhelpers.core import host
from charmlibs import apt, systemd
from charmlibs.interfaces.tls_certificates import (
    CertificateRequestAttributes,
    TLSCertificatesRequiresV4,
)
from ops.charm import CharmBase
from ops.main import main
from ops.model import BlockedStatus, MaintenanceStatus

from constants import (
    DOVECOT_CONF_TARGET,
    DOVECOT_CONF_TEMPLATE,
    ENCRYPTED_MOUNTPOINT,
    HOSTNAME_FILE,
    MAIL_ROOT,
    MAILNAME_FILE,
    PEER_RELATION_NAME,
    PROCMAILRC_TARGET,
    PROCMAILRC_TEMPLATE,
    REQUIRED_PACKAGES,
    TEMPLATES_DIR,
    TLS_CERT_DIR,
)
from dovecot_config import DovecotConfig, DovecotConfigInvalidError, DovecotConfigSecretError
from exceptions import CharmBlockedError, ConfigurationError
from storage import ensure_storage_ready, teardown_detaching_storage

logger = logging.getLogger(__name__)

# HA sync paths
SYNC_TO_SECONDARY_TARGET = "/usr/local/bin/sync-to-secondary.sh"
SYNC_TO_SECONDARY_CRONJOB_TARGET = "/etc/cron.d/sync-to-secondary"
SYNC_TO_SECONDARY_TEMPLATE = "sync-to-secondary.sh.tmpl"
SYNC_TO_SECONDARY_CRONJOB_TEMPLATE = "sync-to-secondary_cron.tmpl"

SSHD_CONFIG = Path("/etc/ssh/sshd_config")
SSH_DIR = Path("/root/.ssh")
SSH_HOST_KEY_FILE = Path("/etc/ssh/ssh_host_ed25519_key.pub")


class DovecotCharm(CharmBase):
    """Dovecot IMAP/POP3 mail server charm."""

    def __init__(self, *args):
        super().__init__(*args)

        # Events — every event except install goes through _reconcile.
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._reconcile)
        self.framework.observe(self.on.config_changed, self._reconcile)
        self.framework.observe(self.on.upgrade_charm, self._on_install)
        self.framework.observe(self.on.clear_queue_action, self._on_clear_queue_action)
        self.framework.observe(self.on.mail_data_storage_attached, self._reconcile)
        self.framework.observe(self.on.mail_data_storage_detaching, self._reconcile)
        self.framework.observe(self.on.replicas_relation_changed, self._reconcile)
        self.framework.observe(self.on.force_sync_action, self._on_force_sync)

        self.framework.observe(
            self.on[PEER_RELATION_NAME].relation_created,
            self._on_peer_relation_created,
        )
        # Template system
        self.jinja = jinja2.Environment(
            loader=jinja2.FileSystemLoader(TEMPLATES_DIR), autoescape=True
        )

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
            self.framework.observe(self._tls.on.certificate_available, self._reconcile)

    def get_units(self) -> typing.List[str]:
        """Return a list of all units in the application.

        Returns:
            List[str]: List of unit names.
        """
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

    @property
    def _secondary_hostname(self) -> typing.Optional[str]:
        """Return the hostname/IP of the first remote peer unit, or None."""
        relation = self.model.get_relation(PEER_RELATION_NAME)
        if not relation:
            return None

        for unit in relation.units:
            hostname = (
                relation.data[unit].get("hostname")
                or relation.data[unit].get("private-address")
                or relation.data[unit].get("ingress-address")
            )
            if hostname:
                return hostname

        return None

    def _get_dovecot_config(self) -> DovecotConfig:
        """Craft the DovecotConfig from charm configuration and validate it.

        Returns:
            DovecotConfig: The validated configuration.

        Raises:
            ConfigurationError: If configuration is invalid.
        """
        try:
            return DovecotConfig.from_charm(self)
        except DovecotConfigInvalidError as exc:
            logger.exception(f"Configuration validation error: {exc}")
            msg = ", ".join([str(*err["loc"]) for err in exc.errors()])
            raise ConfigurationError(
                f"Invalid charm configuration, check logs for details: {msg}"
            ) from exc
        except DovecotConfigSecretError as exc:
            logger.exception(f"Secret retrieval error: {exc}")
            raise ConfigurationError(str(exc)) from exc

    # -- Event handlers -------------------------------------------------------

    def _on_install(self, event):
        """Handle install event — install packages only, then reconcile."""
        self.unit.status = MaintenanceStatus("Installing packages")
        self._install()
        self._reconcile(event)

    def _reconcile(self, event):
        """Reconcile charm state for every event except install.

        Holistic handler: storage → TLS → dovecot → procmail → HA → ports.
        """
        self.unit.status = MaintenanceStatus("Configuring charm")
        try:
            dovecot_config = self._get_dovecot_config()
            ensure_storage_ready(self, dovecot_config=dovecot_config)
            teardown_detaching_storage(self)
        except CharmBlockedError as e:
            self.unit.status = BlockedStatus(str(e))
            return
        if not shutil.which("doveconf"):
            logger.warning("Dovecot not installed yet, deferring configuration")
            return
        try:
            self._setup_tls(dovecot_config)
            self._setup_dovecot(dovecot_config)
            self._setup_procmail()
        except ConfigurationError as e:
            self.unit.status = BlockedStatus(str(e))
            return
        # HA: SSH keys, authorized_keys, known_hosts, sync script + cronjob
        self._setup_ssh_keys()
        self._sync_authorized_keys()
        self._sync_known_hosts()
        if self._is_primary:
            self._install_mail_sync_script()
            self._setup_mail_sync_cronjob()
        self._open_ports()
        self.unit.status = ops.ActiveStatus()

    # -- Installation ---------------------------------------------------------

    def _install(self):
        """Perform basic installation — packages and hostname only."""
        self.unit.status = MaintenanceStatus("Installing required dependencies")
        apt.update()
        apt.add_package(REQUIRED_PACKAGES)
        shutil.copy(HOSTNAME_FILE, MAILNAME_FILE)
        self.unit.status = MaintenanceStatus("Charm installation done")

    # -- Service configuration ------------------------------------------------

    def _open_ports(self):
        """Open mail ports (TLS-only: plaintext 143/110 are not exposed)."""
        self.unit.open_port("tcp", 993)
        self.unit.open_port("tcp", 995)
        self.unit.open_port("tcp", 4190)
        self.unit.open_port("tcp", 9900)

    def _setup_dovecot(self, dovecot_config: DovecotConfig) -> None:
        """Set up and configure dovecot.

        Raises:
            ConfigurationError: If dovecot configuration validation fails.
        """
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
            raise ConfigurationError("Invalid Dovecot configuration, check logs for details")
        systemd.service_reload("dovecot", restart_on_failure=True)
        self.unit.status = MaintenanceStatus("Dovecot configuration updated")

    def _validate_dovecot_config(self, config: DovecotConfig) -> bool:
        """Validate the Dovecot configuration.

        Returns:
            bool: True if configuration is valid, False otherwise.
        """
        try:
            # The command and arguments are fixed literals with no user-controlled input.
            subprocess.run(
                ["/usr/bin/doveconf", "-c", DOVECOT_CONF_TARGET],
                check=True,
                capture_output=True,
                text=True,
            )
            return True
        except subprocess.CalledProcessError as e:
            logger.exception(f"Failed to validate dovecot configuration: {e}")
            return False

    def _setup_procmail(self) -> None:
        """Set up and configure procmail default file.

        Raises:
            ConfigurationError: If postfix configuration fails.
        """
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
                text=True,
            )
            systemd.service_reload("postfix", restart_on_failure=True)
        except subprocess.CalledProcessError as e:
            logger.exception(f"Failed to configure postfix: {e}")
            raise ConfigurationError(f"Failed to configure postfix: {e.stderr}") from e

    def _setup_tls(self, dovecot_config: DovecotConfig) -> None:
        """Write TLS cert+key to disk from the certificates relation.

        Called from _reconcile before _setup_dovecot so the cert files are
        present when dovecot.conf is rendered and validated.

        Raises:
            ConfigurationError: If no TLS relation exists or the certificate
                has not been issued yet.
        """
        if not self._tls:
            raise ConfigurationError(
                "TLS certificates relation not available. "
                "Integrate with a TLS provider using the 'certificates' relation."
            )

        cert_request = CertificateRequestAttributes(
            common_name=dovecot_config.mailname,
            sans_dns=frozenset([dovecot_config.mailname]),
        )
        provider_cert, private_key = self._tls.get_assigned_certificate(cert_request)
        if not provider_cert or not private_key:
            raise ConfigurationError(
                "TLS certificate not yet available from the certificates relation."
            )

        TLS_CERT_DIR.mkdir(parents=True, exist_ok=True)
        cert_path = TLS_CERT_DIR / f"{dovecot_config.mailname}.pem"
        key_path = TLS_CERT_DIR / f"{dovecot_config.mailname}.key"

        cert_content = str(provider_cert.certificate)
        if provider_cert.ca:
            cert_content += "\n" + str(provider_cert.ca)
        cert_path.write_text(cert_content)
        cert_path.chmod(0o644)
        logger.info(f"TLS certificate written to {cert_path}")

        key_path.write_text(str(private_key))
        key_path.chmod(0o600)
        logger.info(f"TLS private key written to {key_path}")

    # -- HA / SSH key exchange ------------------------------------------------

    def _setup_ssh_keys(self):
        """Generate an SSH key pair if absent and publish keys via the peer relation.

        Publishes both the user public key (for authorized_keys) and the host
        public key (for known_hosts) so peers can verify each other's identity
        without disabling StrictHostKeyChecking.
        """
        SSH_DIR.mkdir(mode=0o700, exist_ok=True)
        key_file = SSH_DIR / "id_ed25519"

        if not key_file.exists():
            subprocess.run(
                ["/usr/bin/ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key_file)],
                check=True,
                capture_output=True,
            )

        pub_key_file = SSH_DIR / "id_ed25519.pub"
        if not pub_key_file.exists():
            logger.error("SSH public key file not found after key generation")
            return

        pub_key = pub_key_file.read_text().strip()
        relation = self.model.get_relation(PEER_RELATION_NAME)
        if relation:
            relation.data[self.unit]["public_key"] = pub_key
            relation.data[self.unit]["hostname"] = socket.gethostname()

            # Publish the host public key so peers can populate known_hosts
            if SSH_HOST_KEY_FILE.exists():
                host_key = SSH_HOST_KEY_FILE.read_text().strip()
                relation.data[self.unit]["ssh_host_key"] = host_key

    def _sync_authorized_keys(self):
        """Collect public keys from all peer units and write authorized_keys."""
        relation = self.model.get_relation(PEER_RELATION_NAME)
        if not relation:
            return

        authorized_keys = []
        for unit in relation.units:
            pk = relation.data[unit].get("public_key")
            if pk:
                authorized_keys.append(pk)

        our_pk = relation.data[self.unit].get("public_key")
        if our_pk:
            authorized_keys.append(our_pk)

        if not authorized_keys:
            return

        auth_file = SSH_DIR / "authorized_keys"
        auth_file.write_text("\n".join(authorized_keys) + "\n")
        auth_file.chmod(0o600)

        self._ensure_root_ssh_login()

    def _sync_known_hosts(self):
        """Populate known_hosts with peer SSH host keys from the peer relation.

        Each peer publishes its host public key and hostname on the relation.
        This method writes those into known_hosts so SSH connections between
        units use StrictHostKeyChecking (the default) instead of disabling it.
        """
        relation = self.model.get_relation(PEER_RELATION_NAME)
        if not relation:
            return

        entries = []
        for unit in relation.units:
            host_key = relation.data[unit].get("ssh_host_key")
            hostname = relation.data[unit].get("hostname")
            if host_key and hostname:
                # known_hosts format: <hostname> <key_type> <key_data>
                entries.append(f"{hostname} {host_key}")

        if not entries:
            return

        known_hosts_file = SSH_DIR / "known_hosts"
        known_hosts_file.write_text("\n".join(entries) + "\n")
        known_hosts_file.chmod(0o600)

    def _ensure_root_ssh_login(self):
        """Set PermitRootLogin to prohibit-password in sshd_config and reload sshd."""
        if SSHD_CONFIG.exists():
            content = SSHD_CONFIG.read_text()
            new_content = ""
            found = False
            for line in content.splitlines(keepends=True):
                stripped = line.lstrip("#").strip()
                if stripped.startswith("PermitRootLogin"):
                    new_content += "PermitRootLogin prohibit-password\n"
                    found = True
                else:
                    new_content += line
            if not found:
                new_content += "\nPermitRootLogin prohibit-password\n"
            if new_content != content:
                SSHD_CONFIG.write_text(new_content)
                systemd.service_reload("ssh", restart_on_failure=True)

    def _install_mail_sync_script(self):
        """Render and install the mail pool synchronization script.

        Skipped when the secondary hostname is not yet known (no remote peer).
        """
        secondary = self._secondary_hostname
        if not secondary:
            logger.info("Secondary hostname not yet known; skipping sync script installation")
            return

        self.unit.status = MaintenanceStatus("Installing mail pool synchronization script")
        template_context = {
            "secondary_hostname": secondary,
            "mail_root": MAIL_ROOT,
        }
        template = self.jinja.get_template(SYNC_TO_SECONDARY_TEMPLATE)
        contents = template.render(template_context)
        host.write_file(SYNC_TO_SECONDARY_TARGET, contents, perms=0o755)

    def _setup_mail_sync_cronjob(self):
        """Set up the mail pool synchronization cronjob."""
        if not self._secondary_hostname:
            logger.info("Secondary hostname not yet known; skipping cronjob setup")
            return

        self.unit.status = MaintenanceStatus("Setting up mail pool synchronization cronjob")
        template_context = {
            "schedule": self.config.get("sync-schedule", "*/30 * * * *"),
        }
        template = self.jinja.get_template(SYNC_TO_SECONDARY_CRONJOB_TEMPLATE)
        contents = template.render(template_context)
        host.write_file(SYNC_TO_SECONDARY_CRONJOB_TARGET, contents, perms=0o644)
        systemd.service_restart("cron")

    # -- Actions --------------------------------------------------------------

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

    def _on_force_sync(self, event):
        """Force synchronization with secondary unit."""
        if not self._is_primary:
            event.fail("This action can only be run on the primary unit.")
            return

        if not self._secondary_hostname:
            event.fail("No secondary unit found to sync to.")
            return

        try:
            cmd = [SYNC_TO_SECONDARY_TARGET]
            logger.info(f"Running manual sync: {' '.join(cmd)}")
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            event.set_results({"result": "Sync completed successfully"})
        except subprocess.CalledProcessError as e:
            msg = f"Sync failed: {e.stderr}"
            logger.error(msg)
            event.fail(msg)

    def _setup_tls(self, dovecot_config: DovecotConfig) -> None:
        """Write TLS cert+key to disk from the certificates relation.

        Called from _reconcile before _setup_dovecot so the cert files are
        present when dovecot.conf is rendered and validated.

        Raises:
            ConfigurationError: If no TLS relation exists or the certificate
                has not been issued yet.
        """
        if not self._tls:
            raise ConfigurationError(
                "TLS certificates relation not available. "
                "Integrate with a TLS provider using the 'certificates' relation."
            )

        cert_request = CertificateRequestAttributes(
            common_name=dovecot_config.mailname,
            sans_dns=frozenset([dovecot_config.mailname]),
        )
        provider_cert, private_key = self._tls.get_assigned_certificate(cert_request)
        if not provider_cert or not private_key:
            raise ConfigurationError(
                "TLS certificate not yet available from the certificates relation."
            )

        TLS_CERT_DIR.mkdir(parents=True, exist_ok=True)
        cert_path = TLS_CERT_DIR / f"{dovecot_config.mailname}.pem"
        key_path = TLS_CERT_DIR / f"{dovecot_config.mailname}.key"

        cert_content = str(provider_cert.certificate)
        if provider_cert.ca:
            cert_content += "\n" + str(provider_cert.ca)
        cert_path.write_text(cert_content)
        cert_path.chmod(0o644)
        logger.info(f"TLS certificate written to {cert_path}")

        key_path.write_text(str(private_key))
        key_path.chmod(0o600)
        logger.info(f"TLS private key written to {key_path}")


if __name__ == "__main__":  # pragma: nocover
    main(DovecotCharm)
