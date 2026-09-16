#!/bin/bash

# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

set -euo pipefail

rm -f /var/backups/dovecot/mail-data.tar.gz.enc
rm -f /var/backups/dovecot/manifest.json
