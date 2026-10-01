# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for virtual-user credential reconciliation."""

import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import credentials


@pytest.fixture()
def mock_ownership(monkeypatch):
    """Avoid requiring Dovecot system accounts in the unit-test environment."""
    monkeypatch.setattr(
        credentials.pwd,
        "getpwnam",
        MagicMock(return_value=SimpleNamespace(pw_uid=os.getuid())),
    )
    monkeypatch.setattr(
        credentials.grp,
        "getgrnam",
        MagicMock(return_value=SimpleNamespace(gr_gid=os.getgid())),
    )
    monkeypatch.setattr(credentials.os, "chown", MagicMock())


@pytest.mark.parametrize("identifier", ["1", "5", "6", "y"])
def test_validate_credential_accepts_supported_hashes(identifier):
    """All required crypt identifiers are accepted and email logins are normalized."""
    username, entry = credentials.validate_credential(
        f"alice@example.com:{{crypt}}${identifier}$hash"
    )

    assert username == "alice"
    assert entry == f"alice:{{crypt}}${identifier}$hash"


@pytest.mark.parametrize(
    "entry",
    [
        "alice",
        "alice:plaintext",
        "alice:{crypt}$2$hash",
        "alice:{crypt}$6$",
    ],
)
def test_validate_credential_rejects_malformed_entries(entry):
    """Malformed credential entries are rejected."""
    with pytest.raises(credentials.CredentialError):
        credentials.validate_credential(entry)


def test_sync_credentials_merges_authoritatively_and_atomically(
    tmp_path,
    monkeypatch,
    mock_ownership,
):
    """Static users override external users and successful refreshes remove deleted users."""
    source = tmp_path / "source"
    cache = tmp_path / "cache"
    effective = tmp_path / "users"
    source.write_text("shared:{crypt}$6$external\nexternal:{crypt}$6$old\n")
    static = ["shared:{crypt}$6$static", "static:{crypt}$6$hash"]
    replace = MagicMock(wraps=os.replace)
    reload_dovecot = MagicMock()
    monkeypatch.setattr(credentials.os, "replace", replace)
    monkeypatch.setattr(credentials.subprocess, "run", reload_dovecot)

    credentials.sync_credentials(
        source_path=source,
        static_users=static,
        cache_path=cache,
        effective_path=effective,
    )

    assert effective.read_text().splitlines() == [
        "external:{crypt}$6$old",
        "shared:{crypt}$6$static",
        "static:{crypt}$6$hash",
    ]
    assert effective.stat().st_mode & 0o777 == 0o640
    assert cache.stat().st_mode & 0o777 == 0o640
    assert any(call.args[1] == effective for call in replace.call_args_list)

    source.write_text("replacement:{crypt}$6$new\n")
    credentials.sync_credentials(
        source_path=source,
        static_users=static,
        cache_path=cache,
        effective_path=effective,
    )

    assert effective.read_text().splitlines() == [
        "replacement:{crypt}$6$new",
        "shared:{crypt}$6$static",
        "static:{crypt}$6$hash",
    ]
    assert reload_dovecot.call_count == 2


def test_sync_credentials_uses_last_known_good_source(tmp_path, monkeypatch, mock_ownership):
    """Invalid or missing source data retains the last valid external credentials."""
    source = tmp_path / "source"
    cache = tmp_path / "cache"
    effective = tmp_path / "users"
    source.write_text("external:{crypt}$6$valid\n")
    reload_dovecot = MagicMock()
    monkeypatch.setattr(credentials.subprocess, "run", reload_dovecot)

    credentials.sync_credentials(
        source_path=source,
        static_users=[],
        cache_path=cache,
        effective_path=effective,
    )
    expected = effective.read_text()

    source.write_text("malformed")
    malformed_result = credentials.sync_credentials(
        source_path=source,
        static_users=[],
        cache_path=cache,
        effective_path=effective,
    )
    source.unlink()
    missing_result = credentials.sync_credentials(
        source_path=source,
        static_users=[],
        cache_path=cache,
        effective_path=effective,
    )

    assert malformed_result.using_cached_external_users
    assert missing_result.using_cached_external_users
    assert effective.read_text() == expected
    assert reload_dovecot.call_count == 1
