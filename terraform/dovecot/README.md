# Dovecot Terraform product

This CC008 product deploys Dovecot into a Juju machine model with encrypted mail storage and TLS.
It creates the LUKS secret, grants it to Dovecot, and deploys `self-signed-certificates` by default.

See the repository's [product installation guide](../INSTALL.md) for prerequisites, secure
configuration, deployment, and verification.

```hcl
module "dovecot" {
  source = "./terraform/dovecot"

  juju_controller = {
    endpoint = var.juju_endpoint
    username = var.juju_username
    password = var.juju_password
    ca       = var.juju_ca
  }

  model_cloud       = { name = "maas-prod" }
  mail_domain       = "mail.example.com"
  postmaster_address = "postmaster@mail.example.com"
  luks_key           = var.mail_luks_key
}
```

Replace the default TLS provider with an in-model endpoint:

```hcl
tls = {
  kind     = "endpoint"
  name     = "corporate-ca"
  endpoint = "certificates"
}
```

or a cross-model offer:

```hcl
tls = {
  kind = "offer"
  url  = "admin/certificates.certificates"
}
```

The module defaults to Dovecot `2.3/edge` and 8 GiB of `mail-data` storage. Use a machine cloud
with block storage for staging; Juju LXD loop storage is suitable only where the controller
correctly resolves unit storage attachments. Pin charm revisions for reproducible deployments.
`model_cloud` is required so Juju cannot accidentally create the model on a Kubernetes cloud.

For a centrally managed deployment, set `create_model = false` and pass `model_uuid` instead of
`model_cloud`. The product then deploys into that model and does not create or own it.
`juju_controller` accepts either `username`/`password` or JAAS `client_id`/`client_secret`
credentials.
TLS offers must be hosted on the configured controller.

Outputs follow the CC008 product contract: `metadata`, `models`, `provides`, and `requires`.
The LUKS passphrase and controller credentials remain sensitive Terraform state values.
