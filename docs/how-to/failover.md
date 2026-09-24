---
myst:
  html_meta:
    "description lang=en": "How to manually fail over a replicated Dovecot charm deployment to its secondary unit"
---

(how_to_failover)=

# How to manually fail over Dovecot

Dovecot supports an active/passive deployment with one primary and one secondary
unit. Mails are copied asynchronously from the primary to the secondary by
`doveadm dsync`. The units do not use shared mail storage and the charm does not
automatically change external routing.

Use Terraform to manage the primary unit and its routing in production. A single
Terraform input can update the charm's `primary-unit` configuration, the Postfix
delivery target, and the HAProxy backend together. Direct Juju configuration is
useful for recovery or deployments that are not managed by Terraform.

## Prerequisites

Before starting, ensure that:

- Exactly two Dovecot units are deployed and active.
- The secondary has joined the `replicas` peer relation.
- You know which external routes and mail delivery services target the current
  primary.
- You have a maintenance window for the failover.
- You can stop new IMAP connections and SMTP deliveries to the current primary
  and allow existing connections to finish.

Check the units and current primary:

```shell
juju status dovecot --relations
juju config dovecot primary-unit
```

## Plan a failover between two Dovecot units

The steps in this section assume a planned failover from `dovecot/0` to `dovecot/1`.

### Stop traffic to the current primary

Stop routing new IMAP connections and SMTP deliveries to the current primary.
Wait for existing client sessions and in progress mail deliveries to finish, or
terminate them before continuing.

### Synchronize the secondary

Copy the latest mail to the secondary:

```shell
juju run dovecot/0 force-sync
```

If `force-sync` fails, resolve the reported error and rerun the action. Continue
only after the synchronization succeeds.

### Promote the secondary

Set the secondary as the new primary:

```shell
juju config dovecot primary-unit=dovecot/1
juju wait-for application dovecot --timeout=15m
```

### Update routing

Update every route that used the old primary (`dovecot/0`) to target the new primary (`dovecot/1`).

### Restore traffic

Restore traffic and verify that new mail can be delivered and retrieved through
the external endpoint.

After the configuration change, the old primary (`dovecot/0`) becomes the secondary. Its sync
timer is stopped, and the new primary (`dovecot/1`) installs or enables its timer to copy mail
in the opposite direction.

## Handle an unplanned failover

If the primary is unavailable, skip `force-sync` and promote the secondary, then
update the external routes. Mail received since the last successful sync may be
missing. The maximum expected loss is determined by the `sync-schedule` interval
and whether the most recent sync succeeded.

```{warning}
Fence the failed unit before restoring traffic. A recovered former primary must
not accept mail until it has reconciled as the secondary and received a current
copy from the new primary. This avoids divergent mailboxes.
```

## Fail back

Failback uses the same procedure in reverse. Stop traffic to the current
primary, run `force-sync`, change `primary-unit`, update routing, and then
restore traffic. Never fail back by changing routing alone.

## Manage failover with Terraform

Model the selected primary once and derive all dependent configuration from it.
For example:

```terraform
variable "dovecot_primary_unit" {
  type    = string
  default = "dovecot/0"
}

# Pass the value to the Dovecot module.
primary_unit = var.dovecot_primary_unit

# Resolve the selected unit address and use it for both:
# - the Postfix delivery target
# - the HAProxy or ingress-configurator backend
```

For a planned failover, stop traffic to the current primary and run `force-sync`
before applying the Terraform change. Review the plan to confirm that it changes
all three surfaces:

- Dovecot `primary-unit`
- Postfix delivery to Dovecot
- External client routing, such as the HAProxy backend.

Terraform records the desired state and prevents a later apply from reverting a
direct Juju change. It does not make the asynchronous data synchronization or
traffic cutover atomic.
