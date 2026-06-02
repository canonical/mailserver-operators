# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from pathlib import Path

import ops.testing
import pytest
import yaml
from testing import (
    DovecotTestCharm,
    NoOpDovecotSetup,
    NoOpHAManager,
    NoOpStorageManager,
    StorageTestDovecotCharm,
    TLSTestDovecotCharm,
)

__all__ = [
    "DovecotTestCharm",
    "NoOpDovecotSetup",
    "NoOpHAManager",
    "NoOpStorageManager",
    "StorageTestDovecotCharm",
    "TLSTestDovecotCharm",
]

# Load charm metadata once so Context fixtures don't rely on Scenario's
# __module__-based autoload (which would resolve the wrong charm root when
# the charm class is defined outside src/).
_CHARM_ROOT = Path(__file__).parents[2]
_META = yaml.safe_load((_CHARM_ROOT / "charmcraft.yaml").read_text())
MAILNAME = "example.com"


@pytest.fixture
def ctx():
    return ops.testing.Context(DovecotTestCharm, meta=_META, app_name="dovecot")


@pytest.fixture
def storage_ctx():
    """Context using StorageTestDovecotCharm: real StorageManager, no-op dovecot/HA."""
    return ops.testing.Context(StorageTestDovecotCharm, meta=_META, app_name="dovecot")


@pytest.fixture
def base_state():
    luks_secret = ops.testing.Secret({"key": "deadbeef"})
    storage = ops.testing.Storage("mail-data")
    return ops.testing.State(
        config={
            "mailname": MAILNAME,
            "postmaster-address": f"postmaster@{MAILNAME}",
            "primary-unit": "dovecot/0",
            "luks-auto-provisioning": True,
            "luks-key": luks_secret.id,
        },
        secrets={luks_secret},
        storages={storage},
    )
