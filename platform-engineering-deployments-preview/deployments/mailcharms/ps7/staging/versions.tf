terraform {
  required_version = ">= 1.12, < 2.0"

  required_providers {
    juju = {
      source  = "juju/juju"
      version = "> 1.0.0, < 2.0.0"
    }
    vault = {
      source  = "hashicorp/vault"
      version = ">= 5.6.0"
    }
  }
}
