# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

terraform {
  required_version = "~> 1.12"
  required_providers {
    external = {
      version = "> 2"
      source  = "hashicorp/external"
    }
    juju = {
      version = "~> 1.0"
      source  = "juju/juju"
    }
  }
}

provider "juju" {}

variable "model_uuid" {
  type = string
}

module "mail_stack" {
  source     = "../.."
  model_uuid = var.model_uuid

  dovecot = {
    charm    = "local:dovecot"
    app_name = "dovecot"
  }

  postfix_relay = {
    charm    = "local:postfix-relay"
    app_name = "postfix-relay"
  }

  opendkim = {
    charm    = "local:opendkim"
    app_name = "opendkim"
  }

  postfix_relay_configurator = {
    charm    = "local:postfix-relay-configurator"
    app_name = "postfix-relay-configurator"
  }

  self_signed_certificates = {
    channel  = "1/stable"
    base     = "ubuntu@22.04"
    app_name = "self-signed-certificates"
  }
}

# tflint-ignore: terraform_unused_declarations
data "external" "dovecot_status" {
  program = ["bash", "${path.module}/wait-for-active.sh", var.model_uuid, module.mail_stack.app_names.dovecot, "12m"]
}

# tflint-ignore: terraform_unused_declarations
data "external" "postfix_relay_status" {
  program = ["bash", "${path.module}/wait-for-active.sh", var.model_uuid, module.mail_stack.app_names.postfix_relay, "12m"]
}

# tflint-ignore: terraform_unused_declarations
data "external" "self_signed_status" {
  program = ["bash", "${path.module}/wait-for-active.sh", var.model_uuid, module.mail_stack.app_names.self_signed_certificates, "12m"]
}

# tflint-ignore: terraform_unused_declarations
data "external" "opendkim_status" {
  program = ["bash", "${path.module}/wait-for-active.sh", var.model_uuid, module.mail_stack.app_names.opendkim, "12m", "any"]
}
