"""Pure projections preserve each stored strategy family's existing semantics."""

from __future__ import annotations

from typing import Literal

# Stored family summaries are the sole source of scalar economic facts.
from backtest.application.run_results import (
    CopySummaryMetadata,
    FirstSwapSummaryMetadata,
    SuccessfulRunManifest,
)

# Common presentation types do not replace the underlying family result contracts.
from backtest.application.strategy_results import (
    EntryAttempt,
    ResultMetric,
    StrategyEntry,
    # Family labels select vocabulary, not alternative execution/accounting behavior.
    StrategyFamily,
    StrategySummary,
)

# Projection consumes existing typed identities and records without storage access.
from backtest.domain.identifiers import ArtifactId
from backtest.domain.roundtrips import RoundTripRecord
from backtest.engine.copytrading_results import CopyPositionRecord


def exact(value: object) -> str | None:
    """Only scalar historical facts may become exact display strings."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("invalid result scalar")
    # Decimal text preserves the complete original scalar across JavaScript transport.
    return str(value)


def project_summary(artifact_id: ArtifactId, manifest: SuccessfulRunManifest) -> StrategySummary:
    """Expose only manifest-defined scalar counts, money, and valuation state."""
    summary = manifest.bounded_summary
    family: StrategyFamily = "PUMPFUN_SNIPING"
    values = summary.document()
    if isinstance(summary, CopySummaryMetadata):
        # Copy totals use their own reducer and remain distinct from launch cooldowns.
        family = "PUMPFUN_COPY_BUY"
        values = summary.totals.document()
        values["entry_count"] = summary.totals.position_count
        values["open_position_count"] = summary.totals.exhausted_position_count
    # FirstSwap exposes order lifecycle but has no Pump position-accounting policy.
    elif isinstance(summary, FirstSwapSummaryMetadata):
        family = "FIRST_SWAP"
        # A FirstSwap has order outcomes but no defined round-trip valuation policy.
        values = {}
        values["entry_count"] = (
            summary.comparison.accepted_order_count + summary.comparison.rejected_order_count
        )
    # A Sniping creation target is an entry even when cooldown suppresses its order.
    else:
        values["entry_count"] = summary.target_count
        values["closed_position_count"] = summary.closed_roundtrip_count
    # Comparison counters are authoritative and common to every implemented result family.
    values.update(summary.comparison.document())
    metrics = []
    for key, value in sorted(values.items()):
        if key.endswith("_count") or key.endswith("_atomic") or key == "valuation_status":
            # Suffix conventions belong to the existing closed summary documents.
            unit: Literal["count", "atomic", "text"] = (
                "atomic" if key.endswith("_atomic") else "count"
            )
            if key == "valuation_status":
                unit = "text"
            # Nullable PnL is unavailable, including partial open-position valuation.
            metrics.append(
                ResultMetric(
                    key, exact(value), unit, "UNAVAILABLE" if value is None else "AVAILABLE"
                )
            )
    # Explicit nonapplicability distinguishes absent strategy semantics from missing evidence.
    existing = {item.key for item in metrics}
    for key in ("realized_cash_pnl_atomic", "economic_pnl_atomic", "closed_position_count"):
        if key not in existing:
            unit = "atomic" if key.endswith("_atomic") else "count"
            metrics.append(ResultMetric(key, None, unit, "NOT_APPLICABLE"))
    # Immutable IDs remain visible without leaking the executable resolved specification.
    return StrategySummary(
        artifact_id.hex,
        manifest.logical_run_id.hex,
        family,
        manifest.resolved_spec.network_id.value,
        # Network coordinates and original hashes retain the immutable execution provenance.
        manifest.resolved_spec.position_schema_id.value,
        manifest.resolved_spec.execution_mode().value,
        summary.result_hash.hex,
        summary.audit_hash.hex,
        # Only bounded scalar metadata is copied; external tables remain on the host.
        tuple(metrics),
    )


def project_entry(record: RoundTripRecord | CopyPositionRecord) -> StrategyEntry:
    """Normalize layout only; the unmodified stored detail remains inspectable."""
    document = record.document()
    copy = isinstance(record, CopyPositionRecord)
    # Each family already records its own attempt lifecycle and causal coordinates.
    attempts = (
        _copy_attempts(record)
        if isinstance(record, CopyPositionRecord)
        else _sniping_attempts(record)
    )
    exit_reason = _exit_reason(record)
    # Actor roles preserve the distinction between creation ownership and copy signal signer.
    return StrategyEntry(
        record.roundtrip_id.hex,
        str(record.target_position.boundary_ordinal),
        exact(document["signal_event_id" if copy else "target_event_id"]),
        exact(document["asset_id"]),
        # The quote asset is distinct from the actor that caused the entry signal.
        exact(document["quote_asset_id"]),
        "signing_wallet" if copy else "creator",
        exact(document["signing_wallet" if copy else "developer_id"]),
        str(document["status"]),
        # The original accounting result is never inferred from historical chart ordinates.
        exit_reason,
        exact(document["realized_cash_pnl_atomic"]),
        exact(document["economic_pnl_atomic"]),
        str(document["mtm_status"]),
        attempts,
        # Availability permits a bounded historical query; it does not promise that quotas fit.
        "AVAILABLE",
        document,
    )


def _sniping_attempts(record: RoundTripRecord) -> tuple[EntryAttempt, ...]:
    """Preserve typed coordinates instead of reimplementing chain encoding."""
    result = []
    for number, leg in enumerate((record.buy, record.sell)):
        if leg is None:
            continue
        # Failure stage follows actual landing evidence, never an expected coordinate.
        landed = (
            None if leg.landing_position is None else str(leg.landing_position.boundary_ordinal)
        )
        state = "FILLED" if leg.failure_code is None else "FAILED" if landed else "REJECTED"
        # Attempt numbering is retained so individual retries remain traceable in the UI.
        result.append(
            EntryAttempt(
                leg.side.value,
                number,
                state,
                # A causal decision remains separate from actual landing or rejected submission.
                str(leg.decision_position.boundary_ordinal),
                landed,
                # The signed quote delta remains separate from actual settled proceeds.
                exact(leg.reference_out_atomic),
                exact(leg.landing_out_atomic),
                exact(leg.minimum_out_atomic),
                leg.failure_code,
            )
        )
    # Final immutable ordering follows the stored buy/sell or retry sequence.
    return tuple(result)


def _copy_attempts(record: CopyPositionRecord) -> tuple[EntryAttempt, ...]:
    """Every recorded retry remains visible, including pre-submit rejections."""
    result = []
    for attempt in record.attempts:
        landed = None if attempt.landed_at is None else str(attempt.landed_at.boundary_ordinal)
        reference = attempt.reference
        landing = attempt.landing_quote
        # Coordinates and outcomes come from the immutable typed result, not display arithmetic.
        # Attempt numbering is retained so individual retries remain traceable in the UI.
        result.append(
            EntryAttempt(
                "BUY" if attempt.number == 0 else "SELL",
                attempt.number,
                attempt.status.value,
                # Record-provided coordinates avoid a second chain encoding implementation.
                str(attempt.decision.boundary_ordinal),
                landed,
                # Quotes expose exact outputs; absence is preserved without a zero fallback.
                None if reference is None else str(reference.amount_out_atomic),
                None if landing is None else str(landing.amount_out_atomic),
                str(attempt.minimum_out_atomic),
                attempt.failure_code,
            )
        )
    # Final immutable ordering follows the stored buy/sell or retry sequence.
    return tuple(result)


def _exit_reason(record: RoundTripRecord | CopyPositionRecord) -> str | None:
    """Label an actual sell decision with its established family policy."""
    if isinstance(record, CopyPositionRecord):
        return None if record.exit_reason is None else record.exit_reason.value
    # Sniping has one fixed hold policy; absent sell decisions stay absent.
    return "FIXED_HOLD_2_SECONDS" if record.sell is not None else None
