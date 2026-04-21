# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.
import contextlib
import dataclasses
from subprocess import CalledProcessError  # nosec
from unittest.mock import MagicMock, PropertyMock, patch

import ops
import ops.testing
import pytest

from charm import DovecotCharm
from exceptions import ConfigurationError, HASetupError

# ---------------------------------------------------------------------------
# Helpers — patches shared across many tests
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def reconcile_guards():
    """Guard all I/O in _reconcile so tests only exercise event wiring / status.

    Use when the test drives an event that triggers _reconcile but the test
    is NOT about the logic inside these helpers (storage, TLS, dovecot, etc.).
    """
    with (
        patch("charm.ensure_storage_ready"),
        patch("charm.teardown_detaching_storage"),
        patch("charm.shutil.which", return_value="/usr/bin/doveconf"),
        patch("charm.DovecotCharm._setup_tls"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
        patch("ha.setup_ssh_keys"),
        patch("ha.sync_authorized_keys"),
        patch("ha.sync_known_hosts"),
        patch("ha.install_mail_sync_script"),
        patch("ha.setup_mail_sync_cronjob"),
    ):
        yield


def test_reconcile_sets_active_on_success(ctx, base_state):
    """Reconcile must reach ActiveStatus when all setup steps succeed."""
    with reconcile_guards():
        state_out = ctx.run(ctx.on.config_changed(), base_state)
    assert isinstance(state_out.unit_status, ops.ActiveStatus)


def test_reconcile_opens_mail_ports(ctx, base_state):
    """All required IMAP/POP3/Sieve/metrics ports must be opened."""
    with reconcile_guards():
        state_out = ctx.run(ctx.on.config_changed(), base_state)

    expected = {ops.testing.TCPPort(p) for p in [993, 995, 4190, 9900]}
    assert state_out.opened_ports == expected


def test_reconcile_blocks_when_dovecot_setup_fails(ctx, base_state):
    """Charm must be Blocked when _setup_dovecot raises ConfigurationError."""
    with (
        patch("charm.ensure_storage_ready"),
        patch("charm.teardown_detaching_storage"),
        patch("charm.shutil.which", return_value="/usr/bin/doveconf"),
        patch("charm.DovecotCharm._setup_tls"),
        patch(
            "charm.DovecotCharm._setup_dovecot",
            side_effect=ConfigurationError(
                "Invalid Dovecot configuration, check logs for details"
            ),
        ),
        patch("charm.DovecotCharm._setup_procmail"),
    ):
        state_out = ctx.run(ctx.on.config_changed(), base_state)

    assert isinstance(state_out.unit_status, ops.BlockedStatus)
    assert "Invalid Dovecot configuration" in state_out.unit_status.message


def test_reconcile_blocks_when_procmail_setup_fails(ctx, base_state):
    """Charm must be Blocked when _setup_procmail raises ConfigurationError."""
    with (
        patch("charm.ensure_storage_ready"),
        patch("charm.teardown_detaching_storage"),
        patch("charm.shutil.which", return_value="/usr/bin/doveconf"),
        patch("charm.DovecotCharm._setup_tls"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch(
            "charm.DovecotCharm._setup_procmail",
            side_effect=ConfigurationError("Failed to configure postfix: error"),
        ),
    ):
        state_out = ctx.run(ctx.on.config_changed(), base_state)

    assert isinstance(state_out.unit_status, ops.BlockedStatus)
    assert "postfix" in state_out.unit_status.message


# ---------------------------------------------------------------------------
# HA: _is_primary
# ---------------------------------------------------------------------------


def test_is_primary_true_when_unit_matches_config(ctx, base_state):
    """_is_primary returns True when primary-unit config matches this unit."""
    with reconcile_guards(), ctx(ctx.on.config_changed(), base_state) as mgr:
        assert mgr.charm._is_primary is True


def test_is_primary_false_when_unit_differs(ctx, base_state):
    """_is_primary returns False when primary-unit config doesn't match this unit.

    We access the charm inside the context manager before the event fires,
    so no _reconcile I/O is reached — no patches needed for the HA methods.
    Config validation is bypassed by patching _get_dovecot_config.
    """
    state_in = dataclasses.replace(
        base_state, config={**base_state.config, "primary-unit": "dovecot-charm/99"}
    )
    with (
        patch("charm.DovecotCharm._get_dovecot_config"),
        patch("charm.ensure_storage_ready"),
        patch("charm.teardown_detaching_storage"),
        patch("charm.shutil.which", return_value=None),
        ctx(ctx.on.config_changed(), state_in) as mgr,
    ):
        assert mgr.charm._is_primary is False


# ---------------------------------------------------------------------------
# HA: reconcile calls sync script only on primary with known secondary
# ---------------------------------------------------------------------------


def test_reconcile_skips_sync_script_when_not_primary(ctx, base_state):
    """When this unit is NOT primary, sync script and cronjob are not installed."""
    with (
        patch("charm.ensure_storage_ready"),
        patch("charm.teardown_detaching_storage"),
        patch("charm.shutil.which", return_value="/usr/bin/doveconf"),
        patch("charm.DovecotCharm._setup_tls"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
        patch("ha.setup_ssh_keys"),
        patch("ha.sync_authorized_keys"),
        patch("ha.sync_known_hosts"),
        patch("charm.DovecotCharm._is_primary", new_callable=PropertyMock, return_value=False),
        patch("ha.install_mail_sync_script") as mock_sync,
        patch("ha.setup_mail_sync_cronjob") as mock_cron,
    ):
        state_out = ctx.run(ctx.on.config_changed(), base_state)

    assert isinstance(state_out.unit_status, ops.ActiveStatus)
    mock_sync.assert_not_called()
    mock_cron.assert_not_called()


# ---------------------------------------------------------------------------
# Clear-queue action
# ---------------------------------------------------------------------------


def test_clear_queue_deferred(ctx, base_state):
    """clear-queue action with queue=deferred passes correct args to postsuper."""
    mock_result = MagicMock(stdout="cleared")
    with (
        patch("charm.subprocess.run", return_value=mock_result) as mock_run,
    ):
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
    """clear-queue action with queue=all omits the deferred queue filter."""
    mock_result = MagicMock(stdout="cleared")
    with (
        patch("charm.subprocess.run", return_value=mock_result) as mock_run,
    ):
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
    """clear-queue action must fail when postsuper returns non-zero."""
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


# ---------------------------------------------------------------------------
# Force-sync action
# ---------------------------------------------------------------------------


def test_force_sync_success(ctx, base_state):
    """force-sync succeeds when this unit is primary and a secondary exists."""
    mock_result = MagicMock(stdout="ok", stderr="")
    with (
        patch("charm.subprocess.run", return_value=mock_result),
        patch("charm.Path") as mock_path_cls,
        patch.object(
            DovecotCharm,
            "_secondary_hostname",
            new_callable=PropertyMock,
            return_value="10.0.0.2",
        ),
    ):
        mock_path_cls.return_value.exists.return_value = True
        ctx.run(ctx.on.action("force-sync"), base_state)
    assert ctx.action_results == {"result": "Sync completed successfully"}


def test_force_sync_not_primary(ctx, base_state):
    """force-sync must fail when executed on a non-primary unit."""
    with (
        patch("charm.DovecotCharm._is_primary", new_callable=PropertyMock, return_value=False),
        pytest.raises(ops.testing.ActionFailed) as exc_info,
    ):
        ctx.run(ctx.on.action("force-sync"), base_state)
    assert "primary unit" in exc_info.value.message


def test_force_sync_no_secondary(ctx, base_state):
    """force-sync must fail when no secondary unit hostname is available."""
    with pytest.raises(ops.testing.ActionFailed) as exc_info:
        ctx.run(ctx.on.action("force-sync"), base_state)
    assert "secondary" in exc_info.value.message


def test_force_sync_subprocess_failure(ctx, base_state):
    """force-sync must fail when the sync script exits non-zero."""
    with (
        patch(
            "charm.subprocess.run",
            side_effect=CalledProcessError(1, "sync", stderr="fail"),
        ),
        patch("charm.Path") as mock_path_cls,
        patch.object(
            DovecotCharm,
            "_secondary_hostname",
            new_callable=PropertyMock,
            return_value="10.0.0.2",
        ),
        pytest.raises(ops.testing.ActionFailed) as exc_info,
    ):
        mock_path_cls.return_value.exists.return_value = True
        ctx.run(ctx.on.action("force-sync"), base_state)
    assert "fail" in exc_info.value.message


# ---------------------------------------------------------------------------
# HA: reconcile blocks on HASetupError
# ---------------------------------------------------------------------------


def test_reconcile_blocks_when_ha_setup_fails(ctx, base_state):
    """Charm must be Blocked when HA setup raises HASetupError."""
    with (
        patch("charm.ensure_storage_ready"),
        patch("charm.teardown_detaching_storage"),
        patch("charm.shutil.which", return_value="/usr/bin/doveconf"),
        patch("charm.DovecotCharm._setup_tls"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
        patch("ha.setup_ssh_keys", side_effect=HASetupError("SSH keygen failed")),
    ):
        state_out = ctx.run(ctx.on.config_changed(), base_state)

    assert isinstance(state_out.unit_status, ops.BlockedStatus)
    assert "SSH keygen failed" in state_out.unit_status.message


def test_force_sync_script_not_installed(ctx, base_state):
    """force-sync must fail with a clear message when sync script is not yet installed."""
    with (
        patch.object(
            DovecotCharm,
            "_secondary_hostname",
            new_callable=PropertyMock,
            return_value="10.0.0.2",
        ),
        patch("charm.Path") as mock_path_cls,
        pytest.raises(ops.testing.ActionFailed) as exc_info,
    ):
        mock_path_cls.return_value.exists.return_value = False
        ctx.run(ctx.on.action("force-sync"), base_state)

    assert "wait for the charm" in exc_info.value.message
