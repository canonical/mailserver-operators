# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

resource "juju_application" "opendkim" {
  name       = var.app_name
  model_uuid = var.model_uuid

  charm {
    name     = "opendkim"
    channel  = var.channel
    revision = var.revision
    base     = var.base
  }

  config            = var.config
  constraints       = var.constraints
  endpoint_bindings = var.endpoint_bindings
  machines          = var.machines
  resources         = var.resources
  units             = var.machines == null ? var.units : null
}

