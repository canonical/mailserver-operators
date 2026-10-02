# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import base64
import logging
import mailbox
import os
import tarfile
import tempfile
from secrets import token_hex

import jubilant
import pytest

from .conftest import MAIL_ROOT
from .helpers import (
    assert_deferred_queue_empty,
    assert_queue_empty,
    assert_queue_non_empty,
    cleanup_header_checks,
    configure_mail_user,
    configure_mail_users,
    reset_mail_users,
    seed_deferred_queue_with_test_mail,
    seed_queue_with_test_mail,
)

logger = logging.getLogger(__name__)


@pytest.fixture
def mail_users_unit(juju: jubilant.Juju, dovecot_charm: str):
    """Restore the shared secret after each authentication test."""
    unit_name = f"{dovecot_charm}/0"
    yield unit_name
    reset_mail_users(juju, unit_name)


def test_mail_users_secret_adds_new_user(juju: jubilant.Juju, mail_users_unit: str):
    """A secret user authenticates while a user absent from the secret does not."""
    user = f"secret-user-{token_hex(4)}"
    password = token_hex(16)
    unknown_user = f"unknown-user-{token_hex(4)}"

    configure_mail_user(juju, mail_users_unit, user, password)

    juju.exec(f"doveadm auth test {user} '{password}'", unit=mail_users_unit)
    with pytest.raises(jubilant.TaskError):
        juju.exec(f"doveadm auth test {unknown_user} invalid-password", unit=mail_users_unit)


def test_mail_users_secret_updates_existing_user(juju: jubilant.Juju, mail_users_unit: str):
    """Rotating a secret user's password invalidates the previous password."""
    user = f"secret-user-{token_hex(4)}"
    old_password = token_hex(16)
    new_password = token_hex(16)

    configure_mail_user(juju, mail_users_unit, user, old_password)
    configure_mail_user(juju, mail_users_unit, user, new_password)

    juju.exec(f"doveadm auth test {user} '{new_password}'", unit=mail_users_unit)
    with pytest.raises(jubilant.TaskError):
        juju.exec(f"doveadm auth test {user} '{old_password}'", unit=mail_users_unit)


def test_mail_users_secret_replaces_user_with_multiple_users(
    juju: jubilant.Juju, mail_users_unit: str
):
    """Rotating to multiple users removes old users and normalizes email-style logins."""
    old_user = f"secret-user-{token_hex(4)}"
    old_password = token_hex(16)
    bare_user = f"bare-user-{token_hex(4)}"
    bare_password = token_hex(16)
    new_user = f"mailbox-user-{token_hex(4)}"
    email_user = f"{new_user}@example.com"
    new_password = token_hex(16)

    configure_mail_user(juju, mail_users_unit, old_user, old_password)
    configure_mail_users(
        juju,
        mail_users_unit,
        {bare_user: bare_password, email_user: new_password},
    )

    juju.exec(f"doveadm auth test {bare_user} '{bare_password}'", unit=mail_users_unit)
    juju.exec(f"doveadm auth test {new_user} '{new_password}'", unit=mail_users_unit)
    juju.exec(f"doveadm auth test {email_user} '{new_password}'", unit=mail_users_unit)
    with pytest.raises(jubilant.TaskError):
        juju.exec(f"doveadm auth test {old_user} '{old_password}'", unit=mail_users_unit)


def test_clear_queue_action(juju: jubilant.Juju, dovecot_charm: str):
    """Test the clear-queue action."""
    unit_name = f"{dovecot_charm}/0"

    try:
        logger.info("Seeding one queued message before default clear-queue action...")
        seed_queue_with_test_mail(juju, unit_name)
        logger.info("Seeding one deferred message before default clear-queue action...")
        seed_deferred_queue_with_test_mail(juju, unit_name)

        logger.info("Running clear-queue action (defaults)...")
        result = juju.run(unit_name, "clear-queue")
        assert result.status == "completed"
        logger.info("clear-queue (defaults) output: %s", result.results.get("output"))
        assert_deferred_queue_empty(juju, unit_name)
        assert_queue_non_empty(juju, unit_name)

        logger.info("Running clear-queue action (all)...")
        result = juju.run(unit_name, "clear-queue", params={"queue": "all"})
        assert result.status == "completed"
        logger.info("clear-queue (all) output: %s", result.results.get("output"))
        assert_queue_empty(juju, unit_name)
    finally:
        cleanup_header_checks(juju, unit_name)


@pytest.mark.parametrize("compress", [True, False])
def test_gdpr_archive(juju: jubilant.Juju, gdpr_test_user: tuple, compress: bool):
    """gdpr-archive creates the expected output based on compress flag."""
    unit_name, username = gdpr_test_user
    result = juju.run(
        unit_name,
        "gdpr-archive",
        params={"username": username, "compress": compress},
    )
    assert result.status == "completed"
    assert result.results.get("status") == "success"
    archive_path = result.results.get("path", "")
    if compress:
        assert archive_path.endswith(".tar.gz")
        juju.exec(f"test -f {archive_path}", unit=unit_name)
    else:
        assert not archive_path.endswith(".tar.gz")
        juju.exec(f"test -d {archive_path}", unit=unit_name)


def test_gdpr_delete_requires_confirm(juju: jubilant.Juju, gdpr_test_user: tuple):
    """gdpr-delete without confirm=true must fail with a clear error message."""
    unit_name, username = gdpr_test_user
    with pytest.raises(jubilant.TaskError) as exc_info:
        juju.run(
            unit_name,
            "gdpr-delete",
            params={"username": username, "confirm": False},
        )
    assert "confirm" in str(exc_info.value).lower()
    juju.exec(f"test -d {MAIL_ROOT}/{username}", unit=unit_name)


def test_gdpr_delete_confirmed(juju: jubilant.Juju, gdpr_test_user: tuple):
    """gdpr-delete with confirm=true expunges all mail and removes the mail directory."""
    unit_name, username = gdpr_test_user
    result = juju.run(
        unit_name,
        "gdpr-delete",
        params={"username": username, "confirm": True},
    )
    assert result.status == "completed"
    assert result.results.get("status") == "success"
    juju.exec(f"test ! -d {MAIL_ROOT}/{username}", unit=unit_name)


@pytest.mark.parametrize("export_format", ["maildir", "mbox"])
def test_gdpr_takeout(juju: jubilant.Juju, gdpr_test_user: tuple, export_format: str):
    """gdpr-takeout creates a tarball for the given export format."""
    unit_name, username = gdpr_test_user
    result = juju.run(
        unit_name,
        "gdpr-takeout",
        params={"username": username, "format": export_format},
    )
    assert result.status == "completed"
    assert result.results.get("status") == "success"
    takeout_path = result.results.get("path", "")
    assert takeout_path.endswith(".tar.gz")
    juju.exec(f"test -f {takeout_path}", unit=unit_name)

    if export_format == "mbox":
        with tempfile.TemporaryDirectory() as tmp:
            local_tarball = os.path.join(tmp, "takeout.tar.gz")
            encoded_tarball = juju.exec(
                f"base64 -w0 {takeout_path}",
                unit=unit_name,
            ).stdout
            with open(local_tarball, "wb") as tarball:
                tarball.write(base64.b64decode(encoded_tarball))
            with tarfile.open(local_tarball, "r:gz") as tar:
                tar.extractall(path=tmp, filter="data")
            mbox_path = os.path.join(tmp, username, "INBOX")
            mbox_file = mailbox.mbox(mbox_path)
            assert len(mbox_file) >= 1, f"Expected at least 1 message, got {len(mbox_file)}"
