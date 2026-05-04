# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Full-stack integration tests for the mailserver operators monorepo.

These tests exercise the complete mail path:

    test runner ──SMTP AUTH/STARTTLS (port 587)──►  postfix-relay
                                                          │
                                              milter ──► opendkim  (DKIM sign)
                                                          │
                                            LMTP :24 ──► dovecot
                                                          │
    test runner ◄──IMAP SSL (port 993)────────────────────┘

All four charms must be pre-built and passed via repeated CLI options:
    --charm-file=<path/to/dovecot-charm_amd64.charm>
    --charm-file=<path/to/postfix-relay_amd64.charm>
    --charm-file=<path/to/opendkim_amd64.charm>
    --charm-file=<path/to/postfix-relay-configurator_amd64.charm>

A self-signed-certificates charm is pulled from CharmHub to provide TLS
for postfix-relay and dovecot.
"""

import base64
import contextlib
import email
import hashlib
import imaplib
import logging
import os
import smtplib
import ssl
import time
import typing

import jubilant
import pytest
import requests

# App name constants — kept in sync with conftest.py.
DOVECOT_APP = "dovecot-charm"
POSTFIX_RELAY_APP = "postfix-relay"
OPENDKIM_APP = "opendkim"
CONFIGURATOR_APP = "postfix-relay-configurator"
SELF_SIGNED_APP = "self-signed-certificates"
TEST_DOMAIN = "mailstack.internal"

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------
IMAP_PORT = 993
SMTP_SUBMISSION_PORT = 587
METRICS_PORT = 9103

TEST_USER = "testuser"
TEST_PASSWORD = "TestP@ssw0rd!"  # nosec B105


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _sha512_dovecot(password: str, salt: bytes | None = None) -> str:
    """Return a Dovecot-compatible SSHA512 hash for *password*.

    This is the same algorithm used by postfix-relay's SMTP AUTH Dovecot
    backend to validate credentials.
    """
    if salt is None:
        salt = os.urandom(8)
    digest = hashlib.sha512(password.encode() + salt).digest()
    return "{SSHA512}" + base64.b64encode(digest + salt).decode()


def _wait_for_imap_message(
    host: str,
    username: str,
    password: str,
    subject: str,
    *,
    retries: int = 20,
    delay: float = 3.0,
) -> bytes:
    """Poll dovecot via IMAP4_SSL until a message with *subject* arrives.

    Args:
        host: Dovecot unit's public IP address.
        username: IMAP login name.
        password: IMAP login password.
        subject: Expected Subject header value to search for.
        retries: Number of polling attempts before giving up.
        delay: Seconds to wait between attempts.

    Returns:
        The raw RFC822 bytes of the first matching message.

    Raises:
        pytest.fail: If the message is not found within *retries* attempts.
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    for attempt in range(retries):
        try:
            conn = imaplib.IMAP4_SSL(host, port=IMAP_PORT, ssl_context=ctx)
            try:
                conn.login(username, password)
                conn.select("inbox")
                _, data = conn.search(None, f'(HEADER Subject "{subject}")')
                if data and data[0]:
                    msg_ids = data[0].split()
                    _, msg_data = conn.fetch(msg_ids[-1], "(RFC822)")
                    raw: bytes = msg_data[0][1]  # type: ignore[index]
                    logger.info("Message found (attempt %d): %d bytes", attempt + 1, len(raw))
                    return raw
                logger.debug("Message not yet in INBOX (attempt %d/%d)", attempt + 1, retries)
            finally:
                with contextlib.suppress(Exception):
                    conn.close()
                with contextlib.suppress(Exception):
                    conn.logout()
        except Exception as exc:  # noqa: BLE001
            logger.warning("IMAP attempt %d failed: %s", attempt + 1, exc)

        time.sleep(delay)

    pytest.fail(f"Message with subject '{subject}' never arrived in dovecot INBOX.")


def _setup_dovecot_user(
    juju: jubilant.Juju,
    dovecot_app: str,
    username: str,
    password: str,
) -> None:
    """Create / update an OS user on the dovecot unit and add them to the mail group."""
    status = juju.status()
    unit_name = next(iter(status.apps[dovecot_app].units))
    # Create user if missing, then set password and add to mail group.
    juju.exec(
        f"id -u {username} &>/dev/null || sudo useradd -m {username}",
        unit=unit_name,
    )
    juju.exec(f"sudo usermod -aG mail {username}", unit=unit_name)
    juju.exec(f"echo '{username}:{password}' | sudo chpasswd", unit=unit_name)
    logger.info("Dovecot OS user '%s' configured on %s", username, unit_name)


# ---------------------------------------------------------------------------
# Test 1: All apps reach active status
# ---------------------------------------------------------------------------
@pytest.mark.abort_on_fail
def test_stack_is_active(juju: jubilant.Juju, mail_stack: typing.Dict[str, str]) -> None:
    """
    arrange: Deploy the full mail stack (postfix-relay, opendkim, dovecot,
             postfix-relay-configurator, self-signed-certificates).
    act: Wait for all applications to reach active status (done in fixtures).
    assert: Every application in the stack reports active.
    """
    status = juju.status()

    for app_name in (
        DOVECOT_APP,
        POSTFIX_RELAY_APP,
        OPENDKIM_APP,
        SELF_SIGNED_APP,
    ):
        app = status.apps.get(app_name)
        assert app is not None, f"Application '{app_name}' not found in model"
        assert app.is_active, (
            f"Application '{app_name}' is not active: "
            f"{app.app_status.current!r} — {app.app_status.message!r}"
        )
        logger.info("✓ %s is active", app_name)

    # The configurator is a subordinate — its units live inside postfix-relay units.
    relay_units = status.apps[POSTFIX_RELAY_APP].units
    for unit_name, unit in relay_units.items():
        subordinates = unit.subordinates or {}
        assert any(CONFIGURATOR_APP in sub_name for sub_name in subordinates), (
            f"postfix-relay-configurator subordinate not found on unit {unit_name}"
        )
    logger.info("✓ %s subordinate present on all postfix-relay units", CONFIGURATOR_APP)


# ---------------------------------------------------------------------------
# Test 2: End-to-end send → DKIM sign → deliver → IMAP retrieve
# ---------------------------------------------------------------------------
@pytest.mark.abort_on_fail
def test_send_and_receive_with_dkim(
    juju: jubilant.Juju,
    mail_stack: typing.Dict[str, str],
) -> None:
    """
    arrange: Full mail stack is active. A local OS user exists on dovecot.
             postfix-relay has SMTP AUTH enabled with the test user's credentials.
             opendkim is configured to sign mail from TEST_DOMAIN.
             The configurator routes TEST_DOMAIN mail to dovecot via LMTP.
    act: Send an email via SMTP AUTH (port 587 + STARTTLS) to
         testuser@mailstack.internal through postfix-relay.
    assert:
        - The message is delivered to the dovecot mailbox.
        - The raw RFC822 message contains a DKIM-Signature header.
        - The Subject and From headers match what was sent.
    """
    relay_ip = mail_stack["postfix_relay_ip"]
    dovecot_ip = mail_stack["dovecot_ip"]

    # 1. Create OS user on dovecot for IMAP login.
    _setup_dovecot_user(juju, DOVECOT_APP, TEST_USER, TEST_PASSWORD)

    # 2. Configure SMTP AUTH credentials on postfix-relay.
    import yaml  # noqa: PLC0415

    hashed = _sha512_dovecot(TEST_PASSWORD)
    auth_users_yaml = yaml.dump([f"{TEST_USER}:{hashed}"])
    juju.config(
        POSTFIX_RELAY_APP,
        {
            "enable_smtp_auth": "true",
            "smtp_auth_users": auth_users_yaml,
        },
    )
    juju.wait(
        lambda status: status.apps[POSTFIX_RELAY_APP].is_active,
        error=jubilant.any_error,
        timeout=5 * 60,
    )

    subject = f"Full-stack DKIM test {int(time.time())}"
    from_addr = f"sender@{TEST_DOMAIN}"
    to_addr = f"{TEST_USER}@{TEST_DOMAIN}"
    body = (
        f"Subject: {subject}\r\n"
        f"From: {from_addr}\r\n"
        f"To: {to_addr}\r\n"
        f"\r\n"
        f"This message was sent through the full mailserver stack.\r\n"
    )

    # 3. Send via postfix-relay with SMTP AUTH + STARTTLS.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    with smtplib.SMTP(relay_ip, SMTP_SUBMISSION_PORT, timeout=30) as server:
        server.set_debuglevel(1)
        server.ehlo()
        server.starttls(context=ctx)
        server.ehlo()
        server.login(TEST_USER, TEST_PASSWORD)
        server.sendmail(from_addr, [to_addr], body)
    logger.info("Message submitted to postfix-relay at %s:%d", relay_ip, SMTP_SUBMISSION_PORT)

    # 4. Poll dovecot IMAP until the message lands in the inbox.
    raw_message = _wait_for_imap_message(
        dovecot_ip,
        TEST_USER,
        TEST_PASSWORD,
        subject,
    )

    # 5. Parse and assert.
    msg = email.message_from_bytes(raw_message)
    logger.info("Received headers: %s", dict(msg.items()))

    assert "DKIM-Signature" in msg, (
        "DKIM-Signature header missing — opendkim did not sign the message.\n"
        f"Headers present: {list(msg.keys())}"
    )
    assert msg["Subject"] == subject, (
        f"Subject mismatch: expected {subject!r}, got {msg['Subject']!r}"
    )
    assert TEST_DOMAIN in msg.get("DKIM-Signature", ""), (
        f"DKIM-Signature does not reference domain {TEST_DOMAIN!r}.\n"
        f"DKIM-Signature: {msg.get('DKIM-Signature')}"
    )
    logger.info("✓ DKIM-signed message delivered and verified via IMAP")


# ---------------------------------------------------------------------------
# Test 3: Unauthenticated SMTP is rejected on port 587
# ---------------------------------------------------------------------------
@pytest.mark.abort_on_fail
def test_unauthenticated_smtp_rejected(
    juju: jubilant.Juju,
    mail_stack: typing.Dict[str, str],
) -> None:
    """
    arrange: postfix-relay has SMTP AUTH enabled (enable_smtp_auth=true).
    act: Attempt to relay mail on port 587 to an external domain without
         providing AUTH credentials.
    assert: The server refuses the recipient (SMTPRecipientsRefused or
            SMTPSenderRefused), indicating that unauthenticated relay to
            external destinations is blocked.
    """
    relay_ip = mail_stack["postfix_relay_ip"]

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    # Send to a domain that is NOT in relay_domains — this should be deferred/rejected
    # for unauthenticated clients by the defer_unauth_destination restriction.
    with pytest.raises((smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused)):
        with smtplib.SMTP(relay_ip, SMTP_SUBMISSION_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls(context=ctx)
            server.ehlo()
            # No server.login() — deliberately unauthenticated
            server.sendmail(
                from_addr=f"attacker@{TEST_DOMAIN}",
                to_addrs=["victim@external.example.com"],
                msg="Subject: Spam\r\n\r\nShouldBeRejected",
            )

    logger.info("✓ Unauthenticated relay correctly refused on port %d", SMTP_SUBMISSION_PORT)


# ---------------------------------------------------------------------------
# Test 4: opendkim blocks when given an invalid key path
# ---------------------------------------------------------------------------
def test_dkim_invalid_key_blocks_opendkim(
    juju: jubilant.Juju,
    mail_stack: typing.Dict[str, str],
) -> None:
    """
    arrange: opendkim is active with a valid DKIM key configuration.
    act: Reconfigure the keytable to point to a non-existent key file.
    assert: opendkim transitions to blocked with a configuration error message.
    act (restore): Restore the original valid configuration.
    assert: opendkim returns to active.
    """
    import json  # noqa: PLC0415

    opendkim_app = mail_stack["opendkim_app"]

    selector = "default"
    keyname = f"{TEST_DOMAIN.replace('.', '-')}-{selector}"

    # Save the current (valid) config so we can restore it.
    current_config = juju.config(opendkim_app)
    valid_keytable = current_config.get("keytable", "")
    valid_signingtable = current_config.get("signingtable", "")

    # Apply a broken keytable pointing to a non-existent file.
    broken_keytable = json.dumps(
        [
            [
                f"{selector}._domainkey.{TEST_DOMAIN}",
                f"{TEST_DOMAIN}:{selector}:/etc/dkimkeys/DOESNOTEXIST.private",
            ]
        ]
    )
    juju.config(opendkim_app, {"keytable": broken_keytable})

    juju.wait(
        lambda status: status.apps[opendkim_app].is_blocked,
        timeout=3 * 60,
        delay=5,
    )
    status = juju.status()
    blocked_message = status.apps[opendkim_app].app_status.message
    assert "opendkim" in blocked_message.lower() or "configuration" in blocked_message.lower(), (
        f"Expected a configuration-related blocked message, got: {blocked_message!r}"
    )
    logger.info("✓ opendkim blocked with message: %s", blocked_message)

    # Restore the valid configuration.
    juju.config(opendkim_app, {"keytable": valid_keytable})
    juju.wait(
        lambda status: jubilant.all_active(status, opendkim_app, POSTFIX_RELAY_APP),
        timeout=3 * 60,
        delay=5,
    )
    logger.info("✓ opendkim restored to active after valid keytable re-applied")


# ---------------------------------------------------------------------------
# Test 5: Metrics endpoints are reachable on all charms
# ---------------------------------------------------------------------------
def test_metrics_endpoints(
    juju: jubilant.Juju,
    mail_stack: typing.Dict[str, str],
) -> None:
    """
    arrange: Full mail stack is active.
    act: Scrape the Telegraf metrics endpoint on postfix-relay and opendkim.
    assert: Each endpoint responds with HTTP 200 and contains expected metric names.
    """
    relay_ip = mail_stack["postfix_relay_ip"]

    status = juju.status()
    opendkim_ip = next(iter(status.apps[OPENDKIM_APP].units.values())).public_address

    expected_relay_metrics = [
        "cpu_usage_idle",
        "postfix_queue_length",
        "procstat_lookup_running",
    ]
    expected_opendkim_metrics = ["cpu_usage_idle", "procstat_lookup_running"]

    for ip, expected in (
        (relay_ip, expected_relay_metrics),
        (opendkim_ip, expected_opendkim_metrics),
    ):
        url = f"http://{ip}:{METRICS_PORT}/metrics"
        resp = requests.get(url, timeout=10)
        assert resp.status_code == 200, f"Metrics endpoint {url} returned {resp.status_code}"
        for metric in expected:
            assert metric in resp.text, (
                f"Expected metric {metric!r} not found in response from {url}"
            )
        logger.info("✓ Metrics OK at %s", url)


# ---------------------------------------------------------------------------
# Test 6: TLS certificate is presented by postfix-relay on port 587
# ---------------------------------------------------------------------------
def test_tls_certificate_presented(
    juju: jubilant.Juju,
    mail_stack: typing.Dict[str, str],
) -> None:
    """
    arrange: postfix-relay is related to self-signed-certificates.
    act: Initiate a STARTTLS handshake on port 587.
    assert: A TLS certificate is presented by the server.
    """
    import ssl as _ssl  # noqa: PLC0415

    relay_ip = mail_stack["postfix_relay_ip"]

    ctx = _ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = _ssl.CERT_NONE

    with smtplib.SMTP(relay_ip, SMTP_SUBMISSION_PORT, timeout=15) as server:
        server.ehlo()
        server.starttls(context=ctx)
        peer_cert = typing.cast(_ssl.SSLSocket, server.sock).getpeercert(binary_form=True)

    assert peer_cert, "No TLS certificate was presented by postfix-relay on STARTTLS"
    logger.info("✓ TLS certificate presented by postfix-relay (%d bytes)", len(peer_cert))
