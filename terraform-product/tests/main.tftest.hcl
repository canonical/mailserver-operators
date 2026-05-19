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
    domain     = "mailstack.internal"

    dovecot = {
      charm    = "./dovecot-charm/dovecot_amd64.charm"
      app_name = "dovecot"
    }

    postfix_relay = {
      charm    = "./postfix-relay-operator/postfix-relay_amd64.charm"
      app_name = "postfix-relay"
    }

    opendkim = {
      charm    = "./opendkim-operator/opendkim_amd64.charm"
      app_name = "opendkim"
    }

    postfix_relay_configurator = {
      charm    = "./postfix-relay-configurator-operator/postfix-relay-configurator_amd64.charm"
      app_name = "postfix-relay-configurator"
    }
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
    condition     = output.app_names.postfix_relay_configurator == "postfix-relay-configurator"
    error_message = "postfix-relay-configurator app_name did not match expected"
  }

  assert {
    condition     = output.app_names.self_signed_certificates == "self-signed-certificates"
    error_message = "self-signed-certificates app_name did not match expected"
  }

  assert {
    condition     = output.endpoints.postfix_relay.milter == "milter"
    error_message = "postfix-relay milter endpoint mismatch"
  }

  assert {
    condition     = output.endpoints.postfix_relay.certificates == "certificates"
    error_message = "postfix-relay certificates endpoint mismatch"
  }

  assert {
    condition     = output.endpoints.dovecot.certificates == "certificates"
    error_message = "dovecot certificates endpoint mismatch"
  }

  assert {
    condition     = output.endpoints.opendkim.milter == "milter"
    error_message = "opendkim milter endpoint mismatch"
  }
}
