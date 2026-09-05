"""Outbound port for canonical Parquet distributions and snapshot roots."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import datetime
from typing import Protocol, runtime_checkable

from backtest.application.canonical_data import (
    # Include canonical distribution ref so the canonical data dependency remains
    # explicit.
    CanonicalDistributionRef,
    PreparedSnapshot,
    ProjectedEventBatch,
)
from backtest.application.models import DatasetPlan, DatasetShard, DatasetSpec, PlannedCapability

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import ArtifactId, BundleId, NetworkId, PositionSchemaId
from backtest.domain.market_events import CanonicalEvent, EventKind
from backtest.engine.transaction_clock import CompactTransactionClock


# Keep the canonical snapshot candidate contract and validation rules together.
@runtime_checkable
class CanonicalSnapshotCandidate(Protocol):
    @property
    def network_id(self) -> NetworkId: ...

    @property
    # Define canonical snapshot candidate position schema id as one focused operation with
    # an explicit boundary.
    def position_schema_id(self) -> PositionSchemaId: ...

    def transaction_clock(self) -> CompactTransactionClock: ...

    def events(self) -> Iterator[CanonicalEvent]: ...


# Keep the canonical snapshot validator contract and validation rules together.
@runtime_checkable
class CanonicalSnapshotValidator(Protocol):
    def validate_snapshot_candidate(
        self,
        spec: DatasetSpec,
        # Keep the candidate input explicit in the validate snapshot candidate contract.
        candidate: CanonicalSnapshotCandidate,
    ) -> None: ...


# Keep the canonical snapshot store contract and validation rules together.
@runtime_checkable
class CanonicalSnapshotStore(Protocol):
    def open_reusable_distribution(
        self,
        *,
        # Keep the artifact id input explicit in the open reusable distribution contract.
        artifact_id: ArtifactId,
        plan: DatasetPlan,
        shard: DatasetShard,
        capability: PlannedCapability,
        event_kind: EventKind,
        # Keep the projector bundle id input explicit in the open reusable distribution
        # contract.
        projector_bundle_id: BundleId,
    ) -> CanonicalDistributionRef: ...

    def publish_distribution(
        self,
        *,
        # Keep the plan input explicit in the publish distribution contract.
        plan: DatasetPlan,
        shard: DatasetShard,
        capability: PlannedCapability,
        event_kind: EventKind,
        projector_bundle_id: BundleId,
        # Keep the batches input explicit in the publish distribution contract.
        batches: Iterable[ProjectedEventBatch],
        extracted_at: datetime,
    ) -> CanonicalDistributionRef: ...

    def publish_snapshot(
        self,
        # Close the publish snapshot signature after its explicit inputs.
        *,
        plan: DatasetPlan,
        projector_bundle_id: BundleId,
        distributions: tuple[CanonicalDistributionRef, ...],
        extracted_at: datetime,
        # Keep the validator input explicit in the publish snapshot contract.
        validator: CanonicalSnapshotValidator | None = None,
    ) -> PreparedSnapshot: ...


__all__ = [
    "CanonicalSnapshotCandidate",
    "CanonicalSnapshotStore",
    # Keep the canonical snapshot validator component named inside the all contract.
    "CanonicalSnapshotValidator",
]
