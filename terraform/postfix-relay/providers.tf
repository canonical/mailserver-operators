# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

provider "juju" {
  ca_certificate       = var.juju_controller.ca
  client_id            = var.juju_controller.client_id
  client_secret        = var.juju_controller.client_secret
  controller_addresses = var.juju_controller.endpoint
  password             = var.juju_controller.password
  username             = var.juju_controller.username
}
