# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Backup on a published revision, restore onto the charm under test.

This backs up on an older, published revision of the charm, then restores onto a
separately deployed instance of the charm under test. It catches regressions that
a same-revision round-trip cannot, such as a changed mail mountpoint or a change
in how the backup encryption key is stored, and confirms a backup is portable
across independent deployments.

Both deployments share the same ``backup-encryption-key`` secret (see the
``backup_secret`` fixture) so the newer charm can decrypt the archive produced by
the older one.
"""

import logging
import secrets
from pathlib import PurePosixPath

import jubilant

from . import baculum as baculum_client_module
from .helpers import (
    find_bacula_job,
    mailbox_has_subject,
    seed_backup_test_message,
    teardown_gdpr_test_user,
    wait_for_bacula_job,
)

logger = logging.getLogger(__name__)

_BACKUP_TEST_USER = "upgrade-backup-testuser"
_BACKUP_TEST_SUBJECT = "bacula-upgrade-roundtrip-test"


def test_backup_restore_across_charm_upgrade(
    juju: jubilant.Juju,
    dovecot_charm_backup: str,
    dovecot_old: str,
    baculum: baculum_client_module.Baculum,
):
    """Back up on the published revision and restore onto the charm under test."""
    old_unit = f"{dovecot_old}/0"
    new_unit = f"{dovecot_charm_backup}/0"

    password = secrets.token_hex(16)
    seed_backup_test_message(juju, old_unit, _BACKUP_TEST_USER, password, _BACKUP_TEST_SUBJECT)
    try:
        assert mailbox_has_subject(juju, old_unit, _BACKUP_TEST_USER, _BACKUP_TEST_SUBJECT), (
            "seeded message not found before backup"
        )

        backup_job = find_bacula_job(baculum, "-backup", contains=f"{dovecot_old}-0")
        restore_job = find_bacula_job(baculum, "-restore", contains=f"{dovecot_charm_backup}-0")

        logger.info("Running backup job %s on the published revision", backup_job)
        baculum.run_backup_job(backup_job)
        backup_run = wait_for_bacula_job(baculum, backup_job)

        backed_up_files = {
            PurePosixPath(f).name for f in baculum.list_job_files(int(backup_run["jobid"]))
        }
        assert "mail-data.tar.gz.enc" in backed_up_files, (
            "encrypted mail archive was not stored in Bacula"
        )
        assert "manifest.json" in backed_up_files, "manifest was not stored in Bacula"

        # The charm under test is a fresh deployment; confirm before restoring onto it.
        assert not mailbox_has_subject(juju, new_unit, _BACKUP_TEST_USER, _BACKUP_TEST_SUBJECT), (
            "message unexpectedly present on the freshly deployed charm"
        )

        logger.info(
            "Restoring backup %s onto %s via %s", backup_run["jobid"], new_unit, restore_job
        )
        baculum.run_restore_job(restore_job, backup_job_id=int(backup_run["jobid"]))
        wait_for_bacula_job(baculum, restore_job)

        assert mailbox_has_subject(juju, new_unit, _BACKUP_TEST_USER, _BACKUP_TEST_SUBJECT), (
            "message was not restored onto the newly deployed charm"
        )
    finally:
        teardown_gdpr_test_user(juju, old_unit, _BACKUP_TEST_USER)
        teardown_gdpr_test_user(juju, new_unit, _BACKUP_TEST_USER)
