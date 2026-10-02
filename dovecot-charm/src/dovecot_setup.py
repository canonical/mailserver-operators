# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Dovecot setup manager for the Dovecot charm."""

from __future__ import annotations

import grp
import logging
import os
import pwd
import shutil
import subprocess  # nosec
import typing
from pathlib import Path

from charmhelpers.core import host
from charmlibs import systemd
from ops.model import MaintenanceStatus

from constants import (
    DOVECOT_AUTH_CONF_TARGET,
    DOVECOT_CONF_TARGET,
    DOVECOT_CONF_TEMPLATE,
    DOVECOT_USERS_FILE,
    ENCRYPTED_MOUNTPOINT,
    MAIL_ROOT,
    PROCMAILRC_TARGET,
    PROCMAILRC_TEMPLATE,
    TLS_CERT_DIR,
    VMAIL_GID,
    VMAIL_GROUP,
    VMAIL_UID,
    VMAIL_USER,
)
from credentials import (
    atomic_write,
    parse_credential_entries,
    render_dovecot_credentials,
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
            "users_file": str(DOVECOT_USERS_FILE),
            "vmail_group": VMAIL_GROUP,
            "vmail_user": VMAIL_USER,
        }
        # Disable the packaged PAM passdb before defining the virtual-user
        # passdb and userdb in the charm's local configuration.
        host.write_file(
            DOVECOT_AUTH_CONF_TARGET,
            "",
            perms=0o644,
        )
        template = self._charm.jinja.get_template(DOVECOT_CONF_TEMPLATE)
        contents = template.render(template_context)
        host.write_file(DOVECOT_CONF_TARGET, contents, perms=0o644)
        if not self._validate_dovecot_config():
            raise ConfigurationError("Invalid Dovecot configuration, check logs for details")
        systemd.service_reload("dovecot", restart_on_failure=True)
        self._charm.unit.status = MaintenanceStatus("Dovecot configuration updated")

    def setup_credentials(self, dovecot_config: DovecotConfig) -> None:
        """Install virtual-user support and configure authentication credentials."""
        self._charm.unit.status = MaintenanceStatus("Configuring mail credentials")
        self._ensure_virtual_mail_identity()
        credentials = parse_credential_entries(dovecot_config.mail_users)
        atomic_write(
            DOVECOT_USERS_FILE,
            render_dovecot_credentials(credentials),
            user="root",
            group="dovecot",
            mode=0o640,
        )

    def _ensure_virtual_mail_identity(self) -> None:
        """Create the stable virtual mailbox user and group."""
        self._ensure_virtual_mail_group()
        self._ensure_virtual_mail_user()

        mail_root = Path(MAIL_ROOT)
        mail_root.mkdir(parents=True, exist_ok=True)
        os.chown(mail_root, VMAIL_UID, VMAIL_GID)
        mail_root.chmod(0o750)

    @staticmethod
    def _ensure_virtual_mail_group() -> None:
        """Create the virtual mailbox group with its stable GID."""
        try:
            group = grp.getgrnam(VMAIL_GROUP)
        except KeyError:
            try:
                existing_group = grp.getgrgid(VMAIL_GID)
            except KeyError:
                existing_group = None
            if existing_group:
                raise ConfigurationError(
                    f"GID {VMAIL_GID} is already used by group {existing_group.gr_name!r}"
                )
            try:
                subprocess.run(
                    ["/usr/sbin/groupadd", "--system", "--gid", str(VMAIL_GID), VMAIL_GROUP],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as exc:
                raise ConfigurationError(
                    f"Failed to create virtual mail group: {exc.stderr}"
                ) from exc
        else:
            if group.gr_gid != VMAIL_GID:
                raise ConfigurationError(
                    f"Group {VMAIL_GROUP!r} uses GID {group.gr_gid}, expected {VMAIL_GID}"
                )

    @staticmethod
    def _ensure_virtual_mail_user() -> None:
        """Create the virtual mailbox user with its stable UID."""
        try:
            user = pwd.getpwnam(VMAIL_USER)
        except KeyError:
            try:
                existing_user = pwd.getpwuid(VMAIL_UID)
            except KeyError:
                existing_user = None
            if existing_user:
                raise ConfigurationError(
                    f"UID {VMAIL_UID} is already used by user {existing_user.pw_name!r}"
                )
            try:
                subprocess.run(
                    [
                        "/usr/sbin/useradd",
                        "--system",
                        "--uid",
                        str(VMAIL_UID),
                        "--gid",
                        VMAIL_GROUP,
                        "--home-dir",
                        MAIL_ROOT,
                        "--no-create-home",
                        "--shell",
                        "/usr/sbin/nologin",
                        VMAIL_USER,
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as exc:
                raise ConfigurationError(
                    f"Failed to create virtual mail user: {exc.stderr}"
                ) from exc
        else:
            if user.pw_uid != VMAIL_UID or user.pw_gid != VMAIL_GID:
                raise ConfigurationError(
                    f"User {VMAIL_USER!r} uses UID/GID {user.pw_uid}/{user.pw_gid}, "
                    f"expected {VMAIL_UID}/{VMAIL_GID}"
                )

    def _validate_dovecot_config(self) -> bool:
        """Run doveconf to validate the written configuration.

        Returns:
            bool: True if configuration is valid, False otherwise.
        """
        try:
            subprocess.run(
                ["/usr/bin/doveconf"],
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

        template = self._charm.jinja.get_template(PROCMAILRC_TEMPLATE)
        contents = template.render({"mail_root": MAIL_ROOT})
        host.write_file(PROCMAILRC_TARGET, contents, perms=0o644)

        postconf_settings = [
            'mailbox_command=/usr/bin/procmail -a "$EXTENSION"',
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
