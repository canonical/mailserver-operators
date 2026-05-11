# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from subprocess import CalledProcessError  # nosec
from unittest.mock import MagicMock, patch

import ops.testing
import pytest


def test_open_ports(ctx, base_state):
    with (
        patch("charm.DovecotCharm._install"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
    ):
        state_out = ctx.run(ctx.on.config_changed(), base_state)

    expected = {ops.testing.TCPPort(p) for p in [143, 993, 110, 995, 4190, 9900]}
    assert state_out.opened_ports == expected


# --- Clear-queue action tests ---


def test_clear_queue_deferred(ctx, base_state):
    mock_result = MagicMock(stdout="cleared")
    with patch("charm.subprocess.run", return_value=mock_result) as mock_run:
        ctx.run(
            ctx.on.action("clear-queue", params={"queue": "deferred"}),
            base_state,
        )
    mock_run.assert_called_once_with(
        ["postsuper", "-d", "ALL", "deferred"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert ctx.action_results == {"status": "success", "output": "cleared"}


def test_clear_queue_all(ctx, base_state):
    mock_result = MagicMock(stdout="cleared")
    with patch("charm.subprocess.run", return_value=mock_result) as mock_run:
        ctx.run(
            ctx.on.action("clear-queue", params={"queue": "all"}),
            base_state,
        )
    mock_run.assert_called_once_with(
        ["postsuper", "-d", "ALL"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert ctx.action_results == {"status": "success", "output": "cleared"}


def test_clear_queue_failure(ctx, base_state):
    with (
        patch(
            "charm.subprocess.run",
            side_effect=CalledProcessError(1, "postsuper", stderr="error msg"),
        ),
        pytest.raises(ops.testing.ActionFailed) as exc_info,
    ):
        ctx.run(
            ctx.on.action("clear-queue", params={"queue": "deferred"}),
            base_state,
        )
    assert "postsuper" in exc_info.value.message


# --- create-mail-user action tests ---


def test_create_mail_user_action_creates_primary_and_mailbox_user(ctx, base_state):
    """create-mail-user creates missing users, groups and passwords."""
    with (
        patch(
            "charm.getpwnam",
            side_effect=[KeyError("e2euser"), KeyError("e2euser@example.com")],
        ),
        patch("charm.subprocess.run", return_value=MagicMock(returncode=0)),
    ):
        ctx.run(
            ctx.on.action(
                "create-mail-user",
                params={
                    "username": "e2euser",
                    "password": "secret",
                    "mailbox-user": "e2euser@example.com",
                },
            ),
            base_state,
        )

    assert ctx.action_results["status"] == "success"
    assert ctx.action_results["created"] == "e2euser,e2euser@example.com"
    assert ctx.action_results["updated"] == ""


def test_create_mail_user_action_updates_existing_user(ctx, base_state):
    """create-mail-user updates password/group for existing users."""
    existing_user = object()
    with (
        patch("charm.getpwnam", return_value=existing_user),
        patch("charm.subprocess.run", return_value=MagicMock(returncode=0)),
    ):
        ctx.run(
            ctx.on.action(
                "create-mail-user",
                params={
                    "username": "e2euser",
                    "password": "secret",
                },
            ),
            base_state,
        )

    assert ctx.action_results["status"] == "success"
    assert ctx.action_results["created"] == ""
    assert ctx.action_results["updated"] == "e2euser"


def test_create_mail_user_action_requires_username(ctx, base_state):
    """create-mail-user fails fast when username is missing."""
    with pytest.raises(ops.testing.ActionFailed) as exc_info:
        ctx.run(
            ctx.on.action(
                "create-mail-user",
                params={
                    "username": "",
                    "password": "secret",
                },
            ),
            base_state,
        )
    assert "username" in exc_info.value.message


def test_create_mail_user_action_requires_password(ctx, base_state):
    """create-mail-user fails fast when password is missing."""
    with pytest.raises(ops.testing.ActionFailed) as exc_info:
        ctx.run(
            ctx.on.action(
                "create-mail-user",
                params={
                    "username": "e2euser",
                    "password": "",
                },
            ),
            base_state,
        )
    assert "password" in exc_info.value.message
