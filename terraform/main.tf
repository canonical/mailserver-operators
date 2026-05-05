# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

locals {
  self_signed_is_local_charm = length(regexall("(^local:)|(^/)|(^\\./)|(.+\\.charm$)|(-[0-9]+$)", lower(var.self_signed_certificates.charm))) > 0
  dovecot_is_local_charm     = length(regexall("(^local:)|(^/)|(^\\./)|(.+\\.charm$)|(-[0-9]+$)", lower(var.dovecot.charm))) > 0
  postfix_is_local_charm     = length(regexall("(^local:)|(^/)|(^\\./)|(.+\\.charm$)|(-[0-9]+$)", lower(var.postfix_relay.charm))) > 0
  opendkim_is_local_charm    = length(regexall("(^local:)|(^/)|(^\\./)|(.+\\.charm$)|(-[0-9]+$)", lower(var.opendkim.charm))) > 0
  configurator_is_local_charm = length(regexall(
    "(^local:)|(^/)|(^\\./)|(.+\\.charm$)|(-[0-9]+$)",
    lower(var.postfix_relay_configurator.charm),
  )) > 0

  dovecot_default_config = {
    mailname               = var.test_domain
    postmaster-address     = "postmaster@${var.test_domain}"
    primary-unit           = "${var.dovecot.app_name}/0"
    luks-auto-provisioning = "false"
  }

  postfix_relay_default_config = {
    relay_domains                       = yamlencode([var.test_domain])
    enable_smtp_auth                    = "true"
    enable_reject_unknown_sender_domain = "false"
  }

  configurator_default_config = length(var.transport_maps) > 0 ? {
    transport_maps = yamlencode(var.transport_maps)
  } : {}
}

resource "juju_application" "self_signed_certificates" {
  name       = var.self_signed_certificates.app_name
  model_uuid = var.model_uuid

  charm {
    name     = var.self_signed_certificates.charm
    channel  = local.self_signed_is_local_charm ? null : var.self_signed_certificates.channel
    revision = local.self_signed_is_local_charm ? null : var.self_signed_certificates.revision
    base     = local.self_signed_is_local_charm ? null : var.self_signed_certificates.base
  }

  config      = var.self_signed_certificates.config
  constraints = trimspace(var.self_signed_certificates.constraints) == "" ? null : var.self_signed_certificates.constraints
  units       = var.self_signed_certificates.units
}

resource "juju_application" "dovecot" {
  name       = var.dovecot.app_name
  model_uuid = var.model_uuid

  charm {
    name     = var.dovecot.charm
    channel  = local.dovecot_is_local_charm ? null : var.dovecot.channel
    revision = local.dovecot_is_local_charm ? null : var.dovecot.revision
    base     = local.dovecot_is_local_charm ? null : var.dovecot.base
  }

  config             = merge(local.dovecot_default_config, var.dovecot.config)
  constraints        = trimspace(var.dovecot.constraints) == "" ? null : var.dovecot.constraints
  units              = var.dovecot.units
  storage_directives = var.dovecot.storage
}

resource "juju_application" "postfix_relay" {
  name       = var.postfix_relay.app_name
  model_uuid = var.model_uuid

  charm {
    name     = var.postfix_relay.charm
    channel  = local.postfix_is_local_charm ? null : var.postfix_relay.channel
    revision = local.postfix_is_local_charm ? null : var.postfix_relay.revision
    base     = local.postfix_is_local_charm ? null : var.postfix_relay.base
  }

  config             = merge(local.postfix_relay_default_config, var.postfix_relay.config)
  constraints        = trimspace(var.postfix_relay.constraints) == "" ? null : var.postfix_relay.constraints
  units              = var.postfix_relay.units
  storage_directives = var.postfix_relay.storage
}

resource "juju_application" "opendkim" {
  name       = var.opendkim.app_name
  model_uuid = var.model_uuid

  charm {
    name     = var.opendkim.charm
    channel  = local.opendkim_is_local_charm ? null : var.opendkim.channel
    revision = local.opendkim_is_local_charm ? null : var.opendkim.revision
    base     = local.opendkim_is_local_charm ? null : var.opendkim.base
  }

  config             = var.opendkim.config
  constraints        = trimspace(var.opendkim.constraints) == "" ? null : var.opendkim.constraints
  units              = var.opendkim.units
  storage_directives = var.opendkim.storage
}

resource "juju_application" "postfix_relay_configurator" {
  name       = var.postfix_relay_configurator.app_name
  model_uuid = var.model_uuid

  charm {
    name     = var.postfix_relay_configurator.charm
    channel  = local.configurator_is_local_charm ? null : var.postfix_relay_configurator.channel
    revision = local.configurator_is_local_charm ? null : var.postfix_relay_configurator.revision
    base     = local.configurator_is_local_charm ? null : var.postfix_relay_configurator.base
  }

  config             = merge(local.configurator_default_config, var.postfix_relay_configurator.config)
  constraints        = trimspace(var.postfix_relay_configurator.constraints) == "" ? null : var.postfix_relay_configurator.constraints
  units              = var.postfix_relay_configurator.units
  storage_directives = var.postfix_relay_configurator.storage
}

resource "juju_integration" "dovecot_certificates" {
  model_uuid = var.model_uuid

  application {
    name     = juju_application.dovecot.name
    endpoint = "certificates"
  }

  application {
    name     = juju_application.self_signed_certificates.name
    endpoint = "certificates"
  }
}

resource "juju_integration" "postfix_relay_certificates" {
  model_uuid = var.model_uuid

  application {
    name     = juju_application.postfix_relay.name
    endpoint = "certificates"
  }

  application {
    name     = juju_application.self_signed_certificates.name
    endpoint = "certificates"
  }
}

resource "juju_integration" "postfix_relay_milter" {
  model_uuid = var.model_uuid

  application {
    name     = juju_application.postfix_relay.name
    endpoint = "milter"
  }

  application {
    name     = juju_application.opendkim.name
    endpoint = "milter"
  }
}

resource "juju_integration" "postfix_relay_configurator" {
  model_uuid = var.model_uuid

  application {
    name     = juju_application.postfix_relay.name
    endpoint = "juju-info"
  }

  application {
    name     = juju_application.postfix_relay_configurator.name
    endpoint = "juju-info"
  }
}
