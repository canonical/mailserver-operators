# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

output "app_name" {
  description = "Name of the deployed application."
  value       = juju_application.dovecot.name
}

output "requires" {
  description = "Endpoints that dovecot requires (for wiring integrations)."
  value = {
    certificates = "certificates"
  }
}
