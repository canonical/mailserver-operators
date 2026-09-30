# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for Dovecot workload setup."""

import subprocess  # nosec
from unittest.mock import MagicMock, call, patch

import pytest

from dovecot_setup import DovecotSetup
from exceptions import ConfigurationError

POSTCONF_SETTINGS = {
    "mailbox_command": '/usr/bin/procmail -a "$EXTENSION"',
    "virtual_mailbox_domains": "example.com",
    "virtual_transport": "lmtp:unix:private/dovecot-lmtp",
    "smtpd_reject_unlisted_recipient": "no",
    "inet_interfaces": "all",
}


def _setup(contents: str = "procmail config") -> DovecotSetup:
    charm = MagicMock()
    charm.jinja.get_template.return_value.render.return_value = contents
    return DovecotSetup(charm)


def _postconf_result(command: list[str], **_: object) -> MagicMock:
    if command[1] == "-h":
        return MagicMock(stdout=f"{POSTCONF_SETTINGS[command[2]]}\n")
    return MagicMock(stdout="")


def test_setup_procmail_does_not_reload_unchanged_configuration(tmp_path):
    """Postfix is not reloaded when procmail and Postfix already match."""
    procmail_path = tmp_path / "procmailrc"
    procmail_path.write_text("procmail config")
    setup = _setup()

    with (
        patch("dovecot_setup.PROCMAILRC_TARGET", str(procmail_path)),
        patch("dovecot_setup.host.write_file") as write_file,
        patch("dovecot_setup.subprocess.run", side_effect=_postconf_result) as run,
        patch("dovecot_setup.systemd.service_reload") as service_reload,
    ):
        setup.setup_procmail("example.com")

    write_file.assert_not_called()
    assert run.call_args_list == [
        call(
            ["/usr/sbin/postconf", "-h", key],
            check=True,
            capture_output=True,
            text=True,
        )
        for key in POSTCONF_SETTINGS
    ]
    service_reload.assert_not_called()


def test_setup_procmail_repairs_drift_and_reloads_once(tmp_path):
    """Changed procmail and Postfix settings are applied with one reload."""
    procmail_path = tmp_path / "procmailrc"
    procmail_path.write_text("old config")
    setup = _setup()

    def postconf_result(command: list[str], **_: object) -> MagicMock:
        if command[1] == "-h":
            value = POSTCONF_SETTINGS[command[2]]
            if command[2] == "virtual_mailbox_domains":
                value = "old.example.com"
            return MagicMock(stdout=f"{value}\n")
        return MagicMock(stdout="")

    with (
        patch("dovecot_setup.PROCMAILRC_TARGET", str(procmail_path)),
        patch("dovecot_setup.host.write_file") as write_file,
        patch("dovecot_setup.subprocess.run", side_effect=postconf_result) as run,
        patch("dovecot_setup.systemd.service_reload") as service_reload,
    ):
        setup.setup_procmail("example.com")

    write_file.assert_called_once_with(str(procmail_path), "procmail config", perms=0o644)
    run.assert_any_call(
        ["/usr/sbin/postconf", "-e", "virtual_mailbox_domains = example.com"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert sum(call_.args[0][1] == "-e" for call_ in run.call_args_list) == 1
    service_reload.assert_called_once_with("postfix", restart_on_failure=True)


def test_setup_procmail_raises_when_postconf_fails(tmp_path):
    """Postconf failures remain explicit configuration errors."""
    procmail_path = tmp_path / "procmailrc"
    setup = _setup()

    with (
        patch("dovecot_setup.PROCMAILRC_TARGET", str(procmail_path)),
        patch("dovecot_setup.host.write_file"),
        patch(
            "dovecot_setup.subprocess.run",
            side_effect=subprocess.CalledProcessError(
                1,
                ["/usr/sbin/postconf", "-h", "mailbox_command"],
                stderr="postconf failed",
            ),
        ),
        patch("dovecot_setup.systemd.service_reload") as service_reload,
        pytest.raises(ConfigurationError, match="postconf failed"),
    ):
        setup.setup_procmail("example.com")

    service_reload.assert_not_called()
