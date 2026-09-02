# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

variable "app_name" {
  description = "Name of the application in the Juju model."
  type        = string
  default     = "dovecot"
}

variable "base" {
  description = "The operating system on which to deploy."
  type        = string
  default     = "ubuntu@24.04"
}

variable "channel" {
  description = "The channel to use when deploying the charm."
  type        = string
  default     = "2.3/edge"
}

variable "config" {
  description = "Application config values for the Dovecot charm."
  type        = map(any)
  default     = {}
}

variable "constraints" {
  description = "Juju constraints to apply for this application."
  type        = string
  default     = "arch=amd64 root-disk=20G"
}

variable "endpoint_bindings" {
  description = "Optional endpoint bindings for charm relations."
  type = set(object({
    endpoint = optional(string)
    space    = string
  }))
  default = null
}

variable "expose" {
  description = "Optional Juju exposure restricted by CIDRs, endpoints, or spaces."
  type = object({
    cidrs     = optional(string)
    endpoints = optional(string)
    spaces    = optional(string)
  })
  default  = null
  nullable = true
}

variable "machines" {
  description = "Optional target machine IDs for the application's units."
  type        = set(string)
  default     = null
}

variable "model_uuid" {
  description = "UUID of the Juju model where the application will be deployed."
  type        = string
}

variable "resources" {
  description = "Charm resources to attach during deployment."
  type        = map(string)
  default     = {}
}

variable "revision" {
  description = "Revision number of the charm."
  type        = number
  default     = null
}

variable "storage_directives" {
  description = "Storage directives for the juju application."
  type        = map(string)
  default = {
    "mail-data" = "8G"
  }
}

variable "units" {
  description = "Number of units to deploy when machines are not specified."
  type        = number
  default     = 1
}
