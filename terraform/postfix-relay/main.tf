# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

resource "juju_model" "postfix_relay" {
  count       = var.create_model ? 1 : 0
  name        = var.model_name
  constraints = var.model_constraints

  cloud {
    name   = var.model_cloud == null ? "" : var.model_cloud.name
    region = var.model_cloud == null ? null : var.model_cloud.region
  }

  config = {
    juju-http-proxy  = var.proxy.http
    juju-https-proxy = var.proxy.https
    juju-no-proxy    = var.proxy.no_proxy
    logging-config   = var.logging_config
  }
}

resource "juju_secret" "opendkim_private_key" {
  count      = var.enable_opendkim ? 1 : 0
  info       = "Private DKIM signing key managed by the Postfix Relay product."
  model_uuid = local.model_uuid
  name       = "${local.opendkim.app_name}-private-key"
  value = {
    (var.dkim_key_name) = var.dkim_private_key
  }
}

module "opendkim" {
  count  = var.enable_opendkim ? 1 : 0
  source = "../../opendkim-operator/terraform"

  app_name          = local.opendkim.app_name
  base              = local.opendkim.base
  channel           = local.opendkim.channel
  config            = local.opendkim_config
  constraints       = local.opendkim.constraints
  endpoint_bindings = local.opendkim.endpoint_bindings
  machines          = local.opendkim.machines
  model_uuid        = local.model_uuid
  resources         = local.opendkim.resources
  revision          = local.opendkim.revision
  units             = local.opendkim.units
}

module "postfix_relay" {
  source = "../../postfix-relay-operator/terraform"

  app_name           = local.postfix_relay.app_name
  base               = local.postfix_relay.base
  channel            = local.postfix_relay.channel
  config             = local.postfix_relay.config
  constraints        = local.postfix_relay.constraints
  endpoint_bindings  = local.postfix_relay.endpoint_bindings
  expose             = local.postfix_relay.expose
  machines           = local.postfix_relay.machines
  model_uuid         = local.model_uuid
  resources          = local.postfix_relay.resources
  revision           = local.postfix_relay.revision
  storage_directives = local.postfix_relay.storage_directives
  units              = local.postfix_relay.units
}

resource "juju_access_secret" "opendkim_private_key" {
  count        = var.enable_opendkim ? 1 : 0
  applications = [module.opendkim[0].application.name]
  model_uuid   = local.model_uuid
  secret_id    = juju_secret.opendkim_private_key[0].secret_id
}

resource "juju_integration" "postfix_relay_opendkim" {
  count      = var.enable_opendkim ? 1 : 0
  model_uuid = local.model_uuid

  application {
    endpoint = module.postfix_relay.requires_endpoints.milter.endpoint
    name     = module.postfix_relay.requires_endpoints.milter.name
  }

  application {
    endpoint = module.opendkim[0].provides.milter.endpoint
    name     = module.opendkim[0].provides.milter.name
  }
}

resource "juju_integration" "cos_opendkim" {
  count      = var.enable_opendkim && var.cos != null ? 1 : 0
  model_uuid = local.model_uuid

  application {
    endpoint = module.opendkim[0].provides["cos-agent"].endpoint
    name     = module.opendkim[0].provides["cos-agent"].name
  }

  application {
    endpoint            = var.cos.kind == "endpoint" ? var.cos.endpoint : null
    name                = var.cos.kind == "endpoint" ? var.cos.name : null
    offer_url           = var.cos.kind == "offer" ? var.cos.url : null
    offering_controller = var.cos.kind == "offer" ? var.cos.controller : null
  }
}

moved {
  from = juju_secret.opendkim_private_key
  to   = juju_secret.opendkim_private_key[0]
}

moved {
  from = module.opendkim
  to   = module.opendkim[0]
}

moved {
  from = juju_access_secret.opendkim_private_key
  to   = juju_access_secret.opendkim_private_key[0]
}

moved {
  from = juju_integration.postfix_relay_opendkim
  to   = juju_integration.postfix_relay_opendkim[0]
}

resource "juju_integration" "cos_postfix_relay" {
  count      = var.cos == null || !var.postfix_relay.enable_cos_integration ? 0 : 1
  model_uuid = local.model_uuid

  application {
    endpoint = module.postfix_relay.provides["cos-agent"].endpoint
    name     = module.postfix_relay.provides["cos-agent"].name
  }

  application {
    endpoint            = var.cos.kind == "endpoint" ? var.cos.endpoint : null
    name                = var.cos.kind == "endpoint" ? var.cos.name : null
    offer_url           = var.cos.kind == "offer" ? var.cos.url : null
    offering_controller = var.cos.kind == "offer" ? var.cos.controller : null
  }
}
