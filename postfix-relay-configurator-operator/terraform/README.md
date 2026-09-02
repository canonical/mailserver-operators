# Terraform modules

This project contains the [Terraform][Terraform] modules to deploy the 
`postfix-relay-configurator` subordinate machine charm.

The module uses the [Terraform Juju provider][Terraform Juju provider] to model
the deployment onto any Juju-managed environment.

It inherits provider configuration from its caller and requires Terraform `>= 1.12, < 2.0` and
Juju provider `> 1.0.0, < 2.0.0`. The charm is subordinate: the module creates no units and it
becomes deployed on the principal machine through its `juju-info` integration. Deprecated
constraint and storage inputs remain available for backward compatibility. The module handles no
secrets.

## Module structure

- **main.tf** - Defines the Juju application to be deployed.
- **variables.tf** - Allows customization of the deployment including Juju model UUID, channel, bindings, resources, and configuration.
- **outputs.tf** - Exposes the deployed application and its `juju-info` required relation.
- **terraform.tf** - Defines Terraform and provider version constraints.

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `app_name` | `string` | `postfix-relay-configurator` | Application name. |
| `base` | `string` | `ubuntu@24.04` | Charm base. |
| `channel` | `string` | `latest/stable` | Charm channel. |
| `config` | `map(string)` | `{}` | Charm configuration. |
| `constraints` | `string` | `arch=amd64` | Deprecated Juju constraints retained for compatibility. |
| `endpoint_bindings` | endpoint binding set | `[]` | Endpoint bindings. |
| `model_uuid` | `string` | required | Juju model UUID. |
| `resources` | `map(string)` | `{}` | Charm resources. |
| `revision` | `number` | `null` | Charm revision. |
| `storage` | `map(string)` | `{}` | Deprecated storage directives retained for compatibility. |

## Outputs

| Name | Description |
|---|---|
| `application` | Full `juju_application` object. |
| `app_name` | Deprecated application name. |
| `requires` | Structured `juju-info` endpoint object. |

## Relation usage

The module exposes the subordinate charm's required relation:

```hcl
resource "juju_integration" "postfix_relay_configurator" {
  model_uuid = juju_model.mailserver.uuid

  application {
    name     = module.postfix_relay.application.name
    endpoint = "juju-info"
  }

  application {
    name     = module.postfix_relay_configurator.application.name
    endpoint = module.postfix_relay_configurator.requires["juju-info"].endpoint
  }
}
```

[Terraform]: https://www.terraform.io/
[Terraform Juju provider]: https://registry.terraform.io/providers/juju/juju/latest
[Juju]: https://juju.is
