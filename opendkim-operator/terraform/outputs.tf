# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

output "app_name" {
  description = "Name of the deployed application."
  value       = juju_application.opendkim.name
}

output "provides" {
  description = "Endpoints that opendkim provides (for wiring integrations)."
  value = {
    milter = "milter"
  }
}
