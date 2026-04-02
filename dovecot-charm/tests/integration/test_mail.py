# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import imaplib
import logging
import ssl
import time

import jubilant
import pytest


def test_mail_workflow(juju: jubilant.Juju, dovecot_charm: str):
    """Test end-to-end mail delivery and IMAP retrieval."""
    status = juju.status()
    units = status.apps[dovecot_charm].units
    if not units:
        pytest.fail("No units found")

    unit_name = list(units.keys())[0]
    logging.info(f"Using unit: {unit_name}")

    current_config = juju.config(dovecot_charm)
    if current_config.get("primary-unit") != unit_name:
        logging.info(f"Updating primary-unit config to {unit_name}...")
        juju.config(dovecot_charm, {"primary-unit": unit_name})
        juju.wait(jubilant.all_active, timeout=300)

    password = "securepassword"
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

    found = False
    last_error = None

    for i in range(20):
        try:
            mail = imaplib.IMAP4_SSL(unit_ip, port=993, ssl_context=context)
            try:
                mail.login("ubuntu", password)
                mail.select("inbox")
                typ, data = mail.search(None, f'(HEADER Subject "{subject}")')

                if data and data[0]:
                    logging.info(f"Email found successfully via IMAP! IDs: {data[0]}")
                    found = True
                    break
                else:
                    logging.info("Email not found yet...")
            finally:
                try:
                    mail.close()
                except Exception:
                    pass
                try:
                    mail.logout()
                except Exception:
                    pass

        except Exception as e:
            last_error = e
            logging.warning(f"IMAP check attempt {i + 1} failed: {e}. Retrying...")

        time.sleep(5)

    if not found:
        if last_error:
            pytest.fail(f"Failed to verify email via IMAP after retries. Last error: {last_error}")
        else:
            pytest.fail("Failed to verify email via IMAP: Email not found in inbox.")
