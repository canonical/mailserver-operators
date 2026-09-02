locals {
  juju_controller = {
    client_id     = data.vault_generic_secret.jaas_credentials_ps7.data["juju_client_id"]
    client_secret = data.vault_generic_secret.jaas_credentials_ps7.data["juju_client_secret"]
    endpoint      = "jaas.ps7.canonical.com:443/k8s-jaas-ps7-jimm-jimm"
  }
}

module "dovecot" {
  source = "../../../../../terraform/dovecot"

  create_model       = false
  juju_controller    = local.juju_controller
  model_uuid         = var.juju_model_uuid
  mail_domain        = var.mail_domain
  postmaster_address = var.postmaster_address
  primary_unit       = var.dovecot_primary_unit
  luks_key           = var.luks_key
  luks_secret_name   = "mailcharms-staging-dovecot-luks-key"

  dovecot = {
    channel = "2.3/edge"
    expose = {
      cidrs = "10.0.0.0/8"
    }
    revision = 10
    storage_directives = {
      mail-data = var.dovecot_storage
    }
  }

}

module "postfix_relay" {
  source = "../../../../../terraform/postfix-relay"

  create_model     = false
  juju_controller  = local.juju_controller
  model_uuid       = var.juju_model_uuid
  mail_domain      = var.mail_domain
  dkim_private_key = var.dkim_private_key
  enable_opendkim  = true

  opendkim = {
    channel  = "2/edge"
    machines = toset([var.postfix_machine_id])
    revision = 10
  }

  postfix_relay = {
    channel = "latest/edge"
    expose = {
      cidrs = "10.0.0.0/8"
    }
    revision = 13
    config = {
      allowed_relay_networks              = jsonencode([])
      domain                              = var.mail_domain
      enable_reject_unknown_sender_domain = "false"
      enable_smtp_auth                    = tostring(length(var.smtp_auth_users) > 0)
      relay_domains                       = jsonencode([var.mail_domain])
      relay_host                          = var.dovecot_relay_host == "" ? "" : "[${var.dovecot_relay_host}]"
      smtp_auth_users                     = jsonencode(var.smtp_auth_users)
    }
  }
}

resource "juju_application" "dovecot_imaps_ingress" {
  count      = var.dovecot_backend_address == "" || var.dovecot_machine_id == "" ? 0 : 1
  model_uuid = var.juju_model_uuid
  name       = "dovecot-imaps-ingress"

  machines = toset([var.dovecot_machine_id])

  charm {
    base     = "ubuntu@24.04"
    channel  = "latest/edge"
    name     = "ingress-configurator"
    revision = 72
  }

  config = {
    tcp-backend-addresses = var.dovecot_backend_address
    tcp-backend-port      = "993"
    tcp-enforce-tls       = "true"
    tcp-frontend-port     = tostring(var.imaps_frontend_port)
    tcp-tls-terminate     = "false"
  }
}

resource "juju_integration" "dovecot_imaps_haproxy" {
  count      = var.dovecot_backend_address == "" || var.dovecot_machine_id == "" ? 0 : 1
  model_uuid = var.juju_model_uuid

  application {
    name     = juju_application.dovecot_imaps_ingress[0].name
    endpoint = "haproxy-route-tcp"
  }

  application {
    offer_url = var.haproxy_route_tcp_offer_url
  }
}

resource "juju_application" "postfix_smtp_ingress" {
  count      = var.postfix_backend_address == "" || var.postfix_machine_id == "" ? 0 : 1
  model_uuid = var.juju_model_uuid
  name       = "postfix-smtp-ingress"

  machines = toset([var.postfix_machine_id])

  charm {
    base     = "ubuntu@24.04"
    channel  = "latest/edge"
    name     = "ingress-configurator"
    revision = 72
  }

  config = {
    tcp-backend-addresses = var.postfix_backend_address
    tcp-backend-port      = "25"
    tcp-enforce-tls       = "false"
    tcp-frontend-port     = tostring(var.smtp_frontend_port)
    tcp-tls-terminate     = "false"
  }
}

resource "juju_integration" "postfix_smtp_haproxy" {
  count      = var.postfix_backend_address == "" || var.postfix_machine_id == "" ? 0 : 1
  model_uuid = var.juju_model_uuid

  application {
    name     = juju_application.postfix_smtp_ingress[0].name
    endpoint = "haproxy-route-tcp"
  }

  application {
    offer_url = var.haproxy_route_tcp_offer_url
  }
}

moved {
  from = module.dovecot_imaps_ingress[0].juju_application.ingress-configurator
  to   = juju_application.dovecot_imaps_ingress[0]
}

moved {
  from = module.postfix_smtp_ingress[0].juju_application.ingress-configurator
  to   = juju_application.postfix_smtp_ingress[0]
}
