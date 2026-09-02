# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

output "application" {
  description = "The deployed Juju application."
  value       = juju_application.postfix_relay
}

output "app_name" {
  description = "Deprecated: use application.name."
  value       = juju_application.postfix_relay.name
}

output "provides" {
  value = {
    metrics = {
      kind     = "endpoint"
      name     = juju_application.postfix_relay.name
      endpoint = "metrics"
    }
    "cos-agent" = {
      kind     = "endpoint"
      name     = juju_application.postfix_relay.name
      endpoint = "cos-agent"
    }
  }
}

output "requires" {
  description = "Legacy required endpoint names."
  value = {
    milter = "milter"
  }
}

output "requires_endpoints" {
  description = "Structured required endpoint references."
  value = {
    milter = {
      kind     = "endpoint"
      name     = juju_application.postfix_relay.name
      endpoint = "milter"
    }
    certificates = {
      kind     = "endpoint"
      name     = juju_application.postfix_relay.name
      endpoint = "certificates"
    }
  }
}
