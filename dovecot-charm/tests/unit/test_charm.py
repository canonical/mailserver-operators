# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
import json
from pathlib import Path
from subprocess import CalledProcessError  # nosec
from unittest.mock import MagicMock, patch

import ops
import ops.testing
import pytest
from testing import DovecotTestCharm, NoOpDovecotSetup, NoOpHAManager

from constants import SYNC_TO_SECONDARY_TARGET
from exceptions import ConfigurationError, HASetupError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PEER_RELATION_NAME = "replicas"


def _secondary_relation(hostname: str = "10.0.0.2") -> ops.testing.PeerRelation:
    """Return a peer relation whose remote unit has published the given hostname."""
    return ops.testing.PeerRelation(
        PEER_RELATION_NAME,
        peers_data={1: {"hostname": hostname}},
    )


def _non_primary_config(base_config: dict) -> dict:
    """Return config where primary-unit doesn't match this unit (dovecot/0)."""
    return {**base_config, "primary-unit": "dovecot/99"}


def _sync_script_exists_patch(exists: bool):
    """Return a Path.exists side_effect that intercepts only SYNC_TO_SECONDARY_TARGET."""
    _real_exists = Path.exists

    def _patched(self):
        if str(self) == SYNC_TO_SECONDARY_TARGET:
            return exists
        return _real_exists(self)

    return _patched


# ---------------------------------------------------------------------------
# Reconcile — status and ports
# ---------------------------------------------------------------------------


def test_reconcile_sets_active_on_success(ctx, base_state):
    """Reconcile must reach ActiveStatus when all setup steps succeed."""
    state_out = ctx.run(ctx.on.config_changed(), base_state)
    assert isinstance(state_out.unit_status, ops.ActiveStatus)


def test_reconcile_opens_mail_ports(ctx, base_state):
    """All required IMAP/POP3/Sieve/metrics ports must be opened."""
    state_out = ctx.run(ctx.on.config_changed(), base_state)
    expected = {ops.testing.TCPPort(p) for p in [993, 995, 4190, 9900]}
    assert state_out.opened_ports == expected


# ---------------------------------------------------------------------------
# Reconcile — blocked on setup failures
# ---------------------------------------------------------------------------


def test_reconcile_blocks_when_dovecot_setup_fails(ctx, base_state):
    """Charm must be Blocked when setup_dovecot raises ConfigurationError."""

    class _FailingSetup(NoOpDovecotSetup):
        def setup_dovecot(self, config):
            raise ConfigurationError("Invalid Dovecot configuration, check logs for details")

    with patch.object(DovecotTestCharm, "_dovecot_setup", _FailingSetup()):
        state_out = ctx.run(ctx.on.config_changed(), base_state)

    assert isinstance(state_out.unit_status, ops.BlockedStatus)
    assert "Invalid Dovecot configuration" in state_out.unit_status.message


def test_reconcile_blocks_when_procmail_setup_fails(ctx, base_state):
    """Charm must be Blocked when setup_procmail raises ConfigurationError."""

    class _FailingSetup(NoOpDovecotSetup):
        def setup_procmail(self):
            raise ConfigurationError("Failed to configure postfix: error")

    with patch.object(DovecotTestCharm, "_dovecot_setup", _FailingSetup()):
        state_out = ctx.run(ctx.on.config_changed(), base_state)

    assert isinstance(state_out.unit_status, ops.BlockedStatus)
    assert "postfix" in state_out.unit_status.message


def test_reconcile_blocks_when_ha_setup_fails(ctx, base_state):
    """Charm must be Blocked when setup_ssh_keys raises HASetupError."""

    class _FailingHA(NoOpHAManager):
        def setup_ssh_keys(self):
            raise HASetupError("SSH keygen failed")

    with patch.object(DovecotTestCharm, "_ha", _FailingHA()):
        state_out = ctx.run(ctx.on.config_changed(), base_state)

    assert isinstance(state_out.unit_status, ops.BlockedStatus)
    assert "SSH keygen failed" in state_out.unit_status.message


# ---------------------------------------------------------------------------
# HA: _is_primary
# ---------------------------------------------------------------------------


def test_is_primary_true_when_unit_matches_config(ctx, base_state):
    """_is_primary returns True when primary-unit config matches this unit."""
    with ctx(ctx.on.config_changed(), base_state) as mgr:
        assert mgr.charm._is_primary is True


def test_is_primary_false_when_unit_differs(ctx, base_state):
    """_is_primary returns False when primary-unit config doesn't match this unit."""
    state_in = dataclasses.replace(base_state, config=_non_primary_config(base_state.config))
    with ctx(ctx.on.config_changed(), state_in) as mgr:
        assert mgr.charm._is_primary is False


# ---------------------------------------------------------------------------
# HA: sync script installed only on primary
# ---------------------------------------------------------------------------


def test_reconcile_skips_sync_script_when_not_primary(ctx, base_state):
    """When this unit is NOT primary, sync script and timer are not installed."""
    # primary-unit must be a known unit; use the secondary (unit id 1 = dovecot/1)
    # so that this unit (dovecot/0) is not primary.
    state_in = dataclasses.replace(
        base_state,
        config={**base_state.config, "primary-unit": "dovecot/1"},
        relations={_secondary_relation()},
    )

    class _SpyHA(NoOpHAManager):
        install_called = False
        timer_called = False

        def install_mail_sync_script(self):
            _SpyHA.install_called = True

        def setup_mail_sync_timer(self, dovecot_config):
            _SpyHA.timer_called = True

    with patch.object(DovecotTestCharm, "_ha", _SpyHA()):
        state_out = ctx.run(ctx.on.config_changed(), state_in)

    assert isinstance(state_out.unit_status, ops.ActiveStatus)
    assert not _SpyHA.install_called
    assert not _SpyHA.timer_called


# ---------------------------------------------------------------------------
# Clear-queue action
# ---------------------------------------------------------------------------


def test_clear_queue_deferred(ctx, base_state):
    """clear-queue action with queue=deferred passes correct args to postsuper."""
    mock_result = MagicMock(stdout="cleared")
    with patch("charm.subprocess.run", return_value=mock_result) as mock_run:
        ctx.run(ctx.on.action("clear-queue", params={"queue": "deferred"}), base_state)
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
    with patch("charm.subprocess.run", return_value=mock_result) as mock_run:
        ctx.run(ctx.on.action("clear-queue", params={"queue": "all"}), base_state)
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
        ctx.run(ctx.on.action("clear-queue", params={"queue": "deferred"}), base_state)
    assert "postsuper" in exc_info.value.message


# ---------------------------------------------------------------------------
# Force-sync action
# ---------------------------------------------------------------------------


def test_force_sync_success(ctx, base_state):
    """force-sync succeeds when this unit is primary and a secondary exists."""
    mock_result = MagicMock(stdout="ok", stderr="")
    state_in = dataclasses.replace(base_state, relations={_secondary_relation()})
    with (
        patch("charm.subprocess.run", return_value=mock_result),
        patch.object(Path, "exists", _sync_script_exists_patch(True)),
    ):
        ctx.run(ctx.on.action("force-sync"), state_in)
    assert ctx.action_results == {"result": "Sync completed successfully"}


def test_force_sync_not_primary(ctx, base_state):
    """force-sync must fail when executed on a non-primary unit."""
    state_in = dataclasses.replace(base_state, config=_non_primary_config(base_state.config))
    with pytest.raises(ops.testing.ActionFailed) as exc_info:
        ctx.run(ctx.on.action("force-sync"), state_in)
    assert "primary unit" in exc_info.value.message


def test_force_sync_no_secondary(ctx, base_state):
    """force-sync must fail when no secondary unit hostname is available."""
    with pytest.raises(ops.testing.ActionFailed) as exc_info:
        ctx.run(ctx.on.action("force-sync"), base_state)
    assert "secondary" in exc_info.value.message.lower()


def test_force_sync_subprocess_failure(ctx, base_state):
    """force-sync must fail when the sync script exits non-zero."""
    state_in = dataclasses.replace(base_state, relations={_secondary_relation()})
    with (
        patch(
            "charm.subprocess.run",
            side_effect=CalledProcessError(1, "sync", stderr="fail"),
        ),
        patch.object(Path, "exists", _sync_script_exists_patch(True)),
        pytest.raises(ops.testing.ActionFailed) as exc_info,
    ):
        ctx.run(ctx.on.action("force-sync"), state_in)
    assert "fail" in exc_info.value.message


def test_force_sync_script_not_installed(ctx, base_state):
    """force-sync must fail with a clear message when sync script is not yet installed."""
    state_in = dataclasses.replace(base_state, relations={_secondary_relation()})
    with (
        patch.object(Path, "exists", _sync_script_exists_patch(False)),
        pytest.raises(ops.testing.ActionFailed) as exc_info,
    ):
        ctx.run(ctx.on.action("force-sync"), state_in)
    assert "wait for the charm" in exc_info.value.message


def test_cos_agent_relation_data_populated(ctx, base_state):
    """On cos-agent relation-joined, the unit databag must contain
    the scrape job for port 9900 and non-empty alert rules and dashboard entries.
    """
    cos_relation = ops.testing.Relation("cos-agent")
    state_in = dataclasses.replace(base_state, relations={cos_relation})

    state_out = ctx.run(ctx.on.relation_joined(cos_relation), state_in)

    relation_out = state_out.get_relation(cos_relation.id)
    raw = relation_out.local_unit_data.get("config")
    assert raw is not None, "COSAgentProvider did not write 'config' key to unit databag"

    data = json.loads(raw)
    scrape_jobs = data.get("metrics_scrape_jobs", [])
    assert any(
        job.get("static_configs", [{}])[0].get("targets", [""])[0].endswith(":9900")
        for job in scrape_jobs
    ), f"Expected scrape job on port 9900, got: {scrape_jobs}"
    assert data.get("metrics_alert_rules"), "metrics_alert_rules should be populated"
    assert data.get("log_alert_rules"), "log_alert_rules should be populated"
    assert data.get("dashboards"), "dashboards should be populated"
