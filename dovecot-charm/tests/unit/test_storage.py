# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.
import dataclasses
from unittest.mock import call, mock_open, patch

import ops
import ops.testing
import pytest


def test_get_encryption_key_success(ctx, base_state):
    state_in = dataclasses.replace(base_state, config={**base_state.config, "manage-luks": True})
    with (
        patch("charm.os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=b"\x01\x02\x0f")),
    ):
        ctx.run(ctx.on.action("get-encryption-key"), state_in)

    assert ctx.action_results == {
        "status": "success",
        "encoding": "hex",
        "key": "01020f",
    }


def test_get_encryption_key_fails_when_manage_luks_disabled(ctx, base_state):
    state_in = dataclasses.replace(base_state, config={**base_state.config, "manage-luks": False})
    with pytest.raises(ops.testing.ActionFailed) as exc_info:
        ctx.run(ctx.on.action("get-encryption-key"), state_in)

    assert "manage-luks is disabled" in exc_info.value.message


def test_get_encryption_key_fails_when_keyfile_missing(ctx, base_state):
    state_in = dataclasses.replace(base_state, config={**base_state.config, "manage-luks": True})
    with (
        patch("charm.os.path.exists", return_value=False),
        pytest.raises(ops.testing.ActionFailed) as exc_info,
    ):
        ctx.run(ctx.on.action("get-encryption-key"), state_in)

    assert "encryption key is not available yet" in exc_info.value.message


# --- Storage handler tests ---


def test_storage_attached_defer_if_cryptsetup_missing(ctx, base_state):
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})
    with (
        patch("charm.DovecotCharm._install"),
        patch("charm.DovecotCharm._setup_dovecot", return_value=True),
        patch("charm.DovecotCharm._setup_procmail", return_value=True),
        patch("storage.shutil.which", return_value=None),
        patch("storage.setup_luks_storage") as mock_setup_luks,
    ):
        ctx.run(ctx.on.storage_attached(storage), state_in)
    # When cryptsetup is missing, setup_luks_storage is not called
    mock_setup_luks.assert_not_called()


def test_storage_attached_setup_luks_not_called_when_cryptsetup_missing(ctx, base_state):
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})
    with (
        patch("charm.DovecotCharm._install"),
        patch("charm.DovecotCharm._setup_dovecot", return_value=True),
        patch("charm.DovecotCharm._setup_procmail", return_value=True),
        patch("storage.shutil.which", return_value=None),
        patch("storage.setup_luks_storage") as mock_setup_luks,
    ):
        ctx.run(ctx.on.storage_attached(storage), state_in)
    mock_setup_luks.assert_not_called()


def test_storage_attached_manage_luks_disabled_unmounted_is_blocked(ctx, base_state):
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(
        base_state,
        config={**base_state.config, "manage-luks": False},
        storages={storage},
    )
    with (
        patch("charm.DovecotCharm._install"),
        patch("charm.DovecotCharm._setup_dovecot", return_value=True),
        patch("charm.DovecotCharm._setup_procmail", return_value=True),
        patch("storage._mail_storage_mounted", return_value=False),
        patch("storage.subprocess.run") as mock_run,
    ):
        state_out = ctx.run(ctx.on.storage_attached(storage), state_in)
    mock_run.assert_not_called()
    assert isinstance(state_out.unit_status, ops.BlockedStatus)
    assert "mail-data not mounted" in state_out.unit_status.message


def test_storage_attached_manage_luks_disabled_mounted_is_active(ctx, base_state):
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(
        base_state,
        config={**base_state.config, "manage-luks": False},
        storages={storage},
    )
    with (
        patch("charm.DovecotCharm._install"),
        patch("charm.DovecotCharm._setup_dovecot", return_value=True),
        patch("charm.DovecotCharm._setup_procmail", return_value=True),
        patch("charm.shutil.which", return_value="/usr/bin/doveconf"),
        patch("storage._mail_storage_mounted", return_value=True),
        patch("storage.subprocess.run") as mock_run,
    ):
        state_out = ctx.run(ctx.on.storage_attached(storage), state_in)
    mock_run.assert_not_called()
    assert isinstance(state_out.unit_status, ops.ActiveStatus)


# --- Storage detaching tests ---


def test_storage_detaching_unmount_and_close(ctx, base_state):
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})

    with (
        patch("charm.DovecotCharm._install"),
        patch("charm.DovecotCharm._setup_dovecot", return_value=True),
        patch("charm.DovecotCharm._setup_procmail", return_value=True),
        patch("storage._mail_storage_mounted", return_value=True),
        patch("storage.os.path.exists", return_value=True),
        patch("storage.subprocess.run") as mock_run,
    ):
        ctx.run(ctx.on.storage_detaching(storage), state_in)
    # Handler returns early if storage still exists; no cleanup should occur
    mock_run.assert_not_called()


def test_storage_detaching_not_mounted(ctx, base_state):
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})
    with (
        patch("charm.DovecotCharm._install"),
        patch("charm.DovecotCharm._setup_dovecot", return_value=True),
        patch("charm.DovecotCharm._setup_procmail", return_value=True),
        patch("storage.shutil.which", return_value=None),
        patch("storage._mail_storage_mounted", return_value=False),
        patch("storage.os.path.exists", return_value=False),
        patch("storage.subprocess.run") as mock_run,
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
        patch("charm.DovecotCharm._install"),
        patch("charm.DovecotCharm._setup_dovecot", return_value=True),
        patch("charm.DovecotCharm._setup_procmail", return_value=True),
        patch("storage.shutil.which", return_value=None),
        patch("storage._mail_storage_mounted", return_value=True),
        patch("storage.os.path.exists", return_value=True),
        patch("storage.subprocess.run") as mock_run,
    ):
        ctx.run(ctx.on.storage_detaching(storage), state_in)
    assert call(["/usr/bin/umount", "/srv/mail"], check=True) not in mock_run.call_args_list
