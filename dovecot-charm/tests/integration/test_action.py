# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import secrets
import time

import jubilant
import pytest

logger = logging.getLogger(__name__)

GDPR_TEST_USER = "gdpr-testuser"
GDPR_TEST_PASSWORD = secrets.token_hex(16)
MAIL_ROOT = "/srv/mail"
GDPR_ARCHIVE_DIR = f"{MAIL_ROOT}/archives"
GDPR_TAKEOUT_DIR = f"{MAIL_ROOT}/takeout"


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
def test_gdpr_archive(juju: jubilant.Juju, dovecot_charm: str, compress: bool):
    """gdpr-archive creates the expected output based on compress flag."""
    unit_name = f"{dovecot_charm}/0"
    _setup_gdpr_test_user(juju, unit_name, GDPR_TEST_USER, GDPR_TEST_PASSWORD)
    try:
        result = juju.run(
            unit_name,
            "gdpr-archive",
            params={"username": GDPR_TEST_USER, "compress": compress},
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
    finally:
        _teardown_gdpr_test_user(juju, unit_name, GDPR_TEST_USER)
        juju.exec(f"rm -f {GDPR_ARCHIVE_DIR}/{GDPR_TEST_USER}.tar.gz", unit=unit_name)
        juju.exec(f"rm -rf {GDPR_ARCHIVE_DIR}/{GDPR_TEST_USER}", unit=unit_name)


def test_gdpr_delete_requires_confirm(juju: jubilant.Juju, dovecot_charm: str):
    """gdpr-delete without confirm=true must fail with a clear error message."""
    unit_name = f"{dovecot_charm}/0"
    _setup_gdpr_test_user(juju, unit_name, GDPR_TEST_USER, GDPR_TEST_PASSWORD)
    try:
        result = juju.run(
            unit_name,
            "gdpr-delete",
            params={"username": GDPR_TEST_USER, "confirm": False},
        )
        assert result.status == "failed"
        assert "confirm" in result.message.lower()
        juju.exec(f"test -d {MAIL_ROOT}/{GDPR_TEST_USER}", unit=unit_name)
    finally:
        _teardown_gdpr_test_user(juju, unit_name, GDPR_TEST_USER)


def test_gdpr_delete_confirmed(juju: jubilant.Juju, dovecot_charm: str):
    """gdpr-delete with confirm=true expunges all mail and removes the mail directory."""
    unit_name = f"{dovecot_charm}/0"
    _setup_gdpr_test_user(juju, unit_name, GDPR_TEST_USER, GDPR_TEST_PASSWORD)
    try:
        result = juju.run(
            unit_name,
            "gdpr-delete",
            params={"username": GDPR_TEST_USER, "confirm": True},
        )
        assert result.status == "completed"
        assert result.results.get("status") == "success"
        juju.exec(f"test ! -d {MAIL_ROOT}/{GDPR_TEST_USER}", unit=unit_name)
    finally:
        _teardown_gdpr_test_user(juju, unit_name, GDPR_TEST_USER)


@pytest.mark.parametrize("export_format", ["maildir", "mbox"])
def test_gdpr_takeout(juju: jubilant.Juju, dovecot_charm: str, export_format: str):
    """gdpr-takeout creates a tarball for the given export format."""
    unit_name = f"{dovecot_charm}/0"
    _setup_gdpr_test_user(juju, unit_name, GDPR_TEST_USER, GDPR_TEST_PASSWORD)
    try:
        result = juju.run(
            unit_name,
            "gdpr-takeout",
            params={"username": GDPR_TEST_USER, "format": export_format},
        )
        assert result.status == "completed"
        assert result.results.get("status") == "success"
        takeout_path = result.results.get("path", "")
        assert takeout_path.endswith(".tar.gz")
        juju.exec(f"test -f {takeout_path}", unit=unit_name)

        if export_format == "mbox":
            extract_dir = f"{GDPR_TAKEOUT_DIR}/{GDPR_TEST_USER}-verify"
            juju.exec(f"mkdir -p {extract_dir}", unit=unit_name)
            juju.exec(f"tar -xzf {takeout_path} -C {extract_dir}", unit=unit_name)
            mbox_path = f"{extract_dir}/{GDPR_TEST_USER}/{GDPR_TEST_USER}.mbox"
            juju.exec(f"grep -q '^From ' {mbox_path}", unit=unit_name)
            juju.exec(f"rm -rf {extract_dir}", unit=unit_name)
    finally:
        _teardown_gdpr_test_user(juju, unit_name, GDPR_TEST_USER)
        juju.exec(f"rm -f {GDPR_TAKEOUT_DIR}/{GDPR_TEST_USER}-takeout.tar.gz", unit=unit_name)


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
    except Exception:
        logger.exception("Failed to capture postqueue -p")
    try:
        result = juju.exec(
            "sudo find /var/spool/postfix/deferred -type f | head -20", unit=unit_name
        )
        logger.info("deferred spool files:\n%s", result.stdout or "(empty)")
    except Exception:
        logger.exception("Failed to capture deferred spool state")
    try:
        result = juju.exec("sudo postconf relayhost header_checks", unit=unit_name)
        logger.info("postconf relayhost header_checks:\n%s", result.stdout)
    except Exception:
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
    juju.exec(
        (
            f"id -u {user} >/dev/null 2>&1 || "
            f"useradd -M -d {MAIL_ROOT}/{user} -s /usr/sbin/nologin {user}"
        ),
        unit=unit_name,
    )
    juju.exec(f"echo '{user}:{password}' | chpasswd", unit=unit_name)
    juju.exec(f"usermod -aG mail {user}", unit=unit_name)
    juju.exec(f"install -d -m 0700 -o {user} -g mail {MAIL_ROOT}/{user}", unit=unit_name)
    juju.exec(f"doveadm mailbox create -u {user} INBOX 2>/dev/null || true", unit=unit_name)
    juju.exec(
        (
            f"printf 'From: {user}@example.com\\nSubject: GDPR test\\n\\ntest body\\n' | "
            f"doveadm deliver -u {user} -m INBOX"
        ),
        unit=unit_name,
    )


def _teardown_gdpr_test_user(juju: jubilant.Juju, unit_name: str, user: str) -> None:
    """Remove the test user and mail directory created by _setup_gdpr_test_user."""
    juju.exec(f"userdel -r {user} 2>/dev/null || true", unit=unit_name)
    juju.exec(f"rm -rf {MAIL_ROOT}/{user}", unit=unit_name)
