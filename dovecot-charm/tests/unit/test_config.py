# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
from unittest.mock import MagicMock, patch

import pytest
from ops.model import BlockedStatus

from dovecot_config import DovecotConfig, DovecotConfigInvalidError


@pytest.mark.parametrize(
    "config_change, expected_status",
    [
        pytest.param(
            {"mailname": "", "postmaster-address": ""},
            BlockedStatus("Invalid charm configuration, check logs for details"),
            id="Multiple missing/invalid config options",
        ),
        pytest.param(
            {"mailname": ""},
            BlockedStatus("Invalid mailname: String should have at least 1 character"),
            id="Invalid mailname config option",
        ),
        pytest.param(
            {"postmaster-address": ""},
            BlockedStatus(
                "Invalid postmaster-address: value is not a valid email address: An email address must have an @-sign."
            ),
            id="Invalid postmaster-address config option",
        ),
        pytest.param(
            {"primary-unit": ""},
            BlockedStatus("Invalid primary-unit: String should have at least 1 character"),
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
