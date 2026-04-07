# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Additional pytest options for tests."""

from pytest import Parser


def pytest_addoption(parser: Parser) -> None:
    """Parse additional pytest options.

    Args:
        parser: Pytest parser.
    """
    parser.addoption(
        "--keep-models",
        action="store_true",
        default=False,
        help="Keep test models after tests complete",
    )
    parser.addoption("--model", action="store", help="Juju model to use")
    parser.addoption("--charm-file", action="store", help="Charm file to be deployed")
