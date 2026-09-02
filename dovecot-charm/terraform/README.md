# dovecot Terraform module

This module deploys the `dovecot` charm on a machine substrate.

## What it does

- Deploys `dovecot` from Charmhub
- Uses `ubuntu@24.04`
- Defaults to the currently published `2.3/edge` channel
- Deploys one unit by default
- Sets machine constraints to `arch=amd64 root-disk=20G`
- Applies `mail-data = 8G` storage by default

The Juju provider is inherited from the caller; this module does not configure a provider block.
It requires Terraform `>= 1.12, < 2.0` and Juju provider `> 1.0.0, < 2.0.0`.

## Required charm inputs

The charm expects these config values for a working deployment:

- `mailname`
- `postmaster-address`
- `primary-unit`

For encrypted mail storage:

- set `luks-auto-provisioning = true`
- pass `luks-key` as a Juju secret ID
- the secret must contain a `key` field

For TLS:

- integrate the `certificates` relation

For storage:

- `mail-data` storage is declared by the charm
- this module defaults it to `8G`

## Inputs

- `app_name` - application name, defaults to `dovecot`
- `base` - charm base, defaults to `ubuntu@24.04`
- `channel` - charm channel, defaults to `2.3/edge`
- `config` - charm config map
- `constraints` - Juju constraints; defaults to amd64 with a 20 GiB root disk
- `endpoint_bindings` - optional endpoint bindings
- `expose` - optional Juju exposure restricted by CIDRs, endpoints, or spaces
- `machines` - optional machine IDs for placement
- `model_uuid` - required Juju model UUID
- `resources` - charm resources
- `revision` - optional charm revision
- `storage_directives` - storage directives, defaults to `{ "mail-data" = "8G" }`
- `units` - number of units, defaults to `1`

## Outputs

- `application` - full `juju_application` object
- `app_name` - deprecated application name
- `provides.cos-agent` - `{ kind, name, endpoint }`
- `requires.certificates` - `{ kind, name, endpoint }`

## Example

```hcl
data "juju_model" "this" {
  name = "mail"
}

module "dovecot" {
  source = "./terraform"

  model_uuid = data.juju_model.this.uuid

  config = {
    "mailname"              = "mail.example.com"
    "postmaster-address"    = "postmaster@example.com"
    "primary-unit"          = "dovecot/0"
    "luks-auto-provisioning" = true
    "luks-key"              = "<secret-id>"
  }

  endpoint_bindings = toset([
    {
      endpoint = "certificates"
      space    = "internal"
    }
  ])
}

resource "juju_integration" "dovecot_certificates" {
  model_uuid = data.juju_model.this.uuid

  application {
    name     = module.dovecot.application.name
    endpoint = module.dovecot.requires.certificates.endpoint
  }

  application {
    name     = "tls-certificates"
    endpoint = "certificates"
  }
}
```
