# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

variable "app_name" {
  description = "Name of the application in the Juju model."
  type        = string
  default     = "postfix-relay-configurator"
  nullable    = false
}

variable "base" {
  description = "The operating system on which to deploy"
  type        = string
  default     = "ubuntu@24.04"
  nullable    = false
}

variable "channel" {
  description = "The channel to use when deploying a charm."
  type        = string
  default     = "latest/stable"
  nullable    = false
}

variable "config" {
  description = "Application config. Details about available options can be found at https://charmhub.io/postfix-relay-configurator/configurations."
  type        = map(string)
  default     = {}
  nullable    = false
}

variable "constraints" {
  description = "Deprecated Juju constraints retained for compatibility."
  type        = string
  default     = "arch=amd64"
  nullable    = false
}

variable "endpoint_bindings" {
  description = "Endpoint bindings to apply for this application."
  type = set(object({
    endpoint = optional(string)
    space    = string
  }))
  default  = []
  nullable = false
}

variable "model_uuid" {
  description = "UUID of the Juju model to deploy application to."
  type        = string
  nullable    = false
}

variable "resources" {
  description = "Charm resources to pass to Juju."
  type        = map(string)
  default     = {}
  nullable    = false
}

variable "revision" {
  description = "Revision number of the charm"
  type        = number
  default     = null
  nullable    = true
}

variable "storage" {
  description = "Deprecated storage directives retained for compatibility."
  type        = map(string)
  default     = {}
  nullable    = false
}
