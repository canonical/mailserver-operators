# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Dovecot setup manager for the Dovecot charm."""

from __future__ import annotations

import logging
import shutil
import subprocess  # nosec
import typing
from pathlib import Path

from charmhelpers.core import host
from charmlibs import systemd
from ops.model import MaintenanceStatus

from constants import (
    DOVECOT_CONF_TARGET,
    DOVECOT_CONF_TEMPLATE,
    ENCRYPTED_MOUNTPOINT,
    MAIL_ROOT,
    PROCMAILRC_TARGET,
    PROCMAILRC_TEMPLATE,
    TLS_CERT_DIR,
)
from exceptions import ConfigurationError

if typing.TYPE_CHECKING:
    from charm import DovecotCharm
    from dovecot_config import DovecotConfig

logger = logging.getLogger(__name__)


class DovecotSetup:
    """Manages Dovecot, TLS, and procmail configuration.

    Groups the three setup steps that run during every reconcile after
    Dovecot is confirmed installed.  Injected into DovecotCharm so unit
    tests can substitute a no-op implementation without patching.
    """

    def __init__(self, charm: DovecotCharm) -> None:
        self._charm = charm

    def is_installed(self) -> bool:
        """Return True if the doveconf binary is present on PATH."""
        return shutil.which("doveconf") is not None

    def setup_tls(self, dovecot_config: DovecotConfig) -> None:
        """Write TLS cert+key to disk from the certificates relation.

        Raises:
            ConfigurationError: If no TLS relation exists or the certificate
                has not been issued yet.
        """
        from charmlibs.interfaces.tls_certificates import CertificateRequestAttributes

        if not self._charm._tls:
            raise ConfigurationError(
                "TLS certificates relation not available. "
                "Integrate with a TLS provider using the 'certificates' relation."
            )

        cert_request = CertificateRequestAttributes(
            common_name=dovecot_config.mailname,
            sans_dns=frozenset([dovecot_config.mailname]),
        )
        provider_cert, private_key = self._charm._tls.get_assigned_certificate(cert_request)
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

    def setup_dovecot(self, dovecot_config: DovecotConfig) -> None:
        """Render and validate the Dovecot configuration file.

        Raises:
            ConfigurationError: If dovecot configuration validation fails.
        """
        self._charm.unit.status = MaintenanceStatus("Setting up and configuring dovecot")
        template_context = {
            "dovecot_chroot": ENCRYPTED_MOUNTPOINT,
            "mail_root": MAIL_ROOT,
            "mailname": dovecot_config.mailname,
            "postmaster_address": dovecot_config.postmaster_address,
        }
        template = self._charm.jinja.get_template(DOVECOT_CONF_TEMPLATE)
        contents = template.render(template_context)
        host.write_file(DOVECOT_CONF_TARGET, contents, perms=0o644)
        if not self._validate_dovecot_config():
            raise ConfigurationError("Invalid Dovecot configuration, check logs for details")
        systemd.service_reload("dovecot", restart_on_failure=True)
        self._charm.unit.status = MaintenanceStatus("Dovecot configuration updated")

    def _validate_dovecot_config(self) -> bool:
        """Run doveconf to validate the written configuration.

        Returns:
            bool: True if configuration is valid, False otherwise.
        """
        try:
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

    def setup_procmail(self, mailname: str) -> None:
        """Render procmail config and configure Postfix to use it.

        Args:
            mailname: The mail domain this unit accepts mail for.

        Raises:
            ConfigurationError: If postfix configuration fails.
        """
        self._charm.unit.status = MaintenanceStatus("Setting up and configuring procmail")

        mail_root = Path(MAIL_ROOT)
        mail_root.mkdir(parents=True, exist_ok=True)
        mail_root.chmod(0o1777)

        template_context = {"mail_root": MAIL_ROOT}
        template = self._charm.jinja.get_template(PROCMAILRC_TEMPLATE)
        contents = template.render(template_context)
        host.write_file(PROCMAILRC_TARGET, contents, perms=0o644)

        postconf_settings = [
            # mailbox_command applies only to the Postfix *local* delivery agent and is
            # used here for local system users not covered by virtual_mailbox_domains.
            'mailbox_command=/usr/bin/procmail -a "$EXTENSION"',
            # virtual_mailbox_domains + virtual_transport route mail for the charm's
            # primary domain directly to Dovecot via the LMTP Unix socket, bypassing
            # the local delivery agent (and therefore mailbox_command) for that domain.
            f"virtual_mailbox_domains = {mailname}",
            "virtual_transport = lmtp:unix:private/dovecot-lmtp",
            "smtpd_reject_unlisted_recipient = no",
            "inet_interfaces = all",
        ]
        try:
            for setting in postconf_settings:
                subprocess.run(
                    ["/usr/sbin/postconf", "-e", setting],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            systemd.service_reload("postfix", restart_on_failure=True)
        except subprocess.CalledProcessError as e:
            logger.exception(f"Failed to configure postfix: {e}")
            raise ConfigurationError(f"Failed to configure postfix: {e.stderr}") from e
