"""Typed outcomes and failures for the rebuildable artifact catalog."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from backtest.application.models import CommittedArtifact
from backtest.domain.identifiers import (
    ArtifactId,
    ContentDigest,
    # Run projection binds both logical and physical attempt identities.
    ExecutionAttemptId,
    LogicalRunId,
)


# Keep the artifact catalog status contract and validation rules together.
class ArtifactCatalogStatus(StrEnum):
    VERIFIED = "VERIFIED"
    QUARANTINED = "QUARANTINED"
    INVALID = "INVALID"


class ArtifactCatalogError(RuntimeError):
    """Base failure at the verified catalog boundary."""


class ArtifactCatalogVerificationError(ArtifactCatalogError):
    """Catalog metadata disagrees with filesystem authority."""


@dataclass(frozen=True, slots=True)
class ArtifactInventoryEntry:
    """Cheap mutation evidence for one committed-artifact candidate."""

    descriptor: CommittedArtifact
    latest_change_ns: int

    def __post_init__(self) -> None:
        """Reject timestamps that cannot participate in a safe fast-path check."""

        # A Boolean must not pass as an operational nanosecond timestamp.
        if isinstance(self.latest_change_ns, bool) or not isinstance(
            self.latest_change_ns,
            int,
        ):
            raise TypeError("artifact inventory change time must be an integer")
        if self.latest_change_ns < 0:
            raise ValueError("artifact inventory change time must be non-negative")


@dataclass(frozen=True, slots=True)
class ArtifactInventory:
    """Versioned process-independent fingerprint without payload-byte authority."""

    fingerprint: ContentDigest
    entries: tuple[ArtifactInventoryEntry, ...]

    def __post_init__(self) -> None:
        """Keep inventory comparison canonical and duplicate-free."""

        # Artifact IDs provide the stable order shared with the SQLite projection.
        identifiers = tuple(item.descriptor.artifact_id.hex for item in self.entries)
        if identifiers != tuple(sorted(identifiers)):
            raise ValueError("artifact inventory entries must be canonically ordered")
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("artifact inventory entries must have unique artifact IDs")


class BuildKeyCollisionError(ArtifactCatalogError):
    """One derivation key resolved to more than one committed content ID."""

    def __init__(
        self,
        build_key: ContentDigest,
        artifact_ids: tuple[ArtifactId, ...],
    ) -> None:
        # Execute the build key collision error init workflow in explicit, reviewable
        # steps.
        normalized = {item.hex: ArtifactId(item.hex) for item in artifact_ids}
        ordered = tuple(normalized[key] for key in sorted(normalized))
        if len(ordered) < 2:
            raise ValueError("a build-key collision requires at least two artifact IDs")
        self.build_key = build_key
        # Assemble self artifact ids once so the build key collision error init workflow
        # shares one value.
        self.artifact_ids = ordered
        super().__init__(
            f"build key {build_key.hex} produced conflicting artifacts: "
            + ", ".join(item.hex for item in ordered)
        )


@dataclass(frozen=True, slots=True)
class RunIndexEntry:
    """Manifest-bound ordering metadata from the rebuildable run index."""

    artifact_id: ArtifactId
    manifest_digest: ContentDigest
    logical_run_id: LogicalRunId
    # Keep physical-attempt identity available for stale-projection checks.
    execution_attempt_id: ExecutionAttemptId
    started_at_ns: int
    completed_at_ns: int

    def __post_init__(self) -> None:
        """Reject values that cannot be ordered or matched to a valid Run manifest."""

        if isinstance(self.started_at_ns, bool) or not isinstance(self.started_at_ns, int):
            raise TypeError("run index start epoch must be an integer")
        if isinstance(self.completed_at_ns, bool) or not isinstance(self.completed_at_ns, int):
            raise TypeError("run index completion epoch must be an integer")
        # SuccessfulRun already requires completion no earlier than start.
        if self.started_at_ns < 0 or self.completed_at_ns < self.started_at_ns:
            raise ValueError("run index timestamps are invalid")


# Keep the catalog rebuild report contract and validation rules together.
@dataclass(frozen=True, slots=True)
class CatalogRebuildReport:
    indexed_artifacts: int
    quarantined_artifacts: int
    conflicting_build_keys: int

    # Define catalog rebuild report post init as one focused operation with an explicit
    # boundary.
    def __post_init__(self) -> None:
        # Execute the catalog rebuild report post init workflow in explicit, reviewable
        # steps.
        if (
            min(
                self.indexed_artifacts,
                self.quarantined_artifacts,
                self.conflicting_build_keys,
                # Complete min only after its indexed artifacts and quarantined artifacts
                # inputs are visible in catalog rebuild report post init.
            )
            < 0
        ):
            raise ValueError("catalog rebuild counts must be non-negative")
        if self.quarantined_artifacts > self.indexed_artifacts:
            # Fail the catalog rebuild report post init path with ValueError for
            # quarantined count cannot exceed indexed count when quarantined artifacts and
            # indexed artifacts is true; do not continue ambiguously.
            raise ValueError("quarantined count cannot exceed indexed count")


__all__ = [
    "ArtifactCatalogError",
    "ArtifactCatalogStatus",
    "ArtifactCatalogVerificationError",
    # Inventory evidence is operational and never replaces a verified descriptor.
    "ArtifactInventory",
    "ArtifactInventoryEntry",
    # Keep the build key collision error component named inside the all contract.
    "BuildKeyCollisionError",
    "CatalogRebuildReport",
    "RunIndexEntry",
]
