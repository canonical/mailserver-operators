# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

variable "app_name" {
  description = "Name of the application in the Juju model."
  type        = string
  default     = "postfix-relay"
}

variable "base" {
  description = "The operating system on which to deploy"
  type        = string
  default     = "ubuntu@24.04"
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
  default     = "arch=amd64"
}

variable "model_uuid" {
  description = "UUID of the Juju model to deploy application to."
  type        = string
}

variable "revision" {
  description = "Revision number of the charm"
  type        = number
  default     = null
}

variable "storage" {
  description = "Map of storage used by the application."
  type        = map(string)
  default     = {}
}

variable "units" {
  description = "Number of units to deploy"
  type        = number
  default     = 1
}
