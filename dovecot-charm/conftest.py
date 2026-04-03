# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register custom options for all pytest runs."""
    parser.addoption("--charm-file", action="store")
    parser.addoption("--use-existing", action="store_true", default=False)
    parser.addoption("--model", action="store", default=None)
    parser.addoption("--keep-models", action="store_true", default=False)
