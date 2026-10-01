# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Dovecot charm configuration."""

import logging
import subprocess  # nosec
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from ops import ModelError, SecretNotFoundError
from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
)

from credentials import CredentialError, parse_credential_entries

if TYPE_CHECKING:
    from charm import DovecotCharm

logger = logging.getLogger(__name__)


class DovecotConfigInvalidError(Exception):
    """Represents an error with the dovecot configuration."""

    def __init__(self, validation_error: ValidationError) -> None:
        super().__init__(str(validation_error))
        self._validation_error = validation_error

    def errors(self) -> list:
        """Return the list of validation errors from the wrapped Pydantic error."""
        return self._validation_error.errors()


class DovecotConfigSecretError(Exception):
    """Represents an error retrieving a secret for dovecot configuration."""

    pass


class DovecotConfig(BaseModel):
    """Pydantic model for validating charm configuration."""

    model_config = ConfigDict(str_strip_whitespace=True)

    mailname: str = Field(..., min_length=1, description="Mailname for the server")
    postmaster_address: EmailStr = Field(..., description="Postmaster email address")
    primary_unit: str = Field(..., min_length=1, description="Name of the primary unit")
    luks_auto_provisioning: bool = Field(
        False,
        description=(
            "Enable automatic LUKS encryption management for attached block storage. "
            "When enabled, the charm will format the storage with LUKS using the key "
            "supplied via luks-key, create an ext4 filesystem, and manage mounting "
            "and fstab entries."
        ),
    )
    luks_key: str = Field(
        "",
        description="LUKS passphrase from the luks-key secret. Required when luks_auto_provisioning is true.",
    )
    backup_encryption_key: str = Field(
        "",
        description=(
            "Backup passphrase from the backup-encryption-key secret. "
            "Used to encrypt Bacula backup artifacts when the backup relation is integrated."
        ),
    )
    sync_schedule: str = Field(
        "daily",
        description="Systemd OnCalendar expression for syncing mail from primary to secondary units.",
    )
    mail_users: list[str] = Field(
        default_factory=list,
        description="Static mailbox credentials used for Dovecot authentication",
    )
    credential_sync_interval: int = Field(
        5,
        ge=1,
        description="External credential source synchronization interval in minutes",
    )
    mail_credentials_path: str = Field(
        "", description="Path to the external credentials file merged with static users"
    )

    @field_validator("mail_users", mode="before")
    @classmethod
    def _validate_mail_users(cls, value: object) -> list[str]:
        """Parse and validate static credentials from the mail-users secret."""
        if value == "":
            return []

        if isinstance(value, str):
            try:
                value = yaml.safe_load(value)
            except yaml.YAMLError as exc:
                raise ValueError("mail-users must contain valid YAML") from exc

        if not isinstance(value, list):
            raise ValueError("mail-users must be a YAML list")

        try:
            return list(parse_credential_entries(value).values())
        except CredentialError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("mail_credentials_path", mode="after")
    @classmethod
    def _validate_mail_credentials_path(cls, value: str) -> str:
        """Require an absolute path when the external source is enabled."""
        if not value:
            return value
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("mail-credentials-path must not contain control characters")
        if not Path(value).is_absolute():
            raise ValueError("mail-credentials-path must be an absolute path")
        return value

    @field_validator("luks_key", mode="after")
    @classmethod
    def _validate_luks_key(cls, value: str, info: ValidationInfo) -> str:
        """Require luks_key when luks_auto_provisioning is enabled."""
        luks_auto_provisioning = info.data.get("luks_auto_provisioning", False)
        if luks_auto_provisioning and not value:
            raise ValueError("luks-key secret must be set when luks-auto-provisioning is enabled")
        return value

    @field_validator("sync_schedule", mode="after")
    @classmethod
    def _validate_sync_schedule(cls, value: str) -> str:
        """Validate the OnCalendar expression using systemd-analyze."""
        if "\n" in value or "\r" in value:
            raise ValueError("sync-schedule must not contain newlines")
        try:
            subprocess.run(
                ["/usr/bin/systemd-analyze", "calendar", value],
                check=True,
                capture_output=True,
                text=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            raise ValueError(
                f"sync-schedule {value!r} is not a valid OnCalendar expression: {e}"
            ) from e
        return value

    @field_validator("primary_unit", mode="after")
    @classmethod
    def _validate_primary_unit_exists(cls, value: str, info: ValidationInfo) -> str:
        """Ensure the primary unit exists in the model."""
        charm = info.context and info.context.get("charm")
        if charm and value not in charm.get_units():
            raise ValueError("Primary unit does not exist")
        return value

    @classmethod
    def from_charm(cls, charm: "DovecotCharm") -> "DovecotConfig":
        """Create a DovecotConfig instance from charm configuration."""
        config = charm.model.config
        luks_auto_provisioning = config.get("luks-auto-provisioning", False)
        luks_key = ""
        if luks_auto_provisioning:
            secret_id = config.get("luks-key", "")
            if secret_id:
                luks_key = cls._read_secret_field(charm, secret_id, "luks-key", "key")

        backup_encryption_key = ""
        backup_secret_id = config.get("backup-encryption-key", "")
        if backup_secret_id:
            backup_encryption_key = cls._read_secret_field(
                charm,
                backup_secret_id,
                "backup-encryption-key",
                "backup-key",
            )

        mail_users = ""
        mail_users_secret_id = config.get("mail-users", "")
        if mail_users_secret_id:
            mail_users = cls._read_secret_field(
                charm,
                mail_users_secret_id,
                "mail-users",
                "users",
            )
        try:
            return cls.model_validate(
                {
                    "mailname": config.get("mailname"),
                    "postmaster_address": config.get("postmaster-address"),
                    "primary_unit": config.get("primary-unit"),
                    "luks_auto_provisioning": luks_auto_provisioning,
                    "luks_key": luks_key,
                    "backup_encryption_key": backup_encryption_key,
                    "sync_schedule": config.get("sync-schedule", "daily"),
                    "mail_users": mail_users,
                    "credential_sync_interval": config.get("credential-sync-interval", 5),
                    "mail_credentials_path": config.get("mail-credentials-path", ""),
                },
                context={"charm": charm},
            )
        except ValidationError as e:
            raise DovecotConfigInvalidError(e) from e

    @staticmethod
    def _read_secret_field(
        charm: "DovecotCharm", secret_id: str, config_name: str, field_name: str
    ) -> str:
        """Fetch a Juju secret and return the requested field.

        Args:
            charm: The charm instance used to fetch the Juju secret.
            secret_id: Juju secret identifier stored in charm config.
            config_name: Config option name for error messages.
            field_name: Secret content field that contains the desired value.

        Raises:
            DovecotConfigSecretError: If the secret is missing, inaccessible, or malformed.
        """
        try:
            content = charm.model.get_secret(id=secret_id).get_content(refresh=True)
        except (SecretNotFoundError, ModelError) as e:
            msg = (
                f"Failed to retrieve {config_name} secret (id={secret_id}): {e}. "
                "Ensure the secret exists and the charm has grant-secret permission."
            )
            logger.error(msg)
            raise DovecotConfigSecretError(msg) from e

        value = content.get(field_name, "")
        if value:
            return value

        msg = (
            f"Secret (id={secret_id}) exists but does not contain a '{field_name}' field. "
            f"Ensure the secret was created with: juju add-secret ... {field_name}=<value>"
        )
        logger.error(msg)
        raise DovecotConfigSecretError(msg)
