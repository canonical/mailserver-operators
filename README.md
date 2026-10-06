# Mail server operators

This repository contains a collection of operators for deploying and
managing mail services in the Juju ecosystem. Its goal is to provide
building blocks for operating mail servers with Juju.

This repository contains the source code for the following mail related
charms:

1. `dovecot`: A machine charm that deploys and manages Dovecot as an
   IMAP and POP3 mail server. See the
   [Dovecot README](dovecot-charm/README.md) for more information.
2. `opendkim`: A machine charm that deploys and manages OpenDKIM for
   signing and verifying email with DomainKeys Identified Mail (DKIM).
   See the [OpenDKIM README](opendkim-operator/README.md) for more
   information.
3. `postfix-relay`: A machine charm that deploys and manages a Postfix
   SMTP relay server. See the
   [Postfix relay README](postfix-relay-operator/README.md) for more
   information.
4. `postfix-relay-configurator`: A subordinate charm that manages
   configuration for the Postfix relay charm. See the
   [Postfix relay configuration README](postfix-relay-configurator-operator/README.md)
   for more information.

The repository also holds the snapped workload used by the OpenDKIM
charm:

1. `opendkim`: A snap containing the OpenDKIM email signing and
   verification milter.

## Charmhub and Snapcraft

| Name                         | Listing                                        |
| ---------------------------- | ---------------------------------------------- |
| `dovecot`                    | https://charmhub.io/dovecot                    |
| `opendkim`                   | https://charmhub.io/opendkim                   |
| `postfix-relay`              | https://charmhub.io/postfix-relay              |
| `postfix-relay-configurator` | https://charmhub.io/postfix-relay-configurator |
| `opendkim`                   | https://snapcraft.io/opendkim                  |

## Documentation

Our documentation is stored in the [`docs`](docs) directory. It uses
the [Diátaxis](https://diataxis.fr/) approach to organise tutorials,
how-to guides, reference material, and explanations.

You may open a pull request with your documentation changes, or you can
[file a bug](https://github.com/canonical/mailserver-operators/issues)
to provide constructive feedback or suggestions.

GitHub runs automatic checks on the documentation to verify spelling,
links, and style guide compliance. You can run the same checks locally:

```bash
make docs-check
```

## Project and community

The mail server operators project is a member of the Ubuntu family. It
is an open source project that warmly welcomes community projects,
contributions, suggestions, fixes, and constructive feedback.

- [Code of conduct](https://ubuntu.com/community/code-of-conduct)
- [Get support](https://discourse.charmhub.io/)
- [Issues](https://github.com/canonical/mailserver-operators/issues)
- [Matrix](https://matrix.to/#/#charmhub-charmdev:ubuntu.com)
- [Contribute](https://github.com/canonical/mailserver-operators/blob/main/CONTRIBUTING.md)
