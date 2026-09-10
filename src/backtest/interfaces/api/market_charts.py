"""Closed, lossless HTTP schemas for bounded copy-token charts."""

from typing import Annotated, Literal, Self

from pydantic import Field

# The transport maps application projections without reading artifacts or running math.
from backtest.application.market_charts import (
    MAX_MARKET_CHART_MARKERS,
    MAX_MARKET_CHART_POINTS,
    CopyChartMarker,
    CopyMarketChart,
    # These types preserve canonical chain coordinates and lifecycle on the wire.
    MarketCapPoint,
    MarketLifecycle,
)
from backtest.interfaces.api.schemas import ApiModel, ChainPositionResponse

# Numeric strings avoid JavaScript precision loss for both amounts and timestamps.
_Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
_Atomic = Annotated[str, Field(pattern=r"^(?:0|[1-9][0-9]*)$", max_length=39)]


class MarketCapPointResponse(ApiModel):
    """Wide amounts and nanoseconds reach the browser as exact decimal strings."""

    position: ChainPositionResponse
    block_time_ns: _Atomic
    market_cap_atomic: _Atomic
    lifecycle: MarketLifecycle

    # Serialization preserves the original chain identity alongside the display ordinate.
    @classmethod
    def from_domain(cls, point: MarketCapPoint) -> Self:
        return cls(
            position=ChainPositionResponse.from_domain(point.position),
            block_time_ns=str(point.block_time_ns),
            # Lamport values are never converted to binary floating point.
            market_cap_atomic=str(point.market_cap_atomic),
            lifecycle=point.lifecycle,
        )


class CopyChartMarkerResponse(ApiModel):
    """Failed/rejected attempts remain distinct from actual fills in the UI."""

    kind: Literal["SIGNAL", "BUY", "SELL"]
    status: Literal["OBSERVED_SOURCE", "FILLED", "FAILED", "REJECTED"]
    attempt: int | None = Field(ge=0, le=4)
    point: MarketCapPointResponse
    failure_code: str | None = Field(max_length=256)

    # The mapper retains the original failure instead of inferring it from the chart.
    @classmethod
    def from_domain(cls, marker: CopyChartMarker) -> Self:
        # Model validation checks the closed string vocabulary supplied by the domain view.
        return cls.model_validate(
            {
                "kind": marker.kind,
                "status": marker.status,
                "attempt": marker.attempt,
                # Coordinates identify the effective event, including pre-submit rejections.
                "point": MarketCapPointResponse.from_domain(marker.point),
                "failure_code": marker.failure_code,
            }
        )


class CopyMarketChartResponse(ApiModel):
    """A finite full-history projection of one token inside one retained snapshot."""

    contract_schema: Literal["pumpfun-copy-market-cap/v1"] = "pumpfun-copy-market-cap/v1"
    market_cap_policy: Literal["post-transaction-total-supply-market-cap-lamports-floor/v1"] = (
        "post-transaction-total-supply-market-cap-lamports-floor/v1"
    )
    # Both IDs are exact selectors, never mutable aliases.
    run_artifact_id: _Digest
    position_id: _Digest
    # Input provenance is content-addressed; neither paths nor raw payloads are exposed.
    snapshot_id: _Digest
    asset_id: str = Field(min_length=1, max_length=128)
    quote_asset_id: Literal["SOL"] = "SOL"
    # Series and markers are capped independently before response serialization.
    points: tuple[MarketCapPointResponse, ...] = Field(
        min_length=1, max_length=MAX_MARKET_CHART_POINTS
    )
    # A signal, one entry and at most four exits fit the exact attempt contract.
    markers: tuple[CopyChartMarkerResponse, ...] = Field(
        min_length=2, max_length=MAX_MARKET_CHART_MARKERS
    )

    # All response provenance comes from the verified application view.
    @classmethod
    def from_domain(cls, value: CopyMarketChart) -> Self:
        return cls(
            run_artifact_id=value.run_artifact_id.hex,
            position_id=value.position_id.hex,
            # Snapshot and mint identify the underlying historical series.
            snapshot_id=value.snapshot_id.hex,
            asset_id=value.asset_id.value,
            # Exact integer strings preserve amounts larger than the JS safe-integer range.
            points=tuple(MarketCapPointResponse.from_domain(point) for point in value.points),
            markers=tuple(CopyChartMarkerResponse.from_domain(marker) for marker in value.markers),
        )
