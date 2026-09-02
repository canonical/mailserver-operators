mock_provider "juju" {
  mock_resource "juju_secret" {
    override_during = plan
    defaults = {
      secret_id = "test-secret-id"
    }
  }
}

variables {
  juju_controller = {
    ca       = "test-ca"
    endpoint = "127.0.0.1:17070"
    password = "test-password"
    username = "admin"
  }
  luks_key    = "test-luks-passphrase"
  mail_domain = "mail.example.test"
  model_cloud = {
    name = "localhost"
  }
  postmaster_address = "postmaster@mail.example.test"
}

run "default_product_contract" {
  command = plan

  assert {
    condition     = output.metadata.product == "dovecot"
    error_message = "Product metadata must identify Dovecot."
  }

  assert {
    condition     = module.dovecot.application.charm[0].channel == "2.3/edge"
    error_message = "Dovecot must default to its published edge track."
  }

  assert {
    condition     = module.dovecot.application.config["mailname"] == "mail.example.test"
    error_message = "The product must configure the Dovecot mail domain."
  }

  assert {
    condition     = module.dovecot.application.config["luks-key"] == "secret:test-secret-id"
    error_message = "The product must wire the managed LUKS secret into Dovecot."
  }

  assert {
    condition = (
      juju_application.self_signed_certificates[0].charm[0].base == "ubuntu@22.04"
      && juju_application.self_signed_certificates[0].charm[0].channel == "1/stable"
    )
    error_message = "The default TLS provider must use its stable published platform."
  }
}

run "external_tls_contract" {
  command = plan

  variables {
    tls = {
      kind = "offer"
      url  = "admin/certificates.certificates"
    }
  }

  assert {
    condition     = length(juju_application.self_signed_certificates) == 0
    error_message = "The default TLS charm must not deploy when an external offer is supplied."
  }

  assert {
    condition = anytrue([
      for application in juju_integration.tls_dovecot.application :
      application.offer_url == "admin/certificates.certificates"
    ])
    error_message = "Dovecot TLS must consume the configured external offer."
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
      length(juju_model.dovecot) == 0
      && output.models.dovecot.model_uuid == "00000000-0000-0000-0000-000000000000"
    )
    error_message = "An existing model UUID must suppress model creation and own all product resources."
  }
}

run "explicit_primary_unit" {
  command = plan

  variables {
    primary_unit = "dovecot/1"
  }

  assert {
    condition     = module.dovecot.application.config["primary-unit"] == "dovecot/1"
    error_message = "The product must accept a discovered primary unit name."
  }
}

run "restricted_exposure" {
  command = plan

  variables {
    dovecot = {
      expose = {
        cidrs = "10.0.0.0/8"
      }
    }
  }

  assert {
    condition     = module.dovecot.application.expose[0].cidrs == "10.0.0.0/8"
    error_message = "The product must pass restricted Juju exposure to Dovecot."
  }
}

run "local_lxd_block_storage" {
  command = plan

  variables {
    dovecot = {
      storage_directives = {
        "mail-data" = "loop,8G"
      }
    }
  }

  assert {
    condition     = module.dovecot.application.storage_directives["mail-data"] == "loop,8G"
    error_message = "The product must pass an explicitly selected LXD block-storage pool to Dovecot."
  }
}

run "reject_invalid_risk" {
  command = plan

  variables {
    risk = "dangerous"
  }

  expect_failures = [var.risk]
}

run "reject_empty_luks_key" {
  command = plan

  variables {
    luks_key = ""
  }

  expect_failures = [var.luks_key]
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
