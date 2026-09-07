# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

variable "app_name" {
  description = "Name of the application in the Juju model."
  type        = string
  default     = "postfix-relay"
}

variable "base" {
  description = "The operating system on which to deploy."
  type        = string
  default     = null
}

variable "channel" {
  description = "The channel to use when deploying a charm."
  type        = string
  default     = "3/stable"
}

variable "config" {
  description = "Application config. Details about available options can be found at https://charmhub.io/postfix-relay/configurations."
  type        = map(string)
  default     = {}
}

variable "constraints" {
  description = "Juju constraints to apply for this application."
  type        = string
  default     = null
}

variable "endpoint_bindings" {
  description = "Endpoint bindings to apply to the application."
  type = set(object({
    endpoint = optional(string)
    space    = string
  }))
  default = []
}

variable "expose" {
  description = "Optional Juju exposure restricted by CIDRs, endpoints, or spaces."
  type = object({
    cidrs     = optional(string)
    endpoints = optional(string)
    spaces    = optional(string)
  })
  default  = {}
  nullable = true
}

variable "machines" {
  description = "Target machine IDs for the application's units."
  type        = set(string)
  default     = []
}

variable "model_uuid" {
  description = "UUID of the Juju model to deploy application to."
  type        = string
}

variable "resources" {
  description = "Charm resources to deploy with the application."
  type        = map(string)
  default     = {}
}

variable "revision" {
  description = "Revision number of the charm."
  type        = number
  default     = null
}

variable "storage" {
  description = "Deprecated storage directives; use storage_directives instead."
  type        = map(string)
  default     = {}
}

variable "storage_directives" {
  description = "Storage directives used by the application."
  type        = map(string)
  default     = {}
}

variable "units" {
  description = "Number of units to deploy."
  type        = number
  default     = 1
}
