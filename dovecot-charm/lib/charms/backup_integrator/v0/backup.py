# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""
Library to manage the relation between backup providers and backup
requirers.

Backup provider charms are charms that provide backup services, and
backup requirer charms are charms that have files on the unit that need
to be backed up. This library provides helper classes: `BackupProvider`
for backup provider charms, and `BackupRequirer` and
`BackupDynamicRequirer` for backup requirer charms.

## Understanding the Backup Relation

On the requirer side, the backup relation contains five fields in the
application databag that describe what to back up and how to perform the
backup:

* `fileset`
* `run-before-backup` (optional)
* `run-after-backup` (optional)
* `run-before-restore` (optional)
* `run-after-restore` (optional)

The `fileset` field is a comma-separated list of files or directories
that the backup provider charm will back up.

The `run-before-backup`, `run-after-backup`, `run-before-restore`, and
`run-after-restore` fields are optional and point to absolute paths of
executable files on the requirer charm units. These executables can be
scripts such as Bash or Python scripts, provided they include an
appropriate shebang. If any of the fields are not provided, nothing will
be executed before or after the backup or restore process. For
`run-before-backup` and `run-before-restore`, if the scripts fail, the
backup or restore operation will be canceled. These scripts can be
useful for performing tasks such as preparing for a backup, automating a
restore, and so on.

The backup relation is designed for machine charms, and all the fields within
the relation, including `fileset`, `run-before-backup`, `run-after-backup`,
`run-before-restore`, and `run-after-restore` — point to files on the requirer
unit. To provide the backup relation, the provider charm must have a way to
access and execute those files on the requirer unit to perform the backup.

On the provider side, the backup relation contains no data.

## Backup Requirer Charm Using the `BackupRequirer` Class

For most backup requirer charms, you should use the `BackupRequirer`
class. To use it, simply initialize the `BackupRequirer` class with the
appropriate arguments in the charm constructor. The input arguments (
`fileset`, `run_before_backup`, `run_after_backup`,
`run_before_restore`, `run_after_restore`) should ideally be hardcoded
rather than dynamically generated. The `BackupRequirer` will handle all
aspects of the backup relation.

```python
class FooCharm(ops.CharmBase):
    def __init__(self, *args: typing.Any):
        super().__init__(*args)
        src_dir = pathlib.Path(__file__).parent
        self._requirer = BackupRequirer(
            charm=self,
            fileset=["/var/backups/foo"],
            run_before_backup=src_dir / "run_before_backup.py",
            run_after_backup=src_dir / "run_after_backup.py",
            run_after_restore=src_dir / "run_after_restore.py",
        )
```

## Backup Requirer Charm Using the `BackupDynamicRequirer` Class

In some rare cases, the charm does not know the exact backup
specification at build time, for example, when the backup fileset depends on
charm configuration. In that case, you should use the
`BackupDynamicRequirer` class. To use it, initialize the
`BackupDynamicRequirer` class in the charm constructor. Unlike the
`BackupRequirer` class, the backup specification is not provided during
initialization. Instead, you must call
`BackupDynamicRequirer.require_backup` within an event handler to
provide the information dynamically. You can only call
`BackupDynamicRequirer.require_backup` on the leader unit. If
`BackupDynamicRequirer.require_backup` is run on a non-leader unit,
an `ops.RelationDataAccessError` will be raised.

```python
class BarCharm(ops.CharmBase):
    def __init__(self, *args: typing.Any):
        super().__init__(*args)
        self._requirer = BackupDynamicRequirer(charm=self)
        self.framework.observe(
            self.on.config_changed,
            self._on_config_changed,
        )

    def _on_config_changed(self, _):
        if not self.unit.is_leader():
            return
        fileset = [
            file.strip()
            for file in self.config.get("fileset").split(",")
            if file.strip()
        ]
        if not fileset:
            self.unit.status = ops.WaitingStatus("waiting for fileset config")
            return
        self._requirer.require_backup(fileset=fileset)

```

## Backup Provider Charm Using the `BackupProvider` Class

If you are creating a new backup provider charm, you should use the
`BackupProvider` class, which helps retrieve and validate the backup
specifications provided by backup requirer charms.

```python
import ops


class ProviderCharm(ops.CharmBase):
    def __init__(self, *args: typing.Any):
        super().__init__(*args)
        self._provider = BackupProvider(charm=self)
        self.framework.observe(
            self._provider.on.backup_required,
            self._on_backup_required,
        )

    def _on_backup_required(self, event):
        backup_spec = event.backup_spec
        # do something with backup_spec
        ...

```
"""

import logging
from pathlib import Path
from typing import Any, Optional, Union, List

import ops
from pydantic import BaseModel, field_validator, ConfigDict, field_serializer

# The unique Charmhub library identifier, never change it
LIBID = "55d94366e2624c1786227c24742c558f"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1

PYDEPS = ["pydantic>=2"]

DEFAULT_BACKUP_RELATION_NAME = "backup"

logger = logging.getLogger(__name__)


class BackupSpec(BaseModel):
    """BackupSpec describes what and how to back up a charm unit.

    Attributes:
        fileset: A list of absolute file or directory paths that need to be backed up.
        run_before_backup: An optional absolute path to an executable that, if defined,
            will run before the backup operation. If this command fails, the backup
            operation will be canceled.
        run_after_backup: An optional absolute path to an executable that, if defined,
            will run after the backup operation completes.
        run_before_restore: An optional absolute path to an executable that, if defined,
            will run before the restore operation. If this command fails, the restore
            operation will be canceled.
        run_after_restore: An optional absolute path to an executable that, if defined,
            will run after the restore operation completes.
        model_config: The Pydantic model configuration.
    """

    model_config = ConfigDict(
        alias_generator=lambda name: name.replace("_", "-"),
        serialize_by_alias=True,
        populate_by_name=True,
    )
    fileset: List[Path]
    run_before_backup: Optional[Path] = None
    run_after_backup: Optional[Path] = None
    run_before_restore: Optional[Path] = None
    run_after_restore: Optional[Path] = None

    @field_validator("fileset", mode="after")
    @classmethod
    def _validate_fileset(cls, value: list[Path]) -> list[Path]:
        """Validates the given fileset input.

        Args:
            value: The input fileset to validate.

        Returns:
            A validated list of absolute file and directory paths.

        Raises:
            ValueError: If the fileset contains invalid paths or fails validation.
        """
        if not value:
            raise ValueError("fileset cannot be empty")
        for path in value:
            str_path = str(path)
            if str_path != str_path.strip():
                raise ValueError("path cannot start or end with whitespaces")
            if "," in str_path:
                raise ValueError("path cannot contain commas")
            if not path.is_absolute():
                raise ValueError(f"all path in fileset must be absolute.")
        return value

    @field_serializer("fileset", mode="plain")
    def _serialize_fileset(self, fileset: list[Path]) -> str:
        """Serializes the given fileset into a string.

        Args:
            fileset: The fileset to serialize.

        Returns:
            The serialized fileset.
        """
        return ",".join(map(str, fileset))

    @field_validator(
        "run_before_backup",
        "run_after_backup",
        "run_before_restore",
        "run_after_restore",
        mode="after",
    )
    @classmethod
    def _validate_optional_path_absolute(cls, value: Optional[Path]) -> Optional[Path]:
        """Validates the given script path input.

        Args:
            value: The input script path to validate.

        Returns:
            A validated script path.

        Raises:
            ValueError: If the script path is invalid.
        """
        if value is None:
            return None
        if not value.is_absolute():
            raise ValueError("path must be absolute")
        return value

    @field_serializer(
        "run_before_backup",
        "run_after_backup",
        "run_before_restore",
        "run_after_restore",
        mode="plain",
    )
    def _serialize_optional_path(self, value: Optional[Path]) -> Optional[str]:
        """Serializes the given script path into a string.

        Args:
            value: The input script path.

        Returns:
            The serialized script path.
        """
        if value is None:
            return None
        else:
            return str(value)

    @classmethod
    def new(cls, **kwargs: Any) -> "BackupSpec":
        """Factory method for creating a new BackupSpec."""
        if "fileset" in kwargs:
            fileset = kwargs["fileset"]
            if isinstance(fileset, str):
                fileset = [f.strip() for f in fileset.split(",") if f.strip()]
            if fileset:
                fileset = [Path(f) for f in fileset]
            kwargs["fileset"] = fileset
        for key in [
            "run_before_backup",
            "run_after_backup",
            "run_before_restore",
            "run_after_restore",
            "run-before-backup",
            "run-after-backup",
            "run-before-restore",
            "run-after-restore",
        ]:
            if key not in kwargs:
                continue
            path = kwargs[key]
            if path:
                kwargs[key] = Path(path)
        return cls.model_validate(kwargs)


class BackupRequiredEvent(ops.RelationEvent):
    """Backup is required from the backup requirer."""

    def __init__(
        self,
        handle: ops.Handle,
        relation: ops.Relation,
        backup_spec: BackupSpec,
        app: Optional[ops.Application] = None,
        unit: Optional[ops.Unit] = None,
    ):
        """Initialize a BackupRequiredEvent."""
        super().__init__(handle=handle, relation=relation, app=app, unit=unit)
        self.backup_spec = backup_spec


class BackupProviderEvents(ops.ObjectEvents):
    """BackupProvider events."""

    backup_required = ops.EventSource(BackupRequiredEvent)


class BackupProvider(ops.Object):
    """Backup provider helper class."""

    on = BackupProviderEvents()

    def __init__(
        self,
        charm: ops.CharmBase,
        *,
        relation_name: str = DEFAULT_BACKUP_RELATION_NAME,
    ) -> None:
        """Initialize the backup provider.

        Args:
            charm: The provider charm instance.
            relation_name: The name of the backup relation.
        """
        super().__init__(parent=charm, key=relation_name)
        self._charm = charm
        self._relation_name = relation_name
        self.framework.observe(
            self._charm.on[self._relation_name].relation_changed, self._on_relation_changed
        )

    def _on_relation_changed(self, event: ops.RelationChangedEvent) -> None:
        """Handle relation-changed events."""
        try:
            spec = self.get_backup_spec(event.relation)
        except ValueError:
            logger.exception(f"invalid data in {self._relation_name} relation")
            return
        if spec is not None:
            self.on.backup_required.emit(
                relation=event.relation,
                app=event.app,
                unit=event.unit,
                backup_spec=spec,
            )

    def get_backup_spec(self, relation: ops.Relation) -> Optional[BackupSpec]:
        """Retrieve the backup spec for the given relation.

        Args:
            relation: The relation to get the backup spec from.

        Returns:
            The backup spec.
        """
        if relation.app is None:
            return None
        data = relation.data[relation.app]
        if not data:
            return None
        return BackupSpec.new(**data)


class BackupDynamicRequirer:
    """Backup requirer helper class."""

    def __init__(
        self,
        charm: ops.CharmBase,
        relation_name: str = DEFAULT_BACKUP_RELATION_NAME,
    ) -> None:
        """Initialize the backup requirer.

        Args:
            charm: The requirer charm instance.
            relation_name: The name of the backup relation.
        """
        self._charm = charm
        self._relation_name = relation_name

    def _require_backup(self, spec: BackupSpec) -> None:
        """Update the backup requirement in the relation data.

        Args:
            spec: The backup spec.
        """
        for relation in self._charm.model.relations[self._relation_name]:
            data = spec.model_dump(exclude_none=True)
            relation_data = relation.data[self._charm.app]
            if dict(relation_data) == data:
                continue
            relation_data.clear()
            logger.info("request backup with %s", data)
            relation_data.update(data)

    def require_backup(
        self,
        fileset: List[Union[str, Path]],
        run_before_backup: Optional[Union[str, Path]] = None,
        run_after_backup: Optional[Union[str, Path]] = None,
        run_before_restore: Optional[Union[str, Path]] = None,
        run_after_restore: Optional[Union[str, Path]] = None,
    ) -> None:
        """Update the backup requirement in the relation data.

        This method must be called on a leader unit, if called on a non-leader unit,
        an `ops.RelationDataAccessError` will be raised.

        Args:
            fileset: A list of absolute file or directory paths that need to be backed up.
            run_before_backup: An optional absolute path to an executable that, if defined,
                will run before the backup operation. If this command fails, the backup
                operation will be canceled.
            run_after_backup: An optional absolute path to an executable that, if defined,
                will run after the backup operation completes.
            run_before_restore: An optional absolute path to an executable that, if defined,
                will run before the restore operation. If this command fails, the restore
                operation will be canceled.
            run_after_restore: An optional absolute path to an executable that, if defined,
                will run after the restore operation completes.
        """
        spec = BackupSpec.new(
            fileset=fileset,
            run_before_backup=run_before_backup,
            run_after_backup=run_after_backup,
            run_before_restore=run_before_restore,
            run_after_restore=run_after_restore,
        )
        self._require_backup(spec)


class BackupRequirer(ops.Object):
    """Backup requirer helper class."""

    def __init__(
        self,
        charm: ops.CharmBase,
        *,
        fileset: List[Union[str, Path]],
        run_before_backup: Optional[Union[str, Path]] = None,
        run_after_backup: Optional[Union[str, Path]] = None,
        run_before_restore: Optional[Union[str, Path]] = None,
        run_after_restore: Optional[Union[str, Path]] = None,
        relation_name: str = DEFAULT_BACKUP_RELATION_NAME,
    ):
        """Initialize the backup requirer.

        Args:
            charm: The requirer charm instance.
            fileset: A list of absolute file or directory paths that need to be backed up.
            run_before_backup: An optional absolute path to an executable that, if defined,
                will run before the backup operation. If this command fails, the backup
                operation will be canceled.
            run_after_backup: An optional absolute path to an executable that, if defined,
                will run after the backup operation completes.
            run_before_restore: An optional absolute path to an executable that, if defined,
                will run before the restore operation. If this command fails, the restore
                operation will be canceled.
            run_after_restore: An optional absolute path to an executable that, if defined,
                will run after the restore operation completes.
            relation_name: The name of the backup relation.
        """
        super().__init__(parent=charm, key=relation_name)
        self._charm = charm
        self._relation_name = relation_name
        self._spec = BackupSpec.new(
            fileset=fileset,
            run_before_backup=run_before_backup,
            run_after_backup=run_after_backup,
            run_before_restore=run_before_restore,
            run_after_restore=run_after_restore,
        )
        self._dynamic_requirer = BackupDynamicRequirer(charm=charm, relation_name=relation_name)
        self._listen_on_every_event()

    def _listen_on_every_event(self) -> None:
        """Listen on every charm event."""
        for attr in dir(self._charm.on):
            event = getattr(self._charm.on, attr)
            if isinstance(event, ops.framework.BoundEvent):
                self.framework.observe(event, self._set_relation_data)

    def _set_relation_data(self, _: ops.EventBase) -> None:
        """Charm relation handler."""
        if self._charm.unit.is_leader():
            self._dynamic_requirer._require_backup(spec=self._spec)
