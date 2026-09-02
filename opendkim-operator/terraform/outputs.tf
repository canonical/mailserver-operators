# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

output "app_name" {
  description = "Deprecated name of the deployed application."
  value       = juju_application.opendkim.name
}

output "application" {
  description = "Full juju_application object for the deployed OpenDKIM application."
  value       = juju_application.opendkim
}

output "provides" {
  description = "Provided relations exposed by the module."
  value = {
    "cos-agent" = {
      kind     = "endpoint"
      name     = juju_application.opendkim.name
      endpoint = "cos-agent"
    }
    milter = {
      kind     = "endpoint"
      name     = juju_application.opendkim.name
      endpoint = "milter"
    }
  }
}
