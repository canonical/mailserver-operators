# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Utils unit tests."""

import os
import tempfile

import utils


def test_write_file():
    """
    arrange: do nothing.
    act: write in a file.
    assert: the file content matches what was intended.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        source = "# User-provided config added here"
        dest = os.path.join(tmpdir, "my-test-file")

        utils.write_file(source, dest)

        with open(dest, "r", encoding="utf-8") as f:
            got = f.read()
        assert got == source
