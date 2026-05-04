# Postfix relay operator

A [Juju](https://juju.is/) [charm](https://documentation.ubuntu.com/juju/3.6/reference/charm/)
deploying and managing a SMTP relay server on bare metal. SMTP
is an Internet standard communication protocol for email transmission.

Features include (not limited to):
- set up base Postfix system
- relay through another MTA
- set up virtual aliases and transport maps
- restrict relaying per domain, sender, recipient, headers checks
- enable SPF subsystem
- set up authenticated submission service
- restrict sender address per user
- fine-tune TLS settings
- set up limits (rate, size, connections, ...)

For information about how to deploy, integrate, and manage this charm, see the Official [Postfix relay Operator Documentation](https://charmhub.io/postfix-relay/docs).

## In this documentation

| | |
|--|--|
|  [Tutorials](https://charmhub.io/postfix-relay/docs/tutorial-getting-started)</br>  Get started - a hands-on introduction to using the Postfix Relay operator for new users </br> |
| [How-to guides](https://charmhub.io/postfix-relay/docs/how-to-contribute) </br> Step-by-step guides covering key operations and common tasks | 
| [Reference](https://charmhub.io/postfix-relay/docs/reference-actions) </br> Technical information - specifications, APIs, architecture | 
[Explanation](https://charmhub.io/postfix-relay/docs/explanation-charm-architecture) </br> Concepts - discussion and clarification of key topics  |

## Contributing to this documentation

Documentation is an important part of this project, and we take the same open-source approach to the documentation as the code. As such, we welcome community contributions, suggestions and constructive feedback on our documentation. Our documentation is hosted on the [Charmhub forum](https://discourse.charmhub.io/tag/postfix-relay) to enable easy collaboration. Please use the "Help us improve this documentation" links on each documentation page to either directly change something you see that's wrong, ask a question, or make a suggestion about a potential change via the comments section.

If there's a particular area of documentation that you'd like to see that's missing, please [file a bug](https://github.com/canonical/postfix-relay-operators/issues).

## Project and community

The Postfix relay Operator is a member of the Ubuntu family. It's an open-source project that warmly welcomes community projects, contributions, suggestions, fixes, and constructive feedback.

- [Code of conduct](https://ubuntu.com/community/code-of-conduct)
- [Get support](https://discourse.charmhub.io/)
- [Join our online chat](https://matrix.to/#/#charmhub-charmdev:ubuntu.com)
- [Contribute](https://github.com/canonical/postfix-relay-operators/blob/main/postfix-relay-operator/CONTRIBUTING.md)

Thinking about using the Postfix relay Operator for your next project? [Get in touch](https://matrix.to/#/#charmhub-charmdev:ubuntu.com)!

# Contents 

1. [How-to](how-to)
   1. [Back up and restore](how-to/backup-restore.md)
   1. [Contribute](how-to/contribute.md)
   1. [Redeploy](how-to/redeploy.md)
   1. [Upgrade](how-to/upgrade.md)
1. [Reference](reference)
   1. [Actions](reference/actions.md)
   1. [Charm architecture](reference/charm-architecture.md)
   1. [Configurations](reference/configurations.md)
   1. [External access](reference/external_access.md)
1. [Explanation](explanation)
   1. [Security](explanation/security.md) 
1. [Tutorial](tutorial)
  1. [Deploy the Postfix relay charm for the first time](tutorial/getting-started.md)