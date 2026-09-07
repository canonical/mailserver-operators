# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

resource "juju_application" "postfix_relay" {
  name       = var.app_name
  model_uuid = var.model_uuid

  charm {
    base     = var.base
    channel  = var.channel
    name     = "postfix-relay"
    revision = var.revision
  }

  dynamic "expose" {
    for_each = var.expose == null ? [] : [var.expose]

    content {
      cidrs     = expose.value.cidrs
      endpoints = expose.value.endpoints
      spaces    = expose.value.spaces
    }
  }

  config             = var.config
  constraints        = var.constraints
  endpoint_bindings  = var.endpoint_bindings
  machines           = length(var.machines) == 0 ? null : var.machines
  resources          = var.resources
  storage_directives = merge(var.storage, var.storage_directives)
  units              = var.machines == null || length(var.machines) == 0 ? var.units : null
}
