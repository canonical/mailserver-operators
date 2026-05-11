# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""State unit tests."""

from typing import cast

import pytest
import yaml

import state


def test_state():
    """
    arrange: do nothing.
    act: initialize a charm state from valid configuration.
    assert: the state values are parsed correctly.
    """
    charm_config = {
        "relay_access_sources": """
            # Reject some made user.
            10.10.10.5: REJECT
            10.10.10.0/24: OK
        """,
        "relay_recipient_maps": """
            noreply@mydomain.local: noreply@mydomain.local
        """,
        "restrict_recipients": "mydomain.local: OK",
        "restrict_senders": "mydomain.local: REJECT",
        "sender_login_maps": """
            group@example.com: group
            group2@example.com: group2
        """,
        "transport_maps": """
            example.com: 'smtp:[mx.example.com]'
            admin.example1.com: 'smtp:[mx.example.com]'
        """,
        "virtual_alias_maps": """
            /^group@example.net/: group@example.com
            /^group2@example.net/: group2@example.com
        """,
    }
    charm_state = state.State.from_charm(config=charm_config)

    raw_relay_access_sources = yaml.safe_load(cast("str", charm_config["relay_access_sources"]))
    relay_access_sources = {
        key: state.AccessMapValue(value) for key, value in raw_relay_access_sources.items()
    }
    assert charm_state.relay_access_sources == relay_access_sources
    restrict_recipients_raw = yaml.safe_load(cast("str", charm_config["restrict_recipients"]))
    restrict_recipients = {
        key: state.AccessMapValue(value) for key, value in restrict_recipients_raw.items()
    }
    assert charm_state.restrict_recipients == restrict_recipients
    restrict_sender_raw = yaml.safe_load(cast("str", charm_config["restrict_senders"]))
    restrict_senders = {
        key: state.AccessMapValue(value) for key, value in restrict_sender_raw.items()
    }
    assert charm_state.restrict_senders == restrict_senders
    assert charm_state.sender_login_maps == yaml.safe_load(
        cast("str", charm_config["sender_login_maps"])
    )
    assert charm_state.transport_maps == yaml.safe_load(
        cast("str", charm_config["transport_maps"])
    )
    assert charm_state.virtual_alias_maps == yaml.safe_load(
        cast("str", charm_config["virtual_alias_maps"])
    )


def test_state_defaults():
    """
    arrange: do nothing.
    act: initialize a charm state from default configuration.
    assert: the state values are parsed correctly.
    """
    charm_state = state.State.from_charm(config={})

    assert charm_state.relay_access_sources == {}
    assert charm_state.restrict_recipients == {}
    assert charm_state.restrict_senders == {}
    assert charm_state.sender_login_maps == {}
    assert charm_state.transport_maps == {}
    assert charm_state.virtual_alias_maps == {}


def test_state_with_invalid_restrict_recipients():
    """
    arrange: do nothing.
    act: initialize a charm state from invalid configuration.
    assert: an InvalidStateError is raised.
    """
    charm_config = {
        "restrict_recipients": "recipient: invalid_value",
    }
    with pytest.raises(state.ConfigurationError):
        state.State.from_charm(config=charm_config)


def test_state_with_invalid_restrict_senders():
    """
    arrange: do nothing.
    act: initialize a charm state from invalid configuration.
    assert: an InvalidStateError is raised.
    """
    charm_config = {
        "restrict_senders": "sender: invalid_value",
    }
    with pytest.raises(state.ConfigurationError):
        state.State.from_charm(config=charm_config)
