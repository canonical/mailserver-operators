# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from constants import DOVECOT_USERS_FILE, PROCMAILRC_TARGET
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


def test_setup_procmail_applies_postfix_settings_and_reloads():
    charm = MagicMock()
    charm.jinja.get_template.return_value.render.return_value = "procmail config"
    setup = DovecotSetup(charm)

    with (
        patch("dovecot_setup.host.write_file") as write_file,
        patch("dovecot_setup.subprocess.run") as run,
        patch("dovecot_setup.systemd.service_reload") as reload_service,
    ):
        setup.setup_procmail("example.com")

    write_file.assert_called_once_with(PROCMAILRC_TARGET, "procmail config", perms=0o644)
    assert [call.args[0] for call in run.call_args_list] == [
        ["/usr/sbin/postconf", "-e", 'mailbox_command=/usr/bin/procmail -a "$EXTENSION"'],
        ["/usr/sbin/postconf", "-e", "virtual_mailbox_domains = example.com"],
        ["/usr/sbin/postconf", "-e", "virtual_transport = lmtp:unix:private/dovecot-lmtp"],
        ["/usr/sbin/postconf", "-e", "smtpd_reject_unlisted_recipient = no"],
        ["/usr/sbin/postconf", "-e", "inet_interfaces = all"],
    ]
    reload_service.assert_called_once_with("postfix", restart_on_failure=True)
