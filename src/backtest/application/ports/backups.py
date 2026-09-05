"""Outbound backup-generation and fresh-root recovery boundaries."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from backtest.application.backups import BackupGeneration, RestoreReport
from backtest.domain.identifiers import ContentDigest


@runtime_checkable
# Keep the backup repository contract and validation rules together.
class BackupRepository(Protocol):
    def create_generation(self, *, created_at_ns: int) -> BackupGeneration: ...


@runtime_checkable
class RestoreRepository(Protocol):
    def restore_generation(self, backup_cut_id: ContentDigest) -> RestoreReport: ...


# Bind all once as an explicit module-level contract.
__all__ = ["BackupRepository", "RestoreRepository"]
