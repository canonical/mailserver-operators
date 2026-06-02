# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.
"""Unit tests for TLS certificate integration."""

from unittest.mock import MagicMock, patch

import ops
import ops.testing
import pytest
from conftest import _META, MAILNAME
from testing import TLSTestDovecotCharm

from exceptions import ConfigurationError


@pytest.fixture
def tls_ctx():
    """Context using TLSTestDovecotCharm: real DovecotSetup, no-op storage/HA."""
    return ops.testing.Context(TLSTestDovecotCharm, meta=_META, app_name="dovecot")


def test_no_tls_cert_yet_blocks(tls_ctx, base_state):
    """Charm must be Blocked when the TLS relation has no certificate yet.

    setup_tls calls get_assigned_certificate which returns (None, None) when
    no real provider has issued a cert — no external system calls are reached.
    """
    state_out = tls_ctx.run(tls_ctx.on.config_changed(), base_state)
    assert isinstance(state_out.unit_status, ops.BlockedStatus)
    assert "certificate" in state_out.unit_status.message.lower()


def test_setup_tls_writes_cert_key_and_chain(tls_ctx, base_state, tmp_path):
    """setup_tls writes cert (+ CA chain) and private key to tls_cert_dir.

    setup_tls is invoked by _reconcile at event dispatch time (context manager
    __exit__).  We patch dovecot_setup.TLS_CERT_DIR to tmp_path so no real
    filesystem paths are touched.
    """
    mock_cert = MagicMock()
    mock_cert.certificate.__str__ = MagicMock(return_value="CERT_DATA")
    mock_cert.ca.__str__ = MagicMock(return_value="CA_DATA")
    mock_key = MagicMock()
    mock_key.__str__ = MagicMock(return_value="KEY_DATA")

    with (
        patch("dovecot_setup.TLS_CERT_DIR", tmp_path),
        tls_ctx(tls_ctx.on.config_changed(), base_state) as mgr,
    ):
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


def test_setup_tls_no_ca_omits_chain(tls_ctx, base_state, tmp_path):
    """When provider_cert.ca is falsy the cert file must not have a trailing CA."""
    mock_cert = MagicMock()
    mock_cert.certificate.__str__ = MagicMock(return_value="CERT_DATA")
    mock_cert.ca = None  # no CA attached
    mock_key = MagicMock()
    mock_key.__str__ = MagicMock(return_value="KEY_DATA")

    with (
        patch("dovecot_setup.TLS_CERT_DIR", tmp_path),
        tls_ctx(tls_ctx.on.config_changed(), base_state) as mgr,
    ):
        mgr.charm._tls = MagicMock()
        mgr.charm._tls.get_assigned_certificate.return_value = (mock_cert, mock_key)

    cert_file = tmp_path / "example.com.pem"
    assert cert_file.read_text() == "CERT_DATA"


def test_setup_tls_no_private_key_raises(tls_ctx, base_state):
    """setup_tls must raise ConfigurationError when private key is unavailable.

    We call setup_tls directly inside the context manager body (before the
    event fires).  The error is raised before any filesystem writes so no
    TLS_CERT_DIR patch is needed.  At __exit__ _reconcile also calls
    setup_tls with the same mock, hits the same error, and sets BlockedStatus.
    """
    mock_cert = MagicMock()

    with tls_ctx(tls_ctx.on.config_changed(), base_state) as mgr:
        mgr.charm._tls = MagicMock()
        # cert present but private key is None — error raised before any mkdir
        mgr.charm._tls.get_assigned_certificate.return_value = (mock_cert, None)
        mock_config = MagicMock()
        mock_config.mailname = MAILNAME
        with pytest.raises(ConfigurationError):
            mgr.charm._dovecot_setup.setup_tls(mock_config)


def test_certificate_available_event_triggers_reconcile(tls_ctx, base_state, tmp_path):
    """The certificate_available event must be wired to _reconcile.

    When the cert is now available the charm should reach ActiveStatus.
    TLS_CERT_DIR is redirected to tmp_path so setup_tls can write files.
    """
    mock_cert = MagicMock()
    mock_cert.certificate.__str__ = MagicMock(return_value="CERT_DATA")
    mock_cert.ca = None
    mock_key = MagicMock()
    mock_key.__str__ = MagicMock(return_value="KEY_DATA")

    with (
        patch("dovecot_setup.TLS_CERT_DIR", tmp_path),
        patch(
            "charmlibs.interfaces.tls_certificates.TLSCertificatesRequiresV4.get_assigned_certificate",
            return_value=(mock_cert, mock_key),
        ),
    ):
        state_out = tls_ctx.run(tls_ctx.on.config_changed(), base_state)
    assert isinstance(state_out.unit_status, ops.ActiveStatus)
