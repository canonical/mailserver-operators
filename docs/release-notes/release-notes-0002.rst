.. _release_notes_release_notes_0002:

Dovecot charm release notes – 2.3/edge
=================================

These release notes cover new features and changes in Dovecot charm.

Main features:

* Added end-to-end mail delivery integration test suite.

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

Added end-to-end mail delivery integration test suite
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Added an integration test suite that verifies the full mail delivery pipeline end to end. Tests confirm that messages sent locally using Postfix are delivered through Procmail into Dovecot and are then retrievable over IMAP. The suite connects to a deployed Dovecot unit, sends a test message, and asserts that the message appears in the recipient's inbox within a fixed timeout.

Relevant links:

* `PR <https://github.com/canonical/mailserver-operators/pull/8>`_

Bug fixes
---------

No bug fixes in this release.

Known issues
------------

No known issues.
