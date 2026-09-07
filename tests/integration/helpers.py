# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Shared helpers for integration tests."""

import base64
import hashlib
import logging

import jubilant

logger = logging.getLogger(__name__)

POSTFIX_RELAY_APP = "postfix-relay"
CONFIGURATOR_APP = "postfix-relay-configurator"
SELF_SIGNED_APP = "self-signed-certificates"

TEST_DOMAIN = "mailstack.internal"
SMTP_PORT = 587


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
