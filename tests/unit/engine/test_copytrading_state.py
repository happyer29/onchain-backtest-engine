"""Causal copy-buy policy checks independent of storage and financial reducers."""

from dataclasses import replace

import pytest

# Use the same typed chain contract as canonical replay, including skipped blocks.
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
    ChainPosition,
)

# Price policy uses integer ratios rather than quote fees or account deposits.
from backtest.domain.copytrading import CopyBuyPolicy, CopyExitReason, TokenPrice

# Control state deliberately contains no substitute portfolio or PnL accumulator.
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import AssetId, NetworkId
from backtest.engine.copytrading_state import (
    CopyPositionControl,
    CopyPositionStatus,
    # Tail proof uses the same duration/transaction primitives as retries.
    CopyStateError,
    maximum_settlement_position,
)
from backtest.engine.transaction_clock import CompactTransactionClock, TransactionClockError


def _policy() -> CopyBuyPolicy:
    """Distinct delays ensure retry waits cannot accidentally replace order delay."""

    return CopyBuyPolicy(1_000, 2_000, 1_000, 10, 200, 5, 7, 100, 200)


def _position(block: int, transaction: int = 0) -> ChainPosition:
    """One eventless real transaction boundary in the fixture network."""

    return ChainPosition(
        SOLANA_MAINNET_NETWORK_ID,
        BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        block,
        transaction,
        # Clock boundaries have no fabricated instruction index.
        None,
    )


def _clock(*, blocks: int = 40) -> CompactTransactionClock:
    """No Pump event is needed to advance modeled time or non-Pump transactions."""

    return CompactTransactionClock(
        SOLANA_MAINNET_NETWORK_ID,
        BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        tuple(range(1, blocks + 1)),
        (100,) * blocks,
        # Prefixes are authoritative transaction counts, not event counts.
        tuple(index * 100 for index in range(blocks)),
        tuple(block * 1_000_000_000 for block in range(1, blocks + 1)),
    )


def _control() -> CopyPositionControl:
    """The fill price is 10 atomic SOL units/token before any fees or rent."""

    control = CopyPositionControl(
        domain_digest("test.copy-position", 1), AssetId("token"), _position(1), _policy()
    )
    # Actual entry lands after the configured five global transactions.
    control.fill_buy(
        position=_position(1, 5), curve_input_atomic=1_000, tokens_atomic=100, clock=_clock()
    )
    return control


@pytest.mark.parametrize(
    ("price", "reason"),
    # Inclusive thresholds distinguish one atomic unit on either side.
    [
        (TokenPrice(1200, 100), CopyExitReason.TAKE_PROFIT),
        (TokenPrice(1199, 100), None),
        # Stop-loss has the same inclusive equality contract as take-profit.
        (TokenPrice(900, 100), CopyExitReason.STOP_LOSS),
        (TokenPrice(901, 100), None),
    ],
)
# Boundary prices distinguish inclusive TP/SL from the nearest non-triggering integer.
def test_price_thresholds_are_exact_and_fee_free(
    price: TokenPrice, reason: CopyExitReason | None
) -> None:
    """Price policy compares atomic ratios without using a liquidation PnL."""

    assert _policy().price_exit(TokenPrice(1000, 100), price) is reason


def test_price_normalization_and_large_integer_comparison() -> None:
    """No precision loss is allowed beyond floating-point integer precision."""

    assert TokenPrice(1000, 100) == TokenPrice(10, 1)
    large = 2**100 + 1
    entry = TokenPrice(large, 7)
    exact_tp = TokenPrice(large * 12, 70)
    # Subtracting one atomic unit must move a quote below the exact TP threshold.
    assert _policy().price_exit(entry, exact_tp) is CopyExitReason.TAKE_PROFIT
    assert _policy().price_exit(entry, TokenPrice(large * 12 - 1, 70)) is None


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_invalid_prices_are_rejected(value: int) -> None:
    """Dust source rows do not authorize zero or fractional execution prices."""

    with pytest.raises(ValueError):
        TokenPrice(value, 1)
    with pytest.raises(ValueError):
        TokenPrice(1, value)


@pytest.mark.parametrize(
    ("field", "value"),
    # Every public numeric operand is validated before identity is computed.
    [
        ("take_profit_bps", 0),
        ("stop_loss_bps", 10001),
        ("maximum_hold_seconds", 0),
        ("gross_buy_budget_atomic", True),
        # Observation can be immediate, while order delays must be positive.
        ("observation_delay_transactions", -1),
        ("buy_delay_transactions", 0),
        ("sell_delay_transactions", 0),
        # Slippage is independently bounded and never coerced into a threshold.
        ("buy_slippage_bps", -1),
        ("sell_slippage_bps", 10001),
    ],
)
def test_invalid_policy_fails_before_execution(field: str, value: int) -> None:
    """Fixed retry rules cannot be substituted through numeric coercion."""

    with pytest.raises(ValueError):
        replace(_policy(), **{field: value})


def test_policy_identity_materializes_fixed_and_selectable_operands() -> None:
    """A changed latency or threshold requires a new configured policy identity."""

    policy = _policy()
    assert policy.identity != replace(policy, sell_delay_transactions=8).identity
    assert policy.identity != replace(policy, take_profit_bps=2001).identity
    assert policy.document()["maximum_sell_attempts"] == 4
    assert policy.document()["consume_mint_on_signal"] is True


def test_timeout_from_actual_fill_and_price_priority() -> None:
    """A quiet market still exits; a concurrent price condition takes priority."""

    control = _control()
    assert control.deadline == _position(11)
    assert control.evaluate_exit(position=_position(10, 99), current_price=None) is None
    # The independent timeout becomes eligible exactly at the rounded deadline.
    assert (
        control.evaluate_exit(position=_position(11), current_price=None)
        is CopyExitReason.MAXIMUM_HOLD
    )
    # A separate position at the same deadline proves SL priority over timeout.
    stopped = _control()
    assert (
        stopped.evaluate_exit(position=_position(11), current_price=TokenPrice(9, 1))
        is CopyExitReason.STOP_LOSS
    )
    # Later recovery cannot overwrite the original reason before submission.
    assert (
        stopped.evaluate_exit(position=_position(12), current_price=TokenPrice(20, 1))
        is CopyExitReason.STOP_LOSS
    )


@pytest.mark.parametrize("submitted", [False, True])
def test_four_failed_sales_wait_two_seconds_and_preserve_tokens(submitted: bool) -> None:
    """Pre-submit rejection and landed failure both consume the fixed attempt limit."""

    control = _control()
    clock = _clock()
    decision = _position(11)
    control.evaluate_exit(position=decision, current_price=None)
    # A landing failure waits from its landing, followed by a new order delay.
    for number in range(1, 5):
        assert control.begin_sell(decision, clock=_clock()) == number
        failure = clock.transaction_after(decision, 7) if submitted else decision
        # Both stages retain the tokens and spend one attempt before scheduling retry.
        retry = control.fail_sell(
            attempt=number, position=failure, submitted=submitted, clock=clock
        )
        assert control.remaining_tokens_atomic == 100
        # There is no fifth attempt and no invented fill after exhaustion.
        if number == 4:
            assert retry is None
            break
        assert retry == _position(failure.block_ordinal + 2)
        decision = retry
    # Exhaustion preserves both the original reason and the position's ownership.
    assert control.status is CopyPositionStatus.EXHAUSTED
    assert control.exit_reason is CopyExitReason.MAXIMUM_HOLD
    with pytest.raises(CopyStateError):
        control.begin_sell(_position(30), clock=_clock())


def test_retry_cannot_start_early_and_has_no_duplicate_pending_sale() -> None:
    """Retry notifications are correlated to an attempt and cannot fire twice."""

    control = _control()
    control.evaluate_exit(position=_position(2), current_price=TokenPrice(12, 1))
    control.begin_sell(_position(2), clock=_clock())
    with pytest.raises(CopyStateError):
        control.begin_sell(_position(2, 1), clock=_clock())
    # A synchronous rejection consumes attempt one and schedules t+2s.
    assert control.fail_sell(
        attempt=1, position=_position(2), submitted=False, clock=_clock()
    ) == _position(4)
    # One earlier transaction is still too early, even after another callback.
    with pytest.raises(CopyStateError):
        control.begin_sell(_position(3, 99), clock=_clock())
    assert control.begin_sell(_position(4), clock=_clock()) == 2
    # A late result for the old attempt cannot settle the new reservation.
    with pytest.raises(CopyStateError):
        control.fill_sell(attempt=1, position=_position(4, 7))
    control.fill_sell(attempt=2, position=_position(4, 7))
    assert control.remaining_tokens_atomic == 0
    assert control.status is CopyPositionStatus.CLOSED


def test_failed_buy_never_creates_a_sell() -> None:
    """This control has no transition from failed entry back to pending entry."""

    control = CopyPositionControl(
        domain_digest("test.copy", 2), AssetId("token"), _position(1), _policy()
    )
    control.fail_buy()
    # No price observation can turn a failed entry into a token position.
    assert control.evaluate_exit(position=_position(20), current_price=TokenPrice(100, 1)) is None
    assert control.remaining_tokens_atomic == 0
    # A failed entry has neither an exit trigger nor any sell attempt budget to use.
    with pytest.raises(CopyStateError):
        control.begin_sell(_position(20), clock=_clock())
    with pytest.raises(CopyStateError):
        control.fail_buy()


def test_short_tail_rejects_without_mutating_buy_control() -> None:
    """An insufficient duration clock cannot become a truncated successful position."""

    control = CopyPositionControl(
        domain_digest("test.copy", 3), AssetId("token"), _position(1), _policy()
    )
    # The buy landing fits, but its holding deadline does not fit this short clock.
    with pytest.raises(TransactionClockError):
        control.fill_buy(
            position=_position(1, 5),
            curve_input_atomic=1000,
            tokens_atomic=100,
            # A missing tail must fail before entry price and ownership become visible.
            clock=_clock(blocks=5),
        )
    assert control.status is CopyPositionStatus.BUY_PENDING
    assert control.entry_price is None


def test_settlement_proof_covers_observation_hold_and_all_retry_delays() -> None:
    """The cap must cover the worst landed path rather than just the first sale."""

    assert maximum_settlement_position(_clock(), _position(1), _policy()) == _position(19, 7)
    with pytest.raises(TransactionClockError):
        maximum_settlement_position(_clock(blocks=18), _position(1), _policy())
    immediate = replace(_policy(), observation_delay_transactions=0)
    assert maximum_settlement_position(_clock(), _position(1), immediate) == _position(17, 7)


def test_causality_rejects_same_boundary_fill_and_backward_observation() -> None:
    """Chain boundaries, not callback call order alone, enforce causality."""

    control = _control()
    control.evaluate_exit(position=_position(5), current_price=TokenPrice(10, 1))
    with pytest.raises(CopyStateError):
        control.evaluate_exit(position=_position(4), current_price=TokenPrice(12, 1))
    # Even a triggered order cannot fill in its own decision transaction.
    control.evaluate_exit(position=_position(5), current_price=TokenPrice(12, 1))
    control.begin_sell(_position(5), clock=_clock())
    with pytest.raises(CopyStateError):
        control.fill_sell(attempt=1, position=_position(5))


@pytest.mark.parametrize("transaction", [4, 6])
def test_buy_landing_must_match_the_exact_delay(transaction: int) -> None:
    """Being strictly later alone does not prove the configured five-tx delay."""

    control = CopyPositionControl(
        domain_digest("test.copy", 4), AssetId("token"), _position(1), _policy()
    )
    # An incorrect landing cannot open the position or establish a price baseline.
    with pytest.raises(CopyStateError, match="configured transaction delay"):
        control.fill_buy(
            position=_position(1, transaction),
            curve_input_atomic=1000,
            tokens_atomic=100,
            # A complete clock isolates latency validation from insufficient-tail errors.
            clock=_clock(),
        )
    # Validation is atomic with respect to the position-control state.
    assert control.status is CopyPositionStatus.BUY_PENDING
    assert control.entry_price is None


@pytest.mark.parametrize("transaction", [6, 8])
def test_sell_landing_must_match_its_pending_attempt_delay(transaction: int) -> None:
    """A premature or late callback cannot settle the pending seven-tx order."""

    control = _control()
    control.evaluate_exit(position=_position(2), current_price=TokenPrice(12, 1))
    control.begin_sell(_position(2), clock=_clock())
    # Reject the mismatched landing while retaining both tokens and pending attempt.
    with pytest.raises(CopyStateError, match="configured transaction delay"):
        control.fill_sell(attempt=1, position=_position(2, transaction))
    assert control.status is CopyPositionStatus.SELL_PENDING
    assert control.remaining_tokens_atomic == 100


def test_cross_network_observation_and_asynchronous_presubmit_failure_are_rejected() -> None:
    """Neither matching ordinals nor a truthy stage substitutes for typed causality."""

    control = _control()
    foreign = replace(_position(2), network_id=NetworkId("eip155:1"))
    with pytest.raises(CopyStateError, match="network"):
        control.evaluate_exit(position=foreign, current_price=TokenPrice(12, 1))
    # A pre-submit failure occurs at the same decision, with no elapsed order delay.
    control.evaluate_exit(position=_position(2), current_price=TokenPrice(12, 1))
    control.begin_sell(_position(2), clock=_clock())
    with pytest.raises(CopyStateError, match="decision position"):
        control.fail_sell(attempt=1, position=_position(2, 1), submitted=False, clock=_clock())
    # A failed contract check is not a retryable rejection and does not spend attempt two.
    assert control.status is CopyPositionStatus.SELL_PENDING
    assert control.sell_attempt_count == 1


def test_retry_clock_skips_zero_transaction_blocks() -> None:
    """A produced empty block cannot become a synthetic decision transaction."""

    clock = CompactTransactionClock(
        SOLANA_MAINNET_NETWORK_ID,
        BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        (1, 2, 3, 4, 5, 6, 20),
        (100, 100, 0, 0, 0, 100, 100),
        # Empty blocks retain repeated prefixes; the timer finds the next real boundary.
        (0, 100, 200, 200, 200, 200, 300),
        (
            1_000_000_000,
            2_000_000_000,
            3_000_000_000,
            # These empty produced blocks must never become invented transactions.
            4_000_000_000,
            5_000_000_000,
            6_000_000_000,
            # Keep a bounded nonempty suffix beyond the retry being checked.
            20_000_000_000,
        ),
    )
    # The failure at t=2 needs t>=4, but t=4 and t=5 have no transactions.
    control = _control()
    control.evaluate_exit(position=_position(2), current_price=TokenPrice(12, 1))
    control.begin_sell(_position(2), clock=clock)
    # The first suitable boundary is t=6, not the empty t=4 duration target.
    assert control.fail_sell(
        attempt=1, position=_position(2), submitted=False, clock=clock
    ) == _position(6)
