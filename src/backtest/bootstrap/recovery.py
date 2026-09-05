"""Recovery-only composition that never opens the live SQLite catalog.

The normal runtime composition deliberately validates and migrates the live
catalog at startup.  That is the wrong dependency direction for a restore
drill: recovery must remain usable precisely when those bytes are corrupt.
This module therefore depends only on secret-free configured paths and the
immutable backup-generation verifier.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from backtest.adapters.backup.local import LocalRestoreRepository

# Import backups at the visible module dependency boundary.
from backtest.application.backups import RestoreReport
from backtest.application.use_cases.manage_backups import RestoreBackup
from backtest.bootstrap.config import Settings
from backtest.bootstrap.maintenance import MaintenanceConfigurationError
from backtest.domain.identifiers import ContentDigest


# Keep the recovery verification contract and validation rules together.
@dataclass(frozen=True, slots=True)
class RecoveryVerification:
    report: RestoreReport
    destination_name: str


class RecoveryServices:
    """Verify one generation into a fresh configured destination.

    Construction and execution intentionally do not instantiate an artifact
    repository, SQLite adapter, source adapter, or the normal runtime
    container.  The live data root is not read or modified.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        clock_ns: Callable[[], int] = time.time_ns,
        # Close the init signature after its explicit inputs.
    ) -> None:
        # Execute the recovery services init workflow in explicit, reviewable steps.
        self._backup_root = settings.backup.target_root
        self._restore_parent = settings.backup.restore_verify_parent
        self._clock_ns = clock_ns

    def verify_restore(self, backup_cut_id: ContentDigest) -> RecoveryVerification:
        # Execute the recovery services verify restore workflow in explicit, reviewable
        # steps.
        if self._backup_root is None or self._restore_parent is None:
            # Handle the recovery services verify restore backup root and restore parent
            # condition as a distinct block.
            raise MaintenanceConfigurationError(
                "external backup restore drill is not configured for this host"
            )
        destination_name = f"restore-{backup_cut_id.hex}-{self._clock_ns():020d}"
        destination = self._restore_parent.absolute() / destination_name
        # Assemble report once so the recovery services verify restore workflow shares one
        # value.
        report = RestoreBackup(
            LocalRestoreRepository(self._backup_root.absolute(), destination)
        ).execute(backup_cut_id)
        return RecoveryVerification(report, destination_name)


def build_recovery_services(settings: Settings) -> RecoveryServices:
    """Build the narrow recovery root without touching live operational state."""

    return RecoveryServices(settings)


__all__ = [
    "RecoveryServices",
    "RecoveryVerification",
    "build_recovery_services",
    # Complete the all group only after its semantic components are visible.
]
