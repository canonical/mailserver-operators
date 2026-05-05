# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Dovecot Service Layer."""

from pathlib import Path

import utils


def construct_dovecot_config_file_content(
    dovecot_users_path: str | Path, enable_smtp_auth: bool
) -> str:
    """Prepare the context and render the dovecot.conf file content.

    Args:
        dovecot_users_path: Path to the passwd-file of Dovecot users.
        enable_smtp_auth: Whether SMTP authentication should be enabled.

    Returns:
        str: The rendered content of the `dovecot.conf` file.
    """
    context = {
        "passdb_driver": "passwd-file",
        "passdb_args": f"scheme=CRYPT username_format=%u {dovecot_users_path}",
        # We need to use /var/spool/postfix/private/auth because
        # by default postfix runs chroot'ed in /var/spool/postfix.
        "path": "/var/spool/postfix/private/auth",
        "smtp_auth": enable_smtp_auth,
    }
    return utils.render_jinja2_template(context, "templates/dovecot_conf.tmpl")


def construct_dovecot_user_file_content(smtp_auth_users: list[str]) -> str:
    """Format the list of users into the content for the Dovecot users file.

    Args:
        smtp_auth_users: List of SMTP authentication usernames.

    Returns:
        str: The formatted content for the Dovecot users file.
    """
    return "\n".join(smtp_auth_users) + "\n"
