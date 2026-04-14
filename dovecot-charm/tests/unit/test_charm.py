# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.
import dataclasses
from subprocess import CalledProcessError  # nosec
from unittest.mock import MagicMock, patch

import ops
import ops.testing
import pytest

from exceptions import ConfigurationError


def test_open_ports(ctx, base_state):
    with (
        patch("charm.DovecotCharm._install"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
        patch("charm.ensure_storage_ready"),
        patch("charm.teardown_detaching_storage"),
        patch("charm.shutil.which", return_value="/usr/bin/doveconf"),
    ):
        state_out = ctx.run(ctx.on.config_changed(), base_state)

    expected = {ops.testing.TCPPort(p) for p in [143, 993, 110, 995, 4190, 9900]}
    assert state_out.opened_ports == expected


def test_configure_sets_active_on_success(ctx, base_state):
    with (
        patch("charm.DovecotCharm._install"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
        patch("charm.ensure_storage_ready"),
        patch("charm.teardown_detaching_storage"),
        patch("charm.shutil.which", return_value="/usr/bin/doveconf"),
    ):
        state_out = ctx.run(ctx.on.config_changed(), base_state)

    assert isinstance(state_out.unit_status, ops.ActiveStatus)


def test_configure_blocks_when_dovecot_setup_fails(ctx, base_state):
    with (
        patch("charm.DovecotCharm._install"),
        patch(
            "charm.DovecotCharm._setup_dovecot",
            side_effect=ConfigurationError(
                "Invalid Dovecot configuration, check logs for details"
            ),
        ),
        patch("charm.DovecotCharm._setup_procmail"),
        patch("charm.ensure_storage_ready"),
        patch("charm.teardown_detaching_storage"),
        patch("charm.shutil.which", return_value="/usr/bin/doveconf"),
    ):
        state_out = ctx.run(ctx.on.config_changed(), base_state)

    assert isinstance(state_out.unit_status, ops.BlockedStatus)
    assert "Invalid Dovecot configuration" in state_out.unit_status.message


def test_configure_blocks_when_procmail_setup_fails(ctx, base_state):
    with (
        patch("charm.DovecotCharm._install"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch(
            "charm.DovecotCharm._setup_procmail",
            side_effect=ConfigurationError("Failed to configure postfix: error"),
        ),
        patch("charm.ensure_storage_ready"),
        patch("charm.teardown_detaching_storage"),
        patch("charm.shutil.which", return_value="/usr/bin/doveconf"),
    ):
        state_out = ctx.run(ctx.on.config_changed(), base_state)

    assert isinstance(state_out.unit_status, ops.BlockedStatus)
    assert "postfix" in state_out.unit_status.message


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


# --- TLS certificate tests ---


def test_certificate_available_writes_files(ctx, base_state, tmp_path):
    with (
        patch("charm.DovecotCharm._install"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
        patch("charm.systemd.service_reload", return_value=True),
        ctx(ctx.on.config_changed(), base_state) as mgr,
    ):
        mgr.charm.tls_cert_dir = tmp_path
        event = MagicMock()
        event.certificate.certificate = "CERT_DATA"
        event.certificate.ca = "CA_DATA"
        mgr.charm._tls = MagicMock()
        mgr.charm._tls.private_key = "KEY_DATA"
        mgr.charm._on_certificate_available(event)
    assert (tmp_path / "example.com.pem").exists()


def test_certificate_available_no_mailname_returns(ctx, base_state):
    state_in = dataclasses.replace(base_state, config={**base_state.config, "mailname": ""})
    with (
        patch("charm.DovecotCharm._install"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
        patch("charm.systemd.service_reload") as mock_service_reload,
        ctx(ctx.on.config_changed(), state_in) as mgr,
    ):
        event = MagicMock()
        mgr.charm._on_certificate_available(event)
    mock_service_reload.assert_not_called()


def test_certificate_available_restarts_dovecot(ctx, base_state, tmp_path):
    with (
        patch("charm.DovecotCharm._install"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
        patch("charm.systemd.service_reload", return_value=True) as mock_service_reload,
        ctx(ctx.on.config_changed(), base_state) as mgr,
    ):
        mgr.charm.tls_cert_dir = tmp_path
        event = MagicMock()
        event.certificate.certificate = "CERT_DATA"
        event.certificate.ca = None
        mgr.charm._tls = MagicMock()
        mgr.charm._tls.private_key = "KEY_DATA"
        mgr.charm._on_certificate_available(event)
    mock_service_reload.assert_called_with("dovecot")
