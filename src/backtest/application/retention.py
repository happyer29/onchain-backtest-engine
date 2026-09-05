"""Infrastructure-neutral contracts for pins, leases, retention, and garbage collection."""

from __future__ import annotations

from dataclasses import dataclass

from backtest.application.models import ArtifactKind
from backtest.domain.identifiers import ArtifactId, ContentDigest, Identifier


class RetentionError(RuntimeError):
    """Base fail-closed retention error."""


class RetentionIntegrityError(RetentionError):
    """Retention authority is corrupt, incomplete, or has an unsupported schema."""


class RetentionConflictError(RetentionError):
    """An immutable retention identity already names different content."""


class GarbageCollectionPlanStaleError(RetentionError):
    """The filesystem authority changed after a dry-run plan was produced."""


@dataclass(frozen=True, slots=True)
class PinRecord:
    """One durable filesystem-authoritative pin and its verified lineage closure."""

    pin_id: Identifier
    roots: tuple[ArtifactId, ...]
    transitive_closure: tuple[ArtifactId, ...]
    reason: str
    created_at_ns: int
    # Declare record digest explicitly in the pin record contract.
    record_digest: ContentDigest

    def __post_init__(self) -> None:
        # Execute the pin record post init workflow in explicit, reviewable steps.
        if not self.roots:
            raise ValueError("a pin must have at least one root")
        if self.created_at_ns < 0:
            raise ValueError("pin creation time must be non-negative")
        if not self.reason or self.reason != self.reason.strip() or len(self.reason) > 500:
            # Fail the pin record post init path with ValueError for 500 characters
            # without outer whitespace when reason and strip is true; do not continue
            # ambiguously.
            raise ValueError("pin reason must be 1..500 characters without outer whitespace")
        if any(ord(character) < 32 for character in self.reason):
            raise ValueError("pin reason must not contain control characters")
        _require_sorted_unique(self.roots, label="pin roots")
        _require_sorted_unique(self.transitive_closure, label="pin closure")
        # Assemble closure once so the pin record post init workflow shares one value.
        closure = {item.hex for item in self.transitive_closure}
        if any(root.hex not in closure for root in self.roots):
            raise ValueError("pin closure must contain every root")


# Keep the artifact lease info contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ArtifactLeaseInfo:
    lease_id: Identifier
    roots: tuple[ArtifactId, ...]
    transitive_closure: tuple[ArtifactId, ...]
    # Declare reason explicitly in the artifact lease info contract.
    reason: str

    def __post_init__(self) -> None:
        # Execute the artifact lease info post init workflow in explicit, reviewable
        # steps.
        if not self.roots:
            raise ValueError("a lease must have at least one root")
        _require_sorted_unique(self.roots, label="lease roots")
        _require_sorted_unique(self.transitive_closure, label="lease closure")
        if any(root not in self.transitive_closure for root in self.roots):
            # Fail the artifact lease info post init path with ValueError for lease
            # closure must contain every root when root, transitive closure and roots is
            # true; do not continue ambiguously.
            raise ValueError("lease closure must contain every root")


@dataclass(frozen=True, slots=True)
class GarbageCollectionPolicy:
    """Host-owned hard retention bounds; a caller cannot weaken them."""

    minimum_artifact_age_ns: int
    trash_grace_period_ns: int
    maximum_sweep_bytes: int

    def __post_init__(self) -> None:
        # Execute the garbage collection policy post init workflow in explicit, reviewable
        # steps.
        if self.minimum_artifact_age_ns < 0 or self.trash_grace_period_ns < 0:
            raise ValueError("retention grace periods must be non-negative")
        if self.maximum_sweep_bytes <= 0:
            raise ValueError("maximum sweep size must be positive")


# Keep the garbage collection candidate contract and validation rules together.
@dataclass(frozen=True, slots=True)
class GarbageCollectionCandidate:
    artifact_id: ArtifactId
    kind: ArtifactKind
    size_bytes: int
    # Declare committed at ns explicitly in the garbage collection candidate contract.
    committed_at_ns: int
    tree_digest: ContentDigest

    def __post_init__(self) -> None:
        # Execute the garbage collection candidate post init workflow in explicit,
        # reviewable steps.
        if self.size_bytes < 0 or self.committed_at_ns < 0:
            raise ValueError("candidate size and commit time must be non-negative")


@dataclass(frozen=True, slots=True)
class GarbageCollectionPlan:
    """Immutable dry-run result; execution must revalidate it under exclusion."""

    plan_id: ContentDigest
    planned_at_ns: int
    policy: GarbageCollectionPolicy
    retained_roots: tuple[ArtifactId, ...]
    pinned_roots: tuple[ArtifactId, ...]
    # Declare candidates explicitly in the garbage collection plan contract.
    candidates: tuple[GarbageCollectionCandidate, ...]

    def __post_init__(self) -> None:
        # Execute the garbage collection plan post init workflow in explicit, reviewable
        # steps.
        if self.planned_at_ns < 0:
            raise ValueError("GC plan time must be non-negative")
        _require_sorted_unique(self.retained_roots, label="retained roots")
        _require_sorted_unique(self.pinned_roots, label="pinned roots")
        candidate_ids = tuple(item.artifact_id for item in self.candidates)
        # Invoke _require_sorted_unique for gc candidates and candidate ids as a visible
        # garbage collection plan post init step.
        _require_sorted_unique(candidate_ids, label="GC candidates")
        if sum(item.size_bytes for item in self.candidates) > self.policy.maximum_sweep_bytes:
            raise ValueError("GC plan exceeds its host-owned sweep ceiling")

    @property
    def reclaimable_bytes(self) -> int:
        # Return the completed garbage collection plan reclaimable bytes result without a
        # hidden fallback.
        return sum(item.size_bytes for item in self.candidates)


# Keep the garbage collection batch contract and validation rules together.
@dataclass(frozen=True, slots=True)
class GarbageCollectionBatch:
    batch_id: ContentDigest
    plan_id: ContentDigest
    moved_at_ns: int
    # Declare purge not before ns explicitly in the garbage collection batch contract.
    purge_not_before_ns: int
    artifact_ids: tuple[ArtifactId, ...]

    def __post_init__(self) -> None:
        # Execute the garbage collection batch post init workflow in explicit, reviewable
        # steps.
        if self.moved_at_ns < 0 or self.purge_not_before_ns < self.moved_at_ns:
            raise ValueError("invalid GC batch grace interval")
        _require_sorted_unique(self.artifact_ids, label="GC batch artifacts")


# Keep the garbage collection receipt contract and validation rules together.
@dataclass(frozen=True, slots=True)
class GarbageCollectionReceipt:
    receipt_digest: ContentDigest
    batch_id: ContentDigest
    deleted_at_ns: int
    # Declare artifact ids explicitly in the garbage collection receipt contract.
    artifact_ids: tuple[ArtifactId, ...]
    deleted_bytes: int

    def __post_init__(self) -> None:
        # Execute the garbage collection receipt post init workflow in explicit,
        # reviewable steps.
        if self.deleted_at_ns < 0 or self.deleted_bytes < 0:
            raise ValueError("invalid deletion receipt counters")
        _require_sorted_unique(self.artifact_ids, label="deleted artifacts")


def _require_sorted_unique(values: tuple[ArtifactId, ...], *, label: str) -> None:
    # Execute the require sorted unique workflow in explicit, reviewable steps.
    hexes = tuple(item.hex for item in values)
    if hexes != tuple(sorted(hexes)) or len(hexes) != len(set(hexes)):
        raise ValueError(f"{label} must be sorted and unique")


__all__ = [
    "ArtifactLeaseInfo",
    # Keep the garbage collection batch component named inside the all contract.
    "GarbageCollectionBatch",
    "GarbageCollectionCandidate",
    "GarbageCollectionPlan",
    "GarbageCollectionPlanStaleError",
    "GarbageCollectionPolicy",
    # Keep the garbage collection receipt component named inside the all contract.
    "GarbageCollectionReceipt",
    "PinRecord",
    "RetentionConflictError",
    "RetentionError",
    "RetentionIntegrityError",
    # Complete the all group only after its semantic components are visible.
]
