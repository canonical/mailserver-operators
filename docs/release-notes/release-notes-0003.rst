.. _release_notes_release_notes_0003:

Dovecot release notes – 2.3/edge
=================================

These release notes cover new features and changes in Dovecot.

Main features:

* Added LUKS encrypted block storage support for mail data.

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

Added LUKS encrypted block storage support
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Added support for LUKS-encrypted block storage for mail data. When a ``mail-data`` storage is attached and the ``manage-luks`` configuration option is enabled, the charm automatically formats the device with LUKS encryption using a randomly generated keyfile, opens the device via ``cryptsetup``, creates an ext4 filesystem, and mounts it at ``/srv/mail``. Persistent configuration is written to ``/etc/crypttab`` and ``/etc/fstab`` to survive reboots. When ``manage-luks`` is disabled, the charm monitors the mount point directly and sets the unit status accordingly. Storage detach events cleanly unmount the filesystem and close the LUKS device.

Relevant links:

* `PR <https://github.com/canonical/mailserver-operators/pull/3>`_

Bug fixes
---------

No bug fixes in this release.

Known issues
------------

No known issues.
