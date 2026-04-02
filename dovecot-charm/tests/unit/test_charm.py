# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import subprocess
import unittest
from unittest.mock import MagicMock, mock_open, patch

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


class TestGDPRArchive(unittest.TestCase):
    """Tests for GDPR archive action."""

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

    @patch("charm.shutil.rmtree")
    @patch("charm.os.makedirs")
    @patch("charm.subprocess.run")
    def test_gdpr_archive_compressed(self, mock_run, mock_makedirs, mock_rmtree):
        mock_run.return_value = MagicMock()
        event = MagicMock()
        event.params = {"username": "alice", "compress": True}

        self.harness.charm._on_gdpr_archive(event)

        mock_run.assert_any_call(
            ["doveadm", "backup", "-u", "alice", "mdbox:/srv/mail/archives/alice/"],
            check=True,
            capture_output=True,
            text=True,
        )
        mock_run.assert_any_call(
            [
                "tar",
                "-czf",
                "/srv/mail/archives/alice.tar.gz",
                "-C",
                "/srv/mail/archives",
                "alice",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        mock_rmtree.assert_called_once_with("/srv/mail/archives/alice")
        event.set_results.assert_called_once()
        self.assertEqual(
            event.set_results.call_args[0][0]["path"],
            "/srv/mail/archives/alice.tar.gz",
        )

    @patch("charm.os.makedirs")
    @patch("charm.subprocess.run")
    def test_gdpr_archive_uncompressed(self, mock_run, mock_makedirs):
        mock_run.return_value = MagicMock()
        event = MagicMock()
        event.params = {"username": "bob", "compress": False}

        self.harness.charm._on_gdpr_archive(event)

        event.set_results.assert_called_once()
        self.assertEqual(
            event.set_results.call_args[0][0]["path"],
            "/srv/mail/archives/bob",
        )

    @patch("charm.os.makedirs")
    @patch("charm.subprocess.run")
    def test_gdpr_archive_failure(self, mock_run, mock_makedirs):
        mock_run.side_effect = subprocess.CalledProcessError(1, "doveadm", stderr="no such user")
        event = MagicMock()
        event.params = {"username": "ghost", "compress": True}

        self.harness.charm._on_gdpr_archive(event)

        event.fail.assert_called_once()
        self.assertIn("ghost", event.fail.call_args[0][0])


class TestGDPRDelete(unittest.TestCase):
    """Tests for GDPR delete action."""

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

    def test_gdpr_delete_no_confirm(self):
        event = MagicMock()
        event.params = {"username": "alice", "confirm": False}
        self.harness.charm._on_gdpr_delete(event)
        event.fail.assert_called_once_with("Deletion not confirmed. Set confirm=true to proceed.")

    @patch("charm.shutil.rmtree")
    @patch("charm.os.path.exists")
    @patch("charm.subprocess.run")
    def test_gdpr_delete_confirmed(self, mock_run, mock_exists, mock_rmtree):
        mock_run.return_value = MagicMock()
        mock_exists.return_value = True

        event = MagicMock()
        event.params = {"username": "alice", "confirm": True}
        self.harness.charm._on_gdpr_delete(event)

        mock_run.assert_called_once_with(
            ["doveadm", "expunge", "-u", "alice", "mailbox", "*", "all"],
            check=True,
            capture_output=True,
            text=True,
        )
        mock_rmtree.assert_called_once_with("/srv/mail/alice")
        event.set_results.assert_called_once()

    @patch("charm.os.path.exists")
    @patch("charm.subprocess.run")
    def test_gdpr_delete_no_mail_dir(self, mock_run, mock_exists):
        mock_run.return_value = MagicMock()
        mock_exists.return_value = False

        event = MagicMock()
        event.params = {"username": "nodir", "confirm": True}
        self.harness.charm._on_gdpr_delete(event)

        event.set_results.assert_called_once()

    @patch("charm.subprocess.run")
    def test_gdpr_delete_expunge_fails(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, "doveadm", stderr="error")
        event = MagicMock()
        event.params = {"username": "alice", "confirm": True}
        self.harness.charm._on_gdpr_delete(event)
        event.fail.assert_called_once()


class TestGDPRTakeout(unittest.TestCase):
    """Tests for GDPR takeout action."""

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

    @patch("charm.shutil.rmtree")
    @patch("charm.os.makedirs")
    @patch("charm.subprocess.run")
    def test_gdpr_takeout_maildir(self, mock_run, mock_makedirs, mock_rmtree):
        mock_run.return_value = MagicMock()
        event = MagicMock()
        event.params = {"username": "alice", "format": "maildir"}

        self.harness.charm._on_gdpr_takeout(event)

        mock_run.assert_any_call(
            [
                "doveadm",
                "sync",
                "-u",
                "alice",
                "maildir:/tmp/gdpr-takeout/alice/:LAYOUT=fs",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        mock_run.assert_any_call(
            [
                "tar",
                "-czf",
                "/tmp/gdpr-takeout/alice-takeout.tar.gz",
                "-C",
                "/tmp/gdpr-takeout",
                "alice",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        mock_rmtree.assert_called_once()
        event.set_results.assert_called_once()
        self.assertEqual(
            event.set_results.call_args[0][0]["path"],
            "/tmp/gdpr-takeout/alice-takeout.tar.gz",
        )

    @patch("charm.shutil.rmtree")
    @patch("charm.os.makedirs")
    @patch("charm.subprocess.run")
    @patch("builtins.open", new_callable=mock_open)
    def test_gdpr_takeout_mbox(self, mock_file, mock_run, mock_makedirs, mock_rmtree):
        fetch_result = MagicMock()
        fetch_result.stdout = "From alice@example.com\nSubject: hi\n"
        mock_run.return_value = fetch_result

        event = MagicMock()
        event.params = {"username": "alice", "format": "mbox"}

        self.harness.charm._on_gdpr_takeout(event)

        mock_run.assert_any_call(
            ["doveadm", "fetch", "-u", "alice", "text", "mailbox", "*", "all"],
            check=True,
            capture_output=True,
            text=True,
        )
        mock_file.assert_called_with("/tmp/gdpr-takeout/alice/alice.mbox", "w")
        event.set_results.assert_called_once()

    @patch("charm.os.makedirs")
    @patch("charm.subprocess.run")
    def test_gdpr_takeout_failure(self, mock_run, mock_makedirs):
        mock_run.side_effect = subprocess.CalledProcessError(1, "doveadm", stderr="user not found")
        event = MagicMock()
        event.params = {"username": "ghost", "format": "maildir"}
        self.harness.charm._on_gdpr_takeout(event)
        event.fail.assert_called_once()
        self.assertIn("ghost", event.fail.call_args[0][0])


class TestForceSync(unittest.TestCase):
    """Tests for the force-sync action."""

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
    def test_force_sync_success(self, mock_run):
        mock_run.return_value = MagicMock(stdout="ok", stderr="")
        from unittest.mock import PropertyMock

        with patch.object(
            type(self.harness.charm),
            "_secondary_hostname",
            new_callable=PropertyMock,
            return_value="10.0.0.2",
        ):
            event = MagicMock()
            self.harness.charm._on_force_sync(event)
        event.set_results.assert_called_once_with({"result": "Sync completed successfully"})

    def test_force_sync_not_primary(self):
        with patch("charm.DovecotCharm._install"):
            self.harness.update_config({"primary-unit": "dovecot-charm/999"})
        event = MagicMock()
        self.harness.charm._on_force_sync(event)
        event.fail.assert_called_once_with("This action can only be run on the primary unit.")

    def test_force_sync_no_secondary(self):
        event = MagicMock()
        self.harness.charm._on_force_sync(event)
        event.fail.assert_called_once_with("No secondary unit found to sync to.")

    @patch("charm.subprocess.run")
    def test_force_sync_subprocess_failure(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, "sync", stderr="fail")
        from unittest.mock import PropertyMock

        with patch.object(
            type(self.harness.charm),
            "_secondary_hostname",
            new_callable=PropertyMock,
            return_value="10.0.0.2",
        ):
            event = MagicMock()
            self.harness.charm._on_force_sync(event)
        event.fail.assert_called_once()
        self.assertIn("fail", event.fail.call_args[0][0])


class TestStorageHandlers(unittest.TestCase):
    """Tests for storage event handlers."""

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

    @patch("charm.shutil.which")
    def test_storage_attached_defer_if_cryptsetup_missing(self, mock_which):
        mock_which.return_value = None

        storage_ids = self.harness.add_storage("mail-data", count=1)
        self.harness.model.unit.status = BlockedStatus("Checking storage")
        self.harness.attach_storage(storage_ids[0])

        self.assertEqual(self.harness.model.unit.status.message, "Checking storage")

    @patch("charm.DovecotCharm._setup_luks_storage")
    @patch("charm.shutil.which")
    def test_storage_attached_defer_logic(self, mock_which, mock_setup_luks):
        mock_which.return_value = None

        self.harness.add_storage("mail-data", count=1)
        self.harness.attach_storage("mail-data/0")

        mock_setup_luks.assert_not_called()

    @patch("charm.os.path.ismount")
    @patch("charm.shutil.which")
    def test_storage_attached_manage_luks_disabled_waits_for_mount(self, mock_which, mock_ismount):
        mock_ismount.return_value = False

        with patch("charm.DovecotCharm._install"):
            self.harness.update_config({"manage-luks": False})

        self.harness.add_storage("mail-data", count=1)
        self.harness.attach_storage("mail-data/0")

        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)
        self.assertEqual(
            self.harness.model.unit.status.message,
            "mail-data not mounted; manage-luks disabled",
        )
        mock_which.assert_not_called()

    @patch("charm.os.path.ismount")
    @patch("charm.shutil.which")
    def test_storage_attached_manage_luks_disabled_active(self, mock_which, mock_ismount):
        mock_ismount.return_value = True

        with patch("charm.DovecotCharm._install"):
            self.harness.update_config({"manage-luks": False})

        self.harness.add_storage("mail-data", count=1)
        self.harness.attach_storage("mail-data/0")

        self.assertIsInstance(self.harness.model.unit.status, ActiveStatus)
        mock_which.assert_not_called()


class TestStorageDetaching(unittest.TestCase):
    """Tests for storage detaching handler."""

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
    @patch("charm.os.path.exists")
    @patch("charm.os.path.ismount")
    def test_storage_detaching_unmount_and_close(self, mock_ismount, mock_exists, mock_run):
        mock_ismount.return_value = True
        mock_exists.return_value = True
        mock_run.return_value = MagicMock()

        event = MagicMock()
        self.harness.charm._on_mail_data_storage_detaching(event)

        mock_run.assert_any_call(["umount", "/srv/mail"], check=True)
        mock_run.assert_any_call(["cryptsetup", "luksClose", "mail-data"], check=True)

    @patch("charm.subprocess.run")
    @patch("charm.os.path.exists")
    @patch("charm.os.path.ismount")
    def test_storage_detaching_not_mounted(self, mock_ismount, mock_exists, mock_run):
        mock_ismount.return_value = False
        mock_exists.return_value = False

        event = MagicMock()
        self.harness.charm._on_mail_data_storage_detaching(event)

        mock_run.assert_not_called()

    @patch("charm.subprocess.run")
    @patch("charm.os.path.exists")
    @patch("charm.os.path.ismount")
    def test_storage_detaching_luks_disabled_skips_close(
        self, mock_ismount, mock_exists, mock_run
    ):
        mock_ismount.return_value = True
        mock_exists.return_value = True
        mock_run.return_value = MagicMock()

        with patch("charm.DovecotCharm._install"):
            self.harness.update_config({"manage-luks": False})

        event = MagicMock()
        self.harness.charm._on_mail_data_storage_detaching(event)

        mock_run.assert_called_once_with(["umount", "/srv/mail"], check=True)


class TestUpdateStatus(unittest.TestCase):
    """Tests for update-status handler."""

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

    @patch("charm.os.path.ismount")
    def test_update_status_luks_disabled_mounted(self, mock_ismount):
        mock_ismount.return_value = True
        with patch("charm.DovecotCharm._install"):
            self.harness.update_config({"manage-luks": False})

        self.harness.charm.on.update_status.emit()
        self.assertIsInstance(self.harness.model.unit.status, ActiveStatus)

    @patch("charm.os.path.ismount")
    def test_update_status_luks_disabled_not_mounted(self, mock_ismount):
        mock_ismount.return_value = False
        with patch("charm.DovecotCharm._install"):
            self.harness.update_config({"manage-luks": False})

        self.harness.charm.on.update_status.emit()
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)
        self.assertEqual(
            self.harness.model.unit.status.message,
            "mail-data not mounted; manage-luks disabled",
        )
