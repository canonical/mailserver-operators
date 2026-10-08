.. meta::
   :description: View the changelog for the __charm_name__ charm, including all versions and changes.

.. _changelog:

Changelog
=========

All notable changes to this project will be documented in this file.

The format is based on `Keep a Changelog <https://keepachangelog.com/en/1.1.0/>`_.

Each revision is versioned by the date of the revision.

2026-10-08
----------

Added
~~~~~

- A :ref:`how-to guide <how_to_add_mail_users>` for adding Dovecot mail users
  through a Juju secret, granting application access, and updating credentials.

Changed
~~~~~~~

- Clarified in the :ref:`backup and restore guide <how_to_back_up_restore>` that
  Bacula does not back up or restore mail users or Juju secrets. Documented
  separate secret protection and recovery, including preserving the backup
  encryption passphrase.

2026-09-18
----------

Added
~~~~~

- Added an integration test to verify backup portability across charm upgrades:
  a backup produced by an older published revision can be restored onto a newly
  deployed revision of the charm, as long as both share the same
  ``backup-encryption-key`` secret.
- A how-to guide for manually failing over a replicated Dovecot deployment.

2026-09-16
----------

Added
~~~~~

- Charm-encrypted Bacula backup and restore support for Dovecot. Mail data under
  ``/srv/mail`` is tarred, gzipped, and AES-256-CBC encrypted before being shipped
  to the Bacula server, and decrypted on restore. Enabled by setting the
  ``backup-encryption-key`` secret config and integrating the ``backup`` relation.
