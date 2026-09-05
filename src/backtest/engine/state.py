"""Separated historical, observed and simulated venue state reducers."""

from __future__ import annotations

from dataclasses import dataclass

from backtest.domain.execution import ExecutionMode, VenueTransition
from backtest.domain.fidelity import OrderingFidelity
from backtest.domain.identifiers import AssetId, PoolId

# Import market events at the visible module dependency boundary.
from backtest.domain.market_events import (
    BlockEvent,
    CanonicalEvent,
    SwapEvent,
    TokenCreationEvent,
    # Close the market events import after its required symbols are visible.
)


class HistoricalStateError(RuntimeError):
    """A canonical group cannot be applied atomically."""


@dataclass(frozen=True, slots=True)
class PoolSnapshot:
    pool_id: PoolId
    asset_a_id: AssetId
    asset_b_id: AssetId
    # Declare reserve a atomic explicitly in the pool snapshot contract.
    reserve_a_atomic: int
    reserve_b_atomic: int
    boundary_ordinal: int

    def __post_init__(self) -> None:
        # Execute the pool snapshot post init workflow in explicit, reviewable steps.
        if self.asset_a_id == self.asset_b_id:
            raise ValueError("pool assets must be different")
        if self.reserve_a_atomic < 0 or self.reserve_b_atomic < 0:
            raise ValueError("pool reserves must be non-negative")


@dataclass(frozen=True, slots=True)
# Keep the venue state commit contract and validation rules together.
class VenueStateCommit:
    """Opaque, validated candidate for atomic engine commit."""

    pools: dict[PoolId, PoolSnapshot]


class HistoricalReferenceState:
    """State changed exclusively by committed historical groups."""

    def __init__(self) -> None:
        # Execute the historical reference state init workflow in explicit, reviewable
        # steps.
        self._pools: dict[PoolId, PoolSnapshot] = {}
        self._assets: set[AssetId] = set()
        self._block_times_ns: dict[int, int] = {}

    def apply_group(self, events: tuple[CanonicalEvent, ...]) -> None:
        # Execute the historical reference state apply group workflow in explicit,
        # reviewable steps.
        if not events:
            raise HistoricalStateError("historical group must not be empty")
        boundary = events[0].envelope.boundary_ordinal
        group_id = events[0].envelope.transaction_group_id
        if any(
            # Pass event explicitly so any receives a reviewable boundary ordinal and
            # transaction group id input in historical reference state apply group.
            event.envelope.boundary_ordinal != boundary
            or event.envelope.transaction_group_id != group_id
            for event in events
        ):
            raise HistoricalStateError("historical group contains mixed boundaries or identities")
        # Evaluate the complete historical reference state apply group ordering fidelity,
        # event and events condition before guarded effects.
        if any(
            event.envelope.ordering_fidelity
            not in {
                OrderingFidelity.TRANSACTION_EXACT,
                OrderingFidelity.INSTRUCTION_EXACT,
                # Close the ordering fidelity and envelope payload only after all historical
                # reference state apply group fields are present.
            }
            for event in events
        ):
            # Handle the historical reference state apply group ordering fidelity, event
            # and events condition as a distinct block.
            raise HistoricalStateError(
                "historical group ordering is ambiguous and has no invariant reducer"
            )
        candidate_pools = dict(self._pools)
        candidate_assets = set(self._assets)
        # Assemble candidate times once so the historical reference state apply group
        # workflow shares one value.
        candidate_times = dict(self._block_times_ns)
        for event in events:
            # Process events inside the bounded historical reference state apply group
            # loop.
            if isinstance(event, BlockEvent):
                # Handle the historical reference state apply group isinstance(event,
                # BlockEvent) branch as a distinct logical block.
                if event.block_time_ns is not None:
                    candidate_times[boundary] = event.block_time_ns
            # Handle the historical reference state apply group complement of
            # isinstance(event, BlockEvent) explicitly.
            elif isinstance(event, TokenCreationEvent):
                candidate_assets.add(event.asset_id)
            # Handle the historical reference state apply group complement of
            # isinstance(event, TokenCreationEvent) explicitly.
            elif isinstance(event, SwapEvent):
                # Handle the historical reference state apply group isinstance(event,
                # SwapEvent) branch as a distinct logical block.
                candidate_assets.update((event.pool_asset_a_id, event.pool_asset_b_id))
                if event.reserve_a_after_atomic is not None:
                    if event.reserve_b_after_atomic is None:  # pragma: no cover - domain invariant
                        raise HistoricalStateError("swap reserve pair is incomplete")
                    candidate_pools[event.pool_id] = PoolSnapshot(
                        pool_id=event.pool_id,
                        asset_a_id=event.pool_asset_a_id,
                        asset_b_id=event.pool_asset_b_id,
                        # Pass reserve a atomic explicitly so PoolSnapshot receives a
                        # reviewable pool id and pool asset a id input in historical
                        # reference state apply group.
                        reserve_a_atomic=event.reserve_a_after_atomic,
                        reserve_b_atomic=event.reserve_b_after_atomic,
                        boundary_ordinal=boundary,
                    )
        self._pools = candidate_pools
        # Assemble self assets once so the historical reference state apply group workflow
        # shares one value.
        self._assets = candidate_assets
        self._block_times_ns = candidate_times

    def pool(self, pool_id: PoolId) -> PoolSnapshot | None:
        return self._pools.get(pool_id)

    def block_time_ns(self, boundary_ordinal: int) -> int | None:
        # Return the completed historical reference state block time ns result without a
        # hidden fallback.
        return self._block_times_ns.get(boundary_ordinal)


class ObservedState:
    """Only information already delivered to the strategy."""

    def __init__(self) -> None:
        # Execute the observed state init workflow in explicit, reviewable steps.
        self._pools: dict[PoolId, PoolSnapshot] = {}
        self._assets: set[AssetId] = set()

    def apply(self, event: CanonicalEvent) -> None:
        # Execute the observed state apply workflow in explicit, reviewable steps.
        if isinstance(event, TokenCreationEvent):
            self._assets.add(event.asset_id)
        # Handle the observed state apply complement of isinstance(event,
        # TokenCreationEvent) explicitly.
        elif isinstance(event, SwapEvent) and event.reserve_a_after_atomic is not None:
            if event.reserve_b_after_atomic is None:  # pragma: no cover - domain invariant
                raise HistoricalStateError("observed swap reserve pair is incomplete")
            self._pools[event.pool_id] = PoolSnapshot(
                pool_id=event.pool_id,
                asset_a_id=event.pool_asset_a_id,
                asset_b_id=event.pool_asset_b_id,
                # Pass reserve a atomic explicitly so PoolSnapshot receives a reviewable
                # pool id and pool asset a id input in observed state apply.
                reserve_a_atomic=event.reserve_a_after_atomic,
                reserve_b_atomic=event.reserve_b_after_atomic,
                boundary_ordinal=event.envelope.boundary_ordinal,
            )

    def pool(self, pool_id: PoolId) -> PoolSnapshot | None:
        # Return the completed observed state pool result without a hidden fallback.
        return self._pools.get(pool_id)

    def knows_asset(self, asset_id: AssetId) -> bool:
        return asset_id in self._assets


class SimulationVenueState:
    """Own-order state, always physically separate from historical reference."""

    def __init__(self, mode: ExecutionMode) -> None:
        # Execute the simulation venue state init workflow in explicit, reviewable steps.
        self.mode = mode
        self._pools: dict[PoolId, PoolSnapshot] = {}

    def reconcile_group(
        self,
        events: tuple[CanonicalEvent, ...],
        # Keep the historical input explicit in the reconcile group contract.
        historical: HistoricalReferenceState,
    ) -> None:
        # Execute the simulation venue state reconcile group workflow in explicit,
        # reviewable steps.
        touched = {event.pool_id for event in events if isinstance(event, SwapEvent)}
        for pool_id in touched:
            # Process touched inside the bounded simulation venue state reconcile group
            # loop.
            historical_pool = historical.pool(pool_id)
            if historical_pool is None:
                continue
            if self.mode in {
                ExecutionMode.EXOGENOUS_REPLAY,
                # Keep execution mode visible while evaluating the mode, exogenous replay
                # and shadow state replay guard.
                ExecutionMode.SHADOW_STATE_REPLAY,
            }:
                self._pools[pool_id] = historical_pool
            else:
                # Handle the simulation venue state reconcile group complement of mode,
                # exogenous replay and shadow state replay explicitly.
                raise HistoricalStateError(
                    "conditional protocol replay requires a protocol-specific fork reducer"
                )

    def pool(self, pool_id: PoolId) -> PoolSnapshot | None:
        return self._pools.get(pool_id)

    # Define simulation venue state apply transition as one focused operation with an
    # explicit boundary.
    def apply_transition(self, transition: VenueTransition) -> None:
        self.commit(self.preview_transition(transition))

    def preview_transition(self, transition: VenueTransition) -> VenueStateCommit:
        # Execute the simulation venue state preview transition workflow in explicit,
        # reviewable steps.
        current = self._pools.get(transition.pool_id)
        if current is None:
            raise HistoricalStateError("venue transition references an unknown pool")
        if self.mode is ExecutionMode.EXOGENOUS_REPLAY:
            return VenueStateCommit(dict(self._pools))
        # Assemble candidate once so the simulation venue state preview transition
        # workflow shares one value.
        candidate = dict(self._pools)
        candidate[transition.pool_id] = PoolSnapshot(
            pool_id=current.pool_id,
            asset_a_id=current.asset_a_id,
            asset_b_id=current.asset_b_id,
            # Pass reserve a atomic explicitly so PoolSnapshot receives a reviewable pool
            # id and asset a id input in simulation venue state preview transition.
            reserve_a_atomic=transition.reserve_a_after_atomic,
            reserve_b_atomic=transition.reserve_b_after_atomic,
            boundary_ordinal=current.boundary_ordinal,
        )
        return VenueStateCommit(candidate)

    # Define simulation venue state commit as one focused operation with an explicit
    # boundary.
    def commit(self, candidate: VenueStateCommit) -> None:
        self._pools = dict(candidate.pools)


__all__ = [
    "HistoricalReferenceState",
    "HistoricalStateError",
    # Keep the observed state component named inside the all contract.
    "ObservedState",
    "PoolSnapshot",
    "SimulationVenueState",
    "VenueStateCommit",
]
