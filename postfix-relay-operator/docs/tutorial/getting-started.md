# Deploy the Wazuh Server charm for the first time

## What you’ll do
- Deploy the Postfix relay charm.

## Requirements

* A working station, e.g., a laptop, with amd64 architecture.
* Juju 3 installed and bootstrapped to an LXD controller. You can accomplish
this process by using a [Multipass](https://multipass.run/) VM as outlined in this guide: [How to manage your deployment](https://documentation.ubuntu.com/juju/3.6/howto/manage-your-deployment/). 
[note]
The [How to manage your deployment](https://documentation.ubuntu.com/juju/3.6/howto/manage-your-deployment/) tutorial provides documentation for both manual and automatic deployment management.
[/note]

:warning: When using a Multipass VM, make sure to replace IP addresses with the
VM IP in steps that assume you're running locally. To get the IP address of the
Multipass instance run ```multipass info my-juju-vm```.

## Set up a tutorial model

To manage resources effectively and to separate this tutorial's workload from
your usual work, create a new model using the following command.

```bash
juju add-model postfix-relay-tutorial
```

## Deploy the Postfix relay charm

The Postfix relay charm is standalone and doesn't require any other charm. For it to work rpoperly, you'll need to specify at least the `relay_domains` configuration with the list of domains to relay email to.

```bash
juju deploy postfix-relay --config relay_domains=-your.domain
```

Run `juju status` to see the current status of the deployment. The deployment is complete when the status is `Active`.

## Clean up the environment

Well done! You've successfully completed the Wazuh Server tutorial. To remove the
model environment you created during this tutorial, use the following command.

```bash
juju destroy-model postfix-relay-tutorial
```
