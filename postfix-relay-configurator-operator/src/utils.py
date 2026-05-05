# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Utils."""

import grp
import os
import pwd
import shutil
from pathlib import Path


def write_file(
    content: str,
    destination_path: str | os.PathLike,
    perms: int = 0o644,
    group: str | None = None,
) -> None:
    """Write file only on changes and return True if changes written.

    Args:
        content: file content.
        destination_path: destination path.
        perms: permissions.
        group: file group.
    """
    path = Path(destination_path)

    if path.is_file() and path.read_text("utf-8") == content:
        return

    owner = pwd.getpwuid(os.getuid()).pw_name
    if group is None:
        group = grp.getgrgid(pwd.getpwnam(owner).pw_gid).gr_name
    path.write_text(content, "utf-8")
    path.chmod(perms)

    shutil.chown(path, user=owner, group=group)
