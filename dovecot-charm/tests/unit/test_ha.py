# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock, patch

from ha import HAManager


def test_disable_mail_sync_timer_pauses_existing_timer():
    """Demoting a primary stops and disables its existing sync timer."""
    manager = HAManager(MagicMock())

    with (
        patch("ha.Path.exists", return_value=True),
        patch("ha.systemd.service_pause") as pause,
    ):
        manager.disable_mail_sync_timer()

    pause.assert_called_once_with("sync-to-secondary.timer")


def test_disable_mail_sync_timer_skips_missing_timer():
    """A unit that has never been primary has no timer to disable."""
    manager = HAManager(MagicMock())

    with (
        patch("ha.Path.exists", return_value=False),
        patch("ha.systemd.service_pause") as pause,
    ):
        manager.disable_mail_sync_timer()

    pause.assert_not_called()
