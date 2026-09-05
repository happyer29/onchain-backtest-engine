"""Readable deterministic reference engine for generic launchpad sniping.

This module is the semantic oracle for a later array/mmap backend.  It consumes
only committed-reader values and core-owned plugin ports; no protocol formula,
source adapter, SQL client or network implementation is imported here.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum

# Import typing at the visible module dependency boundary.
from typing import Final

from backtest.domain.account_requirements import (
    AccountComponentRecord,
    AccountRequirementScope,
)
from backtest.domain.chain import ChainIdentityMismatchError, ChainPosition
from backtest.domain.execution import ExecutionMode, Fill
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import (
    # Include account id so the identifiers dependency remains explicit.
    AccountId,
    AssetId,
    BundleId,
    ContentDigest,
    LogicalContentHash,
    # Include order id so the identifiers dependency remains explicit.
    OrderId,
    PoolId,
)
from backtest.domain.intents import RoundTripIntent
from backtest.domain.ledger import (
    # Include account kind so the ledger dependency remains explicit.
    AccountKind,
    LedgerAccount,
    LedgerCorrelationKind,
    LedgerTransaction,
    Posting,
    # Close the ledger import after its required symbols are visible.
)
from backtest.domain.market_events import (
    CanonicalEvent,
    TokenLaunchEvent,
    canonical_event_sort_key,
    # Close the market events import after its required symbols are visible.
)
from backtest.domain.roundtrips import (
    MtmStatus,
    QuoteLiquidityEvidenceRecord,
    RoundTripLegRecord,
    RoundTripLegSide,
    # Include round trip record so the roundtrips dependency remains explicit.
    RoundTripRecord,
    RoundTripStatus,
)
from backtest.domain.time import BlockRange

# Import audit at the visible module dependency boundary.
from backtest.engine.audit import (
    CanonicalStreamHasher,
    fill_document,
    ledger_document,
)

# Import contracts at the visible module dependency boundary.
from backtest.engine.contracts import DEFAULT_ENGINE_PHYSICAL_SETTINGS, EnginePhysicalSettings
from backtest.engine.portfolio import (
    PortfolioInvariantError,
    PortfolioState,
    available_account_id,
    # Include reserved account id so the portfolio dependency remains explicit.
    reserved_account_id,
)
from backtest.engine.replay import (
    HistoricalEventSource,
    IndexedHistoricalEventSource,
    # Include observation delivery so the replay dependency remains explicit.
    ObservationDelivery,
    ObservationDeliverySource,
)
from backtest.engine.rng import KeyedRng
from backtest.engine.scheduler import SchedulerPhase

# Import sniping contracts at the visible module dependency boundary.
from backtest.engine.sniping_contracts import (
    LaunchDecisionStatus,
    LaunchTarget,
    NetworkCostQuote,
    ProtocolExecutionRejected,
    # Include protocol quote so the sniping contracts dependency remains explicit.
    ProtocolQuote,
    ProtocolQuoteSide,
    SnipingNetworkCostModel,
    SnipingProtocolRuntime,
    SnipingRunEventSink,
    # Include sniping strategy instance so the sniping contracts dependency remains
    # explicit.
    SnipingStrategyInstance,
    ensure_single_launch,
    liquidity_policy_id_for_execution_mode,
    synthetic_liquidity_account_id,
)
from backtest.engine.transaction_clock import CompactTransactionClock
from backtest.engine.wallet_accounts import (
    AccountProvisioningTransition,
    AccountReservationPlan,
    WalletProvisioningReducer,
    WalletUvaInitialState,
    initial_wallet_provisioning_state,
    refundable_mint_deposits,
    run_locked_value,
    unsubmitted_account_records,
)

# Bind sniping reference backend name once as an explicit module-level contract.
SNIPING_REFERENCE_BACKEND_NAME: Final = "reference-pumpfun-sniping-v1"
SNIPING_EXECUTION_MODES: Final = frozenset(
    {
        ExecutionMode.EXOGENOUS_REPLAY,
        ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT,
    }
)
SNIPING_REFERENCE_ENGINE_BUNDLE_ID: Final = BundleId(
    domain_digest(
        "backtest.reference-sniping-engine-bundle.v4",
        {
            # Keep accounting named so the v2 and accounting payload passed to
            # domain_digest remains self-describing within module.
            "accounting": "correlated-component-account-lifecycle-v3",
            "backend": SNIPING_REFERENCE_BACKEND_NAME,
            "execution_modes": sorted(mode.value for mode in SNIPING_EXECUTION_MODES),
            "scheduler": "historical-synthetic-two-way-merge-v1",
        },
        # Complete domain_digest only after its v2 and accounting inputs are visible in
        # module.
    ).hex
)


# Keep the sniping engine error code contract and validation rules together.
class SnipingEngineErrorCode(StrEnum):
    SOURCE_ORDER_INVALID = "SOURCE_ORDER_INVALID"
    SOURCE_COUNT_MISMATCH = "SOURCE_COUNT_MISMATCH"
    MIXED_TRANSACTION_GROUP = "MIXED_TRANSACTION_GROUP"
    MIXED_NETWORK = "MIXED_NETWORK"
    # Declare duplicate roundtrip explicitly in the sniping engine error code contract.
    DUPLICATE_ROUNDTRIP = "DUPLICATE_ROUNDTRIP"
    DYNAMIC_ITEM_LIMIT_EXCEEDED = "DYNAMIC_ITEM_LIMIT_EXCEEDED"
    PORTFOLIO_INVARIANT = "PORTFOLIO_INVARIANT"
    QUOTE_CONTRACT_MISMATCH = "QUOTE_CONTRACT_MISMATCH"
    DELIVERY_SCHEDULE_INVALID = "DELIVERY_SCHEDULE_INVALID"
    # Declare internal state invalid explicitly in the sniping engine error code contract.
    INTERNAL_STATE_INVALID = "INTERNAL_STATE_INVALID"


# Keep the sniping valuation status contract and validation rules together.
class SnipingValuationStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL_UNVALUED_OPEN_POSITIONS = "PARTIAL_UNVALUED_OPEN_POSITIONS"


# Keep the sniping engine error contract and validation rules together.
class SnipingEngineError(RuntimeError):
    def __init__(self, code: SnipingEngineErrorCode) -> None:
        # Execute the sniping engine error init workflow in explicit, reviewable steps.
        if not isinstance(code, SnipingEngineErrorCode):
            raise TypeError("code must be a SnipingEngineErrorCode")
        self.code = code
        super().__init__(code.value)


# Keep the sniping run config contract and validation rules together.
@dataclass(frozen=True, slots=True)
class SnipingRunConfig:
    quote_asset_id: AssetId
    decision_range: BlockRange
    initial_available: Mapping[AssetId, int]
    # Declare wallet account profile explicitly in the sniping run config contract.
    initial_uva_state: WalletUvaInitialState
    wallet_account_profile_id: str
    uva_schema_id: str
    root_seed: int
    maximum_dynamic_items: int = 1_000_000
    # Declare execution mode explicitly in the sniping run config contract.
    execution_mode: ExecutionMode = ExecutionMode.EXOGENOUS_REPLAY
    engine_bundle_id: BundleId = SNIPING_REFERENCE_ENGINE_BUNDLE_ID

    def __post_init__(self) -> None:
        # Execute the sniping run config post init workflow in explicit, reviewable steps.
        KeyedRng(self.root_seed)
        if not isinstance(self.initial_uva_state, WalletUvaInitialState):
            raise TypeError("initial UVA state must be resolved")
        for field_name in ("wallet_account_profile_id", "uva_schema_id"):
            # Process wallet account profile id and token account schema id inside the
            # bounded sniping run config post init loop.
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
                raise ValueError(f"{field_name} must be non-empty, trimmed and NUL-free")
        # StrEnum compares equal to its raw value, so type-check before membership.
        if not isinstance(self.execution_mode, ExecutionMode):
            raise TypeError("execution_mode must be an ExecutionMode")
        if self.execution_mode not in SNIPING_EXECUTION_MODES:
            raise ValueError("sniping requires an allowlisted exogenous execution mode")
        # Evaluate the complete sniping run config post init isinstance and maximum
        # dynamic items condition before guarded effects.
        if (
            isinstance(self.maximum_dynamic_items, bool)
            or not isinstance(self.maximum_dynamic_items, int)
            or self.maximum_dynamic_items <= 0
        ):
            # Fail the sniping run config post init path with ValueError for maximum
            # dynamic items must be positive when isinstance and maximum dynamic items is
            # true; do not continue ambiguously.
            raise ValueError("maximum dynamic items must be positive")
        if self.quote_asset_id not in self.initial_available:
            raise ValueError("initial portfolio must contain the quote asset")


# Keep the sniping run summary contract and validation rules together.
@dataclass(frozen=True, slots=True)
class SnipingRunSummary:
    dataset_logical_content_hash: LogicalContentHash
    replay_semantics_id: ContentDigest
    engine_bundle_id: BundleId
    # Declare strategy bundle id explicitly in the sniping run summary contract.
    strategy_bundle_id: BundleId
    protocol_bundle_id: BundleId
    network_cost_bundle_id: BundleId
    historical_group_count: int
    historical_event_count: int
    # Declare delivered event count explicitly in the sniping run summary contract.
    delivered_event_count: int
    target_count: int
    cooldown_skipped_count: int
    accepted_buy_count: int
    accepted_sell_count: int
    # Declare rejected buy count explicitly in the sniping run summary contract.
    rejected_buy_count: int
    rejected_sell_count: int
    accepted_order_count: int
    rejected_order_count: int
    filled_order_count: int
    # Declare failed order count explicitly in the sniping run summary contract.
    failed_order_count: int
    closed_roundtrip_count: int
    open_position_count: int
    failed_buy_count: int
    failed_sell_count: int
    # Declare realized cash pnl atomic explicitly in the sniping run summary contract.
    realized_cash_pnl_atomic: int
    valuation_status: SnipingValuationStatus
    unvalued_open_position_count: int
    valued_economic_pnl_subtotal_atomic: int
    economic_pnl_atomic: int | None
    # Declare cashback receivable atomic explicitly in the sniping run summary contract.
    cashback_receivable_atomic: int
    protocol_fee_paid_atomic: int
    creator_fee_paid_atomic: int
    network_base_fee_paid_atomic: int
    network_priority_fee_paid_atomic: int
    # Declare account deposit paid atomic explicitly in the sniping run summary contract.
    account_deposit_paid_atomic: int
    account_deposit_refunded_atomic: int
    account_deposit_locked_atomic: int
    favorable_slippage_count: int
    adverse_slippage_count: int
    # Declare buy slippage failure count explicitly in the sniping run summary contract.
    buy_slippage_failure_count: int
    sell_slippage_failure_count: int
    ledger_transaction_count: int
    fill_count: int
    roundtrip_count: int
    # Declare audit hash explicitly in the sniping run summary contract.
    audit_hash: ContentDigest
    ledger_hash: ContentDigest
    fill_hash: ContentDigest
    roundtrip_digest: ContentDigest
    final_balances_digest: ContentDigest
    # Declare result hash explicitly in the sniping run summary contract.
    result_hash: ContentDigest
    final_balances: tuple[tuple[str, str, str, int], ...]
    # V3 summary fields keep synthetic settlement explicit and bounded.
    execution_mode: ExecutionMode = ExecutionMode.EXOGENOUS_REPLAY
    settlement_policy_id: str = "real-reserve-capped-v1"
    filled_sell_count: int = 0
    real_liquidity_sufficient_filled_sell_count: int = 0
    synthetic_liquidity_used_sell_count: int = 0
    gross_sell_settlement_atomic: int = 0
    venue_funded_sell_atomic: int = 0
    synthetic_funded_sell_atomic: int = 0


# Keep the round trip aggregate accumulator contract and validation rules together.
@dataclass(slots=True)
class _RoundTripAggregateAccumulator:
    closed_count: int = 0
    open_count: int = 0
    accepted_sell_count: int = 0
    # Declare rejected buy count explicitly in the round trip aggregate accumulator
    # contract.
    rejected_buy_count: int = 0
    rejected_sell_count: int = 0
    realized_cash_pnl_atomic: int = 0
    valued_economic_pnl_subtotal_atomic: int = 0
    unvalued_open_position_count: int = 0
    # Declare cashback receivable atomic explicitly in the round trip aggregate
    # accumulator contract.
    cashback_receivable_atomic: int = 0
    protocol_fee_paid_atomic: int = 0
    creator_fee_paid_atomic: int = 0
    network_base_fee_paid_atomic: int = 0
    network_priority_fee_paid_atomic: int = 0
    # Declare account deposit paid atomic explicitly in the round trip aggregate
    # accumulator contract.
    account_deposit_paid_atomic: int = 0
    account_deposit_refunded_atomic: int = 0
    account_deposit_locked_atomic: int = 0
    favorable_slippage_count: int = 0
    adverse_slippage_count: int = 0
    # Declare buy slippage failure count explicitly in the round trip aggregate
    # accumulator contract.
    buy_slippage_failure_count: int = 0
    sell_slippage_failure_count: int = 0
    filled_sell_count: int = 0
    real_liquidity_sufficient_filled_sell_count: int = 0
    synthetic_liquidity_used_sell_count: int = 0
    gross_sell_settlement_atomic: int = 0
    venue_funded_sell_atomic: int = 0
    synthetic_funded_sell_atomic: int = 0

    def append(self, record: RoundTripRecord) -> None:
        # Execute the round trip aggregate accumulator append workflow in explicit,
        # reviewable steps.
        is_closed = record.status is RoundTripStatus.CLOSED
        is_open = record.acquired_token_amount_atomic > 0 and not is_closed
        self.closed_count += is_closed
        self.open_count += is_open
        self.accepted_sell_count += (
            # Keep the record component named inside the self accepted sell count
            # contract.
            record.sell is not None and record.sell.landing_position is not None
        )
        self.rejected_buy_count += record.status in {
            RoundTripStatus.BUY_REFERENCE_REJECTED,
            RoundTripStatus.BUY_PRE_SUBMIT_INSUFFICIENT_FUNDS,
            # Complete the self rejected buy count group only after its semantic components
            # are visible.
        }
        self.rejected_sell_count += record.status in {
            RoundTripStatus.SELL_REFERENCE_UNAVAILABLE_OPEN,
            RoundTripStatus.SELL_PRE_SUBMIT_INSUFFICIENT_FUNDS_OPEN,
        }
        # Evaluate the complete round trip aggregate accumulator append realized cash pnl
        # atomic and record condition before guarded effects.
        if record.realized_cash_pnl_atomic is not None:
            self.realized_cash_pnl_atomic += record.realized_cash_pnl_atomic
        if record.economic_pnl_atomic is None:
            self.unvalued_open_position_count += is_open
        else:
            # Assemble valued economic pnl subtotal atomic once so the round trip
            # aggregate accumulator append workflow shares one value.
            self.valued_economic_pnl_subtotal_atomic += record.economic_pnl_atomic
        self.cashback_receivable_atomic += record.cashback_receivable_atomic
        for leg in (record.buy, record.sell):
            # Process (record.buy, record.sell) inside the bounded round trip aggregate
            # accumulator append loop.
            if leg is None:
                continue
            self.protocol_fee_paid_atomic += leg.protocol_fee_atomic
            self.creator_fee_paid_atomic += leg.creator_fee_atomic
            self.network_base_fee_paid_atomic += leg.network_base_fee_atomic
            # Assemble self network priority fee paid atomic once so the round trip
            # aggregate accumulator append workflow shares one value.
            self.network_priority_fee_paid_atomic += leg.network_priority_fee_atomic
            if leg.signed_slippage_atomic is not None:
                # Handle the round trip aggregate accumulator append
                # leg.signed_slippage_atomic is not None branch as a distinct logical
                # block.
                self.favorable_slippage_count += leg.signed_slippage_atomic > 0
                self.adverse_slippage_count += leg.signed_slippage_atomic < 0
        if record.buy is not None and record.buy.failure_code == "MINIMUM_OUTPUT_NOT_MET":
            self.buy_slippage_failure_count += 1
        if record.sell is not None and record.sell.failure_code == "MINIMUM_OUTPUT_NOT_MET":
            # Assemble self sell slippage failure count once so the round trip aggregate
            # accumulator append workflow shares one value.
            self.sell_slippage_failure_count += 1
        if is_closed:
            self.filled_sell_count += 1
            self.gross_sell_settlement_atomic += (
                record.settled_venue_funded_atomic + record.settled_synthetic_funded_atomic
            )
            self.venue_funded_sell_atomic += record.settled_venue_funded_atomic
            self.synthetic_funded_sell_atomic += record.settled_synthetic_funded_atomic
            if record.settled_synthetic_funded_atomic:
                self.synthetic_liquidity_used_sell_count += 1
            else:
                self.real_liquidity_sufficient_filled_sell_count += 1
        for component in record.account_components:
            # V3 components attribute one-time UVA and per-mint ATA cashflows exactly once.
            self.account_deposit_paid_atomic += component.paid_atomic
            self.account_deposit_refunded_atomic += component.refunded_atomic
            self.account_deposit_locked_atomic += component.locked_delta_atomic

    @property
    def valuation_status(self) -> SnipingValuationStatus:
        # Execute the round trip aggregate accumulator valuation status workflow in
        # explicit, reviewable steps.
        if self.unvalued_open_position_count:
            return SnipingValuationStatus.PARTIAL_UNVALUED_OPEN_POSITIONS
        return SnipingValuationStatus.COMPLETE

    @property
    def economic_pnl_atomic(self) -> int | None:
        # Execute the round trip aggregate accumulator economic pnl atomic workflow in
        # explicit, reviewable steps.
        if self.unvalued_open_position_count:
            return None
        return self.valued_economic_pnl_subtotal_atomic


def _roundtrip_aggregates(records: Iterable[RoundTripRecord]) -> _RoundTripAggregateAccumulator:
    # Execute the roundtrip aggregates workflow in explicit, reviewable steps.
    result = _RoundTripAggregateAccumulator()
    for record in records:
        result.append(record)
    return result


# Keep the null sniping run event sink contract and validation rules together.
class NullSnipingRunEventSink:
    def append_audit(self, record: dict[str, object]) -> None:
        del record

    def append_ledger(self, transaction: LedgerTransaction) -> None:
        del transaction

    # Define null sniping run event sink append fill as one focused operation with an
    # explicit boundary.
    def append_fill(self, fill: Fill) -> None:
        del fill

    def append_roundtrip(self, record: RoundTripRecord) -> None:
        del record


# Keep the action kind contract and validation rules together.
class _ActionKind(IntEnum):
    SELL_DECISION = 40
    BUY_LANDING = 60
    SELL_LANDING = 60


@dataclass(frozen=True, slots=True)
# Keep the buy landing contract and validation rules together.
class _BuyLanding:
    roundtrip_id: ContentDigest


@dataclass(frozen=True, slots=True)
class _SellDecision:
    roundtrip_id: ContentDigest


# Apply dataclass semantics to the following sell landing contract.
@dataclass(frozen=True, slots=True)
class _SellLanding:
    roundtrip_id: ContentDigest


_ActionPayload = _BuyLanding | _SellDecision | _SellLanding


# Keep the scheduled action contract and validation rules together.
@dataclass(order=True, slots=True)
class _ScheduledAction:
    release_boundary_ordinal: int
    phase: int
    creator_boundary_ordinal: int
    # Declare stable causal id hex explicitly in the scheduled action contract.
    stable_causal_id_hex: str
    payload: _ActionPayload = field(compare=False)


# Keep the round trip state contract and validation rules together.
@dataclass(slots=True)
class _RoundTripState:
    target: LaunchTarget
    target_time_ns: int
    cooldown_consumed: bool
    # Declare cooldown until ns explicitly in the round trip state contract.
    cooldown_until_ns: int | None
    intent: RoundTripIntent | None
    status: RoundTripStatus
    buy_reference: ProtocolQuote | None = None
    buy_landing: ProtocolQuote | None = None
    # Declare buy landing position explicitly in the round trip state contract.
    buy_landing_position: ChainPosition | None = None
    buy_minimum_out_atomic: int = 0
    buy_failure_code: str | None = None
    buy_network_cost: NetworkCostQuote | None = None
    account_reservation: AccountReservationPlan | None = None
    account_components: tuple[AccountComponentRecord, ...] = ()
    sell_reference: ProtocolQuote | None = None
    # Declare sell decision position explicitly in the round trip state contract.
    sell_decision_position: ChainPosition | None = None
    sell_landing: ProtocolQuote | None = None
    sell_landing_position: ChainPosition | None = None
    sell_minimum_out_atomic: int = 0
    sell_failure_code: str | None = None
    # Declare sell network cost explicitly in the round trip state contract.
    sell_network_cost: NetworkCostQuote | None = None
    acquired_token_amount_atomic: int = 0
    # Declare cashback receivable atomic explicitly in the round trip state contract.
    cashback_receivable_atomic: int = 0
    terminal: bool = False


class _CorrelatedLedgerCashflows:
    """Bounded materialized view derived only from committed ledger rows."""

    def __init__(self) -> None:
        self._amounts: dict[tuple[ContentDigest, AssetId], int] = {}

    def append(self, transaction: LedgerTransaction) -> None:
        # Execute the correlated ledger cashflows append workflow in explicit, reviewable
        # steps.
        if transaction.correlation_kind is not LedgerCorrelationKind.ROUNDTRIP:
            raise SnipingEngineError(SnipingEngineErrorCode.INTERNAL_STATE_INVALID)
        for posting in transaction.postings:
            # Process transaction.postings inside the bounded correlated ledger cashflows
            # append loop.
            if posting.account.kind not in (
                AccountKind.PORTFOLIO_AVAILABLE,
                AccountKind.PORTFOLIO_RESERVED,
            ):
                continue
            # Assemble key once so the correlated ledger cashflows append workflow shares
            # one value.
            key = (transaction.correlation_id, posting.asset_id)
            self._amounts[key] = self._amounts.get(key, 0) + posting.amount_atomic

    def amount(self, roundtrip_id: ContentDigest, asset_id: AssetId) -> int:
        return self._amounts.get((roundtrip_id, asset_id), 0)


# Keep the recorder contract and validation rules together.
class _Recorder:
    def __init__(self, sink: SnipingRunEventSink) -> None:
        # Execute the recorder init workflow in explicit, reviewable steps.
        self.sink = sink
        self.audit = CanonicalStreamHasher("backtest.sniping-audit-stream.v1")
        self.ledger = CanonicalStreamHasher("backtest.sniping-ledger-stream.v2")
        self.fills = CanonicalStreamHasher("backtest.sniping-fill-stream.v1")
        self.roundtrips = CanonicalStreamHasher("backtest.sniping-roundtrip-stream.v4")
        # Assemble self cashflows once so the recorder init workflow shares one value.
        self.cashflows = _CorrelatedLedgerCashflows()

    def append_audit(self, record: dict[str, object]) -> None:
        # Execute the recorder append audit workflow in explicit, reviewable steps.
        self.audit.append(record)
        self.sink.append_audit(record)

    def append_ledger(self, transaction: LedgerTransaction) -> None:
        # Execute the recorder append ledger workflow in explicit, reviewable steps.
        self.ledger.append(ledger_document(transaction))
        self.cashflows.append(transaction)
        self.sink.append_ledger(transaction)

    def append_fill(self, fill: Fill) -> None:
        # Execute the recorder append fill workflow in explicit, reviewable steps.
        self.fills.append(fill_document(fill))
        self.sink.append_fill(fill)

    def append_roundtrip(self, record: RoundTripRecord) -> None:
        # Execute the recorder append roundtrip workflow in explicit, reviewable steps.
        self.roundtrips.append(record.document())
        self.sink.append_roundtrip(record)


class _MaterializedSnipingObservationMerge:
    """Merge a preflighted zero-delay observation stream at group boundaries."""

    def __init__(self, source: ObservationDeliverySource) -> None:
        # Execute the materialized sniping observation merge init workflow in explicit,
        # reviewable steps.
        self._source = source
        self._iterator = source.deliveries()
        self._next: ObservationDelivery | None = None
        self._consumed = 0
        self._advance()

    # Define materialized sniping observation merge consume group as one focused operation
    # with an explicit boundary.
    def consume_group(
        self,
        *,
        boundary: int,
        events: tuple[CanonicalEvent, ...],
        # Keep the first event row input explicit in the consume group contract.
        first_event_row: int,
    ) -> int:
        # Execute the materialized sniping observation merge consume group workflow in
        # explicit, reviewable steps.
        expected_rows = sorted(
            range(first_event_row, first_event_row + len(events)),
            key=lambda row: events[row - first_event_row].envelope.stable_causal_id.hex,
        )
        for event_row in expected_rows:
            # Process expected_rows inside the bounded materialized sniping observation
            # merge consume group loop.
            delivery = self._next
            if delivery is None:
                raise SnipingEngineError(SnipingEngineErrorCode.DELIVERY_SCHEDULE_INVALID)
            if (
                delivery.release_boundary_ordinal != boundary
                # Keep delivery visible while evaluating the release boundary ordinal,
                # boundary and event row index guard.
                or delivery.event_row_index != event_row
            ):
                raise SnipingEngineError(SnipingEngineErrorCode.DELIVERY_SCHEDULE_INVALID)
            self._consumed += 1
            self._advance()
        # Evaluate the complete materialized sniping observation merge consume group next,
        # release boundary ordinal and boundary condition before guarded effects.
        if self._next is not None and self._next.release_boundary_ordinal == boundary:
            raise SnipingEngineError(SnipingEngineErrorCode.DELIVERY_SCHEDULE_INVALID)
        return len(expected_rows)

    def finish(self) -> None:
        # Execute the materialized sniping observation merge finish workflow in explicit,
        # reviewable steps.
        if self._next is not None or self._consumed != self._source.delivery_count:
            raise SnipingEngineError(SnipingEngineErrorCode.DELIVERY_SCHEDULE_INVALID)

    def _advance(self) -> None:
        # Execute the materialized sniping observation merge advance workflow in explicit,
        # reviewable steps.
        try:
            self._next = next(self._iterator)
        except StopIteration:
            self._next = None


class SnipingReferenceEngine:
    """Single-process reference reducer with event/synthetic boundary merge."""

    backend_name = SNIPING_REFERENCE_BACKEND_NAME

    def run(
        self,
        *,
        source: HistoricalEventSource,
        # Keep the clock input explicit in the run contract.
        clock: CompactTransactionClock,
        strategy: SnipingStrategyInstance,
        protocol: SnipingProtocolRuntime,
        network_costs: SnipingNetworkCostModel,
        config: SnipingRunConfig,
        # Keep the sink input explicit in the run contract.
        sink: SnipingRunEventSink | None = None,
        delivery_schedule: ObservationDeliverySource | None = None,
        physical_settings: EnginePhysicalSettings = DEFAULT_ENGINE_PHYSICAL_SETTINGS,
    ) -> SnipingRunSummary:
        # Execute the sniping reference engine run workflow in explicit, reviewable steps.
        if physical_settings.threads != 1:
            raise ValueError("one sniping run requires exactly one sequential engine thread")
        _validate_chain_contract(clock, config)
        expected_event_count, expected_group_count = _preflight_source_clock_coverage(
            source=source,
            # Pass clock explicitly so _preflight_source_clock_coverage receives a
            # reviewable decision range and source input in sniping reference engine run.
            clock=clock,
            strategy=strategy,
            decision_range=config.decision_range,
        )
        _preflight_sniping_delivery_schedule(
            # Pass source explicitly so _preflight_sniping_delivery_schedule receives a
            # reviewable source and delivery schedule input in sniping reference engine
            # run.
            source=source,
            schedule=delivery_schedule,
            expected_event_count=expected_event_count,
        )
        materialized_observations = (
            # Complete the materialized observations group only after its semantic
            # components are visible.
            None
            if delivery_schedule is None
            else _MaterializedSnipingObservationMerge(delivery_schedule)
        )
        event_sink = NullSnipingRunEventSink() if sink is None else sink
        # Assemble recorder once so the sniping reference engine run workflow shares one
        # value.
        recorder = _Recorder(event_sink)
        portfolio = PortfolioState(config.initial_available)
        accounts = WalletProvisioningReducer(
            initial_wallet_provisioning_state(
                config.initial_uva_state,
                uva_schema_id=config.uva_schema_id,
            )
        )
        states: dict[ContentDigest, _RoundTripState] = {}
        state_order: list[ContentDigest] = []
        scheduled: list[_ScheduledAction] = []
        # Assemble event count once so the sniping reference engine run workflow shares
        # one value.
        event_count = 0
        delivered_event_count = 0
        group_count = 0
        target_count = 0
        cooldown_skipped_count = 0
        # Assemble accepted buy count once so the sniping reference engine run workflow
        # shares one value.
        accepted_buy_count = 0
        failed_buy_count = 0
        failed_sell_count = 0

        groups = iter(_event_groups(source.events(), clock=clock))
        next_group = next(groups, None)
        # Repeat the sniping reference engine run step only while next_group is not None
        # or scheduled remains true.
        while next_group is not None or scheduled:
            # Keep the next_group is not None or scheduled loop body bounded within
            # sniping reference engine run.
            group_boundary = None if next_group is None else next_group[0].envelope.boundary_ordinal
            scheduled_boundary = None if not scheduled else scheduled[0].release_boundary_ordinal
            boundary = _next_boundary(group_boundary, scheduled_boundary)
            boundary_position: ChainPosition | None = None
            launches: tuple[LaunchTarget, ...] = ()
            # Guard this path with group_boundary == boundary before applying effects.
            if group_boundary == boundary:
                if next_group is None:  # pragma: no cover - narrowed above
                    raise SnipingEngineError(SnipingEngineErrorCode.INTERNAL_STATE_INVALID)
                current_group = next_group
                boundary_position = _boundary_position(current_group)
                launches = ensure_single_launch(
                    protocol.apply_historical_group(
                        # Pass current group explicitly so apply_historical_group receives
                        # a reviewable block time for block and block ordinal input in
                        # sniping reference engine run.
                        current_group,
                        effective_at_unix_s=(
                            clock.block_time_for_block(boundary_position.block_ordinal)
                            // 1_000_000_000
                        ),
                        # Complete apply_historical_group only after its block time for block
                        # and block ordinal inputs are visible in sniping reference engine
                        # run.
                    )
                )
                first_event_row = event_count
                event_count += len(current_group)
                group_count += 1
                # Invoke append_audit for historical group applied and boundary ordinal as
                # a visible sniping reference engine run step.
                recorder.append_audit(
                    {
                        "boundary_ordinal": boundary,
                        "event_ids": [
                            event.envelope.canonical_event_id.hex
                            # Pass event explicitly so append_audit receives a reviewable
                            # historical group applied and boundary ordinal input in
                            # sniping reference engine run.
                            for event in current_group
                            # Close the historical group applied and boundary ordinal payload
                            # only after all sniping reference engine run fields are present.
                        ],
                        "phase": int(SchedulerPhase.HISTORICAL_REFERENCE_APPLY),
                        "record_type": "HISTORICAL_GROUP_APPLIED",
                        "transaction_group_id": current_group[0].envelope.transaction_group_id.hex,
                    }
                    # Complete append_audit only after its historical group applied and
                    # boundary ordinal inputs are visible in sniping reference engine run.
                )
                next_group = next(groups, None)
                if materialized_observations is None:
                    delivered_event_count += len(current_group)
                else:
                    # Handle the sniping reference engine run complement of
                    # materialized_observations is None explicitly.
                    delivered_event_count += materialized_observations.consume_group(
                        boundary=boundary,
                        events=current_group,
                        first_event_row=first_event_row,
                    )
            # Guard this path with boundary_position is None before applying effects.
            if boundary_position is None:
                # Handle the sniping reference engine run boundary_position is None branch
                # as a distinct logical block.
                boundary_position = ChainPosition.from_boundary_ordinal(
                    network_id=clock.network_id,
                    position_schema_id=clock.position_schema_id,
                    boundary_ordinal_value=boundary,
                )

            # Assemble decision actions once so the sniping reference engine run workflow
            # shares one value.
            decision_actions = _pop_actions(
                scheduled, boundary, maximum_phase=int(_ActionKind.SELL_DECISION)
            )
            for action in decision_actions:
                # Process decision_actions inside the bounded sniping reference engine run
                # loop.
                if not isinstance(action.payload, _SellDecision):
                    raise SnipingEngineError(SnipingEngineErrorCode.INTERNAL_STATE_INVALID)
                state = _require_state(states, action.payload.roundtrip_id)
                self._decide_sell(
                    state=state,
                    # Pass position explicitly so _decide_sell receives a reviewable state
                    # and boundary position input in sniping reference engine run.
                    position=boundary_position,
                    clock=clock,
                    protocol=protocol,
                    network_costs=network_costs,
                    portfolio=portfolio,
                    # Pass recorder explicitly so _decide_sell receives a reviewable state
                    # and boundary position input in sniping reference engine run.
                    recorder=recorder,
                    scheduled=scheduled,
                )

            for target in launches:
                # Process launches inside the bounded sniping reference engine run loop.
                if not config.decision_range.contains_position(target.position):
                    # Handle the sniping reference engine run contains position, position
                    # and decision range condition as a distinct block.
                    recorder.append_audit(
                        {
                            "boundary_ordinal": boundary,
                            "phase": int(SchedulerPhase.STRATEGY_CALLBACK),
                            "record_type": "TARGET_OUTSIDE_DECISION_RANGE",
                            # Keep target event id named so the target outside decision
                            # range and boundary ordinal payload passed to append_audit
                            # remains self-describing within sniping reference engine run.
                            "target_event_id": target.target_event_id.hex,
                        }
                    )
                    continue
                if len(states) >= config.maximum_dynamic_items:
                    # Fail the sniping reference engine run path with SnipingEngineError
                    # for dynamic item limit exceeded and sniping engine error code when
                    # maximum dynamic items, states and config is true; do not continue
                    # ambiguously.
                    raise SnipingEngineError(SnipingEngineErrorCode.DYNAMIC_ITEM_LIMIT_EXCEEDED)
                target_count += 1
                target_time_ns = clock.block_time_for_position(target.position)
                decision = strategy.decide(
                    target,
                    # Pass decision time ns explicitly so decide receives a reviewable
                    # target and target time ns input in sniping reference engine run.
                    decision_time_ns=target_time_ns,
                )
                if decision.roundtrip_id in states:
                    raise SnipingEngineError(SnipingEngineErrorCode.DUPLICATE_ROUNDTRIP)
                if decision.status is LaunchDecisionStatus.COOLDOWN_SUPPRESSED:
                    # Handle the sniping reference engine run status, cooldown suppressed
                    # and decision condition as a distinct block.
                    cooldown_skipped_count += 1
                    state = _RoundTripState(
                        target=target,
                        target_time_ns=target_time_ns,
                        cooldown_consumed=False,
                        # Pass cooldown until ns explicitly so _RoundTripState receives a
                        # reviewable cooldown until ns and cooldown skipped input in
                        # sniping reference engine run.
                        cooldown_until_ns=decision.cooldown_until_ns,
                        intent=None,
                        status=RoundTripStatus.COOLDOWN_SKIPPED,
                        terminal=True,
                    )
                    # Assemble states[decision roundtrip id] once so the sniping reference
                    # engine run workflow shares one value.
                    states[decision.roundtrip_id] = state
                    state_order.append(decision.roundtrip_id)
                    recorder.append_audit(
                        {
                            "boundary_ordinal": boundary,
                            # Keep developer id named so the target cooldown skipped and
                            # boundary ordinal payload passed to append_audit remains
                            # self-describing within sniping reference engine run.
                            "developer_id": target.developer_id.value,
                            "phase": int(SchedulerPhase.STRATEGY_CALLBACK),
                            "record_type": "TARGET_COOLDOWN_SKIPPED",
                            "roundtrip_id": decision.roundtrip_id.hex,
                        }
                        # Complete append_audit only after its target cooldown skipped and
                        # boundary ordinal inputs are visible in sniping reference engine run.
                    )
                    continue
                intent = decision.intent
                if intent is None:  # pragma: no cover - decision invariant
                    raise SnipingEngineError(SnipingEngineErrorCode.INTERNAL_STATE_INVALID)
                if intent.execution_mode is not config.execution_mode:
                    raise SnipingEngineError(SnipingEngineErrorCode.INTERNAL_STATE_INVALID)
                state = _RoundTripState(
                    target=target,
                    target_time_ns=target_time_ns,
                    cooldown_consumed=True,
                    # Pass cooldown until ns explicitly so _RoundTripState receives a
                    # reviewable cooldown until ns and buy reference rejected input in
                    # sniping reference engine run.
                    cooldown_until_ns=decision.cooldown_until_ns,
                    intent=intent,
                    status=RoundTripStatus.BUY_REFERENCE_REJECTED,
                )
                states[decision.roundtrip_id] = state
                # Invoke append for roundtrip id and decision as a visible sniping
                # reference engine run step.
                state_order.append(decision.roundtrip_id)
                accepted = self._accept_buy(
                    state=state,
                    clock=clock,
                    protocol=protocol,
                    # Pass network costs explicitly so _accept_buy receives a reviewable
                    # state and clock input in sniping reference engine run.
                    network_costs=network_costs,
                    portfolio=portfolio,
                    accounts=accounts,
                    recorder=recorder,
                    scheduled=scheduled,
                    # Complete _accept_buy only after its state and clock inputs are visible
                    # in sniping reference engine run.
                )
                if accepted:
                    accepted_buy_count += 1

            landing_actions = _pop_actions(
                scheduled,
                # Pass boundary explicitly so _pop_actions receives a reviewable sell
                # landing and int input in sniping reference engine run.
                boundary,
                maximum_phase=int(_ActionKind.SELL_LANDING),
            )
            for action in landing_actions:
                # Process landing_actions inside the bounded sniping reference engine run
                # loop.
                state = _require_state(states, action.payload.roundtrip_id)
                if isinstance(action.payload, _BuyLanding):
                    # Handle the sniping reference engine run action payload buy landing
                    # type condition as a distinct block.
                    if self._land_buy(
                        state=state,
                        position=boundary_position,
                        clock=clock,
                        protocol=protocol,
                        # Pass network costs explicitly so _land_buy receives a reviewable
                        # state and boundary position input in sniping reference engine
                        # run.
                        network_costs=network_costs,
                        portfolio=portfolio,
                        accounts=accounts,
                        recorder=recorder,
                        scheduled=scheduled,
                    ):
                        # Keep this explicitly supported no-op branch visible.
                        pass
                    else:
                        failed_buy_count += 1
                # Handle the sniping reference engine run complement of action payload buy
                # landing type explicitly.
                elif isinstance(action.payload, _SellLanding):
                    # Handle the sniping reference engine run action payload sell landing
                    # type condition as a distinct block.
                    if not self._land_sell(
                        state=state,
                        position=boundary_position,
                        clock=clock,
                        protocol=protocol,
                        # Pass portfolio explicitly so _land_sell receives a reviewable
                        # state and boundary position input in sniping reference engine
                        # run.
                        portfolio=portfolio,
                        accounts=accounts,
                        network_costs=network_costs,
                        recorder=recorder,
                    ):
                        failed_sell_count += 1
                # Route all remaining cases through the explicit alternative branch.
                else:
                    raise SnipingEngineError(SnipingEngineErrorCode.INTERNAL_STATE_INVALID)

            if len(scheduled) > config.maximum_dynamic_items:
                raise SnipingEngineError(SnipingEngineErrorCode.DYNAMIC_ITEM_LIMIT_EXCEEDED)
            recorder.append_audit(
                # Open the boundary checkpoint and boundary ordinal payload explicitly for
                # append_audit within sniping reference engine run.
                {
                    "boundary_ordinal": boundary,
                    "phase": int(SchedulerPhase.CHECKPOINT),
                    "record_type": "BOUNDARY_CHECKPOINT",
                }
                # Complete append_audit only after its boundary checkpoint and boundary
                # ordinal inputs are visible in sniping reference engine run.
            )

        if event_count != expected_event_count or group_count != expected_group_count:
            raise SnipingEngineError(SnipingEngineErrorCode.SOURCE_COUNT_MISMATCH)
        if isinstance(source, IndexedHistoricalEventSource) and event_count != source.event_count:
            raise SnipingEngineError(SnipingEngineErrorCode.SOURCE_COUNT_MISMATCH)
        # Guard this path with materialized_observations is not None before applying
        # effects.
        if materialized_observations is not None:
            materialized_observations.finish()
        if delivered_event_count != event_count:
            raise SnipingEngineError(SnipingEngineErrorCode.DELIVERY_SCHEDULE_INVALID)

        final_time_unix_s = clock.block_time_ns[-1] // 1_000_000_000
        # Assemble records once so the sniping reference engine run workflow shares one
        # value.
        records: list[RoundTripRecord] = []
        for roundtrip_id in state_order:
            # Process state_order inside the bounded sniping reference engine run loop.
            state = states[roundtrip_id]
            record = self._finalize_roundtrip(
                roundtrip_id=roundtrip_id,
                state=state,
                committed_quote_cashflow_atomic=recorder.cashflows.amount(
                    # Pass roundtrip id explicitly so amount receives a reviewable quote
                    # asset id and target input in sniping reference engine run.
                    roundtrip_id,
                    state.target.quote_asset_id,
                ),
                protocol=protocol,
                network_costs=network_costs,
                # Pass config explicitly so _finalize_roundtrip receives a reviewable
                # amount and quote asset id input in sniping reference engine run.
                config=config,
                final_time_unix_s=final_time_unix_s,
            )
            records.append(record)
            recorder.append_roundtrip(record)

        # Assemble final balances once so the sniping reference engine run workflow shares
        # one value.
        final_balances = portfolio.semantic_balances()
        balances = CanonicalStreamHasher("backtest.sniping-final-balances.v1")
        for row in final_balances:
            balances.append(list(row))
        aggregates = _roundtrip_aggregates(records)
        # Assemble accepted order count once so the sniping reference engine run workflow
        # shares one value.
        accepted_order_count = accepted_buy_count + aggregates.accepted_sell_count
        rejected_order_count = aggregates.rejected_buy_count + aggregates.rejected_sell_count
        failed_order_count = failed_buy_count + failed_sell_count
        result_document = {
            "accepted_order_count": accepted_order_count,
            # Keep the account deposit locked atomic component named inside the result
            # document contract.
            "account_deposit_locked_atomic": aggregates.account_deposit_locked_atomic,
            "account_deposit_paid_atomic": aggregates.account_deposit_paid_atomic,
            "account_deposit_refunded_atomic": aggregates.account_deposit_refunded_atomic,
            "adverse_slippage_count": aggregates.adverse_slippage_count,
            "buy_slippage_failure_count": aggregates.buy_slippage_failure_count,
            # Keep the cashback receivable atomic component named inside the result
            # document contract.
            "cashback_receivable_atomic": aggregates.cashback_receivable_atomic,
            "closed_roundtrip_count": aggregates.closed_count,
            "creator_fee_paid_atomic": aggregates.creator_fee_paid_atomic,
            "economic_pnl_atomic": aggregates.economic_pnl_atomic,
            "execution_mode": config.execution_mode.value,
            "failed_buy_count": failed_buy_count,
            # Keep the failed sell count component named inside the result document
            # contract.
            "failed_sell_count": failed_sell_count,
            "favorable_slippage_count": aggregates.favorable_slippage_count,
            "fill_count": recorder.fills.count,
            "fill_hash": recorder.fills.digest.hex,
            "filled_sell_count": aggregates.filled_sell_count,
            "final_balances_count": len(final_balances),
            # Keep the final balances digest component named inside the result document
            # contract.
            "final_balances_digest": balances.digest.hex,
            "ledger_hash": recorder.ledger.digest.hex,
            "ledger_transaction_count": recorder.ledger.count,
            "network_base_fee_paid_atomic": aggregates.network_base_fee_paid_atomic,
            "network_priority_fee_paid_atomic": aggregates.network_priority_fee_paid_atomic,
            # Keep the open position count component named inside the result document
            # contract.
            "open_position_count": aggregates.open_count,
            "protocol_fee_paid_atomic": aggregates.protocol_fee_paid_atomic,
            "real_liquidity_sufficient_filled_sell_count": (
                aggregates.real_liquidity_sufficient_filled_sell_count
            ),
            "realized_cash_pnl_atomic": aggregates.realized_cash_pnl_atomic,
            "rejected_order_count": rejected_order_count,
            "roundtrip_count": recorder.roundtrips.count,
            # Keep the roundtrip digest component named inside the result document
            # contract.
            "roundtrip_digest": recorder.roundtrips.digest.hex,
            "sell_slippage_failure_count": aggregates.sell_slippage_failure_count,
            "settlement_policy_id": liquidity_policy_id_for_execution_mode(config.execution_mode),
            "gross_sell_settlement_atomic": aggregates.gross_sell_settlement_atomic,
            "venue_funded_sell_atomic": aggregates.venue_funded_sell_atomic,
            "synthetic_funded_sell_atomic": aggregates.synthetic_funded_sell_atomic,
            "synthetic_liquidity_used_sell_count": (aggregates.synthetic_liquidity_used_sell_count),
            "unvalued_open_position_count": aggregates.unvalued_open_position_count,
            "valuation_status": aggregates.valuation_status.value,
            "valued_economic_pnl_subtotal_atomic": (aggregates.valued_economic_pnl_subtotal_atomic),
            # Complete the result document group only after its semantic components are
            # visible.
        }
        return SnipingRunSummary(
            dataset_logical_content_hash=source.logical_content_hash,
            replay_semantics_id=source.replay_semantics_id,
            engine_bundle_id=config.engine_bundle_id,
            # Pass strategy bundle id explicitly so SnipingRunSummary receives a
            # reviewable v2 and logical content hash input in sniping reference engine
            # run.
            strategy_bundle_id=strategy.bundle_id,
            protocol_bundle_id=protocol.bundle_id,
            network_cost_bundle_id=network_costs.bundle_id,
            historical_group_count=group_count,
            historical_event_count=event_count,
            # Pass delivered event count explicitly so SnipingRunSummary receives a
            # reviewable v2 and logical content hash input in sniping reference engine
            # run.
            delivered_event_count=delivered_event_count,
            target_count=target_count,
            cooldown_skipped_count=cooldown_skipped_count,
            accepted_buy_count=accepted_buy_count,
            accepted_sell_count=aggregates.accepted_sell_count,
            # Pass rejected buy count explicitly so SnipingRunSummary receives a
            # reviewable v2 and logical content hash input in sniping reference engine
            # run.
            rejected_buy_count=aggregates.rejected_buy_count,
            rejected_sell_count=aggregates.rejected_sell_count,
            accepted_order_count=accepted_order_count,
            rejected_order_count=rejected_order_count,
            filled_order_count=recorder.fills.count,
            # Pass failed order count explicitly so SnipingRunSummary receives a
            # reviewable v2 and logical content hash input in sniping reference engine
            # run.
            failed_order_count=failed_order_count,
            closed_roundtrip_count=aggregates.closed_count,
            open_position_count=aggregates.open_count,
            failed_buy_count=failed_buy_count,
            failed_sell_count=failed_sell_count,
            # Pass realized cash pnl atomic explicitly so SnipingRunSummary receives a
            # reviewable v2 and logical content hash input in sniping reference engine
            # run.
            realized_cash_pnl_atomic=aggregates.realized_cash_pnl_atomic,
            valuation_status=aggregates.valuation_status,
            unvalued_open_position_count=aggregates.unvalued_open_position_count,
            valued_economic_pnl_subtotal_atomic=(aggregates.valued_economic_pnl_subtotal_atomic),
            economic_pnl_atomic=aggregates.economic_pnl_atomic,
            # Pass cashback receivable atomic explicitly so SnipingRunSummary receives a
            # reviewable v2 and logical content hash input in sniping reference engine
            # run.
            cashback_receivable_atomic=aggregates.cashback_receivable_atomic,
            protocol_fee_paid_atomic=aggregates.protocol_fee_paid_atomic,
            creator_fee_paid_atomic=aggregates.creator_fee_paid_atomic,
            network_base_fee_paid_atomic=aggregates.network_base_fee_paid_atomic,
            network_priority_fee_paid_atomic=aggregates.network_priority_fee_paid_atomic,
            # Pass account deposit paid atomic explicitly so SnipingRunSummary receives a
            # reviewable v2 and logical content hash input in sniping reference engine
            # run.
            account_deposit_paid_atomic=aggregates.account_deposit_paid_atomic,
            account_deposit_refunded_atomic=aggregates.account_deposit_refunded_atomic,
            account_deposit_locked_atomic=aggregates.account_deposit_locked_atomic,
            favorable_slippage_count=aggregates.favorable_slippage_count,
            adverse_slippage_count=aggregates.adverse_slippage_count,
            # Pass buy slippage failure count explicitly so SnipingRunSummary receives a
            # reviewable v2 and logical content hash input in sniping reference engine
            # run.
            buy_slippage_failure_count=aggregates.buy_slippage_failure_count,
            sell_slippage_failure_count=aggregates.sell_slippage_failure_count,
            ledger_transaction_count=recorder.ledger.count,
            fill_count=recorder.fills.count,
            roundtrip_count=recorder.roundtrips.count,
            # Pass audit hash explicitly so SnipingRunSummary receives a reviewable v2 and
            # logical content hash input in sniping reference engine run.
            audit_hash=recorder.audit.digest,
            ledger_hash=recorder.ledger.digest,
            fill_hash=recorder.fills.digest,
            roundtrip_digest=recorder.roundtrips.digest,
            final_balances_digest=balances.digest,
            # Include result hash in the completed sniping reference engine run result.
            result_hash=domain_digest("backtest.canonical-sniping-run-result.v4", result_document),
            final_balances=final_balances,
            execution_mode=config.execution_mode,
            settlement_policy_id=liquidity_policy_id_for_execution_mode(config.execution_mode),
            filled_sell_count=aggregates.filled_sell_count,
            real_liquidity_sufficient_filled_sell_count=(
                aggregates.real_liquidity_sufficient_filled_sell_count
            ),
            synthetic_liquidity_used_sell_count=(aggregates.synthetic_liquidity_used_sell_count),
            gross_sell_settlement_atomic=aggregates.gross_sell_settlement_atomic,
            venue_funded_sell_atomic=aggregates.venue_funded_sell_atomic,
            synthetic_funded_sell_atomic=aggregates.synthetic_funded_sell_atomic,
        )

    def _accept_buy(
        self,
        # Close the accept buy signature after its explicit inputs.
        *,
        state: _RoundTripState,
        clock: CompactTransactionClock,
        protocol: SnipingProtocolRuntime,
        network_costs: SnipingNetworkCostModel,
        # Keep the portfolio input explicit in the accept buy contract.
        portfolio: PortfolioState,
        accounts: WalletProvisioningReducer,
        recorder: _Recorder,
        scheduled: list[_ScheduledAction],
    ) -> bool:
        # Execute the sniping reference engine accept buy workflow in explicit, reviewable
        # steps.
        intent = _require_intent(state)
        effective_s = state.target_time_ns // 1_000_000_000
        requirements = protocol.account_requirements(intent)
        network = network_costs.quote_buy(
            effective_at_unix_s=effective_s,
            requirements=requirements,
        )
        account_plan = accounts.reservation(
            roundtrip_id=intent.roundtrip_id,
            mint_asset_id=intent.asset_id,
            priced_requirements=network.account_requirements,
        )
        state.buy_network_cost = network
        state.account_reservation = account_plan
        try:
            # Perform the protected sniping reference engine accept buy operation before
            # explicit failure handling.
            reference = protocol.quote_buy(
                intent,
                effective_at_unix_s=effective_s,
            )
        except ProtocolExecutionRejected as error:
            # Translate the ProtocolExecutionRejected failure through the sniping
            # reference engine accept buy boundary.
            state.buy_failure_code = error.code
            state.status = RoundTripStatus.BUY_REFERENCE_REJECTED
            state.terminal = True
            state.account_components = unsubmitted_account_records(accounts.state, account_plan)
            recorder.append_audit(
                {
                    # Keep boundary ordinal named so the code and buy reference rejected
                    # payload passed to append_audit remains self-describing within
                    # sniping reference engine accept buy.
                    "boundary_ordinal": intent.created_boundary_ordinal,
                    "phase": int(SchedulerPhase.RISK_AND_ORDER_ACCEPTANCE),
                    "reason": error.code,
                    "record_type": "BUY_REFERENCE_REJECTED",
                    "roundtrip_id": intent.roundtrip_id.hex,
                    # Close the code and buy reference rejected payload only after all sniping
                    # reference engine accept buy fields are present.
                }
            )
            return False
        _validate_buy_quote(intent, reference)
        state.buy_reference = reference
        # Assemble state buy minimum out atomic once so the sniping reference engine
        # accept buy workflow shares one value.
        state.buy_minimum_out_atomic = _minimum_output_atomic(
            reference.amount_out_atomic,
            intent.buy_slippage_bps,
        )
        landing = clock.transaction_after(
            # Pass intent explicitly so transaction_after receives a reviewable target
            # position and buy delay transactions input in sniping reference engine accept
            # buy.
            intent.target_position,
            intent.buy_delay_transactions,
        )
        # Assemble reservation once so the sniping reference engine accept buy workflow
        # shares one value.
        reservation = _buy_reservation(intent, network, account_plan)
        if not _has_available(portfolio, reservation):
            # Handle the sniping reference engine accept buy has available, portfolio and
            # reservation condition as a distinct block.
            state.status = RoundTripStatus.BUY_PRE_SUBMIT_INSUFFICIENT_FUNDS
            state.terminal = True
            state.account_components = unsubmitted_account_records(accounts.state, account_plan)
            recorder.append_audit(
                {
                    "boundary_ordinal": intent.created_boundary_ordinal,
                    # Pass phase explicitly to append_audit for insufficient funds and buy
                    # pre submit rejected.
                    "phase": int(SchedulerPhase.RISK_AND_ORDER_ACCEPTANCE),
                    "reason": "INSUFFICIENT_FUNDS",
                    "record_type": "BUY_PRE_SUBMIT_REJECTED",
                    "roundtrip_id": intent.roundtrip_id.hex,
                }
                # Complete append_audit only after its insufficient funds and buy pre submit
                # rejected inputs are visible in sniping reference engine accept buy.
            )
            return False
        transaction = _reserve_buy(intent, network, account_plan)
        _apply_transaction(portfolio, recorder, transaction)
        _schedule(
            # Pass scheduled explicitly so _schedule receives a reviewable buy-landing and
            # buy landing input in sniping reference engine accept buy.
            scheduled,
            position=landing,
            phase=_ActionKind.BUY_LANDING,
            creator_boundary=intent.created_boundary_ordinal,
            causal_id=_action_id(intent.roundtrip_id, "buy-landing"),
            # Pass payload explicitly to _schedule for buy-landing and buy landing.
            payload=_BuyLanding(intent.roundtrip_id),
        )
        recorder.append_audit(
            {
                "boundary_ordinal": intent.created_boundary_ordinal,
                # Keep eligible boundary ordinal named so the buy accepted and reserved
                # and boundary ordinal payload passed to append_audit remains self-
                # describing within sniping reference engine accept buy.
                "eligible_boundary_ordinal": landing.boundary_ordinal,
                "phase": int(SchedulerPhase.RISK_AND_ORDER_ACCEPTANCE),
                "record_type": "BUY_ACCEPTED_AND_RESERVED",
                "reserved_assets": _asset_amounts_document(reservation),
                "roundtrip_id": intent.roundtrip_id.hex,
                # Close the buy accepted and reserved and boundary ordinal payload only after
                # all sniping reference engine accept buy fields are present.
            }
        )
        return True

    def _land_buy(
        self,
        # Close the land buy signature after its explicit inputs.
        *,
        state: _RoundTripState,
        position: ChainPosition,
        clock: CompactTransactionClock,
        protocol: SnipingProtocolRuntime,
        # Keep the network costs input explicit in the land buy contract.
        network_costs: SnipingNetworkCostModel,
        portfolio: PortfolioState,
        accounts: WalletProvisioningReducer,
        recorder: _Recorder,
        scheduled: list[_ScheduledAction],
    ) -> bool:
        # Execute the sniping reference engine land buy workflow in explicit, reviewable
        # steps.
        intent = _require_intent(state)
        reference = _require_buy_reference(state)
        network = _require_buy_network(state)
        account_plan = _require_account_reservation(state)
        effective_s = clock.block_time_for_position(position) // 1_000_000_000
        state.buy_landing_position = position
        # Keep expected failures inside the sniping reference engine land buy error
        # boundary.
        try:
            # Perform the protected sniping reference engine land buy operation before
            # explicit failure handling.
            landing = protocol.quote_buy(
                intent,
                effective_at_unix_s=effective_s,
            )
            _validate_buy_quote(intent, landing)
            # Assemble state buy landing once so the sniping reference engine land buy
            # workflow shares one value.
            state.buy_landing = landing
            if landing.amount_out_atomic < state.buy_minimum_out_atomic:
                raise ProtocolExecutionRejected("MINIMUM_OUTPUT_NOT_MET")
        except ProtocolExecutionRejected as error:
            # Translate the ProtocolExecutionRejected failure through the sniping
            # reference engine land buy boundary.
            state.buy_failure_code = error.code
            state.status = RoundTripStatus.BUY_LANDED_FAILED
            state.terminal = True
            account_transition = accounts.preview_buy(account_plan, successful=False)
            transaction = _failed_buy_settlement(
                intent,
                # Pass boundary explicitly so _failed_buy_settlement receives a reviewable
                # boundary ordinal and fee collector account id input in sniping reference
                # engine land buy.
                boundary=position.boundary_ordinal,
                network=network,
                account_plan=account_plan,
                network_fee_account_id=network_costs.fee_collector_account_id,
                reason=error.code,
            )
            # Invoke _apply_transaction for portfolio and recorder as a visible sniping
            # reference engine land buy step.
            _apply_transaction_with_accounts(
                portfolio,
                recorder,
                transaction,
                accounts=accounts,
                transition=account_transition,
            )
            state.account_components = account_transition.records
            recorder.append_audit(
                {
                    "boundary_ordinal": position.boundary_ordinal,
                    "phase": int(SchedulerPhase.VENUE_EXECUTION_AND_LEDGER_COMMIT),
                    # Keep reason named so the code and buy landed failed network fee
                    # charged payload passed to append_audit remains self-describing
                    # within sniping reference engine land buy.
                    "reason": error.code,
                    "record_type": "BUY_LANDED_FAILED_NETWORK_FEE_CHARGED",
                    "roundtrip_id": intent.roundtrip_id.hex,
                }
            )
            # Return the completed sniping reference engine land buy result without a
            # hidden fallback.
            return False
        account_transition = accounts.preview_buy(account_plan, successful=True)
        transaction = _successful_buy_settlement(
            intent,
            boundary=position.boundary_ordinal,
            quote=landing,
            # Pass network explicitly so _successful_buy_settlement receives a reviewable
            # boundary ordinal and fee collector account id input in sniping reference
            # engine land buy.
            network=network,
            account_plan=account_plan,
            account_transition=account_transition,
            network_fee_account_id=network_costs.fee_collector_account_id,
        )
        _apply_transaction_with_accounts(
            portfolio,
            recorder,
            transaction,
            accounts=accounts,
            transition=account_transition,
        )
        fill = _fill(
            # Pass intent explicitly so _fill receives a reviewable buy and boundary
            # ordinal input in sniping reference engine land buy.
            intent,
            side=ProtocolQuoteSide.BUY,
            quote=landing,
            boundary=position.boundary_ordinal,
        )
        # Invoke append_fill for fill as a visible sniping reference engine land buy step.
        recorder.append_fill(fill)
        state.acquired_token_amount_atomic = landing.amount_out_atomic
        state.account_components = account_transition.records
        state.cashback_receivable_atomic += landing.cashback_receivable_atomic
        state.status = RoundTripStatus.OPEN_AT_HORIZON
        fill_time_ns = clock.block_time_for_position(position)
        decision_position = clock.first_nonempty_transaction_at_or_after(
            # Pass after position explicitly so first_nonempty_transaction_at_or_after
            # receives a reviewable sell decision delay ns and position input in sniping
            # reference engine land buy.
            after_position=position,
            target_time_ns=fill_time_ns + intent.sell_decision_delay_ns,
        )
        _schedule(
            scheduled,
            # Pass position explicitly so _schedule receives a reviewable sell-decision
            # and sell decision input in sniping reference engine land buy.
            position=decision_position,
            phase=_ActionKind.SELL_DECISION,
            creator_boundary=position.boundary_ordinal,
            causal_id=_action_id(intent.roundtrip_id, "sell-decision"),
            payload=_SellDecision(intent.roundtrip_id),
            # Complete _schedule only after its sell-decision and sell decision inputs are
            # visible in sniping reference engine land buy.
        )
        recorder.append_audit(
            {
                "boundary_ordinal": position.boundary_ordinal,
                "phase": int(SchedulerPhase.VENUE_EXECUTION_AND_LEDGER_COMMIT),
                # Keep record type named so the buy filled and boundary ordinal payload
                # passed to append_audit remains self-describing within sniping reference
                # engine land buy.
                "record_type": "BUY_FILLED",
                "roundtrip_id": intent.roundtrip_id.hex,
                "sell_decision_boundary_ordinal": decision_position.boundary_ordinal,
            }
        )
        # Discard reference after its boundary-only use.
        del reference
        return True

    def _decide_sell(
        self,
        *,
        # Keep the state input explicit in the decide sell contract.
        state: _RoundTripState,
        position: ChainPosition,
        clock: CompactTransactionClock,
        protocol: SnipingProtocolRuntime,
        network_costs: SnipingNetworkCostModel,
        # Keep the portfolio input explicit in the decide sell contract.
        portfolio: PortfolioState,
        recorder: _Recorder,
        scheduled: list[_ScheduledAction],
    ) -> None:
        # Execute the sniping reference engine decide sell workflow in explicit,
        # reviewable steps.
        intent = _require_intent(state)
        if state.acquired_token_amount_atomic <= 0 or state.terminal:
            raise SnipingEngineError(SnipingEngineErrorCode.INTERNAL_STATE_INVALID)
        effective_s = clock.block_time_for_position(position) // 1_000_000_000
        state.sell_decision_position = position
        # Keep expected failures inside the sniping reference engine decide sell error
        # boundary.
        try:
            # Perform the protected sniping reference engine decide sell operation before
            # explicit failure handling.
            reference = protocol.quote_sell(
                intent,
                tokens_in_atomic=state.acquired_token_amount_atomic,
                effective_at_unix_s=effective_s,
            )
        # Translate protocol execution rejected through the sniping reference engine
        # decide sell boundary without hiding other errors.
        except ProtocolExecutionRejected as error:
            # Translate the ProtocolExecutionRejected failure through the sniping
            # reference engine decide sell boundary.
            state.sell_failure_code = error.code
            state.status = RoundTripStatus.SELL_REFERENCE_UNAVAILABLE_OPEN
            state.terminal = True
            recorder.append_audit(
                {
                    # Keep boundary ordinal named so the code and sell reference
                    # unavailable payload passed to append_audit remains self-describing
                    # within sniping reference engine decide sell.
                    "boundary_ordinal": position.boundary_ordinal,
                    "phase": int(SchedulerPhase.STRATEGY_CALLBACK),
                    "reason": error.code,
                    "record_type": "SELL_REFERENCE_UNAVAILABLE",
                    "roundtrip_id": intent.roundtrip_id.hex,
                    # Close the code and sell reference unavailable payload only after all
                    # sniping reference engine decide sell fields are present.
                }
            )
            return
        _validate_sell_quote(intent, state.acquired_token_amount_atomic, reference)
        state.sell_reference = reference
        # Assemble state sell minimum out atomic once so the sniping reference engine
        # decide sell workflow shares one value.
        state.sell_minimum_out_atomic = _minimum_output_atomic(
            reference.amount_out_atomic,
            intent.sell_slippage_bps,
        )
        landing = clock.transaction_after(position, intent.sell_delay_transactions)
        # Assemble network once so the sniping reference engine decide sell workflow
        # shares one value.
        network = network_costs.quote_sell(effective_at_unix_s=effective_s)
        state.sell_network_cost = network
        if portfolio.available(intent.asset_id) < state.acquired_token_amount_atomic:
            raise SnipingEngineError(SnipingEngineErrorCode.PORTFOLIO_INVARIANT)
        sell_reservation = _sell_reservation(
            # Pass intent explicitly so _sell_reservation receives a reviewable acquired
            # token amount atomic and intent input in sniping reference engine decide
            # sell.
            intent,
            tokens_atomic=state.acquired_token_amount_atomic,
            network=network,
        )
        if not _has_available(portfolio, sell_reservation):
            # Handle the sniping reference engine decide sell has available, portfolio and
            # sell reservation condition as a distinct block.
            state.status = RoundTripStatus.SELL_PRE_SUBMIT_INSUFFICIENT_FUNDS_OPEN
            state.terminal = True
            recorder.append_audit(
                {
                    "boundary_ordinal": position.boundary_ordinal,
                    # Pass phase explicitly to append_audit for insufficient network fee
                    # and sell pre submit rejected.
                    "phase": int(SchedulerPhase.RISK_AND_ORDER_ACCEPTANCE),
                    "reason": "INSUFFICIENT_NETWORK_FEE",
                    "record_type": "SELL_PRE_SUBMIT_REJECTED",
                    "roundtrip_id": intent.roundtrip_id.hex,
                }
                # Complete append_audit only after its insufficient network fee and sell pre
                # submit rejected inputs are visible in sniping reference engine decide sell.
            )
            return
        reservation = _reserve_sell(
            intent,
            tokens_atomic=state.acquired_token_amount_atomic,
            # Pass network explicitly so _reserve_sell receives a reviewable acquired
            # token amount atomic and boundary ordinal input in sniping reference engine
            # decide sell.
            network=network,
            boundary=position.boundary_ordinal,
        )
        _apply_transaction(portfolio, recorder, reservation)
        _schedule(
            # Pass scheduled explicitly so _schedule receives a reviewable sell-landing
            # and sell landing input in sniping reference engine decide sell.
            scheduled,
            position=landing,
            phase=_ActionKind.SELL_LANDING,
            creator_boundary=position.boundary_ordinal,
            causal_id=_action_id(intent.roundtrip_id, "sell-landing"),
            # Pass payload explicitly to _schedule for sell-landing and sell landing.
            payload=_SellLanding(intent.roundtrip_id),
        )
        recorder.append_audit(
            {
                "boundary_ordinal": position.boundary_ordinal,
                # Keep eligible boundary ordinal named so the sell accepted and reserved
                # and boundary ordinal payload passed to append_audit remains self-
                # describing within sniping reference engine decide sell.
                "eligible_boundary_ordinal": landing.boundary_ordinal,
                "phase": int(SchedulerPhase.RISK_AND_ORDER_ACCEPTANCE),
                "record_type": "SELL_ACCEPTED_AND_RESERVED",
                "roundtrip_id": intent.roundtrip_id.hex,
            }
            # Complete append_audit only after its sell accepted and reserved and boundary
            # ordinal inputs are visible in sniping reference engine decide sell.
        )

    def _land_sell(
        self,
        *,
        state: _RoundTripState,
        # Keep the position input explicit in the land sell contract.
        position: ChainPosition,
        clock: CompactTransactionClock,
        protocol: SnipingProtocolRuntime,
        portfolio: PortfolioState,
        accounts: WalletProvisioningReducer,
        network_costs: SnipingNetworkCostModel,
        # Keep the recorder input explicit in the land sell contract.
        recorder: _Recorder,
    ) -> bool:
        # Execute the sniping reference engine land sell workflow in explicit, reviewable
        # steps.
        intent = _require_intent(state)
        reference = _require_sell_reference(state)
        network = _require_sell_network(state)
        effective_s = clock.block_time_for_position(position) // 1_000_000_000
        state.sell_landing_position = position
        # Keep expected failures inside the sniping reference engine land sell error
        # boundary.
        try:
            # Perform the protected sniping reference engine land sell operation before
            # explicit failure handling.
            landing = protocol.quote_sell(
                intent,
                tokens_in_atomic=state.acquired_token_amount_atomic,
                effective_at_unix_s=effective_s,
            )
            # Invoke _validate_sell_quote for acquired token amount atomic and intent as a
            # visible sniping reference engine land sell step.
            _validate_sell_quote(
                intent,
                state.acquired_token_amount_atomic,
                landing,
            )
            # Assemble state sell landing once so the sniping reference engine land sell
            # workflow shares one value.
            state.sell_landing = landing
            if landing.amount_out_atomic < state.sell_minimum_out_atomic:
                raise ProtocolExecutionRejected("MINIMUM_OUTPUT_NOT_MET")
        except ProtocolExecutionRejected as error:
            # Translate the ProtocolExecutionRejected failure through the sniping
            # reference engine land sell boundary.
            state.sell_failure_code = error.code
            state.status = RoundTripStatus.SELL_LANDED_FAILED_OPEN
            state.terminal = True
            transaction = _failed_sell_settlement(
                intent,
                # Pass boundary explicitly so _failed_sell_settlement receives a
                # reviewable boundary ordinal and acquired token amount atomic input in
                # sniping reference engine land sell.
                boundary=position.boundary_ordinal,
                tokens_atomic=state.acquired_token_amount_atomic,
                network=network,
                network_fee_account_id=network_costs.fee_collector_account_id,
                reason=error.code,
                # Complete _failed_sell_settlement only after its boundary ordinal and
                # acquired token amount atomic inputs are visible in sniping reference engine
                # land sell.
            )
            _apply_transaction(portfolio, recorder, transaction)
            recorder.append_audit(
                {
                    "boundary_ordinal": position.boundary_ordinal,
                    # Pass phase explicitly to append_audit for code and sell landed
                    # failed network fee charged.
                    "phase": int(SchedulerPhase.VENUE_EXECUTION_AND_LEDGER_COMMIT),
                    "reason": error.code,
                    "record_type": "SELL_LANDED_FAILED_NETWORK_FEE_CHARGED",
                    "roundtrip_id": intent.roundtrip_id.hex,
                }
                # Complete append_audit only after its code and sell landed failed network fee
                # charged inputs are visible in sniping reference engine land sell.
            )
            return False
        account_transition = accounts.preview_sell(
            roundtrip_id=intent.roundtrip_id,
            mint_asset_id=intent.asset_id,
            records=state.account_components,
            successful=True,
        )
        transaction = _successful_sell_settlement(
            intent,
            boundary=position.boundary_ordinal,
            # Pass quote explicitly so _successful_sell_settlement receives a reviewable
            # boundary ordinal and acquired token amount atomic input in sniping reference
            # engine land sell.
            quote=landing,
            network=network,
            tokens_atomic=state.acquired_token_amount_atomic,
            account_transition=account_transition,
            # Pass network fee account id explicitly so _successful_sell_settlement
            # receives a reviewable boundary ordinal and acquired token amount atomic
            # input in sniping reference engine land sell.
            network_fee_account_id=network_costs.fee_collector_account_id,
        )
        _apply_transaction_with_accounts(
            portfolio,
            recorder,
            transaction,
            accounts=accounts,
            transition=account_transition,
        )
        recorder.append_fill(
            _fill(
                # Pass intent explicitly so _fill receives a reviewable sell and boundary
                # ordinal input in sniping reference engine land sell.
                intent,
                side=ProtocolQuoteSide.SELL,
                quote=landing,
                boundary=position.boundary_ordinal,
            )
            # Complete append_fill only after its sell and boundary ordinal inputs are visible
            # in sniping reference engine land sell.
        )
        state.cashback_receivable_atomic += landing.cashback_receivable_atomic
        state.account_components = account_transition.records
        state.status = RoundTripStatus.CLOSED
        state.terminal = True
        recorder.append_audit(
            # Open the sell filled and account closed and boundary ordinal payload
            # explicitly for append_audit within sniping reference engine land sell.
            {
                "boundary_ordinal": position.boundary_ordinal,
                "phase": int(SchedulerPhase.VENUE_EXECUTION_AND_LEDGER_COMMIT),
                "realized_cash_pnl_atomic": recorder.cashflows.amount(
                    intent.roundtrip_id,
                    # Pass intent explicitly so amount receives a reviewable roundtrip id
                    # and quote asset id input in sniping reference engine land sell.
                    intent.quote_asset_id,
                ),
                "record_type": "SELL_FILLED_AND_ACCOUNT_CLOSED",
                "roundtrip_id": intent.roundtrip_id.hex,
            }
            # Complete append_audit only after its sell filled and account closed and boundary
            # ordinal inputs are visible in sniping reference engine land sell.
        )
        del reference
        return True

    def _finalize_roundtrip(
        self,
        # Close the finalize roundtrip signature after its explicit inputs.
        *,
        roundtrip_id: ContentDigest,
        state: _RoundTripState,
        committed_quote_cashflow_atomic: int,
        protocol: SnipingProtocolRuntime,
        # Keep the network costs input explicit in the finalize roundtrip contract.
        network_costs: SnipingNetworkCostModel,
        config: SnipingRunConfig,
        final_time_unix_s: int,
    ) -> RoundTripRecord:
        # Execute the sniping reference engine finalize roundtrip workflow in explicit,
        # reviewable steps.
        buy = _buy_leg(state)
        sell = _sell_leg(state)
        realized: int | None = None
        mtm_status = MtmStatus.NOT_APPLICABLE
        mtm_value: int | None = None
        # Assemble mtm pnl once so the sniping reference engine finalize roundtrip
        # workflow shares one value.
        mtm_pnl: int | None = None
        mtm_liquidity: QuoteLiquidityEvidenceRecord | None = None
        economic: int | None = None
        run_locked_quote_value = _asset_amount(
            run_locked_value(state.account_components),
            state.target.quote_asset_id,
        )
        if state.status is RoundTripStatus.CLOSED:
            # Handle the sniping reference engine finalize roundtrip state.status is
            # RoundTripStatus.CLOSED branch as a distinct logical block.
            realized = committed_quote_cashflow_atomic
            economic = realized + state.cashback_receivable_atomic + run_locked_quote_value
        # Handle the sniping reference engine finalize roundtrip complement of
        # state.status is RoundTripStatus.CLOSED explicitly.
        elif state.acquired_token_amount_atomic > 0:
            # Handle the sniping reference engine finalize roundtrip
            # state.acquired_token_amount_atomic > 0 branch as a distinct logical block.
            intent = _require_intent(state)
            try:
                # Perform the protected sniping reference engine finalize roundtrip
                # operation before explicit failure handling.
                valuation = protocol.valuation_quote(
                    intent,
                    tokens_in_atomic=state.acquired_token_amount_atomic,
                    effective_at_unix_s=final_time_unix_s,
                )
            # Translate protocol execution rejected through the sniping reference engine
            # finalize roundtrip boundary without hiding other errors.
            except ProtocolExecutionRejected:
                valuation = None
            if valuation is None:
                mtm_status = MtmStatus.UNAVAILABLE
            else:
                # Handle the sniping reference engine finalize roundtrip complement of
                # valuation is None explicitly.
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
                        # Pass intent explicitly so _amount_if_asset receives a reviewable
                        # fee asset id and quote asset id input in sniping reference
                        # engine finalize roundtrip.
                        intent.quote_asset_id,
                        network.transaction_fee_atomic,
                    )
                    + _asset_amount(
                        refundable_mint_deposits(state.account_components),
                        intent.quote_asset_id,
                    )
                )
                mtm_pnl = committed_quote_cashflow_atomic + mtm_value
                # Assemble economic once so the sniping reference engine finalize
                # roundtrip workflow shares one value.
                economic = mtm_pnl + state.cashback_receivable_atomic + run_locked_quote_value
        else:
            # Handle the sniping reference engine finalize roundtrip complement of
            # state.acquired_token_amount_atomic > 0 explicitly.
            realized = committed_quote_cashflow_atomic
            economic = realized + state.cashback_receivable_atomic + run_locked_quote_value
        return RoundTripRecord(
            roundtrip_id=roundtrip_id,
            # Pass network id explicitly so RoundTripRecord receives a reviewable network
            # id and position input in sniping reference engine finalize roundtrip.
            network_id=state.target.position.network_id,
            position_schema_id=state.target.position.position_schema_id,
            target_event_id=state.target.target_event_id,
            target_position=state.target.position,
            target_time_ns=state.target_time_ns,
            # Pass developer id explicitly so RoundTripRecord receives a reviewable
            # network id and position input in sniping reference engine finalize
            # roundtrip.
            developer_id=state.target.developer_id,
            creation_user_id=state.target.creation_user_id,
            asset_id=state.target.asset_id,
            quote_asset_id=state.target.quote_asset_id,
            venue_id=state.target.venue_id,
            # Pass cooldown consumed explicitly so RoundTripRecord receives a reviewable
            # network id and position input in sniping reference engine finalize
            # roundtrip.
            cooldown_consumed=state.cooldown_consumed,
            cooldown_until_ns=state.cooldown_until_ns,
            status=state.status,
            buy=buy,
            sell=sell,
            # Pass acquired token amount atomic explicitly so RoundTripRecord receives a
            # reviewable network id and position input in sniping reference engine
            # finalize roundtrip.
            acquired_token_amount_atomic=state.acquired_token_amount_atomic,
            cashback_receivable_atomic=state.cashback_receivable_atomic,
            realized_cash_pnl_atomic=realized,
            mtm_status=mtm_status,
            # Pass mtm liquidation value atomic explicitly so RoundTripRecord receives a
            # reviewable network id and position input in sniping reference engine
            # finalize roundtrip.
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


def _validate_chain_contract(
    # Keep the clock input explicit in the validate chain contract contract.
    clock: CompactTransactionClock,
    config: SnipingRunConfig,
) -> None:
    # Execute the validate chain contract workflow in explicit, reviewable steps.
    if (
        config.decision_range.network_id != clock.network_id
        or config.decision_range.position_schema_id != clock.position_schema_id
    ):
        # Handle the validate chain contract network id, position schema id and decision
        # range condition as a distinct block.
        raise ChainIdentityMismatchError(
            "decision range and transaction clock use different chain identities"
        )


def _preflight_sniping_delivery_schedule(
    *,
    # Keep the source input explicit in the preflight sniping delivery schedule contract.
    source: HistoricalEventSource,
    schedule: ObservationDeliverySource | None,
    expected_event_count: int,
) -> None:
    # Execute the preflight sniping delivery schedule workflow in explicit, reviewable
    # steps.
    if schedule is None:
        return
    if not isinstance(source, IndexedHistoricalEventSource):
        raise SnipingEngineError(SnipingEngineErrorCode.DELIVERY_SCHEDULE_INVALID)
    counts = (
        # Keep the schedule component named inside the counts contract.
        schedule.input_event_count,
        schedule.delivery_count,
        schedule.outside_horizon_count,
    )
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts):
        # Fail the preflight sniping delivery schedule path with SnipingEngineError for
        # delivery schedule invalid and sniping engine error code when value, counts and
        # isinstance is true; do not continue ambiguously.
        raise SnipingEngineError(SnipingEngineErrorCode.DELIVERY_SCHEDULE_INVALID)
    if (
        schedule.input_event_count != expected_event_count
        or schedule.delivery_count != expected_event_count
        or schedule.outside_horizon_count != 0
        # Evaluate the complete preflight sniping delivery schedule input event count,
        # expected event count and delivery count condition before guarded effects.
    ):
        raise SnipingEngineError(SnipingEngineErrorCode.DELIVERY_SCHEDULE_INVALID)
    previous_key: tuple[int, int, str] | None = None
    consumed = 0
    for delivery in schedule.deliveries():
        # Process schedule.deliveries() inside the bounded preflight sniping delivery
        # schedule loop.
        if consumed >= schedule.delivery_count:
            raise SnipingEngineError(SnipingEngineErrorCode.DELIVERY_SCHEDULE_INVALID)
        if not isinstance(delivery, ObservationDelivery) or not (
            0 <= delivery.event_row_index < expected_event_count
        ):
            # Fail the preflight sniping delivery schedule path with SnipingEngineError
            # for delivery schedule invalid and sniping engine error code when isinstance,
            # delivery and observation delivery is true; do not continue ambiguously.
            raise SnipingEngineError(SnipingEngineErrorCode.DELIVERY_SCHEDULE_INVALID)
        event = source.event_at(delivery.event_row_index)
        source_boundary = event.envelope.boundary_ordinal
        if delivery.release_boundary_ordinal != source_boundary:
            raise SnipingEngineError(SnipingEngineErrorCode.DELIVERY_SCHEDULE_INVALID)
        # Assemble key once so the preflight sniping delivery schedule workflow shares one
        # value.
        key = (
            delivery.release_boundary_ordinal,
            source_boundary,
            event.envelope.stable_causal_id.hex,
        )
        # Evaluate the complete preflight sniping delivery schedule previous key and key
        # condition before guarded effects.
        if previous_key is not None and key <= previous_key:
            raise SnipingEngineError(SnipingEngineErrorCode.DELIVERY_SCHEDULE_INVALID)
        previous_key = key
        consumed += 1
    if consumed != schedule.delivery_count:
        # Fail the preflight sniping delivery schedule path with SnipingEngineError for
        # delivery schedule invalid and sniping engine error code when consumed, delivery
        # count and schedule is true; do not continue ambiguously.
        raise SnipingEngineError(SnipingEngineErrorCode.DELIVERY_SCHEDULE_INVALID)


def _preflight_source_clock_coverage(
    *,
    source: HistoricalEventSource,
    clock: CompactTransactionClock,
    # Keep the strategy input explicit in the preflight source clock coverage contract.
    strategy: SnipingStrategyInstance,
    decision_range: BlockRange,
) -> tuple[int, int]:
    """Prove all possible v1 execution boundaries before mutable replay starts.

    The reference source is deliberately scanned twice.  This bounded-memory
    pass validates ordering/coordinates and conservatively requires a complete
    buy/sell settlement path for every launch inside the decision range.  It
    therefore cannot consume cooldown, change protocol state, reserve cash or
    append a partial output before discovering an insufficient clock tail.
    """

    event_count = 0
    group_count = 0
    for group in _event_groups(source.events(), clock=clock):
        # Process event groups, events and clock inside the bounded preflight source clock
        # coverage loop.
        event_count += len(group)
        group_count += 1
        for event in group:
            # Process group inside the bounded preflight source clock coverage loop.
            if not isinstance(event, TokenLaunchEvent):
                continue
            position = event.envelope.position
            if not decision_range.contains_position(position):
                continue
            # Assemble buy landing once so the preflight source clock coverage workflow
            # shares one value.
            buy_landing = clock.transaction_after(
                position,
                strategy.buy_delay_transactions,
            )
            sell_decision = clock.first_nonempty_transaction_at_or_after(
                # Pass after position explicitly so first_nonempty_transaction_at_or_after
                # receives a reviewable sell decision delay ns and block time for position
                # input in preflight source clock coverage.
                after_position=buy_landing,
                target_time_ns=(
                    clock.block_time_for_position(buy_landing) + strategy.sell_decision_delay_ns
                ),
            )
            # Invoke transaction_after for sell delay transactions and sell decision as a
            # visible preflight source clock coverage step.
            clock.transaction_after(
                sell_decision,
                strategy.sell_delay_transactions,
            )
    if isinstance(source, IndexedHistoricalEventSource) and event_count != source.event_count:
        # Fail the preflight source clock coverage path with SnipingEngineError for source
        # count mismatch and sniping engine error code when isinstance, source and indexed
        # historical event source is true; do not continue ambiguously.
        raise SnipingEngineError(SnipingEngineErrorCode.SOURCE_COUNT_MISMATCH)
    return event_count, group_count


def _event_groups(
    events: Iterator[CanonicalEvent],
    *,
    # Keep the clock input explicit in the event groups contract.
    clock: CompactTransactionClock,
) -> Iterator[tuple[CanonicalEvent, ...]]:
    # Execute the event groups workflow in explicit, reviewable steps.
    current: list[CanonicalEvent] = []
    current_identity: tuple[int, ContentDigest] | None = None
    previous_key: tuple[str, str, int, str, int, str] | None = None
    for event in events:
        # Process events inside the bounded event groups loop.
        position = event.envelope.position
        if (
            position.network_id != clock.network_id
            or position.position_schema_id != clock.position_schema_id
        ):
            # Fail the event groups path with SnipingEngineError for mixed network and
            # sniping engine error code when network id, position schema id and position
            # is true; do not continue ambiguously.
            raise SnipingEngineError(SnipingEngineErrorCode.MIXED_NETWORK)
        if position.transaction_index >= 0:
            clock.require_position(position)
        key = canonical_event_sort_key(event)
        if previous_key is not None and key <= previous_key:
            # Fail the event groups path with SnipingEngineError for source order invalid
            # and sniping engine error code when previous key and key is true; do not
            # continue ambiguously.
            raise SnipingEngineError(SnipingEngineErrorCode.SOURCE_ORDER_INVALID)
        previous_key = key
        identity = (
            event.envelope.boundary_ordinal,
            event.envelope.transaction_group_id,
            # Complete the identity group only after its semantic components are visible.
        )
        if (
            current_identity is not None
            and identity[0] == current_identity[0]
            and identity[1] != current_identity[1]
            # Evaluate the complete event groups current identity and identity condition
            # before guarded effects.
        ):
            raise SnipingEngineError(SnipingEngineErrorCode.MIXED_TRANSACTION_GROUP)
        if current_identity is None or identity == current_identity:
            # Handle the event groups current identity and identity condition as a
            # distinct block.
            current.append(event)
            current_identity = identity
            continue
        yield tuple(current)
        current = [event]
        # Assemble current identity once so the event groups workflow shares one value.
        current_identity = identity
    if current:
        yield tuple(current)


def _boundary_position(group: tuple[CanonicalEvent, ...]) -> ChainPosition:
    # Execute the boundary position workflow in explicit, reviewable steps.
    first = group[0].envelope.position
    return ChainPosition(
        network_id=first.network_id,
        position_schema_id=first.position_schema_id,
        block_ordinal=first.block_ordinal,
        # Pass transaction index explicitly so ChainPosition receives a reviewable network
        # id and position schema id input in boundary position.
        transaction_index=first.transaction_index,
        event_index=None,
    )


def _next_boundary(group: int | None, scheduled: int | None) -> int:
    # Execute the next boundary workflow in explicit, reviewable steps.
    values = tuple(value for value in (group, scheduled) if value is not None)
    if not values:
        raise SnipingEngineError(SnipingEngineErrorCode.INTERNAL_STATE_INVALID)
    return min(values)


def _pop_actions(
    # Keep the scheduled input explicit in the pop actions contract.
    scheduled: list[_ScheduledAction],
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


# Define schedule as one focused operation with an explicit boundary.
def _schedule(
    scheduled: list[_ScheduledAction],
    *,
    position: ChainPosition,
    phase: _ActionKind,
    # Keep the creator boundary input explicit in the schedule contract.
    creator_boundary: int,
    causal_id: ContentDigest,
    payload: _ActionPayload,
) -> None:
    # Execute the schedule workflow in explicit, reviewable steps.
    if position.boundary_ordinal <= creator_boundary:
        raise SnipingEngineError(SnipingEngineErrorCode.INTERNAL_STATE_INVALID)
    heapq.heappush(
        scheduled,
        _ScheduledAction(
            # Pass position explicitly so _ScheduledAction receives a reviewable boundary
            # ordinal and hex input in schedule.
            position.boundary_ordinal,
            int(phase),
            creator_boundary,
            causal_id.hex,
            payload,
            # Complete _ScheduledAction only after its boundary ordinal and hex inputs are
            # visible in schedule.
        ),
    )


def _action_id(roundtrip_id: ContentDigest, action: str) -> ContentDigest:
    # Execute the action id workflow in explicit, reviewable steps.
    return domain_digest(
        "backtest.sniping-scheduled-action.v1",
        {"action": action, "roundtrip_id": roundtrip_id.hex},
    )


def _require_state(
    # Keep the states input explicit in the require state contract.
    states: dict[ContentDigest, _RoundTripState],
    roundtrip_id: ContentDigest,
) -> _RoundTripState:
    # Execute the require state workflow in explicit, reviewable steps.
    try:
        return states[roundtrip_id]
    except KeyError as error:
        raise SnipingEngineError(SnipingEngineErrorCode.INTERNAL_STATE_INVALID) from error


def _require_intent(state: _RoundTripState) -> RoundTripIntent:
    # Execute the require intent workflow in explicit, reviewable steps.
    if state.intent is None:
        raise SnipingEngineError(SnipingEngineErrorCode.INTERNAL_STATE_INVALID)
    return state.intent


def _require_buy_reference(state: _RoundTripState) -> ProtocolQuote:
    # Execute the require buy reference workflow in explicit, reviewable steps.
    if state.buy_reference is None:
        raise SnipingEngineError(SnipingEngineErrorCode.INTERNAL_STATE_INVALID)
    return state.buy_reference


def _require_buy_network(state: _RoundTripState) -> NetworkCostQuote:
    # Execute the require buy network workflow in explicit, reviewable steps.
    if state.buy_network_cost is None:
        raise SnipingEngineError(SnipingEngineErrorCode.INTERNAL_STATE_INVALID)
    return state.buy_network_cost


def _require_account_reservation(state: _RoundTripState) -> AccountReservationPlan:
    """Return the immutable plan accepted with this buy order."""

    if state.account_reservation is None:
        raise SnipingEngineError(SnipingEngineErrorCode.INTERNAL_STATE_INVALID)
    return state.account_reservation


def _require_sell_reference(state: _RoundTripState) -> ProtocolQuote:
    # Execute the require sell reference workflow in explicit, reviewable steps.
    if state.sell_reference is None:
        raise SnipingEngineError(SnipingEngineErrorCode.INTERNAL_STATE_INVALID)
    return state.sell_reference


def _require_sell_network(state: _RoundTripState) -> NetworkCostQuote:
    # Execute the require sell network workflow in explicit, reviewable steps.
    if state.sell_network_cost is None:
        raise SnipingEngineError(SnipingEngineErrorCode.INTERNAL_STATE_INVALID)
    return state.sell_network_cost


def _validate_buy_quote(intent: RoundTripIntent, quote: ProtocolQuote) -> None:
    # Execute the validate buy quote workflow in explicit, reviewable steps.
    if (
        quote.side is not ProtocolQuoteSide.BUY
        or quote.input_asset_id != intent.quote_asset_id
        or quote.output_asset_id != intent.asset_id
        or quote.amount_in_atomic > intent.gross_buy_budget_atomic
        # Evaluate the complete validate buy quote side, buy and input asset id condition
        # before guarded effects.
    ):
        raise SnipingEngineError(SnipingEngineErrorCode.QUOTE_CONTRACT_MISMATCH)


def _validate_sell_quote(
    intent: RoundTripIntent,
    tokens_atomic: int,
    # Keep the quote input explicit in the validate sell quote contract.
    quote: ProtocolQuote,
) -> None:
    # Validate the common quote shape before interpreting mode-specific funding.
    liquidity = quote.liquidity_evidence
    if (
        quote.side is not ProtocolQuoteSide.SELL
        or quote.input_asset_id != intent.asset_id
        or quote.output_asset_id != intent.quote_asset_id
        # The fill must sell the exact acquired position and carry matched evidence.
        or quote.amount_in_atomic != tokens_atomic
        or liquidity is None
        or liquidity.policy_id != liquidity_policy_id_for_execution_mode(intent.execution_mode)
        # Evaluate the complete validate sell quote side, sell and input asset id condition
        # before guarded effects.
    ):
        raise SnipingEngineError(SnipingEngineErrorCode.QUOTE_CONTRACT_MISMATCH)

    # Strict replay can settle only from the observed venue reserve.
    if intent.execution_mode is ExecutionMode.EXOGENOUS_REPLAY:
        if (
            liquidity.synthetic_shortfall_atomic
            or liquidity.synthetic_source_account_id is not None
        ):
            # Reject before a synthetic EXTERNAL posting can mutate the portfolio.
            raise SnipingEngineError(SnipingEngineErrorCode.QUOTE_CONTRACT_MISMATCH)
        return

    # Virtual settlement must report the exact shortage and source it iff positive.
    expected_shortfall = max(
        0,
        liquidity.required_output_atomic - liquidity.observed_available_output_atomic,
    )
    # Zero shortage has no funding account; positive shortage has one exact source.
    expected_source = None
    if expected_shortfall > 0:
        # Network and venue prevent synthetic liquidity from crossing pool identities.
        expected_source = synthetic_liquidity_account_id(
            protocol_namespace="pumpfun",
            network_id=intent.target_position.network_id,
            venue_id=intent.venue_id,
        )
    # Reject plugin-provided arithmetic or account routing before ledger mutation.
    if (
        intent.execution_mode is not ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT
        or liquidity.synthetic_shortfall_atomic != expected_shortfall
        or liquidity.synthetic_source_account_id != expected_source
    ):
        raise SnipingEngineError(SnipingEngineErrorCode.QUOTE_CONTRACT_MISMATCH)


def _minimum_output_atomic(reference: int, slippage_bps: int) -> int:
    return reference * (10_000 - slippage_bps) // 10_000


def _apply_transaction(
    portfolio: PortfolioState,
    recorder: _Recorder,
    # Keep the transaction input explicit in the apply transaction contract.
    transaction: LedgerTransaction,
) -> None:
    # Execute the apply transaction workflow in explicit, reviewable steps.
    try:
        candidate = portfolio.preview(transaction)
    except PortfolioInvariantError as error:
        raise SnipingEngineError(SnipingEngineErrorCode.PORTFOLIO_INVARIANT) from error
    portfolio.commit(candidate)
    # Invoke append_ledger for transaction as a visible apply transaction step.
    recorder.append_ledger(transaction)


def _apply_transaction_with_accounts(
    portfolio: PortfolioState,
    recorder: _Recorder,
    transaction: LedgerTransaction,
    *,
    accounts: WalletProvisioningReducer,
    transition: AccountProvisioningTransition,
) -> None:
    """Commit one validated portfolio/account candidate as one engine operation."""

    try:
        candidate = portfolio.preview(transaction)
    except PortfolioInvariantError as error:
        raise SnipingEngineError(SnipingEngineErrorCode.PORTFOLIO_INVARIANT) from error
    portfolio.commit(candidate)
    accounts.commit(transition)
    recorder.append_ledger(transaction)


def _ledger_transaction(
    roundtrip_id: ContentDigest,
    *,
    boundary: int,
    # Keep the reason input explicit in the ledger transaction contract.
    reason: str,
    postings: list[Posting],
) -> LedgerTransaction:
    # Execute the ledger transaction workflow in explicit, reviewable steps.
    return LedgerTransaction(
        transaction_id=domain_digest(
            "backtest.sniping-ledger-transaction.v2",
            {
                "boundary_ordinal": boundary,
                # Keep reason named so the reason and v2 payload passed to domain_digest
                # remains self-describing within ledger transaction.
                "reason": reason,
                "roundtrip_id": roundtrip_id.hex,
            },
        ),
        correlation_kind=LedgerCorrelationKind.ROUNDTRIP,
        # Pass correlation id explicitly so LedgerTransaction receives a reviewable v2 and
        # boundary ordinal input in ledger transaction.
        correlation_id=roundtrip_id,
        boundary_ordinal=boundary,
        postings=tuple(postings),
        reason=reason,
    )


# Define posting as one focused operation with an explicit boundary.
def _posting(
    postings: list[Posting],
    account_id: AccountId,
    kind: AccountKind,
    asset_id: AssetId,
    # Keep the amount input explicit in the posting contract.
    amount: int,
) -> None:
    # Execute the posting workflow in explicit, reviewable steps.
    if amount:
        postings.append(Posting(LedgerAccount(account_id, kind), asset_id, amount))


_AssetAmounts = tuple[tuple[AssetId, int], ...]


def _canonical_asset_amounts(*components: tuple[AssetId, int]) -> _AssetAmounts:
    # Execute the canonical asset amounts workflow in explicit, reviewable steps.
    totals: dict[AssetId, int] = {}
    for asset_id, amount in components:
        # Process components inside the bounded canonical asset amounts loop.
        if amount:
            totals[asset_id] = totals.get(asset_id, 0) + amount
    return tuple(sorted(totals.items(), key=lambda item: item[0].value))


def _buy_reservation(
    intent: RoundTripIntent,
    # Keep the network input explicit in the buy reservation contract.
    network: NetworkCostQuote,
    account_plan: AccountReservationPlan,
) -> _AssetAmounts:
    # Execute the buy reservation workflow in explicit, reviewable steps.
    return _canonical_asset_amounts(
        (intent.quote_asset_id, intent.gross_buy_budget_atomic),
        (network.fee_asset_id, network.transaction_fee_atomic),
        *account_plan.reserved_asset_amounts,
    )


def _sell_reservation(
    intent: RoundTripIntent,
    # Close the sell reservation signature after its explicit inputs.
    *,
    tokens_atomic: int,
    network: NetworkCostQuote,
) -> _AssetAmounts:
    # Execute the sell reservation workflow in explicit, reviewable steps.
    return _canonical_asset_amounts(
        (intent.asset_id, tokens_atomic),
        (network.fee_asset_id, network.transaction_fee_atomic),
    )


def _has_available(portfolio: PortfolioState, amounts: _AssetAmounts) -> bool:
    # Return the completed has available result without a hidden fallback.
    return all(portfolio.available(asset_id) >= amount for asset_id, amount in amounts)


def _asset_amounts_document(amounts: _AssetAmounts) -> tuple[dict[str, object], ...]:
    # Execute the asset amounts document workflow in explicit, reviewable steps.
    return tuple(
        {"amount_atomic": amount, "asset_id": asset_id.value} for asset_id, amount in amounts
    )


def _amount_if_asset(asset_id: AssetId, expected: AssetId, amount: int) -> int:
    return amount if asset_id == expected else 0


def _asset_amount(amounts: _AssetAmounts, expected: AssetId) -> int:
    """Read one explicit asset amount without assuming quote/native equivalence."""

    return dict(amounts).get(expected, 0)


# Define reserve amounts as one focused operation with an explicit boundary.
def _reserve_amounts(postings: list[Posting], amounts: _AssetAmounts) -> None:
    # Execute the reserve amounts workflow in explicit, reviewable steps.
    for asset_id, amount in amounts:
        # Process amounts inside the bounded reserve amounts loop.
        _posting(
            postings,
            available_account_id(asset_id),
            AccountKind.PORTFOLIO_AVAILABLE,
            asset_id,
            # Pass amount explicitly so _posting receives a reviewable portfolio available
            # and available account id input in reserve amounts.
            -amount,
        )
        _posting(
            postings,
            reserved_account_id(asset_id),
            # Pass account kind explicitly so _posting receives a reviewable portfolio
            # reserved and reserved account id input in reserve amounts.
            AccountKind.PORTFOLIO_RESERVED,
            asset_id,
            amount,
        )


def _reserve_buy(
    # Keep the intent input explicit in the reserve buy contract.
    intent: RoundTripIntent,
    network: NetworkCostQuote,
    account_plan: AccountReservationPlan,
) -> LedgerTransaction:
    # Execute the reserve buy workflow in explicit, reviewable steps.
    postings: list[Posting] = []
    _reserve_amounts(postings, _buy_reservation(intent, network, account_plan))
    return _ledger_transaction(
        intent.roundtrip_id,
        boundary=intent.created_boundary_ordinal,
        # Pass reason explicitly so _ledger_transaction receives a reviewable sniping buy
        # reservation and roundtrip id input in reserve buy.
        reason="SNIPING_BUY_RESERVATION",
        postings=postings,
    )


def _reserve_sell(
    intent: RoundTripIntent,
    # Close the reserve sell signature after its explicit inputs.
    *,
    tokens_atomic: int,
    network: NetworkCostQuote,
    boundary: int,
) -> LedgerTransaction:
    # Execute the reserve sell workflow in explicit, reviewable steps.
    postings: list[Posting] = []
    _reserve_amounts(
        postings,
        _sell_reservation(intent, tokens_atomic=tokens_atomic, network=network),
    )
    # Return the completed reserve sell result without a hidden fallback.
    return _ledger_transaction(
        intent.roundtrip_id,
        boundary=boundary,
        reason="SNIPING_SELL_RESERVATION",
        postings=postings,
        # Complete _ledger_transaction only after its sniping sell reservation and roundtrip
        # id inputs are visible in reserve sell.
    )


def _settle_reserved_amounts(
    postings: list[Posting],
    *,
    reserved: _AssetAmounts,
    # Keep the consumed input explicit in the settle reserved amounts contract.
    consumed: _AssetAmounts,
) -> None:
    # Execute the settle reserved amounts workflow in explicit, reviewable steps.
    consumed_by_asset = dict(consumed)
    reserved_assets = {asset_id for asset_id, _ in reserved}
    if any(asset_id not in reserved_assets for asset_id in consumed_by_asset):
        raise SnipingEngineError(SnipingEngineErrorCode.PORTFOLIO_INVARIANT)
    for asset_id, reserved_amount in reserved:
        # Process reserved inside the bounded settle reserved amounts loop.
        consumed_amount = consumed_by_asset.get(asset_id, 0)
        if consumed_amount > reserved_amount:
            raise SnipingEngineError(SnipingEngineErrorCode.PORTFOLIO_INVARIANT)
        _posting(
            postings,
            # Pass reserved account id explicitly to _posting for portfolio reserved and
            # reserved account id.
            reserved_account_id(asset_id),
            AccountKind.PORTFOLIO_RESERVED,
            asset_id,
            -reserved_amount,
        )
        # Invoke _posting for portfolio available and available account id as a visible
        # settle reserved amounts step.
        _posting(
            postings,
            available_account_id(asset_id),
            AccountKind.PORTFOLIO_AVAILABLE,
            asset_id,
            # Pass reserved amount explicitly so _posting receives a reviewable portfolio
            # available and available account id input in settle reserved amounts.
            reserved_amount - consumed_amount,
        )


def _failed_buy_settlement(
    intent: RoundTripIntent,
    *,
    # Keep the boundary input explicit in the failed buy settlement contract.
    boundary: int,
    network: NetworkCostQuote,
    account_plan: AccountReservationPlan,
    network_fee_account_id: AccountId,
    reason: str,
) -> LedgerTransaction:
    # Execute the failed buy settlement workflow in explicit, reviewable steps.
    postings: list[Posting] = []
    _settle_reserved_amounts(
        postings,
        reserved=_buy_reservation(intent, network, account_plan),
        consumed=_canonical_asset_amounts(
            # Open the fee asset id and transaction fee atomic payload explicitly for
            # _canonical_asset_amounts within failed buy settlement.
            (network.fee_asset_id, network.transaction_fee_atomic),
        ),
    )
    _posting(
        postings,
        # Pass network fee account id explicitly so _posting receives a reviewable network
        # fee and fee asset id input in failed buy settlement.
        network_fee_account_id,
        AccountKind.NETWORK_FEE,
        network.fee_asset_id,
        network.transaction_fee_atomic,
    )
    # Return the completed failed buy settlement result without a hidden fallback.
    return _ledger_transaction(
        intent.roundtrip_id,
        boundary=boundary,
        reason=f"SNIPING_BUY_FAILED_{reason}",
        postings=postings,
        # Complete _ledger_transaction only after its sniping buy failed and roundtrip id
        # inputs are visible in failed buy settlement.
    )


def _successful_buy_settlement(
    intent: RoundTripIntent,
    *,
    boundary: int,
    # Keep the quote input explicit in the successful buy settlement contract.
    quote: ProtocolQuote,
    network: NetworkCostQuote,
    account_plan: AccountReservationPlan,
    account_transition: AccountProvisioningTransition,
    network_fee_account_id: AccountId,
) -> LedgerTransaction:
    # Execute the successful buy settlement workflow in explicit, reviewable steps.
    postings: list[Posting] = []
    paid_accounts = tuple(
        (record.asset_id, record.paid_atomic)
        for record in account_transition.records
        if record.paid_atomic
    )
    _settle_reserved_amounts(
        postings,
        reserved=_buy_reservation(intent, network, account_plan),
        consumed=_canonical_asset_amounts(
            # Open the quote asset id and amount in atomic payload explicitly for
            # _canonical_asset_amounts within successful buy settlement.
            (intent.quote_asset_id, quote.amount_in_atomic),
            (network.fee_asset_id, network.transaction_fee_atomic),
            *paid_accounts,
        ),
    )
    venue = AccountId(f"venue:{intent.venue_id.value}")
    _posting(
        # Pass postings explicitly so _posting receives a reviewable venue and quote asset
        # id input in successful buy settlement.
        postings,
        venue,
        AccountKind.VENUE,
        intent.quote_asset_id,
        quote.venue_input_atomic,
        # Complete _posting only after its venue and quote asset id inputs are visible in
        # successful buy settlement.
    )
    _posting(
        postings,
        quote.protocol_fee_account_id,
        AccountKind.PROTOCOL_FEE,
        # Pass intent explicitly so _posting receives a reviewable protocol fee account id
        # and protocol fee input in successful buy settlement.
        intent.quote_asset_id,
        quote.protocol_fee_atomic,
    )
    _posting(
        postings,
        # Pass quote explicitly so _posting receives a reviewable creator fee account id
        # and creator fee input in successful buy settlement.
        quote.creator_fee_account_id,
        AccountKind.CREATOR_FEE,
        intent.quote_asset_id,
        quote.creator_fee_atomic,
    )
    # Invoke _posting for network fee and fee asset id as a visible successful buy
    # settlement step.
    _posting(
        postings,
        network_fee_account_id,
        AccountKind.NETWORK_FEE,
        network.fee_asset_id,
        # Pass network explicitly so _posting receives a reviewable network fee and fee
        # asset id input in successful buy settlement.
        network.transaction_fee_atomic,
    )
    for record in account_transition.records:
        # Only the landing that actually creates an account emits its locked posting.
        _posting(
            postings,
            _locked_deposit_account_id(record),
            AccountKind.PORTFOLIO_LOCKED,
            record.asset_id,
            record.paid_atomic,
        )
    _posting(
        postings,
        venue,
        AccountKind.VENUE,
        # Pass intent explicitly so _posting receives a reviewable venue and asset id
        # input in successful buy settlement.
        intent.asset_id,
        -quote.amount_out_atomic,
    )
    _posting(
        postings,
        # Pass available account id explicitly to _posting for asset id and portfolio
        # available.
        available_account_id(intent.asset_id),
        AccountKind.PORTFOLIO_AVAILABLE,
        intent.asset_id,
        quote.amount_out_atomic,
    )
    # Invoke _cashback_postings for postings and intent as a visible successful buy
    # settlement step.
    _cashback_postings(postings, intent, quote)
    return _ledger_transaction(
        intent.roundtrip_id,
        boundary=boundary,
        reason="SNIPING_BUY_FILLED",
        # Pass postings explicitly so _ledger_transaction receives a reviewable sniping
        # buy filled and roundtrip id input in successful buy settlement.
        postings=postings,
    )


def _failed_sell_settlement(
    intent: RoundTripIntent,
    *,
    # Keep the boundary input explicit in the failed sell settlement contract.
    boundary: int,
    tokens_atomic: int,
    network: NetworkCostQuote,
    network_fee_account_id: AccountId,
    reason: str,
    # Keep the ledger transaction input explicit in the failed sell settlement contract.
) -> LedgerTransaction:
    # Execute the failed sell settlement workflow in explicit, reviewable steps.
    postings: list[Posting] = []
    _settle_reserved_amounts(
        postings,
        reserved=_sell_reservation(intent, tokens_atomic=tokens_atomic, network=network),
        consumed=_canonical_asset_amounts(
            # Open the fee asset id and transaction fee atomic payload explicitly for
            # _canonical_asset_amounts within failed sell settlement.
            (network.fee_asset_id, network.transaction_fee_atomic),
        ),
    )
    _posting(
        postings,
        # Pass network fee account id explicitly so _posting receives a reviewable network
        # fee and fee asset id input in failed sell settlement.
        network_fee_account_id,
        AccountKind.NETWORK_FEE,
        network.fee_asset_id,
        network.transaction_fee_atomic,
    )
    # Return the completed failed sell settlement result without a hidden fallback.
    return _ledger_transaction(
        intent.roundtrip_id,
        boundary=boundary,
        reason=f"SNIPING_SELL_FAILED_{reason}",
        postings=postings,
        # Complete _ledger_transaction only after its sniping sell failed and roundtrip id
        # inputs are visible in failed sell settlement.
    )


def _successful_sell_settlement(
    intent: RoundTripIntent,
    *,
    boundary: int,
    # Keep the quote input explicit in the successful sell settlement contract.
    quote: ProtocolQuote,
    network: NetworkCostQuote,
    tokens_atomic: int,
    account_transition: AccountProvisioningTransition,
    # Keep the network fee account id input explicit in the successful sell settlement
    # contract.
    network_fee_account_id: AccountId,
) -> LedgerTransaction:
    # Execute the successful sell settlement workflow in explicit, reviewable steps.
    postings: list[Posting] = []
    venue = AccountId(f"venue:{intent.venue_id.value}")
    liquidity = quote.liquidity_evidence
    if liquidity is None:
        raise SnipingEngineError(SnipingEngineErrorCode.QUOTE_CONTRACT_MISMATCH)
    venue_funded_atomic = liquidity.required_output_atomic - liquidity.synthetic_shortfall_atomic
    _settle_reserved_amounts(
        postings,
        reserved=_sell_reservation(intent, tokens_atomic=tokens_atomic, network=network),
        # Pass consumed explicitly to _settle_reserved_amounts for asset id and fee asset
        # id.
        consumed=_canonical_asset_amounts(
            (intent.asset_id, tokens_atomic),
            (network.fee_asset_id, network.transaction_fee_atomic),
        ),
    )
    # Invoke _posting for venue and asset id as a visible successful sell settlement step.
    _posting(postings, venue, AccountKind.VENUE, intent.asset_id, tokens_atomic)
    _posting(
        postings,
        network_fee_account_id,
        AccountKind.NETWORK_FEE,
        # Pass network explicitly so _posting receives a reviewable network fee and fee
        # asset id input in successful sell settlement.
        network.fee_asset_id,
        network.transaction_fee_atomic,
    )
    _posting(
        postings,
        # Pass venue explicitly so _posting receives a reviewable venue and quote asset id
        # input in successful sell settlement.
        venue,
        AccountKind.VENUE,
        intent.quote_asset_id,
        -venue_funded_atomic,
    )
    if liquidity.synthetic_shortfall_atomic:
        synthetic_source = liquidity.synthetic_source_account_id
        if synthetic_source is None:  # pragma: no cover - evidence invariant
            raise SnipingEngineError(SnipingEngineErrorCode.QUOTE_CONTRACT_MISMATCH)
        _posting(
            postings,
            synthetic_source,
            AccountKind.EXTERNAL,
            intent.quote_asset_id,
            -liquidity.synthetic_shortfall_atomic,
        )
    # Invoke _posting for quote asset id and portfolio available as a visible successful
    # sell settlement step.
    _posting(
        postings,
        available_account_id(intent.quote_asset_id),
        AccountKind.PORTFOLIO_AVAILABLE,
        intent.quote_asset_id,
        # Pass quote explicitly so _posting receives a reviewable quote asset id and
        # portfolio available input in successful sell settlement.
        quote.amount_out_atomic,
    )
    _posting(
        postings,
        quote.protocol_fee_account_id,
        # Pass account kind explicitly so _posting receives a reviewable protocol fee
        # account id and protocol fee input in successful sell settlement.
        AccountKind.PROTOCOL_FEE,
        intent.quote_asset_id,
        quote.protocol_fee_atomic,
    )
    _posting(
        # Pass postings explicitly so _posting receives a reviewable creator fee account
        # id and creator fee input in successful sell settlement.
        postings,
        quote.creator_fee_account_id,
        AccountKind.CREATOR_FEE,
        intent.quote_asset_id,
        quote.creator_fee_atomic,
        # Complete _posting only after its creator fee account id and creator fee inputs are
        # visible in successful sell settlement.
    )
    for record in account_transition.records:
        # Successful sell closes only components whose reducer produced a refund.
        _posting(
            postings,
            _locked_deposit_account_id(record),
            AccountKind.PORTFOLIO_LOCKED,
            record.asset_id,
            -record.refunded_atomic,
        )
        _posting(
            postings,
            available_account_id(record.asset_id),
            AccountKind.PORTFOLIO_AVAILABLE,
            record.asset_id,
            record.refunded_atomic,
        )
    # Invoke _cashback_postings for postings and intent as a visible successful sell
    # settlement step.
    _cashback_postings(postings, intent, quote)
    return _ledger_transaction(
        intent.roundtrip_id,
        boundary=boundary,
        reason="SNIPING_SELL_FILLED_ACCOUNT_CLOSED",
        # Pass postings explicitly so _ledger_transaction receives a reviewable sniping
        # sell filled account closed and roundtrip id input in successful sell settlement.
        postings=postings,
    )


def _cashback_postings(
    postings: list[Posting],
    intent: RoundTripIntent,
    # Keep the quote input explicit in the cashback postings contract.
    quote: ProtocolQuote,
) -> None:
    # Execute the cashback postings workflow in explicit, reviewable steps.
    _posting(
        postings,
        _cashback_receivable_account_id(intent.roundtrip_id),
        AccountKind.RECEIVABLE,
        intent.quote_asset_id,
        # Pass quote explicitly so _posting receives a reviewable roundtrip id and
        # receivable input in cashback postings.
        quote.cashback_receivable_atomic,
    )
    _posting(
        postings,
        quote.cashback_source_account_id,
        # Pass account kind explicitly so _posting receives a reviewable cashback source
        # account id and external input in cashback postings.
        AccountKind.EXTERNAL,
        intent.quote_asset_id,
        -quote.cashback_receivable_atomic,
    )


def _locked_deposit_account_id(record: AccountComponentRecord) -> AccountId:
    """Use wallet identity for UVA and round-trip identity for each mint ATA."""

    if record.scope is AccountRequirementScope.WALLET:
        owner = "wallet"
    else:
        owner = f"mint:{record.attribution_id.hex}"
    return AccountId(f"portfolio:locked-account-deposit:{owner}:{record.requirement_schema_id}")


def _cashback_receivable_account_id(roundtrip_id: ContentDigest) -> AccountId:
    return AccountId(f"portfolio:receivable:cashback:{roundtrip_id.hex}")


def _fill(
    intent: RoundTripIntent,
    # Close the fill signature after its explicit inputs.
    *,
    side: ProtocolQuoteSide,
    quote: ProtocolQuote,
    boundary: int,
) -> Fill:
    # Execute the fill workflow in explicit, reviewable steps.
    order_id = OrderId(
        domain_digest(
            "backtest.sniping-order.v1",
            {"roundtrip_id": intent.roundtrip_id.hex, "side": side.value},
        ).hex
        # Complete OrderId only after its v1 and roundtrip id inputs are visible in fill.
    )
    return Fill(
        order_id=order_id,
        pool_id=PoolId(intent.venue_id.value),
        sold_asset_id=quote.input_asset_id,
        # Pass bought asset id explicitly so Fill receives a reviewable value and venue id
        # input in fill.
        bought_asset_id=quote.output_asset_id,
        amount_in_atomic=quote.amount_in_atomic,
        amount_out_atomic=quote.amount_out_atomic,
        fee_amount_atomic=quote.protocol_fee_atomic + quote.creator_fee_atomic,
        boundary_ordinal=boundary,
        # Complete Fill only after its value and venue id inputs are visible in fill.
    )


def _buy_leg(state: _RoundTripState) -> RoundTripLegRecord | None:
    # Execute the buy leg workflow in explicit, reviewable steps.
    intent = state.intent
    reference = state.buy_reference
    if intent is None or reference is None:
        return None
    landing = state.buy_landing
    # Assemble network once so the buy leg workflow shares one value.
    network = state.buy_network_cost
    landed = state.buy_landing_position is not None
    charged_network = network if landed and network is not None else None
    filled = state.acquired_token_amount_atomic > 0
    return RoundTripLegRecord(
        # Pass side explicitly so RoundTripLegRecord receives a reviewable buy and target
        # position input in buy leg.
        side=RoundTripLegSide.BUY,
        decision_position=intent.target_position,
        landing_position=state.buy_landing_position,
        amount_in_atomic=(None if landing is None or not filled else landing.amount_in_atomic),
        reference_out_atomic=reference.amount_out_atomic,
        # Pass landing out atomic explicitly so RoundTripLegRecord receives a reviewable
        # buy and target position input in buy leg.
        landing_out_atomic=None if landing is None else landing.amount_out_atomic,
        minimum_out_atomic=state.buy_minimum_out_atomic,
        signed_slippage_atomic=(
            None if landing is None else landing.amount_out_atomic - reference.amount_out_atomic
        ),
        # Pass protocol fee atomic explicitly so RoundTripLegRecord receives a reviewable
        # buy and target position input in buy leg.
        protocol_fee_atomic=(0 if landing is None or not filled else landing.protocol_fee_atomic),
        creator_fee_atomic=(0 if landing is None or not filled else landing.creator_fee_atomic),
        network_base_fee_atomic=(0 if charged_network is None else charged_network.base_fee_atomic),
        network_priority_fee_atomic=(
            0 if charged_network is None else charged_network.priority_fee_atomic
            # Complete RoundTripLegRecord only after its buy and target position inputs are
            # visible in buy leg.
        ),
        failure_code=state.buy_failure_code,
    )


def _sell_leg(state: _RoundTripState) -> RoundTripLegRecord | None:
    # Execute the sell leg workflow in explicit, reviewable steps.
    reference = state.sell_reference
    decision = state.sell_decision_position
    if reference is None or decision is None:
        return None
    landing = state.sell_landing
    # Assemble network once so the sell leg workflow shares one value.
    network = state.sell_network_cost
    landed = state.sell_landing_position is not None
    charged_network = network if landed and network is not None else None
    filled = state.status is RoundTripStatus.CLOSED
    return RoundTripLegRecord(
        # Pass side explicitly so RoundTripLegRecord receives a reviewable sell and sell
        # landing position input in sell leg.
        side=RoundTripLegSide.SELL,
        decision_position=decision,
        landing_position=state.sell_landing_position,
        amount_in_atomic=(state.acquired_token_amount_atomic if filled else None),
        reference_out_atomic=reference.amount_out_atomic,
        # Pass landing out atomic explicitly so RoundTripLegRecord receives a reviewable
        # sell and sell landing position input in sell leg.
        landing_out_atomic=None if landing is None else landing.amount_out_atomic,
        minimum_out_atomic=state.sell_minimum_out_atomic,
        signed_slippage_atomic=(
            None if landing is None else landing.amount_out_atomic - reference.amount_out_atomic
        ),
        # Pass protocol fee atomic explicitly so RoundTripLegRecord receives a reviewable
        # sell and sell landing position input in sell leg.
        protocol_fee_atomic=(0 if landing is None or not filled else landing.protocol_fee_atomic),
        creator_fee_atomic=(0 if landing is None or not filled else landing.creator_fee_atomic),
        network_base_fee_atomic=(0 if charged_network is None else charged_network.base_fee_atomic),
        network_priority_fee_atomic=(
            0 if charged_network is None else charged_network.priority_fee_atomic
            # Complete RoundTripLegRecord only after its sell and sell landing position inputs
            # are visible in sell leg.
        ),
        failure_code=state.sell_failure_code,
    )


def _quote_liquidity_record(quote: ProtocolQuote) -> QuoteLiquidityEvidenceRecord:
    """Project exact protocol quote evidence into the versioned result row."""

    evidence = quote.liquidity_evidence
    if evidence is None:
        raise SnipingEngineError(SnipingEngineErrorCode.QUOTE_CONTRACT_MISMATCH)
    return QuoteLiquidityEvidenceRecord(
        policy_id=evidence.policy_id,
        asset_id=evidence.asset_id,
        required_output_atomic=evidence.required_output_atomic,
        observed_available_output_atomic=evidence.observed_available_output_atomic,
        synthetic_shortfall_atomic=evidence.synthetic_shortfall_atomic,
    )


def _optional_quote_liquidity_record(
    quote: ProtocolQuote | None,
) -> QuoteLiquidityEvidenceRecord | None:
    return None if quote is None else _quote_liquidity_record(quote)


def _settled_synthetic_funded_atomic(state: _RoundTripState) -> int:
    if state.status is not RoundTripStatus.CLOSED or state.sell_landing is None:
        return 0
    evidence = state.sell_landing.liquidity_evidence
    if evidence is None:
        raise SnipingEngineError(SnipingEngineErrorCode.QUOTE_CONTRACT_MISMATCH)
    return evidence.synthetic_shortfall_atomic


def _settled_venue_funded_atomic(state: _RoundTripState) -> int:
    if state.status is not RoundTripStatus.CLOSED or state.sell_landing is None:
        return 0
    evidence = state.sell_landing.liquidity_evidence
    if evidence is None:
        raise SnipingEngineError(SnipingEngineErrorCode.QUOTE_CONTRACT_MISMATCH)
    return evidence.required_output_atomic - evidence.synthetic_shortfall_atomic


__all__ = [
    "SNIPING_REFERENCE_BACKEND_NAME",
    # Keep the sniping reference engine bundle id component named inside the all contract.
    "SNIPING_REFERENCE_ENGINE_BUNDLE_ID",
    "NullSnipingRunEventSink",
    "SnipingEngineError",
    "SnipingEngineErrorCode",
    "SnipingReferenceEngine",
    # Keep the sniping run config component named inside the all contract.
    "SnipingRunConfig",
    "SnipingRunSummary",
]
