# Postfix relay Terraform module

This module deploys the `postfix-relay` principal machine charm on Juju.

It inherits the Juju provider from its caller and requires Terraform `>= 1.12, < 2.0` and Juju
provider `> 1.0.0, < 2.0.0`. The target model must provide Ubuntu 24.04 AMD64 machine capacity.

## Files

- `main.tf` - Juju application definition.
- `variables.tf` - Module inputs.
- `outputs.tf` - Module outputs for integrations and consumers.
- `terraform.tf` - Terraform and provider version requirements.
- `providers.tf` - Notes that the Juju provider is inherited from the caller.

## Inputs

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `app_name` | `string` | `postfix-relay` | Application name in the model. |
| `base` | `string` | `ubuntu@24.04` | Base for the machine charm. |
| `channel` | `string` | `3/stable` | Charm channel. |
| `config` | `map(string)` | `{}` | Charm configuration. |
| `constraints` | `string` | `arch=amd64` | Juju constraints. |
| `endpoint_bindings` | `set(object({ endpoint = optional(string), space = string }))` | `[]` | Endpoint bindings. |
| `expose` | `object({ cidrs = optional(string), endpoints = optional(string), spaces = optional(string) })` | `null` | Optional restricted Juju exposure. |
| `machines` | `set(string)` | `[]` | Target machine IDs for units. |
| `model_uuid` | `string` | required | Juju model UUID. |
| `resources` | `map(string)` | `{}` | Charm resources. |
| `revision` | `number` | `null` | Charm revision. |
| `storage_directives` | `map(string)` | `{}` | Storage directives. |
| `storage` | `map(string)` | `{}` | Deprecated storage directives input. |
| `units` | `number` | `1` | Number of units. |

## Outputs

| Name | Type | Description |
| --- | --- | --- |
| `application` | object | Full Juju application resource. |
| `app_name` | string | Deprecated application name output. |
| `provides` | object | Structured endpoint references for `metrics` and `cos-agent`. |
| `requires` | object | Legacy endpoint names retained for compatibility. |
| `requires_endpoints` | object | Structured endpoint references for `milter` and `certificates`. |

## Example

```hcl
module "postfix_relay" {
  source = "./terraform"

  app_name  = "postfix-relay"
  model_uuid = juju_model.model.uuid

  endpoint_bindings = [
    {
      space    = "dmz"
      endpoint = "milter"
    }
  ]

  machines = ["0"]
  resources = {}
  storage_directives = {}
}
```

Integrations consume the structured endpoint outputs:

```hcl
resource "juju_integration" "postfix_opendkim" {
  model_uuid = juju_model.mail.uuid

  application {
    name     = module.postfix_relay.requires_endpoints.milter.name
    endpoint = module.postfix_relay.requires_endpoints.milter.endpoint
  }

  application {
    name     = module.opendkim.provides.milter.name
    endpoint = module.opendkim.provides.milter.endpoint
  }
}
```
