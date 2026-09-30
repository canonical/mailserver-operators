#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Validate, merge, and atomically install Dovecot credentials."""

from __future__ import annotations

import grp
import os
import pwd
import subprocess  # nosec
import tempfile
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_CRYPT_IDENTIFIERS = frozenset({"1", "5", "6", "y"})


class CredentialError(Exception):
    """Base credential synchronization error."""


@dataclass(frozen=True)
class SyncResult:
    """Result of a credential synchronization."""

    using_cached_external_users: bool
    external_user_count: int
    synchronization_failed: bool = False


def is_valid_username(username: str) -> bool:
    """Return whether a username is safe to use as a mailbox directory name."""
    return (
        bool(username)
        and username not in {".", ".."}
        and "/" not in username
        and not any(ord(character) < 32 or ord(character) == 127 for character in username)
    )


def normalize_username(username: str) -> str:
    """Normalize an email-style username to a bare account name."""
    username_parts = username.split("@")
    if len(username_parts) > 2 or not username_parts[0]:
        raise CredentialError("credential entry contains an invalid username")
    if len(username_parts) == 2 and not username_parts[1]:
        raise CredentialError("email-style username has an empty domain")

    bare_username = username_parts[0]
    if not is_valid_username(bare_username):
        raise CredentialError("credential entry contains an invalid account name")
    return bare_username


def validate_credential(entry: object) -> tuple[str, str]:
    """Validate one credential and return its bare username and normalized entry."""
    if not isinstance(entry, str):
        raise CredentialError("credential entry must be a string")

    entry = entry.strip()
    if not entry:
        raise CredentialError("credential entry is empty")

    username, separator, password_hash = entry.partition(":")
    if not separator or ":" in password_hash:
        raise CredentialError("credential entry must contain exactly one ':' separator")

    bare_username = normalize_username(username)

    if not password_hash.lower().startswith("{crypt}$"):
        raise CredentialError("credential hash has an unsupported format")

    hash_parts = password_hash.split("$", 2)
    if (
        len(hash_parts) != 3
        or hash_parts[1] not in SUPPORTED_CRYPT_IDENTIFIERS
        or not hash_parts[2]
    ):
        raise CredentialError("credential hash has an unsupported identifier")
    if any(character.isspace() for character in password_hash):
        raise CredentialError("credential hash contains whitespace")

    return bare_username, f"{bare_username}:{password_hash}"


def parse_credentials(contents: str) -> dict[str, str]:
    """Parse and validate a complete Dovecot passwd-file."""
    return parse_credential_entries(contents.splitlines())


def parse_credential_entries(entries: list[object]) -> dict[str, str]:
    """Parse and validate complete credential entries."""
    credentials: dict[str, str] = {}
    for entry in entries:
        if isinstance(entry, str) and not entry.strip():
            continue
        username, credential = validate_credential(entry)
        if username in credentials:
            raise CredentialError("duplicate normalized username")
        credentials[username] = credential
    return credentials


def render_credentials(credentials: dict[str, str]) -> str:
    """Render credentials deterministically with one entry per line."""
    lines = [credentials[username] for username in sorted(credentials)]
    return "\n".join(lines) + ("\n" if lines else "")


def atomic_write(path: Path, contents: str, *, user: str, group: str, mode: int) -> bool:
    """Atomically replace a file if its contents changed."""
    try:
        if path.read_text() == contents:
            return False
    except FileNotFoundError:
        pass

    path.parent.mkdir(parents=True, exist_ok=True)
    uid = pwd.getpwnam(user).pw_uid
    gid = grp.getgrnam(group).gr_gid
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as temporary_file:
            temporary_file.write(contents)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.chown(temporary_path, uid, gid)
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return True


def read_credentials(path: Path) -> dict[str, str]:
    """Read and validate a credential file."""
    try:
        contents = path.read_text()
    except OSError as exc:
        raise CredentialError(f"unable to read credential source: {exc.strerror}") from exc
    return parse_credentials(contents)


def sync_credentials(
    *,
    source_path: Path | None,
    static_users: list[str],
    cache_path: Path,
    effective_path: Path,
) -> SyncResult:
    """Merge static users over the latest valid external credentials."""
    static_credentials = parse_credential_entries(static_users)
    using_cache = False

    if source_path is None:
        external_users: dict[str, str] = {}
        atomic_write(cache_path, "", user="root", group="dovecot", mode=0o640)
    else:
        try:
            external_users = read_credentials(source_path)
        except CredentialError as source_error:
            try:
                external_users = read_credentials(cache_path)
            except CredentialError:
                if effective_path.exists():
                    existing_users = read_credentials(effective_path)
                    if existing_users:
                        raise CredentialError(
                            "external credentials are unavailable and no valid cache exists"
                        ) from source_error
                external_users = {}
                atomic_write(cache_path, "", user="root", group="dovecot", mode=0o640)
            using_cache = True
        else:
            atomic_write(
                cache_path,
                render_credentials(external_users),
                user="root",
                group="dovecot",
                mode=0o640,
            )

    effective_users = {**external_users, **static_credentials}
    changed = atomic_write(
        effective_path,
        render_credentials(effective_users),
        user="root",
        group="dovecot",
        mode=0o640,
    )
    if changed:
        subprocess.run(
            ["/usr/bin/systemctl", "reload", "dovecot"],
            check=True,
            capture_output=True,
            text=True,
        )

    return SyncResult(
        using_cached_external_users=using_cache,
        external_user_count=len(external_users),
    )
