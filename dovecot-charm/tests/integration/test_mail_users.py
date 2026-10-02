# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for mail users configured through a Juju secret."""

from secrets import token_hex

import jubilant
import pytest

from .helpers import configure_mail_users, reset_mail_users, setup_mail_user


@pytest.fixture
def mail_users_unit(juju: jubilant.Juju, dovecot_charm: str):
    """Restore the shared secret after each authentication test."""
    unit_name = f"{dovecot_charm}/0"
    yield unit_name
    reset_mail_users(juju, unit_name)


def test_mail_users_secret_adds_new_user(juju: jubilant.Juju, mail_users_unit: str):
    """A secret user authenticates while a user absent from the secret does not."""
    user = f"secret-user-{token_hex(4)}"
    password = token_hex(16)
    unknown_user = f"unknown-user-{token_hex(4)}"

    setup_mail_user(juju, mail_users_unit, None, user, password)

    juju.exec(f"doveadm auth test {user} '{password}'", unit=mail_users_unit)
    with pytest.raises(jubilant.TaskError):
        juju.exec(f"doveadm auth test {unknown_user} invalid-password", unit=mail_users_unit)


def test_mail_users_secret_updates_existing_user(juju: jubilant.Juju, mail_users_unit: str):
    """Rotating a secret user's password invalidates the previous password."""
    user = f"secret-user-{token_hex(4)}"
    old_password = token_hex(16)
    new_password = token_hex(16)

    setup_mail_user(juju, mail_users_unit, None, user, old_password)
    setup_mail_user(juju, mail_users_unit, None, user, new_password)

    juju.exec(f"doveadm auth test {user} '{new_password}'", unit=mail_users_unit)
    with pytest.raises(jubilant.TaskError):
        juju.exec(f"doveadm auth test {user} '{old_password}'", unit=mail_users_unit)


def test_mail_users_secret_replaces_user_with_multiple_users(
    juju: jubilant.Juju, mail_users_unit: str
):
    """Rotating to multiple users removes old users and normalizes email-style logins."""
    old_user = f"secret-user-{token_hex(4)}"
    old_password = token_hex(16)
    bare_user = f"bare-user-{token_hex(4)}"
    bare_password = token_hex(16)
    new_user = f"mailbox-user-{token_hex(4)}"
    email_user = f"{new_user}@example.com"
    new_password = token_hex(16)

    setup_mail_user(juju, mail_users_unit, None, old_user, old_password)
    configure_mail_users(
        juju,
        mail_users_unit,
        {bare_user: bare_password, email_user: new_password},
    )

    juju.exec(f"doveadm auth test {bare_user} '{bare_password}'", unit=mail_users_unit)
    juju.exec(f"doveadm auth test {new_user} '{new_password}'", unit=mail_users_unit)
    juju.exec(f"doveadm auth test {email_user} '{new_password}'", unit=mail_users_unit)
    with pytest.raises(jubilant.TaskError):
        juju.exec(f"doveadm auth test {old_user} '{old_password}'", unit=mail_users_unit)
