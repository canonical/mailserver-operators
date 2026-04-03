# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import jubilant


def test_packages_installed(juju: jubilant.Juju, dovecot_charm: str):
    """Verify required packages are installed."""
    logging.info("Checking if dovecot-lmtpd is installed...")
    juju.exec("dpkg -l | grep dovecot-lmtpd", unit=f"{dovecot_charm}/0")


def test_ports_listening(juju: jubilant.Juju, dovecot_charm: str):
    """Verify mail ports are open/listening."""
    ports = [143, 993, 110, 995]

    logging.info("Checking listening ports...")

    for port in ports:
        logging.info(f"Checking port {port}...")
        cmd = f"ss -tln | grep ':{port} '"
        juju.exec(cmd, unit=f"{dovecot_charm}/0")


def test_clear_queue_action(juju: jubilant.Juju, dovecot_charm: str):
    """Test the clear-queue action."""
    unit_name = f"{dovecot_charm}/0"

    logging.info("Running clear-queue action (defaults)...")
    result = juju.run(unit_name, "clear-queue")
    assert result.status == "completed"
    logging.info(f"Action output: {result.results.get('output')}")

    logging.info("Running clear-queue action (all)...")
    result = juju.run(unit_name, "clear-queue", params={"queue": "all"})
    assert result.status == "completed"
    logging.info(f"Action output: {result.results.get('output')}")
