"""Shared helper functions for Dovecot integration tests."""

import logging
import time

import jubilant

logger = logging.getLogger(__name__)

MAIL_ROOT = "/srv/mail"


def setup_gdpr_test_user(juju: jubilant.Juju, unit_name: str, user: str, password: str) -> None:
    """Create a system user with a Dovecot mailbox containing one test message."""
    action_result = juju.run(
        unit_name, "create-mail-user", params={"username": user, "password": password}
    )
    assert action_result.status == "completed", (
        f"create-mail-user action failed for {user}: status={action_result.status}"
    )
    juju.exec(f"install -d -m 0700 -o {user} -g mail {MAIL_ROOT}/{user}", unit=unit_name)
    juju.exec(f"doveadm mailbox create -u {user} INBOX 2>/dev/null || true", unit=unit_name)
    juju.exec(
        (
            f"printf 'From: {user}@example.com\\nSubject: GDPR test\\n\\ntest body\\n' | "
            f"doveadm save -u {user} -m INBOX"
        ),
        unit=unit_name,
    )


def teardown_gdpr_test_user(juju: jubilant.Juju, unit_name: str, user: str) -> None:
    """Remove the test user and mail directory created by setup_gdpr_test_user."""
    juju.exec(f"userdel -r {user} 2>/dev/null || true", unit=unit_name)
    juju.exec(f"rm -rf {MAIL_ROOT}/{user}", unit=unit_name)


def poll(juju: jubilant.Juju, unit_name: str, cmd: str, timeout: int = 60) -> None:
    """Poll a shell command on the unit until it exits 0, or raise after timeout."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            juju.exec(cmd, unit=unit_name)
            return
        except (jubilant.CLIError, jubilant.TaskError):
            if time.monotonic() >= deadline:
                logger.error("Timed out waiting for: %s", cmd)
                log_queue_state(juju, unit_name)
                raise
            time.sleep(2)


def log_queue_state(juju: jubilant.Juju, unit_name: str) -> None:
    """Log the current Postfix queue and deferred spool state for diagnostics."""
    try:
        result = juju.exec("postqueue -p", unit=unit_name)
        logger.info("postqueue -p:\n%s", result.stdout)
    except (jubilant.CLIError, jubilant.TaskError):
        logger.exception("Failed to capture postqueue -p")
    try:
        result = juju.exec(
            "sudo find /var/spool/postfix/deferred -type f | head -20", unit=unit_name
        )
        logger.info("deferred spool files:\n%s", result.stdout or "(empty)")
    except (jubilant.CLIError, jubilant.TaskError):
        logger.exception("Failed to capture deferred spool state")
    try:
        result = juju.exec("sudo postconf relayhost header_checks", unit=unit_name)
        logger.info("postconf relayhost header_checks:\n%s", result.stdout)
    except (jubilant.CLIError, jubilant.TaskError):
        logger.exception("Failed to capture postconf state")


def seed_queue_with_test_mail(juju: jubilant.Juju, unit_name: str) -> None:
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
    poll(juju, unit_name, "postqueue -p | grep -qv 'Mail queue is empty'", timeout=60)


def cleanup_header_checks(juju: jubilant.Juju, unit_name: str) -> None:
    """Remove the HOLD header_checks rule so it does not affect subsequent runs."""
    juju.exec("sudo postconf -e 'header_checks ='", unit=unit_name)
    juju.exec("sudo postfix reload", unit=unit_name)


def seed_deferred_queue_with_test_mail(juju: jubilant.Juju, unit_name: str) -> None:
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
        poll(
            juju,
            unit_name,
            "sudo find /var/spool/postfix/deferred -type f -print -quit | grep -q .",
            timeout=60,
        )
    finally:
        juju.exec("sudo postconf -e 'relayhost =' && sudo postfix reload", unit=unit_name)


def assert_queue_empty(juju: jubilant.Juju, unit_name: str) -> None:
    """Poll until Postfix reports an empty queue."""
    poll(juju, unit_name, "postqueue -p | grep -q 'Mail queue is empty'", timeout=60)


def assert_deferred_queue_empty(juju: jubilant.Juju, unit_name: str) -> None:
    """Poll until the deferred queue contains no files."""
    poll(
        juju,
        unit_name,
        "! sudo find /var/spool/postfix/deferred -type f -print -quit | grep -q .",
        timeout=60,
    )


def assert_queue_non_empty(juju: jubilant.Juju, unit_name: str) -> None:
    """Assert that Postfix reports a non-empty queue."""
    juju.exec("postqueue -p | grep -qv 'Mail queue is empty'", unit=unit_name)
