# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""State unit tests."""

from ipaddress import ip_network
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
        "additional_smtpd_recipient_restrictions": """
            - reject_non_fqdn_helo_hostname
            - reject_unknown_helo_hostname
        """,
        "admin_email": "example@domain.com",
        "allowed_relay_networks": """
            - 192.168.252.0/24
            - 192.168.253.0/24
        """,
        "append_x_envelope_to": True,
        "connection_limit": 200,
        "domain": "somain.example.com",
        "enable_rate_limits": True,
        "enable_reject_unknown_sender_domain": False,
        "enable_spf": True,
        "enable_smtp_auth": False,
        "header_checks": "- /^Received:/ HOLD",
        "restrict_sender_access": """
            - canonical.com
            - ubuntu.com
        """,
        "relay_domains": """
            - domain.example.com
            - domain2.example.com
        """,
        "relay_host": "smtp.relay",
        "smtp_auth_users": """
            - myuser1:$1$bPb0IPiM$kmrSMZkZvICKKHXu66daQ.
            - myuser2:$6$3r//F36qLB/J8rUfIIndaDtkxeb5iR3gs1uBn9fNyJDD1
        """,
        "smtp_header_checks": "- '/^Received:/ PREPEND X-Launchpad-Original-To: $1'",
        "spf_skip_addresses": """
            - 10.0.114.0/24
            - 10.1.1.0/24
        """,
        "tls_ciphers": "HIGH",
        "tls_exclude_ciphers": """
            - aNULL
            - eNULL
        """,
        "tls_policy_maps": """
            example.com: 'smtp:[mx.example.com]'
            admin.example.com: 'smtp:[mx.example.com]'
        """,
        "tls_protocols": """
            - '!SSLv2'
            - '!SSLv3'
        """,
        "tls_security_level": "may",
        "virtual_alias_domains": """
            - mydomain.local
            - mydomain2.local
        """,
        "virtual_alias_maps_type": "hash",
    }
    relay_access_sources = {
        "10.10.10.5": "REJECT",
        "10.10.10.0/24": "OK",
    }
    restrict_recipients = {"mydomain.local": "OK"}
    restrict_senders = {"mydomain.local": "REJECT"}
    relay_recipient_maps = {"noreply@mydomain.local": "noreply@mydomain.local"}
    sender_login_maps = {
        "group@example.com": "group",
        "group2@example.com": "group2",
    }
    transport_maps = {
        "example.com": "smtp:[mx.example.com]",
        "admin.example1.com": "smtp:[mx.example.com]",
    }
    virtual_alias_maps = {
        "/^group@example.net/": "group@example.com",
        "/^group2@example.net/": "group2@example.com",
    }
    charm_state = state.State.from_charm(
        config=charm_config,
        relay_access_sources=relay_access_sources,
        restrict_recipients=restrict_recipients,
        restrict_senders=restrict_senders,
        relay_recipient_maps=relay_recipient_maps,
        sender_login_maps=sender_login_maps,
        transport_maps=transport_maps,
        virtual_alias_maps=virtual_alias_maps,
    )

    assert charm_state.additional_smtpd_recipient_restrictions == (
        yaml.safe_load(cast("str", charm_config["additional_smtpd_recipient_restrictions"]))
    )
    assert charm_state.admin_email == charm_config["admin_email"]
    assert charm_state.allowed_relay_networks == [
        ip_network(value)
        for value in yaml.safe_load(cast("str", charm_config["allowed_relay_networks"]))
    ]
    assert charm_state.append_x_envelope_to
    assert charm_state.connection_limit == charm_config["connection_limit"]
    assert charm_state.domain == charm_config["domain"]
    assert charm_state.enable_rate_limits
    assert not charm_state.enable_reject_unknown_sender_domain
    assert charm_state.enable_spf
    assert not charm_state.enable_smtp_auth
    assert charm_state.header_checks == yaml.safe_load(cast("str", charm_config["header_checks"]))
    assert charm_state.relay_access_sources == {
        key: state.AccessMapValue(value) for key, value in relay_access_sources.items()
    }
    assert charm_state.relay_domains == yaml.safe_load(cast("str", charm_config["relay_domains"]))
    assert charm_state.relay_host == charm_config["relay_host"]
    assert charm_state.restrict_recipients == {
        key: state.AccessMapValue(value) for key, value in restrict_recipients.items()
    }
    assert charm_state.restrict_senders == {
        key: state.AccessMapValue(value) for key, value in restrict_senders.items()
    }
    assert charm_state.restrict_sender_access == ["canonical.com", "ubuntu.com"]
    assert charm_state.sender_login_maps == sender_login_maps
    assert charm_state.smtp_auth_users == yaml.safe_load(
        cast("str", charm_config["smtp_auth_users"])
    )
    assert charm_state.smtp_header_checks == yaml.safe_load(
        cast("str", charm_config["smtp_header_checks"])
    )
    assert charm_state.spf_skip_addresses == [
        ip_network(address)
        for address in yaml.safe_load(cast("str", charm_config["spf_skip_addresses"]))
    ]
    assert charm_state.tls_ciphers == state.SmtpTlsCipherGrade.HIGH
    assert charm_state.tls_exclude_ciphers == yaml.safe_load(
        cast("str", charm_config["tls_exclude_ciphers"])
    )
    assert charm_state.tls_policy_maps == yaml.safe_load(
        cast("str", charm_config["tls_policy_maps"])
    )
    assert charm_state.tls_protocols == yaml.safe_load(cast("str", charm_config["tls_protocols"]))
    assert charm_state.tls_security_level == state.SmtpTlsSecurityLevel.MAY
    assert charm_state.transport_maps == transport_maps
    assert charm_state.virtual_alias_domains == yaml.safe_load(
        cast("str", charm_config["virtual_alias_domains"])
    )
    assert charm_state.virtual_alias_maps == virtual_alias_maps
    assert charm_state.virtual_alias_maps_type == state.PostfixLookupTableType.HASH


def test_state_defaults():
    """
    arrange: do nothing.
    act: initialize a charm state from default configuration.
    assert: the state values are parsed correctly.
    """
    charm_config = {
        "append_x_envelope_to": False,
        "connection_limit": 100,
        "domain": "",
        "enable_rate_limits": False,
        "enable_reject_unknown_sender_domain": True,
        "enable_spf": False,
        "enable_smtp_auth": True,
        "tls_ciphers": "HIGH",
        "tls_exclude_ciphers": """
            - aNULL
            - eNULL
            - DES
            - 3DES
            - MD5
            - RC4
            - CAMELLIA
        """,
        "tls_protocols": """
            - '!SSLv2'
            - '!SSLv3'
        """,
        "tls_security_level": "may",
        "virtual_alias_maps_type": "hash",
    }
    charm_state = state.State.from_charm(
        config=charm_config,
        relay_access_sources={},
        restrict_recipients={},
        restrict_senders={},
        relay_recipient_maps={},
        sender_login_maps={},
        transport_maps={},
        virtual_alias_maps={},
    )

    assert charm_state.additional_smtpd_recipient_restrictions == []
    assert charm_state.admin_email is None
    assert charm_state.allowed_relay_networks == []
    assert not charm_state.append_x_envelope_to
    assert charm_state.connection_limit == 100
    assert charm_state.domain == ""
    assert not charm_state.enable_rate_limits
    assert charm_state.enable_reject_unknown_sender_domain
    assert not charm_state.enable_spf
    assert charm_state.enable_smtp_auth
    assert charm_state.header_checks == []
    assert charm_state.relay_access_sources == {}
    assert charm_state.relay_domains == []
    assert charm_state.relay_host is None
    assert charm_state.restrict_recipients == {}
    assert charm_state.restrict_senders == {}
    assert charm_state.restrict_sender_access == []
    assert charm_state.sender_login_maps == {}
    assert charm_state.smtp_auth_users == []
    assert charm_state.smtp_header_checks == []
    assert charm_state.spf_skip_addresses == []
    assert charm_state.tls_ciphers == state.SmtpTlsCipherGrade.HIGH
    assert charm_state.tls_exclude_ciphers == [
        "aNULL",
        "eNULL",
        "DES",
        "3DES",
        "MD5",
        "RC4",
        "CAMELLIA",
    ]
    assert charm_state.tls_policy_maps == {}
    assert charm_state.tls_protocols == ["!SSLv2", "!SSLv3"]
    assert charm_state.tls_security_level == state.SmtpTlsSecurityLevel.MAY
    assert charm_state.transport_maps == {}
    assert charm_state.virtual_alias_domains == []
    assert charm_state.virtual_alias_maps == {}
    assert charm_state.virtual_alias_maps_type == state.PostfixLookupTableType.HASH


def test_state_with_invalid_admin_email():
    """
    arrange: do nothing.
    act: initialize a charm state from invalid configuration.
    assert: an InvalidStateError is raised.
    """
    charm_config = {
        "admin_email": "example.domain.com",
        "append_x_envelope_to": False,
        "connection_limit": 100,
        "domain": "",
        "enable_rate_limits": False,
        "enable_reject_unknown_sender_domain": True,
        "enable_spf": False,
        "enable_smtp_auth": True,
        "tls_ciphers": "HIGH",
        "tls_exclude_ciphers": """
            - aNULL
            - eNULL
            - DES
            - 3DES
            - MD5
            - RC4
            - CAMELLIA
        """,
        "tls_protocols": """
            - '!SSLv2'
            - '!SSLv3'
        """,
        "tls_security_level": "may",
        "virtual_alias_maps_type": "hash",
    }
    with pytest.raises(state.ConfigurationError):
        state.State.from_charm(
            config=charm_config,
            relay_access_sources={},
            restrict_recipients={},
            restrict_senders={},
            relay_recipient_maps={},
            sender_login_maps={},
            transport_maps={},
            virtual_alias_maps={},
        )


def test_state_with_invalid_allowed_relay_networks():
    """
    arrange: do nothing.
    act: initialize a charm state from invalid configuration.
    assert: an InvalidStateError is raised.
    """
    charm_config = {
        "append_x_envelope_to": False,
        "allowed_relay_networks": "- 192.0.0.0/33",
        "connection_limit": 100,
        "domain": "",
        "enable_rate_limits": False,
        "enable_reject_unknown_sender_domain": True,
        "enable_spf": False,
        "enable_smtp_auth": True,
        "tls_ciphers": "HIGH",
        "tls_exclude_ciphers": """
            - aNULL
            - eNULL
            - DES
            - 3DES
            - MD5
            - RC4
            - CAMELLIA
        """,
        "tls_protocols": """
            - '!SSLv2'
            - '!SSLv3'
        """,
        "tls_security_level": "may",
        "virtual_alias_maps_type": "hash",
    }
    with pytest.raises(state.ConfigurationError):
        state.State.from_charm(
            config=charm_config,
            relay_access_sources={},
            restrict_recipients={},
            restrict_senders={},
            relay_recipient_maps={},
            sender_login_maps={},
            transport_maps={},
            virtual_alias_maps={},
        )


def test_state_with_invalid_connection_limit():
    """
    arrange: do nothing.
    act: initialize a charm state from invalid configuration.
    assert: an InvalidStateError is raised.
    """
    charm_config = {
        "append_x_envelope_to": False,
        "connection_limit": -1,
        "domain": "",
        "enable_rate_limits": False,
        "enable_reject_unknown_sender_domain": True,
        "enable_spf": False,
        "enable_smtp_auth": True,
        "tls_ciphers": "HIGH",
        "tls_exclude_ciphers": """
            - aNULL
            - eNULL
            - DES
            - 3DES
            - MD5
            - RC4
            - CAMELLIA
        """,
        "tls_protocols": """
            - '!SSLv2'
            - '!SSLv3'
        """,
        "tls_security_level": "may",
        "virtual_alias_maps_type": "hash",
    }
    with pytest.raises(state.ConfigurationError):
        state.State.from_charm(
            config=charm_config,
            relay_access_sources={},
            restrict_recipients={},
            restrict_senders={},
            relay_recipient_maps={},
            sender_login_maps={},
            transport_maps={},
            virtual_alias_maps={},
        )


def test_state_with_invalid_restrict_recipients():
    """
    arrange: do nothing.
    act: initialize a charm state from invalid configuration.
    assert: an InvalidStateError is raised.
    """
    charm_config = {
        "append_x_envelope_to": False,
        "connection_limit": -1,
        "domain": "",
        "enable_rate_limits": False,
        "enable_reject_unknown_sender_domain": True,
        "enable_spf": False,
        "enable_smtp_auth": True,
        "restrict_recipients": "recipient: invalid_value",
        "tls_ciphers": "HIGH",
        "tls_exclude_ciphers": """
            - aNULL
            - eNULL
            - DES
            - 3DES
            - MD5
            - RC4
            - CAMELLIA
        """,
        "tls_protocols": """
            - '!SSLv2'
            - '!SSLv3'
        """,
        "tls_security_level": "may",
        "virtual_alias_maps_type": "hash",
    }
    with pytest.raises(state.ConfigurationError):
        state.State.from_charm(
            config=charm_config,
            relay_access_sources={},
            restrict_recipients={},
            restrict_senders={},
            relay_recipient_maps={},
            sender_login_maps={},
            transport_maps={},
            virtual_alias_maps={},
        )


def test_state_with_invalid_restrict_senders():
    """
    arrange: do nothing.
    act: initialize a charm state from invalid configuration.
    assert: an InvalidStateError is raised.
    """
    charm_config = {
        "append_x_envelope_to": False,
        "connection_limit": -1,
        "domain": "",
        "enable_rate_limits": False,
        "enable_reject_unknown_sender_domain": True,
        "enable_spf": False,
        "enable_smtp_auth": True,
        "restrict_senders": "sender: invalid_value",
        "tls_ciphers": "HIGH",
        "tls_exclude_ciphers": """
            - aNULL
            - eNULL
            - DES
            - 3DES
            - MD5
            - RC4
            - CAMELLIA
        """,
        "tls_protocols": """
            - '!SSLv2'
            - '!SSLv3'
        """,
        "tls_security_level": "may",
        "virtual_alias_maps_type": "hash",
    }
    with pytest.raises(state.ConfigurationError):
        state.State.from_charm(
            config=charm_config,
            relay_access_sources={},
            restrict_recipients={},
            restrict_senders={},
            relay_recipient_maps={},
            sender_login_maps={},
            transport_maps={},
            virtual_alias_maps={},
        )


def test_state_with_invalid_spf_skip_addresses():
    """
    arrange: do nothing.
    act: initialize a charm state from invalid configuration.
    assert: an InvalidStateError is raised.
    """
    charm_config = {
        "append_x_envelope_to": False,
        "connection_limit": -1,
        "domain": "",
        "enable_rate_limits": False,
        "enable_reject_unknown_sender_domain": True,
        "enable_spf": False,
        "enable_smtp_auth": True,
        "spf_skip_addresses": "- 192.0.0.0/33",
        "tls_ciphers": "HIGH",
        "tls_exclude_ciphers": """
            - aNULL
            - eNULL
            - DES
            - 3DES
            - MD5
            - RC4
            - CAMELLIA
        """,
        "tls_protocols": """
            - '!SSLv2'
            - '!SSLv3'
        """,
        "tls_security_level": "may",
        "virtual_alias_maps_type": "hash",
    }
    with pytest.raises(state.ConfigurationError):
        state.State.from_charm(
            config=charm_config,
            relay_access_sources={},
            restrict_recipients={},
            restrict_senders={},
            relay_recipient_maps={},
            sender_login_maps={},
            transport_maps={},
            virtual_alias_maps={},
        )


def test_state_with_invalid_tls_ciphers():
    """
    arrange: do nothing.
    act: initialize a charm state from invalid configuration.
    assert: an InvalidStateError is raised.
    """
    charm_config = {
        "append_x_envelope_to": False,
        "connection_limit": -1,
        "domain": "",
        "enable_rate_limits": False,
        "enable_reject_unknown_sender_domain": True,
        "enable_spf": False,
        "enable_smtp_auth": True,
        "tls_ciphers": "invalid",
        "tls_exclude_ciphers": """
            - aNULL
            - eNULL
            - DES
            - 3DES
            - MD5
            - RC4
            - CAMELLIA
        """,
        "tls_protocols": """
            - '!SSLv2'
            - '!SSLv3'
        """,
        "tls_security_level": "may",
        "virtual_alias_maps_type": "hash",
    }
    with pytest.raises(state.ConfigurationError):
        state.State.from_charm(
            config=charm_config,
            relay_access_sources={},
            restrict_recipients={},
            restrict_senders={},
            relay_recipient_maps={},
            sender_login_maps={},
            transport_maps={},
            virtual_alias_maps={},
        )


def test_state_with_invalid_tls_security_level():
    """
    arrange: do nothing.
    act: initialize a charm state from invalid configuration.
    assert: an InvalidStateError is raised.
    """
    charm_config = {
        "append_x_envelope_to": False,
        "connection_limit": -1,
        "domain": "",
        "enable_rate_limits": False,
        "enable_reject_unknown_sender_domain": True,
        "enable_spf": False,
        "enable_smtp_auth": True,
        "tls_ciphers": "HIGH",
        "tls_exclude_ciphers": """
            - aNULL
            - eNULL
            - DES
            - 3DES
            - MD5
            - RC4
            - CAMELLIA
        """,
        "tls_protocols": """
            - '!SSLv2'
            - '!SSLv3'
        """,
        "tls_security_level": "invalid",
        "virtual_alias_maps_type": "hash",
    }
    with pytest.raises(state.ConfigurationError):
        state.State.from_charm(
            config=charm_config,
            relay_access_sources={},
            restrict_recipients={},
            restrict_senders={},
            relay_recipient_maps={},
            sender_login_maps={},
            transport_maps={},
            virtual_alias_maps={},
        )


def test_state_with_invalid_virtual_alias_maps_type():
    """
    arrange: do nothing.
    act: initialize a charm state from invalid configuration.
    assert: an InvalidStateError is raised.
    """
    charm_config = {
        "append_x_envelope_to": False,
        "connection_limit": -1,
        "domain": "",
        "enable_rate_limits": False,
        "enable_reject_unknown_sender_domain": True,
        "enable_spf": False,
        "enable_smtp_auth": True,
        "tls_ciphers": "HIGH",
        "tls_exclude_ciphers": """
            - aNULL
            - eNULL
            - DES
            - 3DES
            - MD5
            - RC4
            - CAMELLIA
        """,
        "tls_protocols": """
            - '!SSLv2'
            - '!SSLv3'
        """,
        "tls_security_level": "may",
        "virtual_alias_maps_type": "invalid",
    }
    with pytest.raises(state.ConfigurationError):
        state.State.from_charm(
            config=charm_config,
            relay_access_sources={},
            restrict_recipients={},
            restrict_senders={},
            relay_recipient_maps={},
            sender_login_maps={},
            transport_maps={},
            virtual_alias_maps={},
        )
