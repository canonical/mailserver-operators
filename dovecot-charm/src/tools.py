#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helpful tools for the charm."""

import logging
import os

logger = logging.getLogger(__name__)


def configure_file(path, entry):
    """Add an entry to a config file if it doesn't already exist."""
    if os.path.exists(path):
        with open(path) as f:
            if entry in f.read():
                logger.info(f"Entry already exists in {path}")
                return

    logger.info(f"Adding entry to {path}")
    with open(path, "a") as f:
        f.write(entry)
    logger.info(f"{path} configured")
