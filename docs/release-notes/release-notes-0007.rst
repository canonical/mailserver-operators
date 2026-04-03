.. _release_notes_release_notes_0007:

Dovecot release notes – 2.3/edge
=================================

These release notes cover new features and changes in Dovecot.

Main features:

* Added sync integration test suite.

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

Sync integration test suite
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

An end-to-end integration test suite for mail pool synchronisation was added.
The tests verify that mail delivered to a primary unit is correctly replicated
to secondary units, covering both delivery confirmation and IMAP retrieval
across the HA cluster.

Relevant links:

* `PR <https://github.com/canonical/mailserver-operators/pull/6>`_

Bug fixes
---------

No bug fixes in this release.

Known issues
------------

No known issues.
