"""Common read-only presentation of stored strategy results; never execution input."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from backtest.application.ports.run_results import RoundTripCursor
from backtest.domain.identifiers import ArtifactId

# The query version does not participate in any canonical Run identity.
STRATEGY_RESULTS_SCHEMA = "strategy-results/v1"
MAX_ANALYTICS_ROWS = 100_000
MAX_ANALYTICS_BYTES = 64 * 1024 * 1024
ANALYTICS_DEADLINE_SECONDS = 5.0

# A missing historical fact and an inapplicable strategy concept have distinct meanings.
Availability = Literal["AVAILABLE", "UNAVAILABLE", "NOT_APPLICABLE"]
StrategyFamily = Literal["PUMPFUN_SNIPING", "PUMPFUN_COPY_BUY", "FIRST_SWAP"]


class StrategyResultsError(RuntimeError):
    """A safe, closed failure surface for optional result analytics."""

    def __init__(self, code: str) -> None:
        allowed = {
            "RESULT_ANALYTICS_LIMIT_EXCEEDED",
            "RESULT_ANALYTICS_BUSY",
            "STRATEGY_RESULT_UNAVAILABLE",
            "STRATEGY_ENTRY_NOT_FOUND",
        }
        # Invalid failures cannot introduce raw infrastructure text into the transport.
        if code not in allowed:
            raise ValueError("unsupported strategy result error")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ResultMetric:
    """Exact scalar with explicit units and availability, including genuine zero."""

    key: str
    value: str | None
    unit: Literal["count", "atomic", "text"]
    availability: Availability = "AVAILABLE"


@dataclass(frozen=True, slots=True)
class StrategySummary:
    """A common bounded header backed exclusively by verified manifest metadata."""

    run_artifact_id: str
    logical_run_id: str
    family: StrategyFamily
    network_id: str
    # Provenance remains inspectable without transporting executable specifications.
    position_schema_id: str
    execution_mode: str
    canonical_result_hash: str
    audit_hash: str
    metrics: tuple[ResultMetric, ...]


@dataclass(frozen=True, slots=True)
class EntryAttempt:
    """Actual decision and landing evidence; a rejection has no fabricated landing."""

    side: str
    number: int
    status: str
    decision_boundary: str
    landing_boundary: str | None
    # Amounts retain their native asset atomic unit without float conversion.
    reference_out_atomic: str | None
    landing_out_atomic: str | None
    minimum_out_atomic: str | None
    failure_code: str | None


@dataclass(frozen=True, slots=True)
class StrategyEntry:
    """The same table/detail shape for a stored position or a generic order."""

    entry_id: str
    boundary_ordinal: str
    signal_event_id: str | None
    asset_id: str | None
    quote_asset_id: str | None
    # Creator and signing wallet remain distinct actor roles.
    actor_role: str | None
    actor_id: str | None
    status: str
    exit_reason: str | None
    realized_cash_pnl_atomic: str | None
    # Full economic PnL is never replaced by a valued subtotal.
    economic_pnl_atomic: str | None
    valuation_status: str
    attempts: tuple[EntryAttempt, ...]
    chart_availability: Availability
    details: dict[str, object]


@dataclass(frozen=True, slots=True)
class StrategyEntryPage:
    """Only one keyset page crosses the query boundary."""

    items: tuple[StrategyEntry, ...]
    next_cursor: RoundTripCursor | None


@dataclass(frozen=True, slots=True)
class StrategyDashboard:
    """Initial summary and bounded entries share the exact authenticated artifact."""

    summary: StrategySummary
    entries: StrategyEntryPage


@dataclass(frozen=True, slots=True)
class ResultDistribution:
    """A whole-run count distribution with an explicit population denominator."""

    key: str
    population: str
    total: int
    items: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class StrategyAnalytics:
    """Completed bounded reduction, never a sample or partially scanned history."""

    run_artifact_id: ArtifactId
    entry_count: int
    distributions: tuple[ResultDistribution, ...]
