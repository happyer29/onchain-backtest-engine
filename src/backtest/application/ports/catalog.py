"""Rebuildable metadata-index boundary."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from backtest.application.catalog_models import CatalogRebuildReport, RunIndexEntry
from backtest.application.models import ArtifactKind, CommittedArtifact

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import ArtifactId, ContentDigest, LogicalRunId

# Run completion epochs are persisted as signed SQLite INTEGER nanoseconds.
_MAX_RUN_COMPLETION_NS = 2**63 - 1


@dataclass(frozen=True, slots=True)
class RunListCursor:
    """Typed exclusive keyset scoped to a global or logical Run list."""

    completed_at_ns: int
    artifact_id: ArtifactId
    logical_run_id: LogicalRunId | None = None

    def __post_init__(self) -> None:
        """Reject completion keys outside the durable ordering domain."""

        # A Boolean must not enter the ordering key as an integer subtype.
        if isinstance(self.completed_at_ns, bool) or not isinstance(
            self.completed_at_ns,
            int,
        ):
            raise TypeError("run cursor completion epoch must be an integer")
        # The cursor must be representable by the SQLite projection.
        if not 0 <= self.completed_at_ns <= _MAX_RUN_COMPLETION_NS:
            raise ValueError("run cursor completion epoch is outside the SQLite range")


# Keep the artifact catalog contract and validation rules together.
@runtime_checkable
class ArtifactCatalog(Protocol):
    def find_committed(self, artifact_id: ArtifactId) -> CommittedArtifact | None: ...

    def find_by_build_key(self, build_key: ContentDigest) -> CommittedArtifact | None: ...

    def index_committed(self, artifact: CommittedArtifact) -> None: ...

    # Define artifact catalog lineage inputs as one focused operation with an explicit
    # boundary.
    def lineage_inputs(self, artifact_id: ArtifactId) -> tuple[ArtifactId, ...]: ...

    def list_committed(
        self,
        *,
        kind: ArtifactKind | None,
        # Keep the limit input explicit in the list committed contract.
        limit: int,
        offset: int,
    ) -> tuple[CommittedArtifact, ...]: ...

    def rebuild_index(
        self,
        # Keep the artifacts input explicit in the rebuild index contract.
        artifacts: Iterable[CommittedArtifact],
    ) -> CatalogRebuildReport: ...


@runtime_checkable
class RunMetadataIndex(Protocol):
    """Bounded query seam over manifest-derived Run ordering metadata."""

    def list_runs(
        self,
        *,
        # Pagination is applied only after deterministic global ordering.
        limit: int,
        offset: int,
        after: RunListCursor | None = None,
    ) -> tuple[RunIndexEntry, ...]: ...

    def list_logical_runs(
        self,
        logical_run_id: LogicalRunId,
        *,
        # Logical-run pages use the same deterministic global time order.
        limit: int,
        offset: int,
        after: RunListCursor | None = None,
    ) -> tuple[RunIndexEntry, ...]: ...


__all__ = ["ArtifactCatalog", "RunListCursor", "RunMetadataIndex"]
