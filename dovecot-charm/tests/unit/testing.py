# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Test doubles for unit testing the Dovecot charm.

Defines no-op manager stubs and specialised DovecotCharm subclasses that
inject them.  Context fixtures must pass `meta` explicitly (loaded from
charmcraft.yaml in conftest.py) because Scenario's autoload resolves the charm
root from the class's __module__ file path, which would be wrong here.
"""

from charm import DovecotCharm
from dovecot_setup import DovecotSetup
from ha import HAManager
from storage import StorageManager


class NoOpStorageManager(StorageManager):
    def __init__(self, charm=None):
        pass

    def ensure_storage_ready(self, dovecot_config):
        pass

    def teardown_detaching_storage(self):
        pass


class FakeStorageManager(StorageManager):
    """StorageManager with injectable I/O primitives for unit tests.

    Construct with the desired fake state; the public methods run the real
    StorageManager logic but delegate all I/O to the overridden helpers below.

    Attributes:
        mounted:        Return value for _mail_storage_mounted().
        saved_path:     Return value for _load_storage_dev_path().
        is_luks:        Return value for _is_luks_device().
        luks_setup_calls: List of (key, dev_path) tuples recorded by setup_luks_storage().
        saved_paths:    List of dev_path values recorded by _save_storage_dev_path().
    """

    def __init__(
        self, charm=None, *, mounted=True, saved_path=None, is_luks=True, mapper_exists=False
    ):
        self._charm = charm
        self.mounted = mounted
        self.saved_path = saved_path
        self.is_luks = is_luks
        self.mapper_exists = mapper_exists
        self.luks_setup_calls: list[tuple[str, str]] = []
        self.saved_paths: list[str] = []

    def _mail_storage_mounted(self) -> bool:
        return self.mounted

    def _mapper_exists(self) -> bool:
        return self.mapper_exists

    def _load_storage_dev_path(self) -> str | None:
        return self.saved_path

    def _is_luks_device(self, dev_path: str) -> bool:
        return self.is_luks

    def _save_storage_dev_path(self, dev_path) -> None:
        self.saved_paths.append(str(dev_path))

    def setup_luks_storage(self, key: str, dev_path) -> None:
        self.luks_setup_calls.append((key, str(dev_path)))


class NoOpDovecotSetup(DovecotSetup):
    def __init__(self, charm=None):
        pass

    def is_installed(self) -> bool:
        return True

    def setup_tls(self, dovecot_config):
        pass

    def setup_dovecot(self, dovecot_config):
        pass

    def setup_procmail(self, mailname: str):
        pass


class NoOpHAManager(HAManager):
    def __init__(self, charm=None):
        pass

    def setup_ssh_keys(self):
        pass

    def sync_authorized_keys(self):
        pass

    def sync_known_hosts(self):
        pass

    def install_mail_sync_script(self):
        pass

    def setup_mail_sync_timer(self, dovecot_config):
        pass


class DovecotTestCharm(DovecotCharm):
    """DovecotCharm with all I/O managers replaced by no-op stubs.

    Class-level stubs act as defaults.  __init__ copies them onto the instance
    so that patch.object(DovecotTestCharm, "_dovecot_setup", ...) set before
    ctx.run() is picked up by the freshly constructed charm instance.
    """

    _storage: StorageManager = NoOpStorageManager()
    _dovecot_setup: DovecotSetup = NoOpDovecotSetup()
    _ha: HAManager = NoOpHAManager()

    def __init__(self, *args):
        super().__init__(*args)
        # Re-read from the class so patch.object overrides take effect.
        self._storage = type(self)._storage
        self._dovecot_setup = type(self)._dovecot_setup
        self._ha = type(self)._ha


class StorageTestDovecotCharm(DovecotCharm):
    """DovecotCharm that uses the real StorageManager but no-ops dovecot setup and HA.

    Used by storage-focused tests so that ensure_storage_ready and
    teardown_detaching_storage execute their real logic while downstream
    Dovecot config file and HA side-effects are suppressed.

    Set StorageTestDovecotCharm._storage = FakeStorageManager(...) before
    ctx.run() to inject the desired fake I/O behaviour.
    """

    _storage: StorageManager = FakeStorageManager()
    _dovecot_setup: DovecotSetup = NoOpDovecotSetup()
    _ha: HAManager = NoOpHAManager()

    def __init__(self, *args):
        super().__init__(*args)
        self._storage = type(self)._storage
        self._storage._charm = self
        self._dovecot_setup = type(self)._dovecot_setup
        self._ha = type(self)._ha


class TLSDovecotSetup(DovecotSetup):
    """DovecotSetup that runs the real setup_tls but no-ops setup_dovecot/procmail."""

    def __init__(self, charm=None):
        self._charm = charm

    def is_installed(self) -> bool:
        return True

    def setup_dovecot(self, dovecot_config):
        pass

    def setup_procmail(self, mailname: str):
        pass


class TLSTestDovecotCharm(DovecotCharm):
    """DovecotCharm that uses TLSDovecotSetup (real TLS logic) but no-ops storage and HA.

    Used by TLS-focused tests so that setup_tls executes its real logic
    (certificate validation, file writing) while storage, HA, and Dovecot
    config file side-effects are suppressed.
    """

    _storage: StorageManager = NoOpStorageManager()
    _dovecot_setup: DovecotSetup = TLSDovecotSetup()
    _ha: HAManager = NoOpHAManager()

    def __init__(self, *args):
        super().__init__(*args)
        self._storage = type(self)._storage
        self._dovecot_setup = type(self)._dovecot_setup
        self._dovecot_setup._charm = self
        self._ha = type(self)._ha
