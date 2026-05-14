.. _release_notes_release_notes_0006:

Dovecot release notes – 2.3/edge
=================================

These release notes cover new features and changes in Dovecot.

Main features:

* Added ``create-mail-user`` action to create or update local system users for mail access.

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

create-mail-user action
^^^^^^^^^^^^^^^^^^^^^^^

A new ``create-mail-user`` Juju action was added to the Dovecot charm. The action
creates or updates a local system user for mail access, adds the user to the
``mail`` group, and sets the user's password. An optional ``mailbox-user``
parameter allows creating a mailbox-style username (e.g. ``user@example.com``)
alongside the primary username in a single call.

Relevant links:

* `PR <https://github.com/canonical/mailserver-operators/pull/28>`_

Bug fixes
---------

No bug fixes in this release.

Known issues
------------

No known issues.
