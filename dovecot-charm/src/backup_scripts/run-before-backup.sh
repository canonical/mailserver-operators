#!/bin/bash

# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

set -euo pipefail

umask 077

staging_dir=/var/backups/dovecot/staging
key_file=/var/lib/dovecot/backup/encryption.key
accounts_file="$staging_dir/mail-users.tsv"
plaintext_archive="$staging_dir/mail-data.tar.gz"
encrypted_archive_tmp="$staging_dir/mail-data.tar.gz.enc.tmp"
encrypted_archive=/var/backups/dovecot/mail-data.tar.gz.enc
manifest_tmp="$staging_dir/manifest.json.tmp"
manifest=/var/backups/dovecot/manifest.json

mkdir -p "$staging_dir"
rm -f "$plaintext_archive" "$encrypted_archive_tmp" "$manifest_tmp" "$accounts_file"
trap 'rm -f "$plaintext_archive" "$encrypted_archive_tmp" "$manifest_tmp" "$accounts_file"' EXIT

if [[ ! -f "$key_file" ]]; then
    echo "Missing backup encryption key file: $key_file" >&2
    exit 1
fi

if ! mountpoint -q /srv/mail; then
    echo "Mail storage is not mounted at /srv/mail" >&2
    exit 1
fi

# Capture mail user accounts (username + password hash) alongside the mail data
# so a restore onto a fresh unit can recreate them, instead of requiring a
# separate manual account-provisioning step. Only the "mail" group's members are
# captured (every account created via the create-mail-user action is added to
# that group), never the full system passwd/shadow files, so unrelated system
# accounts are never touched by a restore.
: > "$accounts_file"
mail_group_members="$(getent group mail | cut -d: -f4)"
if [[ -n "$mail_group_members" ]]; then
    IFS=',' read -ra mail_users <<<"$mail_group_members"
    for user in "${mail_users[@]}"; do
        hash="$(getent shadow "$user" 2>/dev/null | cut -d: -f2)"
        if [[ -n "$hash" ]]; then
            printf '%s:%s\n' "$user" "$hash" >>"$accounts_file"
        fi
    done
fi

tar --create --gzip --file "$plaintext_archive" \
    --directory / srv/mail \
    --directory "$staging_dir" mail-users.tsv
openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -md sha256 -salt \
    -in "$plaintext_archive" \
    -out "$encrypted_archive_tmp" \
    -pass "file:$key_file"

# Encrypt-then-MAC: AES-256-CBC alone does not authenticate the ciphertext, so a
# tampered archive could decrypt to altered data undetected. Authenticate the
# ciphertext with an HMAC computed from a MAC key derived separately from the
# encryption passphrase (domain-separated) and record it in the manifest so the
# restore hook can verify integrity before decrypting.
mac_key="$(openssl dgst -sha256 -hmac "$(cat "$key_file")" -hex <<<"dovecot-backup-mac-v1" | awk '{print $NF}')"
archive_hmac="$(openssl dgst -sha256 -mac HMAC -macopt "hexkey:$mac_key" -hex "$encrypted_archive_tmp" | awk '{print $NF}')"

timestamp="$(date -Iseconds --utc)"
cat > "$manifest_tmp" <<EOF
{
  "format": 2,
  "created_at": "$timestamp",
  "archive": "/var/backups/dovecot/mail-data.tar.gz.enc",
  "mail_root": "/srv/mail",
  "accounts": "mail-users.tsv",
  "integrity": {
    "algorithm": "HMAC-SHA256",
    "value": "$archive_hmac"
  }
}
EOF

mv "$encrypted_archive_tmp" "$encrypted_archive"
mv "$manifest_tmp" "$manifest"
