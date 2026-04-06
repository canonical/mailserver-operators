.. _release_notes_release_notes_0001:

Dovecot release notes – 2.3/edge
=================================

These release notes cover new features and changes in Dovecot.

Main features:

* Added base charm scaffold with config validation and ``clear-queue`` action.

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

Added base charm scaffold with config validation and ``clear-queue`` action
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Added the initial Dovecot IMAP/POP3 charm scaffold. The charm validates four required configuration options on every config-changed and install event: ``mailname``, ``postmaster-address``, ``cron-mailto``, and ``primary-unit``. Each missing field causes the unit to enter ``BlockedStatus`` with a descriptive message. When configuration is valid the charm installs Dovecot and related packages using ``apt``, opens the standard IMAP, POP3, ManageSieve and metrics ports, and renders Dovecot and Procmail configuration from Jinja2 templates. A ``clear-queue`` action is provided to flush the Postfix deferred or full mail queue using ``postsuper``.

Relevant links:

* `PR <https://github.com/canonical/mailserver-operators/pull/2>`_

Bug fixes
---------

No bug fixes in this release.

Known issues
------------

No known issues.
