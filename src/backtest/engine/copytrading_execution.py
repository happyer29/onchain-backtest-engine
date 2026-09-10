"""Copy order execution over shared integer ledger and wallet-account reducers."""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

# Financial effects use the same core-owned contracts as other Pump strategies.
from backtest.domain.account_requirements import AccountComponentRecord
from backtest.domain.chain import ChainPosition
from backtest.domain.copytrading import CopyBuyIntent
from backtest.domain.execution import Fill
from backtest.domain.hashing import domain_digest

# Amounts, assets and order identity remain separate typed values in accounting.
from backtest.domain.identifiers import AssetId, OrderId, PoolId

# ORDER identity distinguishes retries; ledger cash attribution stays position-scoped.
from backtest.domain.ledger import LedgerCorrelationKind, LedgerTransaction, Posting
from backtest.engine.copytrading_contracts import CopyBuyProtocolRuntime
from backtest.engine.copytrading_state import CopyPositionControl, maximum_settlement_position
from backtest.engine.portfolio import PortfolioState
from backtest.engine.sniping import (
    # Shared helpers construct postings without importing a concrete execution plugin.
    _buy_reservation,
    _CorrelatedLedgerCashflows,
    _failed_buy_settlement,
    # Reuse validated posting builders without emitting their Sniping identities.
    _failed_sell_settlement,
    _has_available,
    _minimum_output_atomic,
    _reserve_amounts,
    _sell_reservation,
    # Only successful curve settlements can transfer tokens or accrue Pump fees.
    _successful_buy_settlement,
    _successful_sell_settlement,
    _validate_buy_quote,
    _validate_sell_quote,
)

# Quote validation occurs before any double-entry ledger transaction is committed.
from backtest.engine.sniping_contracts import (
    NetworkCostQuote,
    ProtocolExecutionRejected,
    ProtocolQuote,
    ProtocolQuoteSide,
    # Network costs carry their own fee asset rather than borrowing the quote denomination.
    SnipingNetworkCostModel,
)

# Clock/timer control never derives duration from wall time or external queries.
from backtest.engine.transaction_clock import CompactTransactionClock
from backtest.engine.wallet_accounts import (
    AccountProvisioningTransition,
    AccountReservationPlan,
    WalletProvisioningReducer,
    # Unsubmitted account plans retain audit detail without charging a deposit.
    unsubmitted_account_records,
)


class CopyAttemptStatus(StrEnum):
    """Pre-submit rejection is distinct from a network-fee-paying failed landing."""

    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    FILLED = "FILLED"


# A position retains only its one entry and four bounded exit attempts.
@dataclass(slots=True)
class CopyOrderAttempt:
    """One bounded decision/landing record; a position has at most five of these."""

    order_id: OrderId
    side: ProtocolQuoteSide
    number: int
    decision: ChainPosition
    expected_landing: ChainPosition
    # No landing, charge or fill is inferred from an accepted order.
    status: CopyAttemptStatus = CopyAttemptStatus.CREATED
    landed_at: ChainPosition | None = None
    reference: ProtocolQuote | None = None
    landing_quote: ProtocolQuote | None = None
    minimum_out_atomic: int = 0
    # Quoted costs remain separate from actual costs on failed/rejected instructions.
    network: NetworkCostQuote | None = None
    failure_code: str | None = None

    @property
    def paid_network_fee_atomic(self) -> int:
        """Only a landed instruction pays its asset-tagged base and priority fees."""
        if self.landed_at is None or self.network is None:
            return 0
        return self.network.transaction_fee_atomic


@dataclass(slots=True)
class CopyExecutionPosition:
    """Control, bounded attempt history, and the shared account reducer's records."""

    intent: CopyBuyIntent
    control: CopyPositionControl = field(init=False)
    attempts: list[CopyOrderAttempt] = field(default_factory=list)
    account_plan: AccountReservationPlan | None = None
    account_components: tuple[AccountComponentRecord, ...] = ()
    # Mutable control is per position; account effects still come from the wallet reducer.

    def __post_init__(self) -> None:
        """The real BUY signal is retained; no synthetic launch or cooldown exists."""
        self.control = CopyPositionControl(
            self.intent.roundtrip_id,
            self.intent.asset_id,
            self.intent.decision_position,
            self.intent.policy,
            # The controller owns retry/timer state without duplicating financial balances.
        )


class CopyOrderExecutor:
    """One sequential wallet; quotations never mutate historical or observed state."""

    def __init__(
        self,
        *,
        clock: CompactTransactionClock,
        historical: CopyBuyProtocolRuntime,
        # Landing and observation must never share the same mutable protocol reducer.
        observed: CopyBuyProtocolRuntime,
        network_costs: SnipingNetworkCostModel,
        # The run owns verified input views, its wallet and a buffered ledger sink.
        portfolio: PortfolioState,
        accounts: WalletProvisioningReducer,
        append_ledger: Callable[[LedgerTransaction], None],
        # Dynamic execution records are buffered; no historical-event logging is added.
        append_audit: Callable[[dict[str, object]], None] | None = None,
        append_fill: Callable[[Fill], None] | None = None,
    ) -> None:
        # Separate protocol instances prevent observations from advancing landing state.
        if historical is observed:
            raise ValueError("historical and observed state must be separate instances")
        self.clock, self.historical, self.observed = clock, historical, observed
        self.network_costs, self.portfolio, self.accounts = network_costs, portfolio, accounts
        # PnL is a materialized view of committed correlated postings, not quote totals.
        self.cashflows = _CorrelatedLedgerCashflows()
        self._append_ledger = append_ledger
        self._append_audit, self._append_fill = append_audit, append_fill

    def begin_buy(self, state: CopyExecutionPosition) -> CopyOrderAttempt:
        """Attempt the already-consumed mint once, proving its complete path first."""
        if state.attempts:
            raise ValueError("copy entry cannot be attempted again")
        intent = state.intent
        maximum_settlement_position(self.clock, intent.signal.position, intent.policy)
        # The delivery boundary must exactly match the separately configured observation.
        expected = intent.signal.position
        if intent.policy.observation_delay_transactions:
            expected = self.clock.transaction_after(
                expected, intent.policy.observation_delay_transactions
            )
        # A delayed signal cannot create an order retroactively at its historical timestamp.
        if expected.boundary_ordinal != intent.decision_position.boundary_ordinal:
            raise ValueError("copy decision does not match observation delay")
        # Mint consumption happened in strategy before network/account planning.
        attempt = self._new_attempt(state, ProtocolQuoteSide.BUY, 0, intent.decision_position)
        effective_s = self._seconds(attempt.decision)
        requirements = self.observed.account_requirements(intent)
        # Price network costs at the decision time before attempting a curve quote.
        attempt.network = self.network_costs.quote_buy(
            effective_at_unix_s=effective_s,
            requirements=requirements,
            # Effective-dated network and account costs are fixed for this decision boundary.
        )
        # Reservation accounts are planned from already committed wallet state only.
        plan = self.accounts.reservation(
            roundtrip_id=intent.roundtrip_id,
            mint_asset_id=intent.asset_id,
            priced_requirements=attempt.network.account_requirements,
        )
        # Audit the reservation plan before a quote or balance rejection can return.
        state.account_plan = plan
        state.account_components = unsubmitted_account_records(self.accounts.state, plan)
        try:
            # A protocol rejection cannot leak a fee, deposit or token acquisition.
            attempt.reference = self.observed.quote_buy(intent, effective_at_unix_s=effective_s)
            _validate_buy_quote(intent, attempt.reference)
        except ProtocolExecutionRejected as error:
            return self._reject(state, attempt, error.code)
        # Reference minimum and reservation include own size with integer component fees.
        attempt.minimum_out_atomic = _minimum_output_atomic(
            attempt.reference.amount_out_atomic, intent.policy.buy_slippage_bps
        )
        amounts = _buy_reservation(intent, attempt.network, plan)
        return self._submit(state, attempt, amounts)

    # There is no buy retry path after this first consumed entry attempt.

    def begin_sell(self, state: CopyExecutionPosition, position: ChainPosition) -> CopyOrderAttempt:
        """Consume one of four attempts before a fresh quote or fee balance check."""
        number = state.control.begin_sell(position, clock=self.clock)
        attempt = self._new_attempt(state, ProtocolQuoteSide.SELL, number, position)
        effective_s = self._seconds(position)
        attempt.network = self.network_costs.quote_sell(effective_at_unix_s=effective_s)
        # The original reason remains latched while every attempt gets a fresh quote.
        try:
            attempt.reference = self.observed.quote_sell(
                state.intent,
                tokens_in_atomic=state.control.remaining_tokens_atomic,
                effective_at_unix_s=effective_s,
                # Each retry observes the latest delivered curve state and the whole remaining
                # balance.
            )
            _validate_sell_quote(
                state.intent, state.control.remaining_tokens_atomic, attempt.reference
            )
        except ProtocolExecutionRejected as error:
            # Only supported execution rejections consume an attempt; contract errors abort the run.
            return self._reject(state, attempt, error.code)
        # A reference rejection and insufficient fee funds both consume this attempt.
        attempt.minimum_out_atomic = _minimum_output_atomic(
            attempt.reference.amount_out_atomic, state.intent.policy.sell_slippage_bps
        )
        amounts = _sell_reservation(
            # Reserve the full token balance plus additional network fee funds before submission.
            state.intent,
            tokens_atomic=state.control.remaining_tokens_atomic,
            network=attempt.network,
        )
        return self._submit(state, attempt, amounts)

    # Submitted orders land at exact future boundaries, regardless of later callbacks.

    def land(self, state: CopyExecutionPosition, position: ChainPosition) -> CopyOrderAttempt:
        """Settle the one pending instruction at exactly its configured future boundary."""
        attempt = state.attempts[-1]
        if (
            attempt.status is not CopyAttemptStatus.SUBMITTED
            or position != attempt.expected_landing
        ):
            # Only the pending order may mutate balances at this exact clock boundary.
            raise ValueError("copy landing is stale or does not match its exact boundary")
        # A stale or duplicate landing cannot charge a second network fee.
        network = _require_network(attempt)
        # Compute a landing quote against current historical state, not delayed state.
        failure = None
        try:
            attempt.landing_quote = self._landing_quote(state, attempt, position)
            if attempt.landing_quote.amount_out_atomic < attempt.minimum_out_atomic:
                raise ProtocolExecutionRejected("MINIMUM_OUTPUT_NOT_MET")
        # Unsupported data/profile errors deliberately escape as run-level failures.
        except ProtocolExecutionRejected as error:
            failure = error.code
        # A failed sell has no account transition; a buy always resolves its reservation.
        transition: AccountProvisioningTransition | None
        if attempt.side is ProtocolQuoteSide.BUY:
            transaction, transition = self._buy_settlement(state, attempt, network, failure)
        else:
            # Failed sells retain both tokens and account state; successful sells refund ATA.
            transaction, transition = self._sell_settlement(state, attempt, network, failure)
        self._commit(state, attempt, transaction, transition=transition)
        attempt.landed_at, attempt.failure_code = position, failure
        attempt.status = CopyAttemptStatus.FILLED if failure is None else CopyAttemptStatus.FAILED
        # Control is notified only after the matching portfolio/account commit.
        self._notify(state, attempt, successful=failure is None)
        self._record_attempt(state, attempt)
        # A failed landing pays network fees but emits no curve fill.
        if failure is None and self._append_fill is not None:
            self._append_fill(_copy_fill(state, attempt))
        return attempt

    # Landing quotes use the authoritative historical state at the delayed execution instant.
    def _landing_quote(
        self, state: CopyExecutionPosition, attempt: CopyOrderAttempt, position: ChainPosition
    ) -> ProtocolQuote:
        """Validate assets, quantities and strict/synthetic funding before ledger effects."""
        seconds = self._seconds(position)
        if attempt.side is ProtocolQuoteSide.BUY:
            quote = self.historical.quote_buy(state.intent, effective_at_unix_s=seconds)
            _validate_buy_quote(state.intent, quote)
            return quote
        # Every sell closes the entire acquired balance; no partial fill policy is inferred.
        tokens = state.control.remaining_tokens_atomic
        quote = self.historical.quote_sell(
            state.intent, tokens_in_atomic=tokens, effective_at_unix_s=seconds
        )
        _validate_sell_quote(state.intent, tokens, quote)
        # Validated full-position amounts are the only inputs passed to settlement postings.
        return quote

    def _buy_settlement(
        self,
        state: CopyExecutionPosition,
        # Settlement uses the preexisting reservation and its explicit network-cost profile.
        attempt: CopyOrderAttempt,
        network: NetworkCostQuote,
        failure: str | None,
    ) -> tuple[LedgerTransaction, AccountProvisioningTransition]:
        """Shared reducer rolls failed account creation back and charges only network fee."""
        plan = state.account_plan
        if plan is None:
            raise ValueError("submitted buy has no account reservation")
        transition = self.accounts.preview_buy(plan, successful=failure is None)
        # Both plans release unused reservations through the same asset-tagged math.
        if failure is not None:
            transaction = _failed_buy_settlement(
                state.intent,
                boundary=attempt.expected_landing.boundary_ordinal,
                network=network,
                # Failed entry releases its account reservation without provisioning the account.
                account_plan=plan,
                network_fee_account_id=self.network_costs.fee_collector_account_id,
                reason=failure,
            )
        else:
            # Successful acquisition uses actual curve input/tokens and component deposits.
            transaction = _successful_buy_settlement(
                state.intent,
                boundary=attempt.expected_landing.boundary_ordinal,
                quote=_require_landing(attempt),
                network=network,
                # Successful entry commits the previewed account transition with its token transfer.
                account_plan=plan,
                account_transition=transition,
                network_fee_account_id=self.network_costs.fee_collector_account_id,
            )
        return transaction, transition

    def _sell_settlement(
        self,
        state: CopyExecutionPosition,
        attempt: CopyOrderAttempt,
        # Failure and success share the same pinned network price for this instruction.
        network: NetworkCostQuote,
        failure: str | None,
    ) -> tuple[LedgerTransaction, AccountProvisioningTransition | None]:
        """Synthetic funding exists only in a successful sell's explicit EXTERNAL posting."""
        tokens = state.control.remaining_tokens_atomic
        if failure is not None:
            transaction = _failed_sell_settlement(
                state.intent,
                boundary=attempt.expected_landing.boundary_ordinal,
                # A failed exit releases tokens but still pays its landed transaction fee.
                tokens_atomic=tokens,
                network=network,
                network_fee_account_id=self.network_costs.fee_collector_account_id,
                reason=failure,
            )
            # No ATA refund or provisioning change accompanies a failed exit.
            return transaction, None
        # Only a full successful exit can close the mint ATA; wallet UVA remains locked.
        transition = self.accounts.preview_sell(
            roundtrip_id=state.intent.roundtrip_id,
            mint_asset_id=state.intent.asset_id,
            records=state.account_components,
            successful=True,
            # The shared reducer decides the exact refundable ATA amount.
        )
        transaction = _successful_sell_settlement(
            state.intent,
            boundary=attempt.expected_landing.boundary_ordinal,
            quote=_require_landing(attempt),
            # The full sale pays its network cost in addition to the Pump quote components.
            network=network,
            tokens_atomic=tokens,
            account_transition=transition,
            network_fee_account_id=self.network_costs.fee_collector_account_id,
        )
        # Return one posting plan with its matching account preview for atomic commit.
        return transaction, transition

    def _submit(
        self,
        state: CopyExecutionPosition,
        attempt: CopyOrderAttempt,
        # Reservations carry explicit assets, including any fee asset distinct from SOL.
        amounts: tuple[tuple[AssetId, int], ...],
    ) -> CopyOrderAttempt:
        """Reserve spendable assets atomically, or reject with no ledger transaction."""
        if not _has_available(self.portfolio, amounts):
            return self._reject(state, attempt, "INSUFFICIENT_FUNDS")
        postings: list[Posting] = []
        _reserve_amounts(postings, amounts)
        # Copy order identity distinguishes every retry even at the same modeled second.
        transaction = _transaction(
            state,
            attempt,
            boundary=attempt.decision.boundary_ordinal,
            operation="RESERVATION",
            # Reservation postings move funds into held balances without spending them.
            postings=tuple(postings),
        )
        self._commit(state, attempt, transaction)
        attempt.status = CopyAttemptStatus.SUBMITTED
        self._record_attempt(state, attempt)
        # Only a committed reservation becomes an executable pending instruction.
        return attempt

    def _reject(
        self, state: CopyExecutionPosition, attempt: CopyOrderAttempt, code: str
    ) -> CopyOrderAttempt:
        """No fee/deposit postings are made for an instruction that was never submitted."""
        attempt.status, attempt.failure_code = CopyAttemptStatus.REJECTED, code
        self._notify(state, attempt, successful=False)
        self._record_attempt(state, attempt)
        return attempt

    def _record_attempt(self, state: CopyExecutionPosition, attempt: CopyOrderAttempt) -> None:
        """Audit only simulated instructions after their financial/control transition."""
        if self._append_audit is None:
            return
        position = attempt.landed_at or attempt.decision
        self._append_audit(
            # Audit phase distinguishes submission from historical landing, not extraction time.
            {
                "schema": "pumpfun-copy-order-audit/v1",
                "record_type": "COPY_ORDER",
                "phase": 60 if attempt.landed_at is not None else 50,
                # Retry ordinals and order IDs distinguish each bounded attempt.
                "position_id": state.intent.roundtrip_id.hex,
                "order_id": attempt.order_id.hex,
                "attempt": attempt.number,
                "side": attempt.side.value,
                "boundary_ordinal": position.boundary_ordinal,
                # Status states the actual execution stage, never a quoted hypothetical fill.
                "status": attempt.status.value,
                "failure_code": attempt.failure_code,
            }
        )

    def _notify(
        self, state: CopyExecutionPosition, attempt: CopyOrderAttempt, *, successful: bool
    ) -> None:
        """Failure timing is measured from rejection or actual landing, respectively."""
        position = attempt.landed_at or attempt.decision
        if attempt.side is ProtocolQuoteSide.BUY:
            if not successful:
                state.control.fail_buy()
                return
            # Fee-free entry price uses the actual settled curve input and output.
            quote = _require_landing(attempt)
            state.control.fill_buy(
                position=position,
                curve_input_atomic=quote.venue_input_atomic,
                tokens_atomic=quote.amount_out_atomic,
                # The actual fill boundary starts both the holding timer and entry-price baseline.
                clock=self.clock,
            )
        elif successful:
            state.control.fill_sell(attempt=attempt.number, position=position)
        else:
            # Four total failures exhaust the position; the reducer never schedules a fifth.
            state.control.fail_sell(
                attempt=attempt.number,
                position=position,
                submitted=attempt.landed_at is not None,
                clock=self.clock,
                # A pre-submit rejection starts the same retry wait without charging network fees.
            )

    def _commit(
        self,
        state: CopyExecutionPosition,
        attempt: CopyOrderAttempt,
        transaction: LedgerTransaction,
        # An account preview is optional because failed sells leave provisioning unchanged.
        *,
        transition: AccountProvisioningTransition | None = None,
    ) -> None:
        """No account mutation precedes validation of the complete balanced portfolio plan."""
        if transaction.reason.startswith("SNIPING_"):
            transaction = _transaction(
                state,
                attempt,
                boundary=transaction.boundary_ordinal,
                # Shared posting builders receive copy-specific correlation and transaction domains.
                operation=transaction.reason.removeprefix("SNIPING_"),
                postings=transaction.postings,
            )
        candidate = self.portfolio.preview(transaction)
        self.portfolio.commit(candidate)
        # The account candidate is pure and already validated; both commits form one operation.
        if transition is not None:
            self.accounts.commit(transition)
            state.account_components = transition.records
        self.cashflows.append(transaction)
        self._append_ledger(transaction)

    def _new_attempt(
        self,
        state: CopyExecutionPosition,
        side: ProtocolQuoteSide,
        number: int,
        # Attempt number disambiguates retries while position identity remains unchanged.
        position: ChainPosition,
    ) -> CopyOrderAttempt:
        """Order identity binds position, side and bounded retry ordinal."""
        delay = (
            state.intent.policy.buy_delay_transactions
            if side is ProtocolQuoteSide.BUY
            else state.intent.policy.sell_delay_transactions
        )
        # All latency counts global transactions, including unrelated and failed transactions.
        landing = self.clock.transaction_after(position, delay)
        identity = domain_digest(
            "backtest.pumpfun-copy-order.v1",
            {
                "position_id": state.intent.roundtrip_id.hex,
                # The side and retry ordinal prevent buy/sell and repeated-sale identity collisions.
                "side": side.value,
                "attempt": number,
            },
        )
        # Only dynamic simulated orders are retained; no historical-event heap is created.
        attempt = CopyOrderAttempt(OrderId(identity.hex), side, number, position, landing)
        state.attempts.append(attempt)
        return attempt

    def _seconds(self, position: ChainPosition) -> int:
        """A second-resolution source clock never becomes a measured subsecond feed clock."""
        return self.clock.block_time_for_position(position) // 1_000_000_000


def _transaction(
    state: CopyExecutionPosition,
    attempt: CopyOrderAttempt,
    *,
    boundary: int,
    # Operation distinguishes reservation and settlement for the same order and boundary.
    operation: str,
    postings: tuple[Posting, ...],
) -> LedgerTransaction:
    """Retries have unique transaction IDs and immutable position cash attribution."""
    identity = domain_digest(
        "backtest.pumpfun-copy-ledger.v1",
        {
            "order_id": attempt.order_id.value,
            "boundary": boundary,
            # Different posting operations cannot reuse a committed ledger transaction identity.
            "operation": operation,
        },
    )
    return LedgerTransaction(
        transaction_id=identity,
        # Every copy posting is attributable to exactly one consumed-mint position.
        correlation_kind=LedgerCorrelationKind.ROUNDTRIP,
        # Position identity connects actual cash postings to the bounded result row.
        correlation_id=state.intent.roundtrip_id,
        boundary_ordinal=boundary,
        postings=postings,
        reason=f"COPY_{operation}",
    )


def _copy_fill(state: CopyExecutionPosition, attempt: CopyOrderAttempt) -> Fill:
    """Preserve the real retry ORDER ID in the common immutable fill stream."""
    quote = _require_landing(attempt)
    return Fill(
        order_id=attempt.order_id,
        pool_id=PoolId(state.intent.venue_id.value),
        sold_asset_id=quote.input_asset_id,
        # The quote explicitly determines both assets; network charges are separate postings.
        bought_asset_id=quote.output_asset_id,
        # Pump fees are inside the gross budget/output; network fees stay in the ledger.
        amount_in_atomic=quote.amount_in_atomic,
        amount_out_atomic=quote.amount_out_atomic,
        fee_amount_atomic=quote.protocol_fee_atomic + quote.creator_fee_atomic,
        boundary_ordinal=attempt.expected_landing.boundary_ordinal,
    )


def _require_network(attempt: CopyOrderAttempt) -> NetworkCostQuote:
    """A submitted order must retain its exact reserved network fee profile."""
    if attempt.network is None:
        raise ValueError("copy attempt has no network fee quote")
    return attempt.network


def _require_landing(attempt: CopyOrderAttempt) -> ProtocolQuote:
    """A failed quotation must not be interpreted as a zero-amount successful fill."""
    if attempt.landing_quote is None:
        raise ValueError("copy attempt has no successful landing quote")
    return attempt.landing_quote
