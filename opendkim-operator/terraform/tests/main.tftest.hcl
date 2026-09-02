# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

variables {
  app_name          = "opendkim"
  base              = "ubuntu@24.04"
  channel           = "2/edge"
  config            = {}
  constraints       = "arch=amd64"
  endpoint_bindings = [{ space = "mail" }]
  machines          = null
  model_uuid        = "00000000-0000-0000-0000-000000000001"
  resources         = {}
  revision          = 10
  units             = 1
}

mock_provider "juju" {
  mock_resource "juju_application" {
    defaults = {
      id           = "opendkim"
      model_type   = "machine"
      unit_numbers = ["0"]
    }
  }
}

run "deploys_with_units" {
  command = plan

  assert {
    condition     = output.application.name == "opendkim" && output.application.model_uuid == "00000000-0000-0000-0000-000000000001" && output.application.charm[0].base == "ubuntu@24.04" && output.application.charm[0].channel == "2/edge" && output.application.charm[0].name == "opendkim" && output.application.charm[0].revision == 10
    error_message = "application identity did not match the expected machine deployment"
  }

  assert {
    condition     = output.application.config == null || length(output.application.config) == 0
    error_message = "application config did not match expected"
  }

  assert {
    condition     = output.application.constraints == "arch=amd64"
    error_message = "application constraints did not match expected"
  }

  assert {
    condition     = output.application.units == 1
    error_message = "application units did not match expected"
  }

  assert {
    condition     = length(output.application.endpoint_bindings) == 1
    error_message = "endpoint binding output did not match expected"
  }

  assert {
    condition     = output.app_name == output.application.name
    error_message = "deprecated app_name output did not match expected"
  }

  assert {
    condition = output.provides == {
      "cos-agent" = {
        kind     = "endpoint"
        name     = "opendkim"
        endpoint = "cos-agent"
      }
      milter = {
        kind     = "endpoint"
        name     = "opendkim"
        endpoint = "milter"
      }
    }
    error_message = "relation outputs did not match expected structure"
  }
}

run "deploys_to_specific_machines" {
  command = plan

  variables {
    machines = ["0", "1"]
    units    = null
  }

  assert {
    condition     = length(output.application.machines) == 2 && contains(output.application.machines, "0") && contains(output.application.machines, "1") && output.application.units == null
    error_message = "machine placement output did not match expected"
  }
}
