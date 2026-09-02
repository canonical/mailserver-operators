# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

output "application" {
  description = "Complete Juju application object for the deployed subordinate machine charm."
  value       = juju_application.postfix_relay_configurator
}

output "app_name" {
  description = "Deprecated: use output.application.name instead."
  value       = juju_application.postfix_relay_configurator.name
}

output "requires" {
  description = "Required relations exposed by the subordinate machine charm."
  value = {
    juju-info = {
      kind     = "endpoint"
      name     = juju_application.postfix_relay_configurator.name
      endpoint = "juju-info"
    }
  }
}
