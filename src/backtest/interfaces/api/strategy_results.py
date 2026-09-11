"""Typed precision-safe HTTP DTOs for the common strategy-results presentation."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Literal, Self

from pydantic import Field

# Transport only maps application-owned views and reuses the existing lossless nested codec.
from backtest.application.copy_result_codec import copy_decimal_document
from backtest.application.strategy_results import (
    StrategyAnalytics,
    StrategyDashboard,
    StrategyEntry,
    # Page and summary remain separate responses after the initial combined dashboard request.
    StrategyEntryPage,
    StrategySummary,
)

# Reuse established strict transport and composite cursor validation.
from backtest.interfaces.api.schemas import ApiModel, RoundTripCursorResponse

Decimal = Annotated[str, Field(pattern=r"^-?(?:0|[1-9][0-9]*)$", max_length=40)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Availability = Literal["AVAILABLE", "UNAVAILABLE", "NOT_APPLICABLE"]


class ResultMetricResponse(ApiModel):
    """No float conversion occurs between immutable metadata and the browser."""

    key: str = Field(max_length=96, pattern=r"^[a-z][a-z0-9_]*$")
    value: str | None = Field(max_length=128)
    unit: Literal["count", "atomic", "text"]
    availability: Availability


class StrategySummaryResponse(ApiModel):
    """One stable header for all result families, independent of row pagination."""

    run_artifact_id: Digest
    logical_run_id: Digest
    family: Literal["PUMPFUN_SNIPING", "PUMPFUN_COPY_BUY", "FIRST_SWAP"]
    network_id: str = Field(max_length=256)
    # Chain and execution identity remain explicit in every result view.
    position_schema_id: str = Field(max_length=128)
    execution_mode: str = Field(max_length=128)
    canonical_result_hash: Digest
    audit_hash: Digest
    metrics: tuple[ResultMetricResponse, ...] = Field(max_length=128)

    @classmethod
    def from_view(cls, value: StrategySummary) -> Self:
        """Only application-owned verified views reach this output contract."""
        return cls.model_validate(asdict(value))


class EntryAttemptResponse(ApiModel):
    """Actual decision/landing and outcome semantics fit every stored strategy."""

    side: Literal["BUY", "SELL", "ENTRY"]
    number: int = Field(ge=0, le=4)
    status: Literal["FILLED", "FAILED", "REJECTED"]
    decision_boundary: Decimal
    landing_boundary: Decimal | None
    # Reference/landing quotes remain distinct from executed amounts.
    reference_out_atomic: Decimal | None
    landing_out_atomic: Decimal | None
    minimum_out_atomic: Decimal | None
    failure_code: str | None = Field(max_length=256)


class StrategyEntryResponse(ApiModel):
    """Common table/detail shape with a bounded immutable family detail record."""

    entry_id: Digest
    boundary_ordinal: Decimal
    signal_event_id: Digest | None
    asset_id: str | None = Field(max_length=256)
    quote_asset_id: str | None = Field(max_length=256)
    # Identity roles must not conflate signer, developer and payer.
    actor_role: Literal["creator", "signing_wallet"] | None
    actor_id: str | None = Field(max_length=256)
    status: str = Field(max_length=128)
    exit_reason: str | None = Field(max_length=128)
    realized_cash_pnl_atomic: Decimal | None
    # Full PnL can be absent even when a partial valued subtotal exists.
    economic_pnl_atomic: Decimal | None
    valuation_status: str = Field(max_length=128)
    attempts: tuple[EntryAttemptResponse, ...] = Field(max_length=5)
    chart_availability: Availability
    details: dict[str, object]

    @classmethod
    def from_view(cls, value: StrategyEntry) -> Self:
        """Convert every nested atomic integer before JSON reaches JavaScript."""
        document = asdict(value)
        document["details"] = copy_decimal_document(value.details)
        return cls.model_validate(document)


class StrategyEntryPageResponse(ApiModel):
    """At most one canonical page, with the existing exact composite cursor."""

    items: tuple[StrategyEntryResponse, ...] = Field(max_length=200)
    next_cursor: RoundTripCursorResponse | None

    @classmethod
    def from_view(cls, value: StrategyEntryPage) -> Self:
        """No unbounded history or implicit page concatenation is permitted."""
        return cls(
            items=tuple(StrategyEntryResponse.from_view(item) for item in value.items),
            next_cursor=None
            if value.next_cursor is None
            else RoundTripCursorResponse.from_domain(value.next_cursor),
        )


class StrategyDashboardResponse(ApiModel):
    """A versioned presentation contract, never a new canonical result artifact."""

    contract_schema: Literal["strategy-results/v1"] = "strategy-results/v1"
    summary: StrategySummaryResponse
    entries: StrategyEntryPageResponse

    @classmethod
    def from_view(cls, value: StrategyDashboard) -> Self:
        """Initial response binds the page to its authenticated result summary."""
        return cls(
            summary=StrategySummaryResponse.from_view(value.summary),
            entries=StrategyEntryPageResponse.from_view(value.entries),
        )


class DistributionItemResponse(ApiModel):
    """Each category uses an exact count and a safe bounded label."""

    label: str = Field(max_length=256)
    count: Decimal


class ResultDistributionResponse(ApiModel):
    """An explicit denominator prevents confusing positions with order attempts."""

    key: str = Field(max_length=64)
    population: str = Field(max_length=64)
    total: Decimal
    items: tuple[DistributionItemResponse, ...] = Field(max_length=256)


class StrategyAnalyticsResponse(ApiModel):
    """Only completed whole-run reductions are serialized as successful analytics."""

    contract_schema: Literal["strategy-analytics/v1"] = "strategy-analytics/v1"
    run_artifact_id: Digest
    entry_count: Decimal
    distributions: tuple[ResultDistributionResponse, ...] = Field(max_length=16)

    @classmethod
    def from_view(cls, value: StrategyAnalytics) -> Self:
        """Counts use strings too, so all aggregate math can remain exact in React."""
        distributions = tuple(
            ResultDistributionResponse(
                key=item.key,
                population=item.population,
                total=str(item.total),
                # Every category remains exact decimal text, including zero counts.
                items=tuple(
                    DistributionItemResponse(label=label, count=str(count))
                    for label, count in item.items
                ),
            )
            for item in value.distributions
        )
        # The outer identity binds all completed distributions to the requested committed artifact.
        return cls(
            run_artifact_id=value.run_artifact_id.hex,
            entry_count=str(value.entry_count),
            distributions=distributions,
        )
