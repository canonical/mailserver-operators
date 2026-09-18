# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

variables {
  app_name          = "dovecot"
  base              = "ubuntu@24.04"
  channel           = "2.3/edge"
  config            = {}
  constraints       = "arch=amd64 root-disk=20G"
  endpoint_bindings = null
  machines          = null
  model_uuid        = "00000000-0000-0000-0000-000000000001"
  resources         = {}
  revision          = 10
  storage_directives = {
    "mail-data" = "8G"
  }
  units = 1
}

mock_provider "juju" {
  mock_resource "juju_application" {
    defaults = {
      id           = "dovecot"
      model_type   = "lxd"
      unit_numbers = ["0"]
    }
  }
}

run "deploys_application" {
  command = plan

  assert {
    condition     = output.app_name == "dovecot"
    error_message = "deprecated app_name output did not match"
  }

  assert {
    condition     = output.application.name == "dovecot"
    error_message = "application name did not match"
  }

  assert {
    condition     = output.application.model_uuid == var.model_uuid
    error_message = "application model_uuid did not match"
  }

  assert {
    condition     = output.application.charm[0].name == "dovecot"
    error_message = "application charm name did not match"
  }

  assert {
    condition     = output.provides["cos-agent"].kind == "endpoint"
    error_message = "cos-agent kind did not match"
  }

  assert {
    condition     = output.provides["cos-agent"].name == "dovecot"
    error_message = "cos-agent name did not match"
  }

  assert {
    condition     = output.provides["cos-agent"].endpoint == "cos-agent"
    error_message = "cos-agent endpoint did not match"
  }

  assert {
    condition     = output.requires.certificates.kind == "endpoint"
    error_message = "certificates kind did not match"
  }

  assert {
    condition     = output.requires.certificates.name == "dovecot"
    error_message = "certificates name did not match"
  }

  assert {
    condition     = output.requires.certificates.endpoint == "certificates"
    error_message = "certificates endpoint did not match"
  }
}
