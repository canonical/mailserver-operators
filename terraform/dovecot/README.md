# Dovecot Terraform product

This Terraform product deploys Dovecot into a Juju machine model with encrypted mail storage and TLS.
It creates the LUKS secret, grants it to Dovecot, and deploys `self-signed-certificates` by default.
It also grants Dovecot access to an existing mail-user secret and configures the charm to use it.

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

  model_uuid         = var.model_uuid
  mail_domain       = "mail.example.com"
  postmaster_address = "postmaster@mail.example.com"
  luks_key           = var.mail_luks_key
  mail_users_secret_uri = var.mail_users_secret_uri
  risk               = "edge"
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

The module defaults to Dovecot `2.3/edge` and 8 GiB of `mail-data` storage. The supplied
`model_uuid` must identify an existing machine model with block storage; Juju LXD loop storage is
suitable only where the controller correctly resolves unit storage attachments. The product does
not create or own the model. Pin charm revisions for reproducible deployments.
`juju_controller` accepts either `username`/`password` or JAAS `client_id`/`client_secret`
credentials.
TLS offers must be hosted on the configured controller.

Outputs follow the product contract: `metadata`, `models`, `provides`, and `requires`.
Create the mail-user secret in the deployment model before applying Terraform. Its `users` field
must contain a non-empty YAML list of `username:password-hash` entries with supported crypt hashes.
Pass its URI through the required `mail_users_secret_uri` input. The product manages the access
grant, not the secret or its contents; update credentials separately through Juju or your secret
management process. The product's input takes precedence over `dovecot.config["mail-users"]`.

The LUKS passphrase and controller credentials remain sensitive Terraform state values.
Mail-user credential contents are not read into Terraform state by this product.
