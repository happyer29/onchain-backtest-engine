"""Read one copy signal's chart through verified result and history ports."""

from dataclasses import replace

from backtest.application.errors import ReprepareRequiredError

# Typed chart failures separate unavailable history from rejected resource admission.
from backtest.application.market_charts import (
    MAX_MARKET_CHART_EVENTS,
    CopyMarketChart,
    MarketChartQueryError,
    StrategyMarketChart,
)

# Result and historical storage remain independently replaceable adapters.
from backtest.application.ports.market_charts import CopyMarketChartReader
from backtest.application.ports.run_results import RoundTripCursor, RunResultReaderFactory
from backtest.application.run_results import CopySummaryMetadata
from backtest.domain.identifiers import ArtifactId, ContentDigest
from backtest.engine.copytrading_results import CopyPositionRecord

# Frozen result rows provide the selector; strategy implementations stay outside application.


class QueryCopyMarketChart:
    """An exact row selector prevents cross-run or arbitrary-mint history queries."""

    def __init__(self, results: RunResultReaderFactory, charts: CopyMarketChartReader) -> None:
        self._results = results
        self._charts = charts

    # The endpoint accepts one complete composite result key.

    def execute(
        self,
        artifact_id: ArtifactId,
        position_id: ContentDigest,
        # Boundary is an exact UInt64 ordinal, never a time approximation.
        signal_boundary_ordinal: int,
    ) -> CopyMarketChart:
        """Hold the authenticated run lease throughout the bounded history read."""
        after = _predecessor(signal_boundary_ordinal, position_id)
        try:
            with self._results.open_exact(artifact_id) as reader:
                summary = reader.manifest.bounded_summary
                # Only the Copy Buy result family contains leader signal positions.
                if not isinstance(summary, CopySummaryMetadata):
                    raise MarketChartQueryError("COPY_POSITION_NOT_FOUND")
                # Oversized replay work cannot be smuggled into a synchronous HTTP query.
                if summary.comparison.historical_event_count > MAX_MARKET_CHART_EVENTS:
                    raise MarketChartQueryError("MARKET_CHART_LIMIT_EXCEEDED")
                page = reader.roundtrips(after=after, limit=1)
                # Result verification completes before the historical reader receives authority.
                reader.verify()
                if not page.items or not isinstance(page.items[0], CopyPositionRecord):
                    raise MarketChartQueryError("COPY_POSITION_NOT_FOUND")
                # Both key operands must match the row read from this exact run artifact.
                position = page.items[0]
                if (
                    position.roundtrip_id != position_id
                    or position.target_position.boundary_ordinal != signal_boundary_ordinal
                ):
                    # An adjacent keyset row cannot stand in for the requested position.
                    raise MarketChartQueryError("COPY_POSITION_NOT_FOUND")
                chart = self._charts.read(artifact_id, reader.manifest, position)
                # The replaceable history reader cannot return another run or token's series.
                expected = (artifact_id, position_id, reader.manifest.resolved_spec.snapshot_id)
                if (chart.run_artifact_id, chart.position_id, chart.snapshot_id) != expected:
                    raise ValueError("chart artifact binding mismatch")
                _verify_chart_position(chart, position)
                # Preserve explicitly classified failures without leaking adapter exceptions.
                return chart
        except (ReprepareRequiredError, MarketChartQueryError):
            raise
        # Only safe typed errors cross the result-query boundary.
        except (KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
            raise MarketChartQueryError("MARKET_CHART_UNAVAILABLE") from error


def _verify_chart_position(chart: StrategyMarketChart, position: CopyPositionRecord) -> None:
    """Every chart marker must preserve the exact recorded side, outcome and boundary."""
    if (chart.asset_id, chart.quote_asset_id) != (
        position.intent.asset_id,
        position.intent.quote_asset_id,
    ):
        raise ValueError("chart asset binding mismatch")
    # The first marker is the source signal, independent of delayed strategy observation.
    signal = replace(position.intent.signal.position, event_index=None)
    if chart.markers[0].point.position != signal:
        raise ValueError("chart signal binding mismatch")
    if len(chart.markers) != len(position.attempts) + 1:
        raise ValueError("chart attempt count mismatch")
    # A rejected decision cannot be shifted to its hypothetical landing coordinate.
    for marker, attempt in zip(chart.markers[1:], position.attempts, strict=True):
        boundary = replace(attempt.landed_at or attempt.decision, event_index=None)
        actual = (marker.attempt, marker.status, marker.failure_code, marker.point.position)
        expected = (attempt.number, attempt.status.value, attempt.failure_code, boundary)
        # Compare immutable outcomes, including the absence of a landing after rejection.
        if actual != expected:
            raise ValueError("chart attempt binding mismatch")


def _predecessor(boundary: int, position_id: ContentDigest) -> RoundTripCursor | None:
    """Seek directly before an exact composite key, including the zero-digest edge."""
    RoundTripCursor(boundary, position_id)
    value = int(position_id.hex, 16)
    if value:
        return RoundTripCursor(boundary, ContentDigest(f"{value - 1:064x}"))
    # A zero digest has no predecessor at the same boundary.
    if boundary:
        return RoundTripCursor(boundary - 1, ContentDigest("f" * 64))
    return None
