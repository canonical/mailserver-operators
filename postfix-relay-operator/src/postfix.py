# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Postfix Service Layer."""

from pathlib import Path
from typing import NamedTuple

from pydantic import IPvAnyNetwork

import utils
from state import AccessMapValue, PostfixLookupTableType, State

POSTFIX_CONF_DIRPATH = Path("/etc/postfix")
POSTFIX_MAP_FILES = [
    "/etc/postfix/relay_recipient",
    "/etc/postfix/restricted_recipients",
    "/etc/postfix/restricted_senders",
    "/etc/postfix/access",
    "/etc/postfix/sender_login",
    "/etc/postfix/tls_policy",
    "/etc/postfix/transport_maps",
    "/etc/postfix/virtual_alias",
]


def _smtpd_relay_restrictions(charm_state: State) -> list[str]:
    smtpd_relay_restrictions = ["permit_mynetworks"]
    if bool(charm_state.relay_access_sources):
        smtpd_relay_restrictions.append("check_client_access cidr:/etc/postfix/relay_access")

    if charm_state.enable_smtp_auth:
        if charm_state.sender_login_maps:
            smtpd_relay_restrictions.append("reject_known_sender_login_mismatch")
        if charm_state.restrict_senders:
            smtpd_relay_restrictions.append("reject_sender_login_mismatch")
        smtpd_relay_restrictions.append("permit_sasl_authenticated")

    smtpd_relay_restrictions.append("defer_unauth_destination")

    return smtpd_relay_restrictions


def smtpd_sender_restrictions(charm_state: State) -> list[str]:
    """Generate the smtpd_sender_restrictions.

    Args:
        charm_state: the charm state.

    Returns: the list of restrictions.
    """
    restrictions = []
    if charm_state.enable_reject_unknown_sender_domain:
        restrictions.append("reject_unknown_sender_domain")
    restrictions.append("check_sender_access hash:/etc/postfix/access")
    if charm_state.restrict_sender_access:
        restrictions.append("reject")

    return restrictions


def _smtpd_recipient_restrictions(charm_state: State) -> list[str]:
    smtpd_recipient_restrictions = []
    if charm_state.append_x_envelope_to:
        smtpd_recipient_restrictions.append(
            "check_recipient_access regexp:/etc/postfix/append_envelope_to_header"
        )

    if charm_state.restrict_senders:
        smtpd_recipient_restrictions.append(
            "check_sender_access hash:/etc/postfix/restricted_senders"
        )
    smtpd_recipient_restrictions.extend(charm_state.additional_smtpd_recipient_restrictions)

    if charm_state.enable_spf:
        smtpd_recipient_restrictions.append("check_policy_service unix:private/policyd-spf")

    return smtpd_recipient_restrictions


def construct_postfix_config_params(  # pylint: disable=too-many-arguments
    *,
    charm_state: State,
    tls_dh_params_path: str,
    tls_cert_path: str,
    tls_key_path: str,
    tls_cert_key_path: str,
    fqdn: str,
    hostname: str,
    milters: str,
) -> dict[str, str | int | bool | None]:
    """Prepare the context for rendering Postfix configuration files.

    Args:
        charm_state: The current state of the charm.
        tls_dh_params_path: Path to the Diffie-Hellman parameters file for TLS.
        tls_cert_path: Path to the TLS certificate file.
        tls_key_path: Path to the TLS private key file.
        tls_cert_key_path: Path to the combined certificate and key file for TLS.
        fqdn: Fully Qualified Domain Name of the system.
        hostname: Hostname of the system.
        milters: String representing the milters to be used by Postfix.

    Returns:
        str: The context for remndering Postfix configuration file content.
    """
    return {
        "fqdn": fqdn,
        "hostname": hostname,
        "connection_limit": charm_state.connection_limit,
        "enable_rate_limits": charm_state.enable_rate_limits,
        "enable_smtp_auth": charm_state.enable_smtp_auth,
        "enable_spf": charm_state.enable_spf,
        "header_checks": bool(charm_state.header_checks),
        "milter": milters,
        "mynetworks": ",".join(charm_state.allowed_relay_networks),
        "relayhost": charm_state.relay_host,
        "relay_domains": " ".join(charm_state.relay_domains),
        "relay_recipient_maps": bool(charm_state.relay_recipient_maps),
        "restrict_recipients": bool(charm_state.restrict_recipients),
        "smtp_header_checks": bool(charm_state.smtp_header_checks),
        "smtpd_recipient_restrictions": ", ".join(_smtpd_recipient_restrictions(charm_state)),
        "smtpd_relay_restrictions": ", ".join(_smtpd_relay_restrictions(charm_state)),
        "smtpd_sender_restrictions": ", ".join(smtpd_sender_restrictions(charm_state)),
        "tls_cert_key": tls_cert_key_path,
        "tls_cert": tls_cert_path,
        "tls_key": tls_key_path,
        "tls_ciphers": charm_state.tls_ciphers.value if charm_state.tls_ciphers else None,
        "tls_dh_params": tls_dh_params_path,
        "tls_exclude_ciphers": ", ".join(charm_state.tls_exclude_ciphers),
        "tls_protocols": " ".join(charm_state.tls_protocols),
        "tls_security_level": (
            charm_state.tls_security_level.value if charm_state.tls_security_level else None
        ),
        "transport_maps": bool(charm_state.transport_maps),
        "virtual_alias_domains": " ".join(charm_state.virtual_alias_domains),
        "virtual_alias_maps": bool(charm_state.virtual_alias_maps),
        "virtual_alias_maps_type": charm_state.virtual_alias_maps_type.value,
    }


class PostfixMap(NamedTuple):
    """Represents a Postfix lookup table and its source file content.

    Attributes:
        type: The type of the Postfix lookup table (e.g., 'hash').
        path: The path to the map's source file.
        content: The content to be written to the map's source file.
        source: The Postfix lookup table source string
    """

    type: PostfixLookupTableType
    path: Path
    content: str

    @property
    def source(self) -> str:
        """Return the full Postfix lookup table source string."""
        return f"{self.type.value}:{self.path}"


def _create_map(type_: str | PostfixLookupTableType, name: str, content: str) -> PostfixMap:
    type_ = type_ if isinstance(type_, PostfixLookupTableType) else PostfixLookupTableType(type_)
    return PostfixMap(
        type=type_,
        path=POSTFIX_CONF_DIRPATH / name,
        content=f"{content}\n",
    )


def build_postfix_maps(charm_state: State) -> dict[str, PostfixMap]:
    """Ensure various postfix files exist and are up-to-date with the current charm state.

    Args:
        charm_state: current charm state.

    Returns:
        A dictionary mapping map names to the generated PostfixMap objects.
    """
    # Create a map of all the maps we may need to create/update from the charm state.
    maps = {
        "header_checks": _create_map(
            PostfixLookupTableType.REGEXP,
            "header_checks",
            ";".join(charm_state.header_checks),
        ),
        "sender_access": _create_map(
            PostfixLookupTableType.HASH,
            "access",
            "\n".join([f"{domain:35} OK" for domain in charm_state.restrict_sender_access]),
        ),
        "smtp_header_checks": _create_map(
            PostfixLookupTableType.REGEXP,
            "smtp_header_checks",
            ";".join(charm_state.smtp_header_checks),
        ),
        "tls_policy_maps": _create_map(
            PostfixLookupTableType.HASH,
            "tls_policy",
            "\n".join([f"{key} {value}" for key, value in charm_state.tls_policy_maps.items()]),
        ),
    }

    return maps


def construct_policyd_spf_config_file_content(spf_skip_addresses: "list[IPvAnyNetwork]") -> str:
    """Generate the configuration content for the policyd-spf service.

    Args:
        spf_skip_addresses: A list of IP addresses or networks to exclude from SPF checks.

    Returns:
        str: The rendered configuration file content for policyd-spf.
    """
    context = {
        "skip_addresses": ",".join([str(address) for address in spf_skip_addresses]),
    }
    return utils.render_jinja2_template(context, "templates/policyd_spf_conf.tmpl")


def _parse_access_map(path: Path) -> dict[str, AccessMapValue]:
    if path.exists():
        return {key: AccessMapValue(value) for key, value in _parse_map(path).items()}
    return {}


def _parse_map(path: Path) -> dict[str, str]:
    if path.exists():
        raw_content = path.read_text("utf-8")
        return {line.split(" ")[0]: line.split(" ")[1] for line in raw_content.split("\n")}
    return {}


def _parse_list(path: Path) -> list[str]:
    if path.exists():
        raw_content = path.read_text("utf-8")
        return raw_content.split("\n")
    return []


def fetch_relay_access_sources() -> dict[str, AccessMapValue]:
    """Parse relay access sources from the configuration files.

    Returns:
        the map of access sources.
    """
    return _parse_access_map(POSTFIX_CONF_DIRPATH / "relay_access")


def fetch_relay_recipient_maps() -> dict[str, str]:
    """Parse relay recipient maps from the configuration files.

    Returns:
        the relay recipient maps.
    """
    return _parse_map(POSTFIX_CONF_DIRPATH / "relay_recipient")


def fetch_restrict_recipients() -> dict[str, AccessMapValue]:
    """Parse restrict recipients from the configuration files.

    Returns:
        the restricted recipients maps.
    """
    return _parse_access_map(POSTFIX_CONF_DIRPATH / "restricted_recipients")


def fetch_restrict_senders() -> dict[str, AccessMapValue]:
    """Parse restrict senders from the configuration files.

    Returns:
        the restricted senders maps.
    """
    return _parse_access_map(POSTFIX_CONF_DIRPATH / "restricted_senders")


def fetch_sender_access() -> list[str]:
    """Parse sender access from the configuration files.

    Returns:
        the list of sender access addresses.
    """
    return [
        line.replace(" OK", "").strip() for line in _parse_list(POSTFIX_CONF_DIRPATH / "access")
    ]


def fetch_sender_login_maps() -> dict[str, str]:
    """Parse sender login maps from the configuration files.

    Returns:
        the sender login maps.
    """
    return _parse_map(POSTFIX_CONF_DIRPATH / "sender_login")


def fetch_transport_maps() -> dict[str, str]:
    """Parse transport maps from the configuration files.

    Returns:
        the transport maps.
    """
    return _parse_map(POSTFIX_CONF_DIRPATH / "transport_maps")


def fetch_virtual_alias_maps() -> dict[str, str]:
    """Parse virtual alias maps from the configuration files.

    Returns:
        the virtual alias maps.
    """
    return _parse_map(POSTFIX_CONF_DIRPATH / "virtual_alias_maps")
