# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

resource "juju_application" "postfix_relay_configurator" {
  name       = var.app_name
  model_uuid = var.model_uuid

  charm {
    name     = "postfix-relay-configurator"
    base     = var.base
    channel  = var.channel
    revision = var.revision
  }

  config             = var.config
  constraints        = var.constraints
  endpoint_bindings  = var.endpoint_bindings
  resources          = var.resources
  storage_directives = var.storage
  units              = 0
}
