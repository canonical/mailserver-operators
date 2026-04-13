# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import ops.testing
import pytest

from charm import DovecotCharm


@pytest.fixture
def ctx():
    return ops.testing.Context(DovecotCharm, app_name="dovecot-charm")


@pytest.fixture
def base_state():
    luks_secret = ops.testing.Secret({"key": "deadbeef"})
    return ops.testing.State(
        config={
            "mailname": "example.com",
            "postmaster-address": "admin@example.com",
            "primary-unit": "dovecot-charm/0",
            "manage-luks": True,
            "luks-key": luks_secret.id,
        },
        secrets={luks_secret},
    )
