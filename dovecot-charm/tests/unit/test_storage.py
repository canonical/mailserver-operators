# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
from unittest.mock import PropertyMock, patch

import ops
import ops.testing
import pytest
from ops.model import ModelError
from ops.model import Storage as OpsStorage
from testing import FakeStorageManager, NoOpDovecotSetup, StorageTestDovecotCharm


class _NotInstalledDovecotSetup(NoOpDovecotSetup):
    def is_installed(self) -> bool:
        return False


@pytest.fixture(autouse=True)
def reset_storage_test_charm():
    """Reset StorageTestDovecotCharm class attributes to defaults before each test."""
    StorageTestDovecotCharm._storage = FakeStorageManager()
    StorageTestDovecotCharm._dovecot_setup = NoOpDovecotSetup()
    yield
    StorageTestDovecotCharm._storage = FakeStorageManager()
    StorageTestDovecotCharm._dovecot_setup = NoOpDovecotSetup()


def test_start_uses_saved_dev_path_when_model_error(storage_ctx, base_state):
    """On reboot the start hook must recover LUKS using the saved device path."""
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})
    fake = FakeStorageManager(saved_path="/dev/loop0", is_luks=True)
    StorageTestDovecotCharm._storage = fake

    location_prop = PropertyMock(side_effect=ModelError("storage not provisioned"))
    with (
        patch.object(type(OpsStorage(None, None, None)), "location", location_prop),
        patch("ops._main._Dispatcher.run_any_legacy_hook"),
    ):
        state_out = storage_ctx.run(storage_ctx.on.start(), state_in)

    assert isinstance(state_out.unit_status, ops.ActiveStatus)
    assert len(fake.luks_setup_calls) == 1
    assert fake.luks_setup_calls[0] == ("deadbeef", "/dev/loop0")


def test_storage_attached_luks_auto_provisioning_disabled_unmounted_is_blocked(
    storage_ctx, base_state
):
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(
        base_state,
        config={**base_state.config, "luks-auto-provisioning": False},
        storages={storage},
    )
    StorageTestDovecotCharm._storage = FakeStorageManager(mounted=False)
    state_out = storage_ctx.run(storage_ctx.on.storage_attached(storage), state_in)
    assert isinstance(state_out.unit_status, ops.BlockedStatus)
    assert "mail-data not mounted" in state_out.unit_status.message


def test_storage_attached_luks_auto_provisioning_disabled_mounted_is_active(
    storage_ctx, base_state
):
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(
        base_state,
        config={**base_state.config, "luks-auto-provisioning": False},
        storages={storage},
    )
    StorageTestDovecotCharm._storage = FakeStorageManager(mounted=True)
    state_out = storage_ctx.run(storage_ctx.on.storage_attached(storage), state_in)
    assert isinstance(state_out.unit_status, ops.ActiveStatus)


def test_storage_attached_luks_auto_provisioning_blocks_without_luks_key(storage_ctx, base_state):
    """Missing luks-key with auto-provisioning enabled must immediately block.

    DovecotConfig.from_charm raises ConfigurationError (CharmBlockedError) before
    any storage code is reached — no fake needed.
    """
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(
        base_state,
        config={k: v for k, v in base_state.config.items() if k != "luks-key"},
        secrets=set(),
        storages={storage},
    )
    state_out = storage_ctx.run(storage_ctx.on.storage_attached(storage), state_in)
    assert isinstance(state_out.unit_status, ops.BlockedStatus)


def test_storage_attached_calls_setup_luks_with_key(storage_ctx, base_state):
    """ensure_storage_ready must call setup_luks_storage with the LUKS key from config."""
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})
    fake = FakeStorageManager()
    StorageTestDovecotCharm._storage = fake
    state_out = storage_ctx.run(storage_ctx.on.storage_attached(storage), state_in)
    assert isinstance(state_out.unit_status, ops.ActiveStatus)
    assert len(fake.luks_setup_calls) == 1
    assert fake.luks_setup_calls[0][0] == "deadbeef"


def test_storage_attached_saves_dev_path(storage_ctx, base_state):
    """Dev path must be persisted to disk every time storage-attached fires."""
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})
    fake = FakeStorageManager()
    StorageTestDovecotCharm._storage = fake
    state_out = storage_ctx.run(storage_ctx.on.storage_attached(storage), state_in)
    assert isinstance(state_out.unit_status, ops.ActiveStatus)
    assert len(fake.saved_paths) == 1


def test_start_defers_when_model_error_and_no_saved_path(storage_ctx, base_state):
    """If ModelError and no saved path, LUKS setup must be skipped (not crash)."""
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})
    StorageTestDovecotCharm._storage = FakeStorageManager(saved_path=None)
    StorageTestDovecotCharm._dovecot_setup = _NotInstalledDovecotSetup()

    location_prop = PropertyMock(side_effect=ModelError("storage not provisioned"))
    with (
        patch.object(type(OpsStorage(None, None, None)), "location", location_prop),
        patch("ops._main._Dispatcher.run_any_legacy_hook"),
    ):
        state_out = storage_ctx.run(storage_ctx.on.start(), state_in)
    assert isinstance(state_out.unit_status, ops.MaintenanceStatus)


def test_start_defers_when_device_not_yet_luks(storage_ctx, base_state):
    """If saved path exists but isLuks fails (loop not attached), defer gracefully."""
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})
    StorageTestDovecotCharm._storage = FakeStorageManager(
        saved_path="/dev/disk/by-uuid/aabbccdd", is_luks=False
    )
    StorageTestDovecotCharm._dovecot_setup = _NotInstalledDovecotSetup()

    location_prop = PropertyMock(side_effect=ModelError("storage not provisioned"))
    with (
        patch.object(type(OpsStorage(None, None, None)), "location", location_prop),
        patch("ops._main._Dispatcher.run_any_legacy_hook"),
    ):
        state_out = storage_ctx.run(storage_ctx.on.start(), state_in)
    assert isinstance(state_out.unit_status, ops.MaintenanceStatus)


# --- Storage detaching tests ---


def test_storage_detaching_unmount_and_close(storage_ctx, base_state):
    """teardown_detaching_storage returns early when storage is still present."""
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})
    StorageTestDovecotCharm._storage = FakeStorageManager(mounted=True)
    state_out = storage_ctx.run(storage_ctx.on.storage_detaching(storage), state_in)
    assert isinstance(state_out.unit_status, ops.ActiveStatus)


def test_storage_detaching_not_mounted(storage_ctx, base_state):
    """When storage is gone and not mounted, unit must enter BlockedStatus."""
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})
    StorageTestDovecotCharm._storage = FakeStorageManager(mounted=False)
    with patch("ops.model.StorageMapping.get", return_value=[]):
        state_out = storage_ctx.run(storage_ctx.on.storage_detaching(storage), state_in)
    assert isinstance(state_out.unit_status, ops.BlockedStatus)


def test_storage_detaching_luks_disabled_skips_close(storage_ctx, base_state):
    """With luks-auto-provisioning=False, teardown does not attempt luksClose."""
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(
        base_state,
        config={**base_state.config, "luks-auto-provisioning": False},
        storages={storage},
    )
    StorageTestDovecotCharm._storage = FakeStorageManager(mounted=True)
    state_out = storage_ctx.run(storage_ctx.on.storage_detaching(storage), state_in)
    assert isinstance(state_out.unit_status, ops.ActiveStatus)


def test_storage_detached_sets_blocked_status(storage_ctx, base_state):
    """When storage has fully detached the unit must enter BlockedStatus."""
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})
    StorageTestDovecotCharm._storage = FakeStorageManager(mounted=False)
    with patch("ops.model.StorageMapping.get", return_value=[]):
        state_out = storage_ctx.run(storage_ctx.on.storage_detaching(storage), state_in)
    assert isinstance(state_out.unit_status, ops.BlockedStatus)
    assert "storage is necessary" in state_out.unit_status.message
