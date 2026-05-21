# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for end-to-end mail delivery via Postfix → LMTP → Dovecot."""

import contextlib
import imaplib
import logging
import ssl
import time
from secrets import token_hex

import jubilant
import pytest

from .conftest import MAILNAME
from .helpers import send_mail_via_smtp


def test_mail_workflow(juju: jubilant.Juju, dovecot_charm: str):
    """Test end-to-end mail delivery via Postfix LMTP → Dovecot and IMAP retrieval.

    Mail is submitted over SMTP on port 25.  Postfix matches the recipient domain
    against virtual_mailbox_domains and forwards it to Dovecot via the LMTP Unix
    socket (virtual_transport = lmtp:unix:private/dovecot-lmtp).  The test then
    verifies the message is retrievable over IMAPS.
    """
    unit_name = f"{dovecot_charm}/0"
    logging.info(f"Updating primary-unit config to {unit_name}...")
    juju.config(dovecot_charm, {"primary-unit": unit_name})
    juju.wait(jubilant.all_active, timeout=5 * 60)

    password = token_hex(8)
    logging.info("Configuring user 'ubuntu'...")
    juju.exec("usermod -aG mail ubuntu", unit=unit_name)
    juju.exec(f"echo 'ubuntu:{password}' | chpasswd", unit=unit_name)
    # Ensure the Dovecot mail directory exists so the LMTP delivery can write
    # immediately without waiting for Dovecot to auto-create it.
    juju.exec(
        "install -d -m 0700 -o ubuntu -g mail /srv/mail/ubuntu",
        unit=unit_name,
    )

    # Resolve the unit IP before sending so we can reuse it for the IMAP check.
    status = juju.status()
    unit_ip = status.apps[dovecot_charm].units[unit_name].public_address

    subject = "Mail Verification"
    logging.info(f"Sending test email via SMTP to {unit_ip}:25 ...")
    send_mail_via_smtp(
        host=unit_ip,
        sender=f"test@{MAILNAME}",
        recipient=f"ubuntu@{MAILNAME}",
        subject=subject,
        body="This is the body",
    )

    logging.info(f"Verifying via IMAP at {unit_ip}:993 ...")
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    email_found = False
    for i in range(20):
        mail = None
        try:
            mail = imaplib.IMAP4_SSL(unit_ip, port=993, ssl_context=context)
            mail.login("ubuntu", password)
            mail.select("inbox")
            _, data = mail.search(None, f'(HEADER Subject "{subject}")')

            if data and data[0]:
                logging.info(f"Email found successfully via IMAP! IDs: {data[0]}")
                email_found = True
                break
            else:
                logging.info("Email not found yet...")
        except (imaplib.IMAP4.error, OSError) as e:
            logging.warning(f"IMAP check attempt {i + 1} failed: {e}. Retrying...")
        finally:
            if mail is not None:
                with contextlib.suppress(imaplib.IMAP4.error, OSError):
                    mail.close()
                with contextlib.suppress(imaplib.IMAP4.error, OSError):
                    mail.logout()

        time.sleep(3)

    if not email_found:
        pytest.fail("Failed to verify email delivery via IMAP.")
