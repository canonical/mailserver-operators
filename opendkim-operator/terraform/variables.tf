# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

variable "app_name" {
  description = "Name of the application in the Juju model."
  type        = string
  default     = "opendkim"
}

variable "base" {
  description = "Base to deploy the charm on."
  type        = string
  default     = "ubuntu@24.04"
}

variable "channel" {
  description = "Charm channel to deploy."
  type        = string
  default     = "2/edge"
}

variable "config" {
  description = "Charm configuration values."
  type        = map(string)
  default     = {}
}

variable "constraints" {
  description = "Juju constraints to apply to the application."
  type        = string
  default     = "arch=amd64"
}

variable "endpoint_bindings" {
  description = "Endpoint bindings for the application."
  type = set(object({
    endpoint = optional(string)
    space    = string
  }))
  default = null
}

variable "machines" {
  description = "Target machines for the application units."
  type        = set(string)
  default     = null
}

variable "model_uuid" {
  description = "UUID of the Juju model to deploy the application to."
  type        = string
}

variable "resources" {
  description = "Charm resources to provide when deploying the application."
  type        = map(string)
  default     = {}
}

variable "revision" {
  description = "Charm revision to deploy."
  type        = number
  default     = null
}

variable "units" {
  description = "Number of units to deploy when machines are not specified."
  type        = number
  default     = 1
}
