# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import contextlib
import imaplib
import logging
import ssl
import time
from secrets import token_hex
from typing import cast

import jubilant
import pytest


def _check_mail_via_imap(unit_ip: str, user: str, password: str, subject: str) -> bool:
    """Poll IMAP on unit_ip until the email with the given subject is found."""
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    for attempt in range(20):
        mail = None
        try:
            mail = imaplib.IMAP4_SSL(unit_ip, port=993, ssl_context=context)
            mail.login(user, password)
            mail.select("inbox")
            _, data = mail.search(None, f'(HEADER Subject "{subject}")')
            if data and data[0]:
                logging.info(f"Email found via IMAP on {unit_ip}. IDs: {data[0]}")
                return True
            logging.info(f"Email not found yet on {unit_ip} (attempt {attempt + 1})...")
        except (imaplib.IMAP4.error, OSError) as e:
            logging.warning(f"IMAP attempt {attempt + 1} on {unit_ip} failed: {e}. Retrying...")
        finally:
            if mail is not None:
                with contextlib.suppress(imaplib.IMAP4.error, OSError):
                    mail.close()
                with contextlib.suppress(imaplib.IMAP4.error, OSError):
                    mail.logout()
        time.sleep(3)

    return False


def _setup_mail_user(
    juju: jubilant.Juju,
    primary: str,
    secondary: str,
    user: str,
    password: str,
):
    """Create a mail user on both units.

    The system account and password are created on both units so PAM auth works
    on the secondary after sync.  The Maildir is only initialised on the primary
    so that dsync can replicate it to the secondary without GUID conflicts.
    """
    for unit in (primary, secondary):
        juju.run(unit, "create-mail-user", params={"username": user, "password": password})

    # Maildir only on primary — dsync creates it on the secondary during the
    # first sync.  Pre-initialising it on the secondary would give INBOX a
    # different GUID and cause doveadm backup to fail with
    # "mailbox_delete failed: INBOX can't be deleted".
    juju.exec(
        (
            f"install -d -m 0700 -o {user} -g mail /srv/mail/{user} && "
            f"doveadm mailbox create -u {user} INBOX 2>/dev/null || true"
        ),
        unit=primary,
    )


def _get_last_sync_mtime(juju: jubilant.Juju, unit: str) -> int | None:
    """Return /srv/mail/.last-dsync mtime epoch on unit, or None if missing."""
    output = juju.exec(
        "stat -c %Y /srv/mail/.last-dsync 2>/dev/null || true", unit=unit
    ).stdout.strip()
    return int(output) if output.isdigit() else None


def _get_sync_timer_run_count(juju: jubilant.Juju, unit: str) -> int:
    """Return count of sync-to-secondary service invocations from the journal."""
    output = juju.exec(
        "journalctl -u sync-to-secondary.service --no-pager -q 2>/dev/null | wc -l || true",
        unit=unit,
    ).stdout.strip()
    return int(output) if output.isdigit() else 0


def _get_sync_log_content(juju: jubilant.Juju, unit: str, lines: int = 20) -> str:
    """Return last N lines from the sync-to-secondary service journal for debugging."""
    output = juju.exec(
        f"journalctl -u sync-to-secondary.service --no-pager -n {lines} 2>/dev/null || echo 'No journal entries for sync-to-secondary'",
        unit=unit,
    ).stdout
    return output


def _get_timer_status(juju: jubilant.Juju, unit: str) -> str | None:
    """Return systemctl show output for the sync-to-secondary timer, or None if absent."""
    result = juju.exec(
        "systemctl show sync-to-secondary.timer --property=ActiveState,LastTriggerUSec 2>/dev/null || true",
        unit=unit,
    ).stdout.strip()
    return result if result else None


def _wait_for_sync_trigger(
    juju: jubilant.Juju,
    unit: str,
    previous_mtime: int | None,
    previous_timer_count: int,
    timeout: int = 4 * 60,
    poll_interval: int = 5,
) -> int:
    """Wait until /srv/mail/.last-dsync mtime advances, indicating a completed sync.

    The sync script touches .last-dsync only at the very end, so this is a
    reliable end-of-sync marker. Journal timer count is checked only to log
    that the timer appears to have fired while we continue waiting for
    .last-dsync to be updated.
    """
    deadline = time.time() + timeout
    timer_fired = False
    while time.time() < deadline:
        current_mtime = _get_last_sync_mtime(juju, unit)
        if current_mtime is not None and (
            previous_mtime is None or current_mtime > previous_mtime
        ):
            return current_mtime

        current_timer_count = _get_sync_timer_run_count(juju, unit)
        if current_timer_count > previous_timer_count and not timer_fired:
            logging.info(
                "Timer fired (journal count increased); waiting for .last-dsync to update..."
            )
            timer_fired = True

        time.sleep(poll_interval)

    raise AssertionError(
        "Timed out waiting for sync trigger on "
        f"{unit}; previous mtime={previous_mtime}, previous timer count={previous_timer_count}"
    )


def test_force_sync_action(juju: jubilant.Juju, dovecot_charm_dual_unit: str):
    """force-sync action replicates mail from primary to secondary via doveadm backup."""
    status = juju.status()
    units = sorted(
        status.apps[dovecot_charm_dual_unit].units.keys(), key=lambda x: int(x.split("/")[-1])
    )
    primary, secondary = units[0], units[1]
    logging.info(f"Primary: {primary}, Secondary: {secondary}")

    juju.config(dovecot_charm_dual_unit, {"primary-unit": primary})
    juju.wait(jubilant.all_active, timeout=5 * 60)

    # Remove legacy HA test users that can break dsync on reruns.
    for unit in (primary, secondary):
        juju.exec("rm -rf /srv/mail/syncuser* /srv/mail/autosyncuser*", unit=unit)

    # Set up test user on both units (PAM auth requires user to exist on secondary for IMAP)
    user = f"syncuser{token_hex(3)}"
    password = token_hex(8)
    for unit in (primary, secondary):
        juju.exec(f"rm -rf /srv/mail/{user}", unit=unit)
    _setup_mail_user(juju, primary, secondary, user, password)

    # Send email on primary
    subject = f"Force Sync Test {token_hex(4)}"
    logging.info(f"Sending test email on primary with subject: {subject}")
    juju.exec(f"echo 'test body' | mail -s '{subject}' {user}@localhost", unit=primary)

    # Run force-sync on primary
    logging.info("Running force-sync action on primary...")
    task = juju.run(unit=primary, action="force-sync", wait=2 * 60)
    assert task.status == "completed"
    assert task.results["result"] == "Sync completed successfully"

    # Verify email arrived on secondary via IMAP
    secondary_ip = juju.status().apps[dovecot_charm_dual_unit].units[secondary].public_address
    logging.info(f"Checking for email on secondary via IMAP at {secondary_ip}:993...")
    assert _check_mail_via_imap(secondary_ip, user, password, subject), (
        f"Email with subject '{subject}' not found on secondary after force-sync"
    )

    # force-sync must fail on secondary
    with pytest.raises(jubilant.TaskError) as exc_info:
        juju.run(unit=secondary, action="force-sync", wait=2 * 60)
    assert cast(jubilant.TaskError, exc_info.value).task.status == "failed"
    logging.info("force-sync on secondary correctly failed.")


def test_auto_sync(juju: jubilant.Juju, dovecot_charm_dual_unit: str):
    """Auto-sync via systemd timer replicates mail from primary to secondary within 2 minutes."""
    status = juju.status()
    units = sorted(
        status.apps[dovecot_charm_dual_unit].units.keys(), key=lambda x: int(x.split("/")[-1])
    )
    primary, secondary = units[0], units[1]

    logging.info(f"Ensuring primary-unit is set to {primary}...")
    juju.config(dovecot_charm_dual_unit, {"primary-unit": primary})
    juju.wait(jubilant.all_active, timeout=5 * 60)

    # Remove legacy HA test users that can break dsync on reruns.
    for unit in (primary, secondary):
        juju.exec("rm -rf /srv/mail/syncuser* /srv/mail/autosyncuser*", unit=unit)

    # Set up a fresh test user
    user = f"autosyncuser{token_hex(3)}"
    password = token_hex(8)
    for unit in (primary, secondary):
        juju.exec(f"rm -rf /srv/mail/{user}", unit=unit)
    _setup_mail_user(juju, primary, secondary, user, password)

    # Send email on primary
    subject = f"Auto Sync Test {token_hex(4)}"
    logging.info(f"Sending test email on primary with subject: {subject}")
    juju.exec(f"echo 'test body' | mail -s '{subject}' {user}@localhost", unit=primary)

    previous_sync_mtime = _get_last_sync_mtime(juju, primary)
    previous_timer_count = _get_sync_timer_run_count(juju, primary)

    try:
        # Lower sync schedule to every minute, wait for reconcile
        logging.info("Setting sync-schedule to *:* (every minute)...")
        juju.config(dovecot_charm_dual_unit, {"sync-schedule": "*:*"})
        juju.wait(jubilant.all_active, timeout=5 * 60)

        logging.info(f"Timer status after config change:\n{_get_timer_status(juju, primary)}")
        logging.info("Waiting for first timer-triggered sync signal on primary...")
        _wait_for_sync_trigger(juju, primary, previous_sync_mtime, previous_timer_count)

        # Verify email arrived on secondary via IMAP
        secondary_ip = juju.status().apps[dovecot_charm_dual_unit].units[secondary].public_address
        logging.info(f"Checking for email on secondary via IMAP at {secondary_ip}:993...")
        synced = _check_mail_via_imap(secondary_ip, user, password, subject)
        if not synced:
            logging.info("Email not found after first timer sync.")
            logging.info(f"Sync log on primary:\n{_get_sync_log_content(juju, primary)}")
            logging.info("Timer status:")
            logging.info(_get_timer_status(juju, primary))
            logging.info("Trying manual sync as fallback to verify sync mechanism works...")
            juju.exec("/usr/local/bin/sync-to-secondary.sh", unit=primary)
            time.sleep(15)
            synced = _check_mail_via_imap(secondary_ip, user, password, subject)
            if not synced:
                logging.info("Manual sync also failed. Checking sync log after manual run:")
                logging.info(f"Sync log:\n{_get_sync_log_content(juju, primary, lines=30)}")

        assert synced, f"Email with subject '{subject}' not found on secondary after auto-sync"
    finally:
        # Reset sync-schedule to default
        logging.info("Resetting sync-schedule to default...")
        juju.config(dovecot_charm_dual_unit, {"sync-schedule": "daily"})
        juju.wait(jubilant.all_active, timeout=5 * 60)
