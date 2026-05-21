# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Single end-to-end test for the full mail system."""

import base64
import contextlib
import email
import hashlib
import imaplib
import os
import smtplib
import ssl
import time
from typing import Dict

import jubilant
import pytest
import yaml

TEST_DOMAIN = "mailstack.internal"
TEST_USER = "e2euser"
MAILBOX_USER = f"{TEST_USER}@{TEST_DOMAIN}"
TEST_PASSWORD = "E2eP@ssw0rd!"  # nosec B105
SMTP_SUBMISSION_PORT = 587
IMAP_PORT = 993


def _sha512_dovecot(password: str, salt: bytes | None = None) -> str:
    if salt is None:
        salt = os.urandom(8)
    digest = hashlib.sha512(password.encode() + salt).digest()
    return "{SSHA512}" + base64.b64encode(digest + salt).decode()


def _setup_dovecot_user(juju: jubilant.Juju, username: str, password: str) -> None:
    status = juju.status()
    unit_name = next(iter(status.apps["dovecot-charm"].units))
    juju.exec(f"id -u {username} &>/dev/null || sudo useradd -m {username}", unit=unit_name)
    juju.exec(
        f"id -u {MAILBOX_USER} &>/dev/null || sudo useradd --badname -m {MAILBOX_USER}",
        unit=unit_name,
    )
    juju.exec(f"sudo usermod -aG mail {username}", unit=unit_name)
    juju.exec(f"sudo usermod -aG mail {MAILBOX_USER}", unit=unit_name)
    juju.exec(f"echo '{username}:{password}' | sudo chpasswd", unit=unit_name)
    juju.exec(f"echo '{MAILBOX_USER}:{password}' | sudo chpasswd", unit=unit_name)


def _wait_for_subject(host: str, username: str, password: str, subject: str) -> bytes:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            conn = imaplib.IMAP4_SSL(host, port=IMAP_PORT, ssl_context=ctx)
            try:
                conn.login(username, password)
                conn.select("inbox")
                _, data = conn.search(None, f'(HEADER Subject "{subject}")')
                if data and data[0]:
                    msg_id = data[0].split()[-1]
                    _, msg_data = conn.fetch(msg_id, "(RFC822)")
                    return msg_data[0][1]  # type: ignore[index]
            finally:
                with contextlib.suppress(Exception):
                    conn.close()
                with contextlib.suppress(Exception):
                    conn.logout()
        except Exception:
            pass
        time.sleep(3)

    pytest.fail(f"Message with subject '{subject}' did not arrive in IMAP inbox")


@pytest.mark.abort_on_fail
def test_whole_email_system_e2e(juju: jubilant.Juju, mail_stack: Dict[str, str]) -> None:
    """Verify SMTP AUTH -> DKIM signing -> LMTP delivery -> IMAP retrieval."""
    relay_ip = mail_stack["postfix_relay_ip"]
    dovecot_ip = mail_stack["dovecot_ip"]

    _setup_dovecot_user(juju, TEST_USER, TEST_PASSWORD)

    smtp_auth_users = yaml.dump([f"{TEST_USER}:{_sha512_dovecot(TEST_PASSWORD)}"])
    juju.config(
        "postfix-relay",
        {
            "enable_smtp_auth": "true",
            "smtp_auth_users": smtp_auth_users,
        },
    )
    juju.wait(
        lambda status: status.apps["postfix-relay"].is_active,
        error=jubilant.any_error,
        timeout=5 * 60,
    )

    subject = f"Whole system e2e {int(time.time())}"
    from_addr = f"sender@{TEST_DOMAIN}"
    to_addr = MAILBOX_USER
    message = (
        f"Subject: {subject}\r\n"
        f"From: {from_addr}\r\n"
        f"To: {to_addr}\r\n"
        "\r\n"
        "full system integration test\r\n"
    )

    tls_ctx = ssl.create_default_context()
    tls_ctx.check_hostname = False
    tls_ctx.verify_mode = ssl.CERT_NONE

    with smtplib.SMTP(relay_ip, SMTP_SUBMISSION_PORT, timeout=30) as server:
        server.ehlo()
        server.starttls(context=tls_ctx)
        server.ehlo()
        server.login(TEST_USER, TEST_PASSWORD)
        server.sendmail(from_addr, [to_addr], message)

    raw_message = _wait_for_subject(dovecot_ip, MAILBOX_USER, TEST_PASSWORD, subject)
    parsed = email.message_from_bytes(raw_message)

    assert parsed["Subject"] == subject
    assert "DKIM-Signature" in parsed
    assert TEST_DOMAIN in parsed.get("DKIM-Signature", "")
