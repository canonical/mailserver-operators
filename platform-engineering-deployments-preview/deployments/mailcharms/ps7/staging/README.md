# Mail charms PS7 staging deployment preview

This untracked preview mirrors
`deployments/haproxy/ps7/staging` in `canonical/platform-engineering-deployments`.
It consumes the two CC008 product modules and deploys Dovecot plus the Postfix
Relay/OpenDKIM pair into an existing JAAS machine model.

Before moving it to the deployment repository:

1. Replace the temporary local backend with the managed S3 backend.
2. Replace the relative product sources with immutable Git sources and release tags.
3. Set the real model UUID, mail domain, and Dovecot service address.
4. Move the temporary local mail secrets to Vault after validation succeeds.
5. Replace edge revisions only after the selected revisions pass staging tests.
6. Preserve the standard `../../../Justfile.ps7` symlink when moving the directory.

For local validation from the mailserver-operators repository:

```bash
terraform init -backend=false
terraform fmt -check
terraform validate
```

## Deploy through JAAS

No SSH access is required. Terraform talks to JAAS, and acceptance tests use
`juju run` and `juju exec`.

This staging preview deploys `self-signed-certificates` in the mail model and
relates it to Dovecot. Replace it with a production certificate provider such
as LEGO after functional validation.

Two `ingress-configurator` applications consume the PS7
`haproxy-route-tcp` offer in integrator mode:

- HAProxy `993` routes to Dovecot `993` with TLS passthrough.
- HAProxy `587` routes to Postfix `25` as raw TCP for temporary client testing.

Both routes use
`ingress-ps7-is-charms-stg.dynamic.admin.canonical.com`, the frontend address
managed by the PS7 infrastructure definition.

The second route does not turn Postfix into a full RFC submission service:
SMTP authentication and STARTTLS on the backend remain separate production
work.

Both configurators are colocated on their backend machines to avoid consuming
additional VM quota. OpenDKIM is similarly colocated on the Postfix machine.

Dovecot and Postfix are exposed only to private `10.0.0.0/8` sources so the
cross-model HAProxy units can reach their backend ports. Public clients still
connect exclusively through the managed HAProxy frontend.

1. Replace placeholders in `.env`.
2. Run:

   ```bash
   just vault-login
   just juju-login
   just preflight
   just deploy
   just watch
   just ingress-status
   ```

3. Stop the watch with `Ctrl-C`, then run:

   ```bash
   just test
   ```

Use `just plan-destroy` followed by `just destroy` to remove the product
resources. The existing JAAS model is not owned or destroyed by this state.

`just deploy` creates persistent temporary LUKS and DKIM secrets under
`.mail-secrets/` with owner-only permissions. Keep that directory until
destroying the deployment: changing the LUKS key can make existing mail storage
unavailable. The directory is ignored by Git and is intended only for this
validation phase.

Terraform state is also stored locally under `.terraform-state/` because the
PS7 RADOSGW endpoint is not reachable from the validation workstation. Keep
this directory until the deployment is destroyed. Restore the managed S3
backend before adopting this configuration for normal operations.

Postfix-to-Dovecot discovery is not relation-backed. `dovecot_relay_host` must
therefore be stable DNS or another durable service address, not a replaceable
unit IP.
