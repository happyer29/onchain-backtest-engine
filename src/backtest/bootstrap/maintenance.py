"""Composition of filesystem-authoritative retention and optional backup services."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# Import repository at the visible module dependency boundary.
from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.adapters.artifacts.localfs.retention import LocalRetentionRepository
from backtest.adapters.backup.local import LocalBackupRepository, LocalRestoreRepository
from backtest.adapters.catalog.sqlite.retention_index import (
    SQLiteRetentionIndex,
    # Include sqlite retention root provider so the retention index dependency remains
    # explicit.
    SQLiteRetentionRootProvider,
)
from backtest.application.backups import BackupGeneration, RestoreReport
from backtest.application.retention import GarbageCollectionPolicy
from backtest.application.use_cases.manage_backups import CreateBackup, RestoreBackup

# Import manage retention at the visible module dependency boundary.
from backtest.application.use_cases.manage_retention import ManageRetention
from backtest.bootstrap.config import Settings
from backtest.domain.identifiers import ContentDigest


class MaintenanceConfigurationError(RuntimeError):
    """A requested durability workflow is not configured on this host."""


@dataclass(frozen=True, slots=True)
class RestoreVerification:
    report: RestoreReport
    destination_name: str


# Keep the maintenance services contract and validation rules together.
class MaintenanceServices:
    def __init__(
        self,
        *,
        retention: ManageRetention,
        # Keep the backup input explicit in the init contract.
        backup: CreateBackup | None,
        backup_root: Path | None,
        restore_verify_parent: Path | None,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        # Execute the maintenance services init workflow in explicit, reviewable steps.
        if (backup is None) != (backup_root is None):
            raise ValueError("backup use case and target root presence disagree")
        if (backup is None) != (restore_verify_parent is None):
            raise ValueError("backup and restore verification must be configured together")
        self.retention = retention
        # Assemble self backup once so the maintenance services init workflow shares one
        # value.
        self._backup = backup
        self._backup_root = backup_root
        self._restore_verify_parent = restore_verify_parent
        self._clock_ns = clock_ns

    @property
    # Define maintenance services backup configured as one focused operation with an
    # explicit boundary.
    def backup_configured(self) -> bool:
        return self._backup is not None

    def create_backup(self) -> BackupGeneration:
        # Execute the maintenance services create backup workflow in explicit, reviewable
        # steps.
        if self._backup is None:
            # Handle the maintenance services create backup self._backup is None branch as
            # a distinct logical block.
            raise MaintenanceConfigurationError(
                "external backup target is not configured for this host"
            )
        return self._backup.execute()

    def verify_restore(self, backup_cut_id: ContentDigest) -> RestoreVerification:
        # Execute the maintenance services verify restore workflow in explicit, reviewable
        # steps.
        if self._backup_root is None or self._restore_verify_parent is None:
            # Handle the maintenance services verify restore backup root and restore
            # verify parent condition as a distinct block.
            raise MaintenanceConfigurationError(
                "external backup restore drill is not configured for this host"
            )
        destination_name = f"restore-{backup_cut_id.hex}-{self._clock_ns():020d}"
        destination = self._restore_verify_parent / destination_name
        # Assemble report once so the maintenance services verify restore workflow shares
        # one value.
        report = RestoreBackup(LocalRestoreRepository(self._backup_root, destination)).execute(
            backup_cut_id
        )
        return RestoreVerification(report, destination_name)


def build_maintenance_services(
    # Keep the settings input explicit in the build maintenance services contract.
    settings: Settings,
    artifacts: LocalArtifactRepository,
    *,
    clock_ns: Callable[[], int] = time.time_ns,
) -> MaintenanceServices:
    # Execute the build maintenance services workflow in explicit, reviewable steps.
    data_root = artifacts.data_root
    catalog_path = data_root / "catalog" / "catalog.sqlite"
    local_retention = LocalRetentionRepository(artifacts)
    retention_settings = settings.retention
    retention = ManageRetention(
        # Pass local retention explicitly so ManageRetention receives a reviewable minimum
        # artifact age seconds and trash grace seconds input in build maintenance
        # services.
        local_retention,
        SQLiteRetentionIndex(catalog_path),
        SQLiteRetentionRootProvider(catalog_path),
        policy=GarbageCollectionPolicy(
            minimum_artifact_age_ns=(
                # Pass retention settings explicitly so GarbageCollectionPolicy receives a
                # reviewable minimum artifact age seconds and trash grace seconds input in
                # build maintenance services.
                retention_settings.minimum_artifact_age_seconds * 1_000_000_000
            ),
            trash_grace_period_ns=(retention_settings.trash_grace_seconds * 1_000_000_000),
            maximum_sweep_bytes=retention_settings.maximum_sweep_gb * 1024**3,
        ),
        # Pass clock ns explicitly so ManageRetention receives a reviewable minimum
        # artifact age seconds and trash grace seconds input in build maintenance
        # services.
        clock_ns=clock_ns,
    )
    backup_settings = settings.backup
    if backup_settings.target_root is None:
        # Handle the build maintenance services backup_settings.target_root is None branch
        # as a distinct logical block.
        return MaintenanceServices(
            retention=retention,
            backup=None,
            backup_root=None,
            restore_verify_parent=None,
            # Pass clock ns explicitly so MaintenanceServices receives a reviewable
            # retention and clock ns input in build maintenance services.
            clock_ns=clock_ns,
        )
    restore_parent = backup_settings.restore_verify_parent
    if restore_parent is None:  # Settings validates this pair.
        raise AssertionError("configured backup has no restore verification parent")
    backup_root = backup_settings.target_root.absolute()
    backup = CreateBackup(
        LocalBackupRepository(
            artifacts,
            # Pass local retention explicitly so LocalBackupRepository receives a
            # reviewable allow same device for drill and artifacts input in build
            # maintenance services.
            local_retention,
            catalog_path,
            backup_root,
            allow_same_device_for_drill=backup_settings.allow_same_device_for_drill,
        ),
        # Pass clock ns explicitly so CreateBackup receives a reviewable allow same device
        # for drill and local backup repository input in build maintenance services.
        clock_ns=clock_ns,
    )
    return MaintenanceServices(
        retention=retention,
        backup=backup,
        # Pass backup root explicitly so MaintenanceServices receives a reviewable
        # absolute and retention input in build maintenance services.
        backup_root=backup_root,
        restore_verify_parent=restore_parent.absolute(),
        clock_ns=clock_ns,
    )


__all__ = [
    # Keep the maintenance configuration error component named inside the all contract.
    "MaintenanceConfigurationError",
    "MaintenanceServices",
    "RestoreVerification",
    "build_maintenance_services",
]
