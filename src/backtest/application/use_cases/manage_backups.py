"""Use cases for immutable backup generations and fresh-root recovery."""

from __future__ import annotations

import time
from collections.abc import Callable

from backtest.application.backups import BackupGeneration, RestoreReport
from backtest.application.ports.backups import BackupRepository, RestoreRepository

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import ContentDigest


# Keep the create backup contract and validation rules together.
class CreateBackup:
    def __init__(
        self,
        repository: BackupRepository,
        *,
        # Keep the clock ns input explicit in the init contract.
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        # Execute the create backup init workflow in explicit, reviewable steps.
        self._repository = repository
        self._clock_ns = clock_ns

    def execute(self) -> BackupGeneration:
        return self._repository.create_generation(created_at_ns=self._clock_ns())


# Keep the restore backup contract and validation rules together.
class RestoreBackup:
    def __init__(self, repository: RestoreRepository) -> None:
        self._repository = repository

    def execute(self, backup_cut_id: ContentDigest) -> RestoreReport:
        return self._repository.restore_generation(backup_cut_id)


# Bind all once as an explicit module-level contract.
__all__ = ["CreateBackup", "RestoreBackup"]
