# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

output "dkim" {
  description = "Non-sensitive DKIM DNS publication coordinates."
  value = {
    enabled     = var.enable_opendkim
    domain      = var.mail_domain
    record_name = "${var.dkim_selector}._domainkey.${var.mail_domain}"
    selector    = var.dkim_selector
  }
}

output "integration_gaps" {
  description = "Known integrations that cannot be represented safely with current charm relations."
  value = {
    mailbox_backend = {
      automated = false
      reason    = "Postfix Relay and Dovecot have no first-class mailbox-backend relation."
    }
    postfix_relay_cos = {
      automated = var.postfix_relay.enable_cos_integration
      reason    = "Enable only after pinning a Postfix Relay revision that exposes cos-agent."
    }
  }
}

output "metadata" {
  description = "Metadata describing this CC008 product module."
  value = {
    product   = "postfix-relay"
    substrate = "machine"
    version   = "0.1.0"
  }
}

output "models" {
  description = "Models and components deployed by this product module."
  value = {
    postfix_relay = {
      components = {
        opendkim      = var.enable_opendkim ? module.opendkim[0].application : null
        postfix_relay = module.postfix_relay.application
      }
      model_uuid = local.model_uuid
    }
  }
}

output "provides" {
  description = "Aggregated endpoints provided by the product components."
  value = {
    opendkim_cos_agent      = var.enable_opendkim ? module.opendkim[0].provides["cos-agent"] : null
    postfix_relay_cos_agent = var.postfix_relay.enable_cos_integration ? module.postfix_relay.provides["cos-agent"] : null
    postfix_relay_metrics   = module.postfix_relay.provides.metrics
  }
}

output "requires" {
  description = "Aggregated endpoints required by the product components."
  value = {
    postfix_relay_milter = module.postfix_relay.requires_endpoints.milter
  }
}
