# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Postfix service unit tests."""

import postfix
import state


def test_build_postfix_maps_returns_correct_data() -> None:
    """
    arrange: Define the charm state and expected dictionary of PostfixMap objects.
    act: Call build_postfix_maps.
    assert: The returned dictionary is identical to the expected dictionary.
    """
    charm_config = {
        # Values directly used by the function under test
        "relay_access_sources": "192.168.1.0/24: OK",
        "relay_recipient_maps": "user@example.com: OK",
        "restrict_recipients": "bad@example.com: REJECT",
        "restrict_senders": "spammer@example.com: REJECT",
        "sender_login_maps": "sender@example.com: user@example.com",
        "transport_maps": "domain.com: smtp:relay.example.com",
        "virtual_alias_maps": "alias@example.com: real@example.com",
    }
    charm_state = state.State.from_charm(config=charm_config)

    expected_maps = {
        "relay_access_sources": postfix.PostfixMap(
            type=state.PostfixLookupTableType.CIDR,
            path=postfix.POSTFIX_CONF_DIRPATH / "relay_access",
            content="192.168.1.0/24 OK\n",
        ),
        "relay_recipient_maps": postfix.PostfixMap(
            type=state.PostfixLookupTableType.HASH,
            path=postfix.POSTFIX_CONF_DIRPATH / "relay_recipient",
            content="user@example.com OK\n",
        ),
        "restrict_recipients": postfix.PostfixMap(
            type=state.PostfixLookupTableType.HASH,
            path=postfix.POSTFIX_CONF_DIRPATH / "restricted_recipients",
            content="bad@example.com REJECT\n",
        ),
        "restrict_senders": postfix.PostfixMap(
            type=state.PostfixLookupTableType.HASH,
            path=postfix.POSTFIX_CONF_DIRPATH / "restricted_senders",
            content="spammer@example.com REJECT\n",
        ),
        "sender_login_maps": postfix.PostfixMap(
            type=state.PostfixLookupTableType.HASH,
            path=postfix.POSTFIX_CONF_DIRPATH / "sender_login",
            content="sender@example.com user@example.com\n",
        ),
        "transport_maps": postfix.PostfixMap(
            type=state.PostfixLookupTableType.HASH,
            path=postfix.POSTFIX_CONF_DIRPATH / "transport",
            content="domain.com smtp:relay.example.com\n",
        ),
        "virtual_alias_maps": postfix.PostfixMap(
            type=state.PostfixLookupTableType.HASH,
            path=postfix.POSTFIX_CONF_DIRPATH / "virtual_alias",
            content="alias@example.com real@example.com\n",
        ),
    }

    maps = postfix.build_postfix_maps(charm_state)

    assert maps == expected_maps
