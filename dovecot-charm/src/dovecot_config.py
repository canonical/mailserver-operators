# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Dovecot charm configuration."""

import logging
from typing import TYPE_CHECKING

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

    @field_validator("luks_key", mode="after")
    @classmethod
    def _validate_luks_key(cls, value: str, info: ValidationInfo) -> str:
        """Require luks_key when luks_auto_provisioning is enabled."""
        luks_auto_provisioning = info.data.get("luks_auto_provisioning", False)
        if luks_auto_provisioning and not value:
            raise ValueError("luks-key secret must be set when luks-auto-provisioning is enabled")
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
                try:
                    content = charm.model.get_secret(id=secret_id).get_content()
                    luks_key = content.get("key", "")
                    if not luks_key:
                        msg = (
                            f"Secret (id={secret_id}) exists but does not contain a 'key' field. "
                            "Ensure the secret was created with: juju add-secret ... key=<passphrase>"
                        )
                        logger.error(msg)
                        raise DovecotConfigSecretError(msg)
                except (SecretNotFoundError, ModelError) as e:
                    msg = (
                        f"Failed to retrieve luks-key secret (id={secret_id}): {e}. "
                        "Ensure the secret exists and the charm has grant-secret permission."
                    )
                    logger.error(msg)
                    raise DovecotConfigSecretError(msg) from e
        try:
            return cls.model_validate(
                {
                    "mailname": config.get("mailname"),
                    "postmaster_address": config.get("postmaster-address"),
                    "primary_unit": config.get("primary-unit"),
                    "luks_auto_provisioning": luks_auto_provisioning,
                    "luks_key": luks_key,
                },
                context={"charm": charm},
            )
        except ValidationError as e:
            logger.exception(f"Configuration validation error: {e}")
            raise DovecotConfigInvalidError(e) from e
