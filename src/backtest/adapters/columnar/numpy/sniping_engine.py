"""Dedicated sequential NumPy mmap backend for exact Pump.fun sniping.

The readable engine remains the semantic oracle.  This adapter specializes the
same resolved strategy/protocol/network stack, scans verified ReplayPack v3
arrays directly and keeps historical curve/cooldown state in primitive SoA
arenas.  Canonical event objects are never decoded in the historical hot loop.
"""

from __future__ import annotations

import heapq
import json
from binascii import hexlify
from collections.abc import Iterator, Mapping, Sequence

# Import dataclasses at the visible module dependency boundary.
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Protocol, cast, runtime_checkable

import numpy as np
import numpy.typing as npt

# Import numpy at the visible module dependency boundary.
from backtest.adapters.columnar.numpy import layout as physical
from backtest.adapters.columnar.numpy.reader import NumpyMmapReplaySource
from backtest.domain.account_requirements import AccountComponentRecord, AccountRequirement
from backtest.domain.chain import ChainIdentityMismatchError, ChainPosition
from backtest.domain.execution import Fill
from backtest.domain.hashing import domain_digest

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import (
    AccountId,
    AssetId,
    ContentDigest,
    ProtocolPayloadSchemaId,
    # Include venue id so the identifiers dependency remains explicit.
    VenueId,
)
from backtest.domain.intents import RoundTripIntent
from backtest.domain.ledger import LedgerTransaction
from backtest.domain.market_events import EventKind

# Import roundtrips at the visible module dependency boundary.
from backtest.domain.roundtrips import (
    MtmStatus,
    QuoteLiquidityEvidenceRecord,
    RoundTripRecord,
    RoundTripStatus,
    # Close the roundtrips import after its required symbols are visible.
)
from backtest.engine.audit import CanonicalStreamHasher, fill_document, ledger_document
from backtest.engine.contracts import DEFAULT_ENGINE_PHYSICAL_SETTINGS, EnginePhysicalSettings
from backtest.engine.portfolio import PortfolioInvariantError, PortfolioState
from backtest.engine.replay import (
    # Include columnar observation delivery source so the replay dependency remains
    # explicit.
    ColumnarObservationDeliverySource,
    HistoricalEventSource,
    ObservationDeliverySource,
)
from backtest.engine.scheduler import SchedulerPhase

# Import sniping at the visible module dependency boundary.
from backtest.engine.sniping import (
    SNIPING_EXECUTION_MODES,
    NullSnipingRunEventSink,
    SnipingEngineError,
    SnipingEngineErrorCode,
    SnipingRunConfig,
    # Include sniping run summary so the sniping dependency remains explicit.
    SnipingRunSummary,
    _amount_if_asset,
    _asset_amount,
    _asset_amounts_document,
    _buy_leg,
    _buy_reservation,
    # Include correlated ledger cashflows so the sniping dependency remains explicit.
    _CorrelatedLedgerCashflows,
    _failed_buy_settlement,
    _failed_sell_settlement,
    _fill,
    _has_available,
    # Include minimum output atomic so the sniping dependency remains explicit.
    _minimum_output_atomic,
    _optional_quote_liquidity_record,
    _quote_liquidity_record,
    _reserve_buy,
    _reserve_sell,
    _RoundTripAggregateAccumulator,
    _RoundTripState,
    # Include sell leg so the sniping dependency remains explicit.
    _sell_leg,
    _sell_reservation,
    _settled_synthetic_funded_atomic,
    _settled_venue_funded_atomic,
    _successful_buy_settlement,
    _successful_sell_settlement,
    _validate_buy_quote,
    # Include validate sell quote so the sniping dependency remains explicit.
    _validate_sell_quote,
)
from backtest.engine.sniping_contracts import (
    LaunchDecision,
    LaunchDecisionStatus,
    # Include launch target so the sniping contracts dependency remains explicit.
    LaunchTarget,
    NetworkCostQuote,
    ProtocolExecutionRejected,
    ProtocolQuote,
    SnipingNetworkCostModel,
    # Include sniping protocol runtime so the sniping contracts dependency remains
    # explicit.
    SnipingProtocolRuntime,
    SnipingRunEventSink,
    SnipingStrategyInstance,
    ValuationQuote,
    liquidity_policy_id_for_execution_mode,
    # Close the sniping contracts import after its required symbols are visible.
)
from backtest.engine.transaction_clock import CompactTransactionClock
from backtest.engine.wallet_accounts import (
    AccountProvisioningTransition,
    AccountReservationPlan,
    WalletProvisioningReducer,
    initial_wallet_provisioning_state,
    refundable_mint_deposits,
    run_locked_value,
    unsubmitted_account_records,
)

NUMPY_MMAP_PUMPFUN_SNIPING_BACKEND = "numpy-mmap-pumpfun-sniping-v1"
_MAX_BATCH_ROWS = 256 * 1024
_UINT64_SENTINEL = (1 << 64) - 1
# Bind pump protocol name once as an explicit module-level contract.
_PUMP_PROTOCOL_NAME = "pumpfun"

type _PrimitiveState = tuple[int, int, int, int, int, int, int]


class OptimizedSnipingBackendUnsupported(RuntimeError):
    """The resolved run is outside this backend's exact closed capability."""


@runtime_checkable
class _PrimitivePumpStrategy(SnipingStrategyInstance, Protocol):
    quote_asset_id: AssetId
    gross_buy_budget_atomic: int
    buy_slippage_bps: int
    # Declare sell slippage bps explicitly in the primitive pump strategy contract.
    sell_slippage_bps: int

    def decide_from_cooldown(
        self,
        target: LaunchTarget,
        *,
        # Keep the decision time ns input explicit in the decide from cooldown contract.
        decision_time_ns: int,
        cooldown_until_ns: int | None,
    ) -> LaunchDecision: ...


# Keep the primitive pump runtime contract and validation rules together.
@runtime_checkable
class _PrimitivePumpRuntime(SnipingProtocolRuntime, Protocol):
    quote_asset_id: AssetId
    protocol_version: str

    @property
    # Define primitive pump runtime launch payload schema id as one focused operation with
    # an explicit boundary.
    def launch_payload_schema_id(self) -> ProtocolPayloadSchemaId: ...

    @property
    def trade_payload_schema_id(self) -> ProtocolPayloadSchemaId: ...

    @property
    def lifecycle_payload_schema_id(self) -> ProtocolPayloadSchemaId: ...

    # Apply property semantics to the following primitive pump runtime primitive active
    # lifecycle code contract.
    @property
    def primitive_active_lifecycle_code(self) -> int: ...

    @property
    def primitive_migrated_lifecycle_code(self) -> int: ...

    def decode_primitive_state_payload(self, payload: bytes) -> _PrimitiveState: ...

    # Define primitive pump runtime validate primitive launch state as one focused
    # operation with an explicit boundary.
    def validate_primitive_launch_state(self, state: _PrimitiveState) -> None: ...

    def validate_primitive_lifecycle_state(
        self,
        state: _PrimitiveState,
        *,
        # Keep the lifecycle kind code input explicit in the validate primitive lifecycle
        # state contract.
        lifecycle_kind_code: int,
    ) -> None: ...

    def quote_buy_from_primitive_state(
        self,
        intent: RoundTripIntent,
        # Keep the state input explicit in the quote buy from primitive state contract.
        state: _PrimitiveState,
        *,
        effective_at_unix_s: int,
    ) -> ProtocolQuote: ...

    def account_requirements_from_primitive_state(
        self,
        state: _PrimitiveState,
    ) -> tuple[AccountRequirement, ...]: ...

    def quote_sell_from_primitive_state(
        # Keep the remaining quote sell from primitive state inputs visible at the
        # primitive pump runtime quote sell from primitive state boundary.
        self,
        intent: RoundTripIntent,
        state: _PrimitiveState,
        *,
        tokens_in_atomic: int,
        # Keep the effective at unix s input explicit in the quote sell from primitive
        # state contract.
        effective_at_unix_s: int,
    ) -> ProtocolQuote: ...

    def valuation_quote_from_primitive_state(
        self,
        intent: RoundTripIntent,
        # Keep the state input explicit in the valuation quote from primitive state
        # contract.
        state: _PrimitiveState,
        last_active_state: _PrimitiveState | None,
        last_active_effective_at_unix_s: int | None,
        *,
        tokens_in_atomic: int,
        # Keep the effective at unix s input explicit in the valuation quote from
        # primitive state contract.
        effective_at_unix_s: int,
    ) -> ValuationQuote | None: ...


# Keep the action kind contract and validation rules together.
class _ActionKind(IntEnum):
    SELL_DECISION = 1
    BUY_LANDING = 2
    SELL_LANDING = 3


# Keep the scheduled action contract and validation rules together.
@dataclass(order=True, slots=True)
class _ScheduledAction:
    release_boundary_ordinal: int
    phase: int
    creator_boundary_ordinal: int
    # Declare stable causal id hex explicitly in the scheduled action contract.
    stable_causal_id_hex: str
    kind: _ActionKind = field(compare=False)
    state_index: int = field(compare=False)


@dataclass(slots=True)
class _StateArena:
    """Bounded structure-of-arrays state, one entry per launch target."""

    maximum_items: int
    targets: list[LaunchTarget] = field(default_factory=list)
    roundtrip_ids: list[ContentDigest] = field(default_factory=list)
    venue_codes: list[int] = field(default_factory=list)
    target_time_ns: list[int] = field(default_factory=list)
    # Declare cooldown consumed explicitly in the state arena contract.
    cooldown_consumed: list[bool] = field(default_factory=list)
    cooldown_until_ns: list[int | None] = field(default_factory=list)
    intents: list[RoundTripIntent | None] = field(default_factory=list)
    statuses: list[RoundTripStatus] = field(default_factory=list)
    buy_references: list[ProtocolQuote | None] = field(default_factory=list)
    # Declare buy landings explicitly in the state arena contract.
    buy_landings: list[ProtocolQuote | None] = field(default_factory=list)
    buy_landing_positions: list[ChainPosition | None] = field(default_factory=list)
    buy_minimums: list[int] = field(default_factory=list)
    buy_failure_codes: list[str | None] = field(default_factory=list)
    buy_network_costs: list[NetworkCostQuote | None] = field(default_factory=list)
    # Declare sell references explicitly in the state arena contract.
    sell_references: list[ProtocolQuote | None] = field(default_factory=list)
    sell_decision_positions: list[ChainPosition | None] = field(default_factory=list)
    sell_landings: list[ProtocolQuote | None] = field(default_factory=list)
    sell_landing_positions: list[ChainPosition | None] = field(default_factory=list)
    sell_minimums: list[int] = field(default_factory=list)
    # Declare sell failure codes explicitly in the state arena contract.
    sell_failure_codes: list[str | None] = field(default_factory=list)
    sell_network_costs: list[NetworkCostQuote | None] = field(default_factory=list)
    acquired_tokens: list[int] = field(default_factory=list)
    account_reservations: list[AccountReservationPlan | None] = field(default_factory=list)
    account_components: list[tuple[AccountComponentRecord, ...]] = field(default_factory=list)
    cashback_receivables: list[int] = field(default_factory=list)
    terminal: list[bool] = field(default_factory=list)

    def append(
        self,
        # Close the append signature after its explicit inputs.
        *,
        target: LaunchTarget,
        venue_code: int,
        target_time_ns: int,
        decision: LaunchDecision,
        # Keep the int input explicit in the append contract.
    ) -> int:
        # Execute the state arena append workflow in explicit, reviewable steps.
        if len(self.targets) >= self.maximum_items:
            raise SnipingEngineError(SnipingEngineErrorCode.DYNAMIC_ITEM_LIMIT_EXCEEDED)
        index = len(self.targets)
        self.targets.append(target)
        self.roundtrip_ids.append(decision.roundtrip_id)
        # Invoke append for venue code as a visible state arena append step.
        self.venue_codes.append(venue_code)
        self.target_time_ns.append(target_time_ns)
        eligible = decision.status is LaunchDecisionStatus.ELIGIBLE
        self.cooldown_consumed.append(eligible)
        self.cooldown_until_ns.append(decision.cooldown_until_ns)
        # Invoke append for intent and decision as a visible state arena append step.
        self.intents.append(decision.intent)
        self.statuses.append(
            RoundTripStatus.BUY_REFERENCE_REJECTED if eligible else RoundTripStatus.COOLDOWN_SKIPPED
        )
        self.buy_references.append(None)
        # Invoke append as a visible step within the state arena append workflow.
        self.buy_landings.append(None)
        self.buy_landing_positions.append(None)
        self.buy_minimums.append(0)
        self.buy_failure_codes.append(None)
        self.buy_network_costs.append(None)
        # Invoke append as a visible step within the state arena append workflow.
        self.sell_references.append(None)
        self.sell_decision_positions.append(None)
        self.sell_landings.append(None)
        self.sell_landing_positions.append(None)
        self.sell_minimums.append(0)
        # Invoke append as a visible step within the state arena append workflow.
        self.sell_failure_codes.append(None)
        self.sell_network_costs.append(None)
        self.acquired_tokens.append(0)
        self.account_reservations.append(None)
        self.account_components.append(())
        self.cashback_receivables.append(0)
        self.terminal.append(not eligible)
        return index

    def materialize(self, index: int) -> _RoundTripState:
        # Execute the state arena materialize workflow in explicit, reviewable steps.
        return _RoundTripState(
            target=self.targets[index],
            target_time_ns=self.target_time_ns[index],
            cooldown_consumed=self.cooldown_consumed[index],
            cooldown_until_ns=self.cooldown_until_ns[index],
            # Pass intent explicitly so _RoundTripState receives a reviewable targets and
            # target time ns input in state arena materialize.
            intent=self.intents[index],
            status=self.statuses[index],
            buy_reference=self.buy_references[index],
            buy_landing=self.buy_landings[index],
            buy_landing_position=self.buy_landing_positions[index],
            # Pass buy minimum out atomic explicitly so _RoundTripState receives a
            # reviewable targets and target time ns input in state arena materialize.
            buy_minimum_out_atomic=self.buy_minimums[index],
            buy_failure_code=self.buy_failure_codes[index],
            buy_network_cost=self.buy_network_costs[index],
            account_reservation=self.account_reservations[index],
            account_components=self.account_components[index],
            sell_reference=self.sell_references[index],
            sell_decision_position=self.sell_decision_positions[index],
            # Pass sell landing explicitly so _RoundTripState receives a reviewable
            # targets and target time ns input in state arena materialize.
            sell_landing=self.sell_landings[index],
            sell_landing_position=self.sell_landing_positions[index],
            sell_minimum_out_atomic=self.sell_minimums[index],
            sell_failure_code=self.sell_failure_codes[index],
            sell_network_cost=self.sell_network_costs[index],
            # Pass acquired token amount atomic explicitly so _RoundTripState receives a
            # reviewable targets and target time ns input in state arena materialize.
            acquired_token_amount_atomic=self.acquired_tokens[index],
            cashback_receivable_atomic=self.cashback_receivables[index],
            # Pass terminal explicitly so _RoundTripState receives a reviewable targets
            # and target time ns input in state arena materialize.
            terminal=self.terminal[index],
        )


class _VenueArena:
    """Dense dictionary-code-indexed Pump curve state."""

    def __init__(self, venue_count: int) -> None:
        # Execute the venue arena init workflow in explicit, reviewable steps.
        self.exists = np.zeros(venue_count, dtype=np.bool_)
        self.asset_codes = np.zeros(venue_count, dtype=np.uint32)
        self.quote_asset_codes = np.zeros(venue_count, dtype=np.uint32)
        self.current = np.zeros((7, venue_count), dtype=np.uint64)
        self.last_active = np.zeros((7, venue_count), dtype=np.uint64)
        # Assemble self has last active once so the venue arena init workflow shares one
        # value.
        self.has_last_active = np.zeros(venue_count, dtype=np.bool_)
        self.last_active_effective_at_unix_s = np.full(venue_count, -1, dtype=np.int64)

    def state(self, venue_code: int) -> _PrimitiveState:
        # Execute the venue arena state workflow in explicit, reviewable steps.
        if not bool(self.exists[venue_code]):
            raise OptimizedSnipingBackendUnsupported("Pump venue is unknown")
        return cast(_PrimitiveState, tuple(int(value) for value in self.current[:, venue_code]))

    def active_state(self, venue_code: int) -> _PrimitiveState | None:
        # Execute the venue arena active state workflow in explicit, reviewable steps.
        if not bool(self.has_last_active[venue_code]):
            return None
        return cast(
            _PrimitiveState,
            tuple(int(value) for value in self.last_active[:, venue_code]),
            # Complete cast only after its last active and tuple inputs are visible in venue
            # arena active state.
        )


# Keep the batch states contract and validation rules together.
@dataclass(slots=True)
class _BatchStates:
    start: int
    stop: int
    pump_valid: npt.NDArray[np.bool_]
    # Declare values explicitly in the batch states contract.
    values: npt.NDArray[np.uint64]


# Keep the columnar delivery cursor contract and validation rules together.
@dataclass(slots=True)
class _ColumnarDeliveryCursor:
    release_boundaries: Sequence[int]
    event_rows: Sequence[int]
    index: int = 0

    # Define columnar delivery cursor consume group as one focused operation with an
    # explicit boundary.
    def consume_group(self, *, boundary: int, event_count: int) -> int:
        # Execute the columnar delivery cursor consume group workflow in explicit,
        # reviewable steps.
        stop = self.index + event_count
        if stop > len(self.release_boundaries):
            raise SnipingEngineError(SnipingEngineErrorCode.DELIVERY_SCHEDULE_INVALID)
        if any(
            int(self.release_boundaries[index]) != boundary
            # Keep index visible while evaluating the boundary, index and stop guard.
            for index in range(self.index, stop)
            # Complete any only after its index and release boundaries inputs are visible in
            # columnar delivery cursor consume group.
        ):
            raise SnipingEngineError(SnipingEngineErrorCode.DELIVERY_SCHEDULE_INVALID)
        self.index = stop
        return event_count

    def finish(self) -> None:
        # Execute the columnar delivery cursor finish workflow in explicit, reviewable
        # steps.
        if self.index != len(self.release_boundaries):
            raise SnipingEngineError(SnipingEngineErrorCode.DELIVERY_SCHEDULE_INVALID)


# Keep the optimized recorder contract and validation rules together.
class _OptimizedRecorder:
    def __init__(self, sink: SnipingRunEventSink) -> None:
        # Execute the optimized recorder init workflow in explicit, reviewable steps.
        self.sink = sink
        self.audit = CanonicalStreamHasher("backtest.sniping-audit-stream.v1")
        self.ledger = CanonicalStreamHasher("backtest.sniping-ledger-stream.v2")
        self.fills = CanonicalStreamHasher("backtest.sniping-fill-stream.v1")
        self.roundtrips = CanonicalStreamHasher("backtest.sniping-roundtrip-stream.v4")
        # Assemble self cashflows once so the optimized recorder init workflow shares one
        # value.
        self.cashflows = _CorrelatedLedgerCashflows()
        self._discard_audit = type(sink) is NullSnipingRunEventSink

    def append_encoded_audit(self, value: bytes) -> None:
        # Execute the optimized recorder append encoded audit workflow in explicit,
        # reviewable steps.
        self.audit.append_canonical_bytes(value)
        if self._discard_audit:
            return
        document = json.loads(value)
        if not isinstance(document, dict):  # pragma: no cover - module-authored bytes
            raise AssertionError("canonical audit encoder produced a non-object")
        self.sink.append_audit(cast(dict[str, object], document))

    def append_audit(self, value: dict[str, object]) -> None:
        # Execute the optimized recorder append audit workflow in explicit, reviewable
        # steps.
        self.audit.append(value)
        self.sink.append_audit(value)

    def append_ledger(self, value: LedgerTransaction) -> None:
        # Execute the optimized recorder append ledger workflow in explicit, reviewable
        # steps.
        self.ledger.append(ledger_document(value))
        self.cashflows.append(value)
        self.sink.append_ledger(value)

    def append_fill(self, value: Fill) -> None:
        # Execute the optimized recorder append fill workflow in explicit, reviewable
        # steps.
        self.fills.append(fill_document(value))
        self.sink.append_fill(value)

    def append_roundtrip(self, value: RoundTripRecord) -> None:
        # Execute the optimized recorder append roundtrip workflow in explicit, reviewable
        # steps.
        self.roundtrips.append(value.document())
        self.sink.append_roundtrip(value)


class NumpyMmapPumpfunSnipingEngine:
    """Exact single-thread reducer over verified ReplayPack v3 primitive arrays."""

    backend_name = NUMPY_MMAP_PUMPFUN_SNIPING_BACKEND

    def __init__(
        self,
        *,
        strategy_type: type[object],
        # Keep the protocol type input explicit in the init contract.
        protocol_type: type[object],
        network_cost_type: type[object],
    ) -> None:
        # Execute the numpy mmap pumpfun sniping engine init workflow in explicit,
        # reviewable steps.
        self._strategy_type = strategy_type
        self._protocol_type = protocol_type
        self._network_cost_type = network_cost_type

    def preflight(
        self,
        # Close the preflight signature after its explicit inputs.
        *,
        source: HistoricalEventSource,
        clock: CompactTransactionClock,
        strategy: SnipingStrategyInstance,
        protocol: SnipingProtocolRuntime,
        # Keep the network costs input explicit in the preflight contract.
        network_costs: SnipingNetworkCostModel,
        config: SnipingRunConfig,
        delivery_schedule: ObservationDeliverySource | None,
        physical_settings: EnginePhysicalSettings,
    ) -> NumpyMmapReplaySource:
        # Execute the numpy mmap pumpfun sniping engine preflight workflow in explicit,
        # reviewable steps.
        if type(source) is not NumpyMmapReplaySource:
            # Handle the numpy mmap pumpfun sniping engine preflight numpy mmap replay
            # source, type and source condition as a distinct block.
            raise OptimizedSnipingBackendUnsupported(
                "optimized sniping requires the verified NumPy ReplayPack reader"
            )
        if type(strategy) is not self._strategy_type:
            # Handle the numpy mmap pumpfun sniping engine preflight strategy type, type
            # and strategy condition as a distinct block.
            raise OptimizedSnipingBackendUnsupported(
                "optimized sniping requires the exact resolved strategy type"
            )
        if type(protocol) is not self._protocol_type:
            # Handle the numpy mmap pumpfun sniping engine preflight protocol type, type
            # and protocol condition as a distinct block.
            raise OptimizedSnipingBackendUnsupported(
                "optimized sniping requires the exact resolved Pump runtime type"
            )
        if type(network_costs) is not self._network_cost_type:
            # Handle the numpy mmap pumpfun sniping engine preflight network cost type,
            # type and network costs condition as a distinct block.
            raise OptimizedSnipingBackendUnsupported(
                "optimized sniping requires the exact resolved network-cost type"
            )
        if not isinstance(strategy, _PrimitivePumpStrategy) or not isinstance(
            protocol,
            # Pass primitive pump runtime explicitly so isinstance receives a reviewable
            # protocol and primitive pump runtime input in numpy mmap pumpfun sniping
            # engine preflight.
            _PrimitivePumpRuntime,
            # Complete isinstance only after its protocol and primitive pump runtime inputs
            # are visible in numpy mmap pumpfun sniping engine preflight.
        ):
            # Handle the numpy mmap pumpfun sniping engine preflight isinstance, strategy
            # and primitive pump strategy condition as a distinct block.
            raise OptimizedSnipingBackendUnsupported(
                "resolved components do not expose the optimized primitive contract"
            )
        settings = physical_settings
        if settings.threads != 1:
            # Handle the numpy mmap pumpfun sniping engine preflight settings.threads != 1
            # branch as a distinct logical block.
            raise OptimizedSnipingBackendUnsupported(
                "one optimized sniping run requires exactly one engine thread"
            )
        if settings.reader_batch_rows > _MAX_BATCH_ROWS:
            # Handle the numpy mmap pumpfun sniping engine preflight reader batch rows,
            # max batch rows and settings condition as a distinct block.
            raise OptimizedSnipingBackendUnsupported(
                "optimized sniping batch exceeds the 256k-row limit"
            )
        replay = source
        if replay.transaction_clock() != clock:
            # Handle the numpy mmap pumpfun sniping engine preflight
            # replay.transaction_clock() != clock branch as a distinct logical block.
            raise ChainIdentityMismatchError(
                "supplied transaction clock is not the ReplayPack clock"
            )
        if (
            config.decision_range.network_id != replay.network_id
            # Keep config visible while evaluating the network id, position schema id and
            # decision range guard.
            or config.decision_range.position_schema_id != replay.position_schema_id
            or config.decision_range != replay.decision_range
        ):
            # Handle the numpy mmap pumpfun sniping engine preflight network id, position
            # schema id and decision range condition as a distinct block.
            raise ChainIdentityMismatchError(
                "resolved decision range is not the exact ReplayPack decision range"
            )
        if config.execution_mode not in SNIPING_EXECUTION_MODES:
            # Handle the numpy mmap pumpfun sniping engine preflight execution mode,
            # exogenous replay and config condition as a distinct block.
            raise OptimizedSnipingBackendUnsupported(
                "optimized Pump.fun sniping requires an allowlisted exogenous mode"
            )
        _validate_primitive_layout(
            replay,
            # Pass clock explicitly so _validate_primitive_layout receives a reviewable
            # reader batch rows and replay input in numpy mmap pumpfun sniping engine
            # preflight.
            clock=clock,
            strategy=strategy,
            protocol=protocol,
            batch_rows=settings.reader_batch_rows,
        )
        # Invoke _preflight_delivery_schedule for replay and delivery schedule as a
        # visible numpy mmap pumpfun sniping engine preflight step.
        _preflight_delivery_schedule(replay, delivery_schedule)
        return replay

    def run(
        self,
        *,
        # Keep the source input explicit in the run contract.
        source: HistoricalEventSource,
        clock: CompactTransactionClock,
        strategy: SnipingStrategyInstance,
        protocol: SnipingProtocolRuntime,
        network_costs: SnipingNetworkCostModel,
        # Keep the config input explicit in the run contract.
        config: SnipingRunConfig,
        sink: SnipingRunEventSink | None = None,
        delivery_schedule: ObservationDeliverySource | None = None,
        physical_settings: EnginePhysicalSettings = DEFAULT_ENGINE_PHYSICAL_SETTINGS,
    ) -> SnipingRunSummary:
        # Execute the numpy mmap pumpfun sniping engine run workflow in explicit,
        # reviewable steps.
        replay = self.preflight(
            source=source,
            clock=clock,
            strategy=strategy,
            protocol=protocol,
            # Pass network costs explicitly so preflight receives a reviewable source and
            # clock input in numpy mmap pumpfun sniping engine run.
            network_costs=network_costs,
            config=config,
            delivery_schedule=delivery_schedule,
            physical_settings=physical_settings,
        )
        # Assemble primitive strategy once so the numpy mmap pumpfun sniping engine run
        # workflow shares one value.
        primitive_strategy = cast(_PrimitivePumpStrategy, strategy)
        primitive_protocol = cast(_PrimitivePumpRuntime, protocol)
        arrays = replay.arrays()
        recorder = _OptimizedRecorder(NullSnipingRunEventSink() if sink is None else sink)
        portfolio = PortfolioState(config.initial_available)
        accounts = WalletProvisioningReducer(
            initial_wallet_provisioning_state(
                config.initial_uva_state,
                uva_schema_id=config.uva_schema_id,
            )
        )
        # Assemble venues once so the numpy mmap pumpfun sniping engine run workflow
        # shares one value.
        venues = _VenueArena(_dictionary_count(replay, "venues"))
        developer_cooldowns = np.full(
            _dictionary_count(replay, "accounts"),
            _UINT64_SENTINEL,
            dtype=np.uint64,
            # Complete full only after its accounts and uint64 inputs are visible in numpy
            # mmap pumpfun sniping engine run.
        )
        states = _StateArena(config.maximum_dynamic_items)
        roundtrip_ids: set[ContentDigest] = set()
        scheduled: list[_ScheduledAction] = []
        counts = _RunCounts()
        # Assemble delivery cursor once so the numpy mmap pumpfun sniping engine run
        # workflow shares one value.
        delivery_cursor = _delivery_cursor(delivery_schedule)

        boundary_offsets = arrays[physical.BOUNDARY_OFFSETS]
        boundary_ordinals = arrays[physical.BOUNDARY_ORDINAL]
        batch_windows = _boundary_batches(
            boundary_offsets,
            # Pass physical settings explicitly so _boundary_batches receives a reviewable
            # reader batch rows and reader readahead input in numpy mmap pumpfun sniping
            # engine run.
            physical_settings.reader_batch_rows,
            physical_settings.reader_readahead,
        )
        for boundary_start, boundary_stop in batch_windows:
            # Process batch_windows inside the bounded numpy mmap pumpfun sniping engine
            # run loop.
            row_start = int(boundary_offsets[boundary_start])
            row_stop = int(boundary_offsets[boundary_stop])
            decoded = _decode_batch_states(
                arrays,
                row_start,
                # Pass row stop explicitly so _decode_batch_states receives a reviewable
                # protocols and dictionary code input in numpy mmap pumpfun sniping engine
                # run.
                row_stop,
                protocol=primitive_protocol,
                pump_protocol_code=replay.dictionary_code("protocols", _PUMP_PROTOCOL_NAME),
            )
            for boundary_index in range(boundary_start, boundary_stop):
                # Process range(boundary_start, boundary_stop) inside the bounded numpy
                # mmap pumpfun sniping engine run loop.
                historical_boundary = int(boundary_ordinals[boundary_index])
                while scheduled and scheduled[0].release_boundary_ordinal < historical_boundary:
                    # Keep the scheduled, release boundary ordinal and historical boundary
                    # loop body bounded within numpy mmap pumpfun sniping engine run.
                    self._process_boundary(
                        boundary=scheduled[0].release_boundary_ordinal,
                        row_start=None,
                        row_stop=None,
                        arrays=arrays,
                        # Pass decoded explicitly so _process_boundary receives a
                        # reviewable release boundary ordinal and scheduled input in numpy
                        # mmap pumpfun sniping engine run.
                        decoded=None,
                        replay=replay,
                        clock=clock,
                        strategy=primitive_strategy,
                        protocol=primitive_protocol,
                        # Pass network costs explicitly so _process_boundary receives a
                        # reviewable release boundary ordinal and scheduled input in numpy
                        # mmap pumpfun sniping engine run.
                        network_costs=network_costs,
                        config=config,
                        portfolio=portfolio,
                        accounts=accounts,
                        venues=venues,
                        cooldowns=developer_cooldowns,
                        # Pass states explicitly so _process_boundary receives a
                        # reviewable release boundary ordinal and scheduled input in numpy
                        # mmap pumpfun sniping engine run.
                        states=states,
                        roundtrip_ids=roundtrip_ids,
                        scheduled=scheduled,
                        recorder=recorder,
                        counts=counts,
                        # Pass delivery cursor explicitly so _process_boundary receives a
                        # reviewable release boundary ordinal and scheduled input in numpy
                        # mmap pumpfun sniping engine run.
                        delivery_cursor=delivery_cursor,
                    )
                self._process_boundary(
                    boundary=historical_boundary,
                    row_start=int(boundary_offsets[boundary_index]),
                    # Pass row stop explicitly to _process_boundary for int and historical
                    # boundary.
                    row_stop=int(boundary_offsets[boundary_index + 1]),
                    arrays=arrays,
                    decoded=decoded,
                    replay=replay,
                    clock=clock,
                    # Pass strategy explicitly so _process_boundary receives a reviewable
                    # int and historical boundary input in numpy mmap pumpfun sniping
                    # engine run.
                    strategy=primitive_strategy,
                    protocol=primitive_protocol,
                    network_costs=network_costs,
                    config=config,
                    portfolio=portfolio,
                    accounts=accounts,
                    # Pass venues explicitly so _process_boundary receives a reviewable
                    # int and historical boundary input in numpy mmap pumpfun sniping
                    # engine run.
                    venues=venues,
                    cooldowns=developer_cooldowns,
                    states=states,
                    roundtrip_ids=roundtrip_ids,
                    scheduled=scheduled,
                    # Pass recorder explicitly so _process_boundary receives a reviewable
                    # int and historical boundary input in numpy mmap pumpfun sniping
                    # engine run.
                    recorder=recorder,
                    counts=counts,
                    delivery_cursor=delivery_cursor,
                )
        while scheduled:
            # Keep the scheduled loop body bounded within numpy mmap pumpfun sniping
            # engine run.
            self._process_boundary(
                boundary=scheduled[0].release_boundary_ordinal,
                row_start=None,
                row_stop=None,
                arrays=arrays,
                # Pass decoded explicitly so _process_boundary receives a reviewable
                # release boundary ordinal and scheduled input in numpy mmap pumpfun
                # sniping engine run.
                decoded=None,
                replay=replay,
                clock=clock,
                strategy=primitive_strategy,
                protocol=primitive_protocol,
                # Pass network costs explicitly so _process_boundary receives a reviewable
                # release boundary ordinal and scheduled input in numpy mmap pumpfun
                # sniping engine run.
                network_costs=network_costs,
                config=config,
                portfolio=portfolio,
                accounts=accounts,
                venues=venues,
                cooldowns=developer_cooldowns,
                # Pass states explicitly so _process_boundary receives a reviewable
                # release boundary ordinal and scheduled input in numpy mmap pumpfun
                # sniping engine run.
                states=states,
                roundtrip_ids=roundtrip_ids,
                scheduled=scheduled,
                recorder=recorder,
                counts=counts,
                # Pass delivery cursor explicitly so _process_boundary receives a
                # reviewable release boundary ordinal and scheduled input in numpy mmap
                # pumpfun sniping engine run.
                delivery_cursor=delivery_cursor,
            )

        if delivery_cursor is not None:
            delivery_cursor.finish()

        return _finalize_summary(
            # Pass replay explicitly so _finalize_summary receives a reviewable replay and
            # clock input in numpy mmap pumpfun sniping engine run.
            replay=replay,
            clock=clock,
            strategy=primitive_strategy,
            protocol=primitive_protocol,
            network_costs=network_costs,
            # Pass config explicitly so _finalize_summary receives a reviewable replay and
            # clock input in numpy mmap pumpfun sniping engine run.
            config=config,
            portfolio=portfolio,
            venues=venues,
            states=states,
            recorder=recorder,
            # Pass counts explicitly so _finalize_summary receives a reviewable replay and
            # clock input in numpy mmap pumpfun sniping engine run.
            counts=counts,
        )

    def _process_boundary(
        self,
        *,
        # Keep the boundary input explicit in the process boundary contract.
        boundary: int,
        row_start: int | None,
        row_stop: int | None,
        arrays: Mapping[str, npt.NDArray[np.generic]],
        decoded: _BatchStates | None,
        # Keep the replay input explicit in the process boundary contract.
        replay: NumpyMmapReplaySource,
        clock: CompactTransactionClock,
        strategy: _PrimitivePumpStrategy,
        protocol: _PrimitivePumpRuntime,
        network_costs: SnipingNetworkCostModel,
        # Keep the config input explicit in the process boundary contract.
        config: SnipingRunConfig,
        portfolio: PortfolioState,
        accounts: WalletProvisioningReducer,
        venues: _VenueArena,
        cooldowns: npt.NDArray[np.uint64],
        states: _StateArena,
        # Keep the roundtrip ids input explicit in the process boundary contract.
        roundtrip_ids: set[ContentDigest],
        scheduled: list[_ScheduledAction],
        recorder: _OptimizedRecorder,
        counts: _RunCounts,
        delivery_cursor: _ColumnarDeliveryCursor | None,
        # Close the process boundary signature after its explicit inputs.
    ) -> None:
        # Execute the numpy mmap pumpfun sniping engine process boundary workflow in
        # explicit, reviewable steps.
        position = ChainPosition.from_boundary_ordinal(
            network_id=clock.network_id,
            position_schema_id=clock.position_schema_id,
            boundary_ordinal_value=boundary,
        )
        # Assemble launches once so the numpy mmap pumpfun sniping engine process boundary
        # workflow shares one value.
        launches: list[tuple[LaunchTarget, int, int]] = []
        if row_start is not None and row_stop is not None:
            if decoded is None:  # pragma: no cover - internal call invariant
                raise AssertionError("historical boundary has no decoded batch")
            launches = _apply_historical_group(
                row_start=row_start,
                row_stop=row_stop,
                arrays=arrays,
                # Pass decoded explicitly so _apply_historical_group receives a reviewable
                # block time for block and block ordinal input in numpy mmap pumpfun
                # sniping engine process boundary.
                decoded=decoded,
                replay=replay,
                protocol=protocol,
                venues=venues,
                effective_at_unix_s=(
                    # Keep the block ordinal block_time_for_block step visible while
                    # building launches.
                    clock.block_time_for_block(position.block_ordinal) // 1_000_000_000
                ),
            )
            counts.historical_group_count += 1
            counts.historical_event_count += row_stop - row_start
            # Invoke append_encoded_audit for historical group record and boundary as a
            # visible numpy mmap pumpfun sniping engine process boundary step.
            recorder.append_encoded_audit(
                _historical_group_record(boundary, arrays, row_start, row_stop)
            )
            if delivery_cursor is None:
                counts.delivered_event_count += row_stop - row_start
            # Route all remaining cases through the explicit alternative branch.
            else:
                # Handle the numpy mmap pumpfun sniping engine process boundary complement
                # of delivery_cursor is None explicitly.
                counts.delivered_event_count += delivery_cursor.consume_group(
                    boundary=boundary,
                    event_count=row_stop - row_start,
                )

        for action in _pop_actions(scheduled, boundary, maximum_phase=40):
            # Process pop actions, scheduled and boundary inside the bounded numpy mmap
            # pumpfun sniping engine process boundary loop.
            if action.kind is not _ActionKind.SELL_DECISION:
                raise SnipingEngineError(SnipingEngineErrorCode.INTERNAL_STATE_INVALID)
            _decide_sell(
                action.state_index,
                position=position,
                # Pass clock explicitly so _decide_sell receives a reviewable state index
                # and action input in numpy mmap pumpfun sniping engine process boundary.
                clock=clock,
                protocol=protocol,
                network_costs=network_costs,
                portfolio=portfolio,
                venues=venues,
                # Pass states explicitly so _decide_sell receives a reviewable state index
                # and action input in numpy mmap pumpfun sniping engine process boundary.
                states=states,
                scheduled=scheduled,
                recorder=recorder,
            )

        for target, venue_code, developer_code in launches:
            # Process launches inside the bounded numpy mmap pumpfun sniping engine
            # process boundary loop.
            if not config.decision_range.contains_position(target.position):
                # Handle the numpy mmap pumpfun sniping engine process boundary contains
                # position, position and decision range condition as a distinct block.
                recorder.append_audit(
                    {
                        "boundary_ordinal": boundary,
                        "phase": int(SchedulerPhase.STRATEGY_CALLBACK),
                        "record_type": "TARGET_OUTSIDE_DECISION_RANGE",
                        # Keep target event id named so the target outside decision range
                        # and boundary ordinal payload passed to append_audit remains
                        # self-describing within numpy mmap pumpfun sniping engine process
                        # boundary.
                        "target_event_id": target.target_event_id.hex,
                    }
                )
                continue
            counts.target_count += 1
            # Assemble target time ns once so the numpy mmap pumpfun sniping engine
            # process boundary workflow shares one value.
            target_time_ns = clock.block_time_for_position(target.position)
            raw_until = int(cooldowns[developer_code])
            current_until = None if raw_until == _UINT64_SENTINEL else raw_until
            decision = strategy.decide_from_cooldown(
                target,
                # Pass decision time ns explicitly so decide_from_cooldown receives a
                # reviewable target and target time ns input in numpy mmap pumpfun sniping
                # engine process boundary.
                decision_time_ns=target_time_ns,
                cooldown_until_ns=current_until,
            )
            if decision.roundtrip_id in roundtrip_ids:
                raise SnipingEngineError(SnipingEngineErrorCode.DUPLICATE_ROUNDTRIP)
            # Invoke add for roundtrip id and decision as a visible numpy mmap pumpfun
            # sniping engine process boundary step.
            roundtrip_ids.add(decision.roundtrip_id)
            if decision.status is LaunchDecisionStatus.ELIGIBLE:
                if (
                    decision.intent is None
                    or decision.intent.execution_mode is not config.execution_mode
                ):
                    raise SnipingEngineError(SnipingEngineErrorCode.INTERNAL_STATE_INVALID)
                if decision.cooldown_until_ns is None:  # pragma: no cover - contract invariant
                    raise AssertionError("eligible cooldown decision has no expiry")
                cooldowns[developer_code] = decision.cooldown_until_ns
            index = states.append(
                target=target,
                venue_code=venue_code,
                # Pass target time ns explicitly so append receives a reviewable target
                # and venue code input in numpy mmap pumpfun sniping engine process
                # boundary.
                target_time_ns=target_time_ns,
                decision=decision,
            )
            if decision.status is LaunchDecisionStatus.COOLDOWN_SUPPRESSED:
                # Handle the numpy mmap pumpfun sniping engine process boundary status,
                # cooldown suppressed and decision condition as a distinct block.
                counts.cooldown_skipped_count += 1
                recorder.append_audit(
                    {
                        "boundary_ordinal": boundary,
                        "developer_id": target.developer_id.value,
                        # Pass phase explicitly to append_audit for target cooldown
                        # skipped and boundary ordinal.
                        "phase": int(SchedulerPhase.STRATEGY_CALLBACK),
                        "record_type": "TARGET_COOLDOWN_SKIPPED",
                        "roundtrip_id": decision.roundtrip_id.hex,
                    }
                )
                # Keep the continue step explicit within the numpy mmap pumpfun sniping
                # engine process boundary workflow.
                continue
            if _accept_buy(
                index,
                clock=clock,
                protocol=protocol,
                # Pass network costs explicitly so _accept_buy receives a reviewable index
                # and clock input in numpy mmap pumpfun sniping engine process boundary.
                network_costs=network_costs,
                portfolio=portfolio,
                accounts=accounts,
                venues=venues,
                states=states,
                scheduled=scheduled,
                # Pass recorder explicitly so _accept_buy receives a reviewable index and
                # clock input in numpy mmap pumpfun sniping engine process boundary.
                recorder=recorder,
            ):
                counts.accepted_buy_count += 1

        for action in _pop_actions(scheduled, boundary, maximum_phase=60):
            # Process pop actions, scheduled and boundary inside the bounded numpy mmap
            # pumpfun sniping engine process boundary loop.
            if action.kind is _ActionKind.BUY_LANDING:
                # Handle the numpy mmap pumpfun sniping engine process boundary
                # action.kind is _ActionKind.BUY_LANDING branch as a distinct logical
                # block.
                if not _land_buy(
                    action.state_index,
                    position=position,
                    clock=clock,
                    protocol=protocol,
                    # Pass network costs explicitly so _land_buy receives a reviewable
                    # state index and action input in numpy mmap pumpfun sniping engine
                    # process boundary.
                    network_costs=network_costs,
                    portfolio=portfolio,
                    accounts=accounts,
                    venues=venues,
                    states=states,
                    scheduled=scheduled,
                    # Pass recorder explicitly so _land_buy receives a reviewable state
                    # index and action input in numpy mmap pumpfun sniping engine process
                    # boundary.
                    recorder=recorder,
                ):
                    counts.failed_buy_count += 1
            # Handle the numpy mmap pumpfun sniping engine process boundary complement of
            # action.kind is _ActionKind.BUY_LANDING explicitly.
            elif action.kind is _ActionKind.SELL_LANDING:
                # Handle the numpy mmap pumpfun sniping engine process boundary kind, sell
                # landing and action condition as a distinct block.
                if not _land_sell(
                    action.state_index,
                    position=position,
                    clock=clock,
                    protocol=protocol,
                    # Pass network costs explicitly so _land_sell receives a reviewable
                    # state index and action input in numpy mmap pumpfun sniping engine
                    # process boundary.
                    network_costs=network_costs,
                    portfolio=portfolio,
                    accounts=accounts,
                    venues=venues,
                    states=states,
                    recorder=recorder,
                    # Complete _land_sell only after its state index and action inputs are
                    # visible in numpy mmap pumpfun sniping engine process boundary.
                ):
                    counts.failed_sell_count += 1
            else:
                raise SnipingEngineError(SnipingEngineErrorCode.INTERNAL_STATE_INVALID)

        if len(scheduled) > config.maximum_dynamic_items:
            # Fail the numpy mmap pumpfun sniping engine process boundary path with
            # SnipingEngineError for dynamic item limit exceeded and sniping engine error
            # code when maximum dynamic items, scheduled and config is true; do not
            # continue ambiguously.
            raise SnipingEngineError(SnipingEngineErrorCode.DYNAMIC_ITEM_LIMIT_EXCEEDED)
        recorder.append_encoded_audit(_checkpoint_record(boundary))


# Keep the run counts contract and validation rules together.
@dataclass(slots=True)
class _RunCounts:
    historical_group_count: int = 0
    historical_event_count: int = 0
    delivered_event_count: int = 0
    # Declare target count explicitly in the run counts contract.
    target_count: int = 0
    cooldown_skipped_count: int = 0
    accepted_buy_count: int = 0
    failed_buy_count: int = 0
    failed_sell_count: int = 0


# Define preflight delivery schedule as one focused operation with an explicit boundary.
def _preflight_delivery_schedule(
    replay: NumpyMmapReplaySource,
    schedule: ObservationDeliverySource | None,
) -> None:
    # Execute the preflight delivery schedule workflow in explicit, reviewable steps.
    if schedule is None:
        return
    if not isinstance(schedule, ColumnarObservationDeliverySource):
        # Handle the preflight delivery schedule isinstance, schedule and columnar
        # observation delivery source condition as a distinct block.
        raise OptimizedSnipingBackendUnsupported(
            "optimized sniping requires a verified columnar DeliverySchedule"
        )
    counts = (
        schedule.input_event_count,
        # Keep the schedule component named inside the counts contract.
        schedule.delivery_count,
        schedule.outside_horizon_count,
    )
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts):
        raise SnipingEngineError(SnipingEngineErrorCode.DELIVERY_SCHEDULE_INVALID)
    # Evaluate the complete preflight delivery schedule input event count, event count and
    # delivery count condition before guarded effects.
    if (
        schedule.input_event_count != replay.event_count
        or schedule.delivery_count != replay.event_count
        or schedule.outside_horizon_count != 0
    ):
        # Fail the preflight delivery schedule path with SnipingEngineError for delivery
        # schedule invalid and sniping engine error code when input event count, event
        # count and delivery count is true; do not continue ambiguously.
        raise SnipingEngineError(SnipingEngineErrorCode.DELIVERY_SCHEDULE_INVALID)
    releases, event_rows = schedule.delivery_columns()
    if len(releases) != schedule.delivery_count or len(event_rows) != schedule.delivery_count:
        raise SnipingEngineError(SnipingEngineErrorCode.DELIVERY_SCHEDULE_INVALID)
    arrays = replay.arrays()
    # Assemble source boundaries once so the preflight delivery schedule workflow shares
    # one value.
    source_boundaries = arrays[physical.ENVELOPE_BOUNDARY_ORDINAL]
    stable_ids = arrays[physical.ENVELOPE_STABLE_CAUSAL_ID]
    previous_key: tuple[int, int, bytes] | None = None
    for index in range(schedule.delivery_count):
        # Process range(schedule.delivery_count) inside the bounded preflight delivery
        # schedule loop.
        event_row = int(event_rows[index])
        if event_row < 0 or event_row >= replay.event_count:
            raise SnipingEngineError(SnipingEngineErrorCode.DELIVERY_SCHEDULE_INVALID)
        release = int(releases[index])
        source_boundary = int(source_boundaries[event_row])
        # Guard this path with release != source_boundary before applying effects.
        if release != source_boundary:
            raise SnipingEngineError(SnipingEngineErrorCode.DELIVERY_SCHEDULE_INVALID)
        key = (release, source_boundary, stable_ids[event_row].tobytes())
        if previous_key is not None and key <= previous_key:
            raise SnipingEngineError(SnipingEngineErrorCode.DELIVERY_SCHEDULE_INVALID)
        # Assemble previous key once so the preflight delivery schedule workflow shares
        # one value.
        previous_key = key


def _delivery_cursor(
    schedule: ObservationDeliverySource | None,
) -> _ColumnarDeliveryCursor | None:
    # Execute the delivery cursor workflow in explicit, reviewable steps.
    if schedule is None:
        return None
    if not isinstance(schedule, ColumnarObservationDeliverySource):
        # Handle the delivery cursor isinstance, schedule and columnar observation
        # delivery source condition as a distinct block.
        raise OptimizedSnipingBackendUnsupported(
            "optimized sniping requires a verified columnar DeliverySchedule"
        )
    releases, event_rows = schedule.delivery_columns()
    return _ColumnarDeliveryCursor(releases, event_rows)


# Define validate primitive layout as one focused operation with an explicit boundary.
def _validate_primitive_layout(
    replay: NumpyMmapReplaySource,
    *,
    clock: CompactTransactionClock,
    strategy: _PrimitivePumpStrategy,
    # Keep the protocol input explicit in the validate primitive layout contract.
    protocol: _PrimitivePumpRuntime,
    batch_rows: int,
) -> None:
    # Execute the validate primitive layout workflow in explicit, reviewable steps.
    arrays = replay.arrays()
    boundary_offsets = arrays[physical.BOUNDARY_OFFSETS]
    group_offsets = arrays[physical.GROUP_OFFSETS]
    if not np.array_equal(boundary_offsets, group_offsets):
        # Handle the validate primitive layout array equal, boundary offsets and group
        # offsets condition as a distinct block.
        raise OptimizedSnipingBackendUnsupported(
            "optimized sniping requires exactly one transaction group per boundary"
        )
    group_sizes = np.diff(boundary_offsets)
    if group_sizes.size and int(group_sizes.max()) > batch_rows:
        # Handle the validate primitive layout size, group sizes and batch rows condition
        # as a distinct block.
        raise OptimizedSnipingBackendUnsupported(
            "one historical transaction group exceeds the configured reader batch"
        )
    event_count = replay.event_count
    fidelity = arrays[physical.ENVELOPE_ORDERING_FIDELITY_CODE]
    # Assemble event index valid once so the validate primitive layout workflow shares one
    # value.
    event_index_valid = _validity_values(arrays[physical.ENVELOPE_EVENT_INDEX_VALID], event_count)
    if bool(np.any(np.isin(fidelity, (2, 3)) & ~event_index_valid)):
        # Handle the validate primitive layout any, np and isin condition as a distinct
        # block.
        raise OptimizedSnipingBackendUnsupported(
            "exact ordering requires an event index on every exact row"
        )
    _validate_canonical_group_order(arrays, boundary_offsets)

    pump_code = replay.dictionary_code("protocols", _PUMP_PROTOCOL_NAME)
    # Guard this path with pump_code is None before applying effects.
    if pump_code is None:
        return
    protocol_codes = arrays[physical.ENVELOPE_PROTOCOL_CODE]
    pump_rows = protocol_codes == pump_code
    kinds = arrays[physical.ENVELOPE_EVENT_KIND_CODE]
    # Assemble non block pump once so the validate primitive layout workflow shares one
    # value.
    non_block_pump = pump_rows & (kinds != int(EventKind.BLOCK))
    version_code = replay.dictionary_code("protocol_versions", protocol.protocol_version)
    if version_code is None or bool(
        np.any(arrays[physical.ENVELOPE_PROTOCOL_VERSION_CODE][non_block_pump] != version_code)
    ):
        # Fail the validate primitive layout path with OptimizedSnipingBackendUnsupported
        # for pump protocol version is unsupported when version code, any and np is true;
        # do not continue ambiguously.
        raise OptimizedSnipingBackendUnsupported("Pump protocol version is unsupported")
    if bool(np.any(fidelity[non_block_pump] != 3)):
        raise OptimizedSnipingBackendUnsupported("Pump rows require instruction-exact ordering")
    supported_kind = np.isin(
        kinds,
        # Open the block and token launch payload explicitly for isin within validate
        # primitive layout.
        (
            int(EventKind.BLOCK),
            int(EventKind.TOKEN_LAUNCH),
            int(EventKind.VENUE_TRADE),
            int(EventKind.VENUE_LIFECYCLE),
            # Complete isin only after its block and token launch inputs are visible in
            # validate primitive layout.
        ),
    )
    if bool(np.any(pump_rows & ~supported_kind)):
        raise OptimizedSnipingBackendUnsupported("Pump event kind is unsupported")
    schema_codes = arrays[physical.ENVELOPE_PROTOCOL_PAYLOAD_SCHEMA_CODE]
    # Assemble expected schema once so the validate primitive layout workflow shares one
    # value.
    expected_schema = {
        EventKind.TOKEN_LAUNCH: protocol.launch_payload_schema_id,
        EventKind.VENUE_TRADE: protocol.trade_payload_schema_id,
        EventKind.VENUE_LIFECYCLE: protocol.lifecycle_payload_schema_id,
    }
    # Traverse expected_schema.items() explicitly so each validate primitive layout
    # iteration remains traceable.
    for kind, schema_id in expected_schema.items():
        # Process expected_schema.items() inside the bounded validate primitive layout
        # loop.
        rows = pump_rows & (kinds == int(kind))
        if not bool(np.any(rows)):
            continue
        schema_code = replay.dictionary_code("protocol_payload_schemas", schema_id.value)
        if schema_code is None or bool(np.any(schema_codes[rows] != schema_code)):
            # Handle the validate primitive layout schema code, any and np condition as a
            # distinct block.
            raise OptimizedSnipingBackendUnsupported(
                f"Pump {kind.name.lower()} payload schema is unsupported"
            )
    quote_code = replay.dictionary_code("assets", strategy.quote_asset_id.value)
    if quote_code is None:
        # Handle the validate primitive layout quote_code is None branch as a distinct
        # logical block.
        if bool(np.any(pump_rows & (kinds == int(EventKind.TOKEN_LAUNCH)))):
            raise OptimizedSnipingBackendUnsupported("resolved quote asset is absent")
        return
    payload_indexes = arrays[physical.ENVELOPE_PAYLOAD_INDEX]
    token_quotes = arrays[physical.TOKEN_QUOTE_ASSET_CODE]
    # Assemble blocks once so the validate primitive layout workflow shares one value.
    blocks = arrays[physical.ENVELOPE_BLOCK_ORDINAL]
    transactions = arrays[physical.ENVELOPE_TRANSACTION_INDEX]
    event_indexes = arrays[physical.ENVELOPE_EVENT_INDEX]
    token_rows = np.flatnonzero(pump_rows & (kinds == int(EventKind.TOKEN_LAUNCH)))
    for raw_row in token_rows:
        # Process token_rows inside the bounded validate primitive layout loop.
        row = int(raw_row)
        payload = int(payload_indexes[row])
        if int(token_quotes[payload]) != quote_code:
            raise OptimizedSnipingBackendUnsupported("Pump launch is not SOL-paired")
        position = ChainPosition(
            # Pass network id explicitly so ChainPosition receives a reviewable network id
            # and position schema id input in validate primitive layout.
            network_id=replay.network_id,
            position_schema_id=replay.position_schema_id,
            block_ordinal=int(blocks[row]),
            transaction_index=int(transactions[row]),
            event_index=int(event_indexes[row]),
            # Complete ChainPosition only after its network id and position schema id inputs
            # are visible in validate primitive layout.
        )
        if not replay.decision_range.contains_position(position):
            continue
        buy_landing = clock.transaction_after(position, strategy.buy_delay_transactions)
        sell_decision = clock.first_nonempty_transaction_at_or_after(
            # Pass after position explicitly so first_nonempty_transaction_at_or_after
            # receives a reviewable sell decision delay ns and block time for position
            # input in validate primitive layout.
            after_position=buy_landing,
            target_time_ns=(
                clock.block_time_for_position(buy_landing) + strategy.sell_decision_delay_ns
            ),
        )
        # Invoke transaction_after for sell delay transactions and sell decision as a
        # visible validate primitive layout step.
        clock.transaction_after(sell_decision, strategy.sell_delay_transactions)


def _validate_canonical_group_order(
    arrays: Mapping[str, npt.NDArray[np.generic]],
    offsets: npt.NDArray[np.generic],
) -> None:
    # Execute the validate canonical group order workflow in explicit, reviewable steps.
    event_indexes = arrays[physical.ENVELOPE_EVENT_INDEX]
    valid_event_indexes = _validity_values(
        arrays[physical.ENVELOPE_EVENT_INDEX_VALID], len(event_indexes)
    )
    stable_ids = arrays[physical.ENVELOPE_STABLE_CAUSAL_ID]
    # Traverse range(len(offsets) - 1) explicitly so each validate canonical group order
    # iteration remains traceable.
    for boundary_index in range(len(offsets) - 1):
        # Process range(len(offsets) - 1) inside the bounded validate canonical group
        # order loop.
        start = int(offsets[boundary_index])
        stop = int(offsets[boundary_index + 1])
        previous_index = -1
        previous_stable: bytes | None = None
        for row in range(start, stop):
            # Process range(start, stop) inside the bounded validate canonical group order
            # loop.
            event_index = int(event_indexes[row]) if bool(valid_event_indexes[row]) else -1
            stable = stable_ids[row].tobytes()
            if event_index < previous_index or (
                event_index == previous_index
                and previous_stable is not None
                # Keep stable visible while evaluating the event index, previous index and
                # previous stable guard.
                and stable <= previous_stable
            ):
                # Handle the validate canonical group order event index, previous index
                # and previous stable condition as a distinct block.
                raise OptimizedSnipingBackendUnsupported(
                    "ReplayPack group rows are not in canonical event order"
                )
            previous_index = event_index
            previous_stable = stable


# Define decode batch states as one focused operation with an explicit boundary.
def _decode_batch_states(
    arrays: Mapping[str, npt.NDArray[np.generic]],
    start: int,
    stop: int,
    *,
    # Keep the protocol input explicit in the decode batch states contract.
    protocol: _PrimitivePumpRuntime,
    pump_protocol_code: int | None,
) -> _BatchStates:
    # Execute the decode batch states workflow in explicit, reviewable steps.
    size = stop - start
    valid = np.zeros(size, dtype=np.bool_)
    values = np.zeros((7, size), dtype=np.uint64)
    if pump_protocol_code is None:
        return _BatchStates(start, stop, valid, values)
    # Assemble protocols once so the decode batch states workflow shares one value.
    protocols = arrays[physical.ENVELOPE_PROTOCOL_CODE]
    kinds = arrays[physical.ENVELOPE_EVENT_KIND_CODE]
    payload_indexes = arrays[physical.ENVELOPE_PAYLOAD_INDEX]
    offsets = arrays[physical.ENVELOPE_PROTOCOL_PAYLOAD_OFFSETS]
    payload_bytes = arrays[physical.ENVELOPE_PROTOCOL_PAYLOAD_BYTES]
    # Assemble lifecycle kinds once so the decode batch states workflow shares one value.
    lifecycle_kinds = arrays[physical.LIFECYCLE_KIND_CODE]
    for row in range(start, stop):
        # Process range(start, stop) inside the bounded decode batch states loop.
        if int(protocols[row]) != pump_protocol_code:
            continue
        kind = int(kinds[row])
        if kind == int(EventKind.BLOCK):
            continue
        # Assemble payload start once so the decode batch states workflow shares one
        # value.
        payload_start = int(offsets[row])
        payload_stop = int(offsets[row + 1])
        state = protocol.decode_primitive_state_payload(
            payload_bytes[payload_start:payload_stop].tobytes()
        )
        # Guard this path with kind == int(EventKind.TOKEN_LAUNCH) before applying
        # effects.
        if kind == int(EventKind.TOKEN_LAUNCH):
            protocol.validate_primitive_launch_state(state)
        # Handle the decode batch states complement of kind == int(EventKind.TOKEN_LAUNCH)
        # explicitly.
        elif kind == int(EventKind.VENUE_LIFECYCLE):
            # Handle the decode batch states kind == int(EventKind.VENUE_LIFECYCLE) branch
            # as a distinct logical block.
            protocol.validate_primitive_lifecycle_state(
                state,
                lifecycle_kind_code=int(lifecycle_kinds[int(payload_indexes[row])]),
            )
        local = row - start
        # Assemble values[:, local] once so the decode batch states workflow shares one
        # value.
        values[:, local] = state
        valid[local] = True
    return _BatchStates(start, stop, valid, values)


def _apply_historical_group(
    *,
    # Keep the row start input explicit in the apply historical group contract.
    row_start: int,
    row_stop: int,
    arrays: Mapping[str, npt.NDArray[np.generic]],
    decoded: _BatchStates,
    replay: NumpyMmapReplaySource,
    # Keep the protocol input explicit in the apply historical group contract.
    protocol: _PrimitivePumpRuntime,
    venues: _VenueArena,
    effective_at_unix_s: int,
) -> list[tuple[LaunchTarget, int, int]]:
    # Execute the apply historical group workflow in explicit, reviewable steps.
    kinds = arrays[physical.ENVELOPE_EVENT_KIND_CODE]
    payload_indexes = arrays[physical.ENVELOPE_PAYLOAD_INDEX]
    blocks = arrays[physical.ENVELOPE_BLOCK_ORDINAL]
    transactions = arrays[physical.ENVELOPE_TRANSACTION_INDEX]
    event_indexes = arrays[physical.ENVELOPE_EVENT_INDEX]
    # Assemble event ids once so the apply historical group workflow shares one value.
    event_ids = arrays[physical.ENVELOPE_CANONICAL_EVENT_ID]
    launches: list[tuple[LaunchTarget, int, int]] = []
    for row in range(row_start, row_stop):
        # Process range(row_start, row_stop) inside the bounded apply historical group
        # loop.
        local = row - decoded.start
        if not bool(decoded.pump_valid[local]):
            continue
        kind = int(kinds[row])
        payload = int(payload_indexes[row])
        # Guard this path with kind == int(EventKind.TOKEN_LAUNCH) before applying
        # effects.
        if kind == int(EventKind.TOKEN_LAUNCH):
            # Handle the apply historical group kind == int(EventKind.TOKEN_LAUNCH) branch
            # as a distinct logical block.
            venue_code = int(arrays[physical.TOKEN_VENUE_CODE][payload])
            if bool(venues.exists[venue_code]):
                raise OptimizedSnipingBackendUnsupported("Pump venue was launched twice")
            asset_code = int(arrays[physical.TOKEN_ASSET_CODE][payload])
            quote_code = int(arrays[physical.TOKEN_QUOTE_ASSET_CODE][payload])
            # Assemble venues exists[venue code] once so the apply historical group
            # workflow shares one value.
            venues.exists[venue_code] = True
            venues.asset_codes[venue_code] = asset_code
            venues.quote_asset_codes[venue_code] = quote_code
            venues.current[:, venue_code] = decoded.values[:, local]
            venues.last_active[:, venue_code] = decoded.values[:, local]
            # Assemble venues has last active[venue code] once so the apply historical
            # group workflow shares one value.
            venues.has_last_active[venue_code] = True
            venues.last_active_effective_at_unix_s[venue_code] = effective_at_unix_s
            developer_code = int(arrays[physical.TOKEN_DEVELOPER_CODE][payload])
            target = LaunchTarget(
                target_event_id=ContentDigest(event_ids[row].tobytes().hex()),
                # Keep the chain position and network id ChainPosition step visible while
                # building target.
                position=ChainPosition(
                    network_id=replay.network_id,
                    position_schema_id=replay.position_schema_id,
                    block_ordinal=int(blocks[row]),
                    transaction_index=int(transactions[row]),
                    # Keep the event indexes and row int step visible while building
                    # target.
                    event_index=int(event_indexes[row]),
                ),
                asset_id=AssetId(replay.dictionary_value("assets", asset_code)),
                developer_id=AccountId(replay.dictionary_value("accounts", developer_code)),
                creation_user_id=AccountId(
                    # Keep the accounts dictionary_value step visible while building
                    # target.
                    replay.dictionary_value(
                        "accounts",
                        int(arrays[physical.TOKEN_CREATION_USER_CODE][payload]),
                    )
                ),
                # Keep the venue id and dictionary value VenueId step visible while
                # building target.
                venue_id=VenueId(replay.dictionary_value("venues", venue_code)),
                quote_asset_id=AssetId(replay.dictionary_value("assets", quote_code)),
            )
            launches.append((target, venue_code, developer_code))
            continue
        # Guard this path with kind == int(EventKind.VENUE_TRADE) before applying effects.
        if kind == int(EventKind.VENUE_TRADE):
            # Handle the apply historical group kind == int(EventKind.VENUE_TRADE) branch
            # as a distinct logical block.
            venue_code = int(arrays[physical.TRADE_VENUE_CODE][payload])
            if not bool(venues.exists[venue_code]):
                raise OptimizedSnipingBackendUnsupported("trade references an unknown Pump venue")
            sold = int(arrays[physical.TRADE_SOLD_ASSET_CODE][payload])
            bought = int(arrays[physical.TRADE_BOUGHT_ASSET_CODE][payload])
            # Assemble asset once so the apply historical group workflow shares one value.
            asset = int(venues.asset_codes[venue_code])
            quote_asset = int(venues.quote_asset_codes[venue_code])
            if not (
                (sold == asset and bought == quote_asset)
                or (sold == quote_asset and bought == asset)
                # Evaluate the complete apply historical group sold, asset and bought
                # condition before guarded effects.
            ):
                # Handle the apply historical group sold, asset and bought condition as a
                # distinct block.
                raise OptimizedSnipingBackendUnsupported(
                    "Pump trade assets differ from venue identity"
                )
            venues.current[:, venue_code] = decoded.values[:, local]
            if int(decoded.values[5, local]) == protocol.primitive_active_lifecycle_code:
                # Handle the apply historical group primitive active lifecycle code,
                # protocol and values condition as a distinct block.
                venues.last_active[:, venue_code] = decoded.values[:, local]
                venues.has_last_active[venue_code] = True
                venues.last_active_effective_at_unix_s[venue_code] = effective_at_unix_s
            continue
        if kind == int(EventKind.VENUE_LIFECYCLE):
            # Handle the apply historical group kind == int(EventKind.VENUE_LIFECYCLE)
            # branch as a distinct logical block.
            venue_code = int(arrays[physical.LIFECYCLE_VENUE_CODE][payload])
            if not bool(venues.exists[venue_code]):
                # Handle the apply historical group not bool(venues.exists[venue_code])
                # branch as a distinct logical block.
                raise OptimizedSnipingBackendUnsupported(
                    "lifecycle references an unknown Pump venue"
                )
            venues.current[:, venue_code] = decoded.values[:, local]
            continue
        # Fail the apply historical group path with OptimizedSnipingBackendUnsupported for
        # pump event kind is unsupported; do not continue ambiguously.
        raise OptimizedSnipingBackendUnsupported("Pump event kind is unsupported")
    return launches


def _accept_buy(
    index: int,
    *,
    # Keep the clock input explicit in the accept buy contract.
    clock: CompactTransactionClock,
    protocol: _PrimitivePumpRuntime,
    network_costs: SnipingNetworkCostModel,
    portfolio: PortfolioState,
    accounts: WalletProvisioningReducer,
    venues: _VenueArena,
    # Keep the states input explicit in the accept buy contract.
    states: _StateArena,
    scheduled: list[_ScheduledAction],
    recorder: _OptimizedRecorder,
) -> bool:
    # Execute the accept buy workflow in explicit, reviewable steps.
    intent = _intent(states, index)
    effective_s = states.target_time_ns[index] // 1_000_000_000
    primitive_state = venues.state(states.venue_codes[index])
    requirements = protocol.account_requirements_from_primitive_state(primitive_state)
    network = network_costs.quote_buy(
        effective_at_unix_s=effective_s,
        requirements=requirements,
    )
    account_plan = accounts.reservation(
        roundtrip_id=intent.roundtrip_id,
        mint_asset_id=intent.asset_id,
        priced_requirements=network.account_requirements,
    )
    states.buy_network_costs[index] = network
    states.account_reservations[index] = account_plan
    try:
        # Perform the protected accept buy operation before explicit failure handling.
        reference = protocol.quote_buy_from_primitive_state(
            intent,
            primitive_state,
            effective_at_unix_s=effective_s,
        )
    # Translate protocol execution rejected through the accept buy boundary without hiding
    # other errors.
    except ProtocolExecutionRejected as error:
        # Translate the ProtocolExecutionRejected failure through the accept buy boundary.
        states.buy_failure_codes[index] = error.code
        states.statuses[index] = RoundTripStatus.BUY_REFERENCE_REJECTED
        states.terminal[index] = True
        states.account_components[index] = unsubmitted_account_records(
            accounts.state,
            account_plan,
        )
        recorder.append_audit(
            {
                # Keep boundary ordinal named so the code and buy reference rejected
                # payload passed to append_audit remains self-describing within accept
                # buy.
                "boundary_ordinal": intent.created_boundary_ordinal,
                "phase": int(SchedulerPhase.RISK_AND_ORDER_ACCEPTANCE),
                "reason": error.code,
                "record_type": "BUY_REFERENCE_REJECTED",
                "roundtrip_id": intent.roundtrip_id.hex,
                # Close the code and buy reference rejected payload only after all accept buy
                # fields are present.
            }
        )
        return False
    _validate_buy_quote(intent, reference)
    states.buy_references[index] = reference
    # Assemble states buy minimums[index] once so the accept buy workflow shares one
    # value.
    states.buy_minimums[index] = _minimum_output_atomic(
        reference.amount_out_atomic,
        intent.buy_slippage_bps,
    )
    landing = clock.transaction_after(intent.target_position, intent.buy_delay_transactions)
    reservation = _buy_reservation(intent, network, account_plan)
    if not _has_available(portfolio, reservation):
        # Handle the accept buy has available, portfolio and reservation condition as a
        # distinct block.
        states.statuses[index] = RoundTripStatus.BUY_PRE_SUBMIT_INSUFFICIENT_FUNDS
        states.terminal[index] = True
        states.account_components[index] = unsubmitted_account_records(
            accounts.state,
            account_plan,
        )
        recorder.append_audit(
            {
                "boundary_ordinal": intent.created_boundary_ordinal,
                # Pass phase explicitly to append_audit for insufficient funds and buy pre
                # submit rejected.
                "phase": int(SchedulerPhase.RISK_AND_ORDER_ACCEPTANCE),
                "reason": "INSUFFICIENT_FUNDS",
                "record_type": "BUY_PRE_SUBMIT_REJECTED",
                "roundtrip_id": intent.roundtrip_id.hex,
            }
            # Complete append_audit only after its insufficient funds and buy pre submit
            # rejected inputs are visible in accept buy.
        )
        return False
    _apply(
        portfolio,
        recorder,
        # Pass reserve buy explicitly to _apply for reserve buy and portfolio.
        _reserve_buy(intent, network, account_plan),
    )
    _schedule(
        scheduled,
        position=landing,
        # Pass kind explicitly so _schedule receives a reviewable buy landing and created
        # boundary ordinal input in accept buy.
        kind=_ActionKind.BUY_LANDING,
        creator_boundary=intent.created_boundary_ordinal,
        roundtrip_id=intent.roundtrip_id,
        state_index=index,
    )
    # Invoke append_audit for buy accepted and reserved and boundary ordinal as a visible
    # accept buy step.
    recorder.append_audit(
        {
            "boundary_ordinal": intent.created_boundary_ordinal,
            "eligible_boundary_ordinal": landing.boundary_ordinal,
            "phase": int(SchedulerPhase.RISK_AND_ORDER_ACCEPTANCE),
            # Keep record type named so the buy accepted and reserved and boundary ordinal
            # payload passed to append_audit remains self-describing within accept buy.
            "record_type": "BUY_ACCEPTED_AND_RESERVED",
            "reserved_assets": _asset_amounts_document(reservation),
            "roundtrip_id": intent.roundtrip_id.hex,
        }
    )
    # Return the completed accept buy result without a hidden fallback.
    return True


def _land_buy(
    index: int,
    *,
    position: ChainPosition,
    # Keep the clock input explicit in the land buy contract.
    clock: CompactTransactionClock,
    protocol: _PrimitivePumpRuntime,
    network_costs: SnipingNetworkCostModel,
    portfolio: PortfolioState,
    accounts: WalletProvisioningReducer,
    venues: _VenueArena,
    # Keep the states input explicit in the land buy contract.
    states: _StateArena,
    scheduled: list[_ScheduledAction],
    recorder: _OptimizedRecorder,
) -> bool:
    # Execute the land buy workflow in explicit, reviewable steps.
    intent = _intent(states, index)
    network = _buy_network(states, index)
    account_plan = _account_reservation(states, index)
    effective_s = clock.block_time_for_position(position) // 1_000_000_000
    states.buy_landing_positions[index] = position
    try:
        # Perform the protected land buy operation before explicit failure handling.
        landing = protocol.quote_buy_from_primitive_state(
            intent,
            venues.state(states.venue_codes[index]),
            effective_at_unix_s=effective_s,
        )
        # Invoke _validate_buy_quote for intent and landing as a visible land buy step.
        _validate_buy_quote(intent, landing)
        states.buy_landings[index] = landing
        if landing.amount_out_atomic < states.buy_minimums[index]:
            raise ProtocolExecutionRejected("MINIMUM_OUTPUT_NOT_MET")
    except ProtocolExecutionRejected as error:
        # Translate the ProtocolExecutionRejected failure through the land buy boundary.
        states.buy_failure_codes[index] = error.code
        states.statuses[index] = RoundTripStatus.BUY_LANDED_FAILED
        states.terminal[index] = True
        account_transition = accounts.preview_buy(account_plan, successful=False)
        transaction = _failed_buy_settlement(
            intent,
            # Pass boundary explicitly so _failed_buy_settlement receives a reviewable
            # boundary ordinal and fee collector account id input in land buy.
            boundary=position.boundary_ordinal,
            network=network,
            account_plan=account_plan,
            network_fee_account_id=network_costs.fee_collector_account_id,
            reason=error.code,
        )
        # Invoke _apply for portfolio and recorder as a visible land buy step.
        _apply_with_accounts(
            portfolio,
            recorder,
            transaction,
            accounts=accounts,
            transition=account_transition,
        )
        states.account_components[index] = account_transition.records
        recorder.append_audit(
            {
                "boundary_ordinal": position.boundary_ordinal,
                "phase": int(SchedulerPhase.VENUE_EXECUTION_AND_LEDGER_COMMIT),
                # Keep reason named so the code and buy landed failed network fee charged
                # payload passed to append_audit remains self-describing within land buy.
                "reason": error.code,
                "record_type": "BUY_LANDED_FAILED_NETWORK_FEE_CHARGED",
                "roundtrip_id": intent.roundtrip_id.hex,
            }
        )
        # Return the completed land buy result without a hidden fallback.
        return False
    account_transition = accounts.preview_buy(account_plan, successful=True)
    transaction = _successful_buy_settlement(
        intent,
        boundary=position.boundary_ordinal,
        quote=landing,
        # Pass network explicitly so _successful_buy_settlement receives a reviewable
        # boundary ordinal and fee collector account id input in land buy.
        network=network,
        account_plan=account_plan,
        account_transition=account_transition,
        network_fee_account_id=network_costs.fee_collector_account_id,
    )
    _apply_with_accounts(
        portfolio,
        recorder,
        transaction,
        accounts=accounts,
        transition=account_transition,
    )
    recorder.append_fill(
        # Pass fill explicitly to append_fill for side and boundary ordinal.
        _fill(
            intent,
            side=landing.side,
            quote=landing,
            boundary=position.boundary_ordinal,
            # Complete _fill only after its side and boundary ordinal inputs are visible in
            # land buy.
        )
    )
    states.acquired_tokens[index] = landing.amount_out_atomic
    states.account_components[index] = account_transition.records
    states.cashback_receivables[index] += landing.cashback_receivable_atomic
    states.statuses[index] = RoundTripStatus.OPEN_AT_HORIZON
    fill_time_ns = clock.block_time_for_position(position)
    # Assemble decision position once so the land buy workflow shares one value.
    decision_position = clock.first_nonempty_transaction_at_or_after(
        after_position=position,
        target_time_ns=fill_time_ns + intent.sell_decision_delay_ns,
    )
    _schedule(
        # Pass scheduled explicitly so _schedule receives a reviewable sell decision and
        # boundary ordinal input in land buy.
        scheduled,
        position=decision_position,
        kind=_ActionKind.SELL_DECISION,
        creator_boundary=position.boundary_ordinal,
        roundtrip_id=intent.roundtrip_id,
        # Pass state index explicitly so _schedule receives a reviewable sell decision and
        # boundary ordinal input in land buy.
        state_index=index,
    )
    recorder.append_audit(
        {
            "boundary_ordinal": position.boundary_ordinal,
            # Pass phase explicitly to append_audit for buy filled and boundary ordinal.
            "phase": int(SchedulerPhase.VENUE_EXECUTION_AND_LEDGER_COMMIT),
            "record_type": "BUY_FILLED",
            "roundtrip_id": intent.roundtrip_id.hex,
            "sell_decision_boundary_ordinal": decision_position.boundary_ordinal,
        }
        # Complete append_audit only after its buy filled and boundary ordinal inputs are
        # visible in land buy.
    )
    return True


def _decide_sell(
    index: int,
    *,
    # Keep the position input explicit in the decide sell contract.
    position: ChainPosition,
    clock: CompactTransactionClock,
    protocol: _PrimitivePumpRuntime,
    network_costs: SnipingNetworkCostModel,
    portfolio: PortfolioState,
    # Keep the venues input explicit in the decide sell contract.
    venues: _VenueArena,
    states: _StateArena,
    scheduled: list[_ScheduledAction],
    recorder: _OptimizedRecorder,
) -> None:
    # Execute the decide sell workflow in explicit, reviewable steps.
    intent = _intent(states, index)
    tokens = states.acquired_tokens[index]
    if tokens <= 0 or states.terminal[index]:
        raise SnipingEngineError(SnipingEngineErrorCode.INTERNAL_STATE_INVALID)
    effective_s = clock.block_time_for_position(position) // 1_000_000_000
    # Assemble states sell decision positions[index] once so the decide sell workflow
    # shares one value.
    states.sell_decision_positions[index] = position
    try:
        # Perform the protected decide sell operation before explicit failure handling.
        reference = protocol.quote_sell_from_primitive_state(
            intent,
            venues.state(states.venue_codes[index]),
            tokens_in_atomic=tokens,
            effective_at_unix_s=effective_s,
            # Complete quote_sell_from_primitive_state only after its state and venue codes
            # inputs are visible in decide sell.
        )
    except ProtocolExecutionRejected as error:
        # Translate the ProtocolExecutionRejected failure through the decide sell
        # boundary.
        states.sell_failure_codes[index] = error.code
        states.statuses[index] = RoundTripStatus.SELL_REFERENCE_UNAVAILABLE_OPEN
        states.terminal[index] = True
        recorder.append_audit(
            {
                # Keep boundary ordinal named so the code and sell reference unavailable
                # payload passed to append_audit remains self-describing within decide
                # sell.
                "boundary_ordinal": position.boundary_ordinal,
                "phase": int(SchedulerPhase.STRATEGY_CALLBACK),
                "reason": error.code,
                "record_type": "SELL_REFERENCE_UNAVAILABLE",
                "roundtrip_id": intent.roundtrip_id.hex,
                # Close the code and sell reference unavailable payload only after all decide
                # sell fields are present.
            }
        )
        return
    _validate_sell_quote(intent, tokens, reference)
    states.sell_references[index] = reference
    # Assemble states sell minimums[index] once so the decide sell workflow shares one
    # value.
    states.sell_minimums[index] = _minimum_output_atomic(
        reference.amount_out_atomic,
        intent.sell_slippage_bps,
    )
    landing = clock.transaction_after(position, intent.sell_delay_transactions)
    # Assemble network once so the decide sell workflow shares one value.
    network = network_costs.quote_sell(effective_at_unix_s=effective_s)
    states.sell_network_costs[index] = network
    if portfolio.available(intent.asset_id) < tokens:
        raise SnipingEngineError(SnipingEngineErrorCode.PORTFOLIO_INVARIANT)
    sell_reservation = _sell_reservation(
        # Pass intent explicitly so _sell_reservation receives a reviewable intent and
        # tokens input in decide sell.
        intent,
        tokens_atomic=tokens,
        network=network,
    )
    if not _has_available(portfolio, sell_reservation):
        # Handle the decide sell has available, portfolio and sell reservation condition
        # as a distinct block.
        states.statuses[index] = RoundTripStatus.SELL_PRE_SUBMIT_INSUFFICIENT_FUNDS_OPEN
        states.terminal[index] = True
        recorder.append_audit(
            {
                "boundary_ordinal": position.boundary_ordinal,
                # Pass phase explicitly to append_audit for insufficient network fee and
                # sell pre submit rejected.
                "phase": int(SchedulerPhase.RISK_AND_ORDER_ACCEPTANCE),
                "reason": "INSUFFICIENT_NETWORK_FEE",
                "record_type": "SELL_PRE_SUBMIT_REJECTED",
                "roundtrip_id": intent.roundtrip_id.hex,
            }
            # Complete append_audit only after its insufficient network fee and sell pre
            # submit rejected inputs are visible in decide sell.
        )
        return
    _apply(
        portfolio,
        recorder,
        # Pass reserve sell explicitly to _apply for boundary ordinal and reserve sell.
        _reserve_sell(
            intent,
            tokens_atomic=tokens,
            network=network,
            boundary=position.boundary_ordinal,
            # Complete _reserve_sell only after its boundary ordinal and intent inputs are
            # visible in decide sell.
        ),
    )
    _schedule(
        scheduled,
        position=landing,
        # Pass kind explicitly so _schedule receives a reviewable sell landing and
        # boundary ordinal input in decide sell.
        kind=_ActionKind.SELL_LANDING,
        creator_boundary=position.boundary_ordinal,
        roundtrip_id=intent.roundtrip_id,
        state_index=index,
    )
    # Invoke append_audit for sell accepted and reserved and boundary ordinal as a visible
    # decide sell step.
    recorder.append_audit(
        {
            "boundary_ordinal": position.boundary_ordinal,
            "eligible_boundary_ordinal": landing.boundary_ordinal,
            "phase": int(SchedulerPhase.RISK_AND_ORDER_ACCEPTANCE),
            # Keep record type named so the sell accepted and reserved and boundary
            # ordinal payload passed to append_audit remains self-describing within decide
            # sell.
            "record_type": "SELL_ACCEPTED_AND_RESERVED",
            "roundtrip_id": intent.roundtrip_id.hex,
        }
    )


def _land_sell(
    # Keep the index input explicit in the land sell contract.
    index: int,
    *,
    position: ChainPosition,
    clock: CompactTransactionClock,
    protocol: _PrimitivePumpRuntime,
    # Keep the network costs input explicit in the land sell contract.
    network_costs: SnipingNetworkCostModel,
    portfolio: PortfolioState,
    accounts: WalletProvisioningReducer,
    venues: _VenueArena,
    states: _StateArena,
    recorder: _OptimizedRecorder,
    # Keep the bool input explicit in the land sell contract.
) -> bool:
    # Execute the land sell workflow in explicit, reviewable steps.
    intent = _intent(states, index)
    network = _sell_network(states, index)
    tokens = states.acquired_tokens[index]
    effective_s = clock.block_time_for_position(position) // 1_000_000_000
    states.sell_landing_positions[index] = position
    # Keep expected failures inside the land sell error boundary.
    try:
        # Perform the protected land sell operation before explicit failure handling.
        landing = protocol.quote_sell_from_primitive_state(
            intent,
            venues.state(states.venue_codes[index]),
            tokens_in_atomic=tokens,
            effective_at_unix_s=effective_s,
            # Complete quote_sell_from_primitive_state only after its state and venue codes
            # inputs are visible in land sell.
        )
        _validate_sell_quote(intent, tokens, landing)
        states.sell_landings[index] = landing
        if landing.amount_out_atomic < states.sell_minimums[index]:
            raise ProtocolExecutionRejected("MINIMUM_OUTPUT_NOT_MET")
    # Translate protocol execution rejected through the land sell boundary without hiding
    # other errors.
    except ProtocolExecutionRejected as error:
        # Translate the ProtocolExecutionRejected failure through the land sell boundary.
        states.sell_failure_codes[index] = error.code
        states.statuses[index] = RoundTripStatus.SELL_LANDED_FAILED_OPEN
        states.terminal[index] = True
        transaction = _failed_sell_settlement(
            intent,
            # Pass boundary explicitly so _failed_sell_settlement receives a reviewable
            # boundary ordinal and fee collector account id input in land sell.
            boundary=position.boundary_ordinal,
            tokens_atomic=tokens,
            network=network,
            network_fee_account_id=network_costs.fee_collector_account_id,
            reason=error.code,
            # Complete _failed_sell_settlement only after its boundary ordinal and fee
            # collector account id inputs are visible in land sell.
        )
        _apply(portfolio, recorder, transaction)
        recorder.append_audit(
            {
                "boundary_ordinal": position.boundary_ordinal,
                # Pass phase explicitly to append_audit for code and sell landed failed
                # network fee charged.
                "phase": int(SchedulerPhase.VENUE_EXECUTION_AND_LEDGER_COMMIT),
                "reason": error.code,
                "record_type": "SELL_LANDED_FAILED_NETWORK_FEE_CHARGED",
                "roundtrip_id": intent.roundtrip_id.hex,
            }
            # Complete append_audit only after its code and sell landed failed network fee
            # charged inputs are visible in land sell.
        )
        return False
    account_transition = accounts.preview_sell(
        roundtrip_id=intent.roundtrip_id,
        mint_asset_id=intent.asset_id,
        records=states.account_components[index],
        successful=True,
    )
    transaction = _successful_sell_settlement(
        intent,
        boundary=position.boundary_ordinal,
        # Pass quote explicitly so _successful_sell_settlement receives a reviewable
        # boundary ordinal and refundable deposits input in land sell.
        quote=landing,
        network=network,
        tokens_atomic=tokens,
        account_transition=account_transition,
        # Pass network fee account id explicitly so _successful_sell_settlement receives a
        # reviewable boundary ordinal and refundable deposits input in land sell.
        network_fee_account_id=network_costs.fee_collector_account_id,
    )
    _apply_with_accounts(
        portfolio,
        recorder,
        transaction,
        accounts=accounts,
        transition=account_transition,
    )
    recorder.append_fill(
        _fill(
            # Pass intent explicitly so _fill receives a reviewable side and boundary
            # ordinal input in land sell.
            intent,
            side=landing.side,
            quote=landing,
            boundary=position.boundary_ordinal,
        )
        # Complete append_fill only after its side and boundary ordinal inputs are visible in
        # land sell.
    )
    states.cashback_receivables[index] += landing.cashback_receivable_atomic
    states.account_components[index] = account_transition.records
    states.statuses[index] = RoundTripStatus.CLOSED
    states.terminal[index] = True
    recorder.append_audit(
        # Open the sell filled and account closed and boundary ordinal payload explicitly
        # for append_audit within land sell.
        {
            "boundary_ordinal": position.boundary_ordinal,
            "phase": int(SchedulerPhase.VENUE_EXECUTION_AND_LEDGER_COMMIT),
            "realized_cash_pnl_atomic": recorder.cashflows.amount(
                intent.roundtrip_id,
                # Pass intent explicitly so amount receives a reviewable roundtrip id and
                # quote asset id input in land sell.
                intent.quote_asset_id,
            ),
            "record_type": "SELL_FILLED_AND_ACCOUNT_CLOSED",
            "roundtrip_id": intent.roundtrip_id.hex,
        }
        # Complete append_audit only after its sell filled and account closed and boundary
        # ordinal inputs are visible in land sell.
    )
    return True


def _finalize_summary(
    *,
    replay: NumpyMmapReplaySource,
    # Keep the clock input explicit in the finalize summary contract.
    clock: CompactTransactionClock,
    strategy: _PrimitivePumpStrategy,
    protocol: _PrimitivePumpRuntime,
    network_costs: SnipingNetworkCostModel,
    config: SnipingRunConfig,
    # Keep the portfolio input explicit in the finalize summary contract.
    portfolio: PortfolioState,
    venues: _VenueArena,
    states: _StateArena,
    recorder: _OptimizedRecorder,
    counts: _RunCounts,
    # Keep the sniping run summary input explicit in the finalize summary contract.
) -> SnipingRunSummary:
    # Execute the finalize summary workflow in explicit, reviewable steps.
    final_time_unix_s = clock.block_time_ns[-1] // 1_000_000_000
    aggregates = _RoundTripAggregateAccumulator()
    for index in range(len(states.targets)):
        # Process range(len(states.targets)) inside the bounded finalize summary loop.
        record = _finalize_record(
            index,
            committed_quote_cashflow_atomic=recorder.cashflows.amount(
                states.roundtrip_ids[index],
                states.targets[index].quote_asset_id,
                # Complete amount only after its roundtrip ids and quote asset id inputs are
                # visible in finalize summary.
            ),
            states=states,
            venues=venues,
            protocol=protocol,
            network_costs=network_costs,
            # Pass config explicitly so _finalize_record receives a reviewable amount and
            # quote asset id input in finalize summary.
            config=config,
            final_time_unix_s=final_time_unix_s,
        )
        recorder.append_roundtrip(record)
        aggregates.append(record)
    # Assemble final balances once so the finalize summary workflow shares one value.
    final_balances = portfolio.semantic_balances()
    balances = CanonicalStreamHasher("backtest.sniping-final-balances.v1")
    for row in final_balances:
        balances.append(list(row))
    accepted_order_count = counts.accepted_buy_count + aggregates.accepted_sell_count
    # Assemble rejected order count once so the finalize summary workflow shares one
    # value.
    rejected_order_count = aggregates.rejected_buy_count + aggregates.rejected_sell_count
    failed_order_count = counts.failed_buy_count + counts.failed_sell_count
    result_document = {
        "accepted_order_count": accepted_order_count,
        "account_deposit_locked_atomic": aggregates.account_deposit_locked_atomic,
        # Keep the account deposit paid atomic component named inside the result document
        # contract.
        "account_deposit_paid_atomic": aggregates.account_deposit_paid_atomic,
        "account_deposit_refunded_atomic": aggregates.account_deposit_refunded_atomic,
        "adverse_slippage_count": aggregates.adverse_slippage_count,
        "buy_slippage_failure_count": aggregates.buy_slippage_failure_count,
        "cashback_receivable_atomic": aggregates.cashback_receivable_atomic,
        # Keep the closed roundtrip count component named inside the result document
        # contract.
        "closed_roundtrip_count": aggregates.closed_count,
        "creator_fee_paid_atomic": aggregates.creator_fee_paid_atomic,
        "economic_pnl_atomic": aggregates.economic_pnl_atomic,
        "execution_mode": config.execution_mode.value,
        "failed_buy_count": counts.failed_buy_count,
        "failed_sell_count": counts.failed_sell_count,
        # Keep the favorable slippage count component named inside the result document
        # contract.
        "favorable_slippage_count": aggregates.favorable_slippage_count,
        "fill_count": recorder.fills.count,
        "fill_hash": recorder.fills.digest.hex,
        "filled_sell_count": aggregates.filled_sell_count,
        "final_balances_count": len(final_balances),
        "final_balances_digest": balances.digest.hex,
        # Keep the ledger hash component named inside the result document contract.
        "ledger_hash": recorder.ledger.digest.hex,
        "ledger_transaction_count": recorder.ledger.count,
        "network_base_fee_paid_atomic": aggregates.network_base_fee_paid_atomic,
        "network_priority_fee_paid_atomic": aggregates.network_priority_fee_paid_atomic,
        "open_position_count": aggregates.open_count,
        # Keep the protocol fee paid atomic component named inside the result document
        # contract.
        "protocol_fee_paid_atomic": aggregates.protocol_fee_paid_atomic,
        "real_liquidity_sufficient_filled_sell_count": (
            aggregates.real_liquidity_sufficient_filled_sell_count
        ),
        "realized_cash_pnl_atomic": aggregates.realized_cash_pnl_atomic,
        "rejected_order_count": rejected_order_count,
        "roundtrip_count": recorder.roundtrips.count,
        "roundtrip_digest": recorder.roundtrips.digest.hex,
        # Keep the sell slippage failure count component named inside the result document
        # contract.
        "sell_slippage_failure_count": aggregates.sell_slippage_failure_count,
        "settlement_policy_id": liquidity_policy_id_for_execution_mode(config.execution_mode),
        "gross_sell_settlement_atomic": aggregates.gross_sell_settlement_atomic,
        "venue_funded_sell_atomic": aggregates.venue_funded_sell_atomic,
        "synthetic_funded_sell_atomic": aggregates.synthetic_funded_sell_atomic,
        "synthetic_liquidity_used_sell_count": aggregates.synthetic_liquidity_used_sell_count,
        "unvalued_open_position_count": aggregates.unvalued_open_position_count,
        "valuation_status": aggregates.valuation_status.value,
        "valued_economic_pnl_subtotal_atomic": (aggregates.valued_economic_pnl_subtotal_atomic),
    }
    # Evaluate the complete finalize summary historical group count, group count and
    # historical event count condition before guarded effects.
    if (
        counts.historical_group_count != replay.manifest.group_count
        or counts.historical_event_count != replay.event_count
        or counts.delivered_event_count != replay.event_count
    ):
        # Fail the finalize summary path with SnipingEngineError for source count mismatch
        # and sniping engine error code when historical group count, group count and
        # historical event count is true; do not continue ambiguously.
        raise SnipingEngineError(SnipingEngineErrorCode.SOURCE_COUNT_MISMATCH)
    return SnipingRunSummary(
        dataset_logical_content_hash=replay.logical_content_hash,
        replay_semantics_id=replay.replay_semantics_id,
        engine_bundle_id=config.engine_bundle_id,
        # Pass strategy bundle id explicitly so SnipingRunSummary receives a reviewable v2
        # and logical content hash input in finalize summary.
        strategy_bundle_id=strategy.bundle_id,
        protocol_bundle_id=protocol.bundle_id,
        network_cost_bundle_id=network_costs.bundle_id,
        historical_group_count=counts.historical_group_count,
        historical_event_count=counts.historical_event_count,
        # Pass delivered event count explicitly so SnipingRunSummary receives a reviewable
        # v2 and logical content hash input in finalize summary.
        delivered_event_count=counts.delivered_event_count,
        target_count=counts.target_count,
        cooldown_skipped_count=counts.cooldown_skipped_count,
        accepted_buy_count=counts.accepted_buy_count,
        accepted_sell_count=aggregates.accepted_sell_count,
        # Pass rejected buy count explicitly so SnipingRunSummary receives a reviewable v2
        # and logical content hash input in finalize summary.
        rejected_buy_count=aggregates.rejected_buy_count,
        rejected_sell_count=aggregates.rejected_sell_count,
        accepted_order_count=accepted_order_count,
        rejected_order_count=rejected_order_count,
        filled_order_count=recorder.fills.count,
        # Pass failed order count explicitly so SnipingRunSummary receives a reviewable v2
        # and logical content hash input in finalize summary.
        failed_order_count=failed_order_count,
        closed_roundtrip_count=aggregates.closed_count,
        open_position_count=aggregates.open_count,
        failed_buy_count=counts.failed_buy_count,
        failed_sell_count=counts.failed_sell_count,
        # Pass realized cash pnl atomic explicitly so SnipingRunSummary receives a
        # reviewable v2 and logical content hash input in finalize summary.
        realized_cash_pnl_atomic=aggregates.realized_cash_pnl_atomic,
        valuation_status=aggregates.valuation_status,
        unvalued_open_position_count=aggregates.unvalued_open_position_count,
        valued_economic_pnl_subtotal_atomic=(aggregates.valued_economic_pnl_subtotal_atomic),
        economic_pnl_atomic=aggregates.economic_pnl_atomic,
        # Pass cashback receivable atomic explicitly so SnipingRunSummary receives a
        # reviewable v2 and logical content hash input in finalize summary.
        cashback_receivable_atomic=aggregates.cashback_receivable_atomic,
        protocol_fee_paid_atomic=aggregates.protocol_fee_paid_atomic,
        creator_fee_paid_atomic=aggregates.creator_fee_paid_atomic,
        network_base_fee_paid_atomic=aggregates.network_base_fee_paid_atomic,
        network_priority_fee_paid_atomic=aggregates.network_priority_fee_paid_atomic,
        # Pass account deposit paid atomic explicitly so SnipingRunSummary receives a
        # reviewable v2 and logical content hash input in finalize summary.
        account_deposit_paid_atomic=aggregates.account_deposit_paid_atomic,
        account_deposit_refunded_atomic=aggregates.account_deposit_refunded_atomic,
        account_deposit_locked_atomic=aggregates.account_deposit_locked_atomic,
        favorable_slippage_count=aggregates.favorable_slippage_count,
        adverse_slippage_count=aggregates.adverse_slippage_count,
        # Pass buy slippage failure count explicitly so SnipingRunSummary receives a
        # reviewable v2 and logical content hash input in finalize summary.
        buy_slippage_failure_count=aggregates.buy_slippage_failure_count,
        sell_slippage_failure_count=aggregates.sell_slippage_failure_count,
        ledger_transaction_count=recorder.ledger.count,
        fill_count=recorder.fills.count,
        roundtrip_count=recorder.roundtrips.count,
        # Pass audit hash explicitly so SnipingRunSummary receives a reviewable v2 and
        # logical content hash input in finalize summary.
        audit_hash=recorder.audit.digest,
        ledger_hash=recorder.ledger.digest,
        fill_hash=recorder.fills.digest,
        roundtrip_digest=recorder.roundtrips.digest,
        final_balances_digest=balances.digest,
        # Include result hash in the completed finalize summary result.
        result_hash=domain_digest("backtest.canonical-sniping-run-result.v4", result_document),
        final_balances=final_balances,
        execution_mode=config.execution_mode,
        settlement_policy_id=liquidity_policy_id_for_execution_mode(config.execution_mode),
        filled_sell_count=aggregates.filled_sell_count,
        real_liquidity_sufficient_filled_sell_count=(
            aggregates.real_liquidity_sufficient_filled_sell_count
        ),
        synthetic_liquidity_used_sell_count=aggregates.synthetic_liquidity_used_sell_count,
        gross_sell_settlement_atomic=aggregates.gross_sell_settlement_atomic,
        venue_funded_sell_atomic=aggregates.venue_funded_sell_atomic,
        synthetic_funded_sell_atomic=aggregates.synthetic_funded_sell_atomic,
    )


def _finalize_record(
    index: int,
    # Close the finalize record signature after its explicit inputs.
    *,
    committed_quote_cashflow_atomic: int,
    states: _StateArena,
    venues: _VenueArena,
    protocol: _PrimitivePumpRuntime,
    # Keep the network costs input explicit in the finalize record contract.
    network_costs: SnipingNetworkCostModel,
    config: SnipingRunConfig,
    final_time_unix_s: int,
) -> RoundTripRecord:
    # Execute the finalize record workflow in explicit, reviewable steps.
    state = states.materialize(index)
    buy = _buy_leg(state)
    sell = _sell_leg(state)
    realized: int | None = None
    mtm_status = MtmStatus.NOT_APPLICABLE
    # Assemble mtm value once so the finalize record workflow shares one value.
    mtm_value: int | None = None
    mtm_pnl: int | None = None
    mtm_liquidity: QuoteLiquidityEvidenceRecord | None = None
    economic: int | None = None
    run_locked_quote_value = _asset_amount(
        run_locked_value(state.account_components),
        state.target.quote_asset_id,
    )
    if state.status is RoundTripStatus.CLOSED:
        # Handle the finalize record state.status is RoundTripStatus.CLOSED branch as a
        # distinct logical block.
        realized = committed_quote_cashflow_atomic
        economic = realized + state.cashback_receivable_atomic + run_locked_quote_value
    # Handle the finalize record complement of state.status is RoundTripStatus.CLOSED
    # explicitly.
    elif state.acquired_token_amount_atomic > 0:
        # Handle the finalize record state.acquired_token_amount_atomic > 0 branch as a
        # distinct logical block.
        intent = _intent(states, index)
        try:
            # Perform the protected finalize record operation before explicit failure
            # handling.
            valuation = protocol.valuation_quote_from_primitive_state(
                intent,
                venues.state(states.venue_codes[index]),
                venues.active_state(states.venue_codes[index]),
                (
                    # Keep valuation quote from primitive state, intent and protocol
                    # visible while completing valuation_quote_from_primitive_state within
                    # finalize record.
                    None
                    if int(venues.last_active_effective_at_unix_s[states.venue_codes[index]]) < 0
                    else int(venues.last_active_effective_at_unix_s[states.venue_codes[index]])
                ),
                tokens_in_atomic=state.acquired_token_amount_atomic,
                # Pass effective at unix s explicitly so
                # valuation_quote_from_primitive_state receives a reviewable state and
                # venue codes input in finalize record.
                effective_at_unix_s=final_time_unix_s,
            )
        except ProtocolExecutionRejected:
            valuation = None
        if valuation is None:
            # Assemble mtm status once so the finalize record workflow shares one value.
            mtm_status = MtmStatus.UNAVAILABLE
        else:
            # Handle the finalize record complement of valuation is None explicitly.
            network = network_costs.quote_sell(effective_at_unix_s=final_time_unix_s)
            mtm_status = (
                MtmStatus.STALE_PRE_MIGRATION
                if valuation.stale_pre_migration
                else MtmStatus.EXECUTABLE
                # Complete the mtm status group only after its semantic components are
                # visible.
            )
            mtm_liquidity = _quote_liquidity_record(valuation.quote)
            mtm_value = (
                valuation.quote.amount_out_atomic
                - _amount_if_asset(
                    network.fee_asset_id,
                    # Pass intent explicitly so _amount_if_asset receives a reviewable fee
                    # asset id and quote asset id input in finalize record.
                    intent.quote_asset_id,
                    network.transaction_fee_atomic,
                )
                + _asset_amount(
                    refundable_mint_deposits(state.account_components),
                    intent.quote_asset_id,
                )
            )
            mtm_pnl = committed_quote_cashflow_atomic + mtm_value
            # Assemble economic once so the finalize record workflow shares one value.
            economic = mtm_pnl + state.cashback_receivable_atomic + run_locked_quote_value
    else:
        # Handle the finalize record complement of state.acquired_token_amount_atomic > 0
        # explicitly.
        realized = committed_quote_cashflow_atomic
        economic = realized + state.cashback_receivable_atomic + run_locked_quote_value
    return RoundTripRecord(
        # Pass roundtrip id explicitly so RoundTripRecord receives a reviewable roundtrip
        # ids and network id input in finalize record.
        roundtrip_id=states.roundtrip_ids[index],
        network_id=state.target.position.network_id,
        position_schema_id=state.target.position.position_schema_id,
        target_event_id=state.target.target_event_id,
        target_position=state.target.position,
        # Pass target time ns explicitly so RoundTripRecord receives a reviewable
        # roundtrip ids and network id input in finalize record.
        target_time_ns=state.target_time_ns,
        developer_id=state.target.developer_id,
        creation_user_id=state.target.creation_user_id,
        asset_id=state.target.asset_id,
        quote_asset_id=state.target.quote_asset_id,
        # Pass venue id explicitly so RoundTripRecord receives a reviewable roundtrip ids
        # and network id input in finalize record.
        venue_id=state.target.venue_id,
        cooldown_consumed=state.cooldown_consumed,
        cooldown_until_ns=state.cooldown_until_ns,
        status=state.status,
        buy=buy,
        # Pass sell explicitly so RoundTripRecord receives a reviewable roundtrip ids and
        # network id input in finalize record.
        sell=sell,
        acquired_token_amount_atomic=state.acquired_token_amount_atomic,
        cashback_receivable_atomic=state.cashback_receivable_atomic,
        realized_cash_pnl_atomic=realized,
        # Pass mtm status explicitly so RoundTripRecord receives a reviewable roundtrip
        # ids and network id input in finalize record.
        mtm_status=mtm_status,
        mtm_liquidation_value_atomic=mtm_value,
        mtm_cash_pnl_atomic=mtm_pnl,
        economic_pnl_atomic=economic,
        account_profile_id=config.wallet_account_profile_id,
        account_components=state.account_components,
        execution_mode=config.execution_mode,
        sell_reference_liquidity=_optional_quote_liquidity_record(state.sell_reference),
        sell_landing_liquidity=_optional_quote_liquidity_record(state.sell_landing),
        mtm_liquidity=mtm_liquidity,
        settled_venue_funded_atomic=_settled_venue_funded_atomic(state),
        settled_synthetic_funded_atomic=_settled_synthetic_funded_atomic(state),
    )


# Define intent as one focused operation with an explicit boundary.
def _intent(states: _StateArena, index: int) -> RoundTripIntent:
    # Execute the intent workflow in explicit, reviewable steps.
    intent = states.intents[index]
    if intent is None:
        raise SnipingEngineError(SnipingEngineErrorCode.INTERNAL_STATE_INVALID)
    return intent


def _buy_network(states: _StateArena, index: int) -> NetworkCostQuote:
    # Execute the buy network workflow in explicit, reviewable steps.
    value = states.buy_network_costs[index]
    if value is None:
        raise SnipingEngineError(SnipingEngineErrorCode.INTERNAL_STATE_INVALID)
    return value


def _account_reservation(states: _StateArena, index: int) -> AccountReservationPlan:
    """Return the exact account reservation accepted for an optimized order."""

    value = states.account_reservations[index]
    if value is None:
        raise SnipingEngineError(SnipingEngineErrorCode.INTERNAL_STATE_INVALID)
    return value


def _sell_network(states: _StateArena, index: int) -> NetworkCostQuote:
    # Execute the sell network workflow in explicit, reviewable steps.
    value = states.sell_network_costs[index]
    if value is None:
        raise SnipingEngineError(SnipingEngineErrorCode.INTERNAL_STATE_INVALID)
    return value


def _apply(
    # Keep the portfolio input explicit in the apply contract.
    portfolio: PortfolioState,
    recorder: _OptimizedRecorder,
    transaction: LedgerTransaction,
) -> None:
    # Execute the apply workflow in explicit, reviewable steps.
    try:
        candidate = portfolio.preview(transaction)
    except PortfolioInvariantError as error:
        raise SnipingEngineError(SnipingEngineErrorCode.PORTFOLIO_INVARIANT) from error
    portfolio.commit(candidate)
    # Invoke append_ledger for transaction as a visible apply step.
    recorder.append_ledger(transaction)


def _apply_with_accounts(
    portfolio: PortfolioState,
    recorder: _OptimizedRecorder,
    transaction: LedgerTransaction,
    *,
    accounts: WalletProvisioningReducer,
    transition: AccountProvisioningTransition,
) -> None:
    """Commit the shared account reducer with the matching portfolio candidate."""

    try:
        candidate = portfolio.preview(transaction)
    except PortfolioInvariantError as error:
        raise SnipingEngineError(SnipingEngineErrorCode.PORTFOLIO_INVARIANT) from error
    portfolio.commit(candidate)
    accounts.commit(transition)
    recorder.append_ledger(transaction)


def _schedule(
    scheduled: list[_ScheduledAction],
    *,
    position: ChainPosition,
    # Keep the kind input explicit in the schedule contract.
    kind: _ActionKind,
    creator_boundary: int,
    roundtrip_id: ContentDigest,
    state_index: int,
) -> None:
    # Execute the schedule workflow in explicit, reviewable steps.
    if position.boundary_ordinal <= creator_boundary:
        raise SnipingEngineError(SnipingEngineErrorCode.INTERNAL_STATE_INVALID)
    action_name = {
        _ActionKind.BUY_LANDING: "buy-landing",
        _ActionKind.SELL_DECISION: "sell-decision",
        # Keep the action kind component named inside the action name contract.
        _ActionKind.SELL_LANDING: "sell-landing",
    }[kind]
    causal_id = domain_digest(
        "backtest.sniping-scheduled-action.v1",
        {"action": action_name, "roundtrip_id": roundtrip_id.hex},
        # Complete domain_digest only after its v1 and action inputs are visible in schedule.
    )
    phase = 40 if kind is _ActionKind.SELL_DECISION else 60
    heapq.heappush(
        scheduled,
        _ScheduledAction(
            # Pass position explicitly so _ScheduledAction receives a reviewable boundary
            # ordinal and hex input in schedule.
            position.boundary_ordinal,
            phase,
            creator_boundary,
            causal_id.hex,
            kind,
            # Pass state index explicitly so _ScheduledAction receives a reviewable
            # boundary ordinal and hex input in schedule.
            state_index,
        ),
    )


def _pop_actions(
    scheduled: list[_ScheduledAction],
    # Keep the boundary input explicit in the pop actions contract.
    boundary: int,
    *,
    maximum_phase: int,
) -> tuple[_ScheduledAction, ...]:
    # Execute the pop actions workflow in explicit, reviewable steps.
    values: list[_ScheduledAction] = []
    while scheduled:
        # Keep the scheduled loop body bounded within pop actions.
        item = scheduled[0]
        if item.release_boundary_ordinal != boundary or item.phase > maximum_phase:
            break
        values.append(heapq.heappop(scheduled))
    return tuple(values)


# Define boundary batches as one focused operation with an explicit boundary.
def _boundary_batches(
    offsets: npt.NDArray[np.generic],
    batch_rows: int,
    readahead: int,
) -> Iterator[tuple[int, int]]:
    # Execute the boundary batches workflow in explicit, reviewable steps.
    boundary_count = len(offsets) - 1
    start = 0
    pending: list[tuple[int, int]] = []
    while start < boundary_count:
        # Keep the start < boundary_count loop body bounded within boundary batches.
        row_start = int(offsets[start])
        stop = start
        while stop < boundary_count and int(offsets[stop + 1]) - row_start <= batch_rows:
            stop += 1
        if stop == start:
            # Handle the boundary batches stop == start branch as a distinct logical
            # block.
            raise OptimizedSnipingBackendUnsupported(
                "historical transaction group cannot fit the configured batch"
            )
        pending.append((start, stop))
        start = stop
        # Guard this path with len(pending) == readahead before applying effects.
        if len(pending) == readahead:
            # Handle the boundary batches len(pending) == readahead branch as a distinct
            # logical block.
            yield pending[0][0], pending[-1][1]
            pending.clear()
    if pending:
        yield pending[0][0], pending[-1][1]


def _dictionary_count(replay: NumpyMmapReplaySource, name: str) -> int:
    # Execute the dictionary count workflow in explicit, reviewable steps.
    for descriptor in replay.manifest.layout.dictionaries:
        # Process replay.manifest.layout.dictionaries inside the bounded dictionary count
        # loop.
        if descriptor.name == name:
            return descriptor.count
    raise OptimizedSnipingBackendUnsupported(f"ReplayPack dictionary {name} is absent")


def _validity_values(
    bitmap: npt.NDArray[np.generic],
    # Keep the count input explicit in the validity values contract.
    count: int,
) -> npt.NDArray[np.bool_]:
    # Execute the validity values workflow in explicit, reviewable steps.
    unpacked = np.unpackbits(
        cast(npt.NDArray[np.uint8], bitmap),
        bitorder="little",
        count=count,
    )
    # Return the completed validity values result without a hidden fallback.
    return cast(npt.NDArray[np.bool_], unpacked.astype(np.bool_, copy=False))


def _historical_group_record(
    boundary: int,
    arrays: Mapping[str, npt.NDArray[np.generic]],
    start: int,
    # Keep the stop input explicit in the historical group record contract.
    stop: int,
) -> bytes:
    # Execute the historical group record workflow in explicit, reviewable steps.
    event_ids = arrays[physical.ENVELOPE_CANONICAL_EVENT_ID]
    group_ids = arrays[physical.ENVELOPE_TRANSACTION_GROUP_ID]
    record = bytearray(b'{"boundary_ordinal":')
    record.extend(str(boundary).encode("ascii"))
    record.extend(b',"event_ids":[')
    # Traverse range(start, stop) explicitly so each historical group record iteration
    # remains traceable.
    for row in range(start, stop):
        # Process range(start, stop) inside the bounded historical group record loop.
        if row != start:
            record.extend(b",")
        record.extend(b'"')
        record.extend(hexlify(event_ids[row].tobytes()))
        record.extend(b'"')
    # Invoke extend as a visible step within the historical group record workflow.
    record.extend(b'],"phase":10,"record_type":"HISTORICAL_GROUP_APPLIED",')
    record.extend(b'"transaction_group_id":"')
    record.extend(hexlify(group_ids[start].tobytes()))
    record.extend(b'"}')
    return bytes(record)


# Define checkpoint record as one focused operation with an explicit boundary.
def _checkpoint_record(boundary: int) -> bytes:
    # Execute the checkpoint record workflow in explicit, reviewable steps.
    return (
        b'{"boundary_ordinal":'
        + str(boundary).encode("ascii")
        + b',"phase":80,"record_type":"BOUNDARY_CHECKPOINT"}'
    )


# Bind all once as an explicit module-level contract.
__all__ = [
    "NUMPY_MMAP_PUMPFUN_SNIPING_BACKEND",
    "NumpyMmapPumpfunSnipingEngine",
    "OptimizedSnipingBackendUnsupported",
]
