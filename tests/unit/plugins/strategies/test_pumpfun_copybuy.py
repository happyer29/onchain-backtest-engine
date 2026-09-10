"""Entry attribution and once-per-mint behavior for the copy-buy strategy."""

from dataclasses import replace

import pytest

# Source signer and payer must remain separate identities at the strategy seam.
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
    ChainPosition,
)

# The strategy consumes a typed BUY signal, not an inferred launch target.
from backtest.domain.copytrading import CopyBuyPolicy, CopyBuySignal

# Component hashes bind the exact wallets and selected execution semantics.
from backtest.domain.execution import ExecutionMode
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import AccountId, AssetId, BundleId, NetworkId, VenueId
from backtest.plugins.strategies.pumpfun_copybuy import PumpfunCopyBuyStrategy


def _signal(*, wallet: str = "leader", mint: str = "token", event: int = 0) -> CopyBuySignal:
    """A successful BUY projected after its containing historical group."""

    position = ChainPosition(
        SOLANA_MAINNET_NETWORK_ID, BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID, 10, 2, event
    )
    # The signer is retained independently of the venue and traded assets.
    return CopyBuySignal(
        domain_digest("test.copy-buy-event", event),
        position,
        AccountId(wallet),
        AssetId(mint),
        # Every signal names the original curve; retries cannot change its venue.
        VenueId("curve-" + mint),
        AssetId("SOL"),
    )


def _strategy(*, maximum: int = 10) -> PumpfunCopyBuyStrategy:
    """Wallet membership is explicit and does not refer to a fee payer."""

    return PumpfunCopyBuyStrategy(
        signing_wallets=(AccountId("leader"), AccountId("other-leader")),
        policy=CopyBuyPolicy(1000, 2000, 1000, 10, 0, 5, 7, 100, 200),
        # A fake bundle exists only in the unit fixture, never in runtime resolution.
        bundle_id=BundleId(domain_digest("test.bundle", 1).hex),
        execution_mode=ExecutionMode.EXOGENOUS_REPLAY,
        quote_asset_id=AssetId("SOL"),
        maximum_consumed_mints=maximum,
    )


def test_first_signal_consumes_mint_without_waiting_for_buy_result() -> None:
    """Balance reject, landed failure, and subsequent close cannot release a mint."""

    strategy = _strategy()
    signal = _signal()
    intent = strategy.decide(signal, decision_position=signal.position)
    assert intent is not None
    # No execution notification is necessary to make repeated signals ineligible.
    assert strategy.decide(signal, decision_position=signal.position) is None
    later_leader = _signal(wallet="other-leader", event=1)
    assert strategy.decide(later_leader, decision_position=later_leader.position) is None
    another_mint = _signal(mint="another", event=2)
    assert strategy.decide(another_mint, decision_position=another_mint.position) is not None


def test_untracked_signer_does_not_consume_mint() -> None:
    """Fee-paying or economically related addresses cannot substitute for signer."""

    strategy = _strategy()
    untracked = _signal(wallet="fee-payer")
    assert strategy.decide(untracked, decision_position=untracked.position) is None
    leader = _signal()
    assert strategy.decide(leader, decision_position=leader.position) is not None


def test_resource_limit_is_fail_closed_and_repeated_mints_do_not_spend_capacity() -> None:
    """A limit error must not silently truncate the canonical signal universe."""

    strategy = _strategy(maximum=1)
    signal = _signal()
    assert strategy.decide(signal, decision_position=signal.position) is not None
    assert strategy.decide(signal, decision_position=signal.position) is None
    # A new mint exceeds admitted state rather than being reported as skipped profit.
    another = _signal(mint="another")
    with pytest.raises(ValueError, match="resource limit"):
        strategy.decide(another, decision_position=another.position)


def test_signal_identity_and_delayed_decision_are_preserved() -> None:
    """An observed BUY remains the target; no artificial launch is created."""

    signal = _signal(event=7)
    decision = replace(signal.position, block_ordinal=11, event_index=None)
    intent = _strategy().decide(signal, decision_position=decision)
    assert intent is not None
    # Shared quote math receives actual assets, budget, and original network identity.
    assert intent.target_position == signal.position
    assert intent.asset_id == signal.asset_id
    assert intent.quote_asset_id == signal.quote_asset_id
    assert intent.venue_id == signal.venue_id
    assert intent.gross_buy_budget_atomic == 1000
    # Observation position changes the position identity even with the same source BUY.
    immediate = _strategy().decide(signal, decision_position=signal.position)
    assert immediate is not None
    assert immediate.roundtrip_id != intent.roundtrip_id


@pytest.mark.parametrize(
    "wallets",
    [
        (),
        # Duplicate membership and caller order cannot create another executable identity.
        (AccountId("leader"), AccountId("leader")),
        (AccountId("other-leader"), AccountId("leader")),
    ],
)
def test_noncanonical_wallet_list_is_rejected(wallets: tuple[AccountId, ...]) -> None:
    """Equivalent wallet sets must not acquire different executable identities."""

    base = _strategy()
    with pytest.raises(ValueError):
        PumpfunCopyBuyStrategy(
            signing_wallets=wallets,
            policy=base.policy,
            # Hold code and execution settings fixed to isolate the invalid wallet list.
            bundle_id=base.bundle_id,
            # The invalid wallet list must fail before any configured signal can run.
            execution_mode=ExecutionMode.EXOGENOUS_REPLAY,
            quote_asset_id=AssetId("SOL"),
            maximum_consumed_mints=10,
        )


def test_invalid_observation_does_not_create_a_consumed_mint() -> None:
    """An invalid engine call fails as a contract error, not as an entry rejection."""

    strategy = _strategy()
    signal = _signal()
    before = replace(signal.position, transaction_index=1)
    with pytest.raises(ValueError, match="precedes"):
        strategy.decide(signal, decision_position=before)
    # Wrong-network coordinates cannot alias the legitimate signal's position.
    foreign = replace(signal.position, network_id=NetworkId("eip155:1"))
    with pytest.raises(ValueError, match="chain identity"):
        strategy.decide(signal, decision_position=foreign)
    assert strategy.decide(signal, decision_position=signal.position) is not None


def test_signal_requires_an_exact_instruction_and_different_assets() -> None:
    """A transaction-only key cannot distinguish two leader BUY instructions."""

    signal = _signal()
    with pytest.raises(ValueError, match="exact event"):
        replace(signal, position=replace(signal.position, event_index=None))
    # A token alias cannot be silently interpreted as the quote asset.
    with pytest.raises(ValueError, match="different assets"):
        replace(signal, asset_id=signal.quote_asset_id)
