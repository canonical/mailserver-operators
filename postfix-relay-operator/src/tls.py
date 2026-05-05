# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""TLS Management Service Layer."""

import logging
import os
import subprocess  # nosec
from pathlib import Path
from typing import NamedTuple

from charmlibs.interfaces.tls_certificates import (
    CertificateRequestAttributes,
    ProviderCertificate,
    TLSCertificatesRequiresV4,
)

import utils

logger = logging.getLogger(__name__)


POSTFIX_NAME = "postfix"
TLS_RELATION_DIRPATH = Path("/etc/postfix/tls")
TLS_RELATION_CERT_FILEPATH = TLS_RELATION_DIRPATH / "fullchain.pem"
TLS_RELATION_KEY_FILEPATH = TLS_RELATION_DIRPATH / "key.pem"
TLS_RELATION_CA_FILEPATH = TLS_RELATION_DIRPATH / "ca.pem"
TLS_DH_PARAMS_FILEPATH = Path("/etc/ssl/private/dhparams.pem")


class TLSConfigPaths(NamedTuple):
    """A container for TLS file paths.

    Attributes:
        tls_dh_params: Path to the Diffie-Hellman parameters file.
        tls_cert: Path to the TLS certificate file.
        tls_key: Path to the TLS private key file.
        tls_cert_key: Path to a combined certificate and key file (currently unused).
    """

    tls_dh_params: str
    tls_cert: str
    tls_key: str
    tls_cert_key: str


def get_tls_config_paths() -> TLSConfigPaths:
    """Determine paths for TLS assets.

    Returns:
        TLSConfigPaths: A named tuple containing paths for TLS assets.

    The relation-provided certificate and key are discovered via
    `TLS_RELATION_CERT_FILEPATH` and `TLS_RELATION_KEY_FILEPATH` when provided.
    """
    tls_cert_key = ""
    tls_cert = "/etc/ssl/certs/ssl-cert-snakeoil.pem"
    tls_key = "/etc/ssl/private/ssl-cert-snakeoil.key"
    if os.path.exists(TLS_RELATION_CERT_FILEPATH) and os.path.exists(TLS_RELATION_KEY_FILEPATH):
        tls_cert = str(TLS_RELATION_CERT_FILEPATH)
        tls_key = str(TLS_RELATION_KEY_FILEPATH)
    if not os.path.exists(TLS_DH_PARAMS_FILEPATH):
        subprocess.check_call(
            ["openssl", "dhparam", "-out", str(TLS_DH_PARAMS_FILEPATH), "2048"]
        )  # nosec

    return TLSConfigPaths(
        tls_dh_params=str(TLS_DH_PARAMS_FILEPATH),
        tls_cert=tls_cert,
        tls_key=tls_key,
        tls_cert_key=tls_cert_key,
    )


def sync_tls_certificates(
    request: CertificateRequestAttributes, certificates: TLSCertificatesRequiresV4
) -> None:
    """Write TLS assets from the TLS relation to disk if available."""
    provider_certificate, private_key = certificates.get_assigned_certificate(request)
    if provider_certificate and private_key:
        _write_tls_files(provider_certificate, str(private_key), POSTFIX_NAME)


def _write_tls_files(
    certificate: ProviderCertificate, private_key: str, postfix_name: str
) -> None:
    """Persist TLS assets for Postfix to consume."""
    TLS_RELATION_DIRPATH.mkdir(parents=True, exist_ok=True)
    chain = [str(certificate.certificate), *[str(cert) for cert in certificate.chain]]
    fullchain = "\n\n".join(chain).strip() + "\n"
    utils.write_file(
        fullchain,
        TLS_RELATION_CERT_FILEPATH,
        perms=0o640,
        group=postfix_name,
    )
    utils.write_file(
        private_key,
        TLS_RELATION_KEY_FILEPATH,
        perms=0o640,
        group=postfix_name,
    )
    utils.write_file(
        str(certificate.ca) + "\n",
        TLS_RELATION_CA_FILEPATH,
        perms=0o644,
        group=postfix_name,
    )
