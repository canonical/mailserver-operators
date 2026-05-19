# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

# ---------------------------------------------------------------------------
# Local charm-path detection
# A path is "local" when it ends in .charm, starts with ./ or /, or contains
# a directory separator — i.e. it is not a plain Charmhub charm name.
# For local charms the Juju provider must receive channel = null,
# revision = null and base = null.
# ---------------------------------------------------------------------------
locals {
  _local_re = "(\\.charm$)|(^\\.)|(^/)|(/)"

  dovecot_local      = length(regexall(local._local_re, var.dovecot.charm)) > 0
  postfix_local      = length(regexall(local._local_re, var.postfix_relay.charm)) > 0
  opendkim_local     = length(regexall(local._local_re, var.opendkim.charm)) > 0
  configurator_local = length(regexall(local._local_re, var.postfix_relay_configurator.charm)) > 0
  self_signed_local  = length(regexall(local._local_re, var.self_signed_certificates.charm)) > 0

  # Default dovecot config — merged with any caller overrides.
  dovecot_base_config = {
    mailname             = var.domain
    "postmaster-address" = "postmaster@${var.domain}"
    "primary-unit"       = "${var.dovecot.app_name}/0"
    "manage-luks"        = "false"
  }

  # Default postfix-relay config — merged with caller overrides.
  postfix_base_config = {
    relay_domains                       = yamlencode([var.domain])
    enable_smtp_auth                    = "true"
    enable_reject_unknown_sender_domain = "false"
  }

  # Default configurator transport_maps config (if provided).
  configurator_base_config = length(var.transport_maps) > 0 ? {
    transport_maps = yamlencode(var.transport_maps)
  } : {}
}

# ---------------------------------------------------------------------------
# self-signed-certificates  (TLS provider for postfix-relay and dovecot)
# Deployed inline — there is no separate charm module for this charm.
# ---------------------------------------------------------------------------
resource "juju_application" "self_signed_certificates" {
  name       = var.self_signed_certificates.app_name
  model_uuid = var.model_uuid

  charm {
    name     = var.self_signed_certificates.charm
    channel  = local.self_signed_local ? null : var.self_signed_certificates.channel
    revision = local.self_signed_local ? null : var.self_signed_certificates.revision
    base     = local.self_signed_local ? null : var.self_signed_certificates.base
  }

  config      = var.self_signed_certificates.config
  constraints = trimspace(coalesce(var.self_signed_certificates.constraints, " ")) == "" ? null : var.self_signed_certificates.constraints
  units       = var.self_signed_certificates.units
}

# ---------------------------------------------------------------------------
# dovecot  (IMAP server + LMTP delivery target)
# ---------------------------------------------------------------------------
module "dovecot" {
  source = "../dovecot-charm/terraform"

  model_uuid  = var.model_uuid
  app_name    = var.dovecot.app_name
  charm_name  = var.dovecot.charm
  channel     = local.dovecot_local ? null : var.dovecot.channel
  revision    = local.dovecot_local ? null : var.dovecot.revision
  base        = local.dovecot_local ? null : var.dovecot.base
  config      = merge(local.dovecot_base_config, var.dovecot.config)
  constraints = var.dovecot.constraints
  trust       = true
  units       = var.dovecot.units
  storage     = var.dovecot.storage
}

# ---------------------------------------------------------------------------
# postfix-relay  (SMTP submission + relay)
# ---------------------------------------------------------------------------
module "postfix_relay" {
  source = "../postfix-relay-operator/terraform"

  model_uuid  = var.model_uuid
  app_name    = var.postfix_relay.app_name
  charm_name  = var.postfix_relay.charm
  channel     = local.postfix_local ? null : var.postfix_relay.channel
  revision    = local.postfix_local ? null : var.postfix_relay.revision
  base        = local.postfix_local ? null : var.postfix_relay.base
  config      = merge(local.postfix_base_config, var.postfix_relay.config)
  constraints = var.postfix_relay.constraints
  units       = var.postfix_relay.units
  storage     = var.postfix_relay.storage
}

# ---------------------------------------------------------------------------
# opendkim  (DKIM signing milter)
# ---------------------------------------------------------------------------
module "opendkim" {
  source = "../opendkim-operator/terraform"

  model_uuid  = var.model_uuid
  app_name    = var.opendkim.app_name
  charm_name  = var.opendkim.charm
  channel     = local.opendkim_local ? null : var.opendkim.channel
  revision    = local.opendkim_local ? null : var.opendkim.revision
  base        = local.opendkim_local ? null : var.opendkim.base
  config      = var.opendkim.config
  constraints = var.opendkim.constraints
  units       = var.opendkim.units
  storage     = var.opendkim.storage
}

# ---------------------------------------------------------------------------
# postfix-relay-configurator  (subordinate — LMTP transport + relay rules)
# ---------------------------------------------------------------------------
module "postfix_relay_configurator" {
  source = "../postfix-relay-configurator-operator/terraform"

  model_uuid  = var.model_uuid
  app_name    = var.postfix_relay_configurator.app_name
  charm_name  = var.postfix_relay_configurator.charm
  channel     = local.configurator_local ? null : var.postfix_relay_configurator.channel
  revision    = local.configurator_local ? null : var.postfix_relay_configurator.revision
  base        = local.configurator_local ? null : var.postfix_relay_configurator.base
  config      = merge(local.configurator_base_config, var.postfix_relay_configurator.config)
  constraints = var.postfix_relay_configurator.constraints
  storage     = var.postfix_relay_configurator.storage
}

# ---------------------------------------------------------------------------
# Integrations
# ---------------------------------------------------------------------------

# dovecot ↔ self-signed-certificates  (TLS)
resource "juju_integration" "dovecot_certificates" {
  model_uuid = var.model_uuid

  application {
    name     = module.dovecot.app_name
    endpoint = module.dovecot.requires.certificates
  }

  application {
    name     = juju_application.self_signed_certificates.name
    endpoint = "certificates"
  }
}

# postfix-relay ↔ self-signed-certificates  (TLS)
resource "juju_integration" "postfix_relay_certificates" {
  model_uuid = var.model_uuid

  application {
    name     = module.postfix_relay.app_name
    endpoint = module.postfix_relay.requires.certificates
  }

  application {
    name     = juju_application.self_signed_certificates.name
    endpoint = "certificates"
  }
}

# postfix-relay ↔ opendkim  (DKIM milter)
resource "juju_integration" "postfix_relay_milter" {
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

# postfix-relay ↔ postfix-relay-configurator  (subordinate attachment)
resource "juju_integration" "postfix_relay_configurator" {
  model_uuid = var.model_uuid

  application {
    name     = module.postfix_relay.app_name
    endpoint = module.postfix_relay.provides.juju_info
  }

  application {
    name     = module.postfix_relay_configurator.app_name
    endpoint = module.postfix_relay_configurator.requires.juju_info
  }
}
