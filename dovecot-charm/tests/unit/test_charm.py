# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
from subprocess import CalledProcessError
from unittest.mock import MagicMock, patch

import pytest
import ops.testing
from ops.model import ActiveStatus, BlockedStatus

# --- Config validation tests ---


def test_config_missing_mailname_blocks(ctx, base_state):
    state_in = dataclasses.replace(base_state, config={**base_state.config, "mailname": ""})
    with patch("charm.DovecotCharm._install"):
        state_out = ctx.run(ctx.on.config_changed(), state_in)
    assert state_out.unit_status == BlockedStatus("mailname is required")


def test_config_missing_postmaster_blocks(ctx, base_state):
    state_in = dataclasses.replace(
        base_state, config={**base_state.config, "postmaster-address": ""}
    )
    with patch("charm.DovecotCharm._install"):
        state_out = ctx.run(ctx.on.config_changed(), state_in)
    assert state_out.unit_status == BlockedStatus("postmaster-address is required")


def test_config_missing_cron_mailto_blocks(ctx, base_state):
    state_in = dataclasses.replace(base_state, config={**base_state.config, "cron-mailto": ""})
    with patch("charm.DovecotCharm._install"):
        state_out = ctx.run(ctx.on.config_changed(), state_in)
    assert state_out.unit_status == BlockedStatus("cron-mailto is required")


def test_config_missing_primary_unit_blocks(ctx, base_state):
    state_in = dataclasses.replace(base_state, config={**base_state.config, "primary-unit": ""})
    with patch("charm.DovecotCharm._install"):
        state_out = ctx.run(ctx.on.config_changed(), state_in)
    assert state_out.unit_status == BlockedStatus("primary-unit is required")


# --- Install flow tests ---


def test_config_valid_calls_install(ctx, base_state):
    with patch("charm.DovecotCharm._install") as mock_install:
        ctx.run(ctx.on.config_changed(), base_state)
    mock_install.assert_called()


def test_on_install_valid_config(ctx, base_state):
    with patch("charm.DovecotCharm._install"):
        state_out = ctx.run(ctx.on.install(), base_state)
    assert state_out.unit_status == ActiveStatus()


def test_on_install_invalid_config_does_not_install(ctx, base_state):
    state_in = dataclasses.replace(base_state, config={**base_state.config, "mailname": ""})
    with patch("charm.DovecotCharm._install") as mock_install:
        ctx.run(ctx.on.install(), state_in)
    mock_install.assert_not_called()


def test_on_config_changed_calls_install(ctx, base_state):
    with patch("charm.DovecotCharm._install") as mock_install:
        state_out = ctx.run(ctx.on.config_changed(), base_state)
    mock_install.assert_called()
    assert state_out.unit_status == ActiveStatus()


def test_open_ports(ctx, base_state):
    def fake_install(self):
        self._open_ports()

    with patch("charm.DovecotCharm._install", fake_install):
        state_out = ctx.run(ctx.on.config_changed(), base_state)

    expected = {ops.testing.TCPPort(p) for p in [143, 993, 110, 995, 4190, 9900]}
    assert state_out.opened_ports == expected


def test_install_calls_all_setup_steps(ctx, base_state):
    with (
        patch("charm.apt") as mock_apt,
        patch("charm.shutil.copy") as mock_copy,
        patch("charm.DovecotCharm._open_ports") as mock_open_ports,
        patch("charm.DovecotCharm._setup_dovecot") as mock_dovecot,
        patch("charm.DovecotCharm._setup_procmail") as mock_procmail,
    ):
        ctx.run(ctx.on.install(), base_state)

    mock_apt.update.assert_called_once()
    mock_apt.add_package.assert_called_once()
    mock_copy.assert_called_once_with("/etc/hostname", "/etc/mailname")
    mock_open_ports.assert_called_once()
    mock_dovecot.assert_called_once()
    mock_procmail.assert_called_once()


def test_is_primary_true(ctx, base_state):
    with patch("charm.DovecotCharm._install"):
        with ctx(ctx.on.config_changed(), base_state) as mgr:
            assert mgr.charm._is_primary is True


def test_is_primary_false(ctx, base_state):
    state_in = dataclasses.replace(
        base_state, config={**base_state.config, "primary-unit": "dovecot-charm/999"}
    )
    with patch("charm.DovecotCharm._install"):
        with ctx(ctx.on.config_changed(), state_in) as mgr:
            assert mgr.charm._is_primary is False


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
    with patch(
        "charm.subprocess.run",
        side_effect=CalledProcessError(1, "postsuper", stderr="error msg"),
    ):
        with pytest.raises(ops.testing.ActionFailed) as exc_info:
            ctx.run(
                ctx.on.action("clear-queue", params={"queue": "deferred"}),
                base_state,
            )
    assert "postsuper" in exc_info.value.message
