# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm state."""

import itertools
import logging
from collections.abc import Mapping
from enum import Enum
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)


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


def _parse_access_map(raw_map: str | None) -> dict[str, AccessMapValue]:
    """Parse access map input.

    Args:
        raw_map: the raw map content.

    Returns:
        the parsed map.
    """
    parsed_map = _parse_map(raw_map)
    return {key: AccessMapValue(value) for key, value in parsed_map.items()}


def _parse_list(raw_list: str | None) -> list[str]:
    """Parse list input.

    Args:
        raw_list: the list map content.

    Returns:
        a list of strings.
    """
    return yaml.safe_load(raw_list) if raw_list else []


class State(BaseModel):  # pylint: disable=too-few-public-methods,too-many-instance-attributes
    """The Postfix relay operator charm state.

    Attributes:
        relay_access_sources: Map of entries to restrict access based on CIDR source.
        restrict_recipients: Access map for restrictions by recipient address or domain.
        restrict_senders: Access map for restrictions by sender address or domain.
        relay_recipient_maps: Map that alias mail addresses or domains to addresses.
        sender_login_maps: List of authenticated users that can send mail.
        transport_maps: Map from recipient address to message delivery transport
            or next-hop destination.
        virtual_alias_maps: Map of aliases of mail addresses or domains to other local or
            remote addresses.
    """

    relay_access_sources: dict[str, AccessMapValue]
    restrict_recipients: dict[str, AccessMapValue]
    restrict_senders: dict[str, AccessMapValue]
    relay_recipient_maps: dict[str, str]
    sender_login_maps: dict[str, str]
    transport_maps: dict[str, str]
    virtual_alias_maps: dict[str, str]

    @classmethod
    def from_charm(cls, config: Mapping[str, Any]) -> "State":
        """Initialize the state from charm.

        Args:
            config: the charm configuration.

        Returns:
            Current charm state.

        Raises:
            ConfigurationError: if invalid state values were encountered.
        """
        try:
            relay_access_sources = _parse_access_map(config.get("relay_access_sources"))
            relay_recipient_maps = _parse_map(config.get("relay_recipient_maps"))
            restrict_recipients = _parse_access_map(config.get("restrict_recipients"))
            restrict_senders = _parse_access_map(config.get("restrict_senders"))
            sender_login_maps = _parse_map(config.get("sender_login_maps"))
            transport_maps = _parse_map(config.get("transport_maps"))
            virtual_alias_maps = _parse_map(config.get("virtual_alias_maps"))

            return cls(
                relay_access_sources=relay_access_sources,
                relay_recipient_maps=relay_recipient_maps,
                restrict_recipients=restrict_recipients,
                restrict_senders=restrict_senders,
                sender_login_maps=sender_login_maps,
                transport_maps=transport_maps,
                virtual_alias_maps=virtual_alias_maps,
            )

        except ValueError as exc:
            raise ConfigurationError("Invalid configuration") from exc
        except ValidationError as exc:
            error_fields = set(
                itertools.chain.from_iterable(error["loc"] for error in exc.errors())
            )
            error_field_str = " ".join(f"{f}" for f in error_fields)
            raise ConfigurationError(f"Invalid configuration: {error_field_str}") from exc
