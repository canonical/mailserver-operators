# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.
"""Unit tests for TLS certificate integration."""

from unittest.mock import MagicMock, patch
from exceptions import ConfigurationError

import ops
import pytest


def test_no_tls_cert_yet_blocks(ctx, base_state):
    """Charm must be Blocked when the TLS relation has no certificate yet.

    _setup_tls calls get_assigned_certificate which returns (None, None) when
    no real provider has issued a cert — no external system calls are reached.
    """
    with (
        # Guard against real storage operations in the first try block
        patch("charm.ensure_storage_ready"),
        # doveconf present so _reconcile proceeds to the second try block
        patch("charm.shutil.which", return_value="/usr/bin/doveconf"),
    ):
        state_out = ctx.run(ctx.on.config_changed(), base_state)
    assert isinstance(state_out.unit_status, ops.BlockedStatus)
    assert "certificate" in state_out.unit_status.message.lower()


def test_setup_tls_writes_cert_key_and_chain(ctx, base_state, tmp_path):
    """_setup_tls writes cert (+ CA chain) and private key to tls_cert_dir.

    _setup_tls is invoked by _reconcile at event dispatch time (context manager
    __exit__).  We patch charm.TLS_CERT_DIR to tmp_path so no real filesystem
    paths are touched, and patch _setup_dovecot/_setup_procmail so the test
    stays focused on the file-writing logic.
    """
    mock_cert = MagicMock()
    mock_cert.certificate.__str__ = MagicMock(return_value="CERT_DATA")
    mock_cert.ca.__str__ = MagicMock(return_value="CA_DATA")
    mock_key = MagicMock()
    mock_key.__str__ = MagicMock(return_value="KEY_DATA")

    with (
        # Redirect TLS_CERT_DIR so _setup_tls writes into tmp_path
        patch("charm.TLS_CERT_DIR", tmp_path),
        patch("charm.ensure_storage_ready"),
        patch("charm.shutil.which", return_value="/usr/bin/doveconf"),
        # Isolate from dovecot/procmail filesystem writes
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
        ctx(ctx.on.config_changed(), base_state) as mgr,
    ):
        # Override the TLS library instance so get_assigned_certificate
        # returns our controlled (cert, key) pair when the event fires
        mgr.charm._tls = MagicMock()
        mgr.charm._tls.get_assigned_certificate.return_value = (mock_cert, mock_key)
    # Event fired at __exit__; assert on filesystem state afterwards

    cert_file = tmp_path / "example.com.pem"
    key_file = tmp_path / "example.com.key"

    assert cert_file.exists()
    assert cert_file.read_text() == "CERT_DATA\nCA_DATA"
    assert oct(cert_file.stat().st_mode)[-3:] == "644"

    assert key_file.exists()
    assert key_file.read_text() == "KEY_DATA"
    assert oct(key_file.stat().st_mode)[-3:] == "600"


def test_setup_tls_no_ca_omits_chain(ctx, base_state, tmp_path):
    """When provider_cert.ca is falsy the cert file must not have a trailing CA.

    Same structure as test_setup_tls_writes_cert_key_and_chain: event fires at
    __exit__, TLS_CERT_DIR redirected to tmp_path, downstream methods patched.
    """
    mock_cert = MagicMock()
    mock_cert.certificate.__str__ = MagicMock(return_value="CERT_DATA")
    mock_cert.ca = None  # no CA attached
    mock_key = MagicMock()
    mock_key.__str__ = MagicMock(return_value="KEY_DATA")

    with (
        patch("charm.TLS_CERT_DIR", tmp_path),
        patch("charm.ensure_storage_ready"),
        patch("charm.shutil.which", return_value="/usr/bin/doveconf"),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
        ctx(ctx.on.config_changed(), base_state) as mgr,
    ):
        mgr.charm._tls = MagicMock()
        mgr.charm._tls.get_assigned_certificate.return_value = (mock_cert, mock_key)

    cert_file = tmp_path / "example.com.pem"
    assert cert_file.read_text() == "CERT_DATA"


def test_setup_tls_no_private_key_raises(ctx, base_state):
    """_setup_tls must raise ConfigurationError when private key is unavailable.

    We call _setup_tls directly inside the context manager body (before the
    event fires).  The error is raised before any filesystem writes so no
    TLS_CERT_DIR patch is needed.  At __exit__ _reconcile also calls
    _setup_tls with the same mock, hits the same error, and sets BlockedStatus.
    """
    mock_cert = MagicMock()

    with (
        patch("charm.ensure_storage_ready"),
        patch("charm.shutil.which", return_value="/usr/bin/doveconf"),
        ctx(ctx.on.config_changed(), base_state) as mgr,
    ):
        mgr.charm._tls = MagicMock()
        # cert present but private key is None — error raised before any mkdir
        mgr.charm._tls.get_assigned_certificate.return_value = (mock_cert, None)
        mock_config = MagicMock()
        mock_config.mailname = "example.com"
        with pytest.raises(ConfigurationError):
            mgr.charm._setup_tls(mock_config)


def test_certificate_available_event_triggers_reconcile(ctx, base_state, tmp_path):
    """The certificate_available event must be wired to _reconcile.

    When the cert is now available the charm should reach ActiveStatus.
    TLS_CERT_DIR is redirected to tmp_path so _setup_tls can write files.
    """
    mock_cert = MagicMock()
    mock_cert.certificate.__str__ = MagicMock(return_value="CERT_DATA")
    mock_cert.ca = None
    mock_key = MagicMock()
    mock_key.__str__ = MagicMock(return_value="KEY_DATA")

    with (
        patch("charm.TLS_CERT_DIR", tmp_path),
        patch("charm.ensure_storage_ready"),
        patch("charm.shutil.which", return_value="/usr/bin/doveconf"),
        # _setup_tls runs via _reconcile; mock the cert lookup so it succeeds
        patch(
            "charmlibs.interfaces.tls_certificates.TLSCertificatesRequiresV4.get_assigned_certificate",
            return_value=(mock_cert, mock_key),
        ),
        patch("charm.DovecotCharm._setup_dovecot"),
        patch("charm.DovecotCharm._setup_procmail"),
    ):
        # Fire certificate_available via config_changed (same handler)
        state_out = ctx.run(ctx.on.config_changed(), base_state)
    assert isinstance(state_out.unit_status, ops.ActiveStatus)
