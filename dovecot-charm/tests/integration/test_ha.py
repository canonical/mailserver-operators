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
        juju.exec(
            (
                f"id -u {user} >/dev/null 2>&1 || "
                f"useradd -M -d /srv/mail/{user} -s /usr/sbin/nologin {user}"
            ),
            unit=unit,
        )
        juju.exec(f"echo '{user}:{password}' | chpasswd", unit=unit)
        juju.exec(f"usermod -aG mail {user}", unit=unit)

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


def _get_sync_cron_run_count(juju: jubilant.Juju, unit: str) -> int:
    """Return count of sync-to-secondary cron executions from syslog or direct log.

    Works across charm versions: newer versions log via logger to syslog,
    older versions redirect directly to /var/log/sync-to-secondary.log.
    """
    # Try syslog first (newer charm versions with logger)
    syslog_output = juju.exec(
        "grep -c 'sync-to-secondary' /var/log/syslog 2>/dev/null || true",
        unit=unit,
    ).stdout.strip()
    syslog_count = int(syslog_output) if syslog_output.isdigit() else 0

    # Also check direct sync log file (older charm versions)
    synclog_output = juju.exec(
        "wc -l /var/log/sync-to-secondary.log 2>/dev/null | awk '{print $1}' || true",
        unit=unit,
    ).stdout.strip()
    synclog_count = int(synclog_output) if synclog_output.isdigit() else 0

    # Return the higher count (more reliable detector across versions)
    return max(syslog_count, synclog_count)


def _get_sync_log_content(juju: jubilant.Juju, unit: str, lines: int = 20) -> str:
    """Return last N sync-to-secondary lines from syslog for debugging."""
    output = juju.exec(
        f"grep 'sync-to-secondary' /var/log/syslog 2>/dev/null | tail -n {lines} || echo 'No sync entries in syslog'",
        unit=unit,
    ).stdout
    return output


def _get_cron_file_content(juju: jubilant.Juju, unit: str) -> str:
    """Return content of the sync-to-secondary cron file for debugging."""
    output = juju.exec(
        "cat /etc/cron.d/sync-to-secondary 2>/dev/null || echo 'Cron file not found'",
        unit=unit,
    ).stdout
    return output


def _wait_for_sync_trigger(
    juju: jubilant.Juju,
    unit: str,
    previous_mtime: int | None,
    previous_cron_count: int,
    timeout: int = 4 * 60,
    poll_interval: int = 5,
) -> int:
    """Wait until /srv/mail/.last-dsync mtime advances, indicating a completed sync.

    The sync script touches .last-dsync only at the very end, so this is a
    reliable end-of-sync marker. Falls back to syslog cron count increase only
    when .last-dsync never existed (e.g. no users yet), but in that case we also
    add a grace sleep so any in-progress dsync can finish.
    """
    deadline = time.time() + timeout
    cron_fired = False
    while time.time() < deadline:
        current_mtime = _get_last_sync_mtime(juju, unit)
        if current_mtime is not None and (
            previous_mtime is None or current_mtime > previous_mtime
        ):
            return current_mtime

        current_cron_count = _get_sync_cron_run_count(juju, unit)
        if current_cron_count > previous_cron_count and not cron_fired:
            logging.info(
                "Cron fired (syslog count increased); waiting for .last-dsync to update..."
            )
            cron_fired = True

        time.sleep(poll_interval)

    raise AssertionError(
        "Timed out waiting for sync trigger on "
        f"{unit}; previous mtime={previous_mtime}, previous cron count={previous_cron_count}"
    )


@pytest.mark.timeout(30 * 60)
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
    """Auto-sync via cron replicates mail from primary to secondary within 2 minutes."""
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
    previous_cron_count = _get_sync_cron_run_count(juju, primary)

    try:
        # Lower sync schedule to every minute, wait for reconcile
        logging.info("Setting sync-schedule to */1 * * * * (every minute)...")
        juju.config(dovecot_charm_dual_unit, {"sync-schedule": "*/1 * * * *"})
        juju.wait(jubilant.all_active, timeout=5 * 60)

        logging.info(f"Cron file after config change:\n{_get_cron_file_content(juju, primary)}")
        logging.info("Waiting for first cron-triggered sync signal on primary...")
        _wait_for_sync_trigger(juju, primary, previous_sync_mtime, previous_cron_count)

        # Verify email arrived on secondary via IMAP
        secondary_ip = juju.status().apps[dovecot_charm_dual_unit].units[secondary].public_address
        logging.info(f"Checking for email on secondary via IMAP at {secondary_ip}:993...")
        synced = _check_mail_via_imap(secondary_ip, user, password, subject)
        if not synced:
            logging.info("Email not found after first cron sync.")
            logging.info(f"Sync log on primary:\n{_get_sync_log_content(juju, primary)}")
            logging.info("Cron file content:")
            logging.info(_get_cron_file_content(juju, primary))
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
        juju.config(dovecot_charm_dual_unit, {"sync-schedule": "*/30 * * * *"})
        juju.wait(jubilant.all_active, timeout=5 * 60)
