# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

module "postfix_relay" {
  source      = "../terraform"
  app_name    = var.postfix_relay.app_name
  channel     = var.postfix_relay.channel
  config      = var.postfix_relay.config
  model_uuid  = var.model_uuid
  constraints = var.postfix_relay.constraints
  revision    = var.postfix_relay.revision
  base        = var.postfix_relay.base
  units       = var.postfix_relay.units
}

module "opendkim" {
  source      = "git::https://github.com/canonical/opendkim-operator//terraform?depth=1&ref=rev7"
  app_name    = var.opendkim.app_name
  channel     = var.opendkim.channel
  config      = var.opendkim.config
  constraints = var.opendkim.constraints
  model_uuid  = var.model_uuid
  revision    = var.opendkim.revision
  base        = var.opendkim.base
  storage     = var.opendkim.storage
  units       = var.opendkim.units
}

resource "juju_integration" "postfix_relay_opendkim" {
  model_uuid = var.model_uuid

  application {
    name     = module.postfix_relay.app_name
    endpoint = module.postfix_relay.requires.milter
  }

  application {
    name     = module.opendkim.app_name
    endpoint = module.opendkim.provides.milter
  }
}
