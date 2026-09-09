# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

output "metadata" {
  description = "Metadata describing this CC008 product module."
  value = {
    product   = "dovecot"
    substrate = "machine"
    version   = "0.1.0"
  }
}

output "models" {
  description = "Models and components deployed by this product module."
  value = {
    dovecot = {
      components = {
        dovecot                  = module.dovecot.application
        self_signed_certificates = var.tls == null ? juju_application.self_signed_certificates[0] : null
      }
      model_uuid = local.model_uuid
    }
  }
}

output "provides" {
  description = "Aggregated endpoints provided by the product components."
  value = {
    dovecot_cos_agent = module.dovecot.provides["cos-agent"]
  }
}

output "requires" {
  description = "Aggregated endpoints required by the product components."
  value = {
    dovecot_certificates = module.dovecot.requires.certificates
  }
}
