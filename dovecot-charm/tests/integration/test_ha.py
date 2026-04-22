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


def _get_unit_hostname(status, app_name, unit_name):
    """Helper to get unit hostname from status."""
    try:
        machine = status.apps[app_name].units[unit_name].machine
        return status.machines[machine].hostname
    except KeyError:
        message = f"Could not determine hostname for unit {unit_name} from Juju status."
        logging.error(message)
        pytest.fail(message)


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


def _setup_mail_user(juju: jubilant.Juju, units: list[str], user: str, password: str):
    """Create a system user with a Maildir on each unit, set password on all units."""
    for unit in units:
        juju.exec(
            (
                f"id -u {user} >/dev/null 2>&1 || "
                f"useradd -M -d /srv/mail/{user} -s /usr/sbin/nologin {user}"
            ),
            unit=unit,
        )
        juju.exec(f"echo '{user}:{password}' | chpasswd", unit=unit)
        juju.exec(f"usermod -aG mail {user}", unit=unit)

    # Maildir only needs to exist on primary so doveadm backup has something to sync
    primary = units[0]
    juju.exec(
        (
            f"mkdir -p /srv/mail/{user}/Maildir/{{new,cur,tmp}} && "
            f"chown -R {user}:{user} /srv/mail/{user} && "
            f"chmod 700 /srv/mail/{user} /srv/mail/{user}/Maildir"
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
    """Return count of sync-to-secondary cron executions recorded in syslog."""
    output = juju.exec(
        "grep -c 'sync-to-secondary.sh' /var/log/syslog 2>/dev/null || true",
        unit=unit,
    ).stdout.strip()
    return int(output) if output.isdigit() else 0


def _wait_for_sync_trigger(
    juju: jubilant.Juju,
    unit: str,
    previous_mtime: int | None,
    previous_cron_count: int,
    timeout: int = 4 * 60,
    poll_interval: int = 5,
) -> int:
    """Wait for a cron-triggered sync signal and return observed marker mtime.

    Accepts either /srv/mail/.last-dsync mtime advance or syslog cron count increase
    to work across charm revisions with different script logging/exit behavior.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        current_mtime = _get_last_sync_mtime(juju, unit)
        if current_mtime is not None and (
            previous_mtime is None or current_mtime > previous_mtime
        ):
            return current_mtime

        current_cron_count = _get_sync_cron_run_count(juju, unit)
        if current_cron_count > previous_cron_count:
            return current_mtime or 0

        time.sleep(poll_interval)

    raise AssertionError(
        "Timed out waiting for sync trigger on "
        f"{unit}; previous mtime={previous_mtime}, previous cron count={previous_cron_count}"
    )


@pytest.mark.timeout(30 * 60)
def test_force_sync_action(juju: jubilant.Juju, dovecot_charm: str):
    """force-sync action replicates mail from primary to secondary via doveadm backup."""
    status = juju.status()
    if len(status.apps[dovecot_charm].units) < 2:
        logging.info("Adding the second unit...")
        juju.add_unit(dovecot_charm, num_units=1)

    def two_units_active(status):
        app = status.apps.get(dovecot_charm)
        if not app or len(app.units) < 2:
            return False
        return jubilant.all_active(status)

    logging.info("Waiting for 2 units to be active...")
    juju.wait(two_units_active, timeout=10 * 60)

    status = juju.status()
    units = sorted(status.apps[dovecot_charm].units.keys(), key=lambda x: int(x.split("/")[-1]))
    primary, secondary = units[0], units[1]
    logging.info(f"Primary: {primary}, Secondary: {secondary}")

    juju.config(dovecot_charm, {"primary-unit": primary})
    juju.wait(jubilant.all_active, timeout=5 * 60)

    # Remove legacy HA test users that can break dsync on reruns.
    for unit in (primary, secondary):
        juju.exec("rm -rf /srv/mail/syncuser* /srv/mail/autosyncuser*", unit=unit)

    # Set up test user on both units (PAM auth requires user to exist on secondary for IMAP)
    user = f"syncuser{token_hex(3)}"
    password = token_hex(8)
    for unit in (primary, secondary):
        juju.exec(f"rm -rf /srv/mail/{user}", unit=unit)
    _setup_mail_user(juju, [primary, secondary], user, password)

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
    secondary_ip = juju.status().apps[dovecot_charm].units[secondary].public_address
    logging.info(f"Checking for email on secondary via IMAP at {secondary_ip}:993...")
    assert _check_mail_via_imap(secondary_ip, user, password, subject), (
        f"Email with subject '{subject}' not found on secondary after force-sync"
    )

    # force-sync must fail on secondary
    with pytest.raises(jubilant.TaskError) as exc_info:
        juju.run(unit=secondary, action="force-sync", wait=2 * 60)
    assert cast(jubilant.TaskError, exc_info.value).task.status == "failed"
    logging.info("force-sync on secondary correctly failed.")


@pytest.mark.timeout(10 * 60)
def test_auto_sync(juju: jubilant.Juju, dovecot_charm: str):
    """Auto-sync via cron replicates mail from primary to secondary within 2 minutes."""
    status = juju.status()
    units = sorted(status.apps[dovecot_charm].units.keys(), key=lambda x: int(x.split("/")[-1]))
    assert len(units) >= 2, "Need at least 2 units; run test_force_sync_action first"
    primary, secondary = units[0], units[1]

    logging.info(f"Ensuring primary-unit is set to {primary}...")
    juju.config(dovecot_charm, {"primary-unit": primary})
    juju.wait(jubilant.all_active, timeout=5 * 60)

    # Remove legacy HA test users that can break dsync on reruns.
    for unit in (primary, secondary):
        juju.exec("rm -rf /srv/mail/syncuser* /srv/mail/autosyncuser*", unit=unit)

    # Set up a fresh test user
    user = f"autosyncuser{token_hex(3)}"
    password = token_hex(8)
    for unit in (primary, secondary):
        juju.exec(f"rm -rf /srv/mail/{user}", unit=unit)
    _setup_mail_user(juju, [primary, secondary], user, password)

    # Send email on primary
    subject = f"Auto Sync Test {token_hex(4)}"
    logging.info(f"Sending test email on primary with subject: {subject}")
    juju.exec(f"echo 'test body' | mail -s '{subject}' {user}@localhost", unit=primary)

    previous_sync_mtime = _get_last_sync_mtime(juju, primary)
    previous_cron_count = _get_sync_cron_run_count(juju, primary)

    try:
        # Lower sync schedule to every minute, wait for reconcile
        logging.info("Setting sync-schedule to */1 * * * * (every minute)...")
        juju.config(dovecot_charm, {"sync-schedule": "*/1 * * * *"})
        juju.wait(jubilant.all_active, timeout=5 * 60)

        logging.info("Waiting for first cron-triggered sync signal on primary...")
        _wait_for_sync_trigger(juju, primary, previous_sync_mtime, previous_cron_count)

        # Verify email arrived on secondary via IMAP
        secondary_ip = juju.status().apps[dovecot_charm].units[secondary].public_address
        logging.info(f"Checking for email on secondary via IMAP at {secondary_ip}:993...")
        synced = _check_mail_via_imap(secondary_ip, user, password, subject)
        if not synced:
            logging.info("Email not found after first cron sync; waiting for one more cron run...")
            current_mtime = _get_last_sync_mtime(juju, primary)
            current_cron_count = _get_sync_cron_run_count(juju, primary)
            _wait_for_sync_trigger(
                juju,
                primary,
                current_mtime,
                current_cron_count,
                timeout=2 * 60,
            )
            synced = _check_mail_via_imap(secondary_ip, user, password, subject)

        assert synced, f"Email with subject '{subject}' not found on secondary after auto-sync"
    finally:
        # Reset sync-schedule to default
        logging.info("Resetting sync-schedule to default...")
        juju.config(dovecot_charm, {"sync-schedule": "*/30 * * * *"})
        juju.wait(jubilant.all_active, timeout=5 * 60)
