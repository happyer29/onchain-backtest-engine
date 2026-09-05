# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import pytest

from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
    ChainPosition,
    # Close the chain import after its required symbols are visible.
)
from backtest.domain.execution import ExecutionMode
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import AccountId, AssetId, VenueId
from backtest.engine.sniping_contracts import LaunchDecisionStatus, LaunchTarget
from backtest.plugins.strategies.pumpfun_sniping import PumpfunSnipingStrategy

# Bind sol once as an explicit module-level contract.
SOL = AssetId("SOL")


def _target(sequence: int, *, developer: str = "dev") -> LaunchTarget:
    # Execute the target workflow in explicit, reviewable steps.
    return LaunchTarget(
        target_event_id=domain_digest("test.target", sequence),
        position=ChainPosition(
            network_id=SOLANA_MAINNET_NETWORK_ID,
            position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            # Pass block ordinal explicitly so ChainPosition receives a reviewable solana
            # mainnet network id and block32 transaction32 position schema id input in
            # target.
            block_ordinal=100 + sequence,
            transaction_index=0,
            event_index=0,
        ),
        asset_id=AssetId(f"token-{sequence}"),
        # Include developer id in the completed target result.
        developer_id=AccountId(developer),
        creation_user_id=AccountId(f"user-{sequence}"),
        venue_id=VenueId(f"curve-{sequence}"),
        quote_asset_id=SOL,
    )


# Define strategy as one focused operation with an explicit boundary.
def _strategy() -> PumpfunSnipingStrategy:
    # Execute the strategy workflow in explicit, reviewable steps.
    return PumpfunSnipingStrategy(
        quote_asset_id=SOL,
        gross_buy_budget_atomic=1_000_000_000,
        buy_slippage_bps=100,
        sell_slippage_bps=200,
        # Pass sell delay transactions explicitly so PumpfunSnipingStrategy receives a
        # reviewable sol input in strategy.
        sell_delay_transactions=5,
    )


def test_cooldown_is_consumed_at_signal_and_boundary_is_half_open() -> None:
    # Execute the test cooldown is consumed at signal and boundary is half open workflow
    # in explicit, reviewable steps.
    strategy = _strategy()
    start = 1_700_000_000_000_000_000

    first = strategy.decide(_target(0), decision_time_ns=start)
    suppressed = strategy.decide(_target(1), decision_time_ns=start + 599_000_000_000)
    boundary = strategy.decide(_target(2), decision_time_ns=start + 600_000_000_000)

    # Verify the status, eligible and first relationship before this scenario is accepted.
    assert first.status is LaunchDecisionStatus.ELIGIBLE
    assert first.intent is not None
    assert suppressed.status is LaunchDecisionStatus.COOLDOWN_SUPPRESSED
    assert suppressed.intent is None
    assert boundary.status is LaunchDecisionStatus.ELIGIBLE


# Define test suppressed signal does not extend cooldown and developers are independent as
# one focused operation with an explicit boundary.
def test_suppressed_signal_does_not_extend_cooldown_and_developers_are_independent() -> None:
    # Execute the test suppressed signal does not extend cooldown and developers are
    # independent workflow in explicit, reviewable steps.
    strategy = _strategy()
    start = 1_700_000_000_000_000_000

    first = strategy.decide(_target(0), decision_time_ns=start)
    suppressed = strategy.decide(_target(1), decision_time_ns=start + 300_000_000_000)
    other = strategy.decide(_target(2, developer="other"), decision_time_ns=start + 300_000_000_000)
    # Assemble eligible once so the test suppressed signal does not extend cooldown and
    # developers are independent workflow shares one value.
    eligible = strategy.decide(_target(3), decision_time_ns=start + 600_000_000_000)

    assert suppressed.cooldown_until_ns == first.cooldown_until_ns
    assert other.status is LaunchDecisionStatus.ELIGIBLE
    assert eligible.status is LaunchDecisionStatus.ELIGIBLE


def test_same_timestamp_uses_canonical_call_order() -> None:
    # Execute the test same timestamp uses canonical call order workflow in explicit,
    # reviewable steps.
    strategy = _strategy()
    now = 1_700_000_000_000_000_000

    first = strategy.decide(_target(0), decision_time_ns=now)
    second = strategy.decide(_target(1), decision_time_ns=now)

    assert first.status is LaunchDecisionStatus.ELIGIBLE
    # Verify the status, cooldown suppressed and second relationship before this scenario
    # is accepted.
    assert second.status is LaunchDecisionStatus.COOLDOWN_SUPPRESSED


def test_strategy_propagates_virtual_settlement_mode_into_intent_identity() -> None:
    # The strategy's configured component and emitted intent must agree on mode.
    strategy = PumpfunSnipingStrategy(
        quote_asset_id=SOL,
        gross_buy_budget_atomic=1_000_000_000,
        buy_slippage_bps=100,
        sell_slippage_bps=200,
        # Select the synthetic mode explicitly at the strategy boundary.
        sell_delay_transactions=5,
        execution_mode=ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT,
    )
    decision = strategy.decide(_target(0), decision_time_ns=1_700_000_000_000_000_000)

    assert decision.intent is not None
    assert decision.intent.execution_mode is ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT
    # Unsupported generic modes fail before any cooldown state can be consumed.
    with pytest.raises(ValueError, match="unsupported"):
        PumpfunSnipingStrategy(
            quote_asset_id=SOL,
            gross_buy_budget_atomic=1,
            buy_slippage_bps=0,
            sell_slippage_bps=0,
            # A generic shadow mode must not be accepted as Pump.fun semantics.
            sell_delay_transactions=1,
            execution_mode=ExecutionMode.SHADOW_STATE_REPLAY,
        )
