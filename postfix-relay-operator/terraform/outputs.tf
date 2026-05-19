# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

output "app_name" {
  description = "Name of the deployed application."
  value       = juju_application.postfix_relay.name
}

output "requires" {
  description = "Endpoints that postfix-relay requires (for wiring integrations)."
  value = {
    certificates = "certificates"
    milter       = "milter"
  }
}

output "provides" {
  description = "Endpoints that postfix-relay provides (for wiring integrations)."
  value = {
    juju_info = "juju-info"
  }
}
