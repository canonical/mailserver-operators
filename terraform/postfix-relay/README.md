# Postfix Relay Terraform product

This CC008 product deploys Postfix Relay and OpenDKIM into a Juju machine model. It creates the
private-key secret, grants it to OpenDKIM, and integrates OpenDKIM with Postfix over `milter`.

See the repository's [product installation guide](../INSTALL.md) for prerequisites, secure
configuration, deployment, and verification.

```hcl
module "postfix_relay" {
  source = "./terraform/postfix-relay"

  juju_controller = {
    endpoint = var.juju_endpoint
    username = var.juju_username
    password = var.juju_password
    ca       = var.juju_ca
  }

  model_cloud      = { name = "maas-prod" }
  mail_domain      = "mail.example.com"
  dkim_private_key = file("default.private")
}
```

The module defaults to `latest/edge` for Postfix Relay and `2/edge` for OpenDKIM. Pin revisions for
reproducible deployments. Optional COS integration accepts an in-model endpoint or cross-model
offer. Postfix Relay COS integration is capability-gated because the currently published revision
does not expose `cos-agent`.
`model_cloud` is required and must identify a Juju machine cloud, not Kubernetes.

For a centrally managed deployment, set `create_model = false` and pass `model_uuid` instead of
`model_cloud`. The product then deploys into that model and does not create or own it.
`juju_controller` accepts either `username`/`password` or JAAS `client_id`/`client_secret`
credentials.

Outputs follow the CC008 product contract: `metadata`, `models`, `provides`, and `requires`.
`dkim` contains only non-sensitive DNS publication coordinates. Private keys and controller
credentials remain sensitive Terraform state values.

This product does not deploy Dovecot. There is no first-class Postfix Relay-to-Dovecot relation, so
mailbox-backend routing must be configured explicitly until the charms support that integration.
