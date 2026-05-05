<!-- vale Canonical.007-Headings-sentence-case = NO -->
# Security in Postfix relay
<!-- vale Canonical.007-Headings-sentence-case = YES -->

This document covers the security aspects of the Postfix relay charm itself.

For all use cases and configurations related to the Postfix product, please refer to the [official documentation](https://www.postfix.org/SMTPD_ACCESS_README.html).

## Good practices

<!-- vale Canonical.007-Headings-sentence-case = NO -->
### Use the Postfix relay charm alongside the SMTP DKIM signing charm
<!-- vale Canonical.007-Headings-sentence-case = YES -->

The charm doesn't support DKIM functionality. In order to sign and verify email, deploy the [SMTP DKIM signing charm](https://charmhub.io/smtp-dkim-signing) alongside the Postfix relay charm and integrate both.

## Risks

The charm deploy a Postfix server acting as Postfix relay, and as such, it might handle sensitive information.

You should limit who has access to the service.
