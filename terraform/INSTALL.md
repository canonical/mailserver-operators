# Installing the Terraform products

This guide deploys the two CC008 products from this repository:

- **Dovecot**: Dovecot, encrypted block storage, and TLS.
- **Postfix Relay**: Postfix Relay, OpenDKIM, and their `milter` integration.

Each product creates and owns a separate Juju model. They can be installed independently. Deploying
both does not automatically route Postfix mail to Dovecot because the charms do not yet provide a
mailbox-backend relation.

## 1. Prepare the environment

Install:

- Terraform `>= 1.12, < 2.0`
- Juju with access to an existing controller
- `jq`
- OpenSSL

The Juju cloud must provide Ubuntu 24.04 AMD64 machines. Dovecot additionally requires block
storage; the default is an 8 GiB `mail-data` volume. Use real block storage for staging and
production. Confirm access before continuing:

```bash
terraform version
juju version
juju controllers
juju clouds
```

Identify the machine cloud on the target controller. Do not select a Kubernetes cloud: both
products deploy machine charms. The products require `model_cloud` explicitly to prevent Juju from
silently choosing a controller's default Kubernetes cloud.

Use a Juju account that can create models, applications, integrations, and secrets. Confirm the
correct controller is available:

```bash
juju show-controller <controller-name> --show-password
```

Treat that output as sensitive.

## 2. Generate the product secrets

Generate a DKIM key for Postfix Relay:

```bash
umask 077
openssl genpkey -algorithm RSA \
  -pkeyopt rsa_keygen_bits:2048 \
  -out default.private
openssl pkey -in default.private -pubout -out default.public
```

Generate a strong Dovecot LUKS passphrase:

```bash
openssl rand -base64 48
```

Store these values in an approved secret manager. Do not commit the private key, LUKS passphrase,
controller credentials, Terraform variable files, plan files, or state.
Both products reject empty secret values. Ensure the exported variables contain the generated
content rather than an empty path or an unset shell variable.

Before planning Postfix Relay, verify the private key variable is populated:

```bash
test -n "${TF_VAR_dkim_private_key:-}" ||
  { echo "TF_VAR_dkim_private_key is empty" >&2; exit 1; }
```

## 3. Get the product files

Clone a release or check out an immutable commit:

```bash
git clone https://github.com/canonical/mailserver-operators.git
cd mailserver-operators
git checkout <release-tag-or-commit>
```

If the repository is already checked out, run the remaining commands from its root. The complete
deployable products are already present in:

```text
terraform/dovecot/
terraform/postfix-relay/
```

Do not create additional Terraform files. Each directory is a root module with its provider,
variables, resources, outputs, and tests.

## 4. Supply variables securely

Use your CI/CD secret integration or secret manager where possible. For a manual deployment, build
the required `juju_controller` object directly from Juju's structured output:

```bash
export JUJU_CONTROLLER_NAME="<controller-name>"
printf 'Juju machine cloud: ' >&2
IFS= read -r JUJU_MACHINE_CLOUD

export TF_VAR_juju_controller="$(
  juju show-controller "$JUJU_CONTROLLER_NAME" --show-password --format json |
    jq -c '
      to_entries[0].value |
      {
        ca: .details["ca-cert"],
        endpoint: .details["api-endpoints"][0],
        password: .account.password,
        username: .account.user
      }
    '
)"
export TF_VAR_mail_domain="mail.example.com"
export TF_VAR_model_cloud="$(
  jq -cn --arg name "$JUJU_MACHINE_CLOUD" '{name:$name}'
)"
export TF_VAR_dkim_private_key="$(cat /secure/path/default.private)"
export TF_VAR_postmaster_address="postmaster@$TF_VAR_mail_domain"

umask 077
test -s terraform/dovecot/luks-key.secret ||
  openssl rand -base64 48 >terraform/dovecot/luks-key.secret
export TF_VAR_luks_key="$(
  cat terraform/dovecot/luks-key.secret
)"
unset JUJU_MACHINE_CLOUD
```

Verify the required fields before planning without printing their sensitive values:

```bash
jq -e '
  .ca != "" and .endpoint != "" and .password != "" and .username != ""
' <<<"$TF_VAR_juju_controller" >/dev/null
test -n "${TF_VAR_luks_key:-}" || {
  echo "TF_VAR_luks_key is empty" >&2
  exit 1
}
```

If the target controller runs inside `new-dev`, execute these commands and Terraform from inside
`new-dev`. The controller endpoint reported there is on its nested LXD network and is normally not
routable from the host.

Terraform state contains sensitive values even when variables are marked `sensitive`. The product
directories ignore local state, plans, and variable files, but ignoring them does not encrypt them.
Protect the checkout and use your organization's secured state handling for staging and production.

## 5. Initialize and deploy

Initialize both existing product directories:

```bash
terraform -chdir=terraform/dovecot init
terraform -chdir=terraform/postfix-relay init
```

Validate, plan, and deploy Dovecot:

```bash
terraform -chdir=terraform/dovecot validate
terraform -chdir=terraform/dovecot plan \
  -var='model_name=company-dovecot' \
  -out=dovecot.tfplan &&
terraform -chdir=terraform/dovecot show dovecot.tfplan &&
terraform -chdir=terraform/dovecot apply dovecot.tfplan &&
rm terraform/dovecot/dovecot.tfplan
```

On a local LXD cloud, the generic `8G` directive may select a filesystem pool. Dovecot requires a
block device, so select LXD's `loop` block-storage pool explicitly:

```bash
umask 077
test -s terraform/dovecot/luks-key.secret ||
  openssl rand -base64 48 >terraform/dovecot/luks-key.secret
export TF_VAR_luks_key="$(
  cat terraform/dovecot/luks-key.secret
)"

terraform -chdir=terraform/dovecot plan \
  -var='model_name=company-dovecot' \
  -var='model_cloud={name="localhost"}' \
  -var='dovecot={storage_directives={"mail-data"="loop,8G"}}' \
  -out=dovecot.tfplan &&
terraform -chdir=terraform/dovecot show dovecot.tfplan &&
terraform -chdir=terraform/dovecot apply dovecot.tfplan &&
rm terraform/dovecot/dovecot.tfplan
```

At Terraform's interactive `model_cloud` prompt, the equivalent value is
`{name="localhost"}`, not `localhost`. Supplying it with `-var` avoids the prompt.

Confirm that the pool exists with
`juju storage-pools -m <controller-name>:<existing-machine-model>`. If `loop` is unavailable, use a
block-capable pool supported by that cloud. Juju 4.0.13 has also been observed leaving LXD loop
storage attachments unresolved; use Juju 3.6 or real cloud block storage if the unit remains
`allocating`.

Validate, plan, and deploy Postfix Relay with OpenDKIM:

```bash
terraform -chdir=terraform/postfix-relay validate
terraform -chdir=terraform/postfix-relay plan \
  -var='model_name=company-postfix-relay' \
  -var='postfix_relay={config={domain="mail.example.com"}}' \
  -out=postfix-relay.tfplan &&
terraform -chdir=terraform/postfix-relay show postfix-relay.tfplan &&
terraform -chdir=terraform/postfix-relay apply postfix-relay.tfplan &&
rm terraform/postfix-relay/postfix-relay.tfplan
```

Run only the command block for the product you want when installing a single product.

The default channels are `2.3/edge` for Dovecot, `latest/edge` for Postfix Relay, and `2/edge` for
OpenDKIM. For staging and production, test specific revisions and set their `revision` inputs
instead of accepting future channel updates implicitly.

### Recover from an accidental controller deployment

Terraform state is associated with the controller used during the first apply. Changing
`TF_VAR_juju_controller` does not migrate that state. If a failed attempt used another controller,
the next refresh can report `unknown model: <uuid>`.

First confirm that the UUID is absent from both the old and new controllers:

```bash
juju models -c <old-controller>
juju models -c <new-controller>
terraform -chdir=terraform/dovecot state list
```

If the model no longer exists and every listed Dovecot product resource belongs to that failed
attempt, forget those stale records:

```bash
terraform -chdir=terraform/dovecot state rm \
  'juju_application.self_signed_certificates[0]' \
  juju_secret.dovecot_luks \
  juju_model.dovecot
```

Do not run `state rm` for resources that still exist and should remain managed. Destroy an
accidental live model on its original controller first, or restore that controller's Terraform
credentials and destroy it through Terraform.

## 6. Verify the deployment

Wait for both models to settle:

```bash
juju status -m <controller-name>:company-dovecot --watch 5s
juju status -m <controller-name>:company-postfix-relay --watch 5s
```

Stop each watch with `Ctrl-C` after all units are `active`. Confirm the integrations:

```bash
juju status -m <controller-name>:company-dovecot --relations
juju status -m <controller-name>:company-postfix-relay --relations
```

Expected relations:

- Dovecot to `self-signed-certificates` over `certificates`.
- Postfix Relay to OpenDKIM over `milter`.

Inspect the non-sensitive Terraform outputs:

```bash
terraform -chdir=terraform/dovecot output
terraform -chdir=terraform/postfix-relay output
terraform -chdir=terraform/postfix-relay output -json dkim | jq
```

Never add outputs containing product inputs or secrets.

## 7. Create Dovecot mail users

Create or update a mailbox account with the charm action:

```bash
printf 'Mailbox password: ' >&2
stty -echo
trap 'stty echo' EXIT INT TERM
IFS= read -r MAIL_PASSWORD
stty echo
trap - EXIT INT TERM
printf '\n' >&2
juju run -m <controller-name>:company-dovecot dovecot/0 create-mail-user \
  username=alice \
  mailbox-user=alice@mail.example.com \
  password="$MAIL_PASSWORD"
unset MAIL_PASSWORD
```

Repeat for each user. The action argument is visible briefly to local processes and is retained in
Juju task history; use test credentials locally and follow your credential-handling policy in
production.

## 8. Test end-to-end mail delivery

Run these commands inside the machine that can reach the Juju unit addresses. For the Multipass
lab:

```bash
multipass shell new-dev
```

Set the model names, discover the unit addresses, and choose a disposable mailbox password:

```bash
export DOVECOT_MODEL="concierge-lxd:company-dovecot"
export POSTFIX_MODEL="concierge-lxd:company-postfix-relay"
export MAIL_DOMAIN="mail.example.com"
export MAIL_PASSWORD="MailLab-2026!"

export DOVECOT_IP="$(
  juju status -m "$DOVECOT_MODEL" --format json |
    jq -r '.applications.dovecot.units["dovecot/0"]["public-address"]'
)"
export RELAY_IP="$(
  juju status -m "$POSTFIX_MODEL" --format json |
    jq -r '.applications["postfix-relay"].units["postfix-relay/0"]["public-address"]'
)"

printf 'Dovecot: %s\nPostfix Relay: %s\n' "$DOVECOT_IP" "$RELAY_IP"
```

Create Alice and Bob:

```bash
juju run -m "$DOVECOT_MODEL" dovecot/0 create-mail-user \
  username=alice mailbox-user="alice@$MAIL_DOMAIN" password="$MAIL_PASSWORD"
juju run -m "$DOVECOT_MODEL" dovecot/0 create-mail-user \
  username=bob mailbox-user="bob@$MAIL_DOMAIN" password="$MAIL_PASSWORD"
```

For a disposable test deployment, configure Postfix to relay the mail domain to the current
Dovecot unit:

```bash
juju config -m "$POSTFIX_MODEL" postfix-relay \
  allowed_relay_networks='[]' \
  enable_reject_unknown_sender_domain=false \
  relay_domains="[\"$MAIL_DOMAIN\"]" \
  relay_host="[$DOVECOT_IP]"

juju status -m "$POSTFIX_MODEL" --watch 5s
```

Stop the watch with `Ctrl-C` after both applications are active. This direct `juju config` command
is convenient for acceptance testing but creates Terraform drift. Put the same values in the
Postfix product's `postfix_relay.config` input before the next Terraform apply.

Send a unique message through Postfix with STARTTLS, retrieve it from Bob over IMAPS, verify that
OpenDKIM added a signature, and confirm that unauthenticated external relay is rejected:

```bash
python3 - <<'PY'
import imaplib
import os
import smtplib
import ssl
import time
from email.message import EmailMessage

relay_ip = os.environ["RELAY_IP"]
dovecot_ip = os.environ["DOVECOT_IP"]
domain = os.environ["MAIL_DOMAIN"]
password = os.environ["MAIL_PASSWORD"]
subject = f"Charmed mail acceptance test {int(time.time())}"

tls = ssl.create_default_context()
tls.check_hostname = False
tls.verify_mode = ssl.CERT_NONE

message = EmailMessage()
message["From"] = f"alice@{domain}"
message["To"] = f"bob@{domain}"
message["Subject"] = subject
message.set_content("Postfix Relay -> OpenDKIM -> Dovecot end-to-end test.")

with smtplib.SMTP(relay_ip, 25, timeout=30) as smtp:
    smtp.ehlo()
    assert smtp.has_extn("starttls"), "SMTP does not advertise STARTTLS"
    smtp.starttls(context=tls)
    smtp.send_message(message)
print(f"PASS: submitted {subject!r} through Postfix")

for _ in range(20):
    with imaplib.IMAP4_SSL(dovecot_ip, 993, ssl_context=tls) as mailbox:
        mailbox.login("bob", password)
        mailbox.select("INBOX")
        status, matches = mailbox.search(None, f'(HEADER Subject "{subject}")')
        if status == "OK" and matches[0]:
            message_id = matches[0].split()[-1]
            status, headers = mailbox.fetch(
                message_id, "(BODY.PEEK[HEADER.FIELDS (DKIM-SIGNATURE)])"
            )
            assert status == "OK" and b"DKIM-Signature:" in headers[0][1], (
                "message was delivered without a DKIM-Signature"
            )
            print("PASS: retrieved message through IMAPS with DKIM signature")
            break
    time.sleep(3)
else:
    raise SystemExit("FAIL: message did not reach Bob within 60 seconds")

with smtplib.SMTP(relay_ip, 25, timeout=30) as smtp:
    smtp.ehlo()
    smtp.starttls(context=tls)
    smtp.ehlo()
    code, response = smtp.mail(f"alice@{domain}")
    assert code < 400, f"MAIL FROM failed: {code} {response!r}"
    code, response = smtp.rcpt("outsider@example.net")
    assert code >= 400, f"open relay detected: {code} {response!r}"
    print(f"PASS: external relay rejected with SMTP {code}")
PY
```

Confirm Dovecot uses the encrypted mail volume:

```bash
juju exec -m "$DOVECOT_MODEL" --unit dovecot/0 -- \
  'sudo cryptsetup status mail-data && findmnt /srv/mail'
```

If delivery fails, inspect both models:

```bash
juju debug-log -m "$POSTFIX_MODEL" --replay --no-tail --limit 200
juju debug-log -m "$DOVECOT_MODEL" --replay --no-tail --limit 200
juju exec -m "$POSTFIX_MODEL" --unit postfix-relay/0 -- \
  'sudo postqueue -p; sudo journalctl -u snap.postfix-relay.postfix -n 100 --no-pager'
```

## 9. Configure persistent routing between the products

This step is required only when using Postfix Relay to deliver to Dovecot. There is no automatic
relation or service discovery between the products.

For a test environment, obtain the Dovecot unit address:

```bash
juju status -m <controller-name>:company-dovecot
```

Set `relay_host` by planning the existing Postfix Relay product again with the complete application
configuration:

```bash
terraform -chdir=terraform/postfix-relay plan \
  -var='model_name=company-postfix-relay' \
  -var='postfix_relay={config={domain="mail.example.com",relay_host="[<dovecot-unit-address>]"}}' \
  -out=route.tfplan
terraform -chdir=terraform/postfix-relay apply route.tfplan
rm terraform/postfix-relay/route.tfplan
```

A unit address is not a production-grade service contract and can change when a unit is replaced.
For staging and production, use stable network addressing or DNS and validate reachability between
the two models. The long-term fix is a charm relation that publishes and consumes the mailbox
backend endpoint.

## 10. Publish DKIM DNS

Extract the public key:

```bash
DKIM_PUBLIC_KEY="$(
  sed '/-----BEGIN PUBLIC KEY-----/d;/-----END PUBLIC KEY-----/d' \
    /secure/path/default.public | tr -d '\n'
)"
printf 'default._domainkey.%s TXT "v=DKIM1; k=rsa; p=%s"\n' \
  "$TF_VAR_mail_domain" "$DKIM_PUBLIC_KEY"
unset DKIM_PUBLIC_KEY
```

Publish that TXT record in DNS. Also configure SPF, DMARC, forward DNS, reverse DNS, and trusted TLS
before sending Internet mail. The default self-signed certificate provider is for testing only;
set the Dovecot product's `tls` input to your production certificate endpoint or offer.

## 11. Expose services only when required

Juju applications are not exposed by these modules. If clients must connect directly and cloud
firewall policy permits it:

```bash
juju expose -m <controller-name>:company-dovecot dovecot
juju expose -m <controller-name>:company-postfix-relay postfix-relay
```

Do not expose OpenDKIM. Restrict SMTP and IMAP ingress with Juju spaces, cloud security groups, and
network policy appropriate to the environment.

## 12. Upgrade or remove the products

To upgrade, check out the required repository release or commit, initialize the relevant product,
then review and apply a plan using the same input values as the original deployment:

```bash
git fetch --tags
git checkout <new-release-tag-or-commit>
terraform -chdir=terraform/dovecot init -upgrade
terraform -chdir=terraform/dovecot plan \
  -var='model_name=company-dovecot' \
  -out=upgrade.tfplan
terraform -chdir=terraform/dovecot apply upgrade.tfplan
rm terraform/dovecot/upgrade.tfplan
```

Use `terraform/postfix-relay` instead to upgrade that product, repeating its complete
`postfix_relay` input. Back up mail data and verify recovery before upgrading Dovecot.

To remove Postfix Relay:

```bash
terraform -chdir=terraform/postfix-relay plan -destroy \
  -var='model_name=company-postfix-relay' \
  -out=destroy.tfplan
terraform -chdir=terraform/postfix-relay apply destroy.tfplan
rm terraform/postfix-relay/destroy.tfplan
```

To remove Dovecot:

```bash
terraform -chdir=terraform/dovecot plan -destroy \
  -var='model_name=company-dovecot' \
  -out=destroy.tfplan
terraform -chdir=terraform/dovecot apply destroy.tfplan
rm terraform/dovecot/destroy.tfplan
```

Destroying Dovecot removes its model and can destroy the attached mail volume. Preserve required
mail and DKIM material before teardown, then clear the exported secret variables:

```bash
unset TF_VAR_juju_controller
unset TF_VAR_mail_domain
unset TF_VAR_model_cloud
unset TF_VAR_dkim_private_key
unset TF_VAR_luks_key
unset TF_VAR_postmaster_address
```
