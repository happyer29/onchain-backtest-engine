"""Replaceable execution seams for the generic launchpad-sniping use case."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from backtest.application.models import DatasetSpec

# Import runs at the visible module dependency boundary.
from backtest.application.ports.runs import RuntimeComponentReceipt
from backtest.application.run_specs import ResolvedRunSpec
from backtest.domain.identifiers import NetworkId, PositionSchemaId
from backtest.domain.time import BlockRange
from backtest.engine.contracts import EnginePhysicalSettings

# Import replay at the visible module dependency boundary.
from backtest.engine.replay import HistoricalEventSource, ObservationDeliverySource
from backtest.engine.sniping import SnipingRunConfig, SnipingRunSummary
from backtest.engine.sniping_contracts import (
    SnipingNetworkCostModel,
    SnipingProtocolRuntime,
    # Include sniping run event sink so the sniping contracts dependency remains explicit.
    SnipingRunEventSink,
    SnipingStrategyInstance,
)
from backtest.engine.transaction_clock import CompactTransactionClock
from backtest.engine.wallet_accounts import WalletUvaInitialState


# Apply dataclass semantics to the following resolved sniping runtime components contract.
@dataclass(frozen=True, slots=True)
class ResolvedSnipingRuntimeComponents:
    """Exact runtime instances plus receipts for one sniping semantic closure."""

    strategy: SnipingStrategyInstance
    protocol: SnipingProtocolRuntime
    network_costs: SnipingNetworkCostModel
    initial_uva_state: WalletUvaInitialState
    wallet_account_profile_id: str
    uva_schema_id: str
    maximum_dynamic_items: int
    receipts: tuple[RuntimeComponentReceipt, ...]

    def __post_init__(self) -> None:
        # Execute the resolved sniping runtime components post init workflow in explicit,
        # reviewable steps.
        ordered = tuple(sorted(self.receipts, key=lambda item: item.role))
        if ordered != self.receipts or len({item.role for item in ordered}) != len(ordered):
            raise ValueError("runtime receipts must be sorted and unique by role")
        if not isinstance(self.initial_uva_state, WalletUvaInitialState):
            raise TypeError("initial_uva_state must be resolved")
        # Traverse wallet account profile id and UVA schema id explicitly so
        # each resolved sniping runtime components post init iteration remains traceable.
        for field_name in ("wallet_account_profile_id", "uva_schema_id"):
            # Process wallet account profile id and token account schema id inside the
            # bounded resolved sniping runtime components post init loop.
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
                raise ValueError(f"{field_name} must be non-empty, trimmed and NUL-free")
        if (
            isinstance(self.maximum_dynamic_items, bool)
            # Keep isinstance visible while evaluating the isinstance and maximum dynamic
            # items guard.
            or not isinstance(self.maximum_dynamic_items, int)
            or self.maximum_dynamic_items <= 0
        ):
            raise ValueError("maximum_dynamic_items must be positive")


@runtime_checkable
# Keep the sniping historical event source contract and validation rules together.
class SnipingHistoricalEventSource(HistoricalEventSource, Protocol):
    """Verified event stream paired with its compact all-transaction clock."""

    @property
    def dataset_spec(self) -> DatasetSpec: ...

    @property
    def decision_range(self) -> BlockRange: ...

    @property
    # Define sniping historical event source network id as one focused operation with an
    # explicit boundary.
    def network_id(self) -> NetworkId: ...

    @property
    def position_schema_id(self) -> PositionSchemaId: ...

    def transaction_clock(self) -> CompactTransactionClock: ...


# Keep the sniping historical event source factory contract and validation rules together.
@runtime_checkable
class SnipingHistoricalEventSourceFactory(Protocol):
    def open_resolved(
        self,
        spec: ResolvedRunSpec,
        # Keep the abstract context manager step explicit within the sniping historical event
        # source factory open resolved workflow.
    ) -> AbstractContextManager[SnipingHistoricalEventSource]: ...


@runtime_checkable
class SnipingRuntimeComponentsResolver(Protocol):
    def resolve(self, spec: ResolvedRunSpec) -> ResolvedSnipingRuntimeComponents: ...


# Keep the sniping backtest engine contract and validation rules together.
@runtime_checkable
class SnipingBacktestEngine(Protocol):
    backend_name: str

    def run(
        self,
        # Close the run signature after its explicit inputs.
        *,
        source: HistoricalEventSource,
        clock: CompactTransactionClock,
        strategy: SnipingStrategyInstance,
        protocol: SnipingProtocolRuntime,
        # Keep the network costs input explicit in the run contract.
        network_costs: SnipingNetworkCostModel,
        config: SnipingRunConfig,
        sink: SnipingRunEventSink | None = None,
        delivery_schedule: ObservationDeliverySource | None = None,
        physical_settings: EnginePhysicalSettings = ...,
        # Keep the sniping run summary step explicit within the sniping backtest engine run
        # workflow.
    ) -> SnipingRunSummary: ...


__all__ = [
    "ResolvedSnipingRuntimeComponents",
    "SnipingBacktestEngine",
    "SnipingHistoricalEventSource",
    # Keep the sniping historical event source factory component named inside the all
    # contract.
    "SnipingHistoricalEventSourceFactory",
    "SnipingRuntimeComponentsResolver",
]
