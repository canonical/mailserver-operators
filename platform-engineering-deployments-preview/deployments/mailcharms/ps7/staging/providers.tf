provider "vault" {
  address = "https://vault.ps7.admin.canonical.com"
  auth_login {
    path = "auth/approle/login"

    parameters = {
      role_id   = var.approle_role_id
      secret_id = var.approle_secret_id
    }
  }
}

data "vault_generic_secret" "jaas_credentials_ps7" {
  path = "secret/groups/canonical-is-charms/service_account"
}

provider "juju" {
  controller_addresses = "jaas.ps7.canonical.com:443/k8s-jaas-ps7-jimm-jimm"
  client_id            = data.vault_generic_secret.jaas_credentials_ps7.data["juju_client_id"]
  client_secret        = data.vault_generic_secret.jaas_credentials_ps7.data["juju_client_secret"]
}
