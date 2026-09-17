#!/bin/bash

# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

set -euo pipefail

umask 077

key_file=/var/lib/dovecot/backup/encryption.key
encrypted_archive=/var/backups/dovecot/mail-data.tar.gz.enc
manifest=/var/backups/dovecot/manifest.json
restore_dir=/var/backups/dovecot/restore
plaintext_archive="$restore_dir/mail-data.restore.tar.gz"
staging_dir="$restore_dir/tree"

dovecot_was_active=0

cleanup() {
    rm -rf "$restore_dir"
    # If we stopped Dovecot for the swap, bring it back on every exit path so a
    # failed restore never leaves the service permanently down.
    if [[ "$dovecot_was_active" -eq 1 ]]; then
        dovecot_was_active=0
        systemctl start dovecot
    fi
}
trap cleanup EXIT

if [[ ! -f "$key_file" ]]; then
    echo "Missing backup encryption key file: $key_file" >&2
    exit 1
fi

if [[ ! -f "$encrypted_archive" ]]; then
    echo "Missing restored encrypted archive: $encrypted_archive" >&2
    exit 1
fi

if [[ ! -f "$manifest" ]]; then
    echo "Missing restored backup manifest: $manifest" >&2
    exit 1
fi

if ! mountpoint -q /srv/mail; then
    echo "Mail storage is not mounted at /srv/mail" >&2
    exit 1
fi

# Verify ciphertext integrity (encrypt-then-MAC) before touching any live data.
expected_hmac="$(jq -r '.integrity.value // empty' "$manifest")"
if [[ -z "$expected_hmac" ]]; then
    echo "Backup manifest is missing an integrity value" >&2
    exit 1
fi
mac_key="$(openssl dgst -sha256 -hmac "$(cat "$key_file")" -hex <<<"dovecot-backup-mac-v1" | awk '{print $NF}')"
actual_hmac="$(openssl dgst -sha256 -mac HMAC -macopt "hexkey:$mac_key" -hex "$encrypted_archive" | awk '{print $NF}')"
if [[ "$actual_hmac" != "$expected_hmac" ]]; then
    echo "Backup integrity check failed; refusing to restore tampered archive" >&2
    exit 1
fi

mkdir -p "$staging_dir"
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -md sha256 -salt \
    -in "$encrypted_archive" \
    -out "$plaintext_archive" \
    -pass "file:$key_file"

# Extract into a staging directory and validate the expected layout before
# destroying any live mail, so a corrupt or truncated archive cannot wipe
# /srv/mail without a valid replacement ready.
tar --extract --gzip --file "$plaintext_archive" --directory "$staging_dir"
if [[ ! -d "$staging_dir/srv/mail" ]]; then
    echo "Restored archive does not contain the expected srv/mail tree" >&2
    exit 1
fi

# Stop Dovecot only for the wipe+swap so mail stays available while Bacula is
# restoring the artifact; the EXIT trap restarts it if anything below fails.
if systemctl is-active --quiet dovecot; then
    systemctl stop dovecot
    dovecot_was_active=1
fi

find /srv/mail -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
cp -a "$staging_dir/srv/mail/." /srv/mail/


