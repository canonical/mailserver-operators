# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm state."""

import itertools
import logging
from collections.abc import Mapping
from enum import Enum
from ipaddress import ip_network
from typing import Any

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    IPvAnyNetwork,
    ValidationError,
)
from typing_extensions import Annotated

logger = logging.getLogger(__name__)


# RFC-1034 and RFC-2181 compliance REGEX for validating FQDNs
HOSTNAME_REGEX = (
    r"(?=.{1,253})(?!.*--.*)(?:(?!-)(?![0-9])[a-zA-Z0-9-]"
    r"{1,63}(?<!-)\.){1,}(?:(?!-)[a-zA-Z0-9-]{1,63}(?<!-))"
)


class CharmStateBaseError(Exception):
    """Represents an error with charm state."""


class ConfigurationError(CharmStateBaseError):
    """Exception raised when a charm configuration is found to be invalid.

    Attributes:
        msg: Explanation of the error.
    """

    def __init__(self, msg: str):
        """Initialize a new instance of the ConfigurationError exception.

        Args:
            msg: Explanation of the error.
        """
        self.msg = msg


class SmtpTlsCipherGrade(Enum):
    """TLS cipher grade.

    Attributes:
        HIGH: "HIGH"
        MEDIUM: "MEDIUM"
        NULL: "NULL"
        LOW: "LOW"º
        EXPORT: "EXPORT"
    """

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    NULL = "NULL"
    LOW = "LOW"
    EXPORT = "EXPORT"


class SmtpTlsSecurityLevel(Enum):
    """TLS secutiry level.

    Attributes:
        NONE: "none"
        MAY: "may"
        ENCRYPT: "encrypt"
    """

    NONE = "none"
    MAY = "may"
    ENCRYPT = "encrypt"


class PostfixLookupTableType(Enum):
    """Postfix lookup table types.

    Attributes:
        HASH: "hash"
        REGEXP: "regexp"
        CIDR: "cidr"
    """

    HASH = "hash"
    REGEXP = "regexp"
    CIDR = "cidr"


class AccessMapValue(Enum):
    """Postfix access map valid values.

    Attributes:
        OK: "OK"
        REJECT: "REJECT"
        RESTRICTED: "restricted"
    """

    OK = "OK"
    REJECT = "REJECT"
    RESTRICTED = "restricted"


def _parse_map(raw_map: str | None) -> dict[str, str]:
    """Parse map input.

    Returns:
        the parsed map.
    """
    return yaml.safe_load(raw_map) if raw_map else {}


def _parse_list(raw_list: str | None) -> list[str]:
    """Parse list input.

    Args:
        raw_list: the list map content.

    Returns:
        a list of strings.
    """
    return yaml.safe_load(raw_list) if raw_list else []


class State(
    BaseModel
):  # pylint: disable=too-few-public-methods,too-many-arguments,too-many-instance-attributes,too-many-positional-arguments
    """The Postfix relay operator charm state.

    Attributes:
        additional_smtpd_recipient_restrictions: List of additional recipient restrictions.
        admin_email: Administrator's email address where root@ emails will go to.
        allowed_relay_networks: List of allowed networks to relay without authenticating.
        append_x_envelope_to: Append the X-Envelope-To header.
        connection_limit: Maximum number of SMTP connections allowed.
        domain: Primary domain for hostname generation.
        enable_rate_limits: Enable default rate limiting features.
        enable_reject_unknown_sender_domain: Reject email when sender's domain cannot be resolved.
        enable_smtp_auth: If SMTP authentication is enabled.
        enable_spf: If SPF checks are enabled.
        header_checks: Header checks to perform on inbound email.
        relay_access_sources: Map of entries to restrict access based on CIDR source.
        relay_domains: List of destination domains to relay mail to.
        restrict_recipients: Access map for restrictions by recipient address or domain.
        restrict_senders: Access map for restrictions by sender address or domain.
        relay_host: Postfix relay host to forward mail to.
        relay_recipient_maps: Map that alias mail addresses or domains to
            addresses.
        restrict_sender_access: List of domains, addresses or hosts to restrict relay from.
        sender_login_maps: List of authenticated users that can send mail.
        smtp_auth_users: List of user and crypt password hashe pairs separated by ':'.
        smtp_header_checks: List of header checks to perform on outbound email.
        spf_skip_addresses: List of CIDR addresses to skip SPF checks.
        tls_ciphers: Minimum TLS cipher grade for TLS encryption.
        tls_exclude_ciphers: List of TLS ciphers or cipher types to exclude from the cipher list.
        tls_policy_maps: Map for TLS policy.
        tls_protocols: List of TLS protocols accepted by the Postfix SMTP.
        tls_security_level: The TLS security level.
        transport_maps: Map from recipient address to message delivery transport
            or next-hop destination.
        virtual_alias_domains: List of domains for which all addresses are aliased.
        virtual_alias_maps: Map of aliases of mail addresses or domains to other local or
            remote addresses.
        virtual_alias_maps_type: The virtual alias map type.
    """

    model_config = ConfigDict(regex_engine="python-re")  # noqa: DCO063

    additional_smtpd_recipient_restrictions: list[str]
    admin_email: EmailStr | None
    allowed_relay_networks: list[IPvAnyNetwork]
    append_x_envelope_to: bool
    domain: str = Field(pattern=rf"^(?:$|{HOSTNAME_REGEX})$")
    enable_rate_limits: bool
    enable_reject_unknown_sender_domain: bool
    enable_smtp_auth: bool
    enable_spf: bool
    header_checks: list[str]
    relay_access_sources: dict[str, AccessMapValue]
    relay_domains: list[Annotated[str, Field(min_length=1)]]
    restrict_recipients: dict[str, AccessMapValue]
    restrict_senders: dict[str, AccessMapValue]
    relay_host: Annotated[str, Field(min_length=1)] | None
    relay_recipient_maps: dict[str, str]
    restrict_sender_access: list[Annotated[str, Field(min_length=1)]]
    sender_login_maps: dict[str, str]
    smtp_auth_users: list[str]
    smtp_header_checks: list[str]
    spf_skip_addresses: list[IPvAnyNetwork]
    tls_ciphers: SmtpTlsCipherGrade | None
    tls_exclude_ciphers: list[Annotated[str, Field(min_length=1)]]
    tls_policy_maps: dict[str, str]
    tls_protocols: list[Annotated[str, Field(min_length=1)]]
    tls_security_level: SmtpTlsSecurityLevel | None
    transport_maps: dict[str, str]
    virtual_alias_domains: list[Annotated[str, Field(min_length=1)]]
    virtual_alias_maps: dict[str, str]
    virtual_alias_maps_type: PostfixLookupTableType
    connection_limit: int = Field(ge=0)

    @classmethod
    def from_charm(
        cls,
        config: Mapping[str, Any],
        relay_access_sources: dict[str, AccessMapValue],
        restrict_recipients: dict[str, AccessMapValue],
        restrict_senders: dict[str, AccessMapValue],
        relay_recipient_maps: dict[str, str],
        sender_login_maps: dict[str, str],
        transport_maps: dict[str, str],
        virtual_alias_maps: dict[str, str],
    ) -> "State":
        """Initialize the state from charm.

        Args:
            config: the charm configuration.
            relay_access_sources: Map of entries to restrict access based on CIDR source.
            restrict_recipients: Access map for restrictions by recipient address or domain.
            restrict_senders: Access map for restrictions by sender address or domain.
            relay_recipient_maps: Map that alias mail addresses or domains to addresses.
            sender_login_maps: List of authenticated users that can send mail.
            transport_maps: Map from recipient address to message delivery transport
                or next-hop destination.
            virtual_alias_maps: Map of aliases of mail addresses or domains to other local or
                remote addresses.

        Returns:
            Current charm state.

        Raises:
            ConfigurationError: if invalid state values were encountered.
        """
        try:
            allowed_relay_networks = [
                ip_network(value) for value in _parse_list(config.get("allowed_relay_networks"))
            ]
            additional_smtpd_recipient_restrictions = _parse_list(
                config.get("additional_smtpd_recipient_restrictions")
            )

            return cls(
                additional_smtpd_recipient_restrictions=additional_smtpd_recipient_restrictions,
                admin_email=config.get("admin_email"),
                allowed_relay_networks=allowed_relay_networks,
                append_x_envelope_to=config.get("append_x_envelope_to"),  # type: ignore[arg-type]
                connection_limit=config.get("connection_limit"),  # type: ignore[arg-type]
                domain=config.get("domain"),  # type: ignore[arg-type]
                enable_rate_limits=config.get("enable_rate_limits"),  # type: ignore[arg-type]
                enable_reject_unknown_sender_domain=config.get(
                    "enable_reject_unknown_sender_domain"
                ),  # type: ignore[arg-type]
                enable_smtp_auth=config.get("enable_smtp_auth"),  # type: ignore[arg-type]
                enable_spf=config.get("enable_spf"),  # type: ignore[arg-type]
                header_checks=_parse_list(config.get("header_checks")),
                relay_access_sources=relay_access_sources,
                relay_domains=_parse_list(config.get("relay_domains")),
                relay_host=config.get("relay_host"),
                relay_recipient_maps=relay_recipient_maps,
                restrict_recipients=restrict_recipients,
                restrict_senders=restrict_senders,
                restrict_sender_access=_parse_list(config.get("restrict_sender_access")),
                sender_login_maps=sender_login_maps,
                smtp_auth_users=_parse_list(config.get("smtp_auth_users")),
                smtp_header_checks=_parse_list(config.get("smtp_header_checks")),
                spf_skip_addresses=_parse_list(
                    config.get("spf_skip_addresses")
                ),  # type: ignore[arg-type]
                tls_ciphers=(
                    SmtpTlsCipherGrade(config.get("tls_ciphers"))
                    if config.get("tls_ciphers")
                    else None
                ),
                tls_exclude_ciphers=_parse_list(config.get("tls_exclude_ciphers")),
                tls_policy_maps=_parse_map(config.get("tls_policy_maps")),
                tls_protocols=_parse_list(config.get("tls_protocols")),
                tls_security_level=(
                    SmtpTlsSecurityLevel(config.get("tls_security_level"))
                    if config.get("tls_security_level")
                    else None
                ),
                transport_maps=transport_maps,
                virtual_alias_domains=_parse_list(config.get("virtual_alias_domains")),
                virtual_alias_maps=virtual_alias_maps,
                virtual_alias_maps_type=PostfixLookupTableType(
                    config.get("virtual_alias_maps_type")
                ),
            )

        except ValueError as exc:
            raise ConfigurationError("Invalid configuration") from exc
        except ValidationError as exc:
            error_fields = set(
                itertools.chain.from_iterable(error["loc"] for error in exc.errors())
            )
            error_field_str = " ".join(f"{f}" for f in error_fields)
            raise ConfigurationError(f"Invalid configuration: {error_field_str}") from exc
