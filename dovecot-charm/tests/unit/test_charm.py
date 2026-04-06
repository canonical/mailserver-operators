# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
from subprocess import CalledProcessError  # nosec
from unittest.mock import MagicMock, patch

import ops.testing
import pytest
from ops.model import BlockedStatus

# --- Config validation tests ---


def test_config_missing_mailname_blocks(ctx, base_state):
    state_in = dataclasses.replace(base_state, config={**base_state.config, "mailname": ""})
    with patch("charm.DovecotCharm._install"):
        state_out = ctx.run(ctx.on.config_changed(), state_in)
    assert state_out.unit_status == BlockedStatus(
        "Invalid mailname: Value error, must not be empty"
    )


def test_config_missing_postmaster_blocks(ctx, base_state):
    state_in = dataclasses.replace(
        base_state, config={**base_state.config, "postmaster-address": ""}
    )
    with patch("charm.DovecotCharm._install"):
        state_out = ctx.run(ctx.on.config_changed(), state_in)
    assert state_out.unit_status == BlockedStatus(
        "Invalid postmaster-address: Value error, must not be empty"
    )


def test_config_missing_cron_mailto_blocks(ctx, base_state):
    state_in = dataclasses.replace(base_state, config={**base_state.config, "cron-mailto": ""})
    with patch("charm.DovecotCharm._install"):
        state_out = ctx.run(ctx.on.config_changed(), state_in)
    assert state_out.unit_status == BlockedStatus(
        "Invalid cron-mailto: value is not a valid email address: An email address must have an @-sign."
    )


def test_config_missing_primary_unit_blocks(ctx, base_state):
    state_in = dataclasses.replace(base_state, config={**base_state.config, "primary-unit": ""})
    with patch("charm.DovecotCharm._install"):
        state_out = ctx.run(ctx.on.config_changed(), state_in)
    assert state_out.unit_status == BlockedStatus(
        "Invalid primary-unit: Value error, must not be empty"
    )


def test_open_ports(ctx, base_state):
    def fake_config(self, dovecot_config):
        self._open_ports()

    with patch("charm.DovecotCharm._config", fake_config):
        state_out = ctx.run(ctx.on.config_changed(), base_state)

    expected = {ops.testing.TCPPort(p) for p in [143, 993, 110, 995, 4190, 9900]}
    assert state_out.opened_ports == expected


def test_is_primary_true(ctx, base_state):
    with patch("charm.DovecotCharm._config"), ctx(ctx.on.config_changed(), base_state) as mgr:
        assert mgr.charm._is_primary is True


def test_is_primary_false(ctx, base_state):
    state_in = dataclasses.replace(
        base_state, config={**base_state.config, "primary-unit": "dovecot-charm/999"}
    )
    with patch("charm.DovecotCharm._config"), ctx(ctx.on.config_changed(), state_in) as mgr:
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
