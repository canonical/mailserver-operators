# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import jubilant


def test_dovecot_protocol_responses(juju: jubilant.Juju, dovecot_charm: str):
    """Verify Dovecot responds to simple IMAP and POP3 commands."""
    unit_name = f"{dovecot_charm}/0"

    logging.info("Checking IMAP response on port 143...")
    juju.exec(
        "curl -fsS --max-time 10 --url imap://127.0.0.1:143 --request CAPABILITY | grep -q 'CAPABILITY'",
        unit=unit_name,
        log=False,
    )

    logging.info("Checking IMAPS response on port 993...")
    juju.exec(
        "curl -fsS --insecure --max-time 10 --url imaps://127.0.0.1:993 --request CAPABILITY | grep -q 'CAPABILITY'",
        unit=unit_name,
        log=False,
    )

    logging.info("Checking POP3 response on port 110...")
    juju.exec(
        "curl -fsS --max-time 10 --url pop3://127.0.0.1:110 --request CAPA | grep -Eq '(\\+OK|CAPA)'",
        unit=unit_name,
        log=False,
    )

    logging.info("Checking POP3S response on port 995...")
    juju.exec(
        "curl -fsS --insecure --max-time 10 --url pop3s://127.0.0.1:995 --request CAPA | grep -Eq '(\\+OK|CAPA)'",
        unit=unit_name,
        log=False,
    )


def test_primary_unit_validation(juju: jubilant.Juju, dovecot_charm: str):
    """Verify that the charm rejects configuration with a non-existent primary unit."""
    unit_name = f"{dovecot_charm}/0"

    logging.info("Setting invalid primary unit in config...")
    juju.config(dovecot_charm, {"primary-unit": "nonexistent-unit"}, log=False)

    logging.info("Checking for error status due to invalid primary unit...")
    juju.wait(
        lambda status: jubilant.all_blocked(status, dovecot_charm),
        timeout=5 * 60,
    )
    assert (
        juju.status().apps[dovecot_charm].units[unit_name].workload_status.message
        == "Invalid charm configuration, check logs for details: primary_unit"
    )

    juju.config(dovecot_charm, {"primary-unit": unit_name}, log=False)
    juju.wait(
        lambda status: jubilant.all_active(status, dovecot_charm),
        timeout=5 * 60,
    )
