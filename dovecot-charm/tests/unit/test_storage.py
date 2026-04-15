# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.
import dataclasses
from unittest.mock import call, patch

import ops
import ops.testing


def test_storage_attached_defer_if_cryptsetup_missing(ctx, base_state):
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})
    with (
        patch("charm.DovecotCharm._install"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
        patch("storage.shutil.which", return_value=None),
        patch("storage.setup_luks_storage") as mock_setup_luks,
    ):
        ctx.run(ctx.on.storage_attached(storage), state_in)
    # When cryptsetup is missing, setup_luks_storage is not called
    mock_setup_luks.assert_not_called()


def test_storage_attached_luks_auto_provisioning_disabled_unmounted_is_blocked(ctx, base_state):
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(
        base_state,
        config={**base_state.config, "luks-auto-provisioning": False},
        storages={storage},
    )
    with (
        patch("charm.DovecotCharm._install"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
        patch("storage._mail_storage_mounted", return_value=False),
        patch("storage.subprocess.run") as mock_run,
    ):
        state_out = ctx.run(ctx.on.storage_attached(storage), state_in)
    mock_run.assert_not_called()
    assert isinstance(state_out.unit_status, ops.BlockedStatus)
    assert "mail-data not mounted" in state_out.unit_status.message


def test_storage_attached_luks_auto_provisioning_disabled_mounted_is_active(ctx, base_state):
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(
        base_state,
        config={**base_state.config, "luks-auto-provisioning": False},
        storages={storage},
    )
    with (
        patch("charm.DovecotCharm._install"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
        patch("charm.shutil.which", return_value="/usr/bin/doveconf"),
        patch("storage._mail_storage_mounted", return_value=True),
        patch("storage.subprocess.run") as mock_run,
    ):
        state_out = ctx.run(ctx.on.storage_attached(storage), state_in)
    mock_run.assert_not_called()
    assert isinstance(state_out.unit_status, ops.ActiveStatus)


def test_storage_attached_luks_auto_provisioning_blocks_without_luks_key(ctx, base_state):
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(
        base_state,
        config={k: v for k, v in base_state.config.items() if k != "luks-key"},
        secrets=set(),
        storages={storage},
    )
    with (
        patch("charm.DovecotCharm._install"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
    ):
        state_out = ctx.run(ctx.on.storage_attached(storage), state_in)
    assert isinstance(state_out.unit_status, ops.BlockedStatus)


def test_storage_attached_calls_setup_luks_with_key(ctx, base_state):
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})
    with (
        patch("charm.DovecotCharm._install"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
        patch("charm.shutil.which", return_value="/usr/bin/doveconf"),
        patch("storage.shutil.which", return_value="/usr/sbin/cryptsetup"),
        patch("ops._main._Dispatcher.run_any_legacy_hook"),
        patch("storage._is_luks_device", return_value=True),
        patch("storage._save_storage_dev_path"),
        patch("storage.setup_luks_storage") as mock_setup_luks,
    ):
        ctx.run(ctx.on.storage_attached(storage), state_in)
    mock_setup_luks.assert_called_once()
    key_arg = mock_setup_luks.call_args[0][0]
    assert key_arg == "deadbeef"


def test_storage_attached_saves_dev_path(ctx, base_state):
    """Dev path must be persisted to disk every time storage-attached fires."""
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})
    with (
        patch("charm.DovecotCharm._install"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
        patch("charm.shutil.which", return_value="/usr/bin/doveconf"),
        patch("storage.shutil.which", return_value="/usr/sbin/cryptsetup"),
        patch("ops._main._Dispatcher.run_any_legacy_hook"),
        patch("storage._is_luks_device", return_value=True),
        patch("storage.setup_luks_storage"),
        patch("storage._save_storage_dev_path") as mock_save,
    ):
        ctx.run(ctx.on.storage_attached(storage), state_in)
    mock_save.assert_called_once()


def test_start_uses_saved_dev_path_when_model_error(ctx, base_state):
    """On reboot the start hook must recover LUKS using the saved device path."""
    from unittest.mock import PropertyMock

    from ops.model import ModelError
    from ops.model import Storage as OpsStorage

    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})

    location_prop = PropertyMock(side_effect=ModelError("storage not provisioned"))
    with (
        patch("charm.DovecotCharm._install"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
        patch("charm.shutil.which", return_value="/usr/bin/doveconf"),
        patch("storage.shutil.which", return_value="/usr/sbin/cryptsetup"),
        patch("ops._main._Dispatcher.run_any_legacy_hook"),
        patch.object(type(OpsStorage(None, None, None)), "location", location_prop),
        patch("storage._load_storage_dev_path", return_value="/dev/loop0") as mock_load,
        # Device is a LUKS container (fully attached and ready)
        patch("storage._is_luks_device", return_value=True),
        patch("storage._save_storage_dev_path"),
        patch("storage.setup_luks_storage") as mock_setup_luks,
    ):
        ctx.run(ctx.on.start(), state_in)
    mock_load.assert_called_once()
    mock_setup_luks.assert_called_once()
    assert mock_setup_luks.call_args[0][1] == "/dev/loop0"


def test_start_defers_when_model_error_and_no_saved_path(ctx, base_state):
    """If ModelError and no saved path, LUKS setup must be skipped (not crash)."""
    from unittest.mock import PropertyMock

    from ops.model import ModelError
    from ops.model import Storage as OpsStorage

    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})

    location_prop = PropertyMock(side_effect=ModelError("storage not provisioned"))
    with (
        patch("charm.DovecotCharm._install"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
        patch("charm.shutil.which", return_value="/usr/bin/doveconf"),
        patch("storage.shutil.which", return_value="/usr/sbin/cryptsetup"),
        patch("ops._main._Dispatcher.run_any_legacy_hook"),
        patch.object(type(OpsStorage(None, None, None)), "location", location_prop),
        patch("storage._load_storage_dev_path", return_value=None),
        patch("storage.setup_luks_storage") as mock_setup_luks,
    ):
        ctx.run(ctx.on.start(), state_in)
    mock_setup_luks.assert_not_called()


def test_start_defers_when_device_not_yet_luks(ctx, base_state):
    """If saved path exists but isLuks fails (loop not attached), defer gracefully."""
    from unittest.mock import PropertyMock

    from ops.model import ModelError
    from ops.model import Storage as OpsStorage

    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})

    location_prop = PropertyMock(side_effect=ModelError("storage not provisioned"))
    with (
        patch("charm.DovecotCharm._install"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
        patch("charm.shutil.which", return_value="/usr/bin/doveconf"),
        patch("storage.shutil.which", return_value="/usr/sbin/cryptsetup"),
        patch("ops._main._Dispatcher.run_any_legacy_hook"),
        patch.object(type(OpsStorage(None, None, None)), "location", location_prop),
        patch("storage._load_storage_dev_path", return_value="/dev/disk/by-uuid/aabbccdd"),
        # Loop not yet attached — isLuks returns False
        patch("storage._is_luks_device", return_value=False),
        patch("storage.setup_luks_storage") as mock_setup_luks,
    ):
        ctx.run(ctx.on.start(), state_in)
    mock_setup_luks.assert_not_called()


# --- Storage detaching tests ---


def test_storage_detaching_unmount_and_close(ctx, base_state):
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})

    with (
        patch("charm.DovecotCharm._install"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
        patch("storage._mail_storage_mounted", return_value=True),
        patch("storage.os.path.exists", return_value=True),
        patch("storage._is_luks_device", return_value=False),
        patch("storage._save_storage_dev_path"),
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
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
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
        config={**base_state.config, "luks-auto-provisioning": False},
        storages={storage},
    )
    with (
        patch("charm.DovecotCharm._install"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
        patch("storage.shutil.which", return_value=None),
        patch("storage._mail_storage_mounted", return_value=True),
        patch("storage.os.path.exists", return_value=True),
        patch("storage.subprocess.run") as mock_run,
    ):
        ctx.run(ctx.on.storage_detaching(storage), state_in)
    assert call(["/usr/bin/umount", "/srv/mail"], check=True) not in mock_run.call_args_list


def test_storage_detached_sets_blocked_status(ctx, base_state):
    """When storage has fully detached the unit must enter BlockedStatus."""
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})
    with (
        patch("charm.DovecotCharm._install"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
        patch("storage._mail_storage_mounted", return_value=False),
        patch("storage.os.path.exists", return_value=False),
        patch("storage._is_luks_device", return_value=False),
        patch("storage.subprocess.run"),
        # Simulate the storage being gone when teardown_detaching_storage checks
        patch("ops.model.StorageMapping.get", return_value=[]),
    ):
        state_out = ctx.run(ctx.on.storage_detaching(storage), state_in)
    assert isinstance(state_out.unit_status, ops.BlockedStatus)
    assert "storage is necessary" in state_out.unit_status.message
