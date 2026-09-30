# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Credential synchronization runner template tests."""

from pathlib import Path

import jinja2


def test_runner_template_renders_valid_python() -> None:
    """Python literals remain valid when Jinja autoescaping is enabled."""
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(Path(__file__).parents[2] / "templates"),
        autoescape=True,
    )
    rendered = environment.get_template("dovecot-credential-sync.py.tmpl").render(
        {
            "cache_path": "/var/lib/dovecot/auth/external-users",
            "effective_path": "/etc/dovecot/users",
            "module_dir": "/usr/local/lib/dovecot-charm",
            "source_path": "/source/users&aliases",
            "static_users": ["user:{crypt}$6$hash"],
        }
    )

    compile(rendered, "dovecot-credential-sync", "exec")
    assert "&#" not in rendered
    assert "&amp;" not in rendered
