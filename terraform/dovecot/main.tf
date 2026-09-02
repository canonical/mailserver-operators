# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

resource "juju_model" "dovecot" {
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

resource "juju_secret" "dovecot_luks" {
  info       = "LUKS passphrase for Dovecot mail storage."
  model_uuid = local.model_uuid
  name       = coalesce(var.luks_secret_name, "${local.dovecot.app_name}-luks-key")
  value = {
    key = var.luks_key
  }
}

module "dovecot" {
  source = "../../dovecot-charm/terraform"

  app_name           = local.dovecot.app_name
  base               = local.dovecot.base
  channel            = local.dovecot.channel
  config             = local.dovecot_config
  constraints        = local.dovecot.constraints
  endpoint_bindings  = local.dovecot.endpoint_bindings
  expose             = local.dovecot.expose
  machines           = local.dovecot.machines
  model_uuid         = local.model_uuid
  resources          = local.dovecot.resources
  revision           = local.dovecot.revision
  storage_directives = local.dovecot.storage_directives
  units              = local.dovecot.units
}

resource "juju_access_secret" "dovecot_luks" {
  applications = [module.dovecot.application.name]
  model_uuid   = local.model_uuid
  secret_id    = juju_secret.dovecot_luks.secret_id
}

resource "juju_application" "self_signed_certificates" {
  count      = var.tls == null ? 1 : 0
  model_uuid = local.model_uuid
  name       = local.self_signed_certificates.app_name

  charm {
    base     = local.self_signed_certificates.base
    channel  = local.self_signed_certificates.channel
    name     = "self-signed-certificates"
    revision = local.self_signed_certificates.revision
  }

  config      = local.self_signed_certificates.config
  constraints = local.self_signed_certificates.constraints
  units       = local.self_signed_certificates.units
}

resource "juju_integration" "tls_dovecot" {
  model_uuid = local.model_uuid

  application {
    endpoint            = var.tls == null ? "certificates" : var.tls.kind == "endpoint" ? var.tls.endpoint : null
    name                = var.tls == null ? juju_application.self_signed_certificates[0].name : var.tls.kind == "endpoint" ? var.tls.name : null
    offer_url           = var.tls != null && var.tls.kind == "offer" ? var.tls.url : null
    offering_controller = var.tls != null && var.tls.kind == "offer" ? var.tls.controller : null
  }

  application {
    endpoint = module.dovecot.requires.certificates.endpoint
    name     = module.dovecot.requires.certificates.name
  }
}

resource "juju_integration" "cos_dovecot" {
  count      = var.cos == null ? 0 : 1
  model_uuid = local.model_uuid

  application {
    endpoint = module.dovecot.provides["cos-agent"].endpoint
    name     = module.dovecot.provides["cos-agent"].name
  }

  application {
    endpoint            = var.cos.kind == "endpoint" ? var.cos.endpoint : null
    name                = var.cos.kind == "endpoint" ? var.cos.name : null
    offer_url           = var.cos.kind == "offer" ? var.cos.url : null
    offering_controller = var.cos.kind == "offer" ? var.cos.controller : null
  }
}
