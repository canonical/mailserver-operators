# Mailserver stack Terraform module

This module deploys the machine charms used by the integration e2e topology:

- `dovecot`
- `postfix-relay`
- `opendkim`
- `postfix-relay-configurator`
- `self-signed-certificates`

The module also creates the required relations:

- `dovecot:certificates` <-> `self-signed-certificates:certificates`
- `postfix-relay:certificates` <-> `self-signed-certificates:certificates`
- `postfix-relay:milter` <-> `opendkim:milter`
- `postfix-relay:juju-info` <-> `postfix-relay-configurator:juju-info`

## Notes

- This module models deployment, baseline config, and integrations.
- Runtime e2e setup steps (for example DKIM secret generation, `grant-secret`, SMTP test users)
  remain test-time operations and are not managed by this module.

## Usage

```hcl
data "juju_model" "mail" {
  name = var.model_name
}

module "mailserver_stack" {
  source     = "git::https://github.com/canonical/mailserver-operators//terraform"
  model_uuid = data.juju_model.mail.uuid

  test_domain = "mailstack.internal"

  dovecot = {
    app_name = "dovecot"
    config = {
      mailname           = "mailstack.internal"
      postmaster-address = "postmaster@mailstack.internal"
      primary-unit       = "dovecot/0"
    }
  }

  transport_maps = {
    "mailstack.internal" = "lmtp:inet:10.1.2.3:24"
  }
}
```

## Inputs

- `model_uuid` (required): Juju model UUID.
- `test_domain`: default mail domain used for baseline charm config.
- `transport_maps`: map encoded and applied to postfix-relay-configurator.
- `self_signed_certificates`, `dovecot`, `postfix_relay`, `opendkim`,
  `postfix_relay_configurator`: per-application deployment options.

## Outputs

- `app_names`: deployed application names.
- `endpoints`: relation endpoint names for downstream composition.
