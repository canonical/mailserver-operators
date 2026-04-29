#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Dovecot charm."""

import logging
import os
import shutil
import subprocess  # nosec
import typing
from functools import cached_property
from pathlib import Path

import jinja2
import ops
from charmlibs import apt
from charmlibs.interfaces.tls_certificates import (
    CertificateRequestAttributes,
    TLSCertificatesRequiresV4,
)
from ops.charm import CharmBase
from ops.main import main
from ops.model import BlockedStatus, MaintenanceStatus

from constants import (
    DOVEADM_BIN,
    GDPR_ARCHIVE_DIR,
    GDPR_TAKEOUT_DIR,
    HOSTNAME_FILE,
    MAIL_ROOT,
    MAILNAME_FILE,
    PEER_RELATION_NAME,
    REQUIRED_PACKAGES,
    SYNC_TO_SECONDARY_TARGET,
    TAR_BIN,
    TEMPLATES_DIR,
)
from dovecot_config import DovecotConfig, DovecotConfigInvalidError, DovecotConfigSecretError
from dovecot_setup import DovecotSetup
from exceptions import CharmBlockedError, ConfigurationError, HASetupError
from ha import HAManager
from storage import StorageManager

logger = logging.getLogger(__name__)


class DovecotCharm(CharmBase):
    """Dovecot IMAP/POP3 mail server charm."""

    def __init__(self, *args):
        super().__init__(*args)

        self._storage = StorageManager(self)
        self._dovecot_setup = DovecotSetup(self)
        self._ha = HAManager(self)

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._reconcile)
        self.framework.observe(self.on.config_changed, self._reconcile)
        self.framework.observe(self.on.upgrade_charm, self._on_install)
        self.framework.observe(self.on.clear_queue_action, self._on_clear_queue_action)
        self.framework.observe(self.on.gdpr_archive_action, self._on_gdpr_archive)
        self.framework.observe(self.on.gdpr_delete_action, self._on_gdpr_delete)
        self.framework.observe(self.on.gdpr_takeout_action, self._on_gdpr_takeout)
        self.framework.observe(self.on.mail_data_storage_attached, self._reconcile)
        self.framework.observe(self.on.mail_data_storage_detaching, self._reconcile)
        self.framework.observe(self.on[PEER_RELATION_NAME].relation_changed, self._reconcile)
        self.framework.observe(self.on.force_sync_action, self._on_force_sync)

        self.framework.observe(
            self.on[PEER_RELATION_NAME].relation_created,
            self._on_peer_relation_created,
        )

        self.jinja = jinja2.Environment(
            loader=jinja2.FileSystemLoader(TEMPLATES_DIR), autoescape=True
        )

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

    @cached_property
    def _is_primary(self) -> bool:
        """Return True if this unit is the configured primary unit."""
        return self.unit.name == self.config.get("primary-unit", "")

    @cached_property
    def _secondary_hostname(self) -> typing.Optional[str]:
        """Return the hostname of the first remote peer unit, or None."""
        relation = self.model.get_relation(PEER_RELATION_NAME)
        if not relation:
            return None
        for unit in relation.units:
            hostname = relation.data[unit].get("hostname")
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

    def _on_install(self, event):
        """Handle install event."""
        self.unit.status = MaintenanceStatus("Installing packages")
        self._install()
        self._reconcile(event)

    def _reconcile(self, event):
        """Reconcile charm state."""
        self.unit.status = MaintenanceStatus("Configuring charm")
        if len(self.get_units()) > 2:
            self.unit.status = BlockedStatus(
                "Only one primary and one secondary unit are supported; remove extra units"
            )
            return
        try:
            dovecot_config = self._get_dovecot_config()
            self._storage.ensure_storage_ready(dovecot_config)
            self._storage.teardown_detaching_storage()
        except CharmBlockedError as e:
            self.unit.status = BlockedStatus(str(e))
            return
        if not self._dovecot_setup.is_installed():
            logger.warning("Dovecot not installed yet, deferring configuration")
            return
        try:
            self._dovecot_setup.setup_tls(dovecot_config)
            self._dovecot_setup.setup_dovecot(dovecot_config)
            self._dovecot_setup.setup_procmail()
        except ConfigurationError as e:
            self.unit.status = BlockedStatus(str(e))
            return
        try:
            self._ha.setup_ssh_keys()
            self._ha.sync_authorized_keys()
            self._ha.sync_known_hosts()
            if self._is_primary:
                self._ha.install_mail_sync_script()
                self._ha.setup_mail_sync_timer(dovecot_config)
        except HASetupError as e:
            self.unit.status = BlockedStatus(str(e))
            return
        self._open_ports()
        self.unit.status = ops.ActiveStatus()

    def _install(self):
        """Install required packages and set up mailname."""
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
            result = subprocess.run(command, check=True, capture_output=True, text=True)
            event.set_results({"status": "success", "output": result.stdout})
        except subprocess.CalledProcessError as e:
            logger.exception(f"Failed to clear Postfix queue: {e.stderr}")
            event.fail(f"Failed to run postsuper: {e.stderr}")

    def _on_gdpr_archive(self, event):
        """Archive a user's mailbox for long-term retention."""
        username = event.params["username"]
        compress = event.params.get("compress", True)
        archive_dir = f"{GDPR_ARCHIVE_DIR}/{username}"

        logger.info(f"GDPR archive: archiving mailbox for user '{username}'")

        try:
            os.makedirs(archive_dir, exist_ok=True)

            subprocess.run(
                [DOVEADM_BIN, "backup", "-u", username, f"mdbox:{archive_dir}/"],
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info(f"Mailbox for '{username}' backed up to {archive_dir}")

            result_path = archive_dir
            if compress:
                tar_path = f"{GDPR_ARCHIVE_DIR}/{username}.tar.gz"
                subprocess.run(
                    [TAR_BIN, "-czf", tar_path, "-C", GDPR_ARCHIVE_DIR, username],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                shutil.rmtree(archive_dir)
                result_path = tar_path
                logger.info(f"Archive compressed to {tar_path}")

            event.set_results({"status": "success", "path": result_path})
        except FileNotFoundError as e:
            msg = f"Required binary not found: {e.filename}. Is dovecot-core installed?"
            logger.error(msg)
            event.fail(msg)
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
                [DOVEADM_BIN, "expunge", "-u", username, "mailbox", "*", "all"],
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info(f"All mail expunged for user '{username}'")

            user_mail_dir = os.path.join(MAIL_ROOT, username)
            if os.path.exists(user_mail_dir):
                shutil.rmtree(user_mail_dir)
                logger.info(f"Mail directory removed: {user_mail_dir}")

            event.set_results(
                {"status": "success", "message": f"Mailbox for '{username}' deleted"}
            )
        except FileNotFoundError as e:
            msg = f"Required binary not found: {e.filename}. Is dovecot-core installed?"
            logger.error(msg)
            event.fail(msg)
        except subprocess.CalledProcessError as e:
            msg = f"Failed to delete mailbox for '{username}': {e.stderr}"
            logger.error(msg)
            event.fail(msg)

    def _on_gdpr_takeout(self, event):
        """Export a user's mail data in a portable format (GDPR data portability)."""
        username = event.params["username"]
        export_format = event.params.get("format", "maildir")
        export_dir = f"{GDPR_TAKEOUT_DIR}/{username}"

        logger.info(f"GDPR takeout: exporting mailbox for user '{username}' as {export_format}")

        try:
            os.makedirs(export_dir, exist_ok=True)

            if export_format == "maildir":
                subprocess.run(
                    [
                        DOVEADM_BIN,
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
                        DOVEADM_BIN,
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

            tar_path = f"{GDPR_TAKEOUT_DIR}/{username}-takeout.tar.gz"
            subprocess.run(
                [TAR_BIN, "-czf", tar_path, "-C", GDPR_TAKEOUT_DIR, username],
                check=True,
                capture_output=True,
                text=True,
            )
            shutil.rmtree(export_dir)

            logger.info(f"Takeout export created at {tar_path}")
            event.set_results({"status": "success", "path": tar_path})
        except FileNotFoundError as e:
            msg = f"Required binary not found: {e.filename}. Is dovecot-core installed?"
            logger.error(msg)
            event.fail(msg)
        except subprocess.CalledProcessError as e:
            msg = f"Failed to export mailbox for '{username}': {e.stderr}"
            logger.error(msg)
            event.fail(msg)

    def _on_force_sync(self, event):
        """Force synchronization with secondary unit."""
        if not self._is_primary:
            event.fail("This action can only be run on the primary unit.")
            return

        if not self._secondary_hostname:
            event.fail(
                "Secondary unit hostname is not yet known. "
                "Ensure a second unit is deployed and has joined the peer relation."
            )
            return

        if not Path(SYNC_TO_SECONDARY_TARGET).exists():
            event.fail(
                "Sync script not yet installed. "
                "Please wait for the charm to reach active state before running force-sync."
            )
            return

        try:
            logger.info(f"Running manual sync: {SYNC_TO_SECONDARY_TARGET}")
            subprocess.run([SYNC_TO_SECONDARY_TARGET], check=True, capture_output=True, text=True)
            event.set_results({"result": "Sync completed successfully"})
        except subprocess.CalledProcessError as e:
            parts = [
                f"Sync failed with exit code {e.returncode} while running "
                f"{' '.join(e.cmd) if isinstance(e.cmd, (list, tuple)) else e.cmd}"
            ]
            if e.stderr and e.stderr.strip():
                parts.append(f"stderr: {e.stderr.strip()}")
            if e.stdout and e.stdout.strip():
                parts.append(f"stdout: {e.stdout.strip()}")
            msg = ". ".join(parts)
            logger.error(msg)
            event.fail(msg)
        except FileNotFoundError as e:
            msg = f"Sync failed: {e}"
            logger.error(msg)
            event.fail(msg)


if __name__ == "__main__":  # pragma: nocover
    main(DovecotCharm)
