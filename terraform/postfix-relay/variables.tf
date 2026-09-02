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

variable "dkim_key_name" {
  description = "Secret field and private-key filename stem used by OpenDKIM."
  type        = string
  default     = "postfix-relay-default"
  nullable    = false
}

variable "dkim_private_key" {
  description = "PEM-encoded private key used to sign mail with DKIM."
  type        = string
  sensitive   = true
  nullable    = false

  validation {
    condition     = length(trimspace(var.dkim_private_key)) > 0
    error_message = "dkim_private_key must not be empty."
  }
}

variable "dkim_selector" {
  description = "DKIM selector published below the mail domain."
  type        = string
  default     = "default"
  nullable    = false
}

variable "enable_opendkim" {
  description = "Whether to deploy OpenDKIM and integrate it with Postfix Relay."
  type        = bool
  default     = true
  nullable    = false
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

variable "mail_domain" {
  description = "Mail domain whose messages OpenDKIM signs."
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
  default     = "postfix-relay"
  nullable    = false
}

variable "opendkim" {
  description = "OpenDKIM charm deployment options."
  type = object({
    app_name    = optional(string, "opendkim")
    base        = optional(string, "ubuntu@24.04")
    channel     = optional(string)
    config      = optional(map(string), {})
    constraints = optional(string, "arch=amd64")
    endpoint_bindings = optional(set(object({
      endpoint = optional(string)
      space    = string
    })))
    machines  = optional(set(string))
    resources = optional(map(string), {})
    revision  = optional(number)
    units     = optional(number, 1)
  })
  default  = {}
  nullable = false
}

variable "postfix_relay" {
  description = "Postfix Relay charm deployment options."
  type = object({
    app_name               = optional(string, "postfix-relay")
    base                   = optional(string, "ubuntu@24.04")
    channel                = optional(string)
    config                 = optional(map(string), {})
    constraints            = optional(string, "arch=amd64")
    enable_cos_integration = optional(bool, false)
    endpoint_bindings = optional(set(object({
      endpoint = optional(string)
      space    = string
    })))
    expose = optional(object({
      cidrs     = optional(string)
      endpoints = optional(string)
      spaces    = optional(string)
    }))
    machines           = optional(set(string), [])
    resources          = optional(map(string), {})
    revision           = optional(number)
    storage_directives = optional(map(string), {})
    units              = optional(number, 1)
  })
  default  = {}
  nullable = false
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
