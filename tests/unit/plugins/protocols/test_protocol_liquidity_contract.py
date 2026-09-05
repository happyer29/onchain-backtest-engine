"""Focused tests for the launchpad-neutral sell-liquidity contract."""

from __future__ import annotations

from dataclasses import replace

import pytest

from backtest.domain.execution import ExecutionMode
from backtest.domain.identifiers import AccountId, AssetId, NetworkId, VenueId
from backtest.engine.sniping_contracts import (
    REAL_RESERVE_CAPPED_LIQUIDITY_POLICY_ID,
    VIRTUAL_RESERVE_EXPLICIT_SHORTFALL_LIQUIDITY_POLICY_ID,
    ProtocolLiquidityEvidence,
    liquidity_policy_id_for_execution_mode,
    synthetic_liquidity_account_id,
)


def test_liquidity_policy_mapping_is_closed_to_two_sniping_modes() -> None:
    # Empty-result summaries use this core mapping without importing a venue plugin.
    assert (
        liquidity_policy_id_for_execution_mode(ExecutionMode.EXOGENOUS_REPLAY)
        == REAL_RESERVE_CAPPED_LIQUIDITY_POLICY_ID
    )
    assert (
        liquidity_policy_id_for_execution_mode(ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT)
        == VIRTUAL_RESERVE_EXPLICIT_SHORTFALL_LIQUIDITY_POLICY_ID
    )

    with pytest.raises(ValueError, match=r"unsupported Pump\.fun Sniping execution mode"):
        liquidity_policy_id_for_execution_mode(ExecutionMode.SHADOW_STATE_REPLAY)


def test_liquidity_evidence_requires_exact_shortfall_and_account_coupling() -> None:
    evidence = ProtocolLiquidityEvidence(
        policy_id=VIRTUAL_RESERVE_EXPLICIT_SHORTFALL_LIQUIDITY_POLICY_ID,
        asset_id=AssetId("SOL"),
        required_output_atomic=125,
        observed_available_output_atomic=100,
        # A positive deficit has one explicit deterministic funding source.
        synthetic_shortfall_atomic=25,
        synthetic_source_account_id=AccountId("synthetic-source"),
    )
    assert evidence.synthetic_shortfall_atomic == 25

    with pytest.raises(ValueError, match="inconsistent with observed liquidity"):
        replace(evidence, synthetic_shortfall_atomic=24)
    with pytest.raises(TypeError, match="requires an AccountId source"):
        replace(evidence, synthetic_source_account_id=None)

    fully_funded = ProtocolLiquidityEvidence(
        policy_id=REAL_RESERVE_CAPPED_LIQUIDITY_POLICY_ID,
        asset_id=AssetId("SOL"),
        required_output_atomic=100,
        observed_available_output_atomic=125,
        # No shortfall means no synthetic ledger account may be attached.
        synthetic_shortfall_atomic=0,
        synthetic_source_account_id=None,
    )
    with pytest.raises(ValueError, match="must not carry a source account"):
        replace(fully_funded, synthetic_source_account_id=AccountId("unexpected-source"))


def test_synthetic_account_identity_is_stable_and_chain_scoped() -> None:
    """The public core derivation binds protocol, immutable network, and venue."""

    network = NetworkId("solana:11111111111111111111111111111112")
    venue = VenueId("curve-a")
    # Synthetic funding belongs to this exact network and venue, independently of a run.
    first = synthetic_liquidity_account_id(
        protocol_namespace="pumpfun",
        network_id=network,
        venue_id=venue,
    )
    # Repeating all semantic inputs must recover the same external ledger account.
    assert first == synthetic_liquidity_account_id(
        protocol_namespace="pumpfun",
        network_id=network,
        venue_id=venue,
    )
    # A second valid 32-byte genesis must produce a different chain-scoped account.
    assert first != synthetic_liquidity_account_id(
        protocol_namespace="pumpfun",
        network_id=NetworkId("solana:11111111111111111111111111111113"),
        venue_id=venue,
    )
    # Venue identity also separates accounts even when the network remains unchanged.
    assert first != synthetic_liquidity_account_id(
        protocol_namespace="pumpfun",
        network_id=network,
        venue_id=VenueId("curve-b"),
    )

    # Namespace spelling is part of the account contract and cannot be normalized.
    with pytest.raises(ValueError, match="lowercase ASCII token"):
        # Valid network and venue inputs isolate the unsupported namespace spelling.
        synthetic_liquidity_account_id(
            protocol_namespace="PumpFun",
            network_id=network,
            venue_id=venue,
        )
