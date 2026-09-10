"""Immutable copy position results derived from committed execution and ledger state."""

from dataclasses import dataclass

from backtest.domain.account_requirements import AccountComponentRecord
from backtest.domain.chain import ChainPosition
from backtest.domain.copytrading import CopyBuyIntent, CopyExitReason, TokenPrice
from backtest.domain.hashing import domain_digest

# Content and coordinate identities remain typed throughout immutable result validation.
from backtest.domain.identifiers import ContentDigest, NetworkId, OrderId, PositionSchemaId

# Shared quote records retain explicit assets and strict/synthetic funding evidence.
from backtest.domain.roundtrips import MtmStatus
from backtest.engine.copytrading_execution import (
    CopyAttemptStatus,
    CopyExecutionPosition,
    CopyOrderExecutor,
    # Mutable execution state is frozen before crossing the output sink boundary.
)
from backtest.engine.copytrading_state import CopyPositionStatus
from backtest.engine.sniping_contracts import (
    ProtocolExecutionRejected,
    ProtocolQuote,
    # Only protocol execution rejections may make a liquidation quote unavailable.
    ProtocolQuoteSide,
)
from backtest.engine.wallet_accounts import refundable_mint_deposits, run_locked_value

# These domains never reinterpret existing Sniping rows or stream hashes.
COPY_POSITION_SCHEMA = "pumpfun-copy-position/v1"
COPY_POSITION_STREAM = "backtest.copy-position-stream.v1"
COPY_LEDGER_STREAM = "backtest.copy-ledger-stream.v1"
COPY_AUDIT_STREAM = "backtest.copy-audit-stream.v1"
COPY_FILL_STREAM = "backtest.copy-fill-stream.v1"
# Balances have independent framing from positions and monetary audit events.
COPY_BALANCE_STREAM = "backtest.copy-final-balances.v1"


@dataclass(frozen=True, slots=True)
class CopyAttemptRecord:
    """One finalized instruction; quotations are never presented as actual fills."""

    order_id: OrderId
    number: int
    decision: ChainPosition
    expected_landing: ChainPosition
    status: CopyAttemptStatus
    # A rejection has no landing and no paid network fee.
    landed_at: ChainPosition | None
    reference: ProtocolQuote | None
    landing_quote: ProtocolQuote | None
    minimum_out_atomic: int
    failure_code: str | None
    # The fee asset stays explicit even when the quote asset happens to be SOL.
    network_fee_asset_id: str
    network_base_fee_paid_atomic: int
    network_priority_fee_paid_atomic: int

    def __post_init__(self) -> None:
        """Only terminal instructions can enter an immutable position result."""
        amounts = (
            self.minimum_out_atomic,
            self.network_base_fee_paid_atomic,
            self.network_priority_fee_paid_atomic,
        )
        # Reject booleans, floats and negative paid amounts at the immutable record boundary.
        if any(type(value) is not int or value < 0 for value in amounts):
            raise ValueError("copy attempt contains an invalid nonnegative amount")
        # A simulated instruction can land only at a later boundary of the same chain.
        self.decision.require_same_chain(self.expected_landing)
        if self.expected_landing.boundary_ordinal <= self.decision.boundary_ordinal:
            raise ValueError("copy attempt landing is not strictly later")
        if self.landed_at is not None and self.landed_at != self.expected_landing:
            raise ValueError("copy attempt did not land at its exact planned boundary")
        # Neither a boundary nor a fee asset can be inferred from another field.
        if self.decision.event_index is not None or self.expected_landing.event_index is not None:
            raise ValueError("copy order coordinates must be transaction boundaries")
        if (
            not self.network_fee_asset_id
            or self.network_fee_asset_id != self.network_fee_asset_id.strip()
            # Even zero-cost rejections retain the explicit asset used by the network model.
        ):
            raise ValueError("copy attempt is missing its explicit network fee asset")
        # Only terminal attempt outcomes can enter a successful committed result.
        if self.status not in {
            CopyAttemptStatus.REJECTED,
            CopyAttemptStatus.FAILED,
            CopyAttemptStatus.FILLED,
        }:
            # A pending instruction cannot be mistaken for a terminal result row.
            raise ValueError("copy result contains an unfinished instruction")
        # The entry uses ordinal zero; exactly four exit ordinals are available.
        if not 0 <= self.number <= 4:
            raise ValueError("copy result attempt number exceeds its fixed limit")
        # Paid fees distinguish pre-submit rejection from failed execution.
        landed = self.status is not CopyAttemptStatus.REJECTED
        if landed != (self.landed_at is not None):
            raise ValueError("copy result landing and failure stage disagree")
        if not landed and (
            self.network_base_fee_paid_atomic or self.network_priority_fee_paid_atomic
            # No network charge can be inferred for an instruction rejected before submission.
        ):
            raise ValueError("copy pre-submit rejection cannot pay a network fee")
        # A successful fill must retain its actual quote; failures retain a stable reason.
        if self.status is CopyAttemptStatus.FILLED:
            if self.landing_quote is None or self.failure_code is not None:
                raise ValueError("copy fill is missing its actual quote")
        elif self.failure_code is None:
            raise ValueError("copy failed attempt is missing its reason")
        # Submitted attempts always preserve a causal reference quote and slippage limit.
        if landed and self.reference is None:
            raise ValueError("copy landed attempt has no reference quote")
        if (
            self.status is CopyAttemptStatus.FILLED
            and self.landing_quote is not None
            # A successful quote must satisfy the reference minimum even if price moved favorably.
            and self.landing_quote.amount_out_atomic < self.minimum_out_atomic
        ):
            raise ValueError("copy filled quote violates its slippage limit")

    @property
    def actual_quote(self) -> ProtocolQuote | None:
        """An unsuccessful landing may have a quote but transfers no curve assets."""
        return self.landing_quote if self.status is CopyAttemptStatus.FILLED else None

    def document(self) -> dict[str, object]:
        """Separate causal quotes, actual fees and bounded retry ordinals."""
        return {
            "order_id": self.order_id.hex,
            "attempt": self.number,
            "side": "BUY" if self.number == 0 else "SELL",
            "decision_position": position_document(self.decision),
            # Expected landing remains evidence even if submission was rejected.
            "expected_landing_position": position_document(self.expected_landing),
            "landing_position": position_document(self.landed_at),
            "status": self.status.value,
            "failure_stage": None
            if self.failure_code is None
            # The failure stage reflects whether the instruction actually reached a landing
            # boundary.
            else ("LANDING" if self.landed_at else "PRE_SUBMIT"),
            "failure_code": self.failure_code,
            # Reference and landing amounts are size-aware, unlike TP/SL prices.
            "reference_quote": quote_document(self.reference),
            "landing_quote": quote_document(self.landing_quote),
            "minimum_out_atomic": self.minimum_out_atomic,
            "network_fee_asset_id": self.network_fee_asset_id,
            "network_base_fee_paid_atomic": self.network_base_fee_paid_atomic,
            # Pump fees and cashback are paid/accrued only by a successful instruction.
            "network_priority_fee_paid_atomic": self.network_priority_fee_paid_atomic,
            "protocol_fee_paid_atomic": 0
            if self.actual_quote is None
            else self.actual_quote.protocol_fee_atomic,
            "creator_fee_paid_atomic": 0
            # Creator fees accrue only on successful actual fills, never rejected quotes.
            if self.actual_quote is None
            else self.actual_quote.creator_fee_atomic,
        }


@dataclass(frozen=True, slots=True)
class CopyPositionRecord:
    """Bounded position history and separately qualified cash/economic valuation."""

    intent: CopyBuyIntent
    status: CopyPositionStatus
    attempts: tuple[CopyAttemptRecord, ...]
    acquired_tokens_atomic: int
    entry_price: TokenPrice | None
    # The first trigger survives retries and later price recovery.
    exit_reason: CopyExitReason | None
    trigger_position: ChainPosition | None
    trigger_price: TokenPrice | None
    account_components: tuple[AccountComponentRecord, ...]
    quote_cashflow_atomic: int
    # Open inventory has no realized round-trip PnL; cash outflow remains visible.
    realized_cash_pnl_atomic: int | None
    cashback_receivable_atomic: int
    mtm_status: MtmStatus
    mtm_liquidation_value_atomic: int | None
    mtm_quote: ProtocolQuote | None
    # Full economic PnL stays nullable when open inventory has no qualified mark.
    economic_pnl_atomic: int | None

    def __post_init__(self) -> None:
        """A published position is closed, entry-failed or explicitly exhausted."""
        if self.status not in {
            CopyPositionStatus.BUY_FAILED,
            CopyPositionStatus.CLOSED,
            CopyPositionStatus.EXHAUSTED,
        }:
            # Incomplete control state cannot be published as a completed backtest position.
            raise ValueError("copy result contains an unfinished position")
        if not self.attempts or len(self.attempts) > 5:
            raise ValueError("copy position must contain one buy and at most four sells")
        # Consecutive ordinals prove there is neither a missing nor a fifth sell attempt.
        if tuple(item.number for item in self.attempts) != tuple(range(len(self.attempts))):
            raise ValueError("copy attempt sequence is not canonical")
        if self.status is CopyPositionStatus.EXHAUSTED and len(self.attempts) != 5:
            raise ValueError("exhausted copy position must have four sell failures")
        # Only actual full closure removes tokens from the position.
        bought = self.attempts[0].status is CopyAttemptStatus.FILLED
        if bought != (self.acquired_tokens_atomic > 0 and self.entry_price is not None):
            raise ValueError("copy entry amounts disagree with buy execution")
        if (self.status is CopyPositionStatus.CLOSED) != (
            self.attempts[-1].number > 0 and self.attempts[-1].status is CopyAttemptStatus.FILLED
            # A full successful sale is the only way to classify acquired inventory as closed.
        ):
            raise ValueError("copy position closure disagrees with its last instruction")
        # Realized cash is taken directly from postings, never reconstructed from quotes.
        expected = None if self.remaining_tokens_atomic else self.quote_cashflow_atomic
        if self.realized_cash_pnl_atomic != expected:
            raise ValueError("copy realized cash differs from committed cashflow")
        self._validate_execution()
        self._validate_economics()

    def _validate_execution(self) -> None:
        """Bind every attempt and actual entry price to this position's immutable operands."""
        buy = self.attempts[0]
        if buy.decision != self.intent.decision_position:
            raise ValueError("copy buy decision differs from its observed signal")
        # A failed buy ends this consumed mint immediately and cannot own sale attempts.
        if self.status is CopyPositionStatus.BUY_FAILED:
            if len(self.attempts) != 1 or buy.status is CopyAttemptStatus.FILLED:
                raise ValueError("copy failed entry contains a fill or sale")
            # Rejected reservations may retain zero-cost account audit records.
            deposits = any(
                item.paid_atomic or item.locked_delta_atomic or item.refunded_atomic
                for item in self.account_components
            )
            if self.acquired_tokens_atomic or self.entry_price or deposits:
                # Unsubmitted account plans may exist but cannot own paid or locked deposits.
                raise ValueError("copy failed entry cannot own tokens or account deposits")
        elif buy.actual_quote is None:
            raise ValueError("copy open or closed position has no successful entry")
        # Entry ratios use actual curve input and acquired tokens, excluding all fees.
        if buy.actual_quote is not None:
            expected = TokenPrice(
                buy.actual_quote.venue_input_atomic, buy.actual_quote.amount_out_atomic
            )
            if (
                # The fee-free entry ratio must be reconstructed from the actual own fill.
                self.entry_price != expected
                or self.acquired_tokens_atomic != buy.actual_quote.amount_out_atomic
            ):
                raise ValueError("copy entry price or tokens differ from the actual fill")
        # Recompute every order identity rather than trusting serialized correlation strings.
        for attempt in self.attempts:
            side = ProtocolQuoteSide.BUY if attempt.number == 0 else ProtocolQuoteSide.SELL
            identity = domain_digest(
                "backtest.pumpfun-copy-order.v1",
                {
                    # The consumed position, order side and attempt ordinal jointly define order
                    # identity.
                    "position_id": self.intent.roundtrip_id.hex,
                    "side": side.value,
                    "attempt": attempt.number,
                },
            )
            # The table cannot attach another position's order or another network's coordinates.
            if attempt.order_id.hex != identity.hex:
                raise ValueError("copy order identity differs from its position and attempt")
            self.intent.decision_position.require_same_chain(attempt.decision)
            for quote in (attempt.reference, attempt.landing_quote):
                if quote is not None:
                    # Both reference and landing quotes must use the same fixed budget or full token
                    # balance.
                    self._validate_quote(quote, side)
        # No intermediate successful sell may be followed by another attempt.
        if any(item.status is CopyAttemptStatus.FILLED for item in self.attempts[1:-1]):
            raise ValueError("copy position retried after a successful sale")
        triggered = len(self.attempts) > 1
        if triggered != (self.exit_reason is not None and self.trigger_position is not None):
            raise ValueError("copy sale history and latched exit reason disagree")
        # A latched trigger cannot precede its own actual entry fill.
        if self.trigger_position is not None:
            buy.expected_landing.require_same_chain(self.trigger_position)
            if self.trigger_position.boundary_ordinal < buy.expected_landing.boundary_ordinal:
                raise ValueError("copy exit trigger precedes the actual buy fill")
            if self.attempts[1].decision.boundary_ordinal < self.trigger_position.boundary_ordinal:
                # An exit request cannot act at a boundary earlier than the observed trigger.
                raise ValueError("copy sell decision precedes its trigger")
        # Retry decision follows the preceding failure; full two-second proof belongs to the clock.
        for previous, current in zip(self.attempts[1:], self.attempts[2:], strict=False):
            failed = previous.landed_at or previous.decision
            if current.decision.boundary_ordinal <= failed.boundary_ordinal:
                raise ValueError("copy retry decision does not follow its prior failure")

    def _validate_quote(self, quote: ProtocolQuote, side: ProtocolQuoteSide) -> None:
        """Quotes cannot swap assets, change the entry budget or partially close inventory."""
        buying = side is ProtocolQuoteSide.BUY
        signal = self.intent.signal
        assets = (
            (signal.quote_asset_id, signal.asset_id)
            if buying
            # Buy spends quote units while a full sell spends acquired token units.
            else (signal.asset_id, signal.quote_asset_id)
        )
        amount = (
            self.intent.policy.gross_buy_budget_atomic if buying else self.acquired_tokens_atomic
        )
        # Side and asset validation precedes checking the exact input amount.
        if quote.side is not side or (quote.input_asset_id, quote.output_asset_id) != assets:
            raise ValueError("copy quote side or asset differs from its position")
        if quote.amount_in_atomic != amount:
            raise ValueError("copy quote input differs from fixed budget or full inventory")

    def _validate_economics(self) -> None:
        """Reconcile nullable valuation and cashback without reconstructing authoritative cash."""
        cashback = sum(
            item.actual_quote.cashback_receivable_atomic
            for item in self.attempts
            if item.actual_quote is not None
        )
        # Cashback is derived from successful fills independently of realized cash PnL.
        if self.cashback_receivable_atomic != cashback:
            raise ValueError("copy cashback differs from successful fills")
        if not self.remaining_tokens_atomic:
            if (
                self.mtm_status is not MtmStatus.NOT_APPLICABLE
                # Flat positions have no liquidation quote and must use NOT_APPLICABLE valuation.
                or self.mtm_quote is not None
                or self.mtm_liquidation_value_atomic != 0
            ):
                raise ValueError("copy flat position cannot contain an open valuation")
        elif self.mtm_status is MtmStatus.UNAVAILABLE:
            # Unavailable valuation cannot be represented by an invented zero mark.
            if self.mtm_quote is not None or self.mtm_liquidation_value_atomic is not None:
                raise ValueError("copy unavailable valuation cannot contain a mark")
        else:
            # A quoted open value remains explicitly executable or stale before migration.
            if (
                self.mtm_status not in {MtmStatus.EXECUTABLE, MtmStatus.STALE_PRE_MIGRATION}
                or self.mtm_quote is None
                or self.mtm_liquidation_value_atomic is None
            ):
                # A marked open position requires a qualified protocol quote.
                raise ValueError("copy open valuation is missing its qualified quote")
            self._validate_quote(self.mtm_quote, ProtocolQuoteSide.SELL)
        # Locked UVA value is distinct from refundable per-mint ATA deposits.
        locked = sum(
            amount
            for asset, amount in run_locked_value(self.account_components)
            if asset == self.intent.quote_asset_id
        )
        # Liquidation already accounts for its modeled sale costs and refundable deposits.
        liquidation = self.mtm_liquidation_value_atomic
        economic = (
            None
            if liquidation is None
            else self.quote_cashflow_atomic + liquidation + cashback + locked
            # The economic total must reconcile cash, liquidation, cashback and run-locked value.
        )
        if self.economic_pnl_atomic != economic:
            raise ValueError("copy economic PnL differs from cash and qualified position value")

    @property
    def remaining_tokens_atomic(self) -> int:
        """Exhaustion preserves actual inventory and does not invent a final exit."""
        return 0 if self.status is CopyPositionStatus.CLOSED else self.acquired_tokens_atomic

    @property
    def roundtrip_id(self) -> ContentDigest:
        """The common result paging role uses the copy position's actual identity."""
        return self.intent.roundtrip_id

    @property
    def target_position(self) -> ChainPosition:
        """The table target is the real source BUY, with its exact instruction index."""
        return self.intent.signal.position

    @property
    def network_id(self) -> NetworkId:
        """Result readers bind every row to the manifest's immutable network."""
        return self.target_position.network_id

    @property
    def position_schema_id(self) -> PositionSchemaId:
        """Result readers never compare coordinates from different schemas."""
        return self.target_position.position_schema_id

    def document(self) -> dict[str, object]:
        """The external row keeps its real signer/BUY identity and bounded attempts."""
        signal = self.intent.signal
        return {
            "schema": COPY_POSITION_SCHEMA,
            "position_id": self.intent.roundtrip_id.hex,
            "signal_event_id": signal.event_id.hex,
            # The actor is the exact signing_wallet, with no creator or payer fallback.
            "signing_wallet": signal.signing_wallet.value,
            "signal_position": position_document(signal.position),
            "observation_position": position_document(self.intent.decision_position),
            "asset_id": signal.asset_id.value,
            "quote_asset_id": signal.quote_asset_id.value,
            # Policy and mode are immutable inputs, not inferred result labels.
            "venue_id": signal.venue_id.value,
            "policy": self.intent.policy.document(),
            "execution_mode": self.intent.execution_mode.value,
            "status": self.status.value,
            "attempts": [item.document() for item in self.attempts],
            # Fee-free trigger ratios remain independent of financial PnL.
            "entry_price": price_document(self.entry_price),
            "exit_reason": None if self.exit_reason is None else self.exit_reason.value,
            "trigger_position": position_document(self.trigger_position),
            "trigger_price": price_document(self.trigger_price),
            "acquired_tokens_atomic": self.acquired_tokens_atomic,
            # Account components retain per-mint ATA and one-time wallet UVA attribution.
            "remaining_tokens_atomic": self.remaining_tokens_atomic,
            "account_components": [item.document() for item in self.account_components],
            "quote_cashflow_atomic": self.quote_cashflow_atomic,
            "realized_cash_pnl_atomic": self.realized_cash_pnl_atomic,
            "cashback_receivable_atomic": self.cashback_receivable_atomic,
            # Stale/unavailable valuation never becomes a successful synthetic sale.
            "mtm_status": self.mtm_status.value,
            "mtm_liquidation_value_atomic": self.mtm_liquidation_value_atomic,
            "mtm_quote": quote_document(self.mtm_quote),
            "economic_pnl_atomic": self.economic_pnl_atomic,
        }


def freeze_copy_position(
    state: CopyExecutionPosition, executor: CopyOrderExecutor
) -> CopyPositionRecord:
    """Project final control and committed ledger cash without mutating either."""
    records = tuple(_freeze_attempt(state, index) for index in range(len(state.attempts)))
    cash = executor.cashflows.amount(state.intent.roundtrip_id, state.intent.quote_asset_id)
    cashback = sum(
        item.actual_quote.cashback_receivable_atomic
        for item in records
        # Failed instructions cannot accrue cashback even when they retained a landing quote.
        if item.actual_quote is not None
    )
    # Run-locked deposits remain economically separate from wallet cash movements.
    locked = sum(
        amount
        for asset, amount in run_locked_value(state.account_components)
        if asset == state.intent.quote_asset_id
    )
    # Open valuation follows the same fee/rent/cashback economics as shared Pump execution.
    status, liquidation, quote = _valuation(state, executor)
    economic = None if liquidation is None else cash + liquidation + cashback + locked
    realized = None if state.control.remaining_tokens_atomic else cash
    return CopyPositionRecord(
        state.intent,
        # Freeze terminal control and bounded attempts together with acquired inventory.
        state.control.status,
        records,
        state.control.acquired_tokens_atomic,
        # Retain the original first trigger, including its causal price or missing active price.
        state.control.entry_price,
        state.control.exit_reason,
        state.control.trigger_position,
        state.control.trigger_price,
        state.account_components,
        # Cash and valuation fields retain their independent authoritative sources.
        cash,
        realized,
        cashback,
        status,
        liquidation,
        # Retain the quote behind the terminal mark so readers can verify its qualification.
        quote,
        economic,
    )


def _freeze_attempt(state: CopyExecutionPosition, index: int) -> CopyAttemptRecord:
    """Snapshot immutable quote objects and actual paid costs from one final instruction."""
    attempt = state.attempts[index]
    network = attempt.network
    if network is None:
        raise ValueError("copy finalized instruction has no network cost profile")
    # Rejections retain the fee asset while paying neither base nor priority fee.
    paid = attempt.landed_at is not None
    return CopyAttemptRecord(
        attempt.order_id,
        attempt.number,
        attempt.decision,
        # Expected and actual landing remain separate when an instruction is rejected.
        attempt.expected_landing,
        attempt.status,
        attempt.landed_at,
        attempt.reference,
        attempt.landing_quote,
        # Paid network costs depend on actual landing, not an available quote.
        # Costs are captured after commit and cannot change with later reservations.
        attempt.minimum_out_atomic,
        attempt.failure_code,
        network.fee_asset_id.value,
        network.base_fee_atomic if paid else 0,
        network.priority_fee_atomic if paid else 0,
        # Each component stays in integer atomic units through result serialization.
    )


def _valuation(
    state: CopyExecutionPosition, executor: CopyOrderExecutor
) -> tuple[MtmStatus, int | None, ProtocolQuote | None]:
    """A terminal row may value remaining tokens, but cannot settle them implicitly."""
    if not state.control.remaining_tokens_atomic:
        return MtmStatus.NOT_APPLICABLE, 0, None
    final_s = executor.clock.block_time_ns[-1] // 1_000_000_000
    try:
        # A protocol-level contract error escapes; only a supported execution reject is unknown MTM.
        valuation = executor.historical.valuation_quote(
            state.intent,
            tokens_in_atomic=state.control.remaining_tokens_atomic,
            effective_at_unix_s=final_s,
        )
    # A protocol rejection marks inventory unvalued without forcing a synthetic close.
    except ProtocolExecutionRejected:
        valuation = None
    # Missing or migrated liquidity must not be silently valued as zero.
    if valuation is None:
        return MtmStatus.UNAVAILABLE, None, None
    network = executor.network_costs.quote_sell(effective_at_unix_s=final_s)
    fee = (
        network.transaction_fee_atomic if network.fee_asset_id == state.intent.quote_asset_id else 0
        # A non-quote fee asset must not be subtracted as if it were SOL.
    )
    # Only per-mint refundable deposits contribute to hypothetical liquidation proceeds.
    refund = sum(
        amount
        for asset, amount in refundable_mint_deposits(state.account_components)
        if asset == state.intent.quote_asset_id
    )
    # Stale pre-migration marks are explicitly qualified and do not fund the wallet.
    status = (
        MtmStatus.STALE_PRE_MIGRATION if valuation.stale_pre_migration else MtmStatus.EXECUTABLE
    )
    return status, valuation.quote.amount_out_atomic - fee + refund, valuation.quote


def position_document(position: ChainPosition | None) -> dict[str, object] | None:
    """Exact coordinates include immutable network and position schema identities."""
    if position is None:
        return None
    return {
        "network_id": position.network_id.value,
        "position_schema_id": position.position_schema_id.value,
        # Event index is absent for a boundary and present for the original BUY instruction.
        "block_ordinal": position.block_ordinal,
        "transaction_index": position.transaction_index,
        "event_index": position.event_index,
    }


def price_document(price: TokenPrice | None) -> dict[str, int] | None:
    """Reduced positive integer ratios preserve exact inclusive trigger comparisons."""
    return (
        None
        if price is None
        else {"quote_atomic": price.quote_atomic, "token_atomic": price.token_atomic}
    )


def quote_document(quote: ProtocolQuote | None) -> dict[str, object] | None:
    """Quote data includes potential liquidity shortfall separately from settled funding."""
    if quote is None:
        return None
    result: dict[str, object] = {
        "side": quote.side.value,
        "input_asset_id": quote.input_asset_id.value,
        # Quantities retain atomic units; the venue legs exclude Pump component fees.
        "output_asset_id": quote.output_asset_id.value,
        "amount_in_atomic": quote.amount_in_atomic,
        "amount_out_atomic": quote.amount_out_atomic,
        "venue_input_atomic": quote.venue_input_atomic,
        "venue_output_atomic": quote.venue_output_atomic,
        # Fee destinations and cashback source retain ledger attribution.
        "protocol_fee_atomic": quote.protocol_fee_atomic,
        "creator_fee_atomic": quote.creator_fee_atomic,
        "cashback_receivable_atomic": quote.cashback_receivable_atomic,
        "protocol_fee_account_id": quote.protocol_fee_account_id.value,
        "creator_fee_account_id": quote.creator_fee_account_id.value,
        # Cashback retains its own source account for double-entry reconciliation.
        "cashback_source_account_id": quote.cashback_source_account_id.value,
    }
    # Every sell carries causal funding evidence; buys deliberately carry none.
    evidence = quote.liquidity_evidence
    result["liquidity"] = (
        None
        if evidence is None
        else {
            # Liquidity evidence qualifies output solvency without changing observed reserve state.
            "policy_id": evidence.policy_id,
            "asset_id": evidence.asset_id.value,
            "required_output_atomic": evidence.required_output_atomic,
            # A quoted shortfall is not the amount actually funded by a successful virtual sale.
            "observed_available_output_atomic": evidence.observed_available_output_atomic,
            "synthetic_shortfall_atomic": evidence.synthetic_shortfall_atomic,
            "synthetic_source_account_id": None
            if evidence.synthetic_source_account_id is None
            else evidence.synthetic_source_account_id.value,
            # An absent synthetic source remains absent in strict execution mode.
        }
    )
    return result
