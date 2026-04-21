#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Dovecot charm."""

import logging
import shutil
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


class DovecotCharm(CharmBase):
    """Dovecot IMAP/POP3 mail server charm."""

    def __init__(self, *args):
        super().__init__(*args)

        # Events
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._reconcile)
        self.framework.observe(self.on.config_changed, self._reconcile)
        self.framework.observe(self.on.upgrade_charm, self._on_install)
        self.framework.observe(self.on.clear_queue_action, self._on_clear_queue_action)
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

    def _on_install(self, event):
        """Handle install event."""
        self.unit.status = MaintenanceStatus("Installing packages")
        self._install()
        self._reconcile(event)

    def _reconcile(self, event):
        """Reconcile charm state for install, upgrade, config-changed, and storage events."""
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
        self._open_ports()
        self.unit.status = ops.ActiveStatus()

    def _install(self):
        """Perform basic installation."""
        self.unit.status = MaintenanceStatus("Installing required dependencies")
        apt.update()
        apt.add_package(REQUIRED_PACKAGES)
        shutil.copy(HOSTNAME_FILE, MAILNAME_FILE)
        self.unit.status = MaintenanceStatus("Charm installation done")

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
