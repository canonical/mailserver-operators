# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

output "app_names" {
  description = "Names of deployed applications."
  value = {
    dovecot                    = juju_application.dovecot.name
    postfix_relay              = juju_application.postfix_relay.name
    opendkim                   = juju_application.opendkim.name
    postfix_relay_configurator = juju_application.postfix_relay_configurator.name
    self_signed_certificates   = juju_application.self_signed_certificates.name
  }
}

output "endpoints" {
  value = {
    dovecot = {
      certificates = "certificates"
    }
    postfix_relay = {
      certificates = "certificates"
      milter       = "milter"
      juju_info    = "juju-info"
    }
    opendkim = {
      milter = "milter"
    }
    postfix_relay_configurator = {
      juju_info = "juju-info"
    }
    self_signed_certificates = {
      certificates = "certificates"
    }
  }
}
