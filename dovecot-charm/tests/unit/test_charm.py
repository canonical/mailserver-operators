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
from exceptions import ConfigurationError


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
        # storage module talks to cryptsetup / mount — not under test
        patch("charm.ensure_storage_ready"),
        patch("charm.teardown_detaching_storage"),
        # doveconf binary check — pretend it's installed
        patch("charm.shutil.which", return_value="/usr/bin/doveconf"),
        # TLS writes cert/key files to disk — not under test
        patch("charm.DovecotCharm._setup_tls"),
        # dovecot config rendering + validation + reload — not under test
        patch("charm.DovecotCharm._setup_dovecot"),
        # procmail config rendering + postfix postconf — not under test
        patch("charm.DovecotCharm._setup_procmail"),
        # SSH keygen + filesystem writes — not under test
        patch("charm.DovecotCharm._setup_ssh_keys"),
        # authorized_keys sync — not under test
        patch("charm.DovecotCharm._sync_authorized_keys"),
        # sync script rendering — not under test
        patch("charm.DovecotCharm._install_mail_sync_script"),
        # cronjob rendering + cron restart — not under test
        patch("charm.DovecotCharm._setup_mail_sync_cronjob"),
    ):
        yield


# ---------------------------------------------------------------------------
# Reconcile: status + ports
# ---------------------------------------------------------------------------


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
        # _setup_dovecot raises — this is the condition under test
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
        # _setup_procmail raises — this is the condition under test
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
    # base_state has primary-unit=dovecot-charm/0; the ctx app_name gives unit dovecot-charm/0
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
        # config validation rejects unknown units — bypass it since we're only testing _is_primary
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
    # Use a valid config but override _is_primary to False to bypass pydantic
    # validation (which requires primary-unit to match an existing unit).
    with (
        patch("charm.ensure_storage_ready"),
        patch("charm.teardown_detaching_storage"),
        patch("charm.shutil.which", return_value="/usr/bin/doveconf"),
        patch("charm.DovecotCharm._setup_tls"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
        # ssh keygen — real subprocess not under test
        patch("charm.DovecotCharm._setup_ssh_keys"),
        # authorized_keys sync — not under test
        patch("charm.DovecotCharm._sync_authorized_keys"),
        # Override _is_primary to simulate being a non-primary unit
        patch("charm.DovecotCharm._is_primary", new_callable=PropertyMock, return_value=False),
        # These should NOT be called — we verify via state not mocks
        patch("charm.DovecotCharm._install_mail_sync_script") as mock_sync,
        patch("charm.DovecotCharm._setup_mail_sync_cronjob") as mock_cron,
    ):
        state_out = ctx.run(ctx.on.config_changed(), base_state)

    # Charm still reaches Active even without sync scripts
    assert isinstance(state_out.unit_status, ops.ActiveStatus)
    # Secondary check: these should not have been called since unit is not primary
    mock_sync.assert_not_called()
    mock_cron.assert_not_called()


# ---------------------------------------------------------------------------
# Clear-queue action
# ---------------------------------------------------------------------------


def test_clear_queue_deferred(ctx, base_state):
    """clear-queue action with queue=deferred passes correct args to postsuper."""
    mock_result = MagicMock(stdout="cleared")
    with (
        # postsuper is the only subprocess call in this action path
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
        # postsuper is the only subprocess call in this action path
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
        # simulate postsuper failure
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
        # sync script subprocess call — the action delegates to the shell script
        patch("charm.subprocess.run", return_value=mock_result),
        # provide a secondary hostname so the action doesn't bail out
        patch.object(
            DovecotCharm,
            "_secondary_hostname",
            new_callable=PropertyMock,
            return_value="10.0.0.2",
        ),
    ):
        ctx.run(ctx.on.action("force-sync"), base_state)
    assert ctx.action_results == {"result": "Sync completed successfully"}


def test_force_sync_not_primary(ctx, base_state):
    """force-sync must fail when executed on a non-primary unit."""
    # Override _is_primary since pydantic rejects unknown unit names
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
        # sync script fails
        patch(
            "charm.subprocess.run",
            side_effect=CalledProcessError(1, "sync", stderr="fail"),
        ),
        # provide secondary so the action reaches subprocess.run
        patch.object(
            DovecotCharm,
            "_secondary_hostname",
            new_callable=PropertyMock,
            return_value="10.0.0.2",
        ),
        pytest.raises(ops.testing.ActionFailed) as exc_info,
    ):
        ctx.run(ctx.on.action("force-sync"), base_state)
    assert "fail" in exc_info.value.message
