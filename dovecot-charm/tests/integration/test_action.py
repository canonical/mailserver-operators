# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import mailbox
import os
import secrets
import tarfile
import tempfile
import time

import jubilant
import pytest

logger = logging.getLogger(__name__)

GDPR_TEST_USER = "gdpr-testuser"
GDPR_TEST_PASSWORD = secrets.token_hex(16)
MAIL_ROOT = "/srv/mail"
GDPR_ARCHIVE_DIR = f"{MAIL_ROOT}/archives"
GDPR_TAKEOUT_DIR = f"{MAIL_ROOT}/takeout"


@pytest.fixture()
def gdpr_test_user(juju: jubilant.Juju, dovecot_charm: str):
    """Create a GDPR test user with one message; tear down after the test."""
    unit_name = f"{dovecot_charm}/0"
    _setup_gdpr_test_user(juju, unit_name, GDPR_TEST_USER, GDPR_TEST_PASSWORD)
    yield unit_name, GDPR_TEST_USER
    _teardown_gdpr_test_user(juju, unit_name, GDPR_TEST_USER)
    juju.exec(f"rm -f {GDPR_ARCHIVE_DIR}/{GDPR_TEST_USER}.tar.gz", unit=unit_name)
    juju.exec(f"rm -rf {GDPR_ARCHIVE_DIR}/{GDPR_TEST_USER}", unit=unit_name)
    juju.exec(f"rm -f {GDPR_TAKEOUT_DIR}/{GDPR_TEST_USER}-takeout.tar.gz", unit=unit_name)


def test_clear_queue_action(juju: jubilant.Juju, dovecot_charm: str):
    """Test the clear-queue action."""
    unit_name = f"{dovecot_charm}/0"

    try:
        logger.info("Seeding one queued message before default clear-queue action...")
        _seed_queue_with_test_mail(juju, unit_name)
        logger.info("Seeding one deferred message before default clear-queue action...")
        _seed_deferred_queue_with_test_mail(juju, unit_name)

        logger.info("Running clear-queue action (defaults)...")
        result = juju.run(unit_name, "clear-queue")
        assert result.status == "completed"
        logger.info("clear-queue (defaults) output: %s", result.results.get("output"))
        _assert_deferred_queue_empty(juju, unit_name)
        _assert_queue_non_empty(juju, unit_name)

        logger.info("Running clear-queue action (all)...")
        result = juju.run(unit_name, "clear-queue", params={"queue": "all"})
        assert result.status == "completed"
        logger.info("clear-queue (all) output: %s", result.results.get("output"))
        _assert_queue_empty(juju, unit_name)
    finally:
        _cleanup_header_checks(juju, unit_name)


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
            juju.scp(f"{unit_name}:{takeout_path}", local_tarball)
            with tarfile.open(local_tarball, "r:gz") as tar:
                tar.extractall(path=tmp, filter="data")
            mbox_path = os.path.join(tmp, username, "INBOX")
            mbox_file = mailbox.mbox(mbox_path)
            assert len(mbox_file) >= 1, f"Expected at least 1 message, got {len(mbox_file)}"


def _poll(juju: jubilant.Juju, unit_name: str, cmd: str, timeout: int = 60) -> None:
    """Poll a shell command on the unit until it exits 0, or raise after timeout."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            juju.exec(cmd, unit=unit_name)
            return
        except (jubilant.CLIError, jubilant.TaskError):
            if time.monotonic() >= deadline:
                logger.error("Timed out waiting for: %s", cmd)
                _log_queue_state(juju, unit_name)
                raise
            time.sleep(2)


def _log_queue_state(juju: jubilant.Juju, unit_name: str) -> None:
    """Log the current Postfix queue and deferred spool state for diagnostics."""
    try:
        result = juju.exec("postqueue -p", unit=unit_name)
        logger.info("postqueue -p:\n%s", result.stdout)
    except (jubilant.CLIError, jubilant.TaskError):
        logger.exception("Failed to capture postqueue -p")
    try:
        result = juju.exec(
            "sudo find /var/spool/postfix/deferred -type f | head -20", unit=unit_name
        )
        logger.info("deferred spool files:\n%s", result.stdout or "(empty)")
    except (jubilant.CLIError, jubilant.TaskError):
        logger.exception("Failed to capture deferred spool state")
    try:
        result = juju.exec("sudo postconf relayhost header_checks", unit=unit_name)
        logger.info("postconf relayhost header_checks:\n%s", result.stdout)
    except (jubilant.CLIError, jubilant.TaskError):
        logger.exception("Failed to capture postconf state")


def _seed_queue_with_test_mail(juju: jubilant.Juju, unit_name: str) -> None:
    """Queue a test message and wait until Postfix reports a non-empty queue."""
    juju.exec(
        'sudo postconf -e "header_checks = regexp:/etc/postfix/header_checks"',
        unit=unit_name,
    )
    juju.exec(
        'echo "/^Subject:.*queue.*/  HOLD" | sudo tee /etc/postfix/header_checks',
        unit=unit_name,
    )
    juju.exec(
        "sudo postmap /etc/postfix/header_checks && sudo postfix reload",
        unit=unit_name,
    )
    juju.exec(
        "printf 'Subject: queue-test\\n\\nmessage body\\n' | "
        "/usr/sbin/sendmail -f test@yourdomain.com someone@example.com || true",
        unit=unit_name,
    )
    _poll(juju, unit_name, "postqueue -p | grep -qv 'Mail queue is empty'", timeout=60)


def _cleanup_header_checks(juju: jubilant.Juju, unit_name: str) -> None:
    """Remove the HOLD header_checks rule so it does not affect subsequent runs."""
    juju.exec("sudo postconf -e 'header_checks ='", unit=unit_name)
    juju.exec("sudo postfix reload", unit=unit_name)


def _seed_deferred_queue_with_test_mail(juju: jubilant.Juju, unit_name: str) -> None:
    """Queue one deferred message by temporarily deferring SMTP transports."""
    juju.exec(
        "sudo postconf -e 'relayhost = [10.255.255.255]' && sudo postfix reload", unit=unit_name
    )
    try:
        juju.exec(
            "printf 'Subject: deferred-test\\n\\nmessage body\\n' | "
            "/usr/sbin/sendmail -f deferred-test@example.com deferred-test@example.net || true",
            unit=unit_name,
        )
        _poll(
            juju,
            unit_name,
            "sudo find /var/spool/postfix/deferred -type f -print -quit | grep -q .",
            timeout=60,
        )
    finally:
        juju.exec("sudo postconf -e 'relayhost =' && sudo postfix reload", unit=unit_name)


def _assert_queue_empty(juju: jubilant.Juju, unit_name: str) -> None:
    """Poll until Postfix reports an empty queue."""
    _poll(juju, unit_name, "postqueue -p | grep -q 'Mail queue is empty'", timeout=60)


def _assert_deferred_queue_empty(juju: jubilant.Juju, unit_name: str) -> None:
    """Poll until the deferred queue contains no files."""
    _poll(
        juju,
        unit_name,
        "! sudo find /var/spool/postfix/deferred -type f -print -quit | grep -q .",
        timeout=60,
    )


def _assert_queue_non_empty(juju: jubilant.Juju, unit_name: str) -> None:
    """Assert that Postfix reports a non-empty queue."""
    juju.exec("postqueue -p | grep -qv 'Mail queue is empty'", unit=unit_name)


def _setup_gdpr_test_user(juju: jubilant.Juju, unit_name: str, user: str, password: str) -> None:
    """Create a system user with a Dovecot mailbox containing one test message."""
    action_result = juju.run(
        unit_name, "create-mail-user", params={"username": user, "password": password}
    )
    assert (
        action_result.status == "success"
    ), f"create-mail-user action failed for {user}: status={action_result.status}"
    juju.exec(f"install -d -m 0700 -o {user} -g mail {MAIL_ROOT}/{user}", unit=unit_name)
    juju.exec(f"doveadm mailbox create -u {user} INBOX 2>/dev/null || true", unit=unit_name)
    juju.exec(
        (
            f"printf 'From: {user}@example.com\\nSubject: GDPR test\\n\\ntest body\\n' | "
            f"doveadm save -u {user} -m INBOX"
        ),
        unit=unit_name,
    )


def _teardown_gdpr_test_user(juju: jubilant.Juju, unit_name: str, user: str) -> None:
    """Remove the test user and mail directory created by _setup_gdpr_test_user."""
    juju.exec(f"userdel -r {user} 2>/dev/null || true", unit=unit_name)
    juju.exec(f"rm -rf {MAIL_ROOT}/{user}", unit=unit_name)


CREATE_MAIL_USER_TEST_USER = "cmu-testuser"
CREATE_MAIL_USER_TEST_MAILBOX = "cmu-testuser@example.com"
CREATE_MAIL_USER_TEST_PASSWORD = secrets.token_hex(16)


@pytest.fixture()
def create_mail_user_cleanup(juju: jubilant.Juju, dovecot_charm: str):
    """Tear down users created by create-mail-user tests."""
    unit_name = f"{dovecot_charm}/0"
    yield unit_name
    for user in (CREATE_MAIL_USER_TEST_USER, CREATE_MAIL_USER_TEST_MAILBOX):
        juju.exec(f"userdel -r {user} 2>/dev/null || true", unit=unit_name)


def test_create_mail_user_creates_new_user(juju: jubilant.Juju, create_mail_user_cleanup: str):
    """create-mail-user action creates a new system user in the mail group."""
    unit_name = create_mail_user_cleanup
    result = juju.run(
        unit_name,
        "create-mail-user",
        params={
            "username": CREATE_MAIL_USER_TEST_USER,
            "password": CREATE_MAIL_USER_TEST_PASSWORD,
        },
    )
    assert result.status == "completed"
    assert result.results.get("status") == "success"
    assert CREATE_MAIL_USER_TEST_USER in result.results.get("created", "")
    assert result.results.get("updated") == ""

    juju.exec(f"id {CREATE_MAIL_USER_TEST_USER}", unit=unit_name)
    groups_output = juju.exec(f"groups {CREATE_MAIL_USER_TEST_USER}", unit=unit_name)
    assert "mail" in groups_output.stdout


def test_create_mail_user_updates_existing_user(
    juju: jubilant.Juju, create_mail_user_cleanup: str
):
    """create-mail-user action reports updated when the user already exists."""
    unit_name = create_mail_user_cleanup
    # Create first
    juju.run(
        unit_name,
        "create-mail-user",
        params={
            "username": CREATE_MAIL_USER_TEST_USER,
            "password": CREATE_MAIL_USER_TEST_PASSWORD,
        },
    )
    # Run again — should report updated, not created
    result = juju.run(
        unit_name,
        "create-mail-user",
        params={
            "username": CREATE_MAIL_USER_TEST_USER,
            "password": CREATE_MAIL_USER_TEST_PASSWORD,
        },
    )
    assert result.status == "completed"
    assert result.results.get("status") == "success"
    assert result.results.get("created") == ""
    assert CREATE_MAIL_USER_TEST_USER in result.results.get("updated", "")


def test_create_mail_user_with_mailbox_user(juju: jubilant.Juju, create_mail_user_cleanup: str):
    """create-mail-user action creates both primary and mailbox-style users."""
    unit_name = create_mail_user_cleanup
    result = juju.run(
        unit_name,
        "create-mail-user",
        params={
            "username": CREATE_MAIL_USER_TEST_USER,
            "password": CREATE_MAIL_USER_TEST_PASSWORD,
            "mailbox-user": CREATE_MAIL_USER_TEST_MAILBOX,
        },
    )
    assert result.status == "completed"
    assert result.results.get("status") == "success"
    created = result.results.get("created", "")
    assert CREATE_MAIL_USER_TEST_USER in created
    assert CREATE_MAIL_USER_TEST_MAILBOX in created

    for user in (CREATE_MAIL_USER_TEST_USER, CREATE_MAIL_USER_TEST_MAILBOX):
        groups_output = juju.exec(f"groups {user}", unit=unit_name)
        assert "mail" in groups_output.stdout
