variable "approle_role_id" {
  description = "Vault AppRole role ID."
  type        = string
  sensitive   = true

  validation {
    condition     = length(trimspace(var.approle_role_id)) > 0
    error_message = "Set TF_VAR_approle_role_id from Vault."
  }
}

variable "approle_secret_id" {
  description = "Vault AppRole secret ID."
  type        = string
  sensitive   = true

  validation {
    condition     = length(trimspace(var.approle_secret_id)) > 0
    error_message = "Set TF_VAR_approle_secret_id from Vault."
  }
}

variable "juju_model_uuid" {
  description = "UUID of the existing PS7 staging machine model."
  type        = string
}

variable "luks_key" {
  description = "Temporary local passphrase for Dovecot encrypted mail storage."
  type        = string
  sensitive   = true

  validation {
    condition     = length(trimspace(var.luks_key)) > 0
    error_message = "luks_key must not be empty."
  }
}

variable "dkim_private_key" {
  description = "Temporary local OpenDKIM private key."
  type        = string
  sensitive   = true

  validation {
    condition     = length(trimspace(var.dkim_private_key)) > 0
    error_message = "dkim_private_key must not be empty."
  }
}

variable "mail_domain" {
  description = "Mail domain served by the deployment."
  type        = string
}

variable "postmaster_address" {
  description = "Postmaster address configured on Dovecot."
  type        = string
}

variable "dovecot_relay_host" {
  description = "Stable DNS name or address used by Postfix to reach Dovecot."
  type        = string
}

variable "dovecot_backend_address" {
  description = "Dovecot unit address routed by ingress-configurator."
  type        = string
  default     = ""
}

variable "dovecot_machine_id" {
  description = "Existing Dovecot machine on which to colocate ingress-configurator."
  type        = string
  default     = ""
}

variable "dovecot_primary_unit" {
  description = "Discovered Dovecot primary unit name."
  type        = string
  default     = "dovecot/0"
}

variable "dovecot_storage" {
  description = "Juju block-storage directive for Dovecot mail-data."
  type        = string
  default     = "8G"
}

variable "haproxy_route_tcp_offer_url" {
  description = "Same-controller PS7 HAProxy TCP route offer URL."
  type        = string

  validation {
    condition     = length(trimspace(var.haproxy_route_tcp_offer_url)) > 0
    error_message = "haproxy_route_tcp_offer_url must not be empty."
  }
}

variable "imaps_frontend_port" {
  description = "Temporary HAProxy frontend port routed to Dovecot IMAPS."
  type        = number
  default     = 993

  validation {
    condition     = var.imaps_frontend_port >= 1 && var.imaps_frontend_port <= 65535
    error_message = "imaps_frontend_port must be a valid TCP port."
  }
}

variable "postfix_backend_address" {
  description = "Postfix unit address routed by ingress-configurator."
  type        = string
  default     = ""
}

variable "postfix_machine_id" {
  description = "Existing Postfix machine on which to colocate ingress-configurator."
  type        = string
  default     = ""
}

variable "smtp_auth_users" {
  description = "Postfix SMTP users as username:crypt-hash values."
  type        = list(string)
  default     = []
  sensitive   = true
}

variable "smtp_frontend_port" {
  description = "Temporary HAProxy frontend port routed to Postfix SMTP."
  type        = number
  default     = 587

  validation {
    condition = (
      var.smtp_frontend_port >= 1
      && var.smtp_frontend_port <= 65535
      && var.smtp_frontend_port != var.imaps_frontend_port
    )
    error_message = "smtp_frontend_port must be valid and differ from imaps_frontend_port."
  }
}
