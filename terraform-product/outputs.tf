# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

output "app_names" {
  description = "Map of logical role → deployed Juju application name."
  value = {
    dovecot                    = module.dovecot.app_name
    postfix_relay              = module.postfix_relay.app_name
    opendkim                   = module.opendkim.app_name
    postfix_relay_configurator = module.postfix_relay_configurator.app_name
    self_signed_certificates   = juju_application.self_signed_certificates.name
  }
}

output "endpoints" {
  description = "Notable integration endpoints for each application."
  value = {
    dovecot = {
      certificates = module.dovecot.requires.certificates
    }
    postfix_relay = {
      certificates = module.postfix_relay.requires.certificates
      milter       = module.postfix_relay.requires.milter
      juju_info    = module.postfix_relay.provides.juju_info
    }
    opendkim = {
      milter = module.opendkim.provides.milter
    }
    postfix_relay_configurator = {
      juju_info = module.postfix_relay_configurator.requires.juju_info
    }
    self_signed_certificates = {
      certificates = "certificates"
    }
  }
}
