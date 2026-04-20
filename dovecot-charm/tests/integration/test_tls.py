# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import imaplib
import logging
import ssl

import jubilant
import pytest

TLS_APP = "self-signed-certificates"


@pytest.fixture(scope="module")
def deploy_with_tls(juju: jubilant.Juju, dovecot_charm: str):
    if TLS_APP not in juju.status().apps:
        logging.info("Deploying self-signed-certificates...")
        juju.deploy(TLS_APP, channel="latest/stable")
    else:
        logging.info(f"{TLS_APP} already deployed, skipping deployment.")

    try:
        logging.info("Adding TLS relation...")
        juju.integrate(f"{dovecot_charm}:certificates", f"{TLS_APP}:certificates")
    except Exception:
        logging.info("TLS relation already there...")

    # The charm is Blocked without a certificate; wait until it becomes Active
    # (meaning _setup_tls succeeded and cert files are written).
    logging.info("Waiting for active/idle status...")
    juju.wait(jubilant.all_active, timeout=1200)


def test_tls_certificate_files_written(juju, dovecot_charm, deploy_with_tls):
    """Verify that TLS certificate and key files are written to the unit."""
    unit_name = f"{dovecot_charm}/0"
    logging.info(f"Targeting unit: {unit_name}")

    logging.info("Checking for TLS certificate file...")
    cert_check = juju.exec("ls", "-l", "/etc/dovecot/private/example.com.pem", unit=unit_name)
    logging.info(f"Certificate file: {cert_check}")
    assert "example.com.pem" in cert_check.stdout, "Certificate file not found"

    logging.info("Checking for TLS key file...")
    key_check = juju.exec("ls", "-l", "/etc/dovecot/private/example.com.key", unit=unit_name)
    logging.info(f"Key file: {key_check}")
    assert "example.com.key" in key_check.stdout, "Key file not found"


def test_tls_certificate_permissions(juju, dovecot_charm, deploy_with_tls):
    """Verify correct file permissions on TLS cert and key."""
    unit_name = f"{dovecot_charm}/0"

    cert_perms = juju.exec(
        "stat", "-c", "%a", "/etc/dovecot/private/example.com.pem", unit=unit_name
    )
    logging.info(f"Certificate permissions: {cert_perms.stdout}")
    assert cert_perms.stdout.strip() == "644", (
        f"Certificate permissions should be 644, got {cert_perms.stdout}"
    )

    key_perms = juju.exec(
        "stat", "-c", "%a", "/etc/dovecot/private/example.com.key", unit=unit_name
    )
    logging.info(f"Key permissions: {key_perms.stdout}")
    assert key_perms.stdout.strip() == "600", (
        f"Key permissions should be 600, got {key_perms.stdout}"
    )


def test_tls_certificate_content_valid(juju, dovecot_charm, deploy_with_tls):
    """Verify the certificate file contains a valid PEM certificate."""
    unit_name = f"{dovecot_charm}/0"

    cert_content = juju.exec("head", "-1", "/etc/dovecot/private/example.com.pem", unit=unit_name)
    assert "BEGIN CERTIFICATE" in cert_content.stdout, (
        f"Certificate file does not contain valid PEM data: {cert_content.stdout}"
    )

    key_content = juju.exec("head", "-1", "/etc/dovecot/private/example.com.key", unit=unit_name)
    assert "BEGIN" in key_content.stdout and "KEY" in key_content.stdout, (
        f"Key file does not contain valid PEM key data: {key_content.stdout}"
    )


def test_tls_dovecot_config_references_cert(juju, dovecot_charm, deploy_with_tls):
    """Verify dovecot configuration uses ssl=required and references the cert."""
    unit_name = f"{dovecot_charm}/0"

    dovecot_conf = juju.exec(
        "cat", "/etc/dovecot/conf.d/99-local-dovecot-charm.conf", unit=unit_name
    )
    logging.info("Checking dovecot SSL configuration...")
    assert "ssl = required" in dovecot_conf.stdout
    assert "ssl_cert" in dovecot_conf.stdout
    assert "example.com" in dovecot_conf.stdout
    assert "ssl_min_protocol = TLSv1.2" in dovecot_conf.stdout


def test_tls_dovecot_ssl_port_responds(juju, dovecot_charm, deploy_with_tls):
    """Verify dovecot responds on the SSL IMAP port (993)."""
    unit_name = f"{dovecot_charm}/0"
    status = juju.status()
    unit_ip = status.apps[dovecot_charm].units[unit_name].public_address

    logging.info(f"Checking IMAP SSL port on {unit_ip}:993...")

    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    connected = False
    for i in range(5):
        try:
            mail = imaplib.IMAP4_SSL(unit_ip, port=993, ssl_context=context)
            mail.logout()
            connected = True
            break
        except Exception as e:
            logging.warning(f"Attempt {i + 1} to connect to IMAP SSL failed: {e}")

    assert connected, f"Failed to connect to IMAP SSL port on {unit_ip}:993"
    logging.info("IMAP SSL port responds correctly.")
