# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

resource "juju_application" "dovecot" {
  name       = var.app_name
  model_uuid = var.model_uuid

  charm {
    name     = var.charm_name
    channel  = var.channel
    revision = var.revision
    base     = var.base
  }

  config             = var.config
  constraints        = var.constraints
  trust              = var.trust
  units              = var.units
  storage_directives = var.storage
}
