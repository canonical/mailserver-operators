# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

mock_provider "juju" {
  mock_resource "juju_application" {
    defaults = {
      name = "postfix-relay-configurator"
    }
  }
}

run "basic_deploy" {
  variables {
    app_name          = "postfix-relay-configurator"
    base              = "ubuntu@24.04"
    channel           = "latest/edge"
    config            = {}
    endpoint_bindings = []
    model_uuid        = "00000000-0000-0000-0000-000000000000"
    resources         = {}
    # renovate: depName="postfix-relay-configurator"
    revision = 12
  }

  assert {
    condition     = output.application == juju_application.postfix_relay_configurator
    error_message = "application object did not match expected"
  }

  assert {
    condition     = output.app_name == "postfix-relay-configurator"
    error_message = "deprecated app_name did not match expected"
  }

  assert {
    condition     = output.requires.juju-info.kind == "endpoint"
    error_message = "juju-info kind did not match expected"
  }

  assert {
    condition     = output.requires.juju-info.name == juju_application.postfix_relay_configurator.name
    error_message = "juju-info relation name did not match expected"
  }

  assert {
    condition     = output.requires.juju-info.endpoint == "juju-info"
    error_message = "juju-info endpoint did not match expected"
  }
}
