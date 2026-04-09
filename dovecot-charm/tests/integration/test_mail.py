# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import contextlib
import imaplib
import logging
import ssl
import time
from secrets import token_hex

import jubilant
import pytest


def test_mail_workflow(juju: jubilant.Juju, dovecot_charm: str):
    """Test end-to-end mail delivery and IMAP retrieval."""
    unit_name = f"{dovecot_charm}/0"
    logging.info(f"Updating primary-unit config to {unit_name}...")
    juju.config(dovecot_charm, {"primary-unit": unit_name})
    juju.wait(jubilant.all_active, timeout=300)

    password = token_hex(8)
    logging.info("Configuring user 'ubuntu'...")

    juju.exec("usermod -aG mail ubuntu", unit=unit_name)
    juju.exec(f"echo 'ubuntu:{password}' | chpasswd", unit=unit_name)

    logging.info("Sending test email...")
    subject = "Mail Verification"
    cmd = f"echo 'This is the body' | mail -s '{subject}' ubuntu@localhost"
    juju.exec(cmd, unit=unit_name)

    logging.info("Verifying via IMAP...")
    status = juju.status()
    unit_ip = status.apps[dovecot_charm].units[unit_name].public_address

    logging.info(f"Connecting to IMAP at {unit_ip}:993")

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
                break  # Test passed
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
        pytest.fail("Failed to verify email via IMAP.")
