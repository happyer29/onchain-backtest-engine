"""Focused invariants for strategy intent contracts."""

from __future__ import annotations

import pytest

from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
    ChainPosition,
)
from backtest.domain.execution import ExecutionMode
from backtest.domain.identifiers import AccountId, AssetId, ContentDigest, VenueId
from backtest.domain.intents import RoundTripIntent


def _roundtrip_intent(mode: ExecutionMode) -> RoundTripIntent:
    position = ChainPosition(
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        block_ordinal=100,
        transaction_index=2,
        # Event identity remains exact while execution mode changes semantics.
        event_index=0,
    )
    return RoundTripIntent(
        roundtrip_id=ContentDigest("0" * 64),
        target_event_id=ContentDigest("1" * 64),
        target_position=position,
        asset_id=AssetId("TOKEN"),
        developer_id=AccountId("developer"),
        # Keep launch identity separate from venue and quote-asset identity.
        creation_user_id=AccountId("creation-user"),
        venue_id=VenueId("pump-curve"),
        quote_asset_id=AssetId("SOL"),
        gross_buy_budget_atomic=1_000_000_000,
        buy_slippage_bps=100,
        # Sell semantics remain unchanged across the two admitted modes.
        sell_slippage_bps=100,
        sell_delay_transactions=1,
        created_boundary_ordinal=position.boundary_ordinal,
        execution_mode=mode,
    )


@pytest.mark.parametrize(
    "mode",
    (
        ExecutionMode.EXOGENOUS_REPLAY,
        ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT,
    ),
)
def test_roundtrip_intent_accepts_both_exogenous_sniping_modes(mode: ExecutionMode) -> None:
    assert _roundtrip_intent(mode).execution_mode is mode


def test_roundtrip_intent_rejects_non_exogenous_sniping_modes() -> None:
    with pytest.raises(ValueError, match="supported exogenous execution mode"):
        _roundtrip_intent(ExecutionMode.SHADOW_STATE_REPLAY)
