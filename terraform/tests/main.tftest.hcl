# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

run "setup_tests" {
  module {
    source = "./tests/setup"
  }
}

run "module_plan" {
  command = plan

  variables {
    model_uuid = run.setup_tests.model_uuid
  }

  assert {
    condition     = output.app_names.dovecot == "dovecot"
    error_message = "dovecot app_name did not match expected"
  }

  assert {
    condition     = output.app_names.postfix_relay == "postfix-relay"
    error_message = "postfix-relay app_name did not match expected"
  }

  assert {
    condition     = output.app_names.opendkim == "opendkim"
    error_message = "opendkim app_name did not match expected"
  }

  assert {
    condition     = output.endpoints.postfix_relay.milter == "milter"
    error_message = "postfix-relay milter endpoint mismatch"
  }

  assert {
    condition     = output.endpoints.dovecot.certificates == "certificates"
    error_message = "dovecot certificates endpoint mismatch"
  }
}
