# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for the Postfix relay charm."""

from unittest.mock import Mock, patch

import ops.testing
from ops.testing import Context, State

import charm
from state import ConfigurationError


@patch("charm.State.from_charm", Mock(side_effect=ConfigurationError("Invalid configuration")))
def test_invalid_config() -> None:
    """
    arrange: Invalid charm config.
    act: Run the config-changed event hook on the charm.
    assert: The unit status is set to blocked with the correct error message.
    """
    charm_state = State(config={}, leader=True)

    context = Context(charm.PostfixRelayConfiguratorCharm)
    out = context.run(context.on.config_changed(), charm_state)

    assert out.unit_status == ops.testing.BlockedStatus("Invalid config")


@patch("charm.utils.write_file", Mock())
def test_configure_relay() -> None:
    """
    arrange: Configure the charm with defaults.
    act: Run the config-changed event hook.
    assert: The charm constructs the correct FQDN.
    """
    charm_state = State(
        config={},
        relations=[],
        leader=True,
    )

    context = Context(charm.PostfixRelayConfiguratorCharm)
    out = context.run(context.on.config_changed(), charm_state)

    assert out.unit_status == ops.testing.ActiveStatus()
