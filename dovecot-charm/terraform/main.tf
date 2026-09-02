# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

resource "juju_application" "dovecot" {
  name       = var.app_name
  model_uuid = var.model_uuid

  charm {
    name     = "dovecot"
    channel  = var.channel
    revision = var.revision
    base     = var.base
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
  machines           = var.machines
  resources          = var.resources
  storage_directives = var.storage_directives
  units              = var.machines == null ? var.units : null
}
