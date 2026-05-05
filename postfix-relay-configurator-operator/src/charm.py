#!/usr/bin/env python3

# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Postfix relay Configurator charm."""

import logging
from typing import Any

import ops

import utils
from postfix import PostfixMap, build_postfix_maps
from state import ConfigurationError, State

logger = logging.getLogger(__name__)


class PostfixRelayConfiguratorCharm(ops.CharmBase):
    """Postfix relay Configurator."""

    def __init__(self, *args: Any) -> None:
        """Postfix relay Configurator."""
        super().__init__(*args)

        self.framework.observe(self.on.config_changed, self._reconcile)

    def _reconcile(self, _: ops.EventBase) -> None:
        self.unit.status = ops.MaintenanceStatus("Reconciling config")
        try:
            charm_state = State.from_charm(self.config)
        except ConfigurationError:
            logger.exception("Error validating the charm configuration.")
            self.unit.status = ops.BlockedStatus("Invalid config")
            return

        self._configure_relay(charm_state)
        self.unit.status = ops.ActiveStatus()

    def _configure_relay(self, charm_state: State) -> None:
        """Generate and apply Postfix configuration."""
        postfix_maps = build_postfix_maps(charm_state)
        self._apply_postfix_maps(list(postfix_maps.values()))

    @staticmethod
    def _apply_postfix_maps(postfix_maps: list[PostfixMap]) -> None:
        logger.info("Applying postfix maps")
        for postfix_map in postfix_maps:
            utils.write_file(postfix_map.content, postfix_map.path)


if __name__ == "__main__":  # pragma: nocover
    ops.main(PostfixRelayConfiguratorCharm)
