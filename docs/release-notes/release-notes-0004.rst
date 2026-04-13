.. _release_notes_release_notes_0004:

Dovecot release notes – 2.3/edge
=================================

These release notes cover new features and changes in Dovecot.

Main features:

* Added TLS certificate integration using the ``certificates`` relation.

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

Added TLS certificate integration via the ``certificates`` relation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Added TLS support to the Dovecot charm using the ``tls-certificates-interface`` library. When a ``certificates`` relation is established, the charm requests a certificate for the configured mail name and handles the ``certificate_available`` event by writing the certificate and private key to ``/etc/dovecot/private/``. The Dovecot service is automatically restarted after certificate installation. The Dovecot configuration template was updated to reference the certificate and key paths for IMAPS and POP3S listeners.

Relevant links:

* `PR <https://github.com/canonical/mailserver-operators/pull/4>`_

Bug fixes
---------

No bug fixes in this release.

Known issues
------------

No known issues.
