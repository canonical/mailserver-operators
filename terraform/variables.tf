# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

variable "model_uuid" {
  description = "UUID of the Juju model where the application will be deployed."
  type        = string
}

variable "test_domain" {
  description = "Domain used to configure dovecot and postfix-relay defaults."
  type        = string
  default     = "mailstack.internal"
}

variable "transport_maps" {
  description = "YAML map-equivalent used for postfix-relay-configurator transport_maps."
  type        = map(string)
  default     = {}
}

variable "self_signed_certificates" {
  description = "Configuration for self-signed-certificates charm deployment."
  type = object({
    charm       = optional(string, "self-signed-certificates")
    app_name    = optional(string, "self-signed-certificates")
    channel     = optional(string, "1/stable")
    config      = optional(map(string), {})
    constraints = optional(string, "")
    revision    = optional(number)
    base        = optional(string, "ubuntu@22.04")
    units       = optional(number, 1)
  })
  default = {}
}

variable "dovecot" {
  description = "Configuration for dovecot charm deployment."
  type = object({
    charm       = optional(string, "dovecot")
    app_name    = optional(string, "dovecot")
    channel     = optional(string, "2.3/edge")
    config      = optional(map(string), {})
    constraints = optional(string, "arch=amd64")
    revision    = optional(number)
    base        = optional(string, "ubuntu@24.04")
    units       = optional(number, 1)
    storage     = optional(map(string), {})
  })
  default = {}
}

variable "postfix_relay" {
  description = "Configuration for postfix-relay charm deployment."
  type = object({
    charm       = optional(string, "postfix-relay")
    app_name    = optional(string, "postfix-relay")
    channel     = optional(string, "latest/edge")
    config      = optional(map(string), {})
    constraints = optional(string, "arch=amd64")
    revision    = optional(number)
    base        = optional(string, "ubuntu@24.04")
    units       = optional(number, 1)
    storage     = optional(map(string), {})
  })
  default = {}
}

variable "opendkim" {
  description = "Configuration for opendkim charm deployment."
  type = object({
    charm       = optional(string, "opendkim")
    app_name    = optional(string, "opendkim")
    channel     = optional(string, "2/edge")
    config      = optional(map(string), {})
    constraints = optional(string, "arch=amd64")
    revision    = optional(number)
    base        = optional(string, "ubuntu@24.04")
    units       = optional(number, 1)
    storage     = optional(map(string), {})
  })
  default = {}
}

variable "postfix_relay_configurator" {
  description = "Configuration for postfix-relay-configurator charm deployment."
  type = object({
    charm       = optional(string, "postfix-relay-configurator")
    app_name    = optional(string, "postfix-relay-configurator")
    channel     = optional(string, "latest/edge")
    config      = optional(map(string), {})
    constraints = optional(string, "")
    revision    = optional(number)
    base        = optional(string, "ubuntu@24.04")
    units       = optional(number, 0)
    storage     = optional(map(string), {})
  })
  default = {}
}
