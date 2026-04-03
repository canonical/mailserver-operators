.. _release_notes_release_notes_0008:

Dovecot release notes – 2.3/edge
=================================

These release notes cover new features and changes in Dovecot.

Main features:

* Added COS observability integration via the ``cos-agent`` relation.

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

COS observability integration
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The Dovecot charm was integrated with the Canonical Observability Stack
(COS) via the ``cos-agent`` relation. Prometheus metrics are exposed on
port 9900, Prometheus alerting rules and Loki log alerting rules are
included, and a pre-built Grafana dashboard is bundled with the charm.
The observability configuration is refreshed automatically on each
``config-changed`` event.

Relevant links:

* `PR <https://github.com/canonical/mailserver-operators/pull/7>`_

Bug fixes
---------

No bug fixes in this release.

Known issues
------------

No known issues.
