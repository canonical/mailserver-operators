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
    )

    logging.info("Checking IMAPS response on port 993...")
    juju.exec(
        "curl -fsS --insecure --max-time 10 --url imaps://127.0.0.1:993 --request CAPABILITY | grep -q 'CAPABILITY'",
        unit=unit_name,
    )

    logging.info("Checking POP3 response on port 110...")
    juju.exec(
        "curl -fsS --max-time 10 --url pop3://127.0.0.1:110 --request CAPA | grep -Eq '(\\+OK|CAPA)'",
        unit=unit_name,
    )

    logging.info("Checking POP3S response on port 995...")
    juju.exec(
        "curl -fsS --insecure --max-time 10 --url pop3s://127.0.0.1:995 --request CAPA | grep -Eq '(\\+OK|CAPA)'",
        unit=unit_name,
    )


def test_clear_queue_action(juju: jubilant.Juju, dovecot_charm: str):
    """Test the clear-queue action."""
    unit_name = f"{dovecot_charm}/0"

    logging.info("Running clear-queue action (defaults)...")
    result = juju.run(unit_name, "clear-queue")
    assert result.status == "completed"
    logging.info(f"Action output: {result.results.get('output')}")

    logging.info("Running clear-queue action (all)...")
    result = juju.run(unit_name, "clear-queue", params={"queue": "all"})
    assert result.status == "completed"
    logging.info(f"Action output: {result.results.get('output')}")
