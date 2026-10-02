# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from secrets import token_hex

import jubilant

from .helpers import configure_mail_user, reset_mail_users


def test_dovecot_protocol_responses(juju: jubilant.Juju, dovecot_charm: str):
    """Verify Dovecot responds to simple IMAP and POP3 commands."""
    unit_name = f"{dovecot_charm}/0"

    logging.info("Checking IMAPS response on port 993...")
    juju.exec(
        "curl -fsS --insecure --max-time 10 --url imaps://127.0.0.1:993 --request CAPABILITY | grep -q 'CAPABILITY'",
        unit=unit_name,
    )

    logging.info("Checking POP3S response on port 995...")
    juju.exec(
        "curl -fsS --insecure --max-time 10 --url pop3s://127.0.0.1:995 --request CAPA | grep -Eq '(\\+OK|CAPA)'",
        unit=unit_name,
    )


def test_primary_unit_validation(juju: jubilant.Juju, dovecot_charm: str):
    """Verify that the charm rejects configuration with a non-existent primary unit."""
    unit_name = f"{dovecot_charm}/0"

    logging.info("Setting invalid primary unit in config...")
    juju.config(dovecot_charm, {"primary-unit": "nonexistent-unit"})

    logging.info("Checking for error status due to invalid primary unit...")
    juju.wait(
        lambda status: jubilant.all_blocked(status, dovecot_charm),
        timeout=5 * 60,
    )
    assert (
        juju.status().apps[dovecot_charm].units[unit_name].workload_status.message
        == "Invalid charm configuration, check logs for details: primary_unit"
    )

    juju.config(dovecot_charm, {"primary-unit": unit_name})
    juju.wait(
        lambda status: jubilant.all_active(status, dovecot_charm),
        timeout=5 * 60,
    )


def test_mail_users_secret_rotation_updates_authentication(
    juju: jubilant.Juju, dovecot_charm: str
):
    """Verify that only users in the current mail-users secret can authenticate."""
    unit_name = f"{dovecot_charm}/0"
    first_user = f"secret-user-{token_hex(4)}"
    first_password = token_hex(16)
    rotated_user = f"rotated-user-{token_hex(4)}"
    rotated_password = token_hex(16)
    unknown_user = f"unknown-user-{token_hex(4)}"

    try:
        configure_mail_user(juju, unit_name, first_user, first_password)
        juju.wait(
            lambda status: jubilant.all_active(status, dovecot_charm),
            timeout=5 * 60,
        )
        juju.exec(
            f"doveadm auth test {first_user} '{first_password}'",
            unit=unit_name,
        )
        juju.exec(
            f"! doveadm auth test {unknown_user} invalid-password >/dev/null 2>&1",
            unit=unit_name,
        )

        configure_mail_user(juju, unit_name, rotated_user, rotated_password)
        juju.wait(
            lambda status: jubilant.all_active(status, dovecot_charm),
            timeout=5 * 60,
        )
        juju.exec(
            f"doveadm auth test {rotated_user} '{rotated_password}'",
            unit=unit_name,
        )
        juju.exec(
            f"! doveadm auth test {first_user} '{first_password}' >/dev/null 2>&1",
            unit=unit_name,
        )
        juju.exec(
            f"! doveadm auth test {unknown_user} invalid-password >/dev/null 2>&1",
            unit=unit_name,
        )
    finally:
        reset_mail_users(juju, unit_name)
