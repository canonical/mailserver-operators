# Terraform products

This repository contains two independent CC008 product modules:

| Product | Path | Components |
|---|---|---|
| Postfix Relay | [`postfix-relay/`](postfix-relay/) | Postfix Relay and OpenDKIM |
| Dovecot | [`dovecot/`](dovecot/) | Dovecot and a default TLS provider |

Each product owns its Juju model, secrets, supported integrations, and CC008-compatible outputs.
The charm modules remain beside their charms under `<charm>/terraform/`.

See [Installing the Terraform products](INSTALL.md) for a complete deployment procedure.

The products intentionally do not form a single mailserver module. Postfix Relay and Dovecot do
not currently have a first-class relation for mailbox-backend discovery. Consumers that deploy
both products must configure routing explicitly until that charm integration exists.
