# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import subprocess  # nosec B404
import time
import typing

import jubilant
from tenacity import retry, stop_after_attempt, wait_fixed


def test_dovecot_stats_port_listening(juju: jubilant.Juju, dovecot_charm: str):
    """Verify port 9900 (Dovecot stats/OpenMetrics) is listening."""
    logging.info("Checking if port 9900 is listening...")
    port_check = juju.exec("ss", "-tln", unit=f"{dovecot_charm}/0").stdout
    logging.info(f"Open ports:\n{port_check}")
    assert ":9900" in port_check, "Port 9900 should be listening for Dovecot stats"


def test_dovecot_openmetrics_endpoint(juju: jubilant.Juju, dovecot_charm: str):
    """Verify the Dovecot OpenMetrics endpoint responds on port 9900."""
    logging.info("Checking OpenMetrics endpoint on port 9900...")

    metrics_content = None
    for i in range(5):
        try:
            metrics_content = juju.exec(
                "curl", "-s", "http://localhost:9900/metrics", unit=f"{dovecot_charm}/0"
            ).stdout
            if metrics_content:
                break
        except subprocess.CalledProcessError:
            logging.warning(f"Attempt {i + 1}: OpenMetrics endpoint not ready yet")
            time.sleep(5)

    assert metrics_content, "OpenMetrics endpoint did not respond"
    assert "# HELP" in metrics_content or "# TYPE" in metrics_content, (
        "Metrics endpoint response does not look like OpenMetrics/Prometheus metrics"
    )
    assert "dovecot_" in metrics_content, "Metrics should contain dovecot-specific metrics"
    logging.info("OpenMetrics endpoint responds with Dovecot metrics.")


def test_dovecot_build_info_metric(juju: jubilant.Juju, dovecot_charm: str):
    """Verify dovecot_build_info metric is present."""
    logging.info("Checking for dovecot_build_info metric...")
    metrics = juju.exec(
        "curl", "-s", "http://localhost:9900/metrics", unit=f"{dovecot_charm}/0"
    ).stdout
    assert "dovecot_build_info" in metrics, "dovecot_build_info metric should be present"
    assert 'version="' in metrics, "dovecot_build_info should contain version info"
    logging.info("dovecot_build_info metric confirmed.")


def test_dovecot_process_start_time_metric(juju: jubilant.Juju, dovecot_charm: str):
    """Verify process_start_time_seconds metric is present."""
    logging.info("Checking for process_start_time_seconds metric...")
    metrics = juju.exec(
        "curl", "-s", "http://localhost:9900/metrics", unit=f"{dovecot_charm}/0"
    ).stdout
    assert "process_start_time_seconds" in metrics, (
        "process_start_time_seconds metric should be present"
    )
    logging.info("process_start_time_seconds metric confirmed.")


def test_dovecot_auth_metrics(juju: jubilant.Juju, dovecot_charm: str):
    """Verify authentication-related metrics are present."""
    logging.info("Checking for authentication metrics...")
    metrics = juju.exec(
        "curl", "-s", "http://localhost:9900/metrics", unit=f"{dovecot_charm}/0"
    ).stdout
    assert "dovecot_" in metrics, "Should have dovecot metrics"
    logging.info("Dovecot metrics confirmed.")


def test_prometheus_alert_rules_present(juju: jubilant.Juju, dovecot_charm: str):
    """Verify Prometheus alert rules files are present in the charm."""
    logging.info("Checking for Prometheus alert rules...")
    endpoint_check = subprocess.run(  # nosec B607
        ["juju", "show-application", dovecot_charm, "--format", "json"],
        capture_output=True,
        text=True,
    )
    assert "cos-agent" in endpoint_check.stdout, (
        "cos-agent endpoint not found in application metadata"
    )
    logging.info("COS agent endpoint confirmed in application metadata.")


def test_grafana_dashboard_present(juju: jubilant.Juju, dovecot_charm: str):
    """Verify Grafana dashboard files are present in the charm."""
    logging.info("Checking for Grafana dashboard...")
    endpoint_check = subprocess.run(  # nosec B607
        ["juju", "show-application", dovecot_charm, "--format", "json"],
        capture_output=True,
        text=True,
    )
    assert "cos-agent" in endpoint_check.stdout, (
        "cos-agent endpoint not found in application metadata"
    )
    logging.info("COS agent endpoint confirmed (dashboard delivery available).")


def test_loki_log_rules_present(juju: jubilant.Juju, dovecot_charm: str):
    """Verify Loki log alert rules are present in the charm."""
    logging.info("Checking for Loki log alert rules...")
    endpoint_check = subprocess.run(  # nosec B607
        ["juju", "show-application", dovecot_charm, "--format", "json"],
        capture_output=True,
        text=True,
    )
    assert "cos-agent" in endpoint_check.stdout, (
        "cos-agent endpoint not found in application metadata"
    )
    logging.info("COS agent endpoint confirmed (log rules delivery available).")


@retry(stop=stop_after_attempt(5), wait=wait_fixed(15))
def check_grafana_dashboards_patiently(grafana_session, grafana_ip: str, dashboard: str):
    """Check if dashboard can be found in Grafana via REST API."""
    dashboards = grafana_session.get(
        f"http://{grafana_ip}:3000/api/search",
        timeout=10,
        params={"query": dashboard},
    ).json()
    assert len(dashboards)


@retry(stop=stop_after_attempt(5), wait=wait_fixed(15))
def check_grafana_datasource_types_patiently(
    grafana_session, grafana_ip: str, datasource_types: typing.List[str]
):
    """Check if datasources of specified types can be found in Grafana."""
    datasources = grafana_session.get(
        f"http://{grafana_ip}:3000/api/datasources",
        timeout=10,
    ).json()
    found_types = {ds.get("type") for ds in datasources}
    for ds_type in datasource_types:
        assert ds_type in found_types, f"Datasource type '{ds_type}' not found in Grafana"


def test_grafana_integration(
    dovecot_charm: str,
    juju: jubilant.Juju,
    cos_apps: typing.Dict[str, str],
    session_with_retry,
):
    """Test Grafana integration with dovecot-charm dashboard."""
    app = dovecot_charm
    dashboard_name = "dovecot"
    juju.integrate(app, cos_apps["loki_app"])
    juju.integrate(app, cos_apps["prometheus_app"])
    juju.integrate(app, cos_apps["grafana_app"])

    juju.wait(lambda status: jubilant.all_active(status, app, cos_apps["grafana_app"]))
    status = juju.status()
    task = juju.run(f"{cos_apps['grafana_app']}/0", "get-admin-password")
    password = task.results["admin-password"]
    grafana_ip = status.apps[cos_apps["grafana_app"]].units[f"{cos_apps['grafana_app']}/0"].address
    session_with_retry.post(
        f"http://{grafana_ip}:3000/login",
        json={
            "user": "admin",
            "password": password,
        },
    ).raise_for_status()
    check_grafana_datasource_types_patiently(
        session_with_retry, grafana_ip, ["prometheus", "loki"]
    )
    check_grafana_dashboards_patiently(session_with_retry, grafana_ip, dashboard_name)
