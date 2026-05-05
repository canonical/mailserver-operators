# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

run "setup_tests" {
  module {
    source = "./tests/setup"
  }
}

run "basic_deploy" {
  variables {
    model_uuid = run.setup_tests.model_uuid
    channel    = "2.3/edge"
    # renovate: depName="dovecot"
    revision = 3
  }

  assert {
    condition     = output.app_name == "dovecot"
    error_message = "dovecot app_name did not match expected"
  }
}
