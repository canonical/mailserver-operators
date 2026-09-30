# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for virtual-user credential synchronization."""

import time
from collections.abc import Generator
from secrets import token_hex

import jubilant
import pytest
import yaml

from .conftest import MAILNAME
from .helpers import (
    DEFAULT_MAIL_USERS,
    crypt_password,
    imap_authenticates,
    remove_credential_source,
    run_credential_sync,
    write_credential_source,
)

SOURCE_PATH = "/var/lib/misc/thishost/integration-test-mail-users"
EFFECTIVE_PATH = "/etc/dovecot/users"
CACHE_PATH = "/var/lib/dovecot/auth/external-users"


@pytest.fixture()
def credential_sync_unit(
    juju: jubilant.Juju,
    dovecot_charm: str,
) -> Generator[tuple[str, str], None, None]:
    """Reset credential state around each synchronization test."""
    unit_name = f"{dovecot_charm}/0"
    juju.config(
        dovecot_charm,
        {
            "credential-sync-interval": 5,
            "mail-credentials-path": "",
            "mail-users": DEFAULT_MAIL_USERS,
        },
    )
    juju.wait(
        lambda status: status.apps[dovecot_charm].is_active,
        error=jubilant.any_error,
        timeout=5 * 60,
    )
    remove_credential_source(juju, unit_name, SOURCE_PATH)

    yield dovecot_charm, unit_name

    juju.config(
        dovecot_charm,
        {
            "credential-sync-interval": 5,
            "mail-credentials-path": "",
            "mail-users": DEFAULT_MAIL_USERS,
        },
    )
    juju.wait(
        lambda status: status.apps[dovecot_charm].is_active,
        error=jubilant.any_error,
        timeout=5 * 60,
    )
    remove_credential_source(juju, unit_name, SOURCE_PATH)


def _configure_credentials(
    juju: jubilant.Juju,
    app_name: str,
    static_credentials: list[str],
) -> None:
    """Configure the external source and static credentials."""
    juju.config(
        app_name,
        {
            "credential-sync-interval": 5,
            "mail-credentials-path": SOURCE_PATH,
            "mail-users": yaml.safe_dump(static_credentials),
        },
    )
    juju.wait(
        lambda status: status.apps[app_name].is_active,
        error=jubilant.any_error,
        timeout=5 * 60,
    )


def _unit_ip(juju: jubilant.Juju, app_name: str, unit_name: str) -> str:
    """Return a unit's public address."""
    return juju.status().apps[app_name].units[unit_name].public_address


def _effective_usernames(juju: jubilant.Juju, unit_name: str) -> set[str]:
    """Read only usernames from the effective file, never password hashes."""
    output = juju.exec(
        f"sudo cut -d: -f1 {EFFECTIVE_PATH}",
        unit=unit_name,
    ).stdout
    return set(output.splitlines())


def _effective_fingerprint(juju: jubilant.Juju, unit_name: str) -> str:
    """Return non-sensitive metadata proving whether the effective file changed."""
    return juju.exec(
        f"sudo stat -c '%i:%s:%Y' {EFFECTIVE_PATH}",
        unit=unit_name,
    ).stdout.strip()


def test_external_and_static_users_authenticate_with_static_precedence(
    juju: jubilant.Juju,
    credential_sync_unit: tuple[str, str],
) -> None:
    """External and static users authenticate, with static duplicate precedence."""
    app_name, unit_name = credential_sync_unit
    suffix = token_hex(3)
    external_user = f"external-{suffix}"
    static_user = f"static-{suffix}"
    shared_user = f"shared-{suffix}"
    external_password = token_hex(12)
    static_password = token_hex(12)
    shared_external_password = token_hex(12)
    shared_static_password = token_hex(12)
    crypt_passwords = {identifier: token_hex(12) for identifier in ("1", "5", "6")}

    external_credentials = [
        f"{external_user}:{crypt_password(external_password, salt='external')}",
        f"{shared_user}:{crypt_password(shared_external_password, salt='external-shared')}",
        f"crypt1-{suffix}:{crypt_password(crypt_passwords['1'], identifier='1', salt='crypt1')}",
        f"crypt5-{suffix}:{crypt_password(crypt_passwords['5'], identifier='5', salt='crypt5')}",
        f"crypt6-{suffix}:{crypt_password(crypt_passwords['6'], identifier='6', salt='crypt6')}",
        f"crypty-{suffix}:{{crypt}}$y$j9T$integration$accepted-by-parser",
    ]
    static_credentials = [
        f"{static_user}:{crypt_password(static_password, salt='static')}",
        f"{shared_user}:{crypt_password(shared_static_password, salt='static-shared')}",
    ]

    write_credential_source(juju, unit_name, SOURCE_PATH, external_credentials)
    _configure_credentials(juju, app_name, static_credentials)
    assert run_credential_sync(juju, unit_name) == 0

    unit_ip = _unit_ip(juju, app_name, unit_name)
    assert imap_authenticates(unit_ip, external_user, external_password)
    assert imap_authenticates(unit_ip, f"{external_user}@{MAILNAME}", external_password)
    assert imap_authenticates(unit_ip, static_user, static_password)
    assert imap_authenticates(unit_ip, shared_user, shared_static_password)
    assert not imap_authenticates(unit_ip, shared_user, shared_external_password)
    for identifier, password in crypt_passwords.items():
        assert imap_authenticates(unit_ip, f"crypt{identifier}-{suffix}", password)

    expected_users = {
        external_user,
        static_user,
        shared_user,
        f"crypt1-{suffix}",
        f"crypt5-{suffix}",
        f"crypt6-{suffix}",
        f"crypty-{suffix}",
    }
    assert _effective_usernames(juju, unit_name) == expected_users

    juju.exec(
        (
            f"test \"$(stat -c '%U:%G:%a' {EFFECTIVE_PATH})\" = root:dovecot:640 && "
            f"test \"$(stat -c '%U:%G:%a' {CACHE_PATH})\" = root:dovecot:640 && "
            "test \"$(stat -c '%U:%G:%a' /var/lib/dovecot/auth)\" = root:dovecot:750"
        ),
        unit=unit_name,
    )
    juju.exec(
        (
            "getent passwd vmail | "
            'awk -F: \'$3 == 5000 && $4 == 5000 && $6 == "/srv/mail" {found=1} '
            "END {exit !found}' && "
            f"! getent passwd {external_user} && "
            f'test "$(doveadm user -f home {external_user})" = /srv/mail/{external_user} && '
            "test \"$(doveconf -h mail_location)\" = 'maildir:/srv/mail/%u/Maildir'"
        ),
        unit=unit_name,
    )
    juju.exec(
        (
            "systemctl is-active --quiet dovecot-credential-sync.timer && "
            "systemctl cat dovecot-credential-sync.timer | grep -q '^OnUnitActiveSec=5min$'"
        ),
        unit=unit_name,
    )
    journal = juju.exec(
        "journalctl -u dovecot-credential-sync.service --no-pager",
        unit=unit_name,
    ).stdout
    sensitive_values = [
        external_password,
        static_password,
        shared_external_password,
        shared_static_password,
        *crypt_passwords.values(),
        *external_credentials,
        *static_credentials,
    ]
    assert not any(value in journal for value in sensitive_values)


def test_successful_refresh_is_authoritative_and_atomic(
    juju: jubilant.Juju,
    credential_sync_unit: tuple[str, str],
) -> None:
    """Successful refreshes change credentials and remove deleted external users."""
    app_name, unit_name = credential_sync_unit
    username = f"refresh-{token_hex(3)}"
    original_password = token_hex(12)
    updated_password = token_hex(12)

    write_credential_source(
        juju,
        unit_name,
        SOURCE_PATH,
        [f"{username}:{crypt_password(original_password, salt='original')}"],
    )
    _configure_credentials(juju, app_name, [])
    assert run_credential_sync(juju, unit_name) == 0

    unit_ip = _unit_ip(juju, app_name, unit_name)
    assert imap_authenticates(unit_ip, username, original_password)
    original_fingerprint = _effective_fingerprint(juju, unit_name)

    time.sleep(1)
    write_credential_source(
        juju,
        unit_name,
        SOURCE_PATH,
        [f"{username}:{crypt_password(updated_password, salt='updated')}"],
    )
    assert run_credential_sync(juju, unit_name) == 0
    assert _effective_fingerprint(juju, unit_name) != original_fingerprint
    assert not imap_authenticates(unit_ip, username, original_password)
    assert imap_authenticates(unit_ip, username, updated_password)
    juju.exec(
        f'test -z "$(find {EFFECTIVE_PATH.rsplit("/", 1)[0]} -maxdepth 1 '
        "-name '.users.*' -print -quit)\"",
        unit=unit_name,
    )

    write_credential_source(juju, unit_name, SOURCE_PATH, [])
    assert run_credential_sync(juju, unit_name) == 0
    assert username not in _effective_usernames(juju, unit_name)
    assert not imap_authenticates(unit_ip, username, updated_password)


def test_invalid_or_missing_source_retains_last_known_good_credentials(
    juju: jubilant.Juju,
    credential_sync_unit: tuple[str, str],
) -> None:
    """Malformed or missing sources report failure without replacing valid credentials."""
    app_name, unit_name = credential_sync_unit
    username = f"retained-{token_hex(3)}"
    password = token_hex(12)

    write_credential_source(
        juju,
        unit_name,
        SOURCE_PATH,
        [f"{username}:{crypt_password(password, salt='retained')}"],
    )
    _configure_credentials(juju, app_name, [])
    assert run_credential_sync(juju, unit_name) == 0

    unit_ip = _unit_ip(juju, app_name, unit_name)
    fingerprint = _effective_fingerprint(juju, unit_name)
    assert imap_authenticates(unit_ip, username, password)

    write_credential_source(
        juju,
        unit_name,
        SOURCE_PATH,
        ["malformed-entry-without-a-password-hash"],
    )
    assert run_credential_sync(juju, unit_name) == 1
    assert _effective_fingerprint(juju, unit_name) == fingerprint
    assert imap_authenticates(unit_ip, username, password)

    remove_credential_source(juju, unit_name, SOURCE_PATH)
    assert run_credential_sync(juju, unit_name) == 1
    assert _effective_fingerprint(juju, unit_name) == fingerprint
    assert imap_authenticates(unit_ip, username, password)
    juju.exec(
        (
            "journalctl -u dovecot-credential-sync.service --no-pager -n 20 | "
            "grep -q 'retained last valid credentials'"
        ),
        unit=unit_name,
    )
