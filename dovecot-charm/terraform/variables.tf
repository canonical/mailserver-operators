# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

variable "app_name" {
  description = "Name of the application in the Juju model."
  type        = string
  default     = "dovecot"
}

variable "base" {
  description = "The operating system on which to deploy"
  type        = string
  default     = "ubuntu@24.04"
}

variable "channel" {
  description = "The channel to use when deploying a charm."
  type        = string
  default     = "2.3/edge"
}

variable "charm_name" {
  description = "Charm name or path to a local .charm file to deploy."
  type        = string
  default     = "dovecot"
}

variable "config" {
  description = "Application config. Details about available options can be found at https://charmhub.io/dovecot/configurations."
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

variable "trust" {
  description = "Whether to grant the charm administrative access to the Juju model (required for dovecot to manage system users)."
  type        = bool
  default     = true
}

variable "units" {
  description = "Number of units to deploy"
  type        = number
  default     = 1
}
