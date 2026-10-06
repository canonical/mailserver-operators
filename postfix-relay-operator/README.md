[![Charmhub badge](https://charmhub.io/postfix-relay/badge.svg)](https://charmhub.io/postfix-relay)

# Postfix relay charm

[Postfix](https://www.postfix.org/) is a widely used mail transfer
agent. This charm installs Postfix and configures it as an SMTP relay,
allowing specific users, hosts, or networks to send mail through it.

This [Juju](https://juju.is/) charm handles one-line deployment,
configuration, integration, and scaling for Postfix relay, including:

* Relaying mail for configured domains, hosts, and networks
* SMTP authentication and sender restrictions
* Virtual aliases, transport maps, and header checks
* Configurable TLS policies, protocols, and cipher suites
* Connection, message size, and rate limits
* Integration with mail filters and Canonical Observability Stack

For information about how to deploy, integrate, and manage this charm,
see the official
[Postfix relay documentation](https://charmhub.io/postfix-relay/docs).

## Get started

See the
[getting started tutorial](docs/tutorial/getting-started.md)
for prerequisites and a complete walkthrough.

### Deploy

Deploy the charm with at least one destination domain:

```bash
juju deploy postfix-relay --config 'relay_domains=[example.com]'
```

Run `juju status` to monitor the deployment.

### Basic operations

Update the domains for which the server relays mail:

```bash
juju config postfix-relay 'relay_domains=[example.com, example.net]'
```

See the
[configuration reference](https://charmhub.io/postfix-relay/configurations)
for SMTP authentication, relay restrictions, TLS, rate limits, and
other available options.

## Integrations

The charm supports the following integrations:

* `milter` connects mail filters such as the OpenDKIM charm.
* `certificates` supplies TLS certificates.
* `cos-agent` provides logs and metrics to Canonical Observability
  Stack.
* `metrics` exposes Postfix metrics.

See the
[integration documentation](https://charmhub.io/postfix-relay/integrations)
for endpoint details and supported charms.

## Learn more

* [Postfix relay documentation](https://charmhub.io/postfix-relay/docs)
* [Postfix documentation](https://www.postfix.org/documentation.html)
* [Postfix official website](https://www.postfix.org/)
* [Troubleshooting and support](https://matrix.to/#/#charmhub-charmdev:ubuntu.com)

## Project and community

* [Issues](https://github.com/canonical/mailserver-operators/issues)
* [Contributing](../CONTRIBUTING.md)
* [Matrix](https://matrix.to/#/#charmhub-charmdev:ubuntu.com)
* [Launchpad](https://launchpad.net/~canonical-is-devops)

## Licensing and trademark

The Postfix relay charm is free software, distributed under the Apache
Software License, version 2.0. See the [license](../LICENSE) for more
information.
