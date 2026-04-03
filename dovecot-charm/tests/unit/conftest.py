# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
import ops.testing

from charm import DovecotCharm


@pytest.fixture
def ctx():
    return ops.testing.Context(DovecotCharm, app_name="dovecot-charm")


@pytest.fixture
def base_state():
    return ops.testing.State(
        config={
            "mailname": "example.com",
            "postmaster-address": "admin@example.com",
            "cron-mailto": "admin@example.com",
            "primary-unit": "dovecot-charm/0",
        }
    )
