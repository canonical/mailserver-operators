# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for utils."""

import utils


def test_logrotate_frequency():
    """Test log rotate frequency is updated."""
    with open("tests/unit/files/logrotate_frequency", encoding="utf-8") as f:
        want = f.read()
    assert utils.update_logrotate_conf("tests/unit/files/logrotate", frequency="daily") == want


def test_logrotate_non_exists():
    """Test update log rotate with a non existent file returns empty string."""
    assert (
        utils.update_logrotate_conf(
            "tests/unit/files/logrotate_file_does_not_exist", frequency="daily"
        )
        == ""
    )


def test_logrotate_retention():
    """Test update log rotate retention is correctly updated."""
    with open("tests/unit/files/logrotate_retention", encoding="utf-8") as f:
        want = f.read()
    assert utils.update_logrotate_conf("tests/unit/files/logrotate", retention=30) == want


def test_logrotate_retention_no_dateext():
    """Test update log rotate retention without dateext."""
    with open("tests/unit/files/logrotate_retention_no_dateext", encoding="utf-8") as f:
        want = f.read()
    assert (
        utils.update_logrotate_conf("tests/unit/files/logrotate", retention=30, dateext=False)
        == want
    )

    with open("tests/unit/files/logrotate_retention_no_dateext", encoding="utf-8") as f:
        want = f.read()
    assert (
        utils.update_logrotate_conf(
            "tests/unit/files/logrotate_retention", retention=30, dateext=False
        )
        == want
    )
