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

from conftest import TEST_DOMAIN, TEST_SMTP_PASSWORD, TEST_SMTP_USER

MAILBOX_USER = f"{TEST_SMTP_USER}@{TEST_DOMAIN}"
SMTP_SUBMISSION_PORT = 587
IMAP_PORT = 993


def test_e2e(juju: jubilant.Juju, mail_stack: Dict[str, str]) -> None:
    """Verify SMTP AUTH -> DKIM signing -> LMTP delivery -> IMAP retrieval."""
    relay_ip = mail_stack["postfix_relay_ip"]
    dovecot_ip = mail_stack["dovecot_ip"]

    dovecot_unit = f"{mail_stack['dovecot_app']}/0"
    action_result = juju.run(
        dovecot_unit,
        "create-mail-user",
        params={
            "username": TEST_SMTP_USER,
            "password": TEST_SMTP_PASSWORD,
            "mailbox-user": MAILBOX_USER,
        },
    )
    assert action_result.status == "completed"

    smtp_auth_users = yaml.dump([f"{MAILBOX_USER}:{_sha512_dovecot(TEST_SMTP_PASSWORD)}"])
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
    from_addr = MAILBOX_USER
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
        server.login(MAILBOX_USER, TEST_SMTP_PASSWORD)
        server.sendmail(from_addr, [to_addr], message)

    raw_message = _wait_for_subject(dovecot_ip, MAILBOX_USER, TEST_SMTP_PASSWORD, subject)
    # Dovecot accepts login with the full mailbox address (e.g. user@domain) when
    # auth_username_format is unset; the system user is looked up by local part.
    parsed = email.message_from_bytes(raw_message)

    assert parsed["Subject"] == subject
    assert "DKIM-Signature" in parsed
    assert TEST_DOMAIN in parsed.get("DKIM-Signature", "")


def _sha512_dovecot(password: str, salt: bytes | None = None) -> str:
    if salt is None:
        salt = os.urandom(8)
    digest = hashlib.sha512(password.encode() + salt).digest()
    return "{SSHA512}" + base64.b64encode(digest + salt).decode()


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
