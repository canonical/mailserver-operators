#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helpful tools for the charm."""

import logging
import os
import tarfile

logger = logging.getLogger(__name__)


def configure_file(path, entry):
    """Add an entry to a config file if it doesn't already exist."""
    with open(path, "a+") as f:
        f.seek(0)
        if entry in f.read():
            logger.info(f"Entry already exists in {path}")
            return

        logger.info(f"Adding entry to {path}")
        f.write(entry)
    logger.info(f"{path} configured")


def create_tarball(tar_path: str, base_dir: str, arcname: str) -> None:
    """Create a gzip-compressed tarball of a directory.

    Args:
        tar_path: destination path for the .tar.gz file.
        base_dir: directory that contains the source tree to archive.
        arcname: name of the top-level entry inside the archive (relative to base_dir).
    """
    with tarfile.open(tar_path, "w:gz") as tf:
        tf.add(os.path.join(base_dir, arcname), arcname=arcname)
    os.chmod(tar_path, 0o644)
