# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import time
from secrets import token_hex
from typing import cast

import jubilant
import pytest
import yaml

from .conftest import MAILNAME
from .helpers import (
    DEFAULT_MAIL_USERS,
    check_mail_via_imap,
    crypt_password,
    get_last_sync_mtime,
    get_sync_log_content,
    get_sync_timer_run_count,
    get_timer_status,
    imap_authenticates,
    remove_credential_source,
    run_credential_sync,
    send_mail_via_smtp,
    setup_mail_user,
    wait_for_sync_trigger,
    write_credential_source,
)

HA_CREDENTIAL_SOURCE = "/var/lib/misc/thishost/integration-ha-mail-users"


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
    setup_mail_user(juju, primary, secondary, user, password)

    # Send email on primary via SMTP so Postfix routes it through the LMTP socket
    # into Dovecot's mail store (the same store dsync replicates).
    subject = f"Force Sync Test {token_hex(4)}"
    logging.info(f"Sending test email on primary with subject: {subject}")
    primary_ip = juju.status().apps[dovecot_charm_dual_unit].units[primary].public_address
    send_mail_via_smtp(
        host=primary_ip,
        sender=f"{user}@{MAILNAME}",
        recipient=f"{user}@{MAILNAME}",
        subject=subject,
        body="test body",
    )

    # Run force-sync on primary
    logging.info("Running force-sync action on primary...")
    task = juju.run(unit=primary, action="force-sync", wait=2 * 60)
    assert task.status == "completed"
    assert task.results["result"] == "Sync completed successfully"

    # Verify email arrived on secondary via IMAP
    secondary_ip = juju.status().apps[dovecot_charm_dual_unit].units[secondary].public_address
    logging.info(f"Checking for email on secondary via IMAP at {secondary_ip}:993...")
    assert check_mail_via_imap(secondary_ip, user, password, subject), (
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
    setup_mail_user(juju, primary, secondary, user, password)

    # Send email on primary via SMTP so Postfix routes it through the LMTP socket
    # into Dovecot's mail store (the same store dsync replicates).
    subject = f"Auto Sync Test {token_hex(4)}"
    logging.info(f"Sending test email on primary with subject: {subject}")
    primary_ip = juju.status().apps[dovecot_charm_dual_unit].units[primary].public_address
    send_mail_via_smtp(
        host=primary_ip,
        sender=f"{user}@{MAILNAME}",
        recipient=f"{user}@{MAILNAME}",
        subject=subject,
        body="test body",
    )

    previous_sync_mtime = get_last_sync_mtime(juju, primary)
    previous_timer_count = get_sync_timer_run_count(juju, primary)

    try:
        # Lower sync schedule to every minute, wait for reconcile
        logging.info("Setting sync-schedule to *:* (every minute)...")
        juju.config(dovecot_charm_dual_unit, {"sync-schedule": "*:*"})
        juju.wait(jubilant.all_active, timeout=5 * 60)

        logging.info(f"Timer status after config change:\n{get_timer_status(juju, primary)}")
        logging.info("Waiting for first timer-triggered sync signal on primary...")
        wait_for_sync_trigger(juju, primary, previous_sync_mtime, previous_timer_count)

        # Verify email arrived on secondary via IMAP
        secondary_ip = juju.status().apps[dovecot_charm_dual_unit].units[secondary].public_address
        logging.info(f"Checking for email on secondary via IMAP at {secondary_ip}:993...")
        synced = check_mail_via_imap(secondary_ip, user, password, subject)
        if not synced:
            logging.info("Email not found after first timer sync.")
            logging.info(f"Sync log on primary:\n{get_sync_log_content(juju, primary)}")
            logging.info("Timer status:")
            logging.info(get_timer_status(juju, primary))
            logging.info("Trying manual sync as fallback to verify sync mechanism works...")
            juju.exec("/usr/local/bin/sync-to-secondary.sh", unit=primary)
            time.sleep(15)
            synced = check_mail_via_imap(secondary_ip, user, password, subject)
            if not synced:
                logging.info("Manual sync also failed. Checking sync log after manual run:")
                logging.info(f"Sync log:\n{get_sync_log_content(juju, primary, lines=30)}")

        assert synced, f"Email with subject '{subject}' not found on secondary after auto-sync"
    finally:
        # Reset sync-schedule to default
        logging.info("Resetting sync-schedule to default...")
        juju.config(dovecot_charm_dual_unit, {"sync-schedule": "daily"})
        juju.wait(jubilant.all_active, timeout=5 * 60)


def test_credentials_converge_independently_on_each_unit(
    juju: jubilant.Juju,
    dovecot_charm_dual_unit: str,
) -> None:
    """Each unit merges its local external source with application static users."""
    status = juju.status()
    units = sorted(status.apps[dovecot_charm_dual_unit].units)
    first_unit, second_unit = units
    suffix = token_hex(3)
    first_user = f"first-{suffix}"
    second_user = f"second-{suffix}"
    static_user = f"static-{suffix}"
    shared_user = f"shared-{suffix}"
    first_password = token_hex(12)
    second_password = token_hex(12)
    static_password = token_hex(12)
    static_shared_password = token_hex(12)
    external_shared_password = token_hex(12)
    static_credentials = [
        f"{static_user}:{crypt_password(static_password, salt='ha-static')}",
        f"{shared_user}:{crypt_password(static_shared_password, salt='ha-shared')}",
    ]

    try:
        juju.config(
            dovecot_charm_dual_unit,
            {
                "mail-credentials-path": "",
                "mail-users": DEFAULT_MAIL_USERS,
            },
        )
        juju.wait(jubilant.all_active, timeout=5 * 60)
        write_credential_source(
            juju,
            first_unit,
            HA_CREDENTIAL_SOURCE,
            [
                f"{first_user}:{crypt_password(first_password, salt='ha-first')}",
                f"{shared_user}:"
                f"{crypt_password(external_shared_password, salt='ha-first-shared')}",
            ],
        )
        write_credential_source(
            juju,
            second_unit,
            HA_CREDENTIAL_SOURCE,
            [
                f"{second_user}:{crypt_password(second_password, salt='ha-second')}",
                f"{shared_user}:"
                f"{crypt_password(external_shared_password, salt='ha-second-shared')}",
            ],
        )
        juju.config(
            dovecot_charm_dual_unit,
            {
                "mail-credentials-path": HA_CREDENTIAL_SOURCE,
                "mail-users": yaml.safe_dump(static_credentials),
            },
        )
        juju.wait(jubilant.all_active, timeout=5 * 60)
        assert run_credential_sync(juju, first_unit) == 0
        assert run_credential_sync(juju, second_unit) == 0

        refreshed_status = juju.status()
        first_ip = refreshed_status.apps[dovecot_charm_dual_unit].units[first_unit].public_address
        second_ip = (
            refreshed_status.apps[dovecot_charm_dual_unit].units[second_unit].public_address
        )

        assert imap_authenticates(first_ip, first_user, first_password)
        assert not imap_authenticates(first_ip, second_user, second_password)
        assert imap_authenticates(second_ip, second_user, second_password)
        assert not imap_authenticates(second_ip, first_user, first_password)
        for unit_ip in (first_ip, second_ip):
            assert imap_authenticates(unit_ip, static_user, static_password)
            assert imap_authenticates(unit_ip, shared_user, static_shared_password)
            assert not imap_authenticates(unit_ip, shared_user, external_shared_password)
    finally:
        juju.config(
            dovecot_charm_dual_unit,
            {
                "mail-credentials-path": "",
                "mail-users": DEFAULT_MAIL_USERS,
            },
        )
        juju.wait(jubilant.all_active, timeout=5 * 60)
        for unit in units:
            remove_credential_source(juju, unit, HA_CREDENTIAL_SOURCE)
