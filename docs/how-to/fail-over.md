---
myst:
  html_meta:
    "description lang=en": "How to manually fail over a replicated Dovecot deployment to its secondary unit"
---

(how_to_fail_over)=

# How to manually fail over Dovecot

Dovecot supports an active/passive deployment with one primary and one secondary
unit. Mail is copied asynchronously from the primary to the secondary by
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
- You have a maintenance window or a way to drain new IMAP and SMTP traffic.

Check the units and current primary:

```bash
juju status dovecot --relations
juju config dovecot primary-unit
```

## Planned failover

For a planned failover from `dovecot/0` to `dovecot/1`:

1. Drain or pause traffic to the current primary. This includes client traffic
   through HAProxy and mail delivery from Postfix. Do not allow both units to
   receive writes during the transition.

1. Copy the latest mail to the secondary:

   ```bash
   juju run dovecot/0 force-sync
   ```

   Do not continue if the action fails. Fix replication or restore the secondary
   before changing the primary.

1. Set the secondary as the new primary:

   ```bash
   juju config dovecot primary-unit=dovecot/1
   juju wait-for application dovecot --timeout=15m
   ```

1. Update every route that used the old primary.

1. Restore traffic and verify that new mail can be delivered and retrieved
   through the external endpoint.

After the configuration change, the old primary becomes the secondary. Its sync
timer is stopped, and the new primary installs or enables its timer to copy mail
in the opposite direction.

## Unplanned failover

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

Failback uses the same procedure in reverse. Drain traffic, run `force-sync` on
the current primary, change `primary-unit`, update routing, and then restore
traffic. Never fail back by changing routing alone.

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

For a planned failover, drain traffic and run `force-sync` before applying the
Terraform change. Review the plan to confirm that it changes all three surfaces:

- Dovecot `primary-unit`
- Postfix delivery to Dovecot
- External client routing, such as the HAProxy backend.

Terraform records the desired state and prevents a later apply from reverting a
direct Juju change. It does not make the asynchronous data synchronization or
traffic cutover atomic.
