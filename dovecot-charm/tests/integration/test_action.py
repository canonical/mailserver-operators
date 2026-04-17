# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import time

import jubilant


def _seed_queue_with_test_mail(juju: jubilant.Juju, unit_name: str):
    """Queue a test message and wait until Postfix reports a non-empty queue."""
    juju.exec(
        'sudo postconf -e "header_checks = regexp:/etc/postfix/header_checks"',
        unit=unit_name,
    )
    juju.exec(
        'echo "/^Subject:.*queue.*/  HOLD" | sudo tee /etc/postfix/header_checks',
        unit=unit_name,
    )
    juju.exec(
        "sudo postmap /etc/postfix/header_checks && sudo postfix reload",
        unit=unit_name,
    )

    juju.exec(
        "printf 'Subject: queue-test\\n\\nmessage body\\n' | "
        "/usr/sbin/sendmail -f test@yourdomain.com someone@example.com || true",
        unit=unit_name,
    )
    time.sleep(10)
    juju.exec(
        "for i in $(seq 1 30); do "
        "postqueue -p | grep -qv 'Mail queue is empty' && exit 0; "
        "sleep 1; "
        "done; "
        "exit 1",
        unit=unit_name,
    )


def _seed_deferred_queue_with_test_mail(juju: jubilant.Juju, unit_name: str):
    """Queue one deferred message by temporarily deferring SMTP transports."""
    juju.exec("postconf -e 'relayhost = [10.255.255.255]' && postfix reload", unit=unit_name)
    time.sleep(5)  # Give Postfix some time to process the new message
    try:
        juju.exec(
            "printf 'Subject: deferred-test\\n\\nmessage body\\n' | "
            "/usr/sbin/sendmail -f deferred-test@example.com deferred-test@example.net || true",
            unit=unit_name,
        )
        time.sleep(10)  # Give Postfix some time to process the new message
        juju.exec(
            "for i in $(seq 1 30); do "
            "sudo find /var/spool/postfix/deferred -type f | grep -q . && exit 0; "
            "sleep 1; "
            "done; "
            "exit 1",
            unit=unit_name,
        )
    finally:
        juju.exec("sudo postconf -e 'relayhost =' && postfix reload", unit=unit_name)


def _assert_queue_empty(juju: jubilant.Juju, unit_name: str):
    """Assert that Postfix reports an empty queue."""
    juju.exec("postqueue -p | grep -q 'Mail queue is empty'", unit=unit_name)


def _assert_deferred_queue_empty(juju: jubilant.Juju, unit_name: str):
    """Assert that the deferred queue has no queued files."""
    juju.exec(
        "sudo find /var/spool/postfix/deferred -type f | grep -q . && exit 1 || exit 0",
        unit=unit_name,
    )


def _assert_queue_non_empty(juju: jubilant.Juju, unit_name: str):
    """Assert that Postfix reports a non-empty queue."""
    juju.exec("postqueue -p | grep -qv 'Mail queue is empty'", unit=unit_name)


def test_clear_queue_action(juju: jubilant.Juju, dovecot_charm: str):
    """Test the clear-queue action."""
    unit_name = f"{dovecot_charm}/0"

    logging.info("Seeding one queued message before default clear-queue action...")
    _seed_queue_with_test_mail(juju, unit_name)
    logging.info("Seeding one deferred message before default clear-queue action...")
    _seed_deferred_queue_with_test_mail(juju, unit_name)

    logging.info("Running clear-queue action (defaults)...")
    time.sleep(5)
    result = juju.run(unit_name, "clear-queue")
    assert result.status == "completed"
    logging.info(f"Action output: {result.results.get('output')}")
    time.sleep(5)
    _assert_deferred_queue_empty(juju, unit_name)
    _assert_queue_non_empty(juju, unit_name)

    logging.info("Running clear-queue action (all)...")
    result = juju.run(unit_name, "clear-queue", params={"queue": "all"})
    assert result.status == "completed"
    logging.info(f"Action output: {result.results.get('output')}")
    time.sleep(15)
    _assert_queue_empty(juju, unit_name)
