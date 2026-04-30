# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import time

import jubilant

logger = logging.getLogger(__name__)


def _log_queue_state(juju: jubilant.Juju, unit_name: str) -> None:
    """Log the current Postfix queue and deferred spool state for diagnostics."""
    try:
        result = juju.exec("postqueue -p", unit=unit_name)
        logger.info("postqueue -p:\n%s", result.stdout)
    except Exception:
        logger.exception("Failed to capture postqueue -p")
    try:
        result = juju.exec(
            "sudo find /var/spool/postfix/deferred -type f | head -20", unit=unit_name
        )
        logger.info("deferred spool files:\n%s", result.stdout or "(empty)")
    except Exception:
        logger.exception("Failed to capture deferred spool state")
    try:
        result = juju.exec("sudo postconf relayhost header_checks", unit=unit_name)
        logger.info("postconf relayhost header_checks:\n%s", result.stdout)
    except Exception:
        logger.exception("Failed to capture postconf state")


def _poll(juju: jubilant.Juju, unit_name: str, cmd: str, timeout: int = 60) -> None:
    """Poll a shell command on the unit until it exits 0, or raise after timeout."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            juju.exec(cmd, unit=unit_name)
            return
        except (jubilant.CLIError, jubilant.TaskError):
            if time.monotonic() >= deadline:
                logger.error("Timed out waiting for: %s", cmd)
                _log_queue_state(juju, unit_name)
                raise
            time.sleep(2)


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
    _poll(juju, unit_name, "postqueue -p | grep -qv 'Mail queue is empty'", timeout=60)


def _cleanup_header_checks(juju: jubilant.Juju, unit_name: str):
    """Remove the HOLD header_checks rule so it does not affect subsequent runs."""
    juju.exec("sudo postconf -e 'header_checks ='", unit=unit_name)
    juju.exec("sudo postfix reload", unit=unit_name)


def _seed_deferred_queue_with_test_mail(juju: jubilant.Juju, unit_name: str):
    """Queue one deferred message by temporarily deferring SMTP transports."""
    juju.exec(
        "sudo postconf -e 'relayhost = [10.255.255.255]' && sudo postfix reload", unit=unit_name
    )
    try:
        juju.exec(
            "printf 'Subject: deferred-test\\n\\nmessage body\\n' | "
            "/usr/sbin/sendmail -f deferred-test@example.com deferred-test@example.net || true",
            unit=unit_name,
        )
        _poll(
            juju,
            unit_name,
            "sudo find /var/spool/postfix/deferred -type f -print -quit | grep -q .",
            timeout=60,
        )
    finally:
        juju.exec("sudo postconf -e 'relayhost =' && sudo postfix reload", unit=unit_name)


def _assert_queue_empty(juju: jubilant.Juju, unit_name: str):
    """Poll until Postfix reports an empty queue."""
    _poll(juju, unit_name, "postqueue -p | grep -q 'Mail queue is empty'", timeout=60)


def _assert_deferred_queue_empty(juju: jubilant.Juju, unit_name: str):
    """Poll until the deferred queue contains no files."""
    _poll(
        juju,
        unit_name,
        "! sudo find /var/spool/postfix/deferred -type f -print -quit | grep -q .",
        timeout=60,
    )


def _assert_queue_non_empty(juju: jubilant.Juju, unit_name: str):
    """Assert that Postfix reports a non-empty queue."""
    juju.exec("postqueue -p | grep -qv 'Mail queue is empty'", unit=unit_name)


def test_clear_queue_action(juju: jubilant.Juju, dovecot_charm: str):
    """Test the clear-queue action."""
    unit_name = f"{dovecot_charm}/0"

    try:
        logger.info("Seeding one queued message before default clear-queue action...")
        _seed_queue_with_test_mail(juju, unit_name)
        logger.info("Seeding one deferred message before default clear-queue action...")
        _seed_deferred_queue_with_test_mail(juju, unit_name)

        logger.info("Running clear-queue action (defaults)...")
        result = juju.run(unit_name, "clear-queue")
        assert result.status == "completed"
        logger.info("clear-queue (defaults) output: %s", result.results.get("output"))
        _assert_deferred_queue_empty(juju, unit_name)
        _assert_queue_non_empty(juju, unit_name)

        logger.info("Running clear-queue action (all)...")
        result = juju.run(unit_name, "clear-queue", params={"queue": "all"})
        assert result.status == "completed"
        logger.info("clear-queue (all) output: %s", result.results.get("output"))
        _assert_queue_empty(juju, unit_name)
    finally:
        _cleanup_header_checks(juju, unit_name)
