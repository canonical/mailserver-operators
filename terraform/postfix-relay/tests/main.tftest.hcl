mock_provider "juju" {
  mock_resource "juju_secret" {
    override_during = plan
    defaults = {
      secret_id = "test-secret-id"
    }
  }
}

variables {
  dkim_private_key = "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----"
  juju_controller = {
    ca       = "test-ca"
    endpoint = "127.0.0.1:17070"
    password = "test-password"
    username = "admin"
  }
  mail_domain = "mail.example.test"
  model_cloud = {
    name = "localhost"
  }
}

run "default_product_contract" {
  command = plan

  assert {
    condition     = output.metadata.product == "postfix-relay"
    error_message = "Product metadata must identify Postfix Relay."
  }

  assert {
    condition = (
      module.opendkim[0].application.charm[0].channel == "2/edge"
      && module.postfix_relay.application.charm[0].channel == "latest/edge"
    )
    error_message = "Default channels must use the published edge tracks."
  }

  assert {
    condition     = module.opendkim[0].application.config["private-keys"] == "secret:test-secret-id"
    error_message = "The product must wire the managed private-key secret into OpenDKIM."
  }

  assert {
    condition     = jsondecode(module.opendkim[0].application.config["signingtable"])[0][0] == "*@mail.example.test"
    error_message = "The product must generate the OpenDKIM signing table for the mail domain."
  }

  assert {
    condition     = output.dkim.record_name == "default._domainkey.mail.example.test"
    error_message = "The DKIM publication name must use the selector and mail domain."
  }
}

run "opendkim_disabled" {
  command = plan

  variables {
    enable_opendkim = false
  }

  assert {
    condition = (
      length(module.opendkim) == 0
      && length(juju_secret.opendkim_private_key) == 0
      && length(juju_integration.postfix_relay_opendkim) == 0
      && output.models.postfix_relay.components.opendkim == null
    )
    error_message = "Disabling OpenDKIM must omit its application, secret, and milter integration."
  }
}

run "cos_offer_contract" {
  command = plan

  variables {
    cos = {
      kind = "offer"
      url  = "admin/cos.cos-agent"
    }
    postfix_relay = {
      enable_cos_integration = true
    }
  }

  assert {
    condition     = length(juju_integration.cos_postfix_relay) == 1
    error_message = "Postfix Relay COS integration must be created when explicitly enabled."
  }
}

run "existing_model_contract" {
  command = plan

  variables {
    create_model = false
    model_cloud  = null
    model_uuid   = "00000000-0000-0000-0000-000000000000"
  }

  assert {
    condition = (
      length(juju_model.postfix_relay) == 0
      && output.models.postfix_relay.model_uuid == "00000000-0000-0000-0000-000000000000"
    )
    error_message = "An existing model UUID must suppress model creation and own all product resources."
  }
}

run "restricted_exposure" {
  command = plan

  variables {
    postfix_relay = {
      expose = {
        cidrs = "10.0.0.0/8"
      }
    }
  }

  assert {
    condition     = module.postfix_relay.application.expose[0].cidrs == "10.0.0.0/8"
    error_message = "The product must pass restricted Juju exposure to Postfix Relay."
  }
}

run "reject_invalid_risk" {
  command = plan

  variables {
    risk = "dangerous"
  }

  expect_failures = [var.risk]
}

run "reject_empty_dkim_private_key" {
  command = plan

  variables {
    dkim_private_key = ""
  }

  expect_failures = [var.dkim_private_key]
}

run "reject_mixed_controller_authentication" {
  command = plan

  variables {
    juju_controller = {
      client_id     = "client"
      client_secret = "client-secret"
      endpoint      = "127.0.0.1:17070"
      password      = "password"
      username      = "admin"
    }
  }

  expect_failures = [var.juju_controller]
}
