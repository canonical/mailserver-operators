# Charm architecture

The Postfix relay charm deploys a Postfix server configured as instructed by the configuration options.

The Postfix relay can be deployed in Kubernetes and machine models, but in order to protect the server reputation, it is recommended to deploy it in machine models.
As a workloadless charm, the Postfix relay doesn't have any OCI images.
