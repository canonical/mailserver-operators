# Mail server operators

This repository contains a collection of operators for deploying and
managing mail services in the Juju ecosystem. Its goal is to provide
building blocks for operating mail servers with Juju.

## Repository layout

```
dovecot-charm/                       # Juju charm: dovecot IMAP/POP3 mail server source
opendkim-operator/                   # Juju charm: opendkim DKIM signing/verification source
postfix-relay-operator/              # Juju charm: postfix-relay SMTP relay source
postfix-relay-configurator-operator/ # Juju charm: postfix-relay-configurator subordinate source

opendkim-snap/                       # Snap: opendkim workload

terraform/                           # Terraform Juju modules for the charms above

docs/                                # Product documentation

tests/                               # Shared integration tests
```

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

## License

The mail server operators are free software, distributed under the
Apache Software License, version 2.0. See [LICENSE](LICENSE) for more
details.
