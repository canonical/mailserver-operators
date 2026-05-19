# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

variable "model_uuid" {
  description = "UUID of the Juju model where the mail stack will be deployed."
  type        = string
}

variable "domain" {
  description = <<-EOT
    Primary mail domain (e.g. \"example.com\").
    Used to set dovecot's mailname, postfix-relay's relay_domains, and as
    default postmaster address domain.
  EOT
  type        = string
  default     = "mail.example.com"
}

variable "transport_maps" {
  description = <<-EOT
    Map of domain → LMTP/SMTP transport destinations forwarded to dovecot.
    Example: { "mail.example.com" = "lmtp:inet:10.0.0.5:24" }
    Leave empty on first deploy, then populate with dovecot's IP after it
    becomes active and re-apply.
  EOT
  type        = map(string)
  default     = {}
}

# ---------------------------------------------------------------------------
# Per-charm configuration objects
# Each object exposes:
#   charm       — charm name (Charmhub) OR path to a local .charm file
#   app_name    — Juju application name
#   channel     — Charmhub channel (ignored for local charms)
#   revision    — Charmhub revision (ignored for local charms)
#   base        — OS base (ignored for local charms)
#   config      — extra charm config merged on top of module defaults
#   constraints — Juju machine constraints
#   units       — number of units (where applicable)
#   storage     — storage directives
# ---------------------------------------------------------------------------

variable "self_signed_certificates" {
  description = "Configuration for the self-signed-certificates charm (TLS provider)."
  type = object({
    charm       = optional(string, "self-signed-certificates")
    app_name    = optional(string, "self-signed-certificates")
    channel     = optional(string, "1/stable")
    revision    = optional(number)
    base        = optional(string, "ubuntu@22.04")
    config      = optional(map(string), {})
    constraints = optional(string, "")
    units       = optional(number, 1)
  })
  default = {}
}

variable "dovecot" {
  description = "Configuration for the dovecot charm (IMAP server)."
  type = object({
    charm       = optional(string, "dovecot")
    app_name    = optional(string, "dovecot")
    channel     = optional(string, "2.3/edge")
    revision    = optional(number)
    base        = optional(string, "ubuntu@24.04")
    config      = optional(map(string), {})
    constraints = optional(string, "virt-type=virtual-machine arch=amd64")
    units       = optional(number, 1)
    storage     = optional(map(string), {})
  })
  default = {}
}

variable "postfix_relay" {
  description = "Configuration for the postfix-relay charm (SMTP relay)."
  type = object({
    charm       = optional(string, "postfix-relay")
    app_name    = optional(string, "postfix-relay")
    channel     = optional(string, "latest/edge")
    revision    = optional(number)
    base        = optional(string, "ubuntu@24.04")
    config      = optional(map(string), {})
    constraints = optional(string, "arch=amd64")
    units       = optional(number, 1)
    storage     = optional(map(string), {})
  })
  default = {}
}

variable "opendkim" {
  description = "Configuration for the opendkim charm (DKIM signing milter)."
  type = object({
    charm       = optional(string, "opendkim")
    app_name    = optional(string, "opendkim")
    channel     = optional(string, "2/edge")
    revision    = optional(number)
    base        = optional(string, "ubuntu@24.04")
    config      = optional(map(string), {})
    constraints = optional(string, "arch=amd64")
    units       = optional(number, 1)
    storage     = optional(map(string), {})
  })
  default = {}
}

variable "postfix_relay_configurator" {
  description = "Configuration for the postfix-relay-configurator subordinate charm."
  type = object({
    charm       = optional(string, "postfix-relay-configurator")
    app_name    = optional(string, "postfix-relay-configurator")
    channel     = optional(string, "latest/edge")
    revision    = optional(number)
    base        = optional(string, "ubuntu@24.04")
    config      = optional(map(string), {})
    constraints = optional(string, "")
    storage     = optional(map(string), {})
  })
  default = {}
}
