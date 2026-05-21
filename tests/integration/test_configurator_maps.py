# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for postfix-relay-configurator sender_login_maps enforcement.

These tests deploy only postfix-relay + postfix-relay-configurator (no Dovecot
or OpenDKIM required) to verify that the configurator correctly writes
sender_login maps and that postfix enforces them.
"""

import logging
import smtplib
import ssl
import typing

import pytest

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Test-specific constants
# ---------------------------------------------------------------------------
TEST_DOMAIN = "mailstack.internal"
SMTP_PORT = 587

AUTH_USER = "testuser"
AUTH_PASSWORD = "test-password"
AUTHORIZED_SENDER = f"authorized@{TEST_DOMAIN}"
SPOOFED_SENDER = f"spoofed@{TEST_DOMAIN}"
RECIPIENT = f"recipient@{TEST_DOMAIN}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestSenderLoginMapEnforcement:
    """Verify that sender_login_maps written by the configurator are enforced by postfix."""

    def test_sender_login_map_enforcement(self, postfix_stack: typing.Dict[str, str]) -> None:
        """Authenticated user can send from authorized address."""
        relay_ip = postfix_stack["postfix_relay_ip"]

        # --- Success case: send from authorized address ---
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        with smtplib.SMTP(relay_ip, SMTP_PORT, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ctx)
            smtp.ehlo()
            smtp.login(AUTH_USER, AUTH_PASSWORD)
            smtp.sendmail(
                from_addr=AUTHORIZED_SENDER,
                to_addrs=[RECIPIENT],
                msg=(
                    f"From: {AUTHORIZED_SENDER}\r\n"
                    f"To: {RECIPIENT}\r\n"
                    "Subject: test authorized sender\r\n"
                    "\r\n"
                    "This message should be accepted.\r\n"
                ),
            )
            logger.info("Success case: message from %s accepted", AUTHORIZED_SENDER)

    def test_sender_login_map_enforcement_failure(self, postfix_stack: typing.Dict[str, str]) -> None:
        """Spoofed user cannot send from an unauthorized address."""
        relay_ip = postfix_stack["postfix_relay_ip"]

        # --- Success case: send from authorized address ---
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        # --- Failure case: send from spoofed address ---
        with smtplib.SMTP(relay_ip, SMTP_PORT, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ctx)
            smtp.ehlo()
            smtp.login(AUTH_USER, AUTH_PASSWORD)
            with pytest.raises(smtplib.SMTPRecipientsRefused) as exc_info:
                smtp.sendmail(
                    from_addr=SPOOFED_SENDER,
                    to_addrs=[RECIPIENT],
                    msg=(
                        f"From: {SPOOFED_SENDER}\r\n"
                        f"To: {RECIPIENT}\r\n"
                        "Subject: test spoofed sender\r\n"
                        "\r\n"
                        "This message should be rejected.\r\n"
                    ),
                )
            # Postfix defers sender restriction checks to RCPT TO (smtpd_delay_reject=yes),
            # so the 553 "Sender address rejected" comes back as SMTPRecipientsRefused.
            recipients_errors = exc_info.value.recipients
            assert RECIPIENT in recipients_errors, (
                f"Expected rejection for {RECIPIENT}, got: {recipients_errors}"
            )
            smtp_code, smtp_error = recipients_errors[RECIPIENT]
            logger.info(
                "Failure case: message from %s rejected with code %s",
                SPOOFED_SENDER,
                smtp_code,
            )
            assert smtp_code == 553, (
                f"Expected 553 Sender address rejected, got {smtp_code}: {smtp_error}"
            )
