# Dovecot charm

A [Juju](https://juju.is/) charm that deploys and manages [Dovecot](https://www.dovecot.org/) as an IMAP/POP3 mail server on Ubuntu VMs. Intended for Canonical IS team use.

Like any Juju charm, this charm supports one-line deployment, configuration, integration, scaling, and more. For the Dovecot charm, this includes:

* Multi-protocol mail server: IMAP, IMAPS, POP3, POP3S, Sieve, and LMTP
* TLS/SSL encryption with configurable cipher suites
* Mail filtering with Sieve and Procmail
* Multi-unit deployments with peer-relation-based mail synchronisation
* Scheduled mail syncing between primary and secondary units using cron
* Postfix mail queue management using the `clear-queue` action

For information about how to deploy, integrate, and manage this charm, see the [Dovecot charm documentation](https://github.com/canonical/mailserver-operators/tree/main/docs).

## Get started

See the [basic deployment tutorial](https://github.com/canonical/mailserver-operators/blob/main/docs/tutorial/basic-deployment.rst) for a step-by-step walkthrough.

### Deploy

```bash
juju deploy dovecot \
  --config mailname=mail.example.com \
  --config postmaster-address=postmaster@example.com \
  --config primary-unit=dovecot/0
```

### Basic operations

**Clear stuck mail from the Postfix queue:**

```bash
# Clear only deferred messages (default)
juju run dovecot/0 clear-queue

# Clear all queued messages
juju run dovecot/0 clear-queue queue=all
```

**Adjust the mail sync schedule** (default: every 30 minutes):

```bash
juju config dovecot sync-schedule="*/15 * * * *"
```

See [`charmcraft.yaml`](dovecot-charm/charmcraft.yaml) for all available configuration options.

## Integrations

The charm uses a **`replicas`** peer relation to synchronise mail between units in a multi-unit deployment. The primary unit is designated with the `primary-unit` configuration option.

## Learn more

* [Dovecot charm documentation](https://github.com/canonical/mailserver-operators/tree/main/docs)
* [Dovecot upstream documentation](https://doc.dovecot.org/)
* [Dovecot official webpage](https://www.dovecot.org/)
* [Troubleshooting](https://github.com/canonical/mailserver-operators/blob/main/docs/how-to/troubleshoot.rst)

## Project and community

* [Issues](https://github.com/canonical/mailserver-operators/issues)
* [Contributing](CONTRIBUTING.md)
* [Matrix](https://matrix.to/#/#charmhub-charmdev:ubuntu.com)

## License

The Dovecot charm is free software, distributed under the Apache Software License, version 2.0. See [LICENSE](LICENSE) for more details.
