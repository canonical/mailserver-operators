# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import imaplib
import logging
import ssl
import time

import jubilant
import pytest

APP_NAME = "dovecot-charm"


@pytest.fixture(scope="module")
def deploy_two_units(juju, dovecot_charm):
    """Add a second unit to the charm."""
    config = {
        "sync-schedule": "*/30 * * * *",
    }
    juju.config(APP_NAME, config)
    status = juju.status()
    if len(status.apps[APP_NAME].units) < 2:
        logging.info("Adding the second unit...")
        juju.add_unit(APP_NAME, num_units=1)

    logging.info("Waiting for active status...")
    juju.wait(jubilant.all_active, timeout=1200)

    status = juju.status()
    units = sorted(status.apps[APP_NAME].units.keys())
    real_primary = units[0]
    logging.info(f"Setting primary-unit to {real_primary}...")
    juju.config(APP_NAME, {"primary-unit": real_primary})
    juju.wait(jubilant.all_active, timeout=300)


def test_manual_sync(juju, deploy_two_units):
    """Test manual 'force-sync' action."""
    status = juju.status()
    units = sorted(status.apps[APP_NAME].units.keys())
    unit_0 = units[0]
    unit_1 = units[1]
    logging.info(f"Primary unit: {unit_0}, Secondary unit: {unit_1}")

    logging.info("Creating user 'syncuser'...")
    for unit in [unit_0, unit_1]:
        juju.exec("id -u syncuser || useradd -m -G mail syncuser -s /bin/bash", unit=unit)
        juju.exec("usermod -aG mail syncuser", unit=unit)
        juju.exec("echo 'syncuser:password' | chpasswd", unit=unit)

    logging.info("Injecting email on Unit 0...")
    _ensure_maildir(juju, unit_0, "syncuser")
    cmd = "echo 'Manual Sync Body' | mail -s 'Manual Sync Test' syncuser@localhost"
    juju.exec(cmd, unit=unit_0)

    _verify_imap(juju, unit_0, "Manual Sync Test")

    try:
        _verify_imap(juju, unit_1, "Manual Sync Test", retries=1)
        pytest.fail("Email should not exist on Unit 1 yet")
    except Exception:
        logging.info("Confirmed email not yet on Unit 1")

    logging.info("Refreshing sync configuration...")
    juju.config(APP_NAME, {"sync-schedule": "*/29 * * * *"})
    juju.wait(jubilant.all_active, timeout=300)
    juju.config(APP_NAME, {"sync-schedule": "*/30 * * * *"})
    juju.wait(jubilant.all_active, timeout=300)

    logging.info("Running force-sync action...")
    juju.run(unit_0, "force-sync")

    logging.info("Verifying email synced to Unit 1...")
    _verify_imap(juju, unit_1, "Manual Sync Test")


def test_periodic_sync(juju, deploy_two_units):
    """Test periodic cron sync."""
    status = juju.status()
    units = sorted(status.apps[APP_NAME].units.keys())
    unit_0 = units[0]
    unit_1 = units[1]

    logging.info("Changing sync-schedule to 1 minute...")
    juju.config(APP_NAME, {"sync-schedule": "* * * * *"})
    juju.wait(jubilant.all_active, timeout=300)

    logging.info("Ensuring user 'syncuser' exists...")
    for unit in [unit_0, unit_1]:
        juju.exec("id -u syncuser || useradd -m -G mail syncuser -s /bin/bash", unit=unit)
        juju.exec("usermod -aG mail syncuser", unit=unit)
        juju.exec("echo 'syncuser:password' | chpasswd", unit=unit)

    logging.info("Injecting periodic email on Unit 0...")
    _ensure_maildir(juju, unit_0, "syncuser")
    cmd = "echo 'Periodic Sync Body' | mail -s 'Periodic Sync Test' syncuser@localhost"
    juju.exec(cmd, unit=unit_0)

    logging.info("Waiting for cron execution (up to 180s)...")
    time.sleep(180)

    logging.info("Verifying email synced to Unit 1...")
    _verify_imap(juju, unit_1, "Periodic Sync Test")


def _verify_imap(juju, unit_name, subject, retries=5):
    """Helper to check IMAP for a specific subject."""
    status = juju.status()
    unit_ip = status.apps[APP_NAME].units[unit_name].public_address

    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    for i in range(retries):
        try:
            if ":" in unit_ip:
                unit_ip = f"[{unit_ip}]"
            mail = imaplib.IMAP4_SSL(unit_ip, port=993, ssl_context=context)
            mail.login("syncuser", "password")
            mail.select("inbox")
            _typ, data = mail.search(None, f'(HEADER Subject "{subject}")')
            mail.close()
            mail.logout()

            if data and data[0]:
                return True
        except Exception as e:
            logging.warning(f"IMAP check {i} failed: {e}")

        time.sleep(5)

    raise Exception(f"Email with subject '{subject}' not found on {unit_name}")


def _ensure_maildir(juju, unit_name, username):
    """Ensure the user's Maildir exists before attempting sync."""
    # The sync script expects /srv/mail/<user>/Maildir to exist.
    # We create the parent Maildir with correct ownership to avoid
    # dovecot permission errors (bug fix: parent must be owned by user, not root).
    create_dirs = (
        f"install -d -m 0700 -o {username} -g mail /srv/mail/{username} && "
        f"install -d -m 0700 -o {username} -g mail /srv/mail/{username}/Maildir && "
        f"install -d -m 0700 -o {username} -g mail "
        f"/srv/mail/{username}/Maildir/cur /srv/mail/{username}/Maildir/new "
        f"/srv/mail/{username}/Maildir/tmp"
    )
    juju.exec(create_dirs, unit=unit_name)
    juju.exec(f"doveadm mailbox create -u {username} INBOX", unit=unit_name)
