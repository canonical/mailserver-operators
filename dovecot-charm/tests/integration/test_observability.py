# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import jubilant
import requests


def test_dovecot_metrics(juju: jubilant.Juju, dovecot_charm: str):
    """Verify expected metrics are present on the OpenMetrics endpoint."""
    logging.info("Checking for specific Dovecot metrics...")
    status = juju.status()
    units = status.apps[dovecot_charm].units.values()
    assert units, "No units found for the Dovecot charm application"
    for unit in units:
        metrics = requests.get(f"http://{unit.public_address}:9900/metrics", timeout=5).text
        assert "dovecot_build_info" in metrics, "dovecot_build_info metric should be present"
        assert 'version="' in metrics, "dovecot_build_info should contain version info"
        assert "process_start_time_seconds" in metrics, (
            "process_start_time_seconds metric should be present"
        )
    logging.info("Dovecot metrics confirmed.")


def test_cos_agent_endpoint_present(juju: jubilant.Juju, dovecot_charm: str):
    """Verify the cos-agent endpoint is present, enabling Prometheus rules, Grafana dashboards and Loki log rules delivery."""
    logging.info("Checking for cos-agent endpoint...")
    output = juju.cli("show-application", dovecot_charm, "--format", "json")
    assert "cos-agent" in output, "cos-agent endpoint not found in application metadata"
    logging.info("COS agent endpoint confirmed.")
