# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

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

_BACKUP_TEST_USER = "backup-testuser"
_BACKUP_TEST_SUBJECT = "bacula-roundtrip-test"


def test_bacula_backup_restore_roundtrip(
    juju: jubilant.Juju,
    dovecot_charm_backup: str,
    baculum: baculum_client_module.Baculum,
):
    """End-to-end: back up the mail store, wipe it, restore, and verify the mail returns."""
    unit_name = f"{dovecot_charm_backup}/0"

    password = secrets.token_hex(16)
    seed_backup_test_message(juju, unit_name, _BACKUP_TEST_USER, password, _BACKUP_TEST_SUBJECT)
    try:
        assert mailbox_has_subject(juju, unit_name, _BACKUP_TEST_USER, _BACKUP_TEST_SUBJECT), (
            "seeded message not found before backup"
        )

        backup_job = find_bacula_job(baculum, "-backup")
        restore_job = find_bacula_job(baculum, "-restore")

        logger.info("Running backup job %s", backup_job)
        baculum.run_backup_job(backup_job)
        backup_run = wait_for_bacula_job(baculum, backup_job)

        backed_up_files = {
            PurePosixPath(f).name for f in baculum.list_job_files(int(backup_run["jobid"]))
        }
        assert "mail-data.tar.gz.enc" in backed_up_files, (
            "encrypted mail archive was not stored in Bacula"
        )
        assert "manifest.json" in backed_up_files, "manifest was not stored in Bacula"

        # Destroy the mail store so the restore has something to bring back.
        juju.exec(
            "find /srv/mail -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +",
            unit=unit_name,
        )
        assert not mailbox_has_subject(juju, unit_name, _BACKUP_TEST_USER, _BACKUP_TEST_SUBJECT), (
            "message should be gone after wiping the mail store"
        )

        logger.info("Running restore job %s from backup %s", restore_job, backup_run["jobid"])
        baculum.run_restore_job(restore_job, backup_job_id=int(backup_run["jobid"]))
        wait_for_bacula_job(baculum, restore_job)

        assert mailbox_has_subject(juju, unit_name, _BACKUP_TEST_USER, _BACKUP_TEST_SUBJECT), (
            "message was not restored from the Bacula backup"
        )
    finally:
        teardown_gdpr_test_user(juju, unit_name, _BACKUP_TEST_USER)
