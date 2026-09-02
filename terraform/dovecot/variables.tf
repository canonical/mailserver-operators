# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

variable "cos" {
  description = "Optional COS integration endpoint or cross-model offer."
  type = object({
    controller = optional(string)
    endpoint   = optional(string)
    kind       = string
    name       = optional(string)
    url        = optional(string)
  })
  default  = null
  nullable = true

  validation {
    condition     = var.cos == null || contains(["endpoint", "offer"], var.cos.kind)
    error_message = "cos.kind must be either endpoint or offer."
  }

  validation {
    condition = var.cos == null || (
      var.cos.kind == "endpoint"
      ? var.cos.name != null && var.cos.endpoint != null && var.cos.url == null
      : var.cos.url != null && var.cos.name == null && var.cos.endpoint == null
    )
    error_message = "COS endpoints require name and endpoint; COS offers require url."
  }
}

variable "dovecot" {
  description = "Dovecot charm deployment options."
  type = object({
    app_name    = optional(string, "dovecot")
    base        = optional(string, "ubuntu@24.04")
    channel     = optional(string)
    config      = optional(map(string), {})
    constraints = optional(string, "arch=amd64 root-disk=20G")
    endpoint_bindings = optional(set(object({
      endpoint = optional(string)
      space    = string
    })))
    expose = optional(object({
      cidrs     = optional(string)
      endpoints = optional(string)
      spaces    = optional(string)
    }))
    machines           = optional(set(string))
    resources          = optional(map(string), {})
    revision           = optional(number)
    storage_directives = optional(map(string), { mail-data = "8G" })
    units              = optional(number, 1)
  })
  default  = {}
  nullable = false
}

variable "juju_controller" {
  description = "Connection information for the Juju controller."
  type = object({
    ca            = optional(string)
    client_id     = optional(string)
    client_secret = optional(string)
    endpoint      = string
    password      = optional(string)
    username      = optional(string)
  })
  sensitive = true
  nullable  = false

  validation {
    condition = (
      (
        var.juju_controller.client_id != null
        && var.juju_controller.client_secret != null
        && var.juju_controller.username == null
        && var.juju_controller.password == null
      )
      || (
        var.juju_controller.username != null
        && var.juju_controller.password != null
        && var.juju_controller.client_id == null
        && var.juju_controller.client_secret == null
      )
    )
    error_message = "Set exactly one complete authentication pair: client_id/client_secret or username/password."
  }
}

variable "logging_config" {
  description = "Juju model logging configuration."
  type        = string
  default     = "<root>=INFO"
  nullable    = false
}

variable "create_model" {
  description = "Whether this product creates and owns its Juju model."
  type        = bool
  default     = true
  nullable    = false
}

variable "luks_key" {
  description = "Passphrase stored in a Juju secret for Dovecot encrypted mail storage."
  type        = string
  sensitive   = true
  nullable    = false

  validation {
    condition     = length(trimspace(var.luks_key)) > 0
    error_message = "luks_key must not be empty."
  }
}

variable "luks_secret_name" {
  description = "Optional Juju secret name for the Dovecot LUKS passphrase."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.luks_secret_name == null || length(trimspace(var.luks_secret_name)) > 0
    error_message = "luks_secret_name must be null or non-empty."
  }
}

variable "mail_domain" {
  description = "Mail domain served by Dovecot."
  type        = string
  nullable    = false
}

variable "model_cloud" {
  description = "Juju machine cloud used when model_uuid is null."
  type = object({
    name   = string
    region = optional(string)
  })
  default  = null
  nullable = true

  validation {
    condition     = !var.create_model || var.model_cloud != null
    error_message = "model_cloud is required when create_model is true."
  }
}

variable "model_uuid" {
  description = "Existing or externally managed Juju model UUID used when create_model is false."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.create_model || var.model_uuid != null
    error_message = "model_uuid is required when create_model is false."
  }
}

variable "model_constraints" {
  description = "Default constraints for machines in the Juju model."
  type        = string
  default     = ""
  nullable    = false
}

variable "model_name" {
  description = "Name of the Juju model created for the product."
  type        = string
  default     = "dovecot"
  nullable    = false
}

variable "postmaster_address" {
  description = "Postmaster email address configured on Dovecot."
  type        = string
  nullable    = false
}

variable "primary_unit" {
  description = "Dovecot unit that owns primary-only operations."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.primary_unit == null || length(trimspace(var.primary_unit)) > 0
    error_message = "primary_unit must be null or non-empty."
  }
}

variable "proxy" {
  description = "Proxy configuration applied to the Juju model."
  type = object({
    http     = optional(string, "")
    https    = optional(string, "")
    no_proxy = optional(string, "")
  })
  default  = {}
  nullable = false
}

variable "risk" {
  description = "Default charm channel risk used when a per-charm channel is not supplied."
  type        = string
  default     = "edge"
  nullable    = false

  validation {
    condition     = contains(["stable", "candidate", "beta", "edge"], var.risk)
    error_message = "risk must be one of stable, candidate, beta, or edge."
  }
}

variable "self_signed_certificates" {
  description = "Default TLS provider deployed when tls is null."
  type = object({
    app_name    = optional(string, "self-signed-certificates")
    base        = optional(string, "ubuntu@22.04")
    channel     = optional(string, "1/stable")
    config      = optional(map(string), {})
    constraints = optional(string, "arch=amd64")
    revision    = optional(number)
    units       = optional(number, 1)
  })
  default  = {}
  nullable = false
}

variable "tls" {
  description = "Optional TLS endpoint or cross-model offer replacing self-signed-certificates."
  type = object({
    controller = optional(string)
    endpoint   = optional(string)
    kind       = string
    name       = optional(string)
    url        = optional(string)
  })
  default  = null
  nullable = true

  validation {
    condition     = var.tls == null || contains(["endpoint", "offer"], var.tls.kind)
    error_message = "tls.kind must be either endpoint or offer."
  }

  validation {
    condition = var.tls == null || (
      var.tls.kind == "endpoint"
      ? var.tls.name != null && var.tls.endpoint != null && var.tls.url == null
      : var.tls.url != null && var.tls.name == null && var.tls.endpoint == null
    )
    error_message = "TLS endpoints require name and endpoint; TLS offers require url."
  }

  validation {
    condition     = var.tls == null || var.tls.controller == null
    error_message = "Cross-controller TLS offers are not supported without offering-controller credentials."
  }
}
