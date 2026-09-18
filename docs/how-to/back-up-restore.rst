.. meta::
.. meta::
:description: Learn how to back up and restore the Dovecot charm and its associated data.

.. _how_to_back_up_restore:

How to back up and restore
===========================

The Dovecot charm stores live mail data on ``/srv/mail``. When integrated via
the ``backup`` relation to Bacula, Dovecot creates an encrypted backup artifact locally and
hands that encrypted artifact to Bacula for offsite storage and restoration.

Backups do not rely on Bacula-native encryption. Instead, the Dovecot charm
encrypts the backup payload before the Bacula file daemon uploads it.

Prerequisites
-------------

- A deployed Dovecot application with mail storage configured.
- A Bacula deployment consisting of ``bacula-server``, PostgreSQL, an
  S3-compatible storage integrator, and ``bacula-fd``.

Configure backup encryption
---------------------------

Create a secret for the backup passphrase and grant it to Dovecot:

.. code-block:: shell

   juju add-secret dovecot-backup-key backup-key='<passphrase>'
   juju grant-secret dovecot-backup-key dovecot
   juju config dovecot backup-encryption-key=secret:dovecot-backup-key

Integrate Dovecot with Bacula
-----------------------------

Attach the Bacula file daemon to the same machine as Dovecot and integrate the
``backup`` relation:

.. code-block:: shell

   juju deploy bacula-fd
   juju integrate dovecot:juju-info bacula-fd:juju-info
   juju integrate dovecot:backup bacula-fd:backup

The charm ships three client-side hook scripts and publishes their absolute
paths from the charm payload to the ``backup`` relation:

- ``run-before-backup`` creates a tarball from ``/srv/mail``, encrypts it, and
  writes a manifest.
- ``run-after-backup`` removes the backed up files from the unit.
- ``run-after-restore`` decrypts the restored artifact, repopulates
  ``/srv/mail``, and starts Dovecot again.

Run a backup
------------

Backups are initiated from the Bacula side, typically through
Baculum (Bacula's web interface) or the configured Bacula schedule. See
`How to use the Baculum web interface
<https://canonical.com/juju/docs/backup-charms/latest/how-to/use-baculum/>`_
for how to run a manual backup job.
Dovecot publishes only these encrypted backup artifacts to Bacula:

- ``/var/backups/dovecot/mail-data.tar.gz.enc``
- ``/var/backups/dovecot/manifest.json``

Run a restore
-------------

Run the restore job from Bacula. See
`How to use the Baculum web interface
<https://canonical.com/juju/docs/backup-charms/latest/how-to/use-baculum/>`_
for how to run a restore job. When selecting the destination in the restore
wizard, set the "Restore to directory" option to ``/`` so files are restored to
their original locations. The restored encrypted artifact is placed back
onto the Dovecot unit by Bacula, and the Dovecot post-restore hook decrypts it
and restores the mail tree under ``/srv/mail``.

.. note::

   The post-restore hook wipes the ``/srv/mail`` mount completely before
   restoring the backup. Any mail received after the last backup will be lost.
