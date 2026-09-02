# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

locals {
  model_uuid = var.create_model ? juju_model.postfix_relay[0].uuid : var.model_uuid

  opendkim = merge(var.opendkim, {
    channel = coalesce(var.opendkim.channel, "2/${var.risk}")
  })

  opendkim_config = merge(var.opendkim.config, {
    keytable = jsonencode([
      [
        "${var.dkim_selector}._domainkey.${var.mail_domain}",
        "${var.mail_domain}:${var.dkim_selector}:/etc/dkimkeys/${var.dkim_key_name}.private",
      ],
    ])
    private-keys = var.enable_opendkim ? "secret:${juju_secret.opendkim_private_key[0].secret_id}" : ""
    signingtable = jsonencode([
      ["*@${var.mail_domain}", "${var.dkim_selector}._domainkey.${var.mail_domain}"],
    ])
  })

  postfix_relay = merge(var.postfix_relay, {
    channel = coalesce(var.postfix_relay.channel, "latest/${var.risk}")
  })
}
