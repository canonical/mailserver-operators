# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from constants import DOVECOT_USERS_FILE
from dovecot_setup import DovecotSetup


def test_setup_credentials_writes_secret_users_to_dovecot_passwd_file():
    setup = DovecotSetup(MagicMock())
    config = SimpleNamespace(
        mail_users=[
            "bob:{crypt}$6$bob-hash",
            "alice:{crypt}$6$alice-hash",
        ]
    )

    with (
        patch.object(setup, "_ensure_virtual_mail_identity"),
        patch("dovecot_setup.atomic_write") as atomic_write,
    ):
        setup.setup_credentials(config)

    atomic_write.assert_called_once_with(
        DOVECOT_USERS_FILE,
        "alice:{crypt}$6$alice-hash::::::\nbob:{crypt}$6$bob-hash::::::\n",
        user="root",
        group="dovecot",
        mode=0o640,
    )
