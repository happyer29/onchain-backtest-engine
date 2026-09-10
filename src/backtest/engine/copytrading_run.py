"""Canonical copy-run recording around the readable sequential replay oracle."""

from collections.abc import Callable
from dataclasses import asdict, dataclass, fields
from typing import Protocol

# This layer receives only verified local input and core-owned runtime contracts.
from backtest.domain.execution import ExecutionMode, Fill
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import AssetId, BundleId, ContentDigest
from backtest.domain.ledger import LedgerTransaction
from backtest.domain.time import BlockRange

# Canonical stream hashing consumes committed execution records only.
from backtest.engine.audit import CanonicalStreamHasher, fill_document, ledger_document

# Per-position projections are bounded and streamed independently of the root summary.
from backtest.engine.copytrading import CopyBuyReferenceEngine, CopyReplayLimits
from backtest.engine.copytrading_contracts import CopyBuyProtocolRuntime, CopyBuyStrategy
from backtest.engine.copytrading_execution import (
    CopyAttemptStatus,
    CopyExecutionPosition,
    # The executor owns bounded per-position attempts and account transitions.
    CopyOrderExecutor,
)
from backtest.engine.copytrading_results import (
    COPY_AUDIT_STREAM,
    COPY_BALANCE_STREAM,
    # Ledger and fill digests allow independent verification of financial publication.
    COPY_FILL_STREAM,
    COPY_LEDGER_STREAM,
    # Distinct domains preserve the interpretation of old Sniping result bytes.
    COPY_POSITION_STREAM,
    CopyPositionRecord,
    freeze_copy_position,
)
from backtest.engine.copytrading_state import CopyPositionStatus

# Portfolio accounting and the transaction clock remain core-owned services.
from backtest.engine.portfolio import PortfolioState
from backtest.engine.replay import HistoricalEventSource
from backtest.engine.sniping_contracts import SnipingNetworkCostModel
from backtest.engine.transaction_clock import CompactTransactionClock
from backtest.engine.wallet_accounts import WalletProvisioningReducer, WalletProvisioningState


class CopyRunSink(Protocol):
    """Buffered output is replaceable; replay knows neither Parquet nor publication."""

    def append_audit(self, record: dict[str, object]) -> None: ...
    def append_ledger(self, transaction: LedgerTransaction) -> None: ...
    def append_fill(self, fill: Fill) -> None: ...
    def append_copy_position(self, record: CopyPositionRecord) -> None: ...


@dataclass(frozen=True, slots=True)
class CopyFinancialTotals:
    """Integer row aggregates; nullable full economics exposes unavailable open valuation."""

    position_count: int = 0
    filled_buy_count: int = 0
    rejected_buy_count: int = 0
    failed_buy_count: int = 0
    closed_position_count: int = 0
    # Exhausted positions retain inventory after exactly four unsuccessful sales.
    exhausted_position_count: int = 0
    sell_attempt_count: int = 0
    rejected_sell_count: int = 0
    failed_sell_count: int = 0
    unvalued_open_position_count: int = 0
    # Cashflow is ledger-derived; realized round trips exclude open inventory.
    quote_cashflow_atomic: int = 0
    realized_cash_pnl_atomic: int = 0
    valued_economic_pnl_subtotal_atomic: int = 0
    cashback_receivable_atomic: int = 0
    protocol_fee_paid_atomic: int = 0
    # Landed failures pay network fees but none of the Pump components.
    creator_fee_paid_atomic: int = 0
    network_base_fee_paid_atomic: int = 0
    network_priority_fee_paid_atomic: int = 0
    account_deposit_paid_atomic: int = 0
    account_deposit_refunded_atomic: int = 0
    # Synthetic funds refer exclusively to successful settled output.
    account_deposit_locked_atomic: int = 0
    gross_sell_settlement_atomic: int = 0
    venue_funded_sell_atomic: int = 0
    synthetic_funded_sell_atomic: int = 0

    def __post_init__(self) -> None:
        """Counts and money obey conservation before a summary may be committed."""
        signed = {
            "quote_cashflow_atomic",
            "realized_cash_pnl_atomic",
            "valued_economic_pnl_subtotal_atomic",
        }
        # Booleans and negative counts must not pass as valid aggregate integers.
        for field in fields(self):
            value = getattr(self, field.name)
            if type(value) is not int or (field.name not in signed and value < 0):
                raise ValueError("invalid copy summary integer")
        # Every consumed mint has exactly one terminal buy outcome.
        if (
            self.position_count
            != self.filled_buy_count + self.rejected_buy_count + self.failed_buy_count
        ):
            raise ValueError("copy summary buy counts do not reconcile")
        # Every filled buy must end either closed or explicitly exhausted.
        if self.filled_buy_count != self.closed_position_count + self.exhausted_position_count:
            raise ValueError("copy summary position counts do not reconcile")
        # Four attempts are a hard ceiling, with no silent tail truncation.
        if (
            self.sell_attempt_count
            != self.closed_position_count + self.rejected_sell_count + self.failed_sell_count
        ):
            raise ValueError("copy summary sell counts do not reconcile")
        # Exhaustion requires all four attempts; successful exits may stop earlier.
        if (
            not 4 * self.exhausted_position_count
            <= self.sell_attempt_count
            <= 4 * self.filled_buy_count
        ):
            # Out-of-range attempts indicate a truncated or inconsistent result.
            raise ValueError("copy summary retry count is invalid")
        # Actual synthetic plus observed funding must conserve gross sell proceeds.
        if (
            self.gross_sell_settlement_atomic
            != self.venue_funded_sell_atomic + self.synthetic_funded_sell_atomic
        ):
            raise ValueError("copy summary sell funding does not reconcile")
        # Only exhausted inventory can lack a terminal liquidation valuation.
        if self.unvalued_open_position_count > self.exhausted_position_count:
            raise ValueError("copy summary has more unvalued than open positions")

    @property
    def economic_pnl_atomic(self) -> int | None:
        """A known subtotal cannot masquerade as a complete portfolio valuation."""
        return (
            None if self.unvalued_open_position_count else self.valued_economic_pnl_subtotal_atomic
        )

    def document(self) -> dict[str, object]:
        """Dataclass fields form a closed scalar schema outside the replay hot loop."""
        result = asdict(self)
        result["economic_pnl_atomic"] = self.economic_pnl_atomic
        result["valuation_status"] = "PARTIAL" if self.unvalued_open_position_count else "COMPLETE"
        return result


class CopyTotalsAccumulator:
    """Fixed-size aggregate state; position rows remain in the external sink."""

    def __init__(self) -> None:
        self._values = {field.name: 0 for field in fields(CopyFinancialTotals)}

    def append(self, record: CopyPositionRecord) -> None:
        """Aggregate immutable execution outcomes, not hypothetical quote amounts."""
        values = self._values
        values["position_count"] += 1
        buy = record.attempts[0]
        values[f"{buy.status.value.lower()}_buy_count"] += 1
        # Open cash expenditure stays separate from realized closed-position PnL.
        values["closed_position_count"] += record.status is CopyPositionStatus.CLOSED
        values["exhausted_position_count"] += record.status is CopyPositionStatus.EXHAUSTED
        values["quote_cashflow_atomic"] += record.quote_cashflow_atomic
        values["realized_cash_pnl_atomic"] += record.realized_cash_pnl_atomic or 0
        values["cashback_receivable_atomic"] += record.cashback_receivable_atomic
        # Unknown valuation contributes no invented zero to full economic PnL.
        values["unvalued_open_position_count"] += record.economic_pnl_atomic is None
        values["valued_economic_pnl_subtotal_atomic"] += record.economic_pnl_atomic or 0
        # Refundable deposits are aggregated separately from wallet cash and cashback.
        for component in record.account_components:
            values["account_deposit_paid_atomic"] += component.paid_atomic
            values["account_deposit_refunded_atomic"] += component.refunded_atomic
            values["account_deposit_locked_atomic"] += component.locked_delta_atomic
        # Summing only actual fills prevents failed quotes from accruing Pump fees/cashback.
        for attempt in record.attempts:
            values["network_base_fee_paid_atomic"] += attempt.network_base_fee_paid_atomic
            values["network_priority_fee_paid_atomic"] += attempt.network_priority_fee_paid_atomic
            if attempt.number:
                values["sell_attempt_count"] += 1
                # An unsuccessful attempt contributes to its exact rejection or landed-failure
                # count.
                if attempt.status is not CopyAttemptStatus.FILLED:
                    # Filled sell count is already represented by full position closure.
                    values[f"{attempt.status.value.lower()}_sell_count"] += 1
            quote = attempt.actual_quote
            if quote is None:
                continue
            # Protocol components accrue solely from successful actual fills.
            values["protocol_fee_paid_atomic"] += quote.protocol_fee_atomic
            values["creator_fee_paid_atomic"] += quote.creator_fee_atomic
            # Potential reference/MTM shortfalls never enter the settled funding totals.
            if attempt.number and quote.liquidity_evidence is not None:
                synthetic = quote.liquidity_evidence.synthetic_shortfall_atomic
                values["gross_sell_settlement_atomic"] += quote.venue_output_atomic
                values["synthetic_funded_sell_atomic"] += synthetic
                values["venue_funded_sell_atomic"] += quote.venue_output_atomic - synthetic

    def finish(self) -> CopyFinancialTotals:
        """Validate all aggregate relationships once every terminal row has arrived."""
        return CopyFinancialTotals(**self._values)


@dataclass(frozen=True, slots=True)
class CopyRunConfig:
    """Exact engine identities and initial assets; physical reader settings stay outside."""

    quote_asset_id: AssetId
    initial_quote_balance_atomic: int
    execution_mode: ExecutionMode
    engine_bundle_id: BundleId
    strategy_bundle_id: BundleId
    # Concrete implementations are supplied through core-owned protocols.
    protocol_bundle_id: BundleId
    network_cost_bundle_id: BundleId
    initial_accounts: WalletProvisioningState
    limits: CopyReplayLimits
    semantic_config_digest: ContentDigest


@dataclass(frozen=True, slots=True)
class CopyRunSummary:
    """Bounded summary plus in-memory balances consumed by an external table writer."""

    result_hash: ContentDigest
    dataset_logical_content_hash: ContentDigest
    replay_semantics_id: ContentDigest
    config: CopyRunConfig
    totals: CopyFinancialTotals
    # Each independently framed stream is deterministic across physical input formats.
    audit_hash: ContentDigest
    ledger_hash: ContentDigest
    fill_hash: ContentDigest
    roundtrip_digest: ContentDigest
    final_balances_digest: ContentDigest
    # These counts do not require retaining historical per-event result objects.
    historical_event_count: int
    historical_group_count: int
    delivered_event_count: int
    ledger_transaction_count: int
    fill_count: int
    # Balances are passed to the external writer, never embedded into an unbounded root.
    final_balances: tuple[tuple[str, str, str, int], ...]


class _Recorder:
    """Hash and forward only dynamic execution records and final position rows."""

    def __init__(self, sink: CopyRunSink | None) -> None:
        self.sink = sink
        self.audit = CanonicalStreamHasher(COPY_AUDIT_STREAM)
        self.ledger = CanonicalStreamHasher(COPY_LEDGER_STREAM)
        self.fills = CanonicalStreamHasher(COPY_FILL_STREAM)
        # Positions and balances have their own framing and bounded metadata descriptors.
        self.positions = CanonicalStreamHasher(COPY_POSITION_STREAM)
        self.balances = CanonicalStreamHasher(COPY_BALANCE_STREAM)
        self.totals = CopyTotalsAccumulator()

    def append_audit(self, record: dict[str, object]) -> None:
        self.audit.append(record)
        if self.sink is not None:
            self.sink.append_audit(record)

    def append_ledger(self, transaction: LedgerTransaction) -> None:
        self.ledger.append(ledger_document(transaction))
        if self.sink is not None:
            self.sink.append_ledger(transaction)

    def append_fill(self, fill: Fill) -> None:
        self.fills.append(fill_document(fill))
        if self.sink is not None:
            self.sink.append_fill(fill)

    def append_position(self, record: CopyPositionRecord) -> None:
        self.positions.append(record.document())
        self.totals.append(record)
        if self.sink is not None:
            self.sink.append_copy_position(record)


def run_copy_backtest(
    *,
    source: HistoricalEventSource,
    clock: CompactTransactionClock,
    decision_range: BlockRange,
    # The strategy supplies the prepared signer set and canonical integer policy.
    strategy: CopyBuyStrategy,
    # The factory must return a fresh protocol reducer for each independent view.
    protocol_factory: Callable[[], CopyBuyProtocolRuntime],
    network_costs: SnipingNetworkCostModel,
    config: CopyRunConfig,
    sink: CopyRunSink | None = None,
) -> CopyRunSummary:
    """Run exact local history with shared financial reducers and immutable outputs."""
    recorder = _Recorder(sink)
    portfolio = PortfolioState({config.quote_asset_id: config.initial_quote_balance_atomic})
    # Construct one wallet with independent historical and delayed-observation reducers.
    executor = CopyOrderExecutor(
        clock=clock,
        historical=protocol_factory(),
        observed=protocol_factory(),
        # Account state belongs to this single run, not the factory or another attempt.
        network_costs=network_costs,
        portfolio=portfolio,
        accounts=WalletProvisioningReducer(config.initial_accounts),
        append_ledger=recorder.append_ledger,
        append_audit=recorder.append_audit,
        # Fill output is separate from ledger output so both can be reconciled independently.
        append_fill=recorder.append_fill,
    )

    def finish_position(state: CopyExecutionPosition) -> None:
        """Freeze after replay ends, so final valuation uses causal final historical state."""
        recorder.append_position(freeze_copy_position(state, executor))

    # Replay completes every proven settlement path before final row publication.
    counts = CopyBuyReferenceEngine().run(
        source=source,
        decision_range=decision_range,
        strategy=strategy,
        executor=executor,
        # Input validation has its own state and precedes every wallet mutation.
        validation_protocol=protocol_factory(),
        limits=config.limits,
        append_position=finish_position,
    )
    # Final balances come from committed portfolio postings after all notifications.
    balances = portfolio.semantic_balances()
    for row in balances:
        recorder.balances.append(list(row))
    # The root digest includes semantic code/data/config plus canonical output stream hashes.
    totals = recorder.totals.finish()
    identity = {
        "schema": "pumpfun-copy-run-summary/v1",
        "dataset_logical_content_hash": source.logical_content_hash.hex,
        "replay_semantics_id": source.replay_semantics_id.hex,
        # Wallet list/policy identity is carried by each consumed signal and the run spec.
        "engine_bundle_id": config.engine_bundle_id.hex,
        "strategy_bundle_id": config.strategy_bundle_id.hex,
        "protocol_bundle_id": config.protocol_bundle_id.hex,
        "network_cost_bundle_id": config.network_cost_bundle_id.hex,
        "execution_mode": config.execution_mode.value,
        # Empty runs still bind their explicit policy and initial balance.
        "policy": strategy.policy.document(),
        "semantic_config_digest": config.semantic_config_digest.hex,
        "initial_quote_balance_atomic": config.initial_quote_balance_atomic,
        "totals": totals.document(),
        "audit_hash": recorder.audit.digest.hex,
        # Ledger and fill hashes bind actual settlement, including failed transaction costs.
        "ledger_hash": recorder.ledger.digest.hex,
        "fill_hash": recorder.fills.digest.hex,
        # Position and balance streams remain external and independently verifiable.
        "position_digest": recorder.positions.digest.hex,
        "final_balances_digest": recorder.balances.digest.hex,
        "historical_event_count": counts.historical_events,
        "historical_group_count": counts.historical_groups,
    }
    # The summary keeps identities and bounded counters alongside external stream digests.
    return CopyRunSummary(
        domain_digest("backtest.copy-run-result.v1", identity),
        ContentDigest(source.logical_content_hash.hex),
        source.replay_semantics_id,
        # Operational physical settings are intentionally absent from canonical result identity.
        config,
        totals,
        recorder.audit.digest,
        recorder.ledger.digest,
        recorder.fills.digest,
        # Position and balance digests allow verified paging without reading the audit stream.
        recorder.positions.digest,
        recorder.balances.digest,
        counts.historical_events,
        counts.historical_groups,
        counts.observed_events,
        # Output counts describe committed records rather than requested instructions.
        recorder.ledger.count,
        recorder.fills.count,
        balances,
    )
