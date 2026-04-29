.. _release_notes_release_notes_0005:

Dovecot release notes – 2.3/edge
=================================

These release notes cover new features and changes in Dovecot.

Main features:

* Added HA support with SSH key exchange and ``force-sync`` action.

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

HA support with SSH key exchange and force-sync action
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

High-availability support was added to the Dovecot charm. The charm now
exchanges SSH keys between primary and secondary units during installation,
enabling passwordless root SSH access required for mail pool synchronisation.
A new ``force-sync`` action was introduced, allowing operators to trigger an
immediate synchronisation of the mail pool from the primary unit to the
secondary unit on demand.

Relevant links:

* `PR <https://github.com/canonical/mailserver-operators/pull/15>`_

Bug fixes
---------

No bug fixes in this release.

Known issues
------------

No known issues.
