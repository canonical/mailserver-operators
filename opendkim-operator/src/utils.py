# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""OpenDKIM charm utils."""

import os
import pwd
import re
from pathlib import Path


def update_logrotate_conf(
    path: Path, frequency: str | None = None, retention: int = 0, dateext: bool = True
) -> str:
    """Update existing logrotate config with log retention settings.

    Args:
        path: Path for the logrotate config.
        frequency: Frequency to use for the logrotate file.
        retention: Retention time for the logs.
        dateext: Add dateext to the rotation files.

    Returns:
        The updated content of the logrotate file.
    """
    if not os.path.exists(path):
        return ""

    with open(path, encoding="utf-8") as f:
        config = f.read().split("\n")

    new = []
    regex = re.compile("^(\\s+)(daily|weekly|monthly|rotate|dateext)")
    for line in config:
        m = regex.match(line)
        if not m:
            new.append(line)
            continue

        conf = m.group(2)
        indent = m.group(1)

        # Rotation frequency.
        if frequency and conf in ("daily", "weekly", "monthly"):
            new.append(f"{indent}{frequency}")
        elif retention and conf == "dateext":
            # Ignore 'dateext', we'll put it back on updating 'rotate'.
            continue
        elif retention and conf == "rotate":
            if dateext:
                new.append(f"{indent}dateext")
            new.append(f"{indent}rotate {retention}")
        else:
            new.append(line)

    return "\n".join(new)


def read_text(path: Path) -> str:
    """Return text from a file.

    Args:
        path: Path of the file ro read.

    Returns: String content of the file.
    """
    try:
        return path.read_text()
    except FileNotFoundError:
        return ""


def write_file(path: Path, content: str, mode: int, user: str) -> None:
    """Write a content rendered from a template to a file.

    Args:
        path: Path object to the file.
        content: the data to be written to the file.
        mode: access permission mask applied to the
            file using chmod (e.g. 0o640).
        user: The user that will own the file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    os.chmod(path, mode)
    try:
        u = pwd.getpwnam(user)
    except KeyError:
        # Fallback to root if user does not exist (e.g., opendkim snap not yet installed).
        u = pwd.getpwnam("root")
    os.chown(path, uid=u.pw_uid, gid=u.pw_gid)
