# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Utils."""

import grp
import os
import pwd
import shutil
from pathlib import Path
from typing import Any

import jinja2


def write_file(
    content: str,
    destination_path: str | os.PathLike,
    perms: int = 0o644,
    group: str | None = None,
) -> None:
    """Write file.

    Args:
        content: file content.
        destination_path: destination path.
        perms: permissions.
        group: file group.
    """
    path = Path(destination_path)
    owner = pwd.getpwuid(os.getuid()).pw_name
    if group is None:
        group = grp.getgrgid(pwd.getpwnam(owner).pw_gid).gr_name
    path.write_text(content, "utf-8")
    path.chmod(perms)
    shutil.chown(path, user=owner, group=group)


def render_jinja2_template(
    context: dict[str, Any],
    template_path: str | os.PathLike,
    base_path: str | None = None,
) -> str:
    """Render jinja2 template given the context.

    Args:
        context: Variables to render into the template.
        template_path: path of the Jinja2 template (relative to base_path).
        base_path: base path to the template, defaults to the project root.
    """
    base = Path(base_path) if base_path else Path(__file__).resolve().parent.parent
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(base), autoescape=True)
    template = env.get_template(str(template_path))
    return template.render(context)
