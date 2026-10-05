#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Validate and atomically install Dovecot credentials."""

from __future__ import annotations

import grp
import os
import pwd
import tempfile
from pathlib import Path

SUPPORTED_CRYPT_IDENTIFIERS = frozenset({"1", "5", "6", "y"})


class CredentialError(Exception):
    """Base credential validation error."""


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

    if not password_hash.startswith("$"):
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


def render_dovecot_credentials(credentials: dict[str, str]) -> str:
    """Render credentials with empty userdb columns for Dovecot defaults."""
    lines = [f"{credentials[username]}::::::" for username in sorted(credentials)]
    return "\n".join(lines) + ("\n" if lines else "")


def atomic_write(path: Path, contents: str, *, user: str, group: str, mode: int) -> bool:
    """Atomically replace a file if its contents changed."""
    uid = pwd.getpwnam(user).pw_uid
    gid = grp.getgrnam(group).gr_gid
    try:
        if path.read_text() == contents:
            os.chown(path, uid, gid)
            os.chmod(path, mode)
            return False
    except FileNotFoundError:
        pass

    path.parent.mkdir(parents=True, exist_ok=True)
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
