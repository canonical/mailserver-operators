#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Dovecot IMAP/POP3 mail server charm."""

import logging
from typing import Any, Mapping

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    ValidationError,
    field_validator,
)

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

    cron_mailto: EmailStr = Field(..., description="Email address for cron output")
    mailname: str = Field(..., description="Mailname for the server")
    postmaster_address: EmailStr = Field(..., description="Postmaster email address")
    primary_unit: str = Field(..., description="Name of the primary unit")

    @field_validator("mailname", "postmaster_address", "primary_unit", mode="before")
    @classmethod
    def _reject_empty_values(cls, value: Any) -> Any:
        """Ensure string config values are not empty or whitespace-only."""
        if isinstance(value, str) and not value.strip():
            raise ValueError("must not be empty")
        return value

    @classmethod
    def from_charm(cls, config: Mapping[str, Any]) -> "DovecotConfig":
        """Create a DovecotConfig instance from charm configuration."""
        try:
            return cls(
                cron_mailto=config.get("cron-mailto"),
                mailname=config.get("mailname"),
                postmaster_address=config.get("postmaster-address"),
                primary_unit=config.get("primary-unit"),
            )
        except ValidationError as e:
            logger.exception(f"Configuration validation error: {e}")
            raise DovecotConfigInvalidError(e) from e
