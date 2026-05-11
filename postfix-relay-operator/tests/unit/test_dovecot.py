# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""dovecot service unit tests."""

from pathlib import Path

import pytest

import dovecot


@pytest.mark.parametrize(
    ("enable_smtp_auth", "expected_filename"),
    [
        pytest.param(True, "dovecot_config", id="smtp_auth_enabled"),
        pytest.param(False, "dovecot_config_auth_disabled", id="smtp_auth_disabled"),
    ],
)
def test_construct_dovecot_config_file_content(
    enable_smtp_auth: bool, expected_filename: str
) -> None:
    """
    arrange: Given different values for enabling SMTP auth.
    act: Call construct_dovecot_config_file_content.
    assert: The Jinja2 renderer is called with the correctly formatted context.
    """
    dovecot_users_path = "/etc/dovecot/users"
    expected_path = Path(__file__).parent / "files" / expected_filename
    expected = expected_path.read_text()

    result = dovecot.construct_dovecot_config_file_content(dovecot_users_path, enable_smtp_auth)

    assert result == expected


def test_construct_dovecot_user_file_content() -> None:
    """
    arrange: Given a list of SMTP auth users.
    act: Call construct_dovecot_user_file_content.
    assert: The returned string is correctly formatted.
    """
    smtp_auth_users = [
        "myuser1:$1$bPb0IPiM$kmrSMZkZvICKKHXu66daQ.",
        "myuser2:$6$3r//F36qLB/J8rUfIIndaDtkxeb5iR3gs1uBn9fNyJDD1",
    ]
    expected_path = Path(__file__).parent / "files/dovecot_users"
    expected = expected_path.read_text()

    result = dovecot.construct_dovecot_user_file_content(smtp_auth_users)

    assert result == expected
