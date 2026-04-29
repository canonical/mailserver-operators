.. _release_notes_release_notes_0006:

Dovecot release notes – 2.3/edge
=================================

These release notes cover new features and changes in Dovecot.

Main features:

* Added GDPR compliance actions: ``gdpr-archive``, ``gdpr-delete``, and ``gdpr-takeout``.

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

GDPR compliance actions
^^^^^^^^^^^^^^^^^^^^^^^

Three new Juju actions were added to support GDPR compliance requirements.

``gdpr-archive`` creates a backup of a user's mailbox using ``doveadm backup``
and optionally compresses it into a ``.tar.gz`` file. The archive is stored
under ``/srv/mail/archives/``.

``gdpr-delete`` permanently expunges all mail for a user and removes their mail
directory, satisfying the right to erasure. The action requires ``confirm=true``
to be set explicitly to prevent accidental data loss.

``gdpr-takeout`` exports a user's mail in a portable format (``maildir`` or
``mbox``) and packages it as a ``.tar.gz`` tarball under ``/srv/mail/takeout/``,
satisfying the right to data portability.

Relevant links:

* `PR <https://github.com/canonical/mailserver-operators/pull/16>`_

Bug fixes
---------

No bug fixes in this release.

Known issues
------------

No known issues.
