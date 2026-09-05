"""Infrastructure-neutral historical replay contracts consumed by the engine."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from backtest.domain.chain import ChainPosition, boundary_coordinates

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import (
    ContentDigest,
    DatasetRevisionId,
    LogicalContentHash,
    NetworkId,
    # Include position schema id so the identifiers dependency remains explicit.
    PositionSchemaId,
)
from backtest.domain.market_events import CanonicalEvent
from backtest.domain.time import BlockRange
from backtest.engine.transaction_clock import CompactTransactionClock


# Keep the replay boundary contract and validation rules together.
@dataclass(frozen=True, slots=True, order=True)
class ReplayBoundary:
    network_id: NetworkId
    position_schema_id: PositionSchemaId
    boundary_ordinal: int
    # Declare block ordinal explicitly in the replay boundary contract.
    block_ordinal: int

    def __post_init__(self) -> None:
        # Execute the replay boundary post init workflow in explicit, reviewable steps.
        if not isinstance(self.network_id, NetworkId):
            raise TypeError("network_id must be a NetworkId")
        if not isinstance(self.position_schema_id, PositionSchemaId):
            raise TypeError("position_schema_id must be a PositionSchemaId")
        decoded_block, _ = boundary_coordinates(
            # Pass self explicitly so boundary_coordinates receives a reviewable boundary
            # ordinal and position schema id input in replay boundary post init.
            self.boundary_ordinal,
            position_schema_id=self.position_schema_id,
        )
        if decoded_block != self.block_ordinal:
            raise ValueError("replay boundary block does not match its ordinal")

    # Apply classmethod semantics to the following replay boundary from position contract.
    @classmethod
    def from_position(cls, position: ChainPosition) -> ReplayBoundary:
        # Execute the replay boundary from position workflow in explicit, reviewable
        # steps.
        if not isinstance(position, ChainPosition):
            raise TypeError("position must be a ChainPosition")
        return cls(
            network_id=position.network_id,
            position_schema_id=position.position_schema_id,
            # Pass boundary ordinal explicitly so cls receives a reviewable network id and
            # position schema id input in replay boundary from position.
            boundary_ordinal=position.boundary_ordinal,
            block_ordinal=position.block_ordinal,
        )

    @property
    def transaction_index(self) -> int:
        # Execute the replay boundary transaction index workflow in explicit, reviewable
        # steps.
        _, transaction_index = boundary_coordinates(
            self.boundary_ordinal,
            position_schema_id=self.position_schema_id,
        )
        return transaction_index

    # Apply property semantics to the following replay boundary chain position contract.
    @property
    def chain_position(self) -> ChainPosition:
        # Execute the replay boundary chain position workflow in explicit, reviewable
        # steps.
        return ChainPosition(
            network_id=self.network_id,
            position_schema_id=self.position_schema_id,
            block_ordinal=self.block_ordinal,
            transaction_index=self.transaction_index,
            # Pass event index explicitly so ChainPosition receives a reviewable network
            # id and position schema id input in replay boundary chain position.
            event_index=None,
        )

    @property
    def slot(self) -> int:
        """Deprecated read-only bridge for slot-shaped internal callers."""

        return self.block_ordinal


@dataclass(frozen=True, slots=True, order=True)
class ObservationDelivery:
    """One materialized observation release referencing a canonical event row."""

    release_boundary_ordinal: int
    event_row_index: int

    def __post_init__(self) -> None:
        # Execute the observation delivery post init workflow in explicit, reviewable
        # steps.
        if self.release_boundary_ordinal < 0 or self.event_row_index < 0:
            raise ValueError("observation delivery coordinates must be non-negative")


# Keep the historical event source contract and validation rules together.
@runtime_checkable
class HistoricalEventSource(Protocol):
    @property
    def dataset_revision_id(self) -> DatasetRevisionId: ...

    @property
    # Define historical event source logical content hash as one focused operation with an
    # explicit boundary.
    def logical_content_hash(self) -> LogicalContentHash: ...

    @property
    def replay_semantics_id(self) -> ContentDigest: ...

    def boundaries(self) -> tuple[ReplayBoundary, ...]: ...

    def events(self) -> Iterator[CanonicalEvent]: ...


# Apply runtime checkable semantics to the following indexed historical event source
# contract.
@runtime_checkable
class IndexedHistoricalEventSource(HistoricalEventSource, Protocol):
    """ReplayPack-style source with stable canonical row addressing."""

    @property
    def event_count(self) -> int: ...

    def event_at(self, event_row_index: int) -> CanonicalEvent: ...


@runtime_checkable
class TransactionClockEventSource(HistoricalEventSource, Protocol):
    """Network-aware source exposing an exact compact block clock."""

    @property
    def decision_range(self) -> BlockRange: ...

    def transaction_clock(self) -> CompactTransactionClock: ...


@runtime_checkable
class ObservationDeliverySource(Protocol):
    """Core-owned sequential stream used instead of per-event scheduler heap items."""

    @property
    def input_event_count(self) -> int: ...

    @property
    def delivery_count(self) -> int: ...

    @property
    # Define observation delivery source outside horizon count as one focused operation
    # with an explicit boundary.
    def outside_horizon_count(self) -> int: ...

    def deliveries(self) -> Iterator[ObservationDelivery]: ...


@runtime_checkable
class ColumnarObservationDeliverySource(ObservationDeliverySource, Protocol):
    """Optional zero-copy columns for array-specialized sequential engines."""

    def delivery_columns(self) -> tuple[Sequence[int], Sequence[int]]:
        """Return release-boundary and event-row columns in scheduler order."""
        ...


__all__ = [
    "ColumnarObservationDeliverySource",
    "HistoricalEventSource",
    "IndexedHistoricalEventSource",
    # Keep the observation delivery component named inside the all contract.
    "ObservationDelivery",
    "ObservationDeliverySource",
    "ReplayBoundary",
    "TransactionClockEventSource",
]
