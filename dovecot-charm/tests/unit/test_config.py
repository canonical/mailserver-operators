# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
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
    "primary_unit": "dovecot-charm/0",
}


class TestSyncScheduleValidation:
    def test_valid_default(self):
        cfg = DovecotConfig(**_VALID_BASE)
        assert cfg.sync_schedule == "*/30 * * * *"

    def test_valid_every_minute(self):
        cfg = DovecotConfig(**_VALID_BASE, sync_schedule="*/1 * * * *")
        assert cfg.sync_schedule == "*/1 * * * *"

    def test_valid_specific_fields(self):
        cfg = DovecotConfig(**_VALID_BASE, sync_schedule="0 4 * * 1")
        assert cfg.sync_schedule == "0 4 * * 1"

    def test_normalises_whitespace(self):
        cfg = DovecotConfig(**_VALID_BASE, sync_schedule="*/30  *   *  * *")
        assert cfg.sync_schedule == "*/30 * * * *"

    def test_rejects_newline(self):
        with pytest.raises(ValidationError, match="must not contain newlines"):
            DovecotConfig(**_VALID_BASE, sync_schedule="*/30 * * * *\nbad root /bin/evil")

    def test_rejects_too_few_fields(self):
        with pytest.raises(ValidationError, match="exactly 5 fields"):
            DovecotConfig(**_VALID_BASE, sync_schedule="*/30 * * *")

    def test_rejects_too_many_fields(self):
        with pytest.raises(ValidationError, match="exactly 5 fields"):
            DovecotConfig(**_VALID_BASE, sync_schedule="*/30 * * * * extra")

    def test_rejects_empty_string(self):
        with pytest.raises(ValidationError, match="exactly 5 fields"):
            DovecotConfig(**_VALID_BASE, sync_schedule="")

    def test_rejects_command_substitution(self):
        with pytest.raises(ValidationError, match="disallowed characters"):
            DovecotConfig(**_VALID_BASE, sync_schedule="$(rm) * * * *")

    def test_rejects_backticks(self):
        with pytest.raises(ValidationError, match="disallowed characters"):
            DovecotConfig(**_VALID_BASE, sync_schedule="`id` * * * *")

    def test_rejects_semicolon(self):
        with pytest.raises(ValidationError, match="disallowed characters"):
            DovecotConfig(**_VALID_BASE, sync_schedule="*;id * * * *")

    def test_rejects_pipe(self):
        with pytest.raises(ValidationError, match="disallowed characters"):
            DovecotConfig(**_VALID_BASE, sync_schedule="*|cat * * * *")

    def test_rejects_alphabetic_field(self):
        with pytest.raises(ValidationError, match="disallowed characters"):
            DovecotConfig(**_VALID_BASE, sync_schedule="* * * * MON")

    def test_rejects_question_mark(self):
        with pytest.raises(ValidationError, match="disallowed characters"):
            DovecotConfig(**_VALID_BASE, sync_schedule="? * * * *")
