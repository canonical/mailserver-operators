# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""High availability functions for the Dovecot charm."""

from __future__ import annotations

import logging
import socket
import subprocess  # nosec
import typing

from charmhelpers.core import host
from charmlibs import systemd
from ops.model import MaintenanceStatus

from constants import (
    MAIL_ROOT,
    PEER_RELATION_NAME,
    SSH_DIR,
    SSH_HOST_KEY_FILE,
    SSHD_CONFIG,
    SYNC_TO_SECONDARY_CRONJOB_TARGET,
    SYNC_TO_SECONDARY_CRONJOB_TEMPLATE,
    SYNC_TO_SECONDARY_TARGET,
    SYNC_TO_SECONDARY_TEMPLATE,
)

if typing.TYPE_CHECKING:
    from charm import DovecotCharm

logger = logging.getLogger(__name__)


def setup_ssh_keys(charm: DovecotCharm) -> None:
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
    relation = charm.model.get_relation(PEER_RELATION_NAME)
    if relation:
        relation.data[charm.unit]["public_key"] = pub_key
        relation.data[charm.unit]["hostname"] = socket.gethostname()

        if SSH_HOST_KEY_FILE.exists():
            host_key = SSH_HOST_KEY_FILE.read_text().strip()
            relation.data[charm.unit]["ssh_host_key"] = host_key


def sync_authorized_keys(charm: DovecotCharm) -> None:
    """Collect public keys from all peer units and write authorized_keys."""
    relation = charm.model.get_relation(PEER_RELATION_NAME)
    if not relation:
        return

    authorized_keys = []
    for unit in relation.units:
        pk = relation.data[unit].get("public_key")
        if pk:
            authorized_keys.append(pk)

    our_pk = relation.data[charm.unit].get("public_key")
    if our_pk:
        authorized_keys.append(our_pk)

    if not authorized_keys:
        return

    auth_file = SSH_DIR / "authorized_keys"
    auth_file.write_text("\n".join(authorized_keys) + "\n")
    auth_file.chmod(0o600)

    ensure_root_ssh_login()


def sync_known_hosts(charm: DovecotCharm) -> None:
    """Populate known_hosts with peer SSH host keys from the peer relation.

    Each peer publishes its host public key and hostname on the relation.
    This writes those into known_hosts so SSH connections between units use
    StrictHostKeyChecking (the default) instead of disabling it.
    """
    relation = charm.model.get_relation(PEER_RELATION_NAME)
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


def ensure_root_ssh_login() -> None:
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


def install_mail_sync_script(charm: DovecotCharm) -> None:
    """Render and install the mail pool synchronization script.

    Skipped when the secondary hostname is not yet known (no remote peer).
    """
    secondary = charm._secondary_hostname
    if not secondary:
        logger.info("Secondary hostname not yet known; skipping sync script installation")
        return

    charm.unit.status = MaintenanceStatus("Installing mail pool synchronization script")
    template_context = {
        "secondary_hostname": secondary,
        "mail_root": MAIL_ROOT,
    }
    template = charm.jinja.get_template(SYNC_TO_SECONDARY_TEMPLATE)
    contents = template.render(template_context)
    host.write_file(SYNC_TO_SECONDARY_TARGET, contents, perms=0o755)


def setup_mail_sync_cronjob(charm: DovecotCharm) -> None:
    """Set up the mail pool synchronization cronjob."""
    if not charm._secondary_hostname:
        logger.info("Secondary hostname not yet known; skipping cronjob setup")
        return

    charm.unit.status = MaintenanceStatus("Setting up mail pool synchronization cronjob")
    template_context = {
        "schedule": charm.config.get("sync-schedule", "*/30 * * * *"),
    }
    template = charm.jinja.get_template(SYNC_TO_SECONDARY_CRONJOB_TEMPLATE)
    contents = template.render(template_context)
    host.write_file(SYNC_TO_SECONDARY_CRONJOB_TARGET, contents, perms=0o644)
    systemd.service_restart("cron")
