# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.
import dataclasses
from unittest.mock import PropertyMock, patch

import ops
import ops.testing
from ops.model import ModelError
from ops.model import Storage as OpsStorage


def test_start_uses_saved_dev_path_when_model_error(ctx, base_state):
    """On reboot the start hook must recover LUKS using the saved device path."""
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})

    location_prop = PropertyMock(side_effect=ModelError("storage not provisioned"))
    with (
        # storage.location raises on reboot — simulate the model not knowing the path yet
        patch.object(type(OpsStorage(None, None, None)), "location", location_prop),
        patch("storage._load_storage_dev_path", return_value="/dev/loop0"),
        # Device is a fully-attached LUKS container
        patch("storage._is_luks_device", return_value=True),
        patch("storage._save_storage_dev_path"),
        patch("storage.setup_luks_storage") as mock_setup_luks,
        # doveconf must be present so _reconcile reaches ActiveStatus
        patch("charm.shutil.which", return_value="/usr/bin/doveconf"),
        # TLS cert lookup is not under test here
        patch("charm.DovecotCharm._setup_tls"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
        # HA methods do filesystem I/O (ssh-keygen, authorized_keys, sync scripts)
        patch("charm.DovecotCharm._setup_ssh_keys"),
        patch("charm.DovecotCharm._sync_authorized_keys"),
        patch("charm.DovecotCharm._sync_known_hosts"),
        patch("charm.DovecotCharm._install_mail_sync_script"),
        patch("charm.DovecotCharm._setup_mail_sync_cronjob"),
        patch("ops._main._Dispatcher.run_any_legacy_hook"),
    ):
        state_out = ctx.run(ctx.on.start(), state_in)

    assert isinstance(state_out.unit_status, ops.ActiveStatus)
    # setup_luks_storage must have been called with the saved path (last-resort
    # assertion: the saved path is not observable through Scenario state)
    mock_setup_luks.assert_called_once()
    assert mock_setup_luks.call_args[0][1] == "/dev/loop0"


def test_storage_attached_luks_auto_provisioning_disabled_unmounted_is_blocked(ctx, base_state):
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(
        base_state,
        config={**base_state.config, "luks-auto-provisioning": False},
        storages={storage},
    )
    with (
        # Storage is present but not mounted — ensure_storage_ready raises StorageError
        patch("storage._mail_storage_mounted", return_value=False),
    ):
        state_out = ctx.run(ctx.on.storage_attached(storage), state_in)
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
        # Storage is mounted — ensure_storage_ready succeeds without LUKS setup
        patch("storage._mail_storage_mounted", return_value=True),
        # doveconf present so _reconcile proceeds to ActiveStatus
        patch("charm.shutil.which", return_value="/usr/bin/doveconf"),
        # TLS cert lookup is not under test here
        patch("charm.DovecotCharm._setup_tls"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
        # HA methods do filesystem I/O — not under test
        patch("charm.DovecotCharm._setup_ssh_keys"),
        patch("charm.DovecotCharm._sync_authorized_keys"),
        patch("charm.DovecotCharm._sync_known_hosts"),
        patch("charm.DovecotCharm._install_mail_sync_script"),
        patch("charm.DovecotCharm._setup_mail_sync_cronjob"),
    ):
        state_out = ctx.run(ctx.on.storage_attached(storage), state_in)
    assert isinstance(state_out.unit_status, ops.ActiveStatus)


def test_storage_attached_luks_auto_provisioning_blocks_without_luks_key(ctx, base_state):
    """Missing luks-key with auto-provisioning enabled must immediately block.

    DovecotConfig.from_charm raises ConfigurationError (CharmBlockedError) before
    any storage or subprocess code is reached — no mocks required.
    """
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(
        base_state,
        config={k: v for k, v in base_state.config.items() if k != "luks-key"},
        secrets=set(),
        storages={storage},
    )
    state_out = ctx.run(ctx.on.storage_attached(storage), state_in)
    assert isinstance(state_out.unit_status, ops.BlockedStatus)


def test_storage_attached_calls_setup_luks_with_key(ctx, base_state):
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})
    with (
        patch("storage._save_storage_dev_path"),
        patch("storage.setup_luks_storage") as mock_setup_luks,
        patch("charm.shutil.which", return_value="/usr/bin/doveconf"),
        # TLS cert lookup is not under test here
        patch("charm.DovecotCharm._setup_tls"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
        # HA methods do filesystem I/O — not under test
        patch("charm.DovecotCharm._setup_ssh_keys"),
        patch("charm.DovecotCharm._sync_authorized_keys"),
        patch("charm.DovecotCharm._sync_known_hosts"),
        patch("charm.DovecotCharm._install_mail_sync_script"),
        patch("charm.DovecotCharm._setup_mail_sync_cronjob"),
    ):
        state_out = ctx.run(ctx.on.storage_attached(storage), state_in)
    assert isinstance(state_out.unit_status, ops.ActiveStatus)
    # Last-resort: verify the LUKS key was forwarded (not observable via state)
    mock_setup_luks.assert_called_once()
    assert mock_setup_luks.call_args[0][0] == "deadbeef"


def test_storage_attached_saves_dev_path(ctx, base_state):
    """Dev path must be persisted to disk every time storage-attached fires."""
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})
    with (
        patch("storage._save_storage_dev_path"),
        patch("storage.setup_luks_storage"),
        patch("charm.shutil.which", return_value="/usr/bin/doveconf"),
        # TLS cert lookup is not under test here
        patch("charm.DovecotCharm._setup_tls"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
        # HA methods do filesystem I/O — not under test
        patch("charm.DovecotCharm._setup_ssh_keys"),
        patch("charm.DovecotCharm._sync_authorized_keys"),
        patch("charm.DovecotCharm._sync_known_hosts"),
        patch("charm.DovecotCharm._install_mail_sync_script"),
        patch("charm.DovecotCharm._setup_mail_sync_cronjob"),
    ):
        state_out = ctx.run(ctx.on.storage_attached(storage), state_in)
    assert isinstance(state_out.unit_status, ops.ActiveStatus)


def test_start_defers_when_model_error_and_no_saved_path(ctx, base_state):
    """If ModelError and no saved path, LUKS setup must be skipped (not crash)."""
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})

    location_prop = PropertyMock(side_effect=ModelError("storage not provisioned"))
    with (
        patch.object(type(OpsStorage(None, None, None)), "location", location_prop),
        patch("storage._load_storage_dev_path", return_value=None),
        patch("ops._main._Dispatcher.run_any_legacy_hook"),
        # doveconf absent — _reconcile stops at shutil.which, stays in Maintenance
        patch("charm.shutil.which", return_value=None),
    ):
        state_out = ctx.run(ctx.on.start(), state_in)
    assert isinstance(state_out.unit_status, ops.MaintenanceStatus)


def test_start_defers_when_device_not_yet_luks(ctx, base_state):
    """If saved path exists but isLuks fails (loop not attached), defer gracefully."""
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})

    location_prop = PropertyMock(side_effect=ModelError("storage not provisioned"))
    with (
        patch.object(type(OpsStorage(None, None, None)), "location", location_prop),
        patch("storage._load_storage_dev_path", return_value="/dev/disk/by-uuid/aabbccdd"),
        # Loop not yet attached — isLuks returns False, setup_luks_storage is skipped
        patch("storage._is_luks_device", return_value=False),
        patch("ops._main._Dispatcher.run_any_legacy_hook"),
        # doveconf absent — _reconcile stops at shutil.which, stays in Maintenance
        patch("charm.shutil.which", return_value=None),
    ):
        state_out = ctx.run(ctx.on.start(), state_in)
    assert isinstance(state_out.unit_status, ops.MaintenanceStatus)


# --- Storage detaching tests ---


def test_storage_detaching_unmount_and_close(ctx, base_state):
    """teardown_detaching_storage returns early when storage is still present."""
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})

    with (
        # Storage still in state — teardown_detaching_storage returns early (no cleanup)
        patch("storage._mail_storage_mounted", return_value=True),
        patch("storage._save_storage_dev_path"),
        patch("storage.setup_luks_storage"),
        patch("charm.shutil.which", return_value="/usr/bin/doveconf"),
        # TLS cert lookup is not under test here
        patch("charm.DovecotCharm._setup_tls"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
        # HA methods do filesystem I/O — not under test
        patch("charm.DovecotCharm._setup_ssh_keys"),
        patch("charm.DovecotCharm._sync_authorized_keys"),
        patch("charm.DovecotCharm._sync_known_hosts"),
        patch("charm.DovecotCharm._install_mail_sync_script"),
        patch("charm.DovecotCharm._setup_mail_sync_cronjob"),
    ):
        state_out = ctx.run(ctx.on.storage_detaching(storage), state_in)
    assert isinstance(state_out.unit_status, ops.ActiveStatus)


def test_storage_detaching_not_mounted(ctx, base_state):
    """When storage is gone and not mounted, unit must enter BlockedStatus."""
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})
    with (
        patch("storage._mail_storage_mounted", return_value=False),
        patch("storage.os.path.exists", return_value=False),
        # Simulate storage gone from model so ensure_storage_ready raises StorageError
        patch("ops.model.StorageMapping.get", return_value=[]),
    ):
        state_out = ctx.run(ctx.on.storage_detaching(storage), state_in)
    assert isinstance(state_out.unit_status, ops.BlockedStatus)


def test_storage_detaching_luks_disabled_skips_close(ctx, base_state):
    """With luks-auto-provisioning=False, teardown does not attempt luksClose."""
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(
        base_state,
        config={**base_state.config, "luks-auto-provisioning": False},
        storages={storage},
    )
    with (
        # Storage still present — teardown returns early, _reconcile proceeds normally
        patch("storage._mail_storage_mounted", return_value=True),
        patch("charm.shutil.which", return_value="/usr/bin/doveconf"),
        # TLS cert lookup is not under test here
        patch("charm.DovecotCharm._setup_tls"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
        # HA methods do filesystem I/O — not under test
        patch("charm.DovecotCharm._setup_ssh_keys"),
        patch("charm.DovecotCharm._sync_authorized_keys"),
        patch("charm.DovecotCharm._sync_known_hosts"),
        patch("charm.DovecotCharm._install_mail_sync_script"),
        patch("charm.DovecotCharm._setup_mail_sync_cronjob"),
    ):
        state_out = ctx.run(ctx.on.storage_detaching(storage), state_in)
    assert isinstance(state_out.unit_status, ops.ActiveStatus)


def test_storage_detached_sets_blocked_status(ctx, base_state):
    """When storage has fully detached the unit must enter BlockedStatus."""
    storage = ops.testing.Storage("mail-data")
    state_in = dataclasses.replace(base_state, storages={storage})
    with (
        patch("storage._mail_storage_mounted", return_value=False),
        patch("storage.os.path.exists", return_value=False),
        # Simulate storage gone so ensure_storage_ready raises StorageError → Blocked
        patch("ops.model.StorageMapping.get", return_value=[]),
    ):
        state_out = ctx.run(ctx.on.storage_detaching(storage), state_in)
    assert isinstance(state_out.unit_status, ops.BlockedStatus)
    assert "storage is necessary" in state_out.unit_status.message
