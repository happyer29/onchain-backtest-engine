# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from dataclasses import replace

import pytest

from backtest.adapters.results.parquet import (
    RunOutputIntegrityError,
    # Include sniping ledger reconciler so the parquet dependency remains explicit.
    _SnipingLedgerReconciler,
)
from backtest.application.run_results import (
    LEGACY_PUMPFUN_SNIPING_SUMMARY_SCHEMA,
    PumpfunSnipingSummaryMetadata,
    RunComparisonProjection,
    _summary_metadata_from_document,
    # Close the run results import after its required symbols are visible.
)
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
from backtest.domain.execution import ExecutionMode
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import (
    AccountId,
    AssetId,
    # Include bundle id so the identifiers dependency remains explicit.
    BundleId,
    ContentDigest,
    VenueId,
)
from backtest.domain.ledger import (
    # Include account kind so the ledger dependency remains explicit.
    AccountKind,
    LedgerAccount,
    LedgerCorrelationKind,
    LedgerTransaction,
    Posting,
    # Close the ledger import after its required symbols are visible.
)
from backtest.domain.roundtrips import (
    ROUNDTRIP_RESULT_SCHEMA_V3,
    ROUNDTRIP_RESULT_SCHEMA_V4,
    MtmStatus,
    QuoteLiquidityEvidenceRecord,
    RoundTripLegRecord,
    RoundTripLegSide,
    RoundTripRecord,
    RoundTripStatus,
    roundtrip_record_from_document,
)
from backtest.engine.sniping import SnipingValuationStatus
from backtest.engine.sniping_contracts import synthetic_liquidity_account_id

SOL = AssetId("SOL")

# These exact additions distinguish row v4 from immutable legacy row v3 bytes.
_V4_ROUNDTRIP_FIELDS = {
    "execution_mode",
    "mtm_liquidity",
    "sell_landing_liquidity",
    "sell_reference_liquidity",
    "settled_synthetic_funded_atomic",
    "settled_venue_funded_atomic",
}

# Summary v3 additions are removed only to construct an original-schema test vector.
_V3_SUMMARY_FIELDS = {
    "execution_mode",
    "filled_sell_count",
    "gross_sell_settlement_atomic",
    "real_liquidity_sufficient_filled_sell_count",
    "settlement_policy_id",
    "synthetic_funded_sell_atomic",
    "synthetic_liquidity_used_sell_count",
    "venue_funded_sell_atomic",
}


def test_reconciliation_accepts_ledger_derived_closed_and_open_pnl() -> None:
    # Execute the test reconciliation accepts ledger derived closed and open pnl workflow
    # in explicit, reviewable steps.
    closed = _roundtrip(1, status=RoundTripStatus.CLOSED, cashflow=-10)
    opened = _roundtrip(2, status=RoundTripStatus.OPEN_AT_HORIZON, cashflow=-10)
    reconciler = _SnipingLedgerReconciler()

    for record in (closed, opened):
        # Process (closed, opened) inside the bounded test reconciliation accepts ledger
        # derived closed and open pnl loop.
        reconciler.append_ledger(_ledger(record, cashflow=-10))
        reconciler.append_roundtrip(record)

    reconciler.verify_summary(
        _summary(
            target_count=2,
            # Pass closed count explicitly into _summary within test reconciliation
            # accepts ledger derived closed and open pnl.
            closed_count=1,
            open_count=1,
            realized=-10,
            valued_economic=-15,
        )
        # Complete verify_summary only after its summary inputs are visible in test
        # reconciliation accepts ledger derived closed and open pnl.
    )


def test_reconciliation_rejects_tampered_roundtrip_pnl() -> None:
    # Execute the test reconciliation rejects tampered roundtrip pnl workflow in explicit,
    # reviewable steps.
    record = _roundtrip(1, status=RoundTripStatus.CLOSED, cashflow=-10)
    reconciler = _SnipingLedgerReconciler()
    reconciler.append_ledger(_ledger(record, cashflow=-10))

    with pytest.raises(RunOutputIntegrityError, match="realized cash PnL"):
        # Keep raises, run output integrity error and pytest active only for the bounded
        # test reconciliation rejects tampered roundtrip pnl operation.
        reconciler.append_roundtrip(
            replace(record, realized_cash_pnl_atomic=-9, economic_pnl_atomic=-9)
        )


def test_reconciliation_rejects_tampered_open_mtm_pnl() -> None:
    # Execute the test reconciliation rejects tampered open mtm pnl workflow in explicit,
    # reviewable steps.
    record = _roundtrip(1, status=RoundTripStatus.OPEN_AT_HORIZON, cashflow=-10)
    reconciler = _SnipingLedgerReconciler()
    reconciler.append_ledger(_ledger(record, cashflow=-10))

    with pytest.raises(RunOutputIntegrityError, match="MTM cash PnL"):
        reconciler.append_roundtrip(replace(record, mtm_cash_pnl_atomic=-4, economic_pnl_atomic=-4))


# Define test reconciliation rejects missing and orphan ledger correlations as one focused
# operation with an explicit boundary.
def test_reconciliation_rejects_missing_and_orphan_ledger_correlations() -> None:
    # Execute the test reconciliation rejects missing and orphan ledger correlations
    # workflow in explicit, reviewable steps.
    record = _roundtrip(1, status=RoundTripStatus.CLOSED, cashflow=-10)

    missing = _SnipingLedgerReconciler()
    with pytest.raises(RunOutputIntegrityError, match="ledger presence"):
        missing.append_roundtrip(record)

    orphan = _SnipingLedgerReconciler()
    # Invoke append_ledger for ledger and record as a visible test reconciliation rejects
    # missing and orphan ledger correlations step.
    orphan.append_ledger(_ledger(record, cashflow=-10))
    with pytest.raises(RunOutputIntegrityError, match="orphan correlations"):
        orphan.verify_summary(_summary(target_count=0))


def test_reconciliation_rejects_duplicate_or_wrong_kind_correlations() -> None:
    # Execute the test reconciliation rejects duplicate or wrong kind correlations
    # workflow in explicit, reviewable steps.
    rejected = _roundtrip(
        1,
        status=RoundTripStatus.BUY_PRE_SUBMIT_INSUFFICIENT_FUNDS,
        cashflow=0,
    )
    # Assemble duplicate once so the test reconciliation rejects duplicate or wrong kind
    # correlations workflow shares one value.
    duplicate = _SnipingLedgerReconciler()
    duplicate.append_roundtrip(rejected)
    with pytest.raises(RunOutputIntegrityError, match="duplicated"):
        duplicate.append_roundtrip(rejected)

    closed = _roundtrip(2, status=RoundTripStatus.CLOSED, cashflow=-10)
    # Assemble wrong kind once so the test reconciliation rejects duplicate or wrong kind
    # correlations workflow shares one value.
    wrong_kind = _SnipingLedgerReconciler()
    with pytest.raises(RunOutputIntegrityError, match="ROUNDTRIP-correlated"):
        # Keep raises, run output integrity error and pytest active only for the bounded
        # test reconciliation rejects duplicate or wrong kind correlations operation.
        wrong_kind.append_ledger(
            replace(_ledger(closed, cashflow=-10), correlation_kind=LedgerCorrelationKind.ORDER)
        )


def test_reconciliation_rejects_tampered_summary_pnl() -> None:
    # Execute the test reconciliation rejects tampered summary pnl workflow in explicit,
    # reviewable steps.
    record = _roundtrip(1, status=RoundTripStatus.CLOSED, cashflow=-10)
    reconciler = _SnipingLedgerReconciler()
    reconciler.append_ledger(_ledger(record, cashflow=-10))
    reconciler.append_roundtrip(record)

    with pytest.raises(RunOutputIntegrityError, match="run summary"):
        # Keep raises, run output integrity error and pytest active only for the bounded
        # test reconciliation rejects tampered summary pnl operation.
        reconciler.verify_summary(
            _summary(
                target_count=1,
                closed_count=1,
                realized=-9,
                # Pass valued economic explicitly into _summary within test reconciliation
                # rejects tampered summary pnl.
                valued_economic=-10,
            )
        )


def test_reconciliation_matches_virtual_funding_across_row_ledger_and_summary() -> None:
    """A synthetic sell source must reconcile at all three result boundaries."""

    record = _virtual_closed_roundtrip(1, venue_funded=3, synthetic_funded=7)
    reconciler = _SnipingLedgerReconciler()
    reconciler.append_ledger(_virtual_sell_ledger(record, venue_funded=3, synthetic_funded=7))
    reconciler.append_roundtrip(record)
    reconciler.verify_summary(
        _summary(
            target_count=1,
            closed_count=1,
            realized=10,
            valued_economic=10,
            execution_mode=ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT,
            venue_funded=3,
            synthetic_funded=7,
        )
    )


def test_reconciliation_rejects_synthetic_ledger_amount_tampering() -> None:
    """A balanced ledger still fails if its synthetic split differs from the result row."""

    record = _virtual_closed_roundtrip(1, venue_funded=3, synthetic_funded=7)
    reconciler = _SnipingLedgerReconciler()
    reconciler.append_ledger(_virtual_sell_ledger(record, venue_funded=2, synthetic_funded=8))
    with pytest.raises(RunOutputIntegrityError, match="synthetic ledger funding"):
        reconciler.append_roundtrip(record)


def test_reconciliation_rejects_wrong_synthetic_funding_account() -> None:
    """A prefix-compatible but non-canonical synthetic source cannot fund a row."""

    record = _virtual_closed_roundtrip(1, venue_funded=3, synthetic_funded=7)
    reconciler = _SnipingLedgerReconciler()
    ledger = _virtual_sell_ledger(
        record,
        venue_funded=3,
        synthetic_funded=7,
        synthetic_account=AccountId("synthetic-liquidity:pumpfun:tampered"),
    )
    reconciler.append_ledger(ledger)
    with pytest.raises(RunOutputIntegrityError, match="synthetic ledger funding"):
        reconciler.append_roundtrip(record)


@pytest.mark.parametrize(
    ("venue_funded", "venue_account"),
    (
        (2, None),
        (3, AccountId("venue:tampered")),
    ),
)
def test_reconciliation_rejects_wrong_venue_funding_debit(
    venue_funded: int,
    venue_account: AccountId | None,
) -> None:
    """Venue settlement must use the row's exact venue account and amount."""

    record = _virtual_closed_roundtrip(1, venue_funded=3, synthetic_funded=7)
    reconciler = _SnipingLedgerReconciler()
    ledger = _virtual_sell_ledger(
        record,
        venue_funded=venue_funded,
        synthetic_funded=7,
        venue_account=venue_account,
    )
    reconciler.append_ledger(ledger)
    with pytest.raises(RunOutputIntegrityError, match="venue ledger funding"):
        reconciler.append_roundtrip(record)


def test_roundtrip_v4_codec_requires_and_preserves_liquidity_contract() -> None:
    """The new codec preserves exact evidence and rejects a mismatched funding split."""

    record = _virtual_closed_roundtrip(1, venue_funded=3, synthetic_funded=7)
    decoded = roundtrip_record_from_document(
        record.document(),
        schema_id=ROUNDTRIP_RESULT_SCHEMA_V4,
    )
    assert decoded == record
    with pytest.raises(ValueError, match="landing shortfall"):
        replace(record, settled_synthetic_funded_atomic=6)

    # Gross liquidity must fund the exact net sell output and both Pump fee routes.
    assert record.sell is not None
    tampered_sell = replace(record.sell, protocol_fee_atomic=1)
    tampered_record = replace(record, sell=tampered_sell)
    with pytest.raises(ValueError, match="net output plus Pump fees"):
        roundtrip_record_from_document(
            tampered_record.document(),
            schema_id=ROUNDTRIP_RESULT_SCHEMA_V4,
        )


def test_roundtrip_v3_codec_reads_original_fields_without_upgrading_document() -> None:
    """Legacy bytes select the v3 codec explicitly and retain their fixed old mode."""

    document = _roundtrip(
        1,
        status=RoundTripStatus.OPEN_AT_HORIZON,
        cashflow=-10,
    ).document()
    for field_name in _V4_ROUNDTRIP_FIELDS:
        document.pop(field_name)
    decoded = roundtrip_record_from_document(document, schema_id=ROUNDTRIP_RESULT_SCHEMA_V3)
    assert decoded.execution_mode is ExecutionMode.EXOGENOUS_REPLAY
    assert decoded.sell_reference_liquidity is None
    assert decoded.document() == document
    with pytest.raises(ValueError, match="schema is invalid"):
        roundtrip_record_from_document(document)


def test_summary_v2_codec_reemits_original_schema_without_v3_totals() -> None:
    """Committed summary v2 bytes remain byte-shape stable after strict decoding."""

    document = _summary(target_count=1, closed_count=1).document()
    for field_name in _V3_SUMMARY_FIELDS:
        document.pop(field_name)
    document["schema"] = LEGACY_PUMPFUN_SNIPING_SUMMARY_SCHEMA
    decoded = _summary_metadata_from_document(document)
    assert isinstance(decoded, PumpfunSnipingSummaryMetadata)
    assert decoded.source_schema_id == LEGACY_PUMPFUN_SNIPING_SUMMARY_SCHEMA
    assert decoded.document() == document


def test_summary_v3_codec_preserves_virtual_settlement_conservation() -> None:
    """Summary v3 round-trips its explicit gross, venue, and synthetic totals."""

    summary = _summary(
        target_count=1,
        closed_count=1,
        realized=10,
        valued_economic=10,
        execution_mode=ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT,
        venue_funded=3,
        synthetic_funded=7,
    )
    decoded = _summary_metadata_from_document(summary.document())
    assert decoded == summary
    with pytest.raises(ValueError, match="does not conserve"):
        replace(summary, gross_sell_settlement_atomic=9)


def _roundtrip(
    ordinal: int,
    # Close the roundtrip signature after its explicit inputs.
    *,
    status: RoundTripStatus,
    cashflow: int,
) -> RoundTripRecord:
    # Execute the roundtrip workflow in explicit, reviewable steps.
    is_open = status is RoundTripStatus.OPEN_AT_HORIZON
    acquired = 1 if status in {RoundTripStatus.OPEN_AT_HORIZON, RoundTripStatus.CLOSED} else 0
    realized = None if is_open else cashflow
    mtm_value = 5 if is_open else None
    mtm_cash = cashflow + mtm_value if mtm_value is not None else None
    # Assemble economic once so the roundtrip workflow shares one value.
    economic = mtm_cash if is_open else realized
    roundtrip_id = _digest("roundtrip", ordinal)
    target_position = ChainPosition(
        SOLANA_MAINNET_NETWORK_ID,
        BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        ordinal,
        0,
        0,
    )
    if status is RoundTripStatus.CLOSED:
        lifecycle = AccountComponentLifecycle.CLOSED_REFUNDED
        paid = refunded = 1
    elif is_open:
        lifecycle = AccountComponentLifecycle.CREATED_LOCKED
        paid, refunded = 1, 0
    else:
        lifecycle = AccountComponentLifecycle.NOT_CREATED
        paid = refunded = 0
    account_component = AccountComponentRecord(
        requirement_schema_id="test-token-account-v1",
        asset_id=SOL,
        scope=AccountRequirementScope.MINT,
        release_policy=AccountReleasePolicy.CLOSE_ON_SUCCESSFUL_SELL,
        maximum_reserved_atomic=1,
        paid_atomic=paid,
        released_atomic=0,
        refunded_atomic=refunded,
        locked_delta_atomic=paid - refunded,
        lifecycle=lifecycle,
        attribution_kind=LedgerCorrelationKind.ROUNDTRIP,
        attribution_id=roundtrip_id,
    )
    wallet_component = AccountComponentRecord(
        requirement_schema_id="test-wallet-account-v1",
        asset_id=SOL,
        scope=AccountRequirementScope.WALLET,
        release_policy=AccountReleasePolicy.RUN_LOCKED,
        maximum_reserved_atomic=0,
        paid_atomic=0,
        released_atomic=0,
        refunded_atomic=0,
        locked_delta_atomic=0,
        lifecycle=AccountComponentLifecycle.PREWARMED,
        attribution_kind=LedgerCorrelationKind.ROUNDTRIP,
        attribution_id=roundtrip_id,
    )
    sell = None
    sell_evidence = None
    settled_venue = 0
    if status is RoundTripStatus.CLOSED:
        # A closed v4 row carries one positive, fully venue-funded sell quote.
        sell_evidence = QuoteLiquidityEvidenceRecord(
            policy_id="real-reserve-capped-v1",
            asset_id=SOL,
            required_output_atomic=1,
            observed_available_output_atomic=1,
            synthetic_shortfall_atomic=0,
        )
        sell = RoundTripLegRecord(
            side=RoundTripLegSide.SELL,
            decision_position=target_position,
            landing_position=ChainPosition(
                SOLANA_MAINNET_NETWORK_ID,
                BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
                ordinal,
                1,
                None,
            ),
            amount_in_atomic=1,
            reference_out_atomic=1,
            landing_out_atomic=1,
            minimum_out_atomic=1,
            signed_slippage_atomic=0,
            # The focused settlement evidence has no fee components.
            protocol_fee_atomic=0,
            creator_fee_atomic=0,
            network_base_fee_atomic=0,
            network_priority_fee_atomic=0,
        )
        settled_venue = 1
    return RoundTripRecord(
        roundtrip_id=roundtrip_id,
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        # Include target event id in the completed roundtrip result.
        target_event_id=_digest("event", ordinal),
        target_position=target_position,
        target_time_ns=ordinal * 1_000_000_000,
        developer_id=AccountId(f"developer-{ordinal}"),
        # Include creation user id in the completed roundtrip result.
        creation_user_id=AccountId(f"creator-{ordinal}"),
        asset_id=AssetId(f"TOKEN-{ordinal}"),
        quote_asset_id=SOL,
        venue_id=VenueId(f"curve-{ordinal}"),
        cooldown_consumed=True,
        # Pass cooldown until ns explicitly so RoundTripRecord receives a reviewable
        # roundtrip and event input in roundtrip.
        cooldown_until_ns=(ordinal + 600) * 1_000_000_000,
        status=status,
        buy=None,
        sell=sell,
        acquired_token_amount_atomic=acquired,
        cashback_receivable_atomic=0,
        realized_cash_pnl_atomic=realized,
        mtm_status=MtmStatus.EXECUTABLE if is_open else MtmStatus.NOT_APPLICABLE,
        mtm_liquidation_value_atomic=mtm_value,
        # Pass mtm cash pnl atomic explicitly so RoundTripRecord receives a reviewable
        # roundtrip and event input in roundtrip.
        mtm_cash_pnl_atomic=mtm_cash,
        economic_pnl_atomic=economic,
        account_profile_id="test-fresh-v1",
        account_components=(account_component, wallet_component),
        sell_reference_liquidity=sell_evidence,
        sell_landing_liquidity=sell_evidence,
        settled_venue_funded_atomic=settled_venue,
        # Complete RoundTripRecord only after its roundtrip and event inputs are visible in
        # roundtrip.
    )


def _virtual_closed_roundtrip(
    ordinal: int,
    *,
    venue_funded: int,
    synthetic_funded: int,
) -> RoundTripRecord:
    """Build one fully evidenced virtual-settlement result row."""

    base = _roundtrip(ordinal, status=RoundTripStatus.CLOSED, cashflow=10)
    landing = ChainPosition(
        SOLANA_MAINNET_NETWORK_ID,
        BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        ordinal,
        1,
        None,
    )
    required = venue_funded + synthetic_funded
    evidence = QuoteLiquidityEvidenceRecord(
        policy_id="virtual-reserve-output-with-explicit-synthetic-shortfall-v1",
        asset_id=SOL,
        required_output_atomic=required,
        observed_available_output_atomic=venue_funded,
        synthetic_shortfall_atomic=synthetic_funded,
    )
    sell = RoundTripLegRecord(
        side=RoundTripLegSide.SELL,
        decision_position=base.target_position,
        landing_position=landing,
        amount_in_atomic=1,
        reference_out_atomic=required,
        landing_out_atomic=required,
        minimum_out_atomic=required,
        # The focused quote has no Pump or Solana fees.
        signed_slippage_atomic=0,
        protocol_fee_atomic=0,
        creator_fee_atomic=0,
        network_base_fee_atomic=0,
        network_priority_fee_atomic=0,
    )
    return replace(
        base,
        execution_mode=ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT,
        sell=sell,
        sell_reference_liquidity=evidence,
        sell_landing_liquidity=evidence,
        settled_venue_funded_atomic=venue_funded,
        settled_synthetic_funded_atomic=synthetic_funded,
    )


def _ledger(record: RoundTripRecord, *, cashflow: int) -> LedgerTransaction:
    # Execute the ledger workflow in explicit, reviewable steps.
    venue = LedgerAccount(AccountId(f"venue:{record.venue_id.value}"), AccountKind.VENUE)
    venue_funded = record.settled_venue_funded_atomic
    postings = [
        Posting(
            LedgerAccount(AccountId("portfolio:available:SOL"), AccountKind.PORTFOLIO_AVAILABLE),
            SOL,
            cashflow,
        ),
        # Separate the buy-side credit from the exact sell-side venue debit.
        Posting(venue, SOL, -cashflow + venue_funded),
    ]
    if venue_funded:
        postings.append(Posting(venue, SOL, -venue_funded))
    return LedgerTransaction(
        transaction_id=_digest("ledger", int(record.target_position.block_ordinal)),
        correlation_kind=LedgerCorrelationKind.ROUNDTRIP,
        correlation_id=record.roundtrip_id,
        boundary_ordinal=record.target_position.boundary_ordinal + 1,
        # Freeze the test postings after both modeled sides have been assembled.
        postings=tuple(postings),
        reason="TEST_SETTLEMENT",
        # Complete LedgerTransaction only after its ledger and portfolio:available:sol inputs
        # are visible in ledger.
    )


def _virtual_sell_ledger(
    record: RoundTripRecord,
    *,
    venue_funded: int,
    synthetic_funded: int,
    venue_account: AccountId | None = None,
    synthetic_account: AccountId | None = None,
) -> LedgerTransaction:
    """Build a conserved successful-sell ledger with an explicit synthetic source."""

    resolved_venue = venue_account or AccountId(f"venue:{record.venue_id.value}")
    resolved_synthetic = synthetic_account or synthetic_liquidity_account_id(
        protocol_namespace="pumpfun",
        network_id=record.network_id,
        venue_id=record.venue_id,
    )
    return LedgerTransaction(
        transaction_id=_digest("virtual-ledger", int(record.target_position.block_ordinal)),
        correlation_kind=LedgerCorrelationKind.ROUNDTRIP,
        correlation_id=record.roundtrip_id,
        boundary_ordinal=record.target_position.boundary_ordinal + 1,
        postings=(
            Posting(
                LedgerAccount(
                    AccountId("portfolio:available:SOL"), AccountKind.PORTFOLIO_AVAILABLE
                ),
                SOL,
                venue_funded + synthetic_funded,
            ),
            Posting(
                LedgerAccount(resolved_venue, AccountKind.VENUE),
                SOL,
                -venue_funded,
            ),
            Posting(
                LedgerAccount(resolved_synthetic, AccountKind.EXTERNAL),
                SOL,
                -synthetic_funded,
            ),
        ),
        reason="SNIPING_SELL_FILLED_ACCOUNT_CLOSED",
    )


def _summary(
    *,
    target_count: int,
    closed_count: int = 0,
    # Keep the open count input explicit in the summary contract.
    open_count: int = 0,
    realized: int = 0,
    valued_economic: int = 0,
    execution_mode: ExecutionMode = ExecutionMode.EXOGENOUS_REPLAY,
    venue_funded: int = 0,
    synthetic_funded: int = 0,
) -> PumpfunSnipingSummaryMetadata:
    # Execute the summary workflow in explicit, reviewable steps.
    if closed_count and venue_funded == 0 and synthetic_funded == 0:
        venue_funded = closed_count
    comparison = RunComparisonProjection(
        canonical_result_hash=_digest("result", 1),
        audit_hash=_digest("audit", 1),
        ledger_hash=_digest("ledger-stream", 1),
        fill_hash=_digest("fills", 1),
        # Pass historical group count explicitly so RunComparisonProjection receives a
        # reviewable result and audit input in summary.
        historical_group_count=0,
        historical_event_count=0,
        delivered_event_count=0,
        accepted_order_count=0,
        rejected_order_count=0,
        # Pass filled order count explicitly so RunComparisonProjection receives a
        # reviewable result and audit input in summary.
        filled_order_count=0,
        failed_order_count=0,
        ledger_transaction_count=0,
        fill_count=0,
        final_balances_count=0,
        # Keep the balances _digest step visible while building comparison.
        final_balances_digest=_digest("balances", 1),
    )
    return PumpfunSnipingSummaryMetadata(
        dataset_logical_content_hash=_digest("dataset", 1),
        replay_semantics_id=_digest("replay", 1),
        # Include engine bundle id in the completed summary result.
        engine_bundle_id=BundleId(_digest("engine", 1).hex),
        strategy_bundle_id=BundleId(_digest("strategy", 1).hex),
        protocol_bundle_id=BundleId(_digest("protocol", 1).hex),
        network_cost_bundle_id=BundleId(_digest("network", 1).hex),
        comparison=comparison,
        # Pass target count explicitly so PumpfunSnipingSummaryMetadata receives a
        # reviewable dataset and replay input in summary.
        target_count=target_count,
        cooldown_skipped_count=0,
        accepted_buy_count=target_count,
        closed_roundtrip_count=closed_count,
        open_position_count=open_count,
        # Pass failed buy count explicitly so PumpfunSnipingSummaryMetadata receives a
        # reviewable dataset and replay input in summary.
        failed_buy_count=0,
        failed_sell_count=0,
        roundtrip_count=target_count,
        roundtrip_digest=_digest("roundtrips", 1),
        realized_cash_pnl_atomic=realized,
        # Pass valuation status explicitly so PumpfunSnipingSummaryMetadata receives a
        # reviewable dataset and replay input in summary.
        valuation_status=SnipingValuationStatus.COMPLETE,
        unvalued_open_position_count=0,
        valued_economic_pnl_subtotal_atomic=valued_economic,
        economic_pnl_atomic=valued_economic,
        cashback_receivable_atomic=0,
        # Pass protocol fee paid atomic explicitly so PumpfunSnipingSummaryMetadata
        # receives a reviewable dataset and replay input in summary.
        protocol_fee_paid_atomic=0,
        creator_fee_paid_atomic=0,
        network_base_fee_paid_atomic=0,
        network_priority_fee_paid_atomic=0,
        account_deposit_paid_atomic=0,
        # Pass account deposit refunded atomic explicitly so PumpfunSnipingSummaryMetadata
        # receives a reviewable dataset and replay input in summary.
        account_deposit_refunded_atomic=0,
        account_deposit_locked_atomic=0,
        favorable_slippage_count=0,
        adverse_slippage_count=0,
        buy_slippage_failure_count=0,
        execution_mode=execution_mode,
        settlement_policy_id=(
            "virtual-reserve-output-with-explicit-synthetic-shortfall-v1"
            if execution_mode is ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT
            else "real-reserve-capped-v1"
        ),
        filled_sell_count=closed_count,
        real_liquidity_sufficient_filled_sell_count=(closed_count if synthetic_funded == 0 else 0),
        synthetic_liquidity_used_sell_count=(closed_count if synthetic_funded else 0),
        # Aggregate gross funding remains separate from the net portfolio cashflow.
        gross_sell_settlement_atomic=venue_funded + synthetic_funded,
        venue_funded_sell_atomic=venue_funded,
        synthetic_funded_sell_atomic=synthetic_funded,
        # Pass sell slippage failure count explicitly so PumpfunSnipingSummaryMetadata
        # receives a reviewable dataset and replay input in summary.
        sell_slippage_failure_count=0,
    )


def _digest(label: str, ordinal: int) -> ContentDigest:
    return domain_digest("test.sniping-ledger-reconciliation", {"label": label, "n": ordinal})
