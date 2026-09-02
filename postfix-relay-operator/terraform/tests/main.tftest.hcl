# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

mock_provider "juju" {}

run "principal_machine_deploy" {
  variables {
    app_name           = "postfix-relay"
    base               = "ubuntu@24.04"
    channel            = "latest/edge"
    config             = {}
    constraints        = "arch=amd64"
    endpoint_bindings  = []
    machines           = []
    model_uuid         = "00000000-0000-0000-0000-000000000000"
    resources          = {}
    revision           = 13
    storage_directives = {}
    units              = 1
  }

  assert {
    condition     = output.application.name == "postfix-relay"
    error_message = "application name did not match expected"
  }

  assert {
    condition     = output.application.model_uuid == "00000000-0000-0000-0000-000000000000"
    error_message = "application model_uuid did not match expected"
  }

  assert {
    condition     = output.application.charm[0].base == "ubuntu@24.04" && output.application.charm[0].channel == "latest/edge" && output.application.charm[0].name == "postfix-relay" && output.application.charm[0].revision == 13
    error_message = "application charm block did not match expected"
  }

  assert {
    condition     = length(keys(output.application.config)) == 0
    error_message = "application config did not match expected"
  }

  assert {
    condition     = output.application.constraints == "arch=amd64"
    error_message = "application constraints did not match expected"
  }

  assert {
    condition     = length(output.application.endpoint_bindings) == 0 && length(output.application.machines) == 0
    error_message = "application machine bindings did not match expected"
  }

  assert {
    condition     = length(keys(output.application.resources)) == 0 && length(keys(output.application.storage_directives)) == 0 && output.application.units == 1
    error_message = "application resources, storage directives, or units did not match expected"
  }

  assert {
    condition     = output.app_name == output.application.name
    error_message = "deprecated app_name output did not match expected"
  }

  assert {
    condition = output.provides == {
      metrics = {
        kind     = "endpoint"
        name     = output.application.name
        endpoint = "metrics"
      }
      "cos-agent" = {
        kind     = "endpoint"
        name     = output.application.name
        endpoint = "cos-agent"
      }
    }
    error_message = "provides output did not match expected structure"
  }

  assert {
    condition = output.requires_endpoints == {
      milter = {
        kind     = "endpoint"
        name     = output.application.name
        endpoint = "milter"
      }
      certificates = {
        kind     = "endpoint"
        name     = output.application.name
        endpoint = "certificates"
      }
    }
    error_message = "requires_endpoints output did not match expected structure"
  }

  assert {
    condition     = output.requires.milter == "milter"
    error_message = "legacy requires output must remain backward compatible"
  }
}
