"""SuccessfulRun v3 capacity acceptance for external sniping result tables."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository

# Import results at the visible module dependency boundary.
from backtest.adapters.results import LocalParquetRunOutputStore
from backtest.adapters.results.parquet import LocalParquetRunResultReaderFactory
from backtest.application.models import ArtifactDraft, ArtifactKind
from backtest.application.run_drafts import (
    PumpFeeProfileDraft,
    # Include pumpfun sniping run draft so the run drafts dependency remains explicit.
    PumpfunSnipingRunDraft,
    SolanaAccountDepositCostDraft,
    SolanaFeeProfileDraft,
    WalletAccountMode,
    WalletAccountProfileDraft,
)

# Import run results at the visible module dependency boundary.
from backtest.application.run_results import (
    MAX_SUCCESSFUL_RUN_MANIFEST_BYTES,
    RunBackend,
    RunPhysicalSettings,
    RunResultTableRole,
    # Include successful run manifest so the run results dependency remains explicit.
    SuccessfulRunManifest,
)
from backtest.application.run_specs import (
    AssetBalance,
    ReplayInputFormat,
    # Include resolved component so the run specs dependency remains explicit.
    ResolvedComponent,
    ResolvedReplayInput,
    ResolvedRunSpec,
)
from backtest.application.sniping_run_contract import sniping_component_configs

# Import reference bundles at the visible module dependency boundary.
from backtest.bootstrap.reference_bundles import PumpfunSnipingBundleRegistry
from backtest.domain.account_requirements import (
    AccountComponentLifecycle,
    AccountComponentRecord,
    AccountReleasePolicy,
    AccountRequirementScope,
)
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
    ChainPosition,
    # Close the chain import after its required symbols are visible.
)
from backtest.domain.execution import ExecutionMode, Fill
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.domain.identifiers import (
    AccountId,
    # Include artifact id so the identifiers dependency remains explicit.
    ArtifactId,
    AssetId,
    ContentDigest,
    DatasetRevisionId,
    LogicalContentHash,
    # Include order id so the identifiers dependency remains explicit.
    OrderId,
    PoolId,
    RuntimeLockId,
    SnapshotId,
    VenueId,
    # Close the identifiers import after its required symbols are visible.
)
from backtest.domain.ledger import (
    AccountKind,
    LedgerAccount,
    LedgerCorrelationKind,
    # Include ledger transaction so the ledger dependency remains explicit.
    LedgerTransaction,
    Posting,
)
from backtest.domain.roundtrips import (
    MtmStatus,
    # Include round trip leg record so the roundtrips dependency remains explicit.
    RoundTripLegRecord,
    RoundTripLegSide,
    RoundTripRecord,
    RoundTripStatus,
    # Close the roundtrips import after its required symbols are visible.
)
from backtest.engine.audit import CanonicalStreamHasher, fill_document, ledger_document
from backtest.engine.sniping import SnipingRunSummary, SnipingValuationStatus
from backtest.plugins.networks.solana import SOLANA_LEGACY_V0_FEE_FORMULA_V1
from backtest.plugins.protocols.pumpfun import (
    # Include pump buy exact gross sol formula v1 so the pumpfun dependency remains
    # explicit.
    PUMP_BUY_EXACT_GROSS_SOL_FORMULA_V1,
    PUMP_SELL_EXACT_TOKEN_IN_FORMULA_V1,
    PUMP_STATIC_PROGRAM_CONTRACT_V1,
    PUMPFUN_LEGACY_ATA_SCHEMA_ID,
    PUMPFUN_TOKEN_2022_ATA_SCHEMA_ID,
    PUMPFUN_UVA_SCHEMA_ID,
)

_POSITION_COUNT = 16_385
# Bind sol once as an explicit module-level contract.
_SOL = AssetId("SOL")
_RUNTIME_LOCK_ID = RuntimeLockId("9" * 64)
_STARTED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def test_successful_run_v3_publishes_16385_open_positions_outside_manifest(
    tmp_path: Path,
    # Close the test successful run v3 publishes 16385 open positions outside manifest
    # signature after its explicit inputs.
) -> None:
    # Execute the test successful run v3 publishes 16385 open positions outside manifest
    # workflow in explicit, reviewable steps.
    artifacts = LocalArtifactRepository(tmp_path / "var")
    snapshot_id = _publish_input_snapshot(artifacts)
    spec = _resolved_spec(snapshot_id)
    settings = RunPhysicalSettings(
        backend=RunBackend.REFERENCE_PUMPFUN_SNIPING,
        # Pass reader batch rows explicitly so RunPhysicalSettings receives a reviewable
        # reference pumpfun sniping and run backend input in test successful run v3
        # publishes 16385 open positions outside manifest.
        reader_batch_rows=65_536,
        reader_readahead=1,
        output_buffer_rows=1_024,
        threads=1,
    )
    # Assemble attempt nonce once so the test successful run v3 publishes 16385 open
    # positions outside manifest workflow shares one value.
    attempt_nonce = ContentDigest("8" * 64)
    execution_attempt_id = spec.execution_attempt_id(
        attempt_nonce,
        settings.identity_digest,
    )
    # Assemble session once so the test successful run v3 publishes 16385 open positions
    # outside manifest workflow shares one value.
    session = LocalParquetRunOutputStore(
        artifacts,
        tmp_path / "run-work",
    ).start(
        spec=spec,
        # Pass execution attempt id explicitly so start receives a reviewable spec and
        # execution attempt id input in test successful run v3 publishes 16385 open
        # positions outside manifest.
        execution_attempt_id=execution_attempt_id,
        physical_settings=settings,
    )

    ledger_hasher = CanonicalStreamHasher("backtest.sniping-ledger-stream.v2")
    fill_hasher = CanonicalStreamHasher("backtest.sniping-fill-stream.v1")
    # Assemble roundtrip hasher once so the test successful run v3 publishes 16385 open
    # positions outside manifest workflow shares one value.
    roundtrip_hasher = CanonicalStreamHasher("backtest.sniping-roundtrip-stream.v4")
    balances_hasher = CanonicalStreamHasher("backtest.sniping-final-balances.v1")
    final_balances = _final_balances()
    for row in final_balances:
        balances_hasher.append(list(row))
    # Traverse range(_POSITION_COUNT) explicitly so each test successful run v3 publishes
    # 16385 open positions outside manifest iteration remains traceable.
    for index in range(_POSITION_COUNT):
        # Process range(_POSITION_COUNT) inside the bounded test successful run v3
        # publishes 16385 open positions outside manifest loop.
        record = _open_roundtrip(index)
        ledger = _buy_ledger(index, record)
        fill = _buy_fill(index, record)
        ledger_hasher.append(ledger_document(ledger))
        fill_hasher.append(fill_document(fill))
        # Invoke append for document and record as a visible test successful run v3
        # publishes 16385 open positions outside manifest step.
        roundtrip_hasher.append(record.document())
        session.append_ledger(ledger)
        session.append_fill(fill)
        session.append_roundtrip(record)

    empty_audit = CanonicalStreamHasher("backtest.sniping-audit-stream.v1").digest
    # Assemble result document once so the test successful run v3 publishes 16385 open
    # positions outside manifest workflow shares one value.
    result_document = {
        "accepted_order_count": _POSITION_COUNT,
        "account_deposit_locked_atomic": 2_039_280 * _POSITION_COUNT + 1_844_400,
        "account_deposit_paid_atomic": 2_039_280 * _POSITION_COUNT + 1_844_400,
        "account_deposit_refunded_atomic": 0,
        # Keep the adverse slippage count component named inside the result document
        # contract.
        "adverse_slippage_count": 0,
        "buy_slippage_failure_count": 0,
        "cashback_receivable_atomic": 0,
        "closed_roundtrip_count": 0,
        "creator_fee_paid_atomic": 300_000 * _POSITION_COUNT,
        # Keep the economic pnl atomic component named inside the result document
        # contract.
        "economic_pnl_atomic": -10_000_000 * _POSITION_COUNT,
        "execution_mode": ExecutionMode.EXOGENOUS_REPLAY.value,
        "failed_buy_count": 0,
        "failed_sell_count": 0,
        "favorable_slippage_count": 0,
        "fill_count": _POSITION_COUNT,
        # Keep the fill hash component named inside the result document contract.
        "fill_hash": fill_hasher.digest.hex,
        "filled_sell_count": 0,
        "final_balances_count": len(final_balances),
        "final_balances_digest": balances_hasher.digest.hex,
        "ledger_hash": ledger_hasher.digest.hex,
        "ledger_transaction_count": _POSITION_COUNT,
        # Keep the network base fee paid atomic component named inside the result document
        # contract.
        "network_base_fee_paid_atomic": 5_000 * _POSITION_COUNT,
        "network_priority_fee_paid_atomic": _POSITION_COUNT,
        "open_position_count": _POSITION_COUNT,
        "protocol_fee_paid_atomic": 950_000 * _POSITION_COUNT,
        "real_liquidity_sufficient_filled_sell_count": 0,
        "realized_cash_pnl_atomic": 0,
        # Keep the rejected order count component named inside the result document
        # contract.
        "rejected_order_count": 0,
        "roundtrip_count": _POSITION_COUNT,
        "roundtrip_digest": roundtrip_hasher.digest.hex,
        "sell_slippage_failure_count": 0,
        "settlement_policy_id": "real-reserve-capped-v1",
        "gross_sell_settlement_atomic": 0,
        "venue_funded_sell_atomic": 0,
        "synthetic_funded_sell_atomic": 0,
        "synthetic_liquidity_used_sell_count": 0,
        "unvalued_open_position_count": 0,
        # Keep the valuation status component named inside the result document contract.
        "valuation_status": SnipingValuationStatus.COMPLETE.value,
        "valued_economic_pnl_subtotal_atomic": -10_000_000 * _POSITION_COUNT,
    }
    components = {item.role: item for item in spec.components}
    summary = SnipingRunSummary(
        # Pass dataset logical content hash explicitly so SnipingRunSummary receives a
        # reviewable engine and strategy input in test successful run v3 publishes 16385
        # open positions outside manifest.
        dataset_logical_content_hash=spec.logical_content_hash,
        replay_semantics_id=spec.replay_semantics_id,
        engine_bundle_id=components["engine"].bundle_id,
        strategy_bundle_id=components["strategy"].bundle_id,
        protocol_bundle_id=components["protocol:pumpfun"].bundle_id,
        # Pass network cost bundle id explicitly so SnipingRunSummary receives a
        # reviewable engine and strategy input in test successful run v3 publishes 16385
        # open positions outside manifest.
        network_cost_bundle_id=components["network:solana"].bundle_id,
        historical_group_count=_POSITION_COUNT,
        historical_event_count=_POSITION_COUNT,
        delivered_event_count=_POSITION_COUNT,
        target_count=_POSITION_COUNT,
        # Pass cooldown skipped count explicitly so SnipingRunSummary receives a
        # reviewable engine and strategy input in test successful run v3 publishes 16385
        # open positions outside manifest.
        cooldown_skipped_count=0,
        accepted_buy_count=_POSITION_COUNT,
        accepted_sell_count=0,
        rejected_buy_count=0,
        rejected_sell_count=0,
        # Pass accepted order count explicitly so SnipingRunSummary receives a reviewable
        # engine and strategy input in test successful run v3 publishes 16385 open
        # positions outside manifest.
        accepted_order_count=_POSITION_COUNT,
        rejected_order_count=0,
        filled_order_count=_POSITION_COUNT,
        failed_order_count=0,
        closed_roundtrip_count=0,
        # Pass open position count explicitly so SnipingRunSummary receives a reviewable
        # engine and strategy input in test successful run v3 publishes 16385 open
        # positions outside manifest.
        open_position_count=_POSITION_COUNT,
        failed_buy_count=0,
        failed_sell_count=0,
        realized_cash_pnl_atomic=0,
        valuation_status=SnipingValuationStatus.COMPLETE,
        # Pass unvalued open position count explicitly so SnipingRunSummary receives a
        # reviewable engine and strategy input in test successful run v3 publishes 16385
        # open positions outside manifest.
        unvalued_open_position_count=0,
        valued_economic_pnl_subtotal_atomic=-10_000_000 * _POSITION_COUNT,
        economic_pnl_atomic=-10_000_000 * _POSITION_COUNT,
        cashback_receivable_atomic=0,
        protocol_fee_paid_atomic=950_000 * _POSITION_COUNT,
        # Pass creator fee paid atomic explicitly so SnipingRunSummary receives a
        # reviewable engine and strategy input in test successful run v3 publishes 16385
        # open positions outside manifest.
        creator_fee_paid_atomic=300_000 * _POSITION_COUNT,
        network_base_fee_paid_atomic=5_000 * _POSITION_COUNT,
        network_priority_fee_paid_atomic=_POSITION_COUNT,
        account_deposit_paid_atomic=2_039_280 * _POSITION_COUNT + 1_844_400,
        account_deposit_refunded_atomic=0,
        # Pass account deposit locked atomic explicitly so SnipingRunSummary receives a
        # reviewable engine and strategy input in test successful run v3 publishes 16385
        # open positions outside manifest.
        account_deposit_locked_atomic=2_039_280 * _POSITION_COUNT + 1_844_400,
        favorable_slippage_count=0,
        adverse_slippage_count=0,
        buy_slippage_failure_count=0,
        sell_slippage_failure_count=0,
        # Pass ledger transaction count explicitly so SnipingRunSummary receives a
        # reviewable engine and strategy input in test successful run v3 publishes 16385
        # open positions outside manifest.
        ledger_transaction_count=_POSITION_COUNT,
        fill_count=_POSITION_COUNT,
        roundtrip_count=_POSITION_COUNT,
        audit_hash=empty_audit,
        ledger_hash=ledger_hasher.digest,
        # Pass fill hash explicitly so SnipingRunSummary receives a reviewable engine and
        # strategy input in test successful run v3 publishes 16385 open positions outside
        # manifest.
        fill_hash=fill_hasher.digest,
        roundtrip_digest=roundtrip_hasher.digest,
        final_balances_digest=balances_hasher.digest,
        result_hash=domain_digest(
            "backtest.canonical-sniping-run-result.v4",
            # Pass result document explicitly so domain_digest receives a reviewable v2
            # and result document input in test successful run v3 publishes 16385 open
            # positions outside manifest.
            result_document,
        ),
        final_balances=final_balances,
    )
    manifest = SuccessfulRunManifest.create(
        # Pass resolved spec explicitly so create receives a reviewable hex and artifact
        # id input in test successful run v3 publishes 16385 open positions outside
        # manifest.
        resolved_spec=spec,
        attempt_nonce=attempt_nonce,
        execution_attempt_id=execution_attempt_id,
        input_artifact_ids=(ArtifactId(snapshot_id.hex),),
        summary=summary,
        # Pass physical settings explicitly so create receives a reviewable hex and
        # artifact id input in test successful run v3 publishes 16385 open positions
        # outside manifest.
        physical_settings=settings,
        started_at=_STARTED_AT,
        completed_at=_STARTED_AT + timedelta(seconds=1),
    )
    committed = session.finalize(manifest, final_balances=final_balances)

    # Acquire open committed, artifact id and artifacts at an explicit test successful run
    # v3 publishes 16385 open positions outside manifest context boundary so cleanup
    # remains scoped.
    with artifacts.open_committed(committed.artifact_id) as handle:
        # Keep open committed, artifact id and artifacts active only for the bounded test
        # successful run v3 publishes 16385 open positions outside manifest operation.
        with handle.open_binary("manifest.json") as stream:
            manifest_bytes = stream.read()
        manifest_document = json.loads(manifest_bytes)
    assert len(manifest_bytes) < MAX_SUCCESSFUL_RUN_MANIFEST_BYTES
    assert "final_balances" not in manifest_document
    # Verify 'roundtrips' not in manifest_document before this scenario is accepted.
    assert "roundtrips" not in manifest_document
    assert manifest_document["summary"]["open_position_count"] == _POSITION_COUNT

    reader_factory = LocalParquetRunResultReaderFactory(artifacts)
    with reader_factory.open_exact(committed.artifact_id) as reader:
        # Keep open exact, artifact id and committed active only for the bounded test
        # successful run v3 publishes 16385 open positions outside manifest operation.
        reader.verify()
        assert (
            reader.manifest.result_table(RunResultTableRole.ROUNDTRIPS).row_count == _POSITION_COUNT
        )
        assert (
            # Keep the reader expectation tied to canonical digest, digest and roundtrip
            # hasher in this scenario.
            reader.manifest.result_table(RunResultTableRole.ROUNDTRIPS).canonical_digest
            == roundtrip_hasher.digest
        )
        assert (
            reader.manifest.result_table(RunResultTableRole.FINAL_BALANCES).row_count
            # Keep the position count expectation tied to row count, position count and
            # result table in this scenario.
            == _POSITION_COUNT
        )
        assert (
            reader.manifest.result_table(RunResultTableRole.FINAL_BALANCES).canonical_digest
            == balances_hasher.digest
            # Verify the canonical digest, digest and balances hasher relationship before this
            # scenario is accepted.
        )
        first_page = reader.roundtrips(after=None, limit=200)
        assert len(first_page.items) == 200
        assert first_page.next_cursor is not None

    # A new reader from the same bounded factory may reuse semantic evidence only after
    # the repository has re-authenticated the exact immutable artifact tree.
    with reader_factory.open_exact(committed.artifact_id) as cached_reader:
        second_page = cached_reader.roundtrips(after=first_page.next_cursor, limit=25)
        assert len(second_page.items) == 25


def _publish_input_snapshot(artifacts: LocalArtifactRepository) -> SnapshotId:
    # Execute the publish input snapshot workflow in explicit, reviewable steps.
    writer = artifacts.stage(ArtifactDraft(ArtifactKind.SNAPSHOT, ContentDigest("a" * 64)))
    committed = writer.commit(canonical_json_bytes({"fixture": "sniping-result-capacity-v1"}))
    return SnapshotId(committed.artifact_id.hex)


def _resolved_spec(snapshot_id: SnapshotId) -> ResolvedRunSpec:
    # Execute the resolved spec workflow in explicit, reviewable steps.
    draft = PumpfunSnipingRunDraft(
        dataset_revision_id=DatasetRevisionId("1" * 64),
        snapshot_id=snapshot_id,
        replay_pack_id=None,
        initial_sol_balance_lamports=10**15,
        # Pass gross buy budget lamports explicitly so PumpfunSnipingRunDraft receives a
        # reviewable 1 and fresh-result-capacity-v1 input in resolved spec.
        gross_buy_budget_lamports=100_000_000,
        buy_slippage_bps=100,
        sell_slippage_bps=100,
        execution_mode=ExecutionMode.EXOGENOUS_REPLAY,
        sell_delay_transactions=1,
        wallet_account_profile=WalletAccountProfileDraft(
            # Pass profile id explicitly so WalletAccountProfileDraft receives a
            # reviewable fresh-result-capacity-v1 and pump-token-account-v1 input in
            # resolved spec.
            profile_id="fresh-result-capacity-v1",
            initial_uva_state=WalletAccountMode.FRESH,
            effective_from_unix_s=1_700_000_000,
            effective_until_unix_s=1_800_000_000,
            account_costs=(
                SolanaAccountDepositCostDraft(PUMPFUN_UVA_SCHEMA_ID, 1_844_400),
                SolanaAccountDepositCostDraft(PUMPFUN_LEGACY_ATA_SCHEMA_ID, 2_039_280),
                SolanaAccountDepositCostDraft(PUMPFUN_TOKEN_2022_ATA_SCHEMA_ID, 2_074_080),
            ),
        ),
        # Keep the pump fee profile draft and pump-static-95-30-result-capacity-v1
        # PumpFeeProfileDraft step visible while building draft.
        pump_fee_profile=PumpFeeProfileDraft(
            profile_id="pump-static-95-30-result-capacity-v1",
            program_version=PUMP_STATIC_PROGRAM_CONTRACT_V1,
            buy_formula_version=PUMP_BUY_EXACT_GROSS_SOL_FORMULA_V1,
            sell_formula_version=PUMP_SELL_EXACT_TOKEN_IN_FORMULA_V1,
            # Pass effective from unix s explicitly so PumpFeeProfileDraft receives a
            # reviewable pump-static-95-30-result-capacity-v1 and pump static program
            # contract v1 input in resolved spec.
            effective_from_unix_s=1_700_000_000,
            effective_until_unix_s=1_800_000_000,
            protocol_fee_bps=95,
            creator_fee_bps=30,
        ),
        # Keep the buy-result-capacity-v1 _fee_profile step visible while building draft.
        buy_solana_fee_profile=_fee_profile("buy-result-capacity-v1"),
        sell_solana_fee_profile=_fee_profile("sell-result-capacity-v1"),
        root_seed=7,
    )
    configs = sniping_component_configs(draft)
    # Assemble closure once so the resolved spec workflow shares one value.
    closure = PumpfunSnipingBundleRegistry().snapshot()
    components = tuple(
        ResolvedComponent.create(
            role=item.role,
            bundle_id=item.bundle_id,
            # Pass api version explicitly so create receives a reviewable role and bundle
            # id input in resolved spec.
            api_version=item.api_version,
            config=configs[item.role],
        )
        for item in closure.manifests
    )
    # Return the completed resolved spec result without a hidden fallback.
    return ResolvedRunSpec.create(
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        dataset_revision_id=draft.dataset_revision_id,
        logical_content_hash=LogicalContentHash("2" * 64),
        # Pass snapshot id explicitly so create receives a reviewable 2 and 3 input in
        # resolved spec.
        snapshot_id=snapshot_id,
        replay_semantics_id=ContentDigest("3" * 64),
        replay_input=ResolvedReplayInput(ReplayInputFormat.CANONICAL_PARQUET),
        components=components,
        runtime_lock_id=_RUNTIME_LOCK_ID,
        # Include initial portfolio in the completed resolved spec result.
        initial_portfolio=(AssetBalance(_SOL, 10**15),),
        root_seed=draft.root_seed,
    )


def _fee_profile(profile_id: str) -> SolanaFeeProfileDraft:
    # Execute the fee profile workflow in explicit, reviewable steps.
    return SolanaFeeProfileDraft(
        profile_id=profile_id,
        formula_version=SOLANA_LEGACY_V0_FEE_FORMULA_V1,
        transaction_format="V0",
        effective_from_unix_s=1_700_000_000,
        # Pass effective until unix s explicitly so SolanaFeeProfileDraft receives a
        # reviewable v0 and profile id input in fee profile.
        effective_until_unix_s=1_800_000_000,
        charged_signature_count=1,
        lamports_per_signature=5_000,
        compute_unit_limit=100_000,
        micro_lamports_per_compute_unit=10,
        # Complete SolanaFeeProfileDraft only after its v0 and profile id inputs are visible
        # in fee profile.
    )


def _open_roundtrip(index: int) -> RoundTripRecord:
    # Execute the open roundtrip workflow in explicit, reviewable steps.
    target = _position(index + 1, 0, 0)
    landing = _position(index + 1, 500, None)
    roundtrip_id = _digest(1, index)
    ata = AccountComponentRecord(
        requirement_schema_id=PUMPFUN_LEGACY_ATA_SCHEMA_ID,
        asset_id=_SOL,
        scope=AccountRequirementScope.MINT,
        release_policy=AccountReleasePolicy.CLOSE_ON_SUCCESSFUL_SELL,
        maximum_reserved_atomic=2_039_280,
        paid_atomic=2_039_280,
        released_atomic=0,
        refunded_atomic=0,
        locked_delta_atomic=2_039_280,
        lifecycle=AccountComponentLifecycle.CREATED_LOCKED,
        attribution_kind=LedgerCorrelationKind.ROUNDTRIP,
        attribution_id=roundtrip_id,
    )
    uva_created = index == 0
    uva = AccountComponentRecord(
        requirement_schema_id=PUMPFUN_UVA_SCHEMA_ID,
        asset_id=_SOL,
        scope=AccountRequirementScope.WALLET,
        release_policy=AccountReleasePolicy.RUN_LOCKED,
        maximum_reserved_atomic=1_844_400 if uva_created else 0,
        paid_atomic=1_844_400 if uva_created else 0,
        released_atomic=0,
        refunded_atomic=0,
        locked_delta_atomic=1_844_400 if uva_created else 0,
        lifecycle=(
            AccountComponentLifecycle.CREATED_LOCKED
            if uva_created
            else AccountComponentLifecycle.EXISTING_RUN_LOCKED
        ),
        attribution_kind=LedgerCorrelationKind.ROUNDTRIP,
        attribution_id=roundtrip_id,
    )
    quote_cashflow = -102_039_280 - (1_844_400 if uva_created else 0)
    mtm_liquidation = 92_039_280
    mtm_cash = quote_cashflow + mtm_liquidation
    return RoundTripRecord(
        roundtrip_id=roundtrip_id,
        network_id=SOLANA_MAINNET_NETWORK_ID,
        # Pass position schema id explicitly so RoundTripRecord receives a reviewable
        # developer- and 05d input in open roundtrip.
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        target_event_id=_digest(2, index),
        target_position=target,
        target_time_ns=(1_750_000_000 + index) * 1_000_000_000,
        developer_id=AccountId(f"developer-{index:05d}"),
        # Include creation user id in the completed open roundtrip result.
        creation_user_id=AccountId(f"payer-{index:05d}"),
        asset_id=AssetId(f"TOKEN-{index:05d}"),
        quote_asset_id=_SOL,
        venue_id=VenueId(f"pump-curve-{index:05d}"),
        cooldown_consumed=True,
        # Pass cooldown until ns explicitly so RoundTripRecord receives a reviewable
        # developer- and 05d input in open roundtrip.
        cooldown_until_ns=(1_750_000_600 + index) * 1_000_000_000,
        status=RoundTripStatus.OPEN_AT_HORIZON,
        buy=RoundTripLegRecord(
            side=RoundTripLegSide.BUY,
            decision_position=target,
            # Pass landing position explicitly so RoundTripLegRecord receives a reviewable
            # buy and round trip leg side input in open roundtrip.
            landing_position=landing,
            amount_in_atomic=100_000_000,
            reference_out_atomic=1_000,
            landing_out_atomic=1_000,
            minimum_out_atomic=990,
            # Pass signed slippage atomic explicitly so RoundTripLegRecord receives a
            # reviewable buy and round trip leg side input in open roundtrip.
            signed_slippage_atomic=0,
            protocol_fee_atomic=950_000,
            creator_fee_atomic=300_000,
            network_base_fee_atomic=5_000,
            network_priority_fee_atomic=1,
            # Complete RoundTripLegRecord only after its buy and round trip leg side inputs
            # are visible in open roundtrip.
        ),
        sell=None,
        acquired_token_amount_atomic=1_000,
        cashback_receivable_atomic=0,
        # Pass realized cash pnl atomic explicitly so RoundTripRecord receives a
        # reviewable developer- and 05d input in open roundtrip.
        realized_cash_pnl_atomic=None,
        mtm_status=MtmStatus.EXECUTABLE,
        mtm_liquidation_value_atomic=mtm_liquidation,
        mtm_cash_pnl_atomic=mtm_cash,
        economic_pnl_atomic=-10_000_000,
        # Pass account profile id explicitly so RoundTripRecord receives a reviewable
        # developer- and 05d input in open roundtrip.
        account_profile_id="capacity-fresh-v1",
        account_components=(ata, uva),
        # Complete RoundTripRecord only after its developer- and 05d inputs are visible in
        # open roundtrip.
    )


def _buy_ledger(index: int, record: RoundTripRecord) -> LedgerTransaction:
    # Execute the buy ledger workflow in explicit, reviewable steps.
    portfolio_sol = LedgerAccount(
        AccountId("portfolio:available:SOL"),
        AccountKind.PORTFOLIO_AVAILABLE,
    )
    venue_sol = LedgerAccount(
        # Keep the account id and venue:sol: AccountId step visible while building venue
        # sol.
        AccountId(f"venue:sol:{index:05d}"),
        AccountKind.VENUE,
    )
    portfolio_token = LedgerAccount(
        AccountId(f"portfolio:available:TOKEN-{index:05d}"),
        # Pass account kind explicitly so LedgerAccount receives a reviewable
        # portfolio:available:token- and 05d input in buy ledger.
        AccountKind.PORTFOLIO_AVAILABLE,
    )
    venue_token = LedgerAccount(
        AccountId(f"venue:token:{index:05d}"),
        AccountKind.VENUE,
        # Complete LedgerAccount only after its venue:token: and 05d inputs are visible in buy
        # ledger.
    )
    account_postings: list[Posting] = []
    for component in record.account_components:
        # Only the first UVA and this round trip's ATA create deposit cashflow.
        if component.paid_atomic == 0:
            continue
        owner = (
            "wallet"
            if component.scope is AccountRequirementScope.WALLET
            else (f"mint:{record.roundtrip_id.hex}")
        )
        locked = LedgerAccount(
            AccountId(
                f"portfolio:locked-account-deposit:{owner}:{component.requirement_schema_id}"
            ),
            AccountKind.PORTFOLIO_LOCKED,
        )
        account_postings.extend(
            (
                Posting(portfolio_sol, _SOL, -component.paid_atomic),
                Posting(locked, _SOL, component.paid_atomic),
            )
        )
    return LedgerTransaction(
        transaction_id=_digest(3, index),
        correlation_kind=LedgerCorrelationKind.ROUNDTRIP,
        correlation_id=record.roundtrip_id,
        # Pass boundary ordinal explicitly so LedgerTransaction receives a reviewable buy
        # settled and roundtrip input in buy ledger.
        boundary_ordinal=record.buy.landing_position.boundary_ordinal
        if record.buy is not None and record.buy.landing_position is not None
        else record.target_position.boundary_ordinal,
        postings=(
            Posting(portfolio_sol, _SOL, -100_000_000),
            # Include posting in the completed buy ledger result.
            Posting(venue_sol, _SOL, 100_000_000),
            *account_postings,
            Posting(portfolio_token, record.asset_id, 1_000),
            Posting(venue_token, record.asset_id, -1_000),
        ),
        reason="BUY_SETTLED",
        # Complete LedgerTransaction only after its buy settled and roundtrip inputs are
        # visible in buy ledger.
    )


def _buy_fill(index: int, record: RoundTripRecord) -> Fill:
    # Execute the buy fill workflow in explicit, reviewable steps.
    if record.buy is None or record.buy.landing_position is None:
        raise AssertionError("capacity fixture buy must be landed")
    return Fill(
        order_id=OrderId(_digest(4, index).hex),
        pool_id=PoolId(record.venue_id.value),
        # Pass sold asset id explicitly so Fill receives a reviewable hex and value input
        # in buy fill.
        sold_asset_id=_SOL,
        bought_asset_id=record.asset_id,
        amount_in_atomic=100_000_000,
        amount_out_atomic=1_000,
        fee_amount_atomic=1_250_000,
        # Pass boundary ordinal explicitly so Fill receives a reviewable hex and value
        # input in buy fill.
        boundary_ordinal=record.buy.landing_position.boundary_ordinal,
    )


def _final_balances() -> tuple[tuple[str, str, str, int], ...]:
    # Execute the final balances workflow in explicit, reviewable steps.
    return tuple(
        (
            f"portfolio:available:TOKEN-{index:05d}",
            AccountKind.PORTFOLIO_AVAILABLE.value,
            f"TOKEN-{index:05d}",
            # Pass 000 explicitly so tuple receives a reviewable
            # portfolio:available:token- and token- input in final balances.
            1_000,
        )
        for index in range(_POSITION_COUNT)
    )


def _position(
    # Keep the block input explicit in the position contract.
    block: int,
    transaction: int,
    event_index: int | None,
) -> ChainPosition:
    # Execute the position workflow in explicit, reviewable steps.
    return ChainPosition(
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        block_ordinal=block,
        transaction_index=transaction,
        # Pass event index explicitly so ChainPosition receives a reviewable solana
        # mainnet network id and block32 transaction32 position schema id input in
        # position.
        event_index=event_index,
    )


def _digest(namespace: int, value: int) -> ContentDigest:
    return ContentDigest(f"{((namespace << 48) | value):064x}")
