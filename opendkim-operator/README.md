[![Charmhub badge](https://charmhub.io/opendkim/badge.svg)](https://charmhub.io/opendkim)

# OpenDKIM charm

[OpenDKIM](http://www.opendkim.org/) is an open-source milter that
signs outgoing email and verifies incoming signatures using DomainKeys
Identified Mail (DKIM), helping mail servers authenticate the origin
of messages and guard against spoofing.

This [Juju](https://juju.is/) charm deploys and manages OpenDKIM on
Ubuntu machines, and provides:

* DKIM signing and verification modes
* Signing and key table management
* Private key storage through Juju secrets
* Configurable trusted hosts and networks
* Integration with mail transfer agents through the milter protocol
* Metrics and alert rules for Canonical Observability Stack

For information about how to deploy, integrate, and manage this charm,
see the official
[OpenDKIM documentation](https://charmhub.io/opendkim/docs).

## Get started

Deploy the charm:

```bash
juju deploy opendkim
```

Configure `signingtable`, `keytable`, and `private-keys` before using
the charm for DKIM signing. The `private-keys` option requires a Juju
secret containing the private key files.

See the
[configuration reference](https://charmhub.io/opendkim/configurations)
for configuration formats and examples.

### Basic operations

Integrate OpenDKIM with the Postfix relay charm:

```bash
juju integrate opendkim postfix-relay
```

Use the `mode` option to enable signing, verification, or both:

```bash
juju config opendkim mode=sv
```

## Integrations

The charm provides these integrations:

* `milter` connects OpenDKIM to a mail transfer agent such as the
  Postfix relay charm.
* `cos-agent` provides logs, metrics, and alert rules to Canonical
  Observability Stack.

See the
[integration documentation](https://charmhub.io/opendkim/integrations)
for endpoint details and supported charms.

## Learn more

* [OpenDKIM documentation](https://charmhub.io/opendkim/docs)
* [OpenDKIM configuration reference](http://www.opendkim.org/opendkim.conf.5.html)
* [OpenDKIM official website](http://www.opendkim.org/)
* [Troubleshooting and support](https://matrix.to/#/#charmhub-charmdev:ubuntu.com)

## Project and community

* [Issues](https://github.com/canonical/mailserver-operators/issues)
* [Contributing](../CONTRIBUTING.md)
* [Matrix](https://matrix.to/#/#charmhub-charmdev:ubuntu.com)
* [Launchpad](https://launchpad.net/~canonical-is-devops)

## Licensing and trademark

The OpenDKIM charm is free software, distributed under the Apache
Software License, version 2.0. See the [license](../LICENSE) for more
information.
