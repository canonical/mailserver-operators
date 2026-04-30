#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helpful tools for the charm."""

import logging
import os
import pwd
import shutil
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


def prepare_user_dir(dirpath: str, username: str) -> None:
    """Recreate dirpath as a fresh, empty directory owned by the given system user.

    Args:
        dirpath: path to create (any existing content is removed first).
        username: system user that should own the directory.

    Raises:
        KeyError: if username does not exist on the system.
    """
    pw = pwd.getpwnam(username)
    shutil.rmtree(dirpath, ignore_errors=True)
    os.makedirs(dirpath, mode=0o700)
    os.chown(dirpath, pw.pw_uid, pw.pw_gid)


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
