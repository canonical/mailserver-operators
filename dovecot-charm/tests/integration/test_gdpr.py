# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import time
from typing import cast

import jubilant
import pytest

TEST_USER = "gdpruser"
TEST_PASSWORD = "gdprpassword"


def _setup_test_user(juju, unit_name):
    """Create a test user and inject a test email."""
    logging.info(f"Creating test user '{TEST_USER}' on {unit_name}...")
    juju.exec(
        f"id -u {TEST_USER} || useradd -m -G mail {TEST_USER} -s /bin/bash",
        unit=unit_name,
    )
    juju.exec(f"usermod -aG mail {TEST_USER}", unit=unit_name)
    juju.exec(f"echo '{TEST_USER}:{TEST_PASSWORD}' | chpasswd", unit=unit_name)

    juju.exec(
        f"install -d -m 0750 -o {TEST_USER} -g {TEST_USER} /srv/mail/archives/{TEST_USER}",
        unit=unit_name,
    )
    juju.exec(
        f"install -d -m 0750 -o {TEST_USER} -g {TEST_USER} /tmp/gdpr-takeout/{TEST_USER}",
        unit=unit_name,
    )

    logging.info("Injecting test email...")
    cmd = f"echo 'GDPR test body' | mail -s 'GDPR Test Email' {TEST_USER}@localhost"
    juju.exec(cmd, unit=unit_name)

    time.sleep(10)


def test_gdpr_archive_compressed(juju, dovecot_charm):
    """Test GDPR archive action with compression."""
    unit_name = f"{dovecot_charm}/0"
    logging.info(f"Targeting unit: {unit_name}")

    _setup_test_user(juju, unit_name)

    logging.info("Running gdpr-archive action (compressed)...")
    result = juju.run(
        unit_name,
        "gdpr-archive",
        params={"username": TEST_USER, "compress": True},
    )
    logging.info(f"Action status: {result.status}")
    logging.info(f"Action results: {result.results}")

    assert result.status == "completed", f"Action failed: {result.results}"
    assert "path" in result.results
    assert result.results["path"].endswith(".tar.gz")

    archive_path = result.results["path"]
    file_check = juju.exec(f"ls -l {archive_path}", unit=unit_name).stdout.strip()
    logging.info(f"Archive file: {file_check}")
    assert TEST_USER in file_check

    juju.exec(f"rm -f {archive_path}", unit=unit_name)


def test_gdpr_archive_uncompressed(juju, dovecot_charm):
    """Test GDPR archive action without compression."""
    unit_name = f"{dovecot_charm}/0"

    _setup_test_user(juju, unit_name)

    logging.info("Running gdpr-archive action (uncompressed)...")
    result = juju.run(
        unit_name,
        "gdpr-archive",
        params={"username": TEST_USER, "compress": False},
    )

    assert result.status == "completed", f"Action failed: {result.results}"
    assert "path" in result.results
    assert not result.results["path"].endswith(".tar.gz")

    archive_path = result.results["path"]
    dir_check = juju.exec(f"ls -ld {archive_path}", unit=unit_name).stdout.strip()
    logging.info(f"Archive directory: {dir_check}")
    assert archive_path in dir_check
    juju.exec(f"rm -rf {archive_path}", unit=unit_name)


def test_gdpr_delete_requires_confirm(juju, dovecot_charm):
    """Test that GDPR delete action fails without confirmation."""
    unit_name = f"{dovecot_charm}/0"

    logging.info("Running gdpr-delete action without confirm (expect failure)...")

    with pytest.raises(jubilant.TaskError) as exc_info:
        juju.run(
            unit_name,
            "gdpr-delete",
            params={"username": TEST_USER, "confirm": False},
        )
    assert "Deletion not confirmed" in cast(jubilant.TaskError, exc_info.value).task.message
    logging.info("GDPR delete correctly rejected without confirmation.")


def test_gdpr_delete_confirmed(juju, dovecot_charm):
    """Test GDPR delete action with confirmation."""
    unit_name = f"{dovecot_charm}/0"

    delete_user = "gdprdeleteuser"
    logging.info(f"Creating user '{delete_user}' for deletion test...")
    juju.exec(
        f"id -u {delete_user} || useradd -m -G mail {delete_user} -s /bin/bash",
        unit=unit_name,
    )
    juju.exec(f"echo '{delete_user}:password' | chpasswd", unit=unit_name)

    cmd = f"echo 'Delete me' | mail -s 'Delete Test' {delete_user}@localhost"
    juju.exec(cmd, unit=unit_name)

    time.sleep(10)

    logging.info("Running gdpr-delete action with confirm=true...")
    result = juju.run(
        unit_name,
        "gdpr-delete",
        params={"username": delete_user, "confirm": True},
    )
    logging.info(f"Action status: {result.status}")
    logging.info(f"Action results: {result.results}")

    assert result.status == "completed", f"Action failed: {result.results}"
    assert result.results.get("status") == "success"

    with pytest.raises(jubilant.TaskError) as exc_info:
        juju.exec(f"ls /srv/mail/{delete_user}", unit=unit_name)

    assert (
        f"cannot access '/srv/mail/{delete_user}'"
        in cast(jubilant.TaskError, exc_info.value).task.stderr
    )

    juju.exec(f"userdel -r {delete_user} 2>/dev/null || true", unit=unit_name)


def test_gdpr_takeout_maildir(juju, dovecot_charm):
    """Test GDPR takeout action with maildir format."""
    unit_name = f"{dovecot_charm}/0"

    _setup_test_user(juju, unit_name)

    logging.info("Running gdpr-takeout action (maildir)...")
    result = juju.run(
        unit_name,
        "gdpr-takeout",
        params={"username": TEST_USER, "format": "maildir"},
    )
    logging.info(f"Action status: {result.status}")
    logging.info(f"Action results: {result.results}")

    assert result.status == "completed", f"Action failed: {result.results}"
    assert "path" in result.results
    assert result.results["path"].endswith(".tar.gz")

    takeout_path = result.results["path"]
    file_check = juju.exec(f"ls -l {takeout_path}", unit=unit_name).stdout.strip()
    logging.info(f"Takeout file: {file_check}")

    juju.exec(f"rm -f {takeout_path}", unit=unit_name)


def test_gdpr_takeout_mbox(juju, dovecot_charm):
    """Test GDPR takeout action with mbox format."""
    unit_name = f"{dovecot_charm}/0"

    _setup_test_user(juju, unit_name)

    logging.info("Running gdpr-takeout action (mbox)...")
    result = juju.run(
        unit_name,
        "gdpr-takeout",
        params={"username": TEST_USER, "format": "mbox"},
    )
    logging.info(f"Action status: {result.status}")
    logging.info(f"Action results: {result.results}")

    assert result.status == "completed", f"Action failed: {result.results}"
    assert "path" in result.results
    assert result.results["path"].endswith(".tar.gz")

    takeout_path = result.results["path"]
    file_check = juju.exec(f"ls -l {takeout_path}", unit=unit_name).stdout.strip()
    logging.info(f"Takeout file: {file_check}")

    juju.exec(f"rm -f {takeout_path}", unit=unit_name)


def test_gdpr_archive_nonexistent_user(juju, dovecot_charm):
    """Test GDPR archive action with a user that doesn't exist."""
    unit_name = f"{dovecot_charm}/0"

    logging.info("Running gdpr-archive for nonexistent user...")

    with pytest.raises(jubilant.TaskError) as exc_info:
        juju.run(
            unit_name,
            "gdpr-archive",
            params={"username": "nonexistent_user_xyz", "compress": True},
        )
    assert "Error: User doesn't exist" in cast(jubilant.TaskError, exc_info.value).task.message

    logging.info("GDPR archive correctly failed for nonexistent user.")
