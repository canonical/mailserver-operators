# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
from pathlib import Path

import ops
import ops.testing

import charm as charm_module


def _patch_backup_paths(monkeypatch, tmp_path: Path) -> dict[str, str]:
    backup_root = tmp_path / "backups" / "dovecot"
    state_dir = tmp_path / "var" / "lib" / "dovecot" / "backup"

    values = {
        "BACKUP_ARCHIVE_PATH": str(backup_root / "mail-data.tar.gz.enc"),
        "BACKUP_MANIFEST_PATH": str(backup_root / "manifest.json"),
        "BACKUP_KEY_FILE": str(state_dir / "encryption.key"),
    }

    for name, value in values.items():
        monkeypatch.setattr(charm_module, name, value)
    return values


def test_backup_relation_requires_encryption_secret(backup_ctx, base_state):
    """Integrating the backup relation without an encryption key blocks the unit."""
    backup_relation = ops.testing.Relation("backup", remote_app_name="bacula-fd")
    state_in = dataclasses.replace(base_state, relations={backup_relation})

    state_out = backup_ctx.run(backup_ctx.on.relation_created(backup_relation), state_in)

    assert isinstance(state_out.unit_status, ops.BlockedStatus)
    assert (
        state_out.unit_status.message
        == "backup-encryption-key secret must be set when the backup relation is integrated"
    )


def test_backup_encryption_key_reset_deletes_key_file(
    backup_ctx, base_state, monkeypatch, tmp_path
):
    """Clearing the encryption key blocks the unit, and removing the relation reactivates it."""
    paths = _patch_backup_paths(monkeypatch, tmp_path)
    key_file = Path(paths["BACKUP_KEY_FILE"])
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text("stale-passphrase", encoding="utf-8")

    backup_relation = ops.testing.Relation("backup", remote_app_name="bacula-fd")
    state_in = dataclasses.replace(base_state, relations={backup_relation})

    state_out = backup_ctx.run(backup_ctx.on.config_changed(), state_in)

    assert isinstance(state_out.unit_status, ops.BlockedStatus)
    assert "backup-encryption-key" in state_out.unit_status.message
    assert not key_file.exists()

    state_out = backup_ctx.run(backup_ctx.on.relation_broken(backup_relation), state_out)

    assert isinstance(state_out.unit_status, ops.ActiveStatus)


def test_backup_key_file_removed_without_relation(backup_ctx, base_state, monkeypatch, tmp_path):
    """Without the backup relation the key file is removed and the unit stays active."""
    paths = _patch_backup_paths(monkeypatch, tmp_path)
    key_file = Path(paths["BACKUP_KEY_FILE"])
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text("stale-passphrase", encoding="utf-8")

    state_out = backup_ctx.run(backup_ctx.on.config_changed(), base_state)

    assert isinstance(state_out.unit_status, ops.ActiveStatus)
    assert not key_file.exists()


def test_backup_key_file_written_without_relation_when_configured(
    backup_ctx, base_state, monkeypatch, tmp_path
):
    """With the key configured but no backup relation, the key file is still written."""
    paths = _patch_backup_paths(monkeypatch, tmp_path)
    key_file = Path(paths["BACKUP_KEY_FILE"])
    backup_secret = ops.testing.Secret({"backup-key": "backup-passphrase"})
    state_in = dataclasses.replace(
        base_state,
        config={**base_state.config, "backup-encryption-key": backup_secret.id},
        secrets=set(base_state.secrets) | {backup_secret},
    )

    state_out = backup_ctx.run(backup_ctx.on.config_changed(), state_in)

    assert isinstance(state_out.unit_status, ops.ActiveStatus)
    assert key_file.read_text(encoding="utf-8") == "backup-passphrase"


def test_backup_relation_publishes_spec_and_writes_assets(
    backup_ctx, base_state, monkeypatch, tmp_path
):
    """Configuring the key publishes the backup spec and renders the encrypted assets."""
    paths = _patch_backup_paths(monkeypatch, tmp_path)
    run_before_backup = str(charm_module.RUN_BEFORE_BACKUP_SCRIPT)
    run_after_backup = str(charm_module.RUN_AFTER_BACKUP_SCRIPT)
    run_after_restore = str(charm_module.RUN_AFTER_RESTORE_SCRIPT)
    backup_relation = ops.testing.Relation("backup", remote_app_name="bacula-fd")
    backup_secret = ops.testing.Secret({"backup-key": "backup-passphrase"})
    state_in = dataclasses.replace(
        base_state,
        config={**base_state.config, "backup-encryption-key": backup_secret.id},
        relations={backup_relation},
        leader=True,
        secrets=set(base_state.secrets) | {backup_secret},
    )

    state_out = backup_ctx.run(backup_ctx.on.config_changed(), state_in)

    assert isinstance(state_out.unit_status, ops.ActiveStatus)
    relation_out = state_out.get_relation(backup_relation.id)
    assert relation_out.local_app_data == {
        "fileset": f"{paths['BACKUP_ARCHIVE_PATH']},{paths['BACKUP_MANIFEST_PATH']}",
        "run-before-backup": run_before_backup,
        "run-after-backup": run_after_backup,
        "run-after-restore": run_after_restore,
    }

    key_file = Path(paths["BACKUP_KEY_FILE"])
    assert key_file.read_text(encoding="utf-8") == "backup-passphrase"

    pre_backup = Path(run_before_backup).read_text(encoding="utf-8")
    assert "openssl enc -aes-256-cbc" in pre_backup

    post_backup = Path(run_after_backup).read_text(encoding="utf-8")
    assert "rm -f /var/backups/dovecot/mail-data.tar.gz.enc" in post_backup

    post_restore = Path(run_after_restore).read_text(encoding="utf-8")
    assert "openssl enc -d -aes-256-cbc" in post_restore
