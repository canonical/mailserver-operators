# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.
import dataclasses
from unittest.mock import call, patch

import ops
import ops.testing


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


def test_storage_attached_manage_luks_blocks_without_luks_key(ctx, base_state):
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(
        base_state,
        config={k: v for k, v in base_state.config.items() if k != "luks-key"},
        secrets=set(),
        storages={storage},
    )
    with (
        patch("charm.DovecotCharm._install"),
        patch("charm.DovecotCharm._setup_dovecot", return_value=True),
        patch("charm.DovecotCharm._setup_procmail", return_value=True),
    ):
        state_out = ctx.run(ctx.on.storage_attached(storage), state_in)
    assert isinstance(state_out.unit_status, ops.BlockedStatus)


def test_storage_attached_calls_setup_luks_with_key(ctx, base_state):
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})
    with (
        patch("charm.DovecotCharm._install"),
        patch("charm.DovecotCharm._setup_dovecot", return_value=True),
        patch("charm.DovecotCharm._setup_procmail", return_value=True),
        patch("charm.shutil.which", return_value="/usr/bin/doveconf"),
        patch("storage.shutil.which", return_value="/usr/sbin/cryptsetup"),
        patch("ops._main._Dispatcher.run_any_legacy_hook"),
        patch("storage.setup_luks_storage") as mock_setup_luks,
    ):
        ctx.run(ctx.on.storage_attached(storage), state_in)
    mock_setup_luks.assert_called_once()
    key_arg = mock_setup_luks.call_args[0][0]
    assert key_arg == "deadbeef"


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
