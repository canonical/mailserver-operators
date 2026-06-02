# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import contextlib
import imaplib
import logging
import smtplib
import ssl
import time
from email.message import EmailMessage

import jubilant
from tenacity import RetryError, retry, retry_if_result, stop_after_attempt, wait_fixed


def send_mail_via_smtp(
    host: str,
    sender: str,
    recipient: str,
    subject: str,
    body: str,
) -> None:
    """Send a plain-text e-mail through the unit's Postfix SMTP listener on port 25.

    Postfix routes delivery for MAILNAME addresses via the LMTP Unix socket
    (virtual_transport = lmtp:unix:private/dovecot-lmtp), so mail lands directly
    in the Dovecot mail store — the same store that dsync replicates to the secondary.
    """
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(body)
    with smtplib.SMTP(host, 25, timeout=30) as smtp:
        smtp.send_message(msg)


@retry(
    stop=stop_after_attempt(20),
    wait=wait_fixed(3),
    retry=retry_if_result(lambda found: not found),
)
def _check_mail_via_imap(unit_ip: str, user: str, password: str, subject: str) -> bool:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    mail = None
    try:
        mail = imaplib.IMAP4_SSL(unit_ip, port=993, ssl_context=context)
        mail.login(user, password)
        mail.select("inbox")
        _, data = mail.search(None, f'(HEADER Subject "{subject}")')
        if data and data[0]:
            logging.info(f"Email found via IMAP on {unit_ip}. IDs: {data[0]}")
            return True
        logging.info(f"Email not found yet on {unit_ip}, retrying...")
        return False
    except (imaplib.IMAP4.error, OSError) as e:
        logging.warning(f"IMAP attempt on {unit_ip} failed: {e}. Retrying...")
        return False
    finally:
        if mail is not None:
            with contextlib.suppress(imaplib.IMAP4.error, OSError):
                mail.close()
            with contextlib.suppress(imaplib.IMAP4.error, OSError):
                mail.logout()


def check_mail_via_imap(unit_ip: str, user: str, password: str, subject: str) -> bool:
    """Poll IMAP on unit_ip until the email with the given subject is found."""
    try:
        return _check_mail_via_imap(unit_ip, user, password, subject)
    except RetryError:
        return False


def setup_mail_user(
    juju: jubilant.Juju,
    primary: str,
    secondary: str | None,
    user: str,
    password: str,
):
    """Create a mail user on primary and optionally secondary unit.

    The system account and password are created on both units so PAM auth works
    on the secondary after sync.  The Maildir is only initialised on the primary
    so that dsync can replicate it to the secondary without GUID conflicts.

    Args:
        secondary: Secondary unit name, or None for single-unit deployments.
    """
    for unit in (u for u in (primary, secondary) if u is not None):
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


def get_last_sync_mtime(juju: jubilant.Juju, unit: str) -> int | None:
    """Return /srv/mail/.last-dsync mtime epoch on unit, or None if missing."""
    output = juju.exec(
        "stat -c %Y /srv/mail/.last-dsync 2>/dev/null || true", unit=unit
    ).stdout.strip()
    return int(output) if output.isdigit() else None


def get_sync_timer_run_count(juju: jubilant.Juju, unit: str) -> int:
    """Return count of sync-to-secondary service invocations from the journal."""
    output = juju.exec(
        "journalctl -u sync-to-secondary.service --no-pager -q 2>/dev/null | wc -l || true",
        unit=unit,
    ).stdout.strip()
    return int(output) if output.isdigit() else 0


def get_sync_log_content(juju: jubilant.Juju, unit: str, lines: int = 20) -> str:
    """Return last N lines from the sync-to-secondary service journal for debugging."""
    output = juju.exec(
        f"journalctl -u sync-to-secondary.service --no-pager -n {lines} 2>/dev/null || echo 'No journal entries for sync-to-secondary'",
        unit=unit,
    ).stdout
    return output


def get_timer_status(juju: jubilant.Juju, unit: str) -> str | None:
    """Return systemctl show output for the sync-to-secondary timer, or None if absent."""
    result = juju.exec(
        "systemctl show sync-to-secondary.timer --property=ActiveState,LastTriggerUSec 2>/dev/null || true",
        unit=unit,
    ).stdout.strip()
    return result if result else None


def wait_for_sync_trigger(
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
        current_mtime = get_last_sync_mtime(juju, unit)
        if current_mtime is not None and (
            previous_mtime is None or current_mtime > previous_mtime
        ):
            return current_mtime

        current_timer_count = get_sync_timer_run_count(juju, unit)
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
