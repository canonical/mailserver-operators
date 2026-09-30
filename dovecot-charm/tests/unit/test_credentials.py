# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from credentials import (
    CredentialError,
    atomic_write,
    parse_credentials,
    sync_credentials,
    validate_credential,
)


@pytest.fixture(autouse=True)
def mock_file_ownership():
    """Use the test process UID/GID instead of requiring system accounts."""
    with (
        patch("credentials.pwd.getpwnam", return_value=SimpleNamespace(pw_uid=os.getuid())),
        patch("credentials.grp.getgrnam", return_value=SimpleNamespace(gr_gid=os.getgid())),
        patch("credentials.subprocess.run"),
    ):
        yield


@pytest.mark.parametrize("identifier", ["1", "5", "6", "y"])
def test_validate_credential_accepts_supported_identifiers(identifier):
    username, credential = validate_credential(
        f"alice@example.com:{{crypt}}${identifier}$hash-value"
    )

    assert username == "alice"
    assert credential == f"alice:{{crypt}}${identifier}$hash-value"


def test_validate_credential_accepts_username_allowed_by_legacy_check():
    username, credential = validate_credential("alice+mail:{crypt}$6$hash-value")

    assert username == "alice+mail"
    assert credential == "alice+mail:{crypt}$6$hash-value"


@pytest.mark.parametrize(
    "credential",
    [
        "alice:plaintext",
        "alice:{crypt}$2$hash-value",
        "alice:{crypt}$6$",
        "bad/user:{crypt}$6$hash-value",
        "alice:{crypt}$6$hash value",
    ],
)
def test_validate_credential_rejects_malformed_entries(credential):
    with pytest.raises(CredentialError):
        validate_credential(credential)


def test_parse_credentials_rejects_duplicate_normalized_usernames():
    contents = "alice:{crypt}$6$first\nalice@example.com:{crypt}$6$second\n"

    with pytest.raises(CredentialError, match="duplicate normalized username"):
        parse_credentials(contents)


def test_sync_credentials_merges_static_users_with_precedence(tmp_path):
    source = tmp_path / "source"
    cache = tmp_path / "cache"
    effective = tmp_path / "effective"
    source.write_text("alice:{crypt}$6$ldap\nbob:{crypt}$6$ldap\n")

    result = sync_credentials(
        source_path=source,
        static_users=["alice:{crypt}$6$static"],
        cache_path=cache,
        effective_path=effective,
    )

    assert result.external_user_count == 2
    assert not result.using_cached_external_users
    assert cache.read_text() == "alice:{crypt}$6$ldap\nbob:{crypt}$6$ldap\n"
    assert effective.read_text() == "alice:{crypt}$6$static\nbob:{crypt}$6$ldap\n"


def test_sync_credentials_removes_deleted_external_users(tmp_path):
    source = tmp_path / "source"
    cache = tmp_path / "cache"
    effective = tmp_path / "effective"
    source.write_text("alice:{crypt}$6$first\nbob:{crypt}$6$first\n")
    sync_credentials(
        source_path=source,
        static_users=[],
        cache_path=cache,
        effective_path=effective,
    )

    source.write_text("bob:{crypt}$6$second\n")
    sync_credentials(
        source_path=source,
        static_users=[],
        cache_path=cache,
        effective_path=effective,
    )

    assert cache.read_text() == "bob:{crypt}$6$second\n"
    assert effective.read_text() == "bob:{crypt}$6$second\n"


def test_sync_credentials_uses_cache_and_applies_static_changes(tmp_path):
    source = tmp_path / "source"
    cache = tmp_path / "cache"
    effective = tmp_path / "effective"
    source.write_text("alice:{crypt}$6$ldap\n")
    sync_credentials(
        source_path=source,
        static_users=[],
        cache_path=cache,
        effective_path=effective,
    )

    source.write_text("malformed")
    result = sync_credentials(
        source_path=source,
        static_users=["bob:{crypt}$6$static"],
        cache_path=cache,
        effective_path=effective,
    )

    assert result.using_cached_external_users
    assert effective.read_text() == "alice:{crypt}$6$ldap\nbob:{crypt}$6$static\n"


def test_sync_credentials_allows_static_only_first_boot(tmp_path):
    source = tmp_path / "missing"
    cache = tmp_path / "cache"
    effective = tmp_path / "effective"

    result = sync_credentials(
        source_path=source,
        static_users=["alice:{crypt}$6$static"],
        cache_path=cache,
        effective_path=effective,
    )

    assert result.using_cached_external_users
    assert result.external_user_count == 0
    assert effective.read_text() == "alice:{crypt}$6$static\n"


def test_sync_credentials_preserves_populated_effective_file_without_cache(tmp_path):
    source = tmp_path / "missing"
    cache = tmp_path / "cache"
    effective = tmp_path / "effective"
    effective.write_text("alice:{crypt}$6$previous\n")

    with pytest.raises(CredentialError, match="no valid cache"):
        sync_credentials(
            source_path=source,
            static_users=[],
            cache_path=cache,
            effective_path=effective,
        )

    assert effective.read_text() == "alice:{crypt}$6$previous\n"


def test_atomic_write_sets_permissions(tmp_path):
    destination = tmp_path / "users"

    atomic_write(
        destination,
        "alice:{crypt}$6$hash\n",
        user="root",
        group="dovecot",
        mode=0o640,
    )

    assert destination.read_text() == "alice:{crypt}$6$hash\n"
    assert destination.stat().st_mode & 0o777 == 0o640
