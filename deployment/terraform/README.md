# Mail stack deployment

Terraform configuration for deploying the full mail stack locally using Juju.

## Stack topology

```
SMTP client ──587──► postfix-relay ◄─milter─► opendkim  (DKIM signing)
                     + postfix-relay-configurator (subordinate, transport maps)
                              │ LMTP :24
                              ▼
                        dovecot  (IMAP / LMTP)
                              │
                     ◄──993───┘
                     IMAP client
```

TLS for both postfix-relay and dovecot is provided by the
`self-signed-certificates` charm (Charmhub).

## Prerequisites

- A Juju controller bootstrapped and accessible via `juju`
- Terraform >= 1.12
- The Juju Terraform provider (installed automatically by `terraform init`)

## Quick start

### 1 — Build or locate charm files

```bash
# From the repo root, build each charm with charmcraft:
cd dovecot-charm      && charmcraft pack && cd ..
cd postfix-relay-operator && charmcraft pack && cd ..
cd opendkim-operator  && charmcraft pack && cd ..
cd postfix-relay-configurator-operator && charmcraft pack && cd ..
```

### 2 — Configure

```bash
cd deployment/terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars — at minimum set `domain`
```

### 3 — First apply (deploys everything except transport routing)

```bash
terraform init
terraform apply
```

Wait for all applications to become active:

```bash
juju status --model mailserver --watch 5s
```

### 4 — Configure LMTP routing (postfix-relay → dovecot)

Once dovecot is active, retrieve its IP and update `terraform.tfvars`:

```bash
DOVECOT_IP=$(juju status --model mailserver --format json | \
  jq -r '.applications.dovecot.units | to_entries[0].value["public-address"]')

echo "transport_maps = { \"$(grep '^domain' terraform.tfvars | cut -d= -f2 | tr -d ' "')\" = \"lmtp:inet:${DOVECOT_IP}:24\" }" \
  >> terraform.tfvars
```

Then re-apply:

```bash
terraform apply
```

### 5 — Configure DKIM keys (opendkim)

Generate a keypair and configure opendkim via Juju:

```bash
# Generate a key (requires python-cryptography)
python3 - <<'EOF'
import base64, os
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
priv = key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()).decode()

pub_der = key.public_key().public_bytes(serialization.Encoding.DER,
           serialization.PublicFormat.SubjectPublicKeyInfo)
pub_b64 = base64.b64encode(pub_der).decode()

domain = "mail.example.com"   # <-- change me
selector = "default"
keyname = f"{domain.replace('.', '-')}-{selector}"

print(f"Key name : {keyname}")
print(f"TXT record: {selector}._domainkey.{domain} IN TXT \"v=DKIM1; h=sha256; k=rsa; p={pub_b64}\"")
with open(f"{keyname}.pem", "w") as f:
    f.write(priv)
print(f"Private key written to {keyname}.pem")
EOF

# Store the private key as a Juju secret
juju add-secret mailstack-dkim-secret \
  "mail-example-com-default#file=mail-example-com-default.pem"
SECRET_ID=$(juju show-secret mailstack-dkim-secret --format json | jq -r 'to_entries[0].key')
juju grant-secret "$SECRET_ID" opendkim

# Configure opendkim (adjust domain / selector as needed)
juju config opendkim --model mailserver \
  keytable='[["default._domainkey.mail.example.com","mail.example.com:default:/etc/dkimkeys/mail-example-com-default.private"]]' \
  signingtable='[["*@mail.example.com","default._domainkey.mail.example.com"]]' \
  private-keys="$SECRET_ID" \
  mode=s
```

## Variables reference

| Variable | Default | Description |
|---|---|---|
| `model_name` | `"mailserver"` | Juju model to create (or target) |
| `create_model` | `true` | Create a new model; set `false` to reuse existing |
| `model_uuid` | `""` | UUID of existing model (only when `create_model = false`) |
| `domain` | — | **Required.** Primary mail domain |
| `transport_maps` | `{}` | Postfix transport map (fill after first apply) |
| `dovecot_charm` | `"dovecot"` | Local `.charm` path or Charmhub name |
| `postfix_relay_charm` | `"postfix-relay"` | Local `.charm` path or Charmhub name |
| `opendkim_charm` | `"opendkim"` | Local `.charm` path or Charmhub name |
| `postfix_relay_configurator_charm` | `"postfix-relay-configurator"` | Local `.charm` path or Charmhub name |

## Destroy

```bash
terraform destroy
```
