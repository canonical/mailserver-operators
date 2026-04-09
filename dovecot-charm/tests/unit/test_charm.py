# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.
import dataclasses
from subprocess import CalledProcessError  # nosec
from unittest.mock import MagicMock, patch

import ops.testing
import pytest
from ops.testing import ActiveStatus, BlockedStatus


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


# --- Storage handler tests ---


def test_storage_attached_defer_if_cryptsetup_missing(ctx, base_state):
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})
    with patch("charm.shutil.which", return_value=None):
        state_out = ctx.run(ctx.on.storage_attached(storage), state_in)
    # When cryptsetup is missing, event is deferred — status not changed to Active
    assert state_out.unit_status != ActiveStatus()


def test_storage_attached_setup_luks_not_called_when_cryptsetup_missing(ctx, base_state):
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})
    with (
        patch("charm.shutil.which", return_value=None),
        patch("charm.DovecotCharm._setup_luks_storage") as mock_setup_luks,
    ):
        ctx.run(ctx.on.storage_attached(storage), state_in)
    mock_setup_luks.assert_not_called()


def test_storage_attached_manage_luks_disabled_waits_for_mount(ctx, base_state):
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(
        base_state,
        config={**base_state.config, "manage-luks": False},
        storages={storage},
    )
    with patch("charm.os.path.ismount", return_value=False):
        state_out = ctx.run(ctx.on.storage_attached(storage), state_in)
    assert state_out.unit_status == BlockedStatus("mail-data not mounted; manage-luks disabled")


def test_storage_attached_manage_luks_disabled_active(ctx, base_state):
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(
        base_state,
        config={**base_state.config, "manage-luks": False},
        storages={storage},
    )
    with patch("charm.os.path.ismount", return_value=True):
        state_out = ctx.run(ctx.on.storage_attached(storage), state_in)
    assert state_out.unit_status == ActiveStatus()


# --- Storage detaching tests ---


def test_storage_detaching_unmount_and_close(ctx, base_state):
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})
    with (
        patch("charm.os.path.ismount", return_value=True),
        patch("charm.os.path.exists", return_value=True),
        patch("charm.subprocess.run") as mock_run,
    ):
        ctx.run(ctx.on.storage_detaching(storage), state_in)
    mock_run.assert_any_call(["umount", "/srv/mail"], check=True)
    mock_run.assert_any_call(["cryptsetup", "luksClose", "mail-data"], check=True)


def test_storage_detaching_not_mounted(ctx, base_state):
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})
    with (
        patch("charm.os.path.ismount", return_value=False),
        patch("charm.os.path.exists", return_value=False),
        patch("charm.subprocess.run") as mock_run,
    ):
        ctx.run(ctx.on.storage_detaching(storage), state_in)
    mock_run.assert_not_called()


def test_storage_detaching_luks_disabled_skips_close(ctx, base_state):
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(
        base_state,
        config={**base_state.config, "manage-luks": False},
        storages={storage},
    )
    with (
        patch("charm.os.path.ismount", return_value=True),
        patch("charm.os.path.exists", return_value=True),
        patch("charm.subprocess.run") as mock_run,
    ):
        ctx.run(ctx.on.storage_detaching(storage), state_in)
    mock_run.assert_called_once_with(["umount", "/srv/mail"], check=True)


# --- Update-status tests ---


def test_update_status_luks_disabled_mounted(ctx, base_state):
    state_in = dataclasses.replace(base_state, config={**base_state.config, "manage-luks": False})
    with patch("charm.os.path.ismount", return_value=True):
        state_out = ctx.run(ctx.on.update_status(), state_in)
    assert state_out.unit_status == ActiveStatus()


def test_update_status_luks_disabled_not_mounted(ctx, base_state):
    state_in = dataclasses.replace(base_state, config={**base_state.config, "manage-luks": False})
    with patch("charm.os.path.ismount", return_value=False):
        state_out = ctx.run(ctx.on.update_status(), state_in)
    assert state_out.unit_status == BlockedStatus("mail-data not mounted; manage-luks disabled")
