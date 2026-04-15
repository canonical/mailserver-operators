.. vale off

.. meta::
   :description: State diagrams showing the Dovecot charm's event handling, handler call chains, and all possible unit status outcomes.

.. _explanation_dovecot_charm_state_diagrams:

Dovecot charm state diagrams
=============================

These diagrams document the Dovecot charm's internal state machine as
implemented in ``charm.py`` and ``storage.py``.  They are based on
``pr/2-storage`` (commit ``3b226b0`` and later) and reflect the two-path
``_resolve_dev_path`` design and the ``start`` hook observer.

Diagram 1 — Event to handler to unit status
--------------------------------------------

Shows which Juju events trigger which handlers, and every possible
``unit.status`` outcome.  ``replicas.relation_created`` and ``clear_queue``
produce no status changes.

.. vale off
.. mermaid::

   flowchart TD
       %% ── Juju events ──────────────────────────────────────────────────────
       EV_INSTALL([install])
       EV_START([start])
       EV_CONFIG([config_changed])
       EV_UPGRADE([upgrade_charm])
       EV_STOR_ATT([mail_data_storage_attached])
       EV_STOR_DET([mail_data_storage_detaching])
       EV_PEER([replicas.relation_created])
       EV_ACTION([clear_queue action])

       %% ── Handlers ─────────────────────────────────────────────────────────
       H_INSTALL[_on_install]
       H_RECONCILE[_reconcile]
       H_PEER[_on_peer_relation_created\nwrites unit-name to relation data]
       H_ACTION[_on_clear_queue_action\nno status change]

       %% ── Status outcomes ──────────────────────────────────────────────────
       M_INSTALLING(["● Maintenance\nInstalling packages"])
       M_DEPS(["● Maintenance\nInstalling required dependencies"])
       M_DONE(["● Maintenance\nCharm installation done"])
       M_CONFIGURING(["● Maintenance\nConfiguring charm"])
       M_DOVECOT(["● Maintenance\nSetting up and configuring dovecot"])
       M_DOVECOT_OK(["● Maintenance\nDovecot configuration updated"])
       M_PROCMAIL(["● Maintenance\nSetting up and configuring procmail"])

       B_CONFIG(["✖ Blocked\nInvalid charm configuration\n(mailname / postmaster-address /\nprimary-unit / luks-key)\nraised: ConfigurationError"])
       B_LUKS_DISABLED(["✖ Blocked\nmail-data not mounted;\nluks-auto-provisioning disabled\nraised: StorageError"])
       B_LUKS_FAILED(["✖ Blocked\nFailed to setup LUKS storage\nraised: StorageError"])
       B_LUKS_RT(["✖ Blocked\nStorage setup step failed\n(device missing / not block /\nluksFormat / open /\ndmsetup / mkfs / mount)\nraised: StorageError"])
       B_DOVECONF(["✖ Blocked\nInvalid Dovecot configuration\nraised: ConfigurationError"])
       B_POSTFIX(["✖ Blocked\nFailed to configure postfix:\n<stderr>\nraised: ConfigurationError"])

       ACTIVE(["✔ Active"])

       SILENT["(no status change)\ndoveconf not yet installed\n— logs warning, returns"]

       %% ── Event wiring ─────────────────────────────────────────────────────
       EV_INSTALL      --> H_INSTALL
       EV_START        --> H_RECONCILE
       EV_CONFIG       --> H_RECONCILE
       EV_UPGRADE      --> H_RECONCILE
       EV_STOR_ATT     --> H_RECONCILE
       EV_STOR_DET     --> H_RECONCILE
       EV_PEER         --> H_PEER
       EV_ACTION       --> H_ACTION

       %% ── _on_install flow ─────────────────────────────────────────────────
       H_INSTALL       --> M_INSTALLING
       M_INSTALLING    --> M_DEPS
       M_DEPS          --> M_DONE
       M_DONE          -->|"calls _reconcile"| H_RECONCILE

       %% ── _reconcile: storage+config try/except ────────────────────────────
       H_RECONCILE     --> M_CONFIGURING
       M_CONFIGURING   -->|"ConfigurationError\n(_get_dovecot_config)"| B_CONFIG
       M_CONFIGURING   -->|"StorageError: not mounted\n(ensure_storage_ready)"| B_LUKS_DISABLED
       M_CONFIGURING   -->|"StorageError: CalledProcessError\n(ensure_storage_ready)"| B_LUKS_FAILED
       M_CONFIGURING   -->|"StorageError: StorageSetupError\n(ensure_storage_ready)"| B_LUKS_RT
       M_CONFIGURING   -->|"shutil.which('doveconf') is None"| SILENT
       M_CONFIGURING   -->|"all pass → _setup_dovecot"| M_DOVECOT

       %% ── _reconcile: dovecot+procmail try/except ──────────────────────────
       M_DOVECOT       -->|"ConfigurationError\n(doveconf -c fails)"| B_DOVECONF
       M_DOVECOT       -->|"validation OK\n→ service_reload(dovecot)"| M_DOVECOT_OK
       M_DOVECOT_OK    --> M_PROCMAIL
       M_PROCMAIL      -->|"ConfigurationError\n(postconf -e fails)"| B_POSTFIX
       M_PROCMAIL      -->|"service_reload(postfix) OK\n→ open_ports()"| ACTIVE

       %% ── Styles ───────────────────────────────────────────────────────────
       classDef event    fill:#dbeafe,stroke:#3b82f6,color:#1e3a5f
       classDef handler  fill:#f3f4f6,stroke:#6b7280,color:#111827
       classDef maint    fill:#fef9c3,stroke:#ca8a04,color:#713f12
       classDef blocked  fill:#fee2e2,stroke:#dc2626,color:#7f1d1d
       classDef active   fill:#dcfce7,stroke:#16a34a,color:#14532d
       classDef silent   fill:#f3f4f6,stroke:#9ca3af,color:#6b7280,stroke-dasharray:4 4

       class EV_INSTALL,EV_START,EV_CONFIG,EV_UPGRADE,EV_STOR_ATT,EV_STOR_DET,EV_PEER,EV_ACTION event
       class H_INSTALL,H_RECONCILE,H_PEER,H_ACTION handler
       class M_INSTALLING,M_DEPS,M_DONE,M_CONFIGURING,M_DOVECOT,M_DOVECOT_OK,M_PROCMAIL maint
       class B_CONFIG,B_LUKS_DISABLED,B_LUKS_FAILED,B_LUKS_RT,B_DOVECONF,B_POSTFIX blocked
       class ACTIVE active
       class SILENT silent

Diagram 2 — ``_reconcile`` internal call chain
-----------------------------------------------

Full execution path inside ``_reconcile``, showing both ``try/except`` blocks
and every branch.

The ``_resolve_dev_path`` sub-diagram reflects the two-path design:

- **Direct path** (``storages[0].location`` succeeds): returned immediately
  with no ``isLuks`` probe.  Used on first deploy and on
  ``storage-attached`` re-fires.  The device may be blank —
  ``setup_luks_storage`` handles formatting.
- **Reboot fallback path** (``ModelError``): falls back to the path saved at
  the last ``storage-attached`` event, then guards with ``_is_luks_device`` to
  defer until Juju has re-attached the loop image.

.. vale off
.. mermaid::

   flowchart TD
       START(["_reconcile(event) called\nstart / config_changed / upgrade_charm /\nmail_data_storage_attached /\nmail_data_storage_detaching /\n[via _on_install]"])

       S1["unit.status =\nMaintenance('Configuring charm')"]

       %% ── try block 1: config + storage ───────────────────────────────────
       TRY1[/"try"/]

       S2["_get_dovecot_config()\nDovecotConfig.from_charm()"]
       S2_RAISES["raises ConfigurationError\n'Invalid charm configuration…'\n(mailname / postmaster-address /\nprimary-unit / luks-key)"]

       S3["ensure_storage_ready(charm)\nstorage.py"]

       S3A{"luks_auto_provisioning\n= False?"}
       S3A_MT{"_mail_storage_mounted()\nos.path.ismount('/srv/mail')"}
       S3A_RAISE["raises StorageError\n'mail-data not mounted;\nluks-auto-provisioning disabled'"]
       S3A_OK["return (proceed)"]

       S3B{"shutil.which\n('cryptsetup')"}
       S3B_NONE["None → log warning\nreturn (defer silently)"]

       %% ── _resolve_dev_path — two branches ─────────────────────────────────
       S3C["_resolve_dev_path(charm)"]
       S3C_NO_STOR["no storages → return None\n(defer silently)"]

       S3C_DIRECT{"storages[0].location\nsucceeds?"}
       S3C_DIRECT_OK["dev_path from Juju API\n(first deploy / storage-attached)\nReturn immediately — no isLuks probe\nDevice may be blank: setup_luks_storage\nwill format it"]

       S3C_FALLBACK["ModelError raised\n→ reboot fallback path"]
       S3C_LOAD{"_load_storage_dev_path()\nsaved path exists?"}
       S3C_NO_PATH["no saved path\nreturn None (defer silently)"]
       S3C_ISLUKS{"_is_luks_device(dev_path)\ncryptsetup isLuks\n(loop re-attached after reboot?)"}
       S3C_NOT_LUKS["loop image not yet attached\nreturn None (defer silently)\nwait for storage-attached re-fire"]
       S3C_OK["return dev_path\n(reboot recovery — LUKS exists)"]

       S3D["_save_storage_dev_path(dev_path)\nthen setup_luks_storage(luks_key, dev_path)"]
       S3D_STEPS["① _mail_storage_mounted check (idempotent)\n② _validate_block_device (exists + S_ISBLK)\n③ _ensure_luks_container:\n   isLuks → luksFormat if new (key via stdin)\n   cryptsetup open if not mapped\n④ _ensure_filesystem:\n   dmsetup mknodes\n   blkid check for ext4\n   mkfs.ext4 if no fs\n⑤ _ensure_mounted:\n   configure_file /etc/fstab\n   mount → /srv/mail (chmod 1777)"]
       S3D_CPE["CalledProcessError\nraises StorageError\n'Failed to setup LUKS storage'"]
       S3D_SSE["StorageSetupError\n(device missing / not block /\nluksFormat / open /\ndmsetup / mkfs / mount)\nraises StorageError(str(e))"]
       S3D_OK["return (LUKS ready, /srv/mail mounted)"]

       S3E["teardown_detaching_storage(charm)"]
       S3E_STEPS["if storages present → return (no-op)\nif storages gone:\n  luks_auto_provisioning + mounted → umount\n  mapper exists → luksClose\nCalledProcessError → log only (never raises)"]

       CATCH1["except CharmBlockedError as e\nunit.status = Blocked(str(e))\nreturn"]

       %% ── doveconf guard ───────────────────────────────────────────────────
       S4{"shutil.which('doveconf')"}
       S4_NONE["log warning\n'Dovecot not installed yet'\nreturn\n(stays in Maintenance\n'Configuring charm')"]

       %% ── try block 2: dovecot + procmail ─────────────────────────────────
       TRY2[/"try"/]

       S5A["_setup_dovecot(dovecot_config)"]
       S5A_1["unit.status =\nMaintenance('Setting up and\nconfiguring dovecot')"]
       S5A_2["render dovecot.conf.tmpl\nwrite → /etc/dovecot/conf.d/\n99-local-dovecot-charm.conf"]
       S5A_3{"doveconf -c\n/etc/dovecot/conf.d/\n99-local-dovecot-charm.conf"}
       S5A_RAISE["raises ConfigurationError\n'Invalid Dovecot configuration,\ncheck logs for details'"]
       S5A_OK["service_reload('dovecot',\nrestart_on_failure=True)\nunit.status =\nMaintenance('Dovecot\nconfiguration updated')"]

       S5B["_setup_procmail()"]
       S5B_1["unit.status =\nMaintenance('Setting up and\nconfiguring procmail')"]
       S5B_2["mkdir /srv/mail (0o1777)\nrender procmailrc.tmpl\nwrite → /etc/procmailrc"]
       S5B_3{"postconf -e\nmailbox_command=procmail…"}
       S5B_RAISE["raises ConfigurationError\n'Failed to configure\npostfix: <stderr>'"]
       S5B_OK["service_reload('postfix',\nrestart_on_failure=True)"]

       CATCH2["except ConfigurationError as e\nunit.status = Blocked(str(e))\nreturn"]

       S5C["_open_ports()\ntcp: 143, 993, 110, 995, 4190, 9900"]
       ACTIVE(["unit.status = Active()"])

       %% ── Wiring ───────────────────────────────────────────────────────────
       START --> S1 --> TRY1 --> S2
       S2 -->|"raises"| S2_RAISES
       S2 -->|"ok"| S3

       S3 --> S3A
       S3A -->|"True"| S3A_MT
       S3A_MT -->|"not mounted"| S3A_RAISE
       S3A_MT -->|"mounted"| S3A_OK

       S3A -->|"False"| S3B
       S3B -->|"None"| S3B_NONE
       S3B -->|"found"| S3C

       S3C -->|"no storages"| S3C_NO_STOR
       S3C --> S3C_DIRECT
       S3C_DIRECT -->|"success"| S3C_DIRECT_OK
       S3C_DIRECT -->|"ModelError"| S3C_FALLBACK
       S3C_FALLBACK --> S3C_LOAD
       S3C_LOAD -->|"None"| S3C_NO_PATH
       S3C_LOAD -->|"path found"| S3C_ISLUKS
       S3C_ISLUKS -->|"False\n(loop not yet re-attached)"| S3C_NOT_LUKS
       S3C_ISLUKS -->|"True\n(LUKS header present)"| S3C_OK

       S3C_DIRECT_OK & S3C_OK --> S3D
       S3D --> S3D_STEPS
       S3D_STEPS -->|"CalledProcessError"| S3D_CPE
       S3D_STEPS -->|"StorageSetupError"| S3D_SSE
       S3D_STEPS -->|"success"| S3D_OK

       S3A_OK & S3B_NONE & S3C_NO_STOR & S3C_NO_PATH & S3C_NOT_LUKS & S3D_OK --> S3E
       S3E --> S3E_STEPS

       S2_RAISES & S3A_RAISE & S3D_CPE & S3D_SSE --> CATCH1

       S3E_STEPS --> S4
       S4 -->|"None"| S4_NONE
       S4 -->|"found"| TRY2

       TRY2 --> S5A --> S5A_1 --> S5A_2 --> S5A_3
       S5A_3 -->|"non-zero exit"| S5A_RAISE
       S5A_3 -->|"exit 0"| S5A_OK --> S5B
       S5B --> S5B_1 --> S5B_2 --> S5B_3
       S5B_3 -->|"CalledProcessError"| S5B_RAISE
       S5B_3 -->|"success"| S5B_OK

       S5A_RAISE & S5B_RAISE --> CATCH2

       S5B_OK --> S5C --> ACTIVE

       %% ── Styles ───────────────────────────────────────────────────────────
       classDef tryblock fill:#ede9fe,stroke:#7c3aed,color:#3b0764
       classDef catch    fill:#fee2e2,stroke:#dc2626,color:#7f1d1d
       classDef decision fill:#e0f2fe,stroke:#0284c7,color:#0c4a6e
       classDef action   fill:#f3f4f6,stroke:#6b7280,color:#111827
       classDef maint    fill:#fef9c3,stroke:#ca8a04,color:#713f12
       classDef blocked  fill:#fee2e2,stroke:#dc2626,color:#7f1d1d
       classDef active   fill:#dcfce7,stroke:#16a34a,color:#14532d
       classDef silent   fill:#f3f4f6,stroke:#9ca3af,color:#6b7280,stroke-dasharray:4 4
       classDef start    fill:#dbeafe,stroke:#3b82f6,color:#1e3a5f
       classDef raises   fill:#fef3c7,stroke:#d97706,color:#78350f
       classDef fixnote  fill:#f0fdf4,stroke:#16a34a,color:#14532d,stroke-dasharray:4 4

       class START start
       class TRY1,TRY2 tryblock
       class CATCH1,CATCH2 catch
       class S3A,S3A_MT,S3B,S3C_DIRECT,S3C_LOAD,S3C_ISLUKS,S5A_3,S5B_3,S4 decision
       class S2,S3,S3C,S3D,S3D_STEPS,S3E,S3E_STEPS,S5A,S5A_1,S5A_2,S5A_OK,S5B,S5B_1,S5B_2,S5B_OK,S5C action
       class S5A_1,S5B_1 maint
       class S2_RAISES,S3A_RAISE,S3D_CPE,S3D_SSE,S5A_RAISE,S5B_RAISE raises
       class ACTIVE active
       class S3B_NONE,S3C_NO_STOR,S3C_NO_PATH,S3C_NOT_LUKS,S4_NONE silent
       class S3C_DIRECT_OK fixnote

Notes
-----

- **``start`` event observed**: ``on.start`` is wired to ``_reconcile``.  On a
  VM reboot this is the first hook to fire (before ``storage-attached``).
  ``_resolve_dev_path`` handles the ``ModelError`` case and defers gracefully
  via the reboot fallback path.
- **``_on_install``** installs packages then calls ``_reconcile``.  Config
  blocking handled entirely inside ``_reconcile``.
- **Status written only in ``_reconcile``** catch blocks (and transient
  Maintenance in individual setup methods).  No function outside
  ``_reconcile``/``_on_install`` writes Blocked directly.
- **Exception hierarchy**: ``StorageError`` and ``ConfigurationError`` both
  extend ``CharmBlockedError``.  First ``try/except`` catches
  ``CharmBlockedError`` (both types).  Second catches ``ConfigurationError``
  only.
- **``luks-auto-provisioning``** config option controls whether the charm
  manages LUKS encryption.  When ``False``, the charm only checks the mount
  and blocks if it is absent.
- **``_resolve_dev_path`` two-path design**:

  - *Direct path*: ``storages[0].location`` returns the Juju-provided path.
    Returned immediately with no ``isLuks`` probe — the device may be blank on
    first deploy and ``setup_luks_storage`` will format it.
  - *Reboot fallback path*: ``ModelError`` → load saved path → guard with
    ``_is_luks_device`` (``cryptsetup isLuks``) to defer until the loop image
    is re-attached by Juju and the existing LUKS header is readable.

- **``teardown_detaching_storage``** never raises — ``CalledProcessError``
  during umount/luksClose is logged and swallowed.  Not inside either try
  block.
- **Silent hang**: if ``doveconf`` is absent, unit stays in
  ``Maintenance("Configuring charm")`` until the next event.
- **No ``WaitingStatus``** used anywhere.
- **LUKS key** fetched from Juju secret at config-validation time; passed to
  ``cryptsetup`` via stdin, never written to disk.
