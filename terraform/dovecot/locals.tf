# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

locals {
  model_uuid = var.create_model ? juju_model.dovecot[0].uuid : var.model_uuid

  dovecot = merge(var.dovecot, {
    channel = coalesce(var.dovecot.channel, "2.3/${var.risk}")
  })

  dovecot_config = merge(var.dovecot.config, {
    luks-auto-provisioning = "true"
    luks-key               = "secret:${juju_secret.dovecot_luks.secret_id}"
    mailname               = var.mail_domain
    postmaster-address     = var.postmaster_address
    primary-unit           = coalesce(var.primary_unit, "${var.dovecot.app_name}/0")
  })

  self_signed_certificates = var.self_signed_certificates
}
