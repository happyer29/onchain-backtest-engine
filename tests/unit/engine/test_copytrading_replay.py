"""Transaction-atomic delayed copy replay with independent orders and holding timers."""

from dataclasses import replace

import pytest
import test_copytrading_execution as execution
import test_sniping_engine as base

# A real BUY signal remains the target across observation and execution delay.
from backtest.domain.copytrading import CopyBuyPolicy, CopyExitReason
from backtest.domain.execution import ExecutionMode
from backtest.domain.identifiers import BundleId
from backtest.domain.time import BlockRange
from backtest.engine.copytrading import CopyBuyReferenceEngine, CopyReplayLimits

# Unit sinks observe actual financial records; they never stand in for published artifacts.
from backtest.engine.copytrading_execution import CopyAttemptStatus, CopyOrderExecutor
from backtest.engine.copytrading_state import CopyPositionStatus
from backtest.engine.portfolio import PortfolioState
from backtest.engine.sniping_contracts import ProtocolContractError, ProtocolExecutionRejected
from backtest.engine.transaction_clock import TransactionClockError

# Provisioning remains the shared ATA/UVA reducer across both execution modes.
from backtest.engine.wallet_accounts import (
    WalletProvisioningReducer,
    initial_wallet_provisioning_state,
)
from backtest.plugins.protocols.pumpfun.copybuy import PumpfunCopyBuyProtocolRuntime

# Protocol payloads retain the copied signer while strategy owns permanent mint consumption.
from backtest.plugins.protocols.pumpfun.copybuy_payload import (
    COPYBUY_TRADE_PAYLOAD_SCHEMA,
    CopyBuyTradePayload,
)
from backtest.plugins.strategies.pumpfun_copybuy import PumpfunCopyBuyStrategy


def _trade(transaction, *, state=None, event_index=0, group=None):
    """An exact source signer accompanies the same integer state used for execution."""
    state = base._state() if state is None else state
    event = base._trade(
        state,
        block=100,
        transaction=transaction,
        # Same-transaction test events use explicit instruction order and group identity.
        event_index=event_index,
        group=group or transaction + 1,
    )
    return replace(
        event,
        # This helper changes actor payload only, leaving the original canonical envelope intact.
        protocol_payload_schema=COPYBUY_TRADE_PAYLOAD_SCHEMA,
        protocol_payload=CopyBuyTradePayload(execution.SIGNER, state).encode(),
    )


def _runner(events, *, observation_delay=0, balance=10_000_000_000, blocks=40):
    """All runtime instances start empty; validation cannot advance execution views."""
    _, prototype, network = base._components()
    clock = base._clock(
        tuple((block, 10, base.BASE_TIME_S + block - 100) for block in range(100, 100 + blocks))
    )

    def runtime():
        return PumpfunCopyBuyProtocolRuntime(
            quote_asset_id=base.SOL,
            fee_profile=prototype.fee_profile,
            protocol_version=prototype.protocol_version,
            # The validation pass must receive a fresh reducer as well as execution and observation.
        )

    # The trial policy has different observation, buy and sell transaction delays.
    policy = CopyBuyPolicy(1_000_000_000, 2000, 1000, 5, observation_delay, 2, 3, 0, 0)
    strategy = PumpfunCopyBuyStrategy(
        signing_wallets=(execution.SIGNER,),
        policy=policy,
        bundle_id=BundleId("1" * 64),
        # A fixed test bundle and quote asset keep the policy test independent of discovery.
        execution_mode=ExecutionMode.EXOGENOUS_REPLAY,
        quote_asset_id=base.SOL,
        maximum_consumed_mints=100,
    )
    # The state/ledger fixtures are in memory only; application publication is tested separately.
    ledger, positions = [], []
    accounts = WalletProvisioningReducer(
        initial_wallet_provisioning_state(
            base.WalletUvaInitialState.FRESH, uva_schema_id=base.PUMPFUN_UVA_SCHEMA_ID
        )
        # Wallet account provisioning starts afresh for every independent replay.
    )
    executor = CopyOrderExecutor(
        clock=clock,
        historical=runtime(),
        observed=runtime(),
        # The two protocol views may diverge under delayed observation without sharing state.
        network_costs=network,
        portfolio=PortfolioState({base.SOL: balance}),
        accounts=accounts,
        append_ledger=ledger.append,
    )
    # Source range is explicit and excludes every later settlement-only transaction.
    arguments = {
        "source": base._Source(events),
        "decision_range": BlockRange(clock.network_id, clock.position_schema_id, 100, 101),
        "strategy": strategy,
        "executor": executor,
        # Validation has its own reducer and runs before the execution wallet can mutate.
        "validation_protocol": runtime(),
        "limits": CopyReplayLimits(1000, 100, 1000),
        "append_position": positions.append,
    }
    return arguments, positions, ledger


def test_copy_replay_copies_once_and_sells_on_own_price_trigger() -> None:
    high = base._state(virtual_sol_reserves_lamports=42_000_000_000)
    events = (base._launch(), _trade(1), _trade(5, state=high), _trade(6, state=high))
    arguments, positions, ledger = _runner(events)
    counts = CopyBuyReferenceEngine().run(**arguments)
    # Repeated purchases do not reopen the token or substitute the leader's exit.
    assert counts.positions == 1 and counts.historical_events == len(events)
    state = positions[0]
    assert state.control.status is CopyPositionStatus.CLOSED
    assert state.control.exit_reason is CopyExitReason.TAKE_PROFIT
    assert len(state.attempts) == 2 and len(ledger) == 4
    # Buy and sell land after their independently configured global transaction delays.
    assert state.attempts[0].landed_at.transaction_index == 3
    assert state.attempts[1].decision.transaction_index == 5
    assert state.attempts[1].landed_at.transaction_index == 8


def test_fill_notification_latches_price_exit_without_revisiting_acceptance_phase() -> None:
    arguments, positions, ledger = _runner((base._launch(), _trade(1)))
    original = arguments["strategy"]
    arguments["strategy"] = PumpfunCopyBuyStrategy(
        signing_wallets=(execution.SIGNER,),
        # A one-basis-point stop exposes an immediate own-fill price trigger.
        policy=replace(original.policy, stop_loss_bps=1),
        bundle_id=original.bundle_id,
        execution_mode=ExecutionMode.EXOGENOUS_REPLAY,
        # A small stop threshold makes the own fill's average price immediately trigger SL.
        quote_asset_id=base.SOL,
        maximum_consumed_mints=100,
    )
    previous = arguments["executor"]
    audit = []
    # Audit phase records prove that notification cannot retroactively revisit acceptance.
    arguments["executor"] = CopyOrderExecutor(
        clock=previous.clock,
        historical=previous.historical,
        observed=previous.observed,
        network_costs=previous.network_costs,
        # Keep the original wallet and costs while collecting phase evidence.
        portfolio=previous.portfolio,
        accounts=previous.accounts,
        # Public output hooks verify the scheduler's externally observable phase order.
        append_ledger=ledger.append,
        append_audit=audit.append,
    )
    CopyBuyReferenceEngine().run(**arguments)
    state = positions[0]
    # The latched trigger is at fill, but submission must wait for a future boundary.
    buy, sell = state.attempts
    assert state.control.trigger_position == buy.landed_at
    assert sell.decision == arguments["executor"].clock.transaction_after(buy.landed_at, 1)
    # Sell latency still starts at its actual decision, independent of notification scheduling.
    assert sell.expected_landing == arguments["executor"].clock.transaction_after(sell.decision, 3)
    instants = [(row["boundary_ordinal"], row["phase"]) for row in audit]
    assert instants == sorted(instants) and state.control.status is CopyPositionStatus.CLOSED


def test_landing_uses_history_while_signal_observes_delayed_state() -> None:
    high = base._state(virtual_sol_reserves_lamports=42_000_000_000)
    arguments, positions, ledger = _runner(
        (base._launch(), _trade(1), _trade(5, state=high), _trade(6, state=high)),
        observation_delay=2,
        # Delayed reference state and contemporaneous landing state intentionally differ.
    )
    CopyBuyReferenceEngine().run(**arguments)
    attempt = positions[0].attempts[0]
    # Observation at tx3 quotes old state; landing at tx5 sees the whole newer transaction.
    assert attempt.decision.transaction_index == 3
    assert attempt.landed_at.transaction_index == 5
    assert attempt.status is CopyAttemptStatus.FAILED
    assert attempt.failure_code == "MINIMUM_OUTPUT_NOT_MET"
    # Even after the new state is observed, the failed mint cannot be bought again.
    assert len(positions) == 1 and len(ledger) == 2
    assert positions[0].control.status is CopyPositionStatus.BUY_FAILED


def test_quiet_market_timeout_and_four_landed_retries(monkeypatch) -> None:
    arguments, positions, ledger = _runner((base._launch(), _trade(1)))

    def failed_sell(*args, **kwargs):
        raise ProtocolExecutionRejected("CURVE_COMPLETED")

    monkeypatch.setattr(arguments["executor"].historical, "quote_sell", failed_sell)
    # Authoritative clock advances even when there are no subsequent Pump trades.
    CopyBuyReferenceEngine().run(**arguments)
    state = positions[0]
    assert state.control.exit_reason is CopyExitReason.MAXIMUM_HOLD
    assert state.control.status is CopyPositionStatus.EXHAUSTED
    assert len(state.attempts) == 5 and len(ledger) == 10
    # Each retry is two seconds after failure, followed by three more transactions.
    assert [item.decision.block_ordinal for item in state.attempts[1:]] == [105, 107, 109, 111]
    assert all(item.landed_at.transaction_index == 3 for item in state.attempts[1:])


def test_transaction_callback_never_observes_intermediate_price() -> None:
    high = base._state(virtual_sol_reserves_lamports=42_000_000_000)
    events = (
        base._launch(),
        _trade(1),
        # An intermediate high price inside one atomic transaction must be unobservable.
        _trade(5, state=high, event_index=0, group=6),
        _trade(5, event_index=1, group=6),
    )
    arguments, positions, _ = _runner(events)
    CopyBuyReferenceEngine().run(**arguments)
    # TP existed only between instructions and therefore cannot trigger an exit.
    assert positions[0].control.exit_reason is CopyExitReason.MAXIMUM_HOLD
    assert positions[0].attempts[1].decision.block_ordinal == 105


def test_short_tail_fails_before_wallet_or_strategy_mutation() -> None:
    arguments, positions, ledger = _runner((base._launch(), _trade(1)), blocks=7)
    with pytest.raises(TransactionClockError):
        CopyBuyReferenceEngine().run(**arguments)
    # A partial debug run is never a successful result; not even a reservation is emitted.
    assert not positions and not ledger
    assert arguments["executor"].portfolio.transaction_count == 0
    assert arguments["strategy"]._consumed_mints == set()


def test_signerless_source_cannot_mutate_the_wallet() -> None:
    legacy = base._trade(base._state(), block=100, transaction=1, event_index=0, group=2)
    arguments, positions, ledger = _runner((base._launch(), legacy))
    with pytest.raises(ProtocolContractError):
        CopyBuyReferenceEngine().run(**arguments)
    # Legacy payloads cannot be upgraded from a payer, creator or external lookup.
    assert not positions and not ledger


def test_other_signer_market_trade_does_not_require_a_copy_settlement_path() -> None:
    """All-signers market coverage does not create entry targets for untracked wallets."""
    event = _trade(1)
    other = base.AccountId("11111111111111111111111111111111")
    event = replace(event, protocol_payload=CopyBuyTradePayload(other, base._state()).encode())
    arguments, positions, ledger = _runner((base._launch(), event), blocks=7)
    # This clock is deliberately too short for an own position, but none is signalled.
    counts = CopyBuyReferenceEngine().run(**arguments)
    assert counts.historical_events == counts.observed_events == 2
    assert not positions and not ledger
