"""Narrow plugin contracts consumed by the deterministic engine."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from backtest.domain.execution import ExecutionMode, ExecutionNotification, ExecutionPlan, Fill

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import AssetId, BundleId, ContentDigest, PoolId
from backtest.domain.intents import Intent, SwapExactInIntent
from backtest.domain.ledger import LedgerTransaction
from backtest.domain.market_events import CanonicalEvent
from backtest.engine.causal_data import CausalScalarView, EmptyCausalScalarProvider

# Import portfolio at the visible module dependency boundary.
from backtest.engine.portfolio import PortfolioState
from backtest.engine.rng import KeyedRng
from backtest.engine.scheduler import SchedulerInstant
from backtest.engine.state import ObservedState, PoolSnapshot, SimulationVenueState


@dataclass(frozen=True, slots=True)
# Keep the engine physical settings contract and validation rules together.
class EnginePhysicalSettings:
    """Operational reader settings excluded from logical run semantics."""

    reader_batch_rows: int = 65_536
    reader_readahead: int = 1
    threads: int = 1

    def __post_init__(self) -> None:
        # Execute the engine physical settings post init workflow in explicit, reviewable
        # steps.
        if (
            isinstance(self.reader_batch_rows, bool)
            or not isinstance(self.reader_batch_rows, int)
            or self.reader_batch_rows <= 0
        ):
            # Fail the engine physical settings post init path with ValueError for reader
            # batch rows must be a positive integer when isinstance and reader batch rows
            # is true; do not continue ambiguously.
            raise ValueError("reader batch rows must be a positive integer")
        if self.reader_readahead not in {1, 2, 4}:
            raise ValueError("reader readahead must be one of 1, 2 or 4")
        if isinstance(self.threads, bool) or not isinstance(self.threads, int) or self.threads <= 0:
            raise ValueError("engine threads must be a positive integer")


# Bind default engine physical settings once as an explicit module-level contract.
DEFAULT_ENGINE_PHYSICAL_SETTINGS = EnginePhysicalSettings()


class PortfolioView:
    """Read-only facade; strategy code cannot apply ledger transactions."""

    def __init__(self, state: PortfolioState) -> None:
        self._state = state

    def available(self, asset_id: AssetId) -> int:
        return self._state.available(asset_id)

    def reserved(self, asset_id: AssetId) -> int:
        # Return the completed portfolio view reserved result without a hidden fallback.
        return self._state.reserved(asset_id)


class ObservedMarketView:
    """Read-only observed-state facade exposed to strategy plugins."""

    def __init__(self, state: ObservedState) -> None:
        self._state = state

    def pool(self, pool_id: PoolId) -> PoolSnapshot | None:
        return self._state.pool(pool_id)

    def knows_asset(self, asset_id: AssetId) -> bool:
        # Return the completed observed market view knows asset result without a hidden
        # fallback.
        return self._state.knows_asset(asset_id)


# Keep the strategy context contract and validation rules together.
@dataclass(frozen=True, slots=True)
class StrategyContext:
    instant: SchedulerInstant
    observed_market: ObservedMarketView
    portfolio: PortfolioView
    # Declare rng explicitly in the strategy context contract.
    rng: KeyedRng
    features: CausalScalarView = field(
        default_factory=lambda: CausalScalarView(EmptyCausalScalarProvider(), 0)
    )
    predictions: CausalScalarView = field(
        # Keep the causal scalar view and empty causal scalar provider CausalScalarView
        # step visible while building predictions.
        default_factory=lambda: CausalScalarView(EmptyCausalScalarProvider(), 0)
    )
    event_row_id: int | None = None

    def __post_init__(self) -> None:
        # Execute the strategy context post init workflow in explicit, reviewable steps.
        if self.event_row_id is not None and self.event_row_id < 0:
            raise ValueError("strategy event row ID must be non-negative")


# Keep the strategy instance contract and validation rules together.
@runtime_checkable
class StrategyInstance(Protocol):
    @property
    def bundle_id(self) -> BundleId: ...

    @property
    # Define strategy instance component id as one focused operation with an explicit
    # boundary.
    def component_id(self) -> ContentDigest: ...

    def on_event(
        self,
        event: CanonicalEvent,
        context: StrategyContext,
        # Keep the iterable step explicit within the strategy instance on event workflow.
    ) -> Iterable[Intent]: ...

    def on_execution(
        self,
        notification: ExecutionNotification,
        context: StrategyContext,
        # Keep the expr step explicit within the strategy instance on execution workflow.
    ) -> None: ...


# Keep the venue execution model contract and validation rules together.
@runtime_checkable
class VenueExecutionModel(Protocol):
    @property
    def bundle_id(self) -> BundleId: ...

    def execute(
        # Keep the remaining execute inputs visible at the venue execution model execute
        # boundary.
        self,
        intent: SwapExactInIntent,
        venue_state: SimulationVenueState,
        *,
        boundary_ordinal: int,
        # Keep the mode input explicit in the execute contract.
        mode: ExecutionMode,
    ) -> ExecutionPlan: ...


# Keep the risk policy contract and validation rules together.
@runtime_checkable
class RiskPolicy(Protocol):
    @property
    def bundle_id(self) -> BundleId: ...

    def accept(self, intent: SwapExactInIntent, portfolio: PortfolioView) -> bool: ...


# Keep the run event sink contract and validation rules together.
@runtime_checkable
class RunEventSink(Protocol):
    def append_audit(self, record: dict[str, object]) -> None: ...

    def append_ledger(self, transaction: LedgerTransaction) -> None: ...

    def append_fill(self, fill: Fill) -> None: ...


# Apply runtime checkable semantics to the following canonical audit bytes sink contract.
@runtime_checkable
class CanonicalAuditBytesSink(Protocol):
    """Optional fast sink for engine-authored canonical audit JSON.

    Indexed columns are supplied separately so a columnar sink never needs to
    parse the JSON record.  This is an optimization of representation only; the
    canonical record bytes and stream framing remain identical to ``append_audit``.
    """

    def append_canonical_audit(
        self,
        record_json: bytes,
        *,
        boundary_ordinal: int,
        # Keep the phase input explicit in the append canonical audit contract.
        phase: int,
        record_type: str,
    ) -> None: ...


__all__ = [
    "DEFAULT_ENGINE_PHYSICAL_SETTINGS",
    # Keep the canonical audit bytes sink component named inside the all contract.
    "CanonicalAuditBytesSink",
    "EnginePhysicalSettings",
    "ObservedMarketView",
    "PortfolioView",
    "RiskPolicy",
    # Keep the run event sink component named inside the all contract.
    "RunEventSink",
    "StrategyContext",
    "StrategyInstance",
    "VenueExecutionModel",
]
