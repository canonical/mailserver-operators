# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Custom exceptions for the Dovecot charm."""


class CharmBlockedError(Exception):
    """Raised when charm should enter Blocked status.

    Carry the human-readable message for BlockedStatus.
    """

    pass


class StorageError(CharmBlockedError):
    """Raised by storage operations when setup or teardown fails."""

    pass


class StorageSetupError(Exception):
    """Raised for expected failures during LUKS/device/filesystem setup."""

    pass


class ConfigurationError(CharmBlockedError):
    """Raised when charm or service configuration is invalid or fails."""

    pass
