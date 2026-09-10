"""Bounded position control for one entry and four causal exit attempts.

This reducer authorizes decisions only. Portfolio changes and fees belong to
the engine's atomic execution/ledger reducer, never to this control state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

# Retry policy is core-owned, so plugins cannot silently change failure behavior.
from backtest.domain.chain import ChainPosition
from backtest.domain.copytrading import (
    MAXIMUM_SELL_ATTEMPTS,
    SELL_RETRY_DELAY_NS,
    CopyBuyPolicy,
    # Price observations are immutable ratios, separate from executable quotes.
    CopyExitReason,
    TokenPrice,
    require_integer,
)
from backtest.domain.identifiers import AssetId, ContentDigest

# Duration boundaries come exclusively from verified local clock data.
from backtest.engine.transaction_clock import CompactTransactionClock


class CopyPositionStatus(StrEnum):
    """A consumed mint never returns to an entry-eligible state."""

    BUY_PENDING = "BUY_PENDING"
    BUY_FAILED = "BUY_FAILED"
    OPEN = "OPEN"
    SELL_PENDING = "SELL_PENDING"
    RETRY_WAIT = "RETRY_WAIT"
    # Exhaustion retains the actual token position; it is not a fill.
    EXHAUSTED = "EXHAUSTED"
    CLOSED = "CLOSED"


class CopyStateError(ValueError):
    """Invalid control transitions are contract errors, not failed trades."""


@dataclass(slots=True)
class CopyPositionControl:
    """One position's bounded control state, owned by a sequential engine."""

    position_id: ContentDigest
    asset_id: AssetId
    buy_decision_position: ChainPosition
    policy: CopyBuyPolicy
    # Fill-dependent fields remain unavailable while a buy is pending or failed.
    status: CopyPositionStatus = field(default=CopyPositionStatus.BUY_PENDING, init=False)
    acquired_tokens_atomic: int = field(default=0, init=False)
    entry_price: TokenPrice | None = field(default=None, init=False)
    buy_fill_position: ChainPosition | None = field(default=None, init=False)
    deadline: ChainPosition | None = field(default=None, init=False)
    # The original trigger is retained through every retry and price recovery.
    exit_reason: CopyExitReason | None = field(default=None, init=False)
    trigger_position: ChainPosition | None = field(default=None, init=False)
    trigger_price: TokenPrice | None = field(default=None, init=False)
    sell_attempt_count: int = field(default=0, init=False)
    attempt_decision: ChainPosition | None = field(default=None, init=False)
    # Retry eligibility and stale-callback detection use exact positions.
    attempt_landing: ChainPosition | None = field(default=None, init=False)
    retry_position: ChainPosition | None = field(default=None, init=False)
    last_evaluation_boundary: int = field(default=-1, init=False)

    def fail_buy(self) -> None:
        """Both pre-submit rejection and landed failure consume entry forever."""

        self._require_status(CopyPositionStatus.BUY_PENDING)
        self.status = CopyPositionStatus.BUY_FAILED

    def fill_buy(
        self,
        *,
        position: ChainPosition,
        # Entry price is based on actual curve input, excluding transaction fees.
        curve_input_atomic: int,
        tokens_atomic: int,
        clock: CompactTransactionClock,
    ) -> None:
        """Call only after the matching buy ledger transaction has committed."""

        self._require_status(CopyPositionStatus.BUY_PENDING)
        self._require_later(position, self.buy_decision_position)
        expected = clock.transaction_after(
            self.buy_decision_position, self.policy.buy_delay_transactions
        )
        # Merely landing later is insufficient: the configured latency must be exact.
        if position.boundary_ordinal != expected.boundary_ordinal:
            raise CopyStateError("buy landing does not match configured transaction delay")
        # A valid price and a complete holding clock are required before opening.
        price = TokenPrice(curve_input_atomic, tokens_atomic)
        deadline = holding_deadline(clock, position, self.policy.maximum_hold_ns)
        # All validation precedes mutation, including the sufficient-tail proof.
        self.entry_price = price
        self.acquired_tokens_atomic = tokens_atomic
        self.buy_fill_position = position
        self.deadline = deadline
        self.status = CopyPositionStatus.OPEN

    def evaluate_exit(
        self,
        *,
        position: ChainPosition,
        # Missing active price does not disable the independent holding deadline.
        current_price: TokenPrice | None,
    ) -> CopyExitReason | None:
        """Evaluate after an atomic observed update or a clock-driven deadline."""

        if self.status is not CopyPositionStatus.OPEN:
            return self.exit_reason
        if self.buy_fill_position is None or self.entry_price is None or self.deadline is None:
            raise CopyStateError("open position has no committed buy")
        # Equality permits a fill notification; an order must still land later.
        self._require_at_or_after(position, self.buy_fill_position)
        if position.boundary_ordinal < self.last_evaluation_boundary:
            raise CopyStateError("exit evaluation moved backwards")
        self.last_evaluation_boundary = position.boundary_ordinal
        # Repeated callbacks between trigger and submission keep the original exit.
        if self.exit_reason is not None:
            return self.exit_reason
        # An inactive curve has no usable current price; its timer still fires.
        reason = (
            None
            if current_price is None
            else self.policy.price_exit(self.entry_price, current_price)
        )
        # Price checks precede the clock condition to implement the declared priority.
        if reason is None and position.boundary_ordinal >= self.deadline.boundary_ordinal:
            reason = CopyExitReason.MAXIMUM_HOLD
        if reason is None:
            return None
        # Only the first trigger wins, irrespective of later market movement.
        self.exit_reason = reason
        self.trigger_position = position
        self.trigger_price = current_price
        return self.exit_reason

    def begin_sell(self, position: ChainPosition, *, clock: CompactTransactionClock) -> int:
        """Consume an attempt before quoting or checking fee balance."""

        if self.status not in (CopyPositionStatus.OPEN, CopyPositionStatus.RETRY_WAIT):
            raise CopyStateError("position cannot start a sell attempt")
        if self.exit_reason is None or self.trigger_position is None:
            raise CopyStateError("sell requires a causal exit trigger")
        # Both first decision and retries must respect their exact release boundary.
        due = self.retry_position if self.retry_position is not None else self.trigger_position
        self._require_at_or_after(position, due)
        if self.sell_attempt_count >= MAXIMUM_SELL_ATTEMPTS:
            raise CopyStateError("sell attempt limit exhausted")
        # Preflight requires this boundary even when quotation will reject the attempt.
        landing = clock.transaction_after(position, self.policy.sell_delay_transactions)
        self.sell_attempt_count += 1
        # Mark pending before any rejection can return control to the scheduler.
        self.attempt_decision = position
        self.attempt_landing = landing
        self.retry_position = None
        self.status = CopyPositionStatus.SELL_PENDING
        return self.sell_attempt_count

    def fail_sell(
        self,
        *,
        attempt: int,
        # Submission stage distinguishes free rejection from a fee-paying landing.
        position: ChainPosition,
        submitted: bool,
        clock: CompactTransactionClock,
    ) -> ChainPosition | None:
        """A pre-submit rejection counts exactly as a landed unsuccessful attempt."""

        self._require_attempt(attempt, position, submitted=submitted)
        if self.sell_attempt_count == MAXIMUM_SELL_ATTEMPTS:
            self.status = CopyPositionStatus.EXHAUSTED
            return None
        # Prove a retry boundary before changing pending state; never truncate a tail.
        retry = holding_deadline(clock, position, SELL_RETRY_DELAY_NS)
        self.retry_position = retry
        self.status = CopyPositionStatus.RETRY_WAIT
        return retry

    def fill_sell(self, *, attempt: int, position: ChainPosition) -> None:
        """Call after a full sell and its account/ledger effects commit atomically."""

        self._require_attempt(attempt, position, submitted=True)
        self.status = CopyPositionStatus.CLOSED

    @property
    def remaining_tokens_atomic(self) -> int:
        """A failure or exhaustion never invents a sale of the acquired tokens."""

        return 0 if self.status is CopyPositionStatus.CLOSED else self.acquired_tokens_atomic

    def _require_status(self, status: CopyPositionStatus) -> None:
        """Reject duplicate/stale notifications before mutating control state."""

        if self.status is not status:
            raise CopyStateError("unexpected copy position state")

    def _require_attempt(
        self,
        attempt: int,
        position: ChainPosition,
        *,
        # The rejection stage is typed rather than inferred from missing amounts.
        submitted: bool,
    ) -> None:
        """A notification belongs to one pending attempt, not a previous retry."""

        self._require_status(CopyPositionStatus.SELL_PENDING)
        require_integer(attempt, "attempt", minimum=1)
        if attempt != self.sell_attempt_count or self.attempt_decision is None:
            raise CopyStateError("stale sell attempt notification")
        # A truthy string must not change whether strict landing causality is checked.
        if type(submitted) is not bool:
            raise CopyStateError("submitted must be a boolean")
        # Pre-submit failure is synchronous; a landed instruction must be later.
        if submitted:
            self._require_later(position, self.attempt_decision)
            if self.attempt_landing is None:
                raise CopyStateError("pending sell has no exact landing boundary")
            # A late or premature callback cannot shorten/extend configured order latency.
            if position.boundary_ordinal != self.attempt_landing.boundary_ordinal:
                raise CopyStateError("sell landing does not match configured transaction delay")
        elif position != self.attempt_decision:
            raise CopyStateError("pre-submit failure must use its decision position")

    @staticmethod
    def _require_at_or_after(position: ChainPosition, start: ChainPosition) -> None:
        """Numeric ordinals are comparable only inside one network/schema."""

        position_chain = (position.network_id, position.position_schema_id)
        start_chain = (start.network_id, start.position_schema_id)
        if position_chain != start_chain:
            raise CopyStateError("position changed network or position schema")
        # A timestamp match cannot make a backward transaction boundary causal.
        if position.boundary_ordinal < start.boundary_ordinal:
            raise CopyStateError("position precedes its causal boundary")

    @classmethod
    def _require_later(cls, position: ChainPosition, start: ChainPosition) -> None:
        """A fill cannot execute in the transaction that created its decision."""

        cls._require_at_or_after(position, start)
        if position.boundary_ordinal == start.boundary_ordinal:
            raise CopyStateError("landing must be strictly after decision")


def holding_deadline(
    clock: CompactTransactionClock,
    position: ChainPosition,
    duration_ns: int,
) -> ChainPosition:
    """Ceil a positive modeled duration to a real nonempty clock boundary."""

    require_integer(duration_ns, "duration_ns", minimum=1)
    return clock.first_nonempty_transaction_at_or_after(
        after_position=position,
        target_time_ns=clock.block_time_for_position(position) + duration_ns,
    )


def maximum_settlement_position(
    clock: CompactTransactionClock,
    signal: ChainPosition,
    policy: CopyBuyPolicy,
) -> ChainPosition:
    """Prove the longest timeout/four-landed-failures path for one signal."""

    return maximum_copy_settlement_position(
        clock,
        signal,
        observation_delay_transactions=policy.observation_delay_transactions,
        buy_delay_transactions=policy.buy_delay_transactions,
        # Maximum holding duration is followed by the complete four-attempt sale path.
        maximum_hold_ns=policy.maximum_hold_ns,
        sell_delay_transactions=policy.sell_delay_transactions,
    )


def maximum_copy_settlement_position(
    clock: CompactTransactionClock,
    signal: ChainPosition,
    *,
    observation_delay_transactions: int,
    # All transaction delays remain separate from the modeled duration requirement.
    buy_delay_transactions: int,
    maximum_hold_ns: int,
    sell_delay_transactions: int,
) -> ChainPosition:
    """Preparation proves the timing path without inventing a budget or price policy."""

    require_integer(observation_delay_transactions, "observation_delay_transactions")
    require_integer(buy_delay_transactions, "buy_delay_transactions", minimum=1)
    require_integer(maximum_hold_ns, "maximum_hold_ns", minimum=1)
    require_integer(sell_delay_transactions, "sell_delay_transactions", minimum=1)
    # Only authoritative produced/nonempty transaction boundaries enter this path.

    clock.require_position(signal)
    decision = signal
    if observation_delay_transactions:
        decision = clock.transaction_after(signal, observation_delay_transactions)
    buy = clock.transaction_after(decision, buy_delay_transactions)
    # A price trigger can only shorten the maximum holding path.
    sell_decision = holding_deadline(clock, buy, maximum_hold_ns)
    for attempt in range(MAXIMUM_SELL_ATTEMPTS):
        landing = clock.transaction_after(sell_decision, sell_delay_transactions)
        if attempt + 1 < MAXIMUM_SELL_ATTEMPTS:
            sell_decision = holding_deadline(clock, landing, SELL_RETRY_DELAY_NS)
    # A final landing is always assigned because the fixed attempt count is positive.
    return landing
