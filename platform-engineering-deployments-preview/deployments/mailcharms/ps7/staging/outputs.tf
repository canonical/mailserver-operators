output "dkim" {
  description = "DKIM DNS publication coordinates."
  value = {
    domain      = var.mail_domain
    record_name = "default._domainkey.${var.mail_domain}"
    selector    = "default"
  }
}

output "applications" {
  description = "Applications deployed into the existing PS7 model."
  value = {
    dovecot               = module.dovecot.models.dovecot.components.dovecot.name
    dovecot_imaps_ingress = try(juju_application.dovecot_imaps_ingress[0].name, null)
    opendkim              = try(module.postfix_relay.models.postfix_relay.components.opendkim.name, null)
    postfix_smtp_ingress  = try(juju_application.postfix_smtp_ingress[0].name, null)
    postfix_relay         = module.postfix_relay.models.postfix_relay.components.postfix_relay.name
  }
}

output "tcp_ingress" {
  description = "Temporary HAProxy TCP routes used for client validation."
  value = {
    offer_url = var.haproxy_route_tcp_offer_url
    imaps = {
      backend_port  = 993
      frontend_port = var.imaps_frontend_port
    }
    smtp = {
      backend_port  = 25
      frontend_port = var.smtp_frontend_port
    }
  }
}
