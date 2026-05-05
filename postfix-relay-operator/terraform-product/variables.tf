# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

variable "model_uuid" {
  description = "UUID of the Juju model to deploy application to."
  type        = string
}

variable "postfix_relay" {
  type = object({
    app_name    = optional(string, "postfix-relay")
    channel     = optional(string, "3/stable")
    config      = optional(map(string), {})
    constraints = optional(string, "arch=amd64")
    revision    = optional(number)
    base        = optional(string, "ubuntu@24.04")
    units       = optional(number, 1)
  })
}

variable "opendkim" {
  type = object({
    app_name    = optional(string, "opendkim")
    channel     = optional(string, "2/stable")
    config      = optional(map(string), {})
    constraints = optional(string, "arch=amd64")
    revision    = optional(number)
    base        = optional(string, "ubuntu@24.04")
    units       = optional(number, 1)
    storage     = optional(map(string), {})
  })
}
