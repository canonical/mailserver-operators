# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import time

import jubilant
import pytest


def _seed_queue_with_test_mail(juju: jubilant.Juju, unit_name: str):
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
    time.sleep(10)
    juju.exec(
        "for i in $(seq 1 30); do "
        "postqueue -p | grep -qv 'Mail queue is empty' && exit 0; "
        "sleep 1; "
        "done; "
        "exit 1",
        unit=unit_name,
    )


def _seed_deferred_queue_with_test_mail(juju: jubilant.Juju, unit_name: str):
    """Queue one deferred message by temporarily deferring SMTP transports."""
    juju.exec("postconf -e 'relayhost = [10.255.255.255]' && postfix reload", unit=unit_name)
    time.sleep(5)  # Give Postfix some time to process the new message
    try:
        juju.exec(
            "printf 'Subject: deferred-test\\n\\nmessage body\\n' | "
            "/usr/sbin/sendmail -f deferred-test@example.com deferred-test@example.net || true",
            unit=unit_name,
        )
        time.sleep(10)  # Give Postfix some time to process the new message
        juju.exec(
            "for i in $(seq 1 30); do "
            "sudo find /var/spool/postfix/deferred -type f | grep -q . && exit 0; "
            "sleep 1; "
            "done; "
            "exit 1",
            unit=unit_name,
        )
    finally:
        juju.exec("sudo postconf -e 'relayhost =' && postfix reload", unit=unit_name)


def _assert_queue_empty(juju: jubilant.Juju, unit_name: str):
    """Assert that Postfix reports an empty queue."""
    juju.exec("postqueue -p | grep -q 'Mail queue is empty'", unit=unit_name)


def _assert_deferred_queue_empty(juju: jubilant.Juju, unit_name: str):
    """Assert that the deferred queue has no queued files."""
    juju.exec(
        "sudo find /var/spool/postfix/deferred -type f | grep -q . && exit 1 || exit 0",
        unit=unit_name,
    )


def _assert_queue_non_empty(juju: jubilant.Juju, unit_name: str):
    """Assert that Postfix reports a non-empty queue."""
    juju.exec("postqueue -p | grep -qv 'Mail queue is empty'", unit=unit_name)


def test_clear_queue_action(juju: jubilant.Juju, dovecot_charm: str):
    """Test the clear-queue action."""
    unit_name = f"{dovecot_charm}/0"

    logging.info("Seeding one queued message before default clear-queue action...")
    _seed_queue_with_test_mail(juju, unit_name)
    logging.info("Seeding one deferred message before default clear-queue action...")
    _seed_deferred_queue_with_test_mail(juju, unit_name)

    logging.info("Running clear-queue action (defaults)...")
    time.sleep(5)
    result = juju.run(unit_name, "clear-queue")
    assert result.status == "completed"
    logging.info(f"Action output: {result.results.get('output')}")
    time.sleep(5)
    _assert_deferred_queue_empty(juju, unit_name)
    _assert_queue_non_empty(juju, unit_name)

    logging.info("Running clear-queue action (all)...")
    result = juju.run(unit_name, "clear-queue", params={"queue": "all"})
    assert result.status == "completed"
    logging.info(f"Action output: {result.results.get('output')}")
    time.sleep(15)
    _assert_queue_empty(juju, unit_name)


# ---------------------------------------------------------------------------
# GDPR action helpers
# ---------------------------------------------------------------------------

GDPR_TEST_USER = "gdpr-testuser"
GDPR_TEST_PASSWORD = "TestPass123!"
MAIL_ROOT = "/srv/mail"


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
    juju.exec(
        (
            f"install -d -m 0700 -o {user} -g mail {MAIL_ROOT}/{user} && "
            f"doveadm mailbox create -u {user} INBOX 2>/dev/null || true"
        ),
        unit=unit_name,
    )
    # Inject one test message so there is mail to archive/export/delete
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


# ---------------------------------------------------------------------------
# GDPR archive action
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("dovecot_charm")
def test_gdpr_archive_compressed(juju: jubilant.Juju, dovecot_charm: str):
    """gdpr-archive with compress=True creates a .tar.gz archive on the unit."""
    unit_name = f"{dovecot_charm}/0"
    _setup_gdpr_test_user(juju, unit_name, GDPR_TEST_USER, GDPR_TEST_PASSWORD)
    try:
        logging.info("Running gdpr-archive action (compress=True)...")
        result = juju.run(
            unit_name,
            "gdpr-archive",
            params={"username": GDPR_TEST_USER, "compress": True},
        )
        assert result.status == "completed"
        assert result.results.get("status") == "success"
        archive_path = result.results.get("path", "")
        assert archive_path.endswith(".tar.gz"), f"Expected .tar.gz path, got: {archive_path}"
        logging.info(f"Archive created at: {archive_path}")
        # Verify the file actually exists on the unit
        juju.exec(f"test -f {archive_path}", unit=unit_name)
    finally:
        _teardown_gdpr_test_user(juju, unit_name, GDPR_TEST_USER)
        juju.exec(f"rm -f /srv/mail/archives/{GDPR_TEST_USER}.tar.gz", unit=unit_name)
        juju.exec(f"rm -rf /srv/mail/archives/{GDPR_TEST_USER}", unit=unit_name)


@pytest.mark.usefixtures("dovecot_charm")
def test_gdpr_archive_uncompressed(juju: jubilant.Juju, dovecot_charm: str):
    """gdpr-archive with compress=False creates an uncompressed backup directory."""
    unit_name = f"{dovecot_charm}/0"
    _setup_gdpr_test_user(juju, unit_name, GDPR_TEST_USER, GDPR_TEST_PASSWORD)
    try:
        logging.info("Running gdpr-archive action (compress=False)...")
        result = juju.run(
            unit_name,
            "gdpr-archive",
            params={"username": GDPR_TEST_USER, "compress": False},
        )
        assert result.status == "completed"
        assert result.results.get("status") == "success"
        archive_path = result.results.get("path", "")
        assert not archive_path.endswith(".tar.gz"), f"Expected directory path, got: {archive_path}"
        logging.info(f"Archive directory at: {archive_path}")
        juju.exec(f"test -d {archive_path}", unit=unit_name)
    finally:
        _teardown_gdpr_test_user(juju, unit_name, GDPR_TEST_USER)
        juju.exec(f"rm -rf /srv/mail/archives/{GDPR_TEST_USER}", unit=unit_name)


# ---------------------------------------------------------------------------
# GDPR delete action
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("dovecot_charm")
def test_gdpr_delete_requires_confirm(juju: jubilant.Juju, dovecot_charm: str):
    """gdpr-delete without confirm=true must fail with a clear error message."""
    unit_name = f"{dovecot_charm}/0"
    _setup_gdpr_test_user(juju, unit_name, GDPR_TEST_USER, GDPR_TEST_PASSWORD)
    try:
        logging.info("Running gdpr-delete without confirmation...")
        result = juju.run(
            unit_name,
            "gdpr-delete",
            params={"username": GDPR_TEST_USER, "confirm": False},
        )
        assert result.status == "failed"
        assert "confirm" in result.message.lower()
        # Mail directory must still exist
        juju.exec(f"test -d {MAIL_ROOT}/{GDPR_TEST_USER}", unit=unit_name)
    finally:
        _teardown_gdpr_test_user(juju, unit_name, GDPR_TEST_USER)


@pytest.mark.usefixtures("dovecot_charm")
def test_gdpr_delete_confirmed(juju: jubilant.Juju, dovecot_charm: str):
    """gdpr-delete with confirm=true expunges all mail and removes the mail directory."""
    unit_name = f"{dovecot_charm}/0"
    _setup_gdpr_test_user(juju, unit_name, GDPR_TEST_USER, GDPR_TEST_PASSWORD)
    try:
        logging.info("Running gdpr-delete with confirmation...")
        result = juju.run(
            unit_name,
            "gdpr-delete",
            params={"username": GDPR_TEST_USER, "confirm": True},
        )
        assert result.status == "completed"
        assert result.results.get("status") == "success"
        # Mail directory must be gone
        juju.exec(
            f"test ! -d {MAIL_ROOT}/{GDPR_TEST_USER}",
            unit=unit_name,
        )
        logging.info(f"Mail directory for {GDPR_TEST_USER} removed as expected")
    finally:
        # User account cleanup (mail dir already gone on success path)
        juju.exec(f"userdel {GDPR_TEST_USER} 2>/dev/null || true", unit=unit_name)


# ---------------------------------------------------------------------------
# GDPR takeout action
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("dovecot_charm")
def test_gdpr_takeout_maildir(juju: jubilant.Juju, dovecot_charm: str):
    """gdpr-takeout with format=maildir creates a tarball of the user's mail in Maildir format."""
    unit_name = f"{dovecot_charm}/0"
    _setup_gdpr_test_user(juju, unit_name, GDPR_TEST_USER, GDPR_TEST_PASSWORD)
    try:
        logging.info("Running gdpr-takeout action (format=maildir)...")
        result = juju.run(
            unit_name,
            "gdpr-takeout",
            params={"username": GDPR_TEST_USER, "format": "maildir"},
        )
        assert result.status == "completed"
        assert result.results.get("status") == "success"
        takeout_path = result.results.get("path", "")
        assert takeout_path.endswith(".tar.gz"), f"Expected .tar.gz path, got: {takeout_path}"
        logging.info(f"Takeout archive at: {takeout_path}")
        juju.exec(f"test -f {takeout_path}", unit=unit_name)
    finally:
        _teardown_gdpr_test_user(juju, unit_name, GDPR_TEST_USER)
        juju.exec(f"rm -f /tmp/gdpr-takeout/{GDPR_TEST_USER}-takeout.tar.gz", unit=unit_name)  # noqa: S108


@pytest.mark.usefixtures("dovecot_charm")
def test_gdpr_takeout_mbox(juju: jubilant.Juju, dovecot_charm: str):
    """gdpr-takeout with format=mbox creates a tarball containing an mbox file."""
    unit_name = f"{dovecot_charm}/0"
    _setup_gdpr_test_user(juju, unit_name, GDPR_TEST_USER, GDPR_TEST_PASSWORD)
    try:
        logging.info("Running gdpr-takeout action (format=mbox)...")
        result = juju.run(
            unit_name,
            "gdpr-takeout",
            params={"username": GDPR_TEST_USER, "format": "mbox"},
        )
        assert result.status == "completed"
        assert result.results.get("status") == "success"
        takeout_path = result.results.get("path", "")
        assert takeout_path.endswith(".tar.gz"), f"Expected .tar.gz path, got: {takeout_path}"
        logging.info(f"Takeout archive at: {takeout_path}")
        juju.exec(f"test -f {takeout_path}", unit=unit_name)
    finally:
        _teardown_gdpr_test_user(juju, unit_name, GDPR_TEST_USER)
        juju.exec(f"rm -f /tmp/gdpr-takeout/{GDPR_TEST_USER}-takeout.tar.gz", unit=unit_name)  # noqa: S108
