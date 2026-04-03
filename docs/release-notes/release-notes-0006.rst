.. _release_notes_release_notes_0006:

Dovecot release notes – 2.3/edge
=================================

These release notes cover new features and changes in Dovecot.

Main features:

* Added GDPR data actions: archive, delete, and takeout.

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

GDPR data actions: archive, delete, and takeout
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Three new Juju actions were added to support GDPR compliance. The
``gdpr-archive`` action creates a compressed or uncompressed backup of a
user's mailbox for long-term retention. The ``gdpr-delete`` action
permanently removes a user's mailbox and mail data in accordance with the
right to erasure, requiring explicit confirmation before proceeding. The
``gdpr-takeout`` action exports a user's mail data in either Maildir or mbox
format, enabling data portability.

Relevant links:

* `PR <https://github.com/canonical/mailserver-operators/pull/5>`_

Bug fixes
---------

No bug fixes in this release.

Known issues
------------

No known issues.
