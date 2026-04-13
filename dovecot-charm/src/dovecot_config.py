# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Dovecot charm configuration."""

import logging
from typing import TYPE_CHECKING

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


class DovecotConfig(BaseModel):
    """Pydantic model for validating charm configuration."""

    model_config = ConfigDict(str_strip_whitespace=True)

    mailname: str = Field(..., min_length=1, description="Mailname for the server")
    postmaster_address: EmailStr = Field(..., description="Postmaster email address")
    primary_unit: str = Field(..., min_length=1, description="Name of the primary unit")
    manage_luks: bool = Field(
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
        description="LUKS passphrase from the luks-key secret. Required when manage_luks is true.",
    )

    @field_validator("luks_key", mode="after")
    @classmethod
    def _validate_luks_key(cls, value: str, info: ValidationInfo) -> str:
        """Require luks_key when manage_luks is enabled."""
        manage_luks = info.data.get("manage_luks", False)
        if manage_luks and not value:
            raise ValueError("luks-key secret must be set when manage-luks is enabled")
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
        manage_luks = config.get("manage-luks", False)
        luks_key = ""
        if manage_luks:
            secret_id = config.get("luks-key", "")
            if secret_id:
                try:
                    luks_key = charm.model.get_secret(id=secret_id).get_content()["key"]
                except Exception as e:
                    logger.exception(f"Failed to retrieve luks-key secret: {e}")
        try:
            return cls.model_validate(
                {
                    "mailname": config.get("mailname"),
                    "postmaster_address": config.get("postmaster-address"),
                    "primary_unit": config.get("primary-unit"),
                    "manage_luks": manage_luks,
                    "luks_key": luks_key,
                },
                context={"charm": charm},
            )
        except ValidationError as e:
            logger.exception(f"Configuration validation error: {e}")
            raise DovecotConfigInvalidError(e) from e
