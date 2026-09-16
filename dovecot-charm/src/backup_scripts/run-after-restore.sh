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

trap 'rm -f "$plaintext_archive"' EXIT

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

mkdir -p "$restore_dir"
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -md sha256 -salt \
    -in "$encrypted_archive" \
    -out "$plaintext_archive" \
    -pass "file:$key_file"

# Stop Dovecot only for the wipe+extract so mail stays available while Bacula
# is restoring the artifact; restart it afterwards if we were the ones to stop it.
dovecot_was_active=0
if systemctl is-active --quiet dovecot; then
    systemctl stop dovecot
    dovecot_was_active=1
fi

find /srv/mail -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
tar --extract --gzip --file "$plaintext_archive" --directory /
rm -f "$plaintext_archive"
rm -rf "$restore_dir"

if [[ "$dovecot_was_active" -eq 1 ]]; then
    systemctl start dovecot
fi
