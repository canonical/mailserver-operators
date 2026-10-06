[![Charmhub badge](https://charmhub.io/postfix-relay-configurator/badge.svg)](https://charmhub.io/postfix-relay-configurator)

# Postfix relay configuration charm

The [Postfix relay](https://charmhub.io/postfix-relay) charm accepts
configuration options for common use cases, but some deployments need
access, alias, restriction, or transport maps beyond what it exposes
directly.

This subordinate [Juju](https://juju.is/) charm manages that additional
configuration and applies it to every related Postfix relay unit,
including:

* Relay access rules based on source networks
* Recipient and sender restrictions
* Sender login maps
* Transport and virtual alias maps
* Configuration shared with every related Postfix relay unit

For information about how to deploy, integrate, and manage this charm,
see the official
[Postfix relay configuration documentation](https://charmhub.io/postfix-relay-configurator/docs).

## Get started

Deploy the Postfix relay and configuration charms, then integrate them:

```bash
juju deploy postfix-relay --config 'relay_domains=[example.com]'
juju deploy postfix-relay-configurator
juju integrate postfix-relay-configurator postfix-relay
```

Run `juju status` to monitor the deployment.

### Basic operations

Use `juju config` to manage relay access, recipient restrictions,
sender restrictions, and mail routing maps:

```bash
juju config postfix-relay-configurator
```

See the
[configuration reference](https://charmhub.io/postfix-relay-configurator/configurations)
for the available options and their expected YAML formats.

## Integrations

The charm uses the `juju-info` subordinate relation to install its
configuration on every related Postfix relay unit.

See the
[integration documentation](https://charmhub.io/postfix-relay-configurator/integrations)
for endpoint details.

## Learn more

* [Postfix relay configuration documentation](https://charmhub.io/postfix-relay-configurator/docs)
* [Postfix documentation](https://www.postfix.org/documentation.html)
* [Postfix official website](https://www.postfix.org/)
* [Troubleshooting and support](https://matrix.to/#/#charmhub-charmdev:ubuntu.com)

## Project and community

* [Issues](https://github.com/canonical/mailserver-operators/issues)
* [Contributing](../CONTRIBUTING.md)
* [Matrix](https://matrix.to/#/#charmhub-charmdev:ubuntu.com)

## Licensing and trademark

The Postfix relay configuration charm is free software, distributed
under the Apache Software License, version 2.0. See the
[license](../LICENSE) for more information.
