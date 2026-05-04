#!/usr/bin/env python3

# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests."""

# pylint: disable=too-many-arguments,too-many-locals

import json
import logging
import pathlib
import smtplib
import socket
import subprocess  # nosec B404
import tempfile
import time
import typing

import jubilant
import pytest
import requests

logger = logging.getLogger(__name__)


def generate_opendkim_genkey(domain: str, selector: str) -> typing.Tuple[str, str]:
    """Generate dkim txt record and private key for a domain an selector.

    Args:
        domain: Domain for the key.
        selector: dkim selector for the key.

    Returns:
        The txt record and the private key.
    """
    with tempfile.TemporaryDirectory(dir=pathlib.Path.home()) as tmpdirname:
        subprocess.run(  # nosec
            ["opendkim-genkey", "-s", selector, "-d", domain],
            check=True,
            cwd=tmpdirname,
        )
        # Two files should have been created, {selector}.txt and {selector}.private
        txt_data = (pathlib.Path(tmpdirname) / pathlib.Path(f"{selector}.txt")).read_text()
        private_data = (pathlib.Path(tmpdirname) / pathlib.Path(f"{selector}.private")).read_text()
        return txt_data, private_data


@pytest.fixture(scope="session", name="machine_ip_address")
def machine_ip_address_fixture() -> str:
    """IP address for the machine running the tests.

    Returns:
        The IP address of the current machine.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip_address = s.getsockname()[0]
    logger.info("IP Address for the current test runner: %s", ip_address)
    s.close()
    return ip_address


@pytest.mark.abort_on_fail
def test_opendkim_signed_message(
    juju: jubilant.Juju, opendkim_app, smtp_relay_app, machine_ip_address
):
    """
    arrange: Deploy smtp-relay charm with the testrelay.internal domain in relay domains.
    act: Send an email to an address with the testrelay.internal domain.
    assert: The email is correctly relayed to the mailcatcher local test smtp server.
    """
    status = juju.status()
    unit = next(iter(status.apps[smtp_relay_app].units.values()))
    unit_ip = unit.public_address

    domain = "testrelay.internal"
    selector = "default"
    keyname = "testrelay-internal-default"
    _, private_key = generate_opendkim_genkey(domain=domain, selector=selector)

    try:
        secret_id = juju.add_secret("opendkimsecret", {f"{keyname}": private_key})
    except jubilant.CLIError as e:
        secret_info = juju.show_secret("opendkimsecret")
        secret_id = secret_info.uri
        if "already exists" in e.stderr:
            juju.update_secret(secret_id, {f"{keyname}": private_key})
        else:
            logger.error("Error adding secret %s %s", e.stderr, e.stdout)
            raise e

    juju.cli("grant-secret", secret_id, opendkim_app)
    keytable = [
        [f"{selector}._domainkey.{domain}", f"{domain}:{selector}:/etc/dkimkeys/{keyname}.private"]
    ]
    signingtable = [[f"*@{domain}", f"{selector}._domainkey.{domain}"]]
    juju.config(
        opendkim_app,
        {
            "keytable": json.dumps(keytable),
            "signingtable": json.dumps(signingtable),
            "private-keys": secret_id,
        },
    )

    command_to_put_domain = f"echo {machine_ip_address} {domain} | sudo tee -a /etc/hosts"
    juju.exec(machine=int(unit.machine), command=command_to_put_domain)

    juju.config(smtp_relay_app, {"relay_domains": f"- {domain}"})
    juju.wait(
        lambda status: jubilant.all_active(status, opendkim_app, smtp_relay_app),
        timeout=3 * 60,
        delay=5,
    )

    mailcatcher_url = "http://127.0.0.1:1080/messages"
    messages = requests.get(mailcatcher_url, timeout=5).json()
    # There should not be any message in mailcatcher before the test.
    assert len(messages) == 0

    with smtplib.SMTP(unit_ip) as server:
        server.set_debuglevel(2)
        from_addr = f"Some One <someone@{domain}>"
        to_addrs = [f"otherone@{domain}"]
        message = f"""\
Subject: Hi Mailtrap
To: {from_addr}
From: {to_addrs[0]}
This is my first message with Python."""
        server.sendmail(from_addr=from_addr, to_addrs=to_addrs, msg=message)

    for _ in range(5):
        messages = requests.get(mailcatcher_url, timeout=5).json()
        if messages:
            break
        time.sleep(1)
    assert len(messages) == 1
    message = requests.get(f"{mailcatcher_url}/{messages[0]['id']}.source", timeout=5).text
    logger.info("Message in mailcatcher: %s", message)
    assert f"DKIM-Signature: v=1; a=rsa-sha256; c=relaxed/relaxed; d={domain}" in message

    # Clean up mailcatcher
    requests.delete(f"{mailcatcher_url}/{messages[0]['id']}", timeout=5)


@pytest.mark.abort_on_fail
def test_opendkim_testkey_failed_validation_(juju: jubilant.Juju, opendkim_app, smtp_relay_app):
    """
    arrange: Deploy opendkim and smtp-relay.
    act: OpenDKIM configuration is invalid as a key file is missing.
    assert: The OpenDKIM charm is blocked and message says that the configuration is invalid.
    """
    domain = "testrelay.internal"
    selector = "default"
    keyname = "testrelay-internal-default"
    _, private_key = generate_opendkim_genkey(domain=domain, selector=selector)

    try:
        secret_id = juju.add_secret("opendkimsecret", {f"{keyname}": private_key})
    except jubilant.CLIError as e:
        secret_info = juju.show_secret("opendkimsecret")
        secret_id = secret_info.uri
        if "already exists" in e.stderr:
            juju.update_secret(secret_id, {f"{keyname}": private_key})
        else:
            logger.error("Error adding secret %s %s", e.stderr, e.stdout)
            raise e

    juju.cli("grant-secret", secret_id, opendkim_app)
    keytable = [
        [f"{selector}._domainkey.{domain}", f"{domain}:{selector}:/etc/dkimkeys/WRONGNAME.private"]
    ]
    signingtable = [[f"*@{domain}", f"{selector}._domainkey.{domain}"]]
    juju.config(
        opendkim_app,
        {
            "keytable": json.dumps(keytable),
            "signingtable": json.dumps(signingtable),
            "private-keys": secret_id,
        },
    )

    juju.config(smtp_relay_app, {"relay_domains": f"- {domain}"})
    juju.wait(
        lambda status: (
            status.apps[smtp_relay_app].is_active and status.apps[opendkim_app].is_blocked
        ),
        timeout=3 * 60,
        delay=5,
    )
    status = juju.status()
    assert "Wrong opendkim configuration" in status.apps[opendkim_app].app_status.message


@pytest.mark.abort_on_fail
def test_metrics_configured(juju: jubilant.Juju, opendkim_app, smtp_relay_app, machine_ip_address):
    """
    arrange: Deploy opendkim.
    act: Get the metrics from the unit.
    assert: The metrics can be scraped and there are metrics.
    """
    status = juju.status()
    unit = next(iter(status.apps[opendkim_app].units.values()))
    unit_ip = unit.public_address

    domain = "testrelay.internal"
    selector = "default"
    keyname = "testrelay-internal-default"
    _, private_key = generate_opendkim_genkey(domain=domain, selector=selector)

    try:
        secret_id = juju.add_secret("opendkimsecret", {f"{keyname}": private_key})
    except jubilant.CLIError as e:
        secret_info = juju.show_secret("opendkimsecret")
        secret_id = secret_info.uri
        if "already exists" in e.stderr:
            juju.update_secret(secret_id, {f"{keyname}": private_key})
        else:
            logger.error("Error adding secret %s %s", e.stderr, e.stdout)
            raise e

    juju.cli("grant-secret", secret_id, opendkim_app)
    keytable = [
        [f"{selector}._domainkey.{domain}", f"{domain}:{selector}:/etc/dkimkeys/{keyname}.private"]
    ]
    signingtable = [[f"*@{domain}", f"{selector}._domainkey.{domain}"]]
    juju.config(
        opendkim_app,
        {
            "keytable": json.dumps(keytable),
            "signingtable": json.dumps(signingtable),
            "private-keys": secret_id,
        },
    )

    command_to_put_domain = f"echo {machine_ip_address} {domain} | sudo tee -a /etc/hosts"
    juju.exec(machine=int(unit.machine), command=command_to_put_domain)

    juju.config(smtp_relay_app, {"relay_domains": f"- {domain}"})
    juju.wait(
        lambda status: jubilant.all_active(status, opendkim_app, smtp_relay_app),
        timeout=3 * 60,
        delay=5,
    )
    metrics_output = requests.get(f"http://{unit_ip}:9103/metrics", timeout=5).text
    # Some of the most important metrics used in the dashboard and alerts.
    expected_metrics = [
        "cpu_usage_idle",
        "procstat_lookup_running",
        "netstat_tcp_established",
    ]
    for expected_metric in expected_metrics:
        assert expected_metric in metrics_output


@pytest.mark.abort_on_fail
def test_opendkim_verify_mode_with_trusted_sources(
    juju: jubilant.Juju, opendkim_app, smtp_relay_app
):
    """
    arrange: Deploy opendkim with valid signing config and trusted-sources set.
    act: Configure opendkim with mode=sv and trusted-sources with specific networks.
    assert: The internalhosts file is written with the correct entries and opendkim.conf
        references it.
    """
    domain = "testrelay.internal"
    selector = "default"
    keyname = "testrelay-internal-default"
    _, private_key = generate_opendkim_genkey(domain=domain, selector=selector)

    try:
        secret_id = juju.add_secret("opendkimsecret", {f"{keyname}": private_key})
    except jubilant.CLIError as e:
        if "already exists" in e.stderr:
            secret_info = juju.show_secret("opendkimsecret")
            secret_id = secret_info.uri
            juju.update_secret(secret_id, {f"{keyname}": private_key})
        else:
            logger.error("Error adding secret %s %s", e.stderr, e.stdout)
            raise e

    juju.cli("grant-secret", secret_id, opendkim_app)
    keytable = [
        [f"{selector}._domainkey.{domain}", f"{domain}:{selector}:/etc/dkimkeys/{keyname}.private"]
    ]
    signingtable = [[f"*@{domain}", f"{selector}._domainkey.{domain}"]]
    trusted_sources = "10.0.0.0/8, 192.168.1.0/24, 172.16.0.0/12"
    juju.config(
        opendkim_app,
        {
            "keytable": json.dumps(keytable),
            "signingtable": json.dumps(signingtable),
            "private-keys": secret_id,
            "mode": "sv",
            "trusted-sources": trusted_sources,
        },
    )

    juju.config(smtp_relay_app, {"relay_domains": f"- {domain}"})
    juju.wait(
        lambda status: jubilant.all_active(status, opendkim_app, smtp_relay_app),
        timeout=3 * 60,
        delay=5,
    )

    # Verify the internalhosts file was written with the correct entries
    status = juju.status()
    opendkim_unit_name = next(iter(status.apps[opendkim_app].units))
    internalhosts_task = juju.exec(
        "cat /var/snap/opendkim/current/etc/dkimkeys/internalhosts", unit=opendkim_unit_name
    )
    internalhosts_content = internalhosts_task.stdout.strip()
    assert "10.0.0.0/8" in internalhosts_content
    assert "192.168.1.0/24" in internalhosts_content
    assert "172.16.0.0/12" in internalhosts_content

    # Verify opendkim.conf references the internalhosts file
    opendkim_conf_task = juju.exec(
        "cat /var/snap/opendkim/current/etc/opendkim.conf", unit=opendkim_unit_name
    )
    opendkim_conf_content = opendkim_conf_task.stdout
    assert (
        "InternalHosts file:/var/snap/opendkim/current/etc/dkimkeys/internalhosts"
        in opendkim_conf_content
    )
