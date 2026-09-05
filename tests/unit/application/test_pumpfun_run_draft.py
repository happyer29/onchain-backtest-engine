# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from dataclasses import replace

import pytest

from backtest.application.run_drafts import (
    PUMPFUN_SNIPING_RUN_DRAFT_SCHEMA,
    # Include pump fee profile draft so the run drafts dependency remains explicit.
    PumpFeeProfileDraft,
    PumpfunSnipingRunDraft,
    SolanaAccountDepositCostDraft,
    SolanaFeeProfileDraft,
    WalletAccountMode,
    WalletAccountProfileDraft,
    # Close the run drafts import after its required symbols are visible.
)
from backtest.domain.execution import ExecutionMode
from backtest.domain.identifiers import (
    DatasetRevisionId,
    DeliveryScheduleId,
    ReplayPackId,
    # Include snapshot id so the identifiers dependency remains explicit.
    SnapshotId,
)


def test_sniping_draft_contains_only_editable_semantics() -> None:
    # Execute the test sniping draft contains only editable semantics workflow in
    # explicit, reviewable steps.
    draft = _draft()

    assert draft.contract_schema == PUMPFUN_SNIPING_RUN_DRAFT_SCHEMA
    assert draft.sell_delay_transactions == 1
    assert draft.execution_mode is ExecutionMode.EXOGENOUS_REPLAY
    assert not hasattr(draft, "cooldown_seconds")
    assert not hasattr(draft, "buy_delay_transactions")
    # Verify the hasattr, draft and sell wait seconds relationship before this scenario is
    # accepted.
    assert not hasattr(draft, "sell_wait_seconds")


def test_sniping_draft_rejects_modes_outside_the_closed_contract() -> None:
    # Generic shadow replay has no approved Pump.fun Sniping settlement semantics.
    with pytest.raises(ValueError, match="execution_mode"):
        replace(_draft(), execution_mode=ExecutionMode.SHADOW_STATE_REPLAY)


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        # Open the field name and value payload explicitly for parametrize within test
        # sniping draft rejects invalid integer policy.
        ("gross_buy_budget_lamports", 0),
        ("buy_slippage_bps", 10_001),
        ("sell_slippage_bps", -1),
        ("sell_delay_transactions", 0),
    ),
    # Complete parametrize only after its field name and value inputs are visible in test
    # sniping draft rejects invalid integer policy.
)
def test_sniping_draft_rejects_invalid_integer_policy(field_name: str, value: int) -> None:
    # Execute the test sniping draft rejects invalid integer policy workflow in explicit,
    # reviewable steps.
    with pytest.raises(ValueError):
        replace(_draft(), **{field_name: value})


def test_sniping_delivery_schedule_requires_exact_replay_pack() -> None:
    # Execute the test sniping delivery schedule requires exact replay pack workflow in
    # explicit, reviewable steps.
    schedule_id = DeliveryScheduleId("4" * 64)

    assert replace(_draft(), delivery_schedule_id=schedule_id).delivery_schedule_id == schedule_id
    with pytest.raises(ValueError, match="requires a ReplayPack"):
        replace(_draft(), replay_pack_id=None, delivery_schedule_id=schedule_id)


def test_wallet_profile_requires_three_versioned_account_prices() -> None:
    # A v1 scalar token-account price cannot be reused as the v2 profile closure.
    with pytest.raises(ValueError, match="three sorted schema prices"):
        WalletAccountProfileDraft(
            profile_id="fresh-v2",
            initial_uva_state=WalletAccountMode.FRESH,
            effective_from_unix_s=0,
            effective_until_unix_s=4_102_444_800,
            account_costs=(SolanaAccountDepositCostDraft("only-one-account-v1", 1),),
        )


def test_profile_documents_are_canonical_and_secret_free() -> None:
    # Execute the test profile documents are canonical and secret free workflow in
    # explicit, reviewable steps.
    draft = _draft()

    assert tuple(draft.pump_fee_profile.document()) == tuple(
        sorted(draft.pump_fee_profile.document())
    )
    assert tuple(draft.buy_solana_fee_profile.document()) == tuple(
        # Keep the sorted expectation tied to document, sorted and buy solana fee profile
        # in this scenario.
        sorted(draft.buy_solana_fee_profile.document())
    )
    assert "endpoint" not in draft.pump_fee_profile.document()
    assert "credential" not in draft.buy_solana_fee_profile.document()


def _draft() -> PumpfunSnipingRunDraft:
    # Execute the draft workflow in explicit, reviewable steps.
    network_fee = SolanaFeeProfileDraft(
        profile_id="solana-buy-v1",
        formula_version="solana-legacy-v0-base-priority-v1",
        transaction_format="V0",
        effective_from_unix_s=0,
        # Pass effective until unix s explicitly so SolanaFeeProfileDraft receives a
        # reviewable solana-buy-v1 and solana-legacy-v0-base-priority-v1 input in draft.
        effective_until_unix_s=4_102_444_800,
        charged_signature_count=1,
        lamports_per_signature=5_000,
        compute_unit_limit=200_000,
        micro_lamports_per_compute_unit=1_000,
        # Complete SolanaFeeProfileDraft only after its solana-buy-v1 and solana-
        # legacy-v0-base-priority-v1 inputs are visible in draft.
    )
    return PumpfunSnipingRunDraft(
        dataset_revision_id=DatasetRevisionId("1" * 64),
        snapshot_id=SnapshotId("2" * 64),
        replay_pack_id=ReplayPackId("3" * 64),
        # Pass initial sol balance lamports explicitly so PumpfunSnipingRunDraft receives
        # a reviewable 1 and 2 input in draft.
        initial_sol_balance_lamports=100_000_000_000,
        gross_buy_budget_lamports=100_000_000,
        buy_slippage_bps=500,
        sell_slippage_bps=500,
        execution_mode=ExecutionMode.EXOGENOUS_REPLAY,
        sell_delay_transactions=1,
        # Include wallet account profile in the completed draft result.
        wallet_account_profile=_account_profile(),
        pump_fee_profile=PumpFeeProfileDraft(
            profile_id="pump-static-95-30-v1",
            program_version="pump-program-static-fee-v1",
            buy_formula_version="pump-buy-exact-gross-sol-v1",
            # Pass sell formula version explicitly so PumpFeeProfileDraft receives a
            # reviewable pump-static-95-30-v1 and pump-program-static-fee-v1 input in
            # draft.
            sell_formula_version="pump-sell-exact-token-in-v1",
            effective_from_unix_s=0,
            effective_until_unix_s=4_102_444_800,
            protocol_fee_bps=95,
            creator_fee_bps=30,
            # Complete PumpFeeProfileDraft only after its pump-static-95-30-v1 and pump-
            # program-static-fee-v1 inputs are visible in draft.
        ),
        buy_solana_fee_profile=network_fee,
        sell_solana_fee_profile=replace(network_fee, profile_id="solana-sell-v1"),
        root_seed=42,
    )


def _account_profile() -> WalletAccountProfileDraft:
    """Build the exact three-component v2 profile used by draft tests."""

    costs = (
        SolanaAccountDepositCostDraft("pumpfun-user-volume-accumulator-v1", 1_844_400),
        SolanaAccountDepositCostDraft("solana-associated-token-account-legacy-v1", 2_039_280),
        SolanaAccountDepositCostDraft(
            "solana-associated-token-account-token-2022-immutable-owner-v1",
            2_074_080,
        ),
    )
    return WalletAccountProfileDraft(
        profile_id="pumpfun-solana-accounts-v2",
        initial_uva_state=WalletAccountMode.FRESH,
        effective_from_unix_s=0,
        effective_until_unix_s=4_102_444_800,
        account_costs=costs,
    )
