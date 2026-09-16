#!/bin/bash

# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

set -euo pipefail

umask 077

staging_dir=/var/backups/dovecot/staging
key_file=/var/lib/dovecot/backup/encryption.key
plaintext_archive="$staging_dir/mail-data.tar.gz"
encrypted_archive_tmp="$staging_dir/mail-data.tar.gz.enc.tmp"
encrypted_archive=/var/backups/dovecot/mail-data.tar.gz.enc
manifest_tmp="$staging_dir/manifest.json.tmp"
manifest=/var/backups/dovecot/manifest.json

mkdir -p "$staging_dir"
rm -f "$plaintext_archive" "$encrypted_archive_tmp" "$manifest_tmp"
trap 'rm -f "$plaintext_archive" "$encrypted_archive_tmp" "$manifest_tmp"' EXIT

if [[ ! -f "$key_file" ]]; then
    echo "Missing backup encryption key file: $key_file" >&2
    exit 1
fi

if ! mountpoint -q /srv/mail; then
    echo "Mail storage is not mounted at /srv/mail" >&2
    exit 1
fi

tar --create --gzip --file "$plaintext_archive" --directory / srv/mail
openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -md sha256 -salt \
    -in "$plaintext_archive" \
    -out "$encrypted_archive_tmp" \
    -pass "file:$key_file"

timestamp="$(date -Iseconds --utc)"
cat > "$manifest_tmp" <<EOF
{
  "format": 1,
  "created_at": "$timestamp",
  "archive": "/var/backups/dovecot/mail-data.tar.gz.enc",
  "mail_root": "/srv/mail"
}
EOF

mv "$encrypted_archive_tmp" "$encrypted_archive"
mv "$manifest_tmp" "$manifest"
