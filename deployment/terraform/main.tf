# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

# ---------------------------------------------------------------------------
# Optional: create a dedicated Juju model.
# Set create_model = false and supply model_name of an existing model instead.
# ---------------------------------------------------------------------------
resource "juju_model" "mailserver" {
  count = var.create_model ? 1 : 0
  name  = var.model_name
}

locals {
  model_uuid = var.create_model ? juju_model.mailserver[0].uuid : var.model_uuid
}

# ---------------------------------------------------------------------------
# Mail stack - the product module wires everything together.
# ---------------------------------------------------------------------------
module "mailserver" {
  source = "../../terraform-product"

  model_uuid     = local.model_uuid
  domain         = var.domain
  transport_maps = var.transport_maps

  dovecot = {
    charm       = var.dovecot_charm
    app_name    = "dovecot"
    channel     = var.dovecot_channel
    constraints = "virt-type=virtual-machine arch=amd64"
  }

  postfix_relay = {
    charm    = var.postfix_relay_charm
    app_name = "postfix-relay"
    channel  = var.postfix_relay_channel
  }

  opendkim = {
    charm    = var.opendkim_charm
    app_name = "opendkim"
    channel  = var.opendkim_channel
  }

  postfix_relay_configurator = {
    charm    = var.postfix_relay_configurator_charm
    app_name = "postfix-relay-configurator"
    channel  = var.postfix_relay_configurator_channel
  }

  self_signed_certificates = {
    channel = "1/stable"
    base    = "ubuntu@22.04"
  }
}

# ---------------------------------------------------------------------------
# Outputs - handy for scripting post-deploy steps (e.g. setting DKIM keys).
# ---------------------------------------------------------------------------
output "app_names" {
  description = "Deployed Juju application names."
  value       = module.mailserver.app_names
}

output "model_uuid" {
  description = "UUID of the Juju model containing the mail stack."
  value       = local.model_uuid
}

output "model_name" {
  description = "Name of the Juju model containing the mail stack."
  value       = var.model_name
}
