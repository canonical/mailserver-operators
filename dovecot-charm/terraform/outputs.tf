# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

output "app_name" {
  description = "Deprecated name of the deployed application; use application.name instead."
  value       = juju_application.dovecot.name
}

output "application" {
  description = "Full juju_application object for the deployed Dovecot application."
  value       = juju_application.dovecot
}

output "provides" {
  description = "Provided relations exposed by the module."
  value = {
    "cos-agent" = {
      kind     = "endpoint"
      name     = juju_application.dovecot.name
      endpoint = "cos-agent"
    }
  }
}

output "requires" {
  description = "Required relations exposed by the module."
  value = {
    certificates = {
      kind     = "endpoint"
      name     = juju_application.dovecot.name
      endpoint = "certificates"
    }
  }
}
