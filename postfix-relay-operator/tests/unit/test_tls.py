# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""TLS service unit tests."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

import tls


class TestGetTlsConfigPaths:
    @patch("tls.subprocess.check_call")
    def test_returns_snakeoil_and_generates_dhparams(
        self, mock_subprocess_call: Mock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        arrange: No relation certs and no DH params present.
        act: Call get_tls_config_paths.
        assert: Snakeoil paths are returned and openssl is invoked.
        """
        dhparams_path = tmp_path / "dhparams.pem"
        monkeypatch.setattr(tls, "TLS_DH_PARAMS_FILEPATH", dhparams_path)

        result = tls.get_tls_config_paths()

        mock_subprocess_call.assert_called_once_with(
            ["openssl", "dhparam", "-out", str(dhparams_path), "2048"]
        )
        assert result.tls_cert == "/etc/ssl/certs/ssl-cert-snakeoil.pem"
        assert result.tls_key == "/etc/ssl/private/ssl-cert-snakeoil.key"
        assert result.tls_dh_params == str(dhparams_path)

    @patch("tls.subprocess.check_call")
    def test_skips_openssl_when_dhparams_exist(
        self, mock_subprocess_call: Mock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        arrange: DH params already exist and no relation certs.
        act: Call get_tls_config_paths.
        assert: openssl is not called.
        """
        dhparams_path = tmp_path / "dhparams.pem"
        dhparams_path.touch()
        monkeypatch.setattr(tls, "TLS_DH_PARAMS_FILEPATH", dhparams_path)

        result = tls.get_tls_config_paths()

        mock_subprocess_call.assert_not_called()
        assert result.tls_cert == "/etc/ssl/certs/ssl-cert-snakeoil.pem"
        assert result.tls_key == "/etc/ssl/private/ssl-cert-snakeoil.key"
        assert result.tls_dh_params == str(dhparams_path)

    @patch("tls.subprocess.check_call")
    def test_relation_paths_preferred(
        self, mock_subprocess_call: Mock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        arrange: Relation cert/key files exist and DH params present.
        act: Call get_tls_config_paths.
        assert: Relation files are used and openssl is not called.
        """
        dhparams_path = tmp_path / "dhparams.pem"
        dhparams_path.touch()
        relation_cert = tmp_path / "fullchain.pem"
        relation_key = tmp_path / "key.pem"
        relation_cert.write_text("cert")
        relation_key.write_text("key")
        monkeypatch.setattr(tls, "TLS_DH_PARAMS_FILEPATH", dhparams_path)
        monkeypatch.setattr(tls, "TLS_RELATION_CERT_FILEPATH", relation_cert)
        monkeypatch.setattr(tls, "TLS_RELATION_KEY_FILEPATH", relation_key)

        result = tls.get_tls_config_paths()

        mock_subprocess_call.assert_not_called()
        assert result.tls_cert == str(relation_cert)
        assert result.tls_key == str(relation_key)
        assert result.tls_dh_params == str(dhparams_path)
