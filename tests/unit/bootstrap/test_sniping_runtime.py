# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import json

import pytest

from backtest.application.run_drafts import (
    PumpFeeProfileDraft,
    PumpfunSnipingRunDraft,
    SolanaAccountDepositCostDraft,
    # Include solana fee profile draft so the run drafts dependency remains explicit.
    SolanaFeeProfileDraft,
    WalletAccountMode,
    WalletAccountProfileDraft,
)
from backtest.application.run_specs import (
    # Include asset balance so the run specs dependency remains explicit.
    AssetBalance,
    ReplayInputFormat,
    ResolvedComponent,
    ResolvedReplayInput,
    ResolvedRunSpec,
    # Close the run specs import after its required symbols are visible.
)
from backtest.application.sniping_run_contract import (
    PUMPFUN_SNIPING_UNIVERSE_POLICY_ID,
    sniping_component_configs,
)
from backtest.bootstrap.reference_bundles import PumpfunSnipingBundleRegistry
from backtest.bootstrap.sniping_runtime import (
    PumpfunSnipingRuntimeComponentsResolver,
    # Include sniping runtime resolution error so the sniping runtime dependency remains
    # explicit.
    SnipingRuntimeResolutionError,
)
from backtest.domain.account_requirements import (
    AccountReleasePolicy,
    AccountRequirement,
    AccountRequirementScope,
)
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
    # Close the chain import after its required symbols are visible.
)
from backtest.domain.execution import ExecutionMode
from backtest.domain.identifiers import (
    AssetId,
    ContentDigest,
    DatasetRevisionId,
    # Include delivery schedule id so the identifiers dependency remains explicit.
    DeliveryScheduleId,
    LogicalContentHash,
    ReplayPackId,
    RuntimeLockId,
    SnapshotId,
    # Close the identifiers import after its required symbols are visible.
)
from backtest.engine.wallet_accounts import WalletUvaInitialState
from backtest.plugins.networks.solana import SOLANA_LEGACY_V0_FEE_FORMULA_V1
from backtest.plugins.protocols.pumpfun import (
    PUMP_BUY_EXACT_GROSS_SOL_FORMULA_V1,
    # Include pump sell exact token in formula v1 so the pumpfun dependency remains
    # explicit.
    PUMP_SELL_EXACT_TOKEN_IN_FORMULA_V1,
    PUMP_STATIC_PROGRAM_CONTRACT_V1,
)


def _fee(profile_id: str) -> SolanaFeeProfileDraft:
    # Execute the fee workflow in explicit, reviewable steps.
    return SolanaFeeProfileDraft(
        profile_id=profile_id,
        formula_version=SOLANA_LEGACY_V0_FEE_FORMULA_V1,
        transaction_format="V0",
        effective_from_unix_s=1_700_000_000,
        # Pass effective until unix s explicitly so SolanaFeeProfileDraft receives a
        # reviewable v0 and profile id input in fee.
        effective_until_unix_s=1_800_000_000,
        charged_signature_count=1,
        lamports_per_signature=5_000,
        compute_unit_limit=100_000,
        micro_lamports_per_compute_unit=10,
        # Complete SolanaFeeProfileDraft only after its v0 and profile id inputs are visible
        # in fee.
    )


def _draft(
    execution_mode: ExecutionMode = ExecutionMode.EXOGENOUS_REPLAY,
) -> PumpfunSnipingRunDraft:
    # Execute the draft workflow in explicit, reviewable steps.
    return PumpfunSnipingRunDraft(
        dataset_revision_id=DatasetRevisionId("1" * 64),
        snapshot_id=SnapshotId("2" * 64),
        replay_pack_id=None,
        initial_sol_balance_lamports=5_000_000_000,
        # Pass gross buy budget lamports explicitly so PumpfunSnipingRunDraft receives a
        # reviewable 1 and 2 input in draft.
        gross_buy_budget_lamports=1_000_000_000,
        buy_slippage_bps=100,
        sell_slippage_bps=200,
        execution_mode=execution_mode,
        sell_delay_transactions=3,
        wallet_account_profile=WalletAccountProfileDraft(
            # Pass profile id explicitly so WalletAccountProfileDraft receives a
            # reviewable fresh-pump-account-v1 and pump-token-account-v1 input in draft.
            profile_id="fresh-pump-account-v2",
            initial_uva_state=WalletAccountMode.FRESH,
            effective_from_unix_s=1_700_000_000,
            effective_until_unix_s=1_800_000_000,
            account_costs=(
                SolanaAccountDepositCostDraft(
                    "pumpfun-user-volume-accumulator-v1",
                    1_844_400,
                ),
                SolanaAccountDepositCostDraft(
                    "solana-associated-token-account-legacy-v1",
                    2_039_280,
                ),
                SolanaAccountDepositCostDraft(
                    "solana-associated-token-account-token-2022-immutable-owner-v1",
                    2_074_080,
                ),
            ),
        ),
        # Include pump fee profile in the completed draft result.
        pump_fee_profile=PumpFeeProfileDraft(
            profile_id="pump-static-95-30-v1",
            program_version=PUMP_STATIC_PROGRAM_CONTRACT_V1,
            buy_formula_version=PUMP_BUY_EXACT_GROSS_SOL_FORMULA_V1,
            sell_formula_version=PUMP_SELL_EXACT_TOKEN_IN_FORMULA_V1,
            # Pass effective from unix s explicitly so PumpFeeProfileDraft receives a
            # reviewable pump-static-95-30-v1 and pump static program contract v1 input in
            # draft.
            effective_from_unix_s=1_700_000_000,
            effective_until_unix_s=1_800_000_000,
            protocol_fee_bps=95,
            creator_fee_bps=30,
        ),
        # Include buy solana fee profile in the completed draft result.
        buy_solana_fee_profile=_fee("buy-v1"),
        sell_solana_fee_profile=_fee("sell-v1"),
        root_seed=7,
    )


def _spec(
    # Close the spec signature after its explicit inputs.
    *,
    configs: dict[str, dict[str, object]] | None = None,
    with_delivery_schedule: bool = False,
    execution_mode: ExecutionMode = ExecutionMode.EXOGENOUS_REPLAY,
) -> ResolvedRunSpec:
    # Execute the spec workflow in explicit, reviewable steps.
    draft = _draft(execution_mode)
    selected = sniping_component_configs(draft) if configs is None else configs
    closure = PumpfunSnipingBundleRegistry().snapshot()
    components = tuple(
        ResolvedComponent.create(
            # Pass role explicitly so create receives a reviewable role and bundle id
            # input in spec.
            role=manifest.role,
            bundle_id=manifest.bundle_id,
            api_version=manifest.api_version,
            config=selected[manifest.role],
        )
        # Pass manifest explicitly so tuple receives a reviewable create and manifests
        # input in spec.
        for manifest in closure.manifests
    )
    replay_input = (
        ResolvedReplayInput(
            ReplayInputFormat.REPLAY_PACK,
            # Keep the content digest ContentDigest step visible while building replay
            # input.
            ContentDigest("6" * 64),
            ReplayPackId("7" * 64),
        )
        if with_delivery_schedule
        else ResolvedReplayInput(ReplayInputFormat.CANONICAL_PARQUET)
        # Complete the replay input group only after its semantic components are visible.
    )
    return ResolvedRunSpec.create(
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        dataset_revision_id=draft.dataset_revision_id,
        # Include logical content hash in the completed spec result.
        logical_content_hash=LogicalContentHash("3" * 64),
        snapshot_id=draft.snapshot_id,
        replay_semantics_id=ContentDigest("4" * 64),
        replay_input=replay_input,
        components=components,
        # Include runtime lock id in the completed spec result.
        runtime_lock_id=RuntimeLockId("5" * 64),
        initial_portfolio=(AssetBalance(AssetId("SOL"), 5_000_000_000),),
        root_seed=draft.root_seed,
        delivery_schedule_id=(DeliveryScheduleId("8" * 64) if with_delivery_schedule else None),
    )


# Define test resolves exact sniping components and profiles as one focused operation with
# an explicit boundary.
def test_resolves_exact_sniping_components_and_profiles() -> None:
    # Execute the test resolves exact sniping components and profiles workflow in
    # explicit, reviewable steps.
    runtime = PumpfunSnipingRuntimeComponentsResolver(RuntimeLockId("5" * 64)).resolve(_spec())

    assert runtime.initial_uva_state is WalletUvaInitialState.FRESH
    assert runtime.strategy.gross_buy_budget_atomic == 1_000_000_000
    assert runtime.strategy.sell_delay_transactions == 3
    assert runtime.strategy.execution_mode is ExecutionMode.EXOGENOUS_REPLAY
    assert runtime.protocol.fee_profile.protocol_fee_bps == 95
    # Verify the creator fee bps, fee profile and protocol relationship before this
    # scenario is accepted.
    assert runtime.protocol.fee_profile.creator_fee_bps == 30
    assert (
        runtime.network_costs.quote_buy(
            effective_at_unix_s=1_750_000_000,
            requirements=(
                AccountRequirement(
                    "solana-associated-token-account-legacy-v1",
                    AccountRequirementScope.MINT,
                    AccountReleasePolicy.CLOSE_ON_SUCCESSFUL_SELL,
                ),
                AccountRequirement(
                    "pumpfun-user-volume-accumulator-v1",
                    AccountRequirementScope.WALLET,
                    AccountReleasePolicy.RUN_LOCKED,
                ),
            ),
            # Complete quote_buy only after its declared inputs are visible in test resolves
            # exact sniping components and profiles.
        )
        .account_requirements[0]
        .maximum_deposit_atomic
        == 2_039_280
    )
    assert {item.role for item in runtime.receipts} == {item.role for item in _spec().components}


def test_run_contract_materializes_non_mayhem_universe_policy_v2() -> None:
    # Keep the versioned exclusion policy in the semantic component configuration.
    universe = sniping_component_configs(_draft())["universe"]

    assert universe == {
        "decision_targets": PUMPFUN_SNIPING_UNIVERSE_POLICY_ID,
        "settlement_tail_creates_targets": False,
    }


def test_exogenous_mode_materializes_real_reserve_policy() -> None:
    # The historical mode retains the original real-reserve solvency gate.
    execution = sniping_component_configs(_draft())["execution"]

    assert execution["mode"] == "EXOGENOUS_REPLAY"
    assert execution["sell_settlement_policy"] == "real-reserve-capped-v1"
    assert execution["synthetic_proceeds_policy"] == "no-synthetic-proceeds-v1"


def test_virtual_mode_materializes_distinct_policy_and_logical_identity() -> None:
    # The same market artifacts produce a different semantic run when funding changes.
    virtual = _spec(execution_mode=ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT)
    exogenous = _spec()
    execution = next(item for item in virtual.components if item.role == "execution")
    execution_config = json.loads(execution.canonical_config)

    # Both mode and its exact funding policies contribute to resolved identity.
    assert virtual.logical_run_id != exogenous.logical_run_id
    assert execution_config["sell_settlement_policy"] == (
        "virtual-reserve-output-with-explicit-synthetic-shortfall-v1"
    )
    assert execution_config["synthetic_proceeds_policy"] == ("spendable-synthetic-proceeds-v1")
    # Runtime strategy receives the same mode rather than inferring it from backend.
    runtime = PumpfunSnipingRuntimeComponentsResolver(RuntimeLockId("5" * 64)).resolve(virtual)
    assert runtime.strategy.execution_mode is ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT


def test_runtime_rejects_mode_and_settlement_policy_mismatch() -> None:
    # A valid component digest cannot legitimize a forged mode/policy combination.
    draft = _draft(ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT)
    configs = sniping_component_configs(draft)
    configs["execution"] = {
        **configs["execution"],
        "sell_settlement_policy": "real-reserve-capped-v1",
    }

    with pytest.raises(SnipingRuntimeResolutionError, match="execution config"):
        PumpfunSnipingRuntimeComponentsResolver(RuntimeLockId("5" * 64)).resolve(
            _spec(configs=configs, execution_mode=draft.execution_mode)
        )


def test_resolves_sniping_runtime_with_exact_materialized_delivery_schedule() -> None:
    # Execute the test resolves sniping runtime with exact materialized delivery schedule
    # workflow in explicit, reviewable steps.
    runtime = PumpfunSnipingRuntimeComponentsResolver(RuntimeLockId("5" * 64)).resolve(
        _spec(with_delivery_schedule=True)
    )

    assert runtime.strategy.sell_delay_transactions == 3


def test_rejects_tampered_fixed_semantics_even_with_valid_component_digest() -> None:
    # Execute the test rejects tampered fixed semantics even with valid component digest
    # workflow in explicit, reviewable steps.
    draft = _draft()
    configs = sniping_component_configs(draft)
    configs["network:solana"] = {
        **configs["network:solana"],
        "jito_tip_lamports": 1,
        # Complete the configs['network:solana'] group only after its semantic components are
        # visible.
    }

    with pytest.raises(SnipingRuntimeResolutionError, match="Jito"):
        # Keep raises, sniping runtime resolution error and pytest active only for the
        # bounded test rejects tampered fixed semantics even with valid component digest
        # operation.
        PumpfunSnipingRuntimeComponentsResolver(RuntimeLockId("5" * 64)).resolve(
            _spec(configs=configs)
        )


def test_rejects_legacy_all_modes_universe_config() -> None:
    # A resolved v1 policy cannot be reinterpreted as the causal non-Mayhem v2 universe.
    configs = sniping_component_configs(_draft())
    configs["universe"] = {
        "decision_targets": "successful-sol-paired-pumpfun-launches-v1",
        "settlement_tail_creates_targets": False,
    }

    with pytest.raises(SnipingRuntimeResolutionError, match="universe config"):
        PumpfunSnipingRuntimeComponentsResolver(RuntimeLockId("5" * 64)).resolve(
            _spec(configs=configs)
        )


def test_rejects_wrong_runtime_lock_before_instantiation() -> None:
    # Execute the test rejects wrong runtime lock before instantiation workflow in
    # explicit, reviewable steps.
    with pytest.raises(SnipingRuntimeResolutionError, match="runtime lock"):
        PumpfunSnipingRuntimeComponentsResolver(RuntimeLockId("6" * 64)).resolve(_spec())
