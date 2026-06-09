# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for end-to-end mail delivery via Postfix → LMTP → Dovecot."""

import logging
from secrets import token_hex

import jubilant
import pytest

from .conftest import MAILNAME
from .helpers import check_mail_via_imap, send_mail_via_smtp, setup_mail_user


def test_mail_workflow(juju: jubilant.Juju, dovecot_charm: str):
    """Test end-to-end mail delivery via Postfix LMTP → Dovecot and IMAP retrieval.

    Mail is submitted over SMTP on port 25.  Postfix matches the recipient domain
    against virtual_mailbox_domains and forwards it to Dovecot via the LMTP Unix
    socket (virtual_transport = lmtp:unix:private/dovecot-lmtp).  Dovecot strips
    the domain from the envelope recipient (auth_username_format = %n) before the
    userdb lookup, so the system user 'ubuntu' is found for 'ubuntu@<mailname>'.
    The test then verifies the message is retrievable over IMAPS.
    """
    unit_name = f"{dovecot_charm}/0"
    logging.info(f"Updating primary-unit config to {unit_name}...")
    juju.config(dovecot_charm, {"primary-unit": unit_name})
    juju.wait(jubilant.all_active, timeout=5 * 60)

    password = token_hex(8)
    logging.info("Configuring user 'ubuntu'...")
    setup_mail_user(juju, primary=unit_name, secondary=None, user="ubuntu", password=password)

    result = juju.run(
        unit_name, "create-mail-user", params={"username": "ubuntu", "password": password}
    )
    assert result.status == "completed"
    assert result.results["status"] == "success"

    logging.info("Sending test email...")
    subject = "Mail Verification"
    cmd = f"echo 'This is the body' | mail -s '{subject}' ubuntu@localhost"
    juju.exec(cmd, unit=unit_name)

    logging.info("Verifying via IMAP...")
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
    if not check_mail_via_imap(unit_ip, "ubuntu", password, subject):
        pytest.fail("Failed to verify email delivery via IMAP.")
