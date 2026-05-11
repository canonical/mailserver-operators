# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
from subprocess import CalledProcessError  # nosec
from unittest.mock import MagicMock, patch

import pytest
from ops.model import BlockedStatus
from pydantic import ValidationError

from dovecot_config import DovecotConfig, DovecotConfigInvalidError


@pytest.mark.parametrize(
    "config_change, expected_status",
    [
        pytest.param(
            {"mailname": "", "postmaster-address": ""},
            BlockedStatus(
                "Invalid charm configuration, check logs for details: mailname, postmaster_address"
            ),
            id="Multiple missing/invalid config options",
        ),
        pytest.param(
            {"mailname": ""},
            BlockedStatus("Invalid charm configuration, check logs for details: mailname"),
            id="Invalid mailname config option",
        ),
        pytest.param(
            {"postmaster-address": ""},
            BlockedStatus(
                "Invalid charm configuration, check logs for details: postmaster_address"
            ),
            id="Invalid postmaster-address config option",
        ),
        pytest.param(
            {"primary-unit": ""},
            BlockedStatus("Invalid charm configuration, check logs for details: primary_unit"),
            id="Invalid primary-unit config option",
        ),
    ],
)
def test_config_missing_multiple_blocks(ctx, base_state, config_change, expected_status):
    state_in = dataclasses.replace(base_state, config={**base_state.config, **config_change})
    with patch("charm.DovecotCharm._install"):
        state_out = ctx.run(ctx.on.config_changed(), state_in)
    assert state_out.unit_status == expected_status


def test_from_charm_primary_unit_does_not_exist_raises_value_error(base_state):
    charm = MagicMock()
    charm.model.config = base_state.config
    charm.model.get_unit.return_value = None

    with pytest.raises(DovecotConfigInvalidError, match="Primary unit does not exist"):
        DovecotConfig.from_charm(charm)


# Valid config kwargs shared by sync_schedule tests.
_VALID_BASE = {
    "mailname": "example.com",
    "postmaster_address": "admin@example.com",
    "primary_unit": "dovecot/0",
}


class TestSyncScheduleValidation:
    """Tests for the sync_schedule OnCalendar validator.

    Most tests patch subprocess.run to avoid a hard dependency on systemd-analyze
    being present in the unit-test environment.  One live test verifies the
    default value against the real binary.
    """

    _VALID_MOCK = MagicMock(returncode=0)

    def _mock_valid(self):
        return patch("dovecot_config.subprocess.run", return_value=self._VALID_MOCK)

    def _mock_invalid(self):
        return patch(
            "dovecot_config.subprocess.run",
            side_effect=CalledProcessError(1, "systemd-analyze", stderr="Invalid"),
        )

    def test_valid_default_live(self):
        """The default 'daily' must be accepted by the real systemd-analyze."""
        cfg = DovecotConfig(**_VALID_BASE)
        assert cfg.sync_schedule == "daily"

    def test_valid_every_minute(self):
        with self._mock_valid():
            cfg = DovecotConfig(**_VALID_BASE, sync_schedule="*:*")
        assert cfg.sync_schedule == "*:*"

    def test_valid_hourly(self):
        with self._mock_valid():
            cfg = DovecotConfig(**_VALID_BASE, sync_schedule="hourly")
        assert cfg.sync_schedule == "hourly"

    def test_valid_daily(self):
        with self._mock_valid():
            cfg = DovecotConfig(**_VALID_BASE, sync_schedule="daily")
        assert cfg.sync_schedule == "daily"

    def test_rejects_newline(self):
        with pytest.raises(ValidationError, match="must not contain newlines"):
            DovecotConfig(**_VALID_BASE, sync_schedule="*:0/30\nbad")

    def test_rejects_carriage_return(self):
        with pytest.raises(ValidationError, match="must not contain newlines"):
            DovecotConfig(**_VALID_BASE, sync_schedule="*:0/30\rbad")

    def test_rejects_invalid_expression(self):
        with (
            self._mock_invalid(),
            pytest.raises(ValidationError, match="not a valid OnCalendar expression"),
        ):
            DovecotConfig(**_VALID_BASE, sync_schedule="not-a-calendar")

    def test_rejects_empty_string(self):
        with (
            self._mock_invalid(),
            pytest.raises(ValidationError, match="not a valid OnCalendar expression"),
        ):
            DovecotConfig(**_VALID_BASE, sync_schedule="")

    def test_rejects_shell_injection(self):
        with (
            self._mock_invalid(),
            pytest.raises(ValidationError, match="not a valid OnCalendar expression"),
        ):
            DovecotConfig(**_VALID_BASE, sync_schedule="$(rm -rf /)/")

    def test_calls_systemd_analyze_with_value(self):
        """Validator must pass the schedule value directly to systemd-analyze calendar."""
        with patch("dovecot_config.subprocess.run", return_value=self._VALID_MOCK) as mock_run:
            DovecotConfig(**_VALID_BASE, sync_schedule="*:0/15")
        mock_run.assert_called_once_with(
            ["/usr/bin/systemd-analyze", "calendar", "*:0/15"],
            check=True,
            capture_output=True,
            text=True,
        )
