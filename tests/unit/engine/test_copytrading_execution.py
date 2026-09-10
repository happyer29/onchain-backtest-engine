"""Financial copy-buy execution with real Pump quotes and the shared ledger reducer."""

from dataclasses import replace

import pytest
import test_sniping_engine as base

# Real token/curve quote semantics are shared with the existing Sniping oracle.
from backtest.domain.copytrading import CopyBuyIntent, CopyBuyPolicy
from backtest.domain.execution import ExecutionMode
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import AccountId
from backtest.domain.ledger import AccountKind

# The controller owns retry timing while this suite checks actual financial effects.
from backtest.engine.copytrading_execution import (
    CopyAttemptStatus,
    CopyExecutionPosition,
    CopyOrderExecutor,
)

# Assertions inspect real ledger and account reducers rather than a shadow cash counter.
from backtest.engine.copytrading_state import CopyPositionStatus
from backtest.engine.portfolio import PortfolioState
from backtest.engine.sniping_contracts import ProtocolExecutionRejected
from backtest.engine.wallet_accounts import (
    WalletProvisioningReducer,
    # Initial UVA state is explicit so failed-entry rollback can be verified.
    initial_wallet_provisioning_state,
)

# Signer-bearing payloads identify real historical BUYs, independent of creation actors.
from backtest.plugins.protocols.pumpfun.copybuy import PumpfunCopyBuyProtocolRuntime
from backtest.plugins.protocols.pumpfun.copybuy_payload import (
    COPYBUY_TRADE_PAYLOAD_SCHEMA,
    CopyBuyTradePayload,
)

# The signer identifies copied trades and is independent of the mint creator.
SIGNER = AccountId("4YK36Hp1f5ZN9Br1JroURgXk2f5R7CNunRPXkpdvkGmU")


def _setup(*, balance=10_000_000_000, mode=ExecutionMode.EXOGENOUS_REPLAY):
    """A bounded forty-second clock proves even four failed full sale attempts."""
    _, prototype, network = base._components()
    clock = base._clock(
        tuple((block, 10, base.BASE_TIME_S + block - 100) for block in range(100, 140))
    )
    # Historical and observed reducers start from equal data but remain different objects.
    historical = PumpfunCopyBuyProtocolRuntime(
        quote_asset_id=base.SOL,
        fee_profile=prototype.fee_profile,
        protocol_version=prototype.protocol_version,
    )
    # Observed and historical state advance independently but start from equal bytes.
    observed = PumpfunCopyBuyProtocolRuntime(
        quote_asset_id=base.SOL,
        fee_profile=prototype.fee_profile,
        protocol_version=prototype.protocol_version,
    )
    # The canonical trade uses the separate signer-bearing copy payload.
    trade = replace(
        base._trade(base._state(), block=100, transaction=1, event_index=0, group=2),
        protocol_payload_schema=COPYBUY_TRADE_PAYLOAD_SCHEMA,
        protocol_payload=CopyBuyTradePayload(SIGNER, base._state()).encode(),
    )
    # Source creation is earlier than the copied purchase, including a different signer.
    for runtime in (historical, observed):
        runtime.apply_group((base._launch(),), effective_at_unix_s=base.BASE_TIME_S)
        signals = runtime.apply_group((trade,), effective_at_unix_s=base.BASE_TIME_S)
    policy = CopyBuyPolicy(1_000_000_000, 2000, 1000, 5, 0, 2, 3, 0, 0)
    # Unit-only identity never enters a published artifact or production resolver.
    intent = CopyBuyIntent(
        domain_digest("test.copy-execution", 1),
        signals[0],
        replace(signals[0].position, event_index=None),
        policy,
        # The chosen mode affects sell solvency without changing the signal or price policy.
        mode,
    )
    portfolio, ledger = PortfolioState({base.SOL: balance}), []
    accounts = WalletProvisioningReducer(
        initial_wallet_provisioning_state(
            # A fresh wallet must reserve its one-time UVA in addition to the per-mint ATA.
            base.WalletUvaInitialState.FRESH,
            uva_schema_id=base.PUMPFUN_UVA_SCHEMA_ID,
        )
    )
    # The unit sink records committed rows for conservation and identity reconciliation.
    executor = CopyOrderExecutor(
        clock=clock,
        historical=historical,
        observed=observed,
        network_costs=network,
        # Ledger collection captures every actual reservation and settlement posting.
        portfolio=portfolio,
        accounts=accounts,
        append_ledger=ledger.append,
    )
    return executor, CopyExecutionPosition(intent), ledger


def _buy(executor, state):
    """Drive one actual submitted buy through its own delayed landing."""
    attempt = executor.begin_buy(state)
    assert attempt.status is CopyAttemptStatus.SUBMITTED
    executor.land(state, attempt.expected_landing)
    assert state.control.status is CopyPositionStatus.OPEN


def _trigger(executor, state):
    """The maximum-hold clock works even without any later Pump market events."""
    deadline = state.control.deadline
    assert deadline is not None
    # The first suitable deadline boundary must produce a latched exit reason.
    assert (
        state.control.evaluate_exit(
            position=deadline,
            current_price=executor.observed.current_price(state.intent),
            # The timer is measured from the own fill, not the leader transaction.
        )
        is not None
    )
    return deadline


def _charged(ledger, kind):
    """Financial assertions are derived from committed postings, not shadow counters."""
    return sum(
        posting.amount_atomic
        for transaction in ledger
        for posting in transaction.postings
        if posting.account.kind is kind
        # Summing postings validates monetary effects independently of attempt metadata.
    )


def test_full_exit_reconciles_cash_and_refunds_only_mint_ata() -> None:
    executor, state, ledger = _setup()
    _buy(executor, state)
    buy = state.attempts[0]
    # Fee-free entry uses the actual curve leg, excluding both network and Pump fees.
    assert (
        state.control.entry_price.quote_atomic * buy.landing_quote.amount_out_atomic
        == state.control.entry_price.token_atomic * buy.landing_quote.venue_input_atomic
    )
    sale = executor.begin_sell(state, _trigger(executor, state))
    # An order created at timeout still waits the independent three-transaction latency.
    assert (
        executor.clock.global_transaction_index(sale.expected_landing)
        - executor.clock.global_transaction_index(sale.decision)
        == 3
    )
    # A successful landing must consume the entire acquired token inventory.
    executor.land(state, sale.expected_landing)
    assert state.control.status is CopyPositionStatus.CLOSED
    assert executor.portfolio.available(state.intent.asset_id) == 0
    # Ledger correlation equals spendable cash movement, including all fees and rent.
    assert (
        executor.cashflows.amount(state.intent.roundtrip_id, base.SOL)
        == executor.portfolio.available(base.SOL) - 10_000_000_000
    )
    assert _charged(ledger, AccountKind.NETWORK_FEE) == sum(
        # Only landed instructions contribute base and priority fees.
        item.paid_network_fee_atomic
        for item in state.attempts
    )
    assert _charged(ledger, AccountKind.PORTFOLIO_LOCKED) == 1_844_400
    assert all(transaction.reason.startswith("COPY_") for transaction in ledger)
    # Every posting transaction and every attempted order has a distinct immutable ID.
    assert len({transaction.transaction_id for transaction in ledger}) == len(ledger)
    assert len({item.order_id for item in state.attempts}) == 2


def test_insufficient_buy_funds_has_no_ledger_or_account_mutation() -> None:
    executor, state, ledger = _setup(balance=1)
    attempt = executor.begin_buy(state)
    assert attempt.status is CopyAttemptStatus.REJECTED
    assert attempt.failure_code == "INSUFFICIENT_FUNDS"
    # Consumed entry cannot turn a funding rejection into a later purchase.
    assert state.control.status is CopyPositionStatus.BUY_FAILED
    assert ledger == [] and not executor.accounts.state.uva_exists
    with pytest.raises(ValueError, match="again"):
        executor.begin_buy(state)


def test_four_landed_failures_charge_four_fees_and_retain_tokens(monkeypatch) -> None:
    executor, state, ledger = _setup()
    _buy(executor, state)
    position = _trigger(executor, state)

    # Reference remains valid, while each actual delayed landing fails on the venue.
    def unavailable(*args, **kwargs):
        raise ProtocolExecutionRejected("CURVE_COMPLETED")

    # Historical rejection after submission models a landed failure rather than quote refusal.
    monkeypatch.setattr(executor.historical, "quote_sell", unavailable)
    for number in range(1, 5):
        attempt = executor.begin_sell(state, position)
        executor.land(state, attempt.expected_landing)
        # Retry waits start after failure and do not replace order latency.
        assert attempt.number == number and attempt.status is CopyAttemptStatus.FAILED
        assert attempt.paid_network_fee_atomic > 0
        if number < 4:
            position = state.control.retry_position
            assert (
                # Every failed landing restarts the two-second wait before a new decision.
                executor.clock.block_time_for_position(position)
                >= executor.clock.block_time_for_position(attempt.expected_landing) + 2_000_000_000
            )
    # The exhausted position remains economically open with the original account deposit.
    assert state.control.status is CopyPositionStatus.EXHAUSTED
    assert (
        executor.portfolio.available(state.intent.asset_id) == state.control.acquired_tokens_atomic
    )
    assert _charged(ledger, AccountKind.NETWORK_FEE) == sum(
        # All four landed failures pay fees while preserving the acquired tokens.
        item.paid_network_fee_atomic
        for item in state.attempts
    )
    # Failed sales add network fees but cannot charge new Pump protocol components.
    assert (
        _charged(ledger, AccountKind.PROTOCOL_FEE)
        == state.attempts[0].landing_quote.protocol_fee_atomic
        # Failed exits add no Pump fee beyond the successful entry.
    )
    assert len(ledger) == 10 and len(state.attempts) == 5
    # A fifth sale attempt fails before it can reserve tokens or pay another fee.
    with pytest.raises(ValueError):
        executor.begin_sell(state, position)
    assert len(ledger) == 10


def test_presubmit_quote_rejections_consume_four_attempts_without_fee(monkeypatch) -> None:
    executor, state, ledger = _setup()
    _buy(executor, state)
    position = _trigger(executor, state)

    # No available quote means no submitted instruction and hence no fee posting.
    def unavailable(*args, **kwargs):
        raise ProtocolExecutionRejected("CURVE_MIGRATED")

    monkeypatch.setattr(executor.observed, "quote_sell", unavailable)
    for number in range(1, 5):
        attempt = executor.begin_sell(state, position)
        # The retry timer starts at this rejected decision, not an invented landing.
        assert attempt.status is CopyAttemptStatus.REJECTED
        assert attempt.landed_at is None and attempt.paid_network_fee_atomic == 0
        if number < 4:
            position = state.control.retry_position
    # Four free pre-submit refusals exhaust the position without adding ledger transactions.
    assert state.control.status is CopyPositionStatus.EXHAUSTED
    assert len(ledger) == 2


def test_landed_buy_failure_rolls_back_deposits_and_charges_network_only(monkeypatch) -> None:
    executor, state, ledger = _setup()
    attempt = executor.begin_buy(state)

    # Completion after submission must fail the original Pump instruction.
    def unavailable(*args, **kwargs):
        raise ProtocolExecutionRejected("CURVE_COMPLETED")

    monkeypatch.setattr(executor.historical, "quote_buy", unavailable)
    executor.land(state, attempt.expected_landing)
    assert state.control.status is CopyPositionStatus.BUY_FAILED
    # No token acquisition, Pump fee, cashback or account creation survives failure.
    assert (
        executor.portfolio.available(base.SOL) == 10_000_000_000 - attempt.paid_network_fee_atomic
    )
    assert not executor.accounts.state.uva_exists
    assert _charged(ledger, AccountKind.PROTOCOL_FEE) == 0
    # Failed buy provisioning cannot leak a locked account deposit.
    assert _charged(ledger, AccountKind.PORTFOLIO_LOCKED) == 0


def test_wrong_landing_is_rejected_before_ledger_mutation() -> None:
    executor, state, ledger = _setup()
    attempt = executor.begin_buy(state)
    later = executor.clock.transaction_after(attempt.expected_landing, 1)
    # A late notification must fail before the reserved wallet balance changes.
    with pytest.raises(ValueError, match="exact boundary"):
        executor.land(state, later)
    # The reservation is still pending; no fictional failed landing is charged.
    assert len(ledger) == 1
    assert attempt.status is CopyAttemptStatus.SUBMITTED
