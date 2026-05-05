# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

run "setup_tests" {
  module {
    source = "./tests/setup"
  }
}

run "basic_deploy" {
  variables {
    model_uuid = run.setup_tests.model_uuid
    postfix_relay = {
      channel = "latest/edge"
      # renovate: depName="postfix-relay"
      revision = 13
    }
    opendkim = {
      channel = "2/edge"
      # renovate: depName="opendkim"
      revision = 9
    }
  }

  assert {
    condition     = output.app_name == "postfix-relay"
    error_message = "postfix-relay app_name did not match expected"
  }
}
