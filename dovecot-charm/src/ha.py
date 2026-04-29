# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""High availability manager for the Dovecot charm."""

from __future__ import annotations

import logging
import socket
import subprocess  # nosec
import typing
from pathlib import Path

from charmhelpers.core import host
from charmlibs import systemd
from ops.model import MaintenanceStatus

from constants import (
    MAIL_ROOT,
    PEER_RELATION_NAME,
    SSH_DIR,
    SSH_HOST_KEY_FILE,
    SSHD_CONFIG,
    SSHD_DROPIN_DIR,
    SSHD_DROPIN_FILE,
    SYNC_TO_SECONDARY_SERVICE_TARGET,
    SYNC_TO_SECONDARY_SERVICE_TEMPLATE,
    SYNC_TO_SECONDARY_TARGET,
    SYNC_TO_SECONDARY_TEMPLATE,
    SYNC_TO_SECONDARY_TIMER_TARGET,
    SYNC_TO_SECONDARY_TIMER_TEMPLATE,
)
from exceptions import HASetupError

if typing.TYPE_CHECKING:
    from charm import DovecotCharm
    from dovecot_config import DovecotConfig

logger = logging.getLogger(__name__)


class HAManager:
    """Manages high-availability setup between primary and secondary units.

    Handles SSH key exchange, authorized_keys/known_hosts population, sshd
    configuration, and mail sync script/timer installation.  Injected into
    DovecotCharm so unit tests can substitute a no-op implementation without
    patching module-level functions.
    """

    def __init__(self, charm: DovecotCharm) -> None:
        self._charm = charm

    def setup_ssh_keys(self) -> None:
        """Generate an SSH key pair if absent and publish keys via the peer relation.

        Publishes both the user public key (for authorized_keys) and the host
        public key (for known_hosts) so peers can verify each other's identity
        without disabling StrictHostKeyChecking.

        Raises:
            HASetupError: If SSH key generation fails.
        """
        SSH_DIR.mkdir(mode=0o700, exist_ok=True)
        key_file = SSH_DIR / "id_ed25519"

        if not key_file.exists():
            try:
                subprocess.run(
                    ["/usr/bin/ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key_file)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as e:
                raise HASetupError(f"SSH key generation failed: {e.stderr}") from e

        pub_key_file = SSH_DIR / "id_ed25519.pub"
        if not pub_key_file.exists():
            raise HASetupError("SSH public key file not found after key generation")

        pub_key = pub_key_file.read_text().strip()
        relation = self._charm.model.get_relation(PEER_RELATION_NAME)
        if relation:
            relation.data[self._charm.unit]["public_key"] = pub_key
            relation.data[self._charm.unit]["hostname"] = socket.gethostname()

            binding = self._charm.model.get_binding(PEER_RELATION_NAME)
            if binding:
                relation.data[self._charm.unit]["ip_address"] = str(binding.network.bind_address)

            if SSH_HOST_KEY_FILE.exists():
                host_key = SSH_HOST_KEY_FILE.read_text().strip()
                relation.data[self._charm.unit]["ssh_host_key"] = host_key

    def sync_authorized_keys(self) -> None:
        """Collect public keys and IPs from all peer units and write authorized_keys.

        Also calls _ensure_root_ssh_login with the collected peer IPs so that
        root SSH key login is restricted to known peer addresses only.
        """
        relation = self._charm.model.get_relation(PEER_RELATION_NAME)
        if not relation:
            return

        authorized_keys = []
        peer_ips: list[str] = []
        for unit in relation.units:
            pk = relation.data[unit].get("public_key")
            if pk:
                authorized_keys.append(pk)
            ip = relation.data[unit].get("ip_address")
            if ip:
                peer_ips.append(ip)

        our_pk = relation.data[self._charm.unit].get("public_key")
        if our_pk:
            authorized_keys.append(our_pk)
        our_ip = relation.data[self._charm.unit].get("ip_address")
        if our_ip:
            peer_ips.append(our_ip)

        if not authorized_keys:
            return

        auth_file = SSH_DIR / "authorized_keys"
        auth_file.write_text("\n".join(authorized_keys) + "\n")
        auth_file.chmod(0o600)

        self._ensure_root_ssh_login(peer_ips)

    def sync_known_hosts(self) -> None:
        """Populate known_hosts with peer SSH host keys from the peer relation."""
        relation = self._charm.model.get_relation(PEER_RELATION_NAME)
        if not relation:
            return

        entries = []
        for unit in relation.units:
            host_key = relation.data[unit].get("ssh_host_key")
            hostname = relation.data[unit].get("hostname")
            if host_key and hostname:
                entries.append(f"{hostname} {host_key}")

        if not entries:
            return

        known_hosts_file = SSH_DIR / "known_hosts"
        known_hosts_file.write_text("\n".join(entries) + "\n")
        known_hosts_file.chmod(0o600)

    def install_mail_sync_script(self) -> None:
        """Render and install the mail pool synchronization script.

        Skipped when the secondary hostname is not yet known (no remote peer).
        """
        secondary = self._charm._secondary_hostname
        if not secondary:
            logger.info("Secondary hostname not yet known; skipping sync script installation")
            return

        self._charm.unit.status = MaintenanceStatus("Installing mail pool synchronization script")
        template_context = {
            "secondary_hostname": secondary,
            "mail_root": MAIL_ROOT,
        }
        template = self._charm.jinja.get_template(SYNC_TO_SECONDARY_TEMPLATE)
        contents = template.render(template_context)
        host.write_file(SYNC_TO_SECONDARY_TARGET, contents, perms=0o755)

    def setup_mail_sync_timer(self, dovecot_config: DovecotConfig) -> None:
        """Set up the mail pool synchronisation systemd timer.

        Writes the .service and .timer unit files if their content has changed,
        reloads the systemd daemon when needed, then enables and starts the timer.
        Skips when the secondary hostname is not yet known.
        """
        if not self._charm._secondary_hostname:
            logger.info("Secondary hostname not yet known; skipping timer setup")
            return

        self._charm.unit.status = MaintenanceStatus("Setting up mail pool synchronisation timer")

        service_contents = self._charm.jinja.get_template(
            SYNC_TO_SECONDARY_SERVICE_TEMPLATE
        ).render()
        service_path = Path(SYNC_TO_SECONDARY_SERVICE_TARGET)
        service_changed = not service_path.exists() or service_path.read_text() != service_contents
        if service_changed:
            host.write_file(SYNC_TO_SECONDARY_SERVICE_TARGET, service_contents, perms=0o644)

        timer_contents = self._charm.jinja.get_template(SYNC_TO_SECONDARY_TIMER_TEMPLATE).render(
            {"schedule": dovecot_config.sync_schedule}
        )
        timer_path = Path(SYNC_TO_SECONDARY_TIMER_TARGET)
        timer_changed = not timer_path.exists() or timer_path.read_text() != timer_contents
        if timer_changed:
            host.write_file(SYNC_TO_SECONDARY_TIMER_TARGET, timer_contents, perms=0o644)

        if service_changed or timer_changed:
            systemd.daemon_reload()

        systemd.service_resume("sync-to-secondary.timer")

    def _ensure_root_ssh_login(self, peer_ips: list[str]) -> None:
        """Set PermitRootLogin via an sshd drop-in restricted to peer addresses.

        Writes /etc/ssh/sshd_config.d/99-dovecot-ha.conf with a global
        ``PermitRootLogin no`` baseline and a ``Match Address`` block that
        permits ``prohibit-password`` only for the supplied peer IPs.

        If no peer IPs are known yet the drop-in is removed so that root login
        remains governed by the distro default.  Validates with ``sshd -t``
        before reloading; rolls back on failure.

        Raises:
            HASetupError: If sshd validation or reload fails.
        """
        if not SSHD_CONFIG.exists():
            return

        if not peer_ips:
            if SSHD_DROPIN_FILE.exists():
                SSHD_DROPIN_FILE.unlink()
                try:
                    systemd.service_reload("ssh", restart_on_failure=True)
                except subprocess.CalledProcessError as e:
                    raise HASetupError(f"Failed to reload sshd after config change: {e}") from e
            return

        address_list = ",".join(sorted(set(peer_ips)))
        drop_in_content = (
            "PermitRootLogin no\n"
            "\n"
            f"Match Address {address_list}\n"
            "    PermitRootLogin prohibit-password\n"
        )

        previous_exists = SSHD_DROPIN_FILE.exists()
        previous_content = SSHD_DROPIN_FILE.read_text() if previous_exists else None

        if previous_exists and previous_content == drop_in_content:
            return

        SSHD_DROPIN_DIR.mkdir(mode=0o755, parents=True, exist_ok=True)
        SSHD_DROPIN_FILE.write_text(drop_in_content)

        Path("/run/sshd").mkdir(mode=0o755, exist_ok=True)

        try:
            subprocess.run(
                ["/usr/sbin/sshd", "-t", "-f", str(SSHD_CONFIG)],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            if previous_exists and previous_content is not None:
                SSHD_DROPIN_FILE.write_text(previous_content)
            else:
                SSHD_DROPIN_FILE.unlink(missing_ok=True)
            raise HASetupError(f"Failed to validate sshd configuration: {e.stderr}") from e

        try:
            systemd.service_reload("ssh", restart_on_failure=True)
        except subprocess.CalledProcessError as e:
            raise HASetupError(f"Failed to reload sshd after config change: {e}") from e
