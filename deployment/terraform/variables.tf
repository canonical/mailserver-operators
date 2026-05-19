# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

variable "create_model" {
  description = "When true a new Juju model named model_name is created. Set false to target an existing model (model_uuid must then be provided)."
  type        = bool
  default     = true
}

variable "model_name" {
  description = "Name for the Juju model. Used when create_model = true; also surfaced as an output."
  type        = string
  default     = "mailserver"
}

variable "model_uuid" {
  description = "UUID of an existing Juju model. Only used when create_model = false."
  type        = string
  default     = ""
}

# ---------------------------------------------------------------------------
# Mail domain
# ---------------------------------------------------------------------------

variable "domain" {
  description = "Primary mail domain (e.g. mail.example.com). Sets relay_domains, mailname, and postmaster address."
  type        = string
}

variable "transport_maps" {
  description = <<-EOT
    Postfix transport_maps: domain -> LMTP destination.
    Example: { "mail.example.com" = "lmtp:inet:10.10.0.5:24" }

    NOTE: Leave empty on first apply. After dovecot is active run:
      juju status --model mailserver --format json | \
        jq -r '.applications.dovecot.units[].["public-address"]'
    then set this variable to the discovered IP and re-apply.
  EOT
  type        = map(string)
  default     = {}
}

# ---------------------------------------------------------------------------
# Charm sources
# Pass a local path (e.g. "../../dovecot-charm/dovecot_amd64.charm") to use
# a locally built charm, or leave the default to pull from Charmhub.
# ---------------------------------------------------------------------------

variable "dovecot_charm" {
  description = "Charm name or path to a local .charm file for dovecot."
  type        = string
  default     = "dovecot"
}

variable "dovecot_channel" {
  description = "Charmhub channel for dovecot (ignored for local charm paths)."
  type        = string
  default     = "2.3/edge"
}

variable "postfix_relay_charm" {
  description = "Charm name or path to a local .charm file for postfix-relay."
  type        = string
  default     = "postfix-relay"
}

variable "postfix_relay_channel" {
  description = "Charmhub channel for postfix-relay (ignored for local charm paths)."
  type        = string
  default     = "latest/edge"
}

variable "opendkim_charm" {
  description = "Charm name or path to a local .charm file for opendkim."
  type        = string
  default     = "opendkim"
}

variable "opendkim_channel" {
  description = "Charmhub channel for opendkim (ignored for local charm paths)."
  type        = string
  default     = "2/edge"
}

variable "postfix_relay_configurator_charm" {
  description = "Charm name or path to a local .charm file for postfix-relay-configurator."
  type        = string
  default     = "postfix-relay-configurator"
}

variable "postfix_relay_configurator_channel" {
  description = "Charmhub channel for postfix-relay-configurator (ignored for local charm paths)."
  type        = string
  default     = "latest/edge"
}
