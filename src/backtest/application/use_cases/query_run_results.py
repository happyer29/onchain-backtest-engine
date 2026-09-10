"""Exact bounded projections over verified external Run result tables."""

from __future__ import annotations

from dataclasses import dataclass

from backtest.application.errors import ReprepareRequiredError
from backtest.application.ports.run_results import (
    MAX_ROUNDTRIP_PAGE_SIZE,
    # Include round trip cursor so the run results dependency remains explicit.
    RoundTripCursor,
    RoundTripPage,
    RunResultReaderFactory,
)
from backtest.application.run_results import (
    # Result dispatch recognizes separate copy metadata without reinterpreting Sniping rows.
    LEGACY_PUMPFUN_SNIPING_SUMMARY_SCHEMA,
    PUMPFUN_SNIPING_SUMMARY_SCHEMA,
    CopySummaryMetadata,
    PumpfunSnipingSummaryMetadata,
    SuccessfulRunManifest,
    # Execution mode and immutable manifest remain the authority for displayed results.
)
from backtest.domain.execution import ExecutionMode

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import (
    ArtifactId,
    ContentDigest,
    ExecutionAttemptId,
    LogicalRunId,
    # Include network id so the identifiers dependency remains explicit.
    NetworkId,
    PositionSchemaId,
)
from backtest.engine.sniping import SnipingValuationStatus


class RunResultQueryError(RuntimeError):
    """Stable fail-closed result-query code safe for CLI/API projection."""

    code: str

    def __init__(self, code: str) -> None:
        # Execute the run result query error init workflow in explicit, reviewable steps.
        if code not in {
            "RUN_HAS_NO_PUMPFUN_SNIPING_RESULTS",
            "RUN_RESULT_UNAVAILABLE",
        }:
            raise ValueError("unsupported run result query error code")
        # Assemble self code once so the run result query error init workflow shares one
        # value.
        self.code = code
        super().__init__(code)


# Keep the pumpfun sniping run summary view contract and validation rules together.
@dataclass(frozen=True, slots=True)
class PumpfunSnipingRunSummaryView:
    run_artifact_id: ArtifactId
    logical_run_id: LogicalRunId
    execution_attempt_id: ExecutionAttemptId
    # Declare network id explicitly in the pumpfun sniping run summary view contract.
    network_id: NetworkId
    position_schema_id: PositionSchemaId
    canonical_result_hash: ContentDigest
    audit_hash: ContentDigest
    ledger_hash: ContentDigest
    # Declare fill hash explicitly in the pumpfun sniping run summary view contract.
    fill_hash: ContentDigest
    roundtrip_digest: ContentDigest
    final_balances_digest: ContentDigest
    historical_group_count: int
    historical_event_count: int
    # Declare delivered event count explicitly in the pumpfun sniping run summary view
    # contract.
    delivered_event_count: int
    target_count: int
    cooldown_skipped_count: int
    accepted_buy_count: int
    accepted_order_count: int
    # Declare rejected order count explicitly in the pumpfun sniping run summary view
    # contract.
    rejected_order_count: int
    filled_order_count: int
    failed_order_count: int
    failed_buy_count: int
    failed_sell_count: int
    # Declare closed position count explicitly in the pumpfun sniping run summary view
    # contract.
    closed_position_count: int
    open_position_count: int
    ledger_transaction_count: int
    fill_count: int
    roundtrip_count: int
    # Declare final balances count explicitly in the pumpfun sniping run summary view
    # contract.
    final_balances_count: int
    realized_cash_pnl_atomic: int
    valuation_status: SnipingValuationStatus
    unvalued_open_position_count: int
    valued_economic_pnl_subtotal_atomic: int
    # Declare economic pnl atomic explicitly in the pumpfun sniping run summary view
    # contract.
    economic_pnl_atomic: int | None
    cashback_receivable_atomic: int
    protocol_fee_paid_atomic: int
    creator_fee_paid_atomic: int
    network_base_fee_paid_atomic: int
    # Declare network priority fee paid atomic explicitly in the pumpfun sniping run
    # summary view contract.
    network_priority_fee_paid_atomic: int
    account_deposit_paid_atomic: int
    account_deposit_refunded_atomic: int
    account_deposit_locked_atomic: int
    favorable_slippage_count: int
    # Declare adverse slippage count explicitly in the pumpfun sniping run summary view
    # contract.
    adverse_slippage_count: int
    buy_slippage_failure_count: int
    sell_slippage_failure_count: int
    summary_schema_id: str
    execution_mode: ExecutionMode
    settlement_policy_id: str
    # Legacy summary/v2 did not contain funding-classification evidence.
    filled_sell_count: int | None
    real_liquidity_sufficient_filled_sell_count: int | None
    synthetic_liquidity_used_sell_count: int | None
    gross_sell_settlement_atomic: int | None
    venue_funded_sell_atomic: int | None
    synthetic_funded_sell_atomic: int | None

    def __post_init__(self) -> None:
        """Reject semantically impossible summary projections at every interface."""

        if not isinstance(self.execution_mode, ExecutionMode):
            raise TypeError("execution_mode must be an ExecutionMode")
        expected_policy = {
            ExecutionMode.EXOGENOUS_REPLAY: "real-reserve-capped-v1",
            ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT: (
                "virtual-reserve-output-with-explicit-synthetic-shortfall-v1"
            ),
        }.get(self.execution_mode)
        if expected_policy is None or self.settlement_policy_id != expected_policy:
            raise ValueError("summary execution mode and settlement policy differ")

        settlement_values = (
            self.filled_sell_count,
            self.real_liquidity_sufficient_filled_sell_count,
            self.synthetic_liquidity_used_sell_count,
            self.gross_sell_settlement_atomic,
            self.venue_funded_sell_atomic,
            self.synthetic_funded_sell_atomic,
        )
        if self.summary_schema_id == LEGACY_PUMPFUN_SNIPING_SUMMARY_SCHEMA:
            if self.execution_mode is not ExecutionMode.EXOGENOUS_REPLAY or any(
                value is not None for value in settlement_values
            ):
                raise ValueError("legacy summary cannot invent settlement evidence")
            return
        if self.summary_schema_id != PUMPFUN_SNIPING_SUMMARY_SCHEMA:
            raise ValueError("unsupported Pump.fun Sniping summary schema")
        if any(value is None for value in settlement_values):
            raise ValueError("summary v3 requires complete settlement evidence")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in settlement_values
        ):
            raise ValueError("summary settlement evidence must be non-negative integers")

        filled = self.filled_sell_count
        real = self.real_liquidity_sufficient_filled_sell_count
        synthetic = self.synthetic_liquidity_used_sell_count
        gross = self.gross_sell_settlement_atomic
        venue_funded = self.venue_funded_sell_atomic
        synthetic_funded = self.synthetic_funded_sell_atomic
        assert filled is not None
        assert real is not None
        assert synthetic is not None
        assert gross is not None
        assert venue_funded is not None
        assert synthetic_funded is not None
        if filled != self.closed_position_count or filled != real + synthetic:
            raise ValueError("summary sell classification does not reconcile")
        if gross != venue_funded + synthetic_funded:
            raise ValueError("summary sell funding does not reconcile")
        if self.execution_mode is ExecutionMode.EXOGENOUS_REPLAY and (
            synthetic != 0 or synthetic_funded != 0
        ):
            raise ValueError("strict replay cannot use synthetic liquidity")


@dataclass(frozen=True, slots=True)
class PumpfunSnipingDashboardView:
    """One verified summary plus exactly one bounded round-trip page."""

    summary: PumpfunSnipingRunSummaryView
    roundtrips: RoundTripPage


@dataclass(frozen=True, slots=True)
class CopyRunSummaryView:
    """Bounded verified copy metadata, without fabricated launch/cooldown fields."""

    run_artifact_id: ArtifactId
    logical_run_id: LogicalRunId
    execution_attempt_id: ExecutionAttemptId
    network_id: NetworkId
    position_schema_id: PositionSchemaId
    # Copy metadata carries its own bounded count and valuation contract.
    metadata: CopySummaryMetadata


@dataclass(frozen=True, slots=True)
class CopyDashboardView:
    """A copy dashboard combines its own summary with one bounded position page."""

    summary: CopyRunSummaryView
    roundtrips: RoundTripPage


RunResultSummaryView = PumpfunSnipingRunSummaryView | CopyRunSummaryView
RunResultDashboardView = PumpfunSnipingDashboardView | CopyDashboardView


def _project_run_summary(
    artifact_id: ArtifactId, manifest: SuccessfulRunManifest
) -> RunResultSummaryView:
    """Select the declared result family from verified metadata, not a user-facing title."""
    if isinstance(manifest.bounded_summary, CopySummaryMetadata):
        return CopyRunSummaryView(
            artifact_id,
            manifest.logical_run_id,
            manifest.execution_attempt_id,
            # The result view exposes the same immutable chain identity as its resolved run.
            manifest.resolved_spec.network_id,
            manifest.resolved_spec.position_schema_id,
            manifest.bounded_summary,
        )
    # All previously supported result families retain their original projection path.
    return _project_sniping_summary(artifact_id, manifest)


def _require_roundtrip_page_limit(limit: int) -> None:
    """Reject lossy or unbounded result-page requests before opening artifacts."""

    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("round-trip page limit must be between 1 and 200")
    # Keep the transport-independent hard bound at the application boundary.
    if not 1 <= limit <= MAX_ROUNDTRIP_PAGE_SIZE:
        raise ValueError("round-trip page limit must be between 1 and 200")


def _project_sniping_summary(
    artifact_id: ArtifactId,
    manifest: SuccessfulRunManifest,
) -> PumpfunSnipingRunSummaryView:
    """Project already-parsed bounded metadata without opening another reader."""

    summary = manifest.bounded_summary
    if not isinstance(summary, PumpfunSnipingSummaryMetadata):
        raise RunResultQueryError("RUN_HAS_NO_PUMPFUN_SNIPING_RESULTS")
    # Settlement fields exist only in the current summary generation.
    comparison = summary.comparison
    has_settlement_evidence = summary.source_schema_id == PUMPFUN_SNIPING_SUMMARY_SCHEMA
    return PumpfunSnipingRunSummaryView(
        run_artifact_id=artifact_id,
        logical_run_id=manifest.logical_run_id,
        execution_attempt_id=manifest.execution_attempt_id,
        # Chain identity is copied from the exact resolved Run manifest.
        network_id=manifest.resolved_spec.network_id,
        position_schema_id=manifest.resolved_spec.position_schema_id,
        canonical_result_hash=comparison.canonical_result_hash,
        audit_hash=comparison.audit_hash,
        ledger_hash=comparison.ledger_hash,
        # Table digests remain bounded metadata rather than browser-visible rows.
        fill_hash=comparison.fill_hash,
        roundtrip_digest=summary.roundtrip_digest,
        final_balances_digest=comparison.final_balances_digest,
        historical_group_count=comparison.historical_group_count,
        historical_event_count=comparison.historical_event_count,
        # Replay counters preserve the existing exact summary projection.
        delivered_event_count=comparison.delivered_event_count,
        target_count=summary.target_count,
        cooldown_skipped_count=summary.cooldown_skipped_count,
        accepted_buy_count=summary.accepted_buy_count,
        accepted_order_count=comparison.accepted_order_count,
        # Order outcomes come from the manifest's comparison projection.
        rejected_order_count=comparison.rejected_order_count,
        filled_order_count=comparison.filled_order_count,
        failed_order_count=comparison.failed_order_count,
        failed_buy_count=summary.failed_buy_count,
        failed_sell_count=summary.failed_sell_count,
        # Position and ledger counts stay aligned with the published summary.
        closed_position_count=summary.closed_roundtrip_count,
        open_position_count=summary.open_position_count,
        ledger_transaction_count=comparison.ledger_transaction_count,
        fill_count=comparison.fill_count,
        roundtrip_count=summary.roundtrip_count,
        # Balance evidence is exposed only as its bounded count and digest.
        final_balances_count=comparison.final_balances_count,
        realized_cash_pnl_atomic=summary.realized_cash_pnl_atomic,
        valuation_status=summary.valuation_status,
        unvalued_open_position_count=summary.unvalued_open_position_count,
        valued_economic_pnl_subtotal_atomic=(summary.valued_economic_pnl_subtotal_atomic),
        # Monetary fields remain exact integers through the application projection.
        economic_pnl_atomic=summary.economic_pnl_atomic,
        cashback_receivable_atomic=summary.cashback_receivable_atomic,
        protocol_fee_paid_atomic=summary.protocol_fee_paid_atomic,
        creator_fee_paid_atomic=summary.creator_fee_paid_atomic,
        network_base_fee_paid_atomic=summary.network_base_fee_paid_atomic,
        # Account and slippage aggregates retain their existing manifest meaning.
        network_priority_fee_paid_atomic=summary.network_priority_fee_paid_atomic,
        account_deposit_paid_atomic=summary.account_deposit_paid_atomic,
        account_deposit_refunded_atomic=summary.account_deposit_refunded_atomic,
        account_deposit_locked_atomic=summary.account_deposit_locked_atomic,
        favorable_slippage_count=summary.favorable_slippage_count,
        # Schema and mode decide whether settlement evidence may be projected.
        adverse_slippage_count=summary.adverse_slippage_count,
        buy_slippage_failure_count=summary.buy_slippage_failure_count,
        sell_slippage_failure_count=summary.sell_slippage_failure_count,
        summary_schema_id=summary.source_schema_id,
        execution_mode=summary.execution_mode,
        # Legacy summary v2 must not acquire synthetic-liquidity fields.
        settlement_policy_id=summary.settlement_policy_id,
        filled_sell_count=summary.filled_sell_count if has_settlement_evidence else None,
        real_liquidity_sufficient_filled_sell_count=(
            summary.real_liquidity_sufficient_filled_sell_count if has_settlement_evidence else None
        ),
        synthetic_liquidity_used_sell_count=(
            summary.synthetic_liquidity_used_sell_count if has_settlement_evidence else None
        ),
        # Funding totals remain nullable only for immutable legacy summaries.
        gross_sell_settlement_atomic=(
            summary.gross_sell_settlement_atomic if has_settlement_evidence else None
        ),
        venue_funded_sell_atomic=(
            summary.venue_funded_sell_atomic if has_settlement_evidence else None
        ),
        synthetic_funded_sell_atomic=(
            summary.synthetic_funded_sell_atomic if has_settlement_evidence else None
        ),
    )


# Keep the query run results contract and validation rules together.
class QueryRunResults:
    def __init__(self, readers: RunResultReaderFactory) -> None:
        self._readers = readers

    def summary(self, artifact_id: ArtifactId) -> RunResultSummaryView:
        """Return a verified bounded summary for one exact Run artifact."""

        try:
            with self._readers.open_exact(artifact_id) as reader:
                # Summary-only queries authenticate and validate both result tables.
                reader.verify()
                return _project_run_summary(artifact_id, reader.manifest)
        except (ReprepareRequiredError, RunResultQueryError):
            raise
        # Infrastructure or malformed-result failures collapse to one safe query code.
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            raise RunResultQueryError("RUN_RESULT_UNAVAILABLE") from error

    # Define query run results roundtrips as one focused operation with an explicit
    # boundary.
    def roundtrips(
        self,
        artifact_id: ArtifactId,
        *,
        after: RoundTripCursor | None = None,
        # Keep the limit input explicit in the roundtrips contract.
        limit: int = MAX_ROUNDTRIP_PAGE_SIZE,
    ) -> RoundTripPage:
        """Return one bounded keyset page for an exact Run artifact."""

        _require_roundtrip_page_limit(limit)
        try:
            with self._readers.open_exact(artifact_id) as reader:
                # Reject a non-sniping manifest with the stable application error code.
                if not isinstance(
                    reader.manifest.bounded_summary,
                    (PumpfunSnipingSummaryMetadata, CopySummaryMetadata),
                ):
                    raise RunResultQueryError("RUN_HAS_NO_PUMPFUN_SNIPING_RESULTS")
                # Paging is permitted only after verifying the supported financial result family.
                return reader.roundtrips(after=after, limit=limit)
        except (ReprepareRequiredError, RunResultQueryError):
            raise
        # Infrastructure or malformed-result failures collapse to one safe query code.
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            raise RunResultQueryError("RUN_RESULT_UNAVAILABLE") from error

    def dashboard(
        self,
        artifact_id: ArtifactId,
        *,
        limit: int = MAX_ROUNDTRIP_PAGE_SIZE,
        # Dashboard queries retain the same bounded page cap as direct row queries.
    ) -> RunResultDashboardView:
        """Return one summary and the first page from one authenticated reader."""

        _require_roundtrip_page_limit(limit)
        try:
            with self._readers.open_exact(artifact_id) as reader:
                # Projection checks the typed result kind before any table read.
                summary = _project_run_summary(artifact_id, reader.manifest)
                page = reader.roundtrips(after=None, limit=limit)
                # A compliant reader makes this a no-op after the cold page scan.
                reader.verify()
                if isinstance(summary, CopyRunSummaryView):
                    return CopyDashboardView(summary=summary, roundtrips=page)
                return PumpfunSnipingDashboardView(summary=summary, roundtrips=page)
        # Typed preparation and query failures remain visible instead of becoming empty dashboards.
        except (ReprepareRequiredError, RunResultQueryError):
            raise
        # Preserve the same safe failure surface as standalone result queries.
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            raise RunResultQueryError("RUN_RESULT_UNAVAILABLE") from error


__all__ = [
    "PumpfunSnipingDashboardView",
    "PumpfunSnipingRunSummaryView",
    "QueryRunResults",
    # Keep the run result query error component named inside the all contract.
    "RunResultQueryError",
]
