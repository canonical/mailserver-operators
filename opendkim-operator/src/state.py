# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""OpenDKIM state."""

import logging
import typing
from pathlib import Path

import ops
import yaml
from pydantic import BaseModel, ValidationError, computed_field

logger = logging.getLogger(__name__)

OPENDKIM_MILTER_PORT = 8892
OPENDKIM_KEYS_PATH = Path("/var/snap/opendkim/current/etc/dkimkeys")
OPENDKIM_SIGNINGTABLE_PATH = OPENDKIM_KEYS_PATH / "signingtable"
OPENDKIM_KEYTABLE_PATH = OPENDKIM_KEYS_PATH / "keytable"


# https://datatracker.ietf.org/doc/html/rfc6376#section-5.4
DEFAULT_SIGN_HEADERS = (
    "From,Reply-To,Subject,Date,To,Cc"
    ",Resent-From,Resent-Date,Resent-To,Resent-Cc"
    ",In-Reply-To,References"
    ",MIME-Version,Message-ID,Content-Type"
)


class InvalidCharmConfigError(Exception):
    """Exception raised when the parsed charm config is invalid."""


class OpenDKIMConfig(BaseModel):
    """OpenDKIM configuration.

    Attrs:
        canonicalization: DKIM canonicalization scheme.
        socket: Socket where OpenDKIM listens.
        signheaders: Header Fields to Sign.
        internalhosts: Set internal hosts whose mail should be signed.
        mode: OpenDKIM model.
        signingtable: OpenDKIM SigningTable as a pair or values per line.
        keytable: OpenDKIM KeyTable as a pair or values per line. Uses refile.
        private_keys: Dict with the filename without extension as key and the private key as value.
        trusted_sources: List of trusted networks/hosts that bypass DKIM verification.
        signing_mode: True if in signing model.
        verify_mode: True if in verify model.
        signingtable_path: Path to the signingtable file.
        keytable_path:  to the keytable file.
    """

    canonicalization: str = "relaxed/relaxed"
    socket: str = f"inet:{OPENDKIM_MILTER_PORT}"
    signheaders: str = DEFAULT_SIGN_HEADERS
    internalhosts: str = "0.0.0.0/0"
    mode: str = "sv"
    signingtable: list[typing.Tuple[str, str]]
    keytable: list[list[str]]
    private_keys: dict[str, str]
    trusted_sources: list[str] = []
    signingtable_path: Path = OPENDKIM_SIGNINGTABLE_PATH
    keytable_path: Path = OPENDKIM_KEYTABLE_PATH

    @computed_field  # type: ignore[misc]
    @property
    def signing_mode(self) -> bool:
        """Return True if the charm works in signing mode."""
        return "s" in self.mode

    @computed_field  # type: ignore[misc]
    @property
    def verify_mode(self) -> bool:
        """Return True if the charm works in verify mode."""
        return "v" in self.mode

    @classmethod
    def from_charm(cls, config: ops.model.ConfigData, model: ops.model.Model) -> typing.Self:
        """Return a new OpenDKIM configuration from the OpenDKIMCharm config and model.

        Args:
          config: Config options from the charm.
          model: Model for the charm.

        Raises:
          InvalidCharmConfigError: When the configuration from the charm is not valid.

        Return:
          Configuration created from the charm.
        """
        errors = []
        try:
            signingtable = _parse_yaml_config_option(config, "signingtable")
        except ValueError as e:
            errors.append(str(e))

        try:
            keytable = _parse_yaml_config_option(config, "keytable")
        except ValueError as e:
            errors.append(str(e))

        private_keys_secret_id = typing.cast(typing.Optional[str], config.get("private-keys"))
        if not private_keys_secret_id:
            errors.append("empty private-keys configuration")

        mode = typing.cast(str, config.get("mode", "sv"))
        trusted_sources = _parse_trusted_sources(
            typing.cast(typing.Optional[str], config.get("trusted-sources"))
        )

        if errors:
            raise InvalidCharmConfigError(" - ".join(errors))

        secret = model.get_secret(id=typing.cast(str, private_keys_secret_id))

        private_keys = secret.get_content(refresh=True)
        try:
            return cls(
                signingtable=signingtable,
                keytable=keytable,
                private_keys=private_keys,
                mode=mode,
                trusted_sources=trusted_sources,
            )
        except ValidationError as exc:
            logger.error(str(exc))
            error_field_str = ",".join(f"{field}" for field in get_invalid_config_fields(exc))
            raise InvalidCharmConfigError(f"wrong config options: {error_field_str}.") from exc


def _parse_yaml_config_option(config_data: ops.model.ConfigData, config_name: str) -> typing.Any:
    """Return the parsed YAML from a configuration option."""
    config_value = typing.cast(typing.Optional[str], config_data.get(config_name))
    if not config_value:
        raise ValueError(f"empty {config_name} configuration")
    try:
        return yaml.safe_load(config_value)
    except yaml.YAMLError as exc:
        logger.exception("Failed loading %s", config_name)
        raise ValueError(f"wrong {config_name} format") from exc


def _parse_trusted_sources(raw_value: typing.Optional[str]) -> list[str]:
    """Parse a comma-separated list of trusted sources into a list of stripped entries.

    Args:
        raw_value: The raw comma-separated string from the charm config.

    Returns:
        A list of stripped, non-empty network/host strings.
    """
    if not raw_value or not raw_value.strip():
        return []
    return [entry.strip() for entry in raw_value.split(",") if entry.strip()]


def get_invalid_config_fields(exc: ValidationError) -> list[str]:
    """Return a list on invalid config from pydantic validation error.

    Args:
        exc: The validation error exception.

    Returns:
        str: list of fields that failed validation.
    """
    logger.info(exc.errors())
    error_fields = ["-".join([str(i) for i in error["loc"]]) for error in exc.errors()]
    return error_fields
