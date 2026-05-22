.. _release_notes_release_notes_0006:

Dovecot release notes – 2.3/edge
=================================

These release notes cover new features and changes in Dovecot.

Main features:

* Added internal Postfix wiring for LMTP delivery and SMTP mail flow.

See our :ref:`Release policy and schedule <release_notes_index>`.

Requirements and compatibility
-------------------------------

The charm operates Dovecot 2.3.

.. list-table::
   :header-rows: 1
   :widths: 50 50

   * - Software
     - Required version
   * - Juju
     - 3.x
   * - Ubuntu
     - 24.04

Updates
-------

The following major and minor features were added in this release.

Added internal Postfix wiring for LMTP delivery and SMTP mail flow
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Postfix now delivers mail for the charm's primary domain to Dovecot through the LMTP Unix socket, while SMTP port 25 is opened for relay traffic. Dovecot was updated to strip the domain from LMTP recipients before userdb lookups, which allows local system users to be resolved correctly when mail is delivered as full addresses. The integration tests were updated to submit mail over SMTP and verify delivery end to end through Postfix, LMTP, and IMAPS.

Relevant links:

* `PR <https://github.com/canonical/mailserver-operators/pull/30>`_

Bug fixes
---------

No bug fixes in this release.

Known issues
------------

No known issues.
