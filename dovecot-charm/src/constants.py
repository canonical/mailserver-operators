# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Dovecot charm constants."""

from pathlib import Path

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

MAPPER_NAME = "mail-data"
MAPPER_PATH = f"/dev/mapper/{MAPPER_NAME}"
PEER_RELATION_NAME = "replicas"

# State file that persists the block-device path across reboots so that the
# start hook can re-open LUKS without relying on `storage-get` (which fails
# when Juju has not yet re-provisioned the storage after a VM restart).
STORAGE_DEV_PATH_FILE = "/var/lib/dovecot-charm/storage-dev-path"

TLS_CERT_DIR = Path("/etc/dovecot/private")

# HA sync paths
SYNC_TO_SECONDARY_TARGET = "/usr/local/bin/sync-to-secondary.sh"
SYNC_TO_SECONDARY_CRONJOB_TARGET = "/etc/cron.d/sync-to-secondary"
SYNC_TO_SECONDARY_TEMPLATE = "sync-to-secondary.sh.tmpl"
SYNC_TO_SECONDARY_CRONJOB_TEMPLATE = "sync-to-secondary_cron.tmpl"

SSHD_CONFIG = Path("/etc/ssh/sshd_config")
SSHD_DROPIN_DIR = Path("/etc/ssh/sshd_config.d")
SSHD_DROPIN_FILE = SSHD_DROPIN_DIR / "99-dovecot-ha.conf"
SSH_DIR = Path("/root/.ssh")
SSH_HOST_KEY_FILE = Path("/etc/ssh/ssh_host_ed25519_key.pub")
