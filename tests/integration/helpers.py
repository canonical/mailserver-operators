# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Shared helpers for integration tests."""

import base64
import hashlib
import logging
import pathlib

import jubilant
import pytest

logger = logging.getLogger(__name__)

def sha512_dovecot_password(password: str) -> str:
    """Generate a SSHA512 password hash compatible with dovecot."""
    salt = b"mailtest"
    digest = hashlib.sha512(password.encode() + salt).digest()
    return "{SSHA512}" + base64.b64encode(digest + salt).decode()


def integrate_once(juju: jubilant.Juju, endpoint_a: str, endpoint_b: str) -> None:
    """Call ``juju integrate`` tolerating 'already related' errors."""
    try:
        juju.integrate(endpoint_a, endpoint_b)
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "already exists" not in msg and "already related" not in msg:
            raise
        logger.debug("Relation %s ↔ %s already exists, skipping", endpoint_a, endpoint_b)


def select_charm_file(pytestconfig: pytest.Config, marker: str) -> str:
    """Select charm file matching marker from --charm-file options."""
    charm_files: list[str] = pytestconfig.getoption("--charm-file", default=[])
    for path in charm_files:
        if marker in pathlib.Path(path).name.lower():
            return path
    use_existing = pytestconfig.getoption("--use-existing", default=False)
    if use_existing:
        return ""
    provided = ", ".join(charm_files) if charm_files else "<none>"
    raise AssertionError(f"Missing --charm-file matching '{marker}'. Provided: {provided}.")

