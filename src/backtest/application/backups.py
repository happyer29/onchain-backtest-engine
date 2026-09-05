"""Infrastructure-neutral backup and fresh-root recovery outcomes."""

from __future__ import annotations

from dataclasses import dataclass

from backtest.application.catalog_models import CatalogRebuildReport
from backtest.domain.identifiers import ArtifactId, ContentDigest


class BackupError(RuntimeError):
    """Base fail-closed backup or recovery error."""


class BackupIntegrityError(BackupError):
    """A backup generation, checkpoint, or restored artifact is invalid."""


@dataclass(frozen=True, slots=True)
class BackupGeneration:
    backup_cut_id: ContentDigest
    catalog_digest: ContentDigest
    artifact_ids: tuple[ArtifactId, ...]
    # Declare created at ns explicitly in the backup generation contract.
    created_at_ns: int
    total_bytes: int

    def __post_init__(self) -> None:
        # Execute the backup generation post init workflow in explicit, reviewable steps.
        if self.created_at_ns < 0 or self.total_bytes < 0:
            raise ValueError("invalid backup generation counters")
        hexes = tuple(item.hex for item in self.artifact_ids)
        if hexes != tuple(sorted(hexes)) or len(hexes) != len(set(hexes)):
            raise ValueError("backup artifact IDs must be sorted and unique")


# Keep the restore report contract and validation rules together.
@dataclass(frozen=True, slots=True)
class RestoreReport:
    backup_cut_id: ContentDigest
    restored_artifacts: int
    catalog_rebuild: CatalogRebuildReport
    # Declare restored job roots explicitly in the restore report contract.
    restored_job_roots: tuple[ArtifactId, ...]
    reconciliation_complete: bool

    def __post_init__(self) -> None:
        # Execute the restore report post init workflow in explicit, reviewable steps.
        if self.restored_artifacts < 0:
            raise ValueError("restored artifact count must be non-negative")
        if not self.reconciliation_complete:
            raise ValueError("a successful restore report must be fully reconciled")


__all__ = [
    # Keep the backup error component named inside the all contract.
    "BackupError",
    "BackupGeneration",
    "BackupIntegrityError",
    "RestoreReport",
]
