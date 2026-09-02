# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

# OpenDKIM Terraform module

This module deploys the `opendkim` charm on **machines**.

It inherits the Juju provider from its caller and requires Terraform `>= 1.12, < 2.0` and Juju
provider `> 1.0.0, < 2.0.0`.

## Prerequisites

- A machine-backed Juju model with Ubuntu 24.04 AMD64 capacity.
- A `milter` relation.
- Valid `signingtable` and `keytable` configuration.
- A granted Juju secret referenced by `private-keys`. Keep the private key in an encrypted,
  access-controlled Terraform state backend.

The charm has no storage or OCI image resources.

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `app_name` | `string` | `opendkim` | Application name. |
| `base` | `string` | `ubuntu@24.04` | Charm base. |
| `channel` | `string` | `2/edge` | Charm channel. |
| `config` | `map(string)` | `{}` | Charm configuration. |
| `constraints` | `string` | `arch=amd64` | Juju constraints. |
| `endpoint_bindings` | endpoint binding set | `null` | Optional endpoint bindings. |
| `machines` | `set(string)` | `null` | Optional target machine IDs. |
| `model_uuid` | `string` | required | Juju model UUID. |
| `resources` | `map(string)` | `{}` | Charm resources. |
| `revision` | `number` | `null` | Charm revision. |
| `units` | `number` | `1` | Unit count when `machines` is unset. |

## Outputs

| Name | Description |
|---|---|
| `application` | Full `juju_application` object. |
| `app_name` | Deprecated application name. |
| `provides` | Structured `milter` and `cos-agent` endpoint objects. |

## Example

```hcl
module "opendkim" {
  source = "./opendkim-operator/terraform"

  model_uuid = juju_model.mail.uuid
  config = {
    keytable     = jsonencode([["default._domainkey.example.com", "example.com:default:/etc/dkimkeys/default.private"]])
    signingtable = jsonencode([["*@example.com", "default._domainkey.example.com"]])
    private-keys = "secret:<secret-id>"
  }
}

resource "juju_integration" "postfix_opendkim" {
  model_uuid = juju_model.mail.uuid

  application {
    name     = module.opendkim.provides.milter.name
    endpoint = module.opendkim.provides.milter.endpoint
  }

  application {
    name     = module.postfix_relay.requires.milter.name
    endpoint = module.postfix_relay.requires.milter.endpoint
  }
}
```
