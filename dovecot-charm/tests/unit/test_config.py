# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
from unittest.mock import patch

from ops.model import BlockedStatus


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
