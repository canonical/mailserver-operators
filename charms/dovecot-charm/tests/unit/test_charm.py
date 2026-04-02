# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import subprocess
import unittest
from unittest.mock import MagicMock, patch

from ops.model import ActiveStatus, BlockedStatus
from ops.testing import Harness

from charm import DovecotCharm


class TestConfigValidation(unittest.TestCase):
    """Tests for charm configuration validation."""

    def setUp(self):
        self.harness = Harness(DovecotCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    def test_config_missing_mailname_blocks(self):
        with patch("charm.DovecotCharm._install"):
            self.harness.update_config(
                {
                    "primary-unit": "dovecot-charm/0",
                    "mailname": "",
                    "postmaster-address": "admin@example.com",
                    "cron-mailto": "admin@example.com",
                }
            )
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)

    def test_config_missing_postmaster_blocks(self):
        with patch("charm.DovecotCharm._install"):
            self.harness.update_config(
                {
                    "primary-unit": "dovecot-charm/0",
                    "mailname": "example.com",
                    "postmaster-address": "",
                    "cron-mailto": "admin@example.com",
                }
            )
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)

    def test_config_missing_cron_mailto_blocks(self):
        with patch("charm.DovecotCharm._install"):
            self.harness.update_config(
                {
                    "primary-unit": "dovecot-charm/0",
                    "mailname": "example.com",
                    "postmaster-address": "admin@example.com",
                    "cron-mailto": "",
                }
            )
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)

    def test_config_missing_primary_unit_blocks(self):
        with patch("charm.DovecotCharm._install"):
            self.harness.update_config(
                {
                    "primary-unit": "",
                    "mailname": "example.com",
                    "postmaster-address": "admin@example.com",
                    "cron-mailto": "admin@example.com",
                }
            )
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)

    def test_config_valid_calls_install(self):
        with patch("charm.DovecotCharm._install") as mock_install:
            self.harness.update_config(
                {
                    "primary-unit": "dovecot-charm/0",
                    "mailname": "example.com",
                    "postmaster-address": "admin@example.com",
                    "cron-mailto": "admin@example.com",
                }
            )
        mock_install.assert_called()
        self.assertIsInstance(self.harness.model.unit.status, ActiveStatus)

    def test_config_is_valid_returns_false_when_missing(self):
        self.assertFalse(self.harness.charm._config_is_valid())

    def test_config_is_valid_returns_true_when_complete(self):
        with patch("charm.DovecotCharm._install"):
            self.harness.update_config(
                {
                    "primary-unit": "dovecot-charm/0",
                    "mailname": "example.com",
                    "postmaster-address": "admin@example.com",
                    "cron-mailto": "admin@example.com",
                }
            )
        self.assertTrue(self.harness.charm._config_is_valid())


class TestInstallFlow(unittest.TestCase):
    """Tests for the install and config-changed handlers."""

    def setUp(self):
        self.harness = Harness(DovecotCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()
        with patch("charm.DovecotCharm._install"):
            self.harness.update_config(
                {
                    "primary-unit": "dovecot-charm/0",
                    "mailname": "example.com",
                    "postmaster-address": "admin@example.com",
                    "cron-mailto": "admin@example.com",
                }
            )

    @patch("charm.DovecotCharm._install")
    def test_on_install_valid_config(self, mock_install):
        self.harness.charm.on.install.emit()
        mock_install.assert_called_once()
        self.assertIsInstance(self.harness.model.unit.status, ActiveStatus)

    @patch("charm.DovecotCharm._install")
    def test_on_install_invalid_config_does_not_install(self, mock_install):
        with patch("charm.DovecotCharm._install"):
            self.harness.update_config({"mailname": ""})
        mock_install.reset_mock()
        self.harness.charm.on.install.emit()
        mock_install.assert_not_called()

    @patch("charm.DovecotCharm._install")
    def test_on_config_changed_calls_install(self, mock_install):
        self.harness.charm.on.config_changed.emit()
        mock_install.assert_called()
        self.assertIsInstance(self.harness.model.unit.status, ActiveStatus)

    def test_open_ports(self):
        self.harness.charm._open_ports()
        expected_ports = [(143, "tcp"), (993, "tcp"), (110, "tcp"), (995, "tcp"), (4190, "tcp")]
        opened = self.harness.model.unit.opened_ports()
        opened_set = {(p.port, p.protocol) for p in opened}
        for port, proto in expected_ports:
            self.assertIn((port, proto), opened_set, f"Port {port}/{proto} not opened")

    @patch("charm.DovecotCharm._setup_procmail")
    @patch("charm.DovecotCharm._setup_dovecot")
    @patch("charm.DovecotCharm._open_ports")
    @patch("charm.shutil.copy")
    @patch("charm.apt")
    def test_install_calls_all_setup_steps(
        self,
        mock_apt,
        mock_copy,
        mock_open_ports,
        mock_dovecot,
        mock_procmail,
    ):
        self.harness.charm._install()
        mock_apt.update.assert_called_once()
        mock_apt.add_package.assert_called_once_with(self.harness.charm.required_packages)
        mock_open_ports.assert_called_once()
        mock_dovecot.assert_called_once()
        mock_procmail.assert_called_once()
        mock_copy.assert_called_once_with("/etc/hostname", "/etc/mailname")

    def test_is_primary_true(self):
        self.assertTrue(self.harness.charm._is_primary)

    def test_is_primary_false(self):
        with patch("charm.DovecotCharm._install"):
            self.harness.update_config({"primary-unit": "dovecot-charm/999"})
        self.assertFalse(self.harness.charm._is_primary)


class TestClearQueue(unittest.TestCase):
    """Tests for the clear-queue action."""

    def setUp(self):
        self.harness = Harness(DovecotCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()
        with patch("charm.DovecotCharm._install"):
            self.harness.update_config(
                {
                    "primary-unit": "dovecot-charm/0",
                    "mailname": "example.com",
                    "postmaster-address": "admin@example.com",
                    "cron-mailto": "admin@example.com",
                }
            )

    @patch("charm.subprocess.run")
    def test_clear_queue_deferred(self, mock_run):
        mock_run.return_value = MagicMock(stdout="cleared")
        event = MagicMock()
        event.params = {"queue": "deferred"}
        self.harness.charm._on_clear_queue_action(event)
        mock_run.assert_called_once_with(
            ["postsuper", "-d", "ALL", "deferred"],
            check=True,
            capture_output=True,
            text=True,
        )
        event.set_results.assert_called_once()

    @patch("charm.subprocess.run")
    def test_clear_queue_all(self, mock_run):
        mock_run.return_value = MagicMock(stdout="cleared")
        event = MagicMock()
        event.params = {"queue": "all"}
        self.harness.charm._on_clear_queue_action(event)
        mock_run.assert_called_once_with(
            ["postsuper", "-d", "ALL"],
            check=True,
            capture_output=True,
            text=True,
        )
        event.set_results.assert_called_once()

    @patch("charm.subprocess.run")
    def test_clear_queue_failure(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, "postsuper", stderr="error")
        event = MagicMock()
        event.params = {"queue": "deferred"}
        self.harness.charm._on_clear_queue_action(event)
        event.fail.assert_called_once()
        self.assertIn("postsuper", event.fail.call_args[0][0])
