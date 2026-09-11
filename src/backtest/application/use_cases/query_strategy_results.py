"""One result-query workflow for every currently implemented strategy family."""

from __future__ import annotations

from collections import Counter
from collections.abc import Generator, Iterator
from contextlib import closing, contextmanager
from dataclasses import replace

# Query orchestration depends on application contracts, never concrete storage or SQL.
from backtest.application.errors import ReprepareRequiredError
from backtest.application.market_charts import (
    MAX_MARKET_CHART_EVENTS,
    MarketChartQueryError,
    # History projections share one immutable signal/attempt marker vocabulary.
    StrategyMarketChart,
)
from backtest.application.ports.market_charts import StrategyMarketChartReader
from backtest.application.ports.run_results import (
    RoundTripCursor,
    RunResultReaderFactory,
    # Authentication and scan lifetime remain owned by the replaceable result reader.
    VerifiedRunResultReader,
)
from backtest.application.run_results import FirstSwapSummaryMetadata
from backtest.application.strategy_result_projection import exact, project_entry, project_summary

# Queries own orchestration and presentation; no adapter or filesystem imports enter this layer.
from backtest.application.strategy_results import (
    EntryAttempt,
    ResultDistribution,
    StrategyAnalytics,
    # Page, aggregate and scalar views have independent bounded transport contracts.
    StrategyDashboard,
    StrategyEntry,
    StrategyEntryPage,
    StrategyResultsError,
    # Summary availability is independent from supplemental scan admission.
    StrategySummary,
)
from backtest.application.use_cases.query_copy_market_chart import _verify_chart_position

# Existing identities and family result values are consumed without semantic remapping.
from backtest.domain.identifiers import ArtifactId, ContentDigest
from backtest.domain.roundtrips import RoundTripRecord
from backtest.engine.copytrading_results import CopyPositionRecord


class QueryStrategyResults:
    """Verified summaries stay usable independently of optional analytical scans."""

    def __init__(
        self, readers: RunResultReaderFactory, charts: StrategyMarketChartReader | None = None
    ) -> None:
        self._readers = readers
        self._charts = charts

    @contextmanager
    def _reader(self, artifact_id: ArtifactId) -> Iterator[VerifiedRunResultReader]:
        """Collapse infrastructure details while retaining typed budget failures."""
        try:
            with self._readers.open_exact(artifact_id) as reader:
                yield reader
        except (StrategyResultsError, ReprepareRequiredError, MarketChartQueryError):
            raise
        # No traceback, source endpoint or local path is exposed to the browser.
        except (OSError, RuntimeError, TypeError, ValueError, KeyError) as error:
            raise StrategyResultsError("STRATEGY_RESULT_UNAVAILABLE") from error

    def summary(self, artifact_id: ArtifactId) -> StrategySummary:
        """Read immutable scalar metadata without requesting optional analytics."""
        with self._reader(artifact_id) as reader:
            reader.verify()
            return project_summary(artifact_id, reader.manifest)

    def dashboard(self, artifact_id: ArtifactId, *, limit: int = 25) -> StrategyDashboard:
        """Initial response contains one page and one summary from the same lease."""
        _limit(limit)
        with self._reader(artifact_id) as reader:
            page = _page(reader, None, limit)
            reader.verify()
            return StrategyDashboard(project_summary(artifact_id, reader.manifest), page)

    def entries(
        self, artifact_id: ArtifactId, *, after: RoundTripCursor | None = None, limit: int = 25
    ) -> StrategyEntryPage:
        """Canonical continuation is independent of page-local search/sort."""
        _limit(limit)
        with self._reader(artifact_id) as reader:
            return _page(reader, after, limit)

    def entry(self, artifact_id: ArtifactId, key: RoundTripCursor) -> StrategyEntry:
        """Select one exact stored identity, never an alias or a nearby position."""
        with self._reader(artifact_id) as reader:
            predecessor = _predecessor(key)
            page = _page(reader, predecessor, 1)
            if not page.items or _key(page.items[0]) != key:
                raise StrategyResultsError("STRATEGY_ENTRY_NOT_FOUND")
            return page.items[0]

    def analytics(self, artifact_id: ArtifactId) -> StrategyAnalytics:
        """Only a completed, budget-admitted reduction becomes a whole-run response."""
        with self._reader(artifact_id) as reader:
            # Each category has its own population, so attempt and position rates cannot mix.
            distributions: dict[str, Counter[str]] = {
                "entry_outcomes": Counter(),
                "position_outcomes": Counter(),
                "exit_reasons": Counter(),
                "attempt_outcomes": Counter(),
                # Failures and quote comparisons include rejected/failed attempts as recorded.
                "failure_reasons": Counter(),
                "quote_slippage": Counter(),
                "realized_pnl": Counter(),
            }
            # Pump rows stream; generic audit is bounded by the same admission gate.
            count = 0
            with closing(_all_entries(reader)) as records:
                for entry in records:
                    _accumulate(distributions, entry)
                    count += 1
            # Names are part of the presentation contract and accompany exact totals.
            populations = {
                "entry_outcomes": "entries",
                "position_outcomes": "entries",
                "exit_reasons": "entries_with_exit_decision",
                "attempt_outcomes": "attempts",
                # Quote/PnL populations exclude missing values instead of inventing zeros.
                "failure_reasons": "failed_or_rejected_attempts",
                "quote_slippage": "attempts_with_both_quotes",
                "realized_pnl": "valued_realized_entries",
            }
            # Each denominator names the exact stored population counted by this reduction.
            result = tuple(
                ResultDistribution(
                    key,
                    populations[key],
                    # Totals are derived only after the admitted iterator completes successfully.
                    sum(counts.values()),
                    tuple(sorted(counts.items())),
                )
                for key, counts in distributions.items()
            )
            # No intermediate aggregate can escape a quota, decoding or corruption failure.
            return StrategyAnalytics(artifact_id, count, result)

    def chart(self, artifact_id: ArtifactId, key: RoundTripCursor) -> StrategyMarketChart:
        """History selection remains bound to an exact verified stored signal and pair."""
        if self._charts is None:
            raise MarketChartQueryError("MARKET_CHART_UNAVAILABLE")
        with self._reader(artifact_id) as reader:
            summary = reader.manifest.bounded_summary
            if isinstance(summary, FirstSwapSummaryMetadata):
                raise MarketChartQueryError("MARKET_CHART_UNAVAILABLE")
            # A bounded history query cannot execute or prepare a larger source range.
            if summary.comparison.historical_event_count > MAX_MARKET_CHART_EVENTS:
                raise MarketChartQueryError("MARKET_CHART_LIMIT_EXCEEDED")
            page = reader.roundtrips(after=_predecessor(key), limit=1)
            reader.verify()
            if not page.items or _key(project_entry(page.items[0])) != key:
                raise StrategyResultsError("STRATEGY_ENTRY_NOT_FOUND")
            # History must be bound to the same stored row selected by the composite cursor.
            position = page.items[0]
            chart = self._charts.read(artifact_id, reader.manifest, position)
            # The replaceable reader must return this exact run, input and recorded position.
            expected = (artifact_id, key.roundtrip_id, reader.manifest.resolved_spec.snapshot_id)
            if (chart.run_artifact_id, chart.position_id, chart.snapshot_id) != expected:
                raise ValueError("chart artifact binding mismatch")
            if isinstance(position, CopyPositionRecord):
                _verify_chart_position(chart, position)
            else:
                _verify_sniping_chart(chart, position)
            # Family-specific marker checks run after common run/snapshot identity validation.
            return chart


def _verify_sniping_chart(chart: StrategyMarketChart, position: RoundTripRecord) -> None:
    """Creation and own-order markers cannot be substituted with another token or outcome."""
    if (chart.asset_id, chart.quote_asset_id) != (position.asset_id, position.quote_asset_id):
        raise ValueError("chart asset binding mismatch")
    signal = replace(position.target_position, event_index=None)
    if chart.markers[0].point.position != signal:
        raise ValueError("chart creation binding mismatch")
    # Missing legs are intentional for cooldown suppression, not empty fabricated orders.
    legs = [
        (number, leg) for number, leg in enumerate((position.buy, position.sell)) if leg is not None
    ]
    if len(chart.markers) != len(legs) + 1:
        raise ValueError("chart attempt count mismatch")
    # A suppressed launch legitimately has only its creation marker.
    for marker, (number, leg) in zip(chart.markers[1:], legs, strict=True):
        coordinate = replace(leg.landing_position or leg.decision_position, event_index=None)
        # Landing evidence determines failure stage; an expected coordinate is insufficient.
        status = (
            "FILLED"
            if leg.failure_code is None
            else "FAILED"
            if leg.landing_position
            # A pre-submit failure is drawn at its actual decision boundary.
            else "REJECTED"
        )
        # Match every semantic marker operand, including attempts with identical boundaries.
        expected = (number, leg.side.value, status, leg.failure_code, coordinate)
        actual = (
            marker.attempt,
            marker.kind,
            marker.status,
            # Outcome labels are checked alongside the actual coordinate, not only the mint.
            marker.failure_code,
            marker.point.position,
        )
        # A replaceable reader cannot substitute a plausible but differently executed result.
        if actual != expected:
            raise ValueError("chart attempt binding mismatch")


def _limit(limit: int) -> None:
    """Reject booleans and unbounded page sizes at the application boundary."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise ValueError("entry limit must be between 1 and 200")


def _key(entry: StrategyEntry) -> RoundTripCursor:
    """Paging reuses actual result/order identity, not a new semantic digest."""
    return RoundTripCursor(int(entry.boundary_ordinal), ContentDigest(entry.entry_id))


def _predecessor(key: RoundTripCursor) -> RoundTripCursor | None:
    """Seek inclusively using the existing strict-after composite cursor."""
    digest = int(key.roundtrip_id.hex, 16)
    if digest:
        return RoundTripCursor(key.target_boundary_ordinal, ContentDigest(f"{digest - 1:064x}"))
    if key.target_boundary_ordinal:
        return RoundTripCursor(key.target_boundary_ordinal - 1, ContentDigest("f" * 64))
    return None


def _page(
    reader: VerifiedRunResultReader, after: RoundTripCursor | None, limit: int
) -> StrategyEntryPage:
    """Preserve existing indexed Pump pagination; only generic audit needs a bounded reduction."""
    if not isinstance(reader.manifest.bounded_summary, FirstSwapSummaryMetadata):
        page = reader.roundtrips(after=after, limit=limit)
        return StrategyEntryPage(tuple(project_entry(row) for row in page.items), page.next_cursor)
    # FirstSwap has no position table, so its order page uses the same bounded audit scan.
    selected = [entry for entry in _all_entries(reader) if after is None or _key(entry) > after]
    items = tuple(selected[:limit])
    cursor = _key(items[-1]) if len(selected) > limit else None
    return StrategyEntryPage(items, cursor)


def _all_entries(reader: VerifiedRunResultReader) -> Generator[StrategyEntry]:
    """A generic order is correlated exclusively by its immutable audit ORDER identity."""
    generic: dict[str, list[dict[str, object]]] = {}
    with reader.entry_records() as records:
        for record in records:
            if not isinstance(record, dict):
                yield project_entry(record)
                continue
            order_id = record.get("order_id")
            if isinstance(order_id, str):
                # Non-order observations cannot be attributed to a strategy signal without evidence.
                ContentDigest(order_id)
                generic.setdefault(order_id, []).append(record)
        # Admission and its deadline include grouping, sorting and downstream reduction.
        entries = [_generic_entry(key, records) for key, records in generic.items()]
        yield from sorted(entries, key=_key)


def _generic_entry(order_id: str, records: list[dict[str, object]]) -> StrategyEntry:
    """FirstSwap audit has order lifecycle but no recoverable signal/round-trip PnL."""
    decisions = [row for row in records if row.get("record_type") == "INTENT_PROPOSED"]
    # Only committed terminal audit outcomes count as a completed order lifecycle.
    terminal_types = {
        "ORDER_REJECTED": "REJECTED",
        "ORDER_EXECUTION_FAILED_AND_RELEASED": "FAILED",
        "ORDER_FILLED_ATOMICALLY": "FILLED",
    }
    # Multiple or missing terminals are ambiguous evidence and must reject the query.
    terminals = [row for row in records if row.get("record_type") in terminal_types]
    if len(decisions) != 1 or len(terminals) != 1:
        raise ValueError("generic order lifecycle is incomplete or ambiguous")
    decision, terminal = decisions[0], terminals[0]
    state = terminal_types[str(terminal["record_type"])]
    fills = [row["fill"] for row in records if row.get("record_type") == "RESULT_FILL"]
    # Actual fills carry asset/amount evidence; rejected entries cannot acquire fabricated fills.
    if len(fills) != (1 if state == "FILLED" else 0):
        raise ValueError("generic fill evidence differs from order outcome")
    fill = fills[0] if fills else None
    if fill is not None and not isinstance(fill, dict):
        raise ValueError("generic fill evidence is malformed")
    # A fill must land at its own terminal audit boundary under the same immutable order ID.
    if fill is not None and (
        fill["order_id"] != order_id or fill["boundary_ordinal"] != terminal["boundary_ordinal"]
    ):
        raise ValueError("generic fill correlation differs from audit")
    # A rejected order never receives a landing marker or a fictitious price.
    boundary = str(decision["boundary_ordinal"])
    landing = None if state == "REJECTED" else str(terminal["boundary_ordinal"])
    attempt = EntryAttempt(
        "ENTRY", 0, state, boundary, landing, None, None, None, exact(terminal.get("reason"))
    )
    # The original ORDER identity is the entry key; no synthetic signal ID is introduced.
    return StrategyEntry(
        order_id,
        boundary,
        None,
        None if fill is None else exact(fill["bought_asset_id"]),
        # Actual fills provide the pair, but do not define creator/signer roles for FirstSwap.
        None if fill is None else exact(fill["sold_asset_id"]),
        None,
        None,
        # FirstSwap has neither an exit reason nor round-trip economic accounting.
        state,
        None,
        None,
        None,
        # Preserve order outcomes and raw verified facts without inventing market-chart support.
        "NOT_APPLICABLE",
        (attempt,),
        "UNAVAILABLE",
        {
            "audit": [row for row in records if row.get("record_type") != "RESULT_FILL"],
            # Amounts are the original Fill document decoded from fixed-width columns.
            "fills": fills,
        },
    )


def _accumulate(distributions: dict[str, Counter[str]], entry: StrategyEntry) -> None:
    """Keep attempts, positions, quote movements and realized valuation separate."""
    entry_state = entry.attempts[0].status if entry.attempts else entry.status
    distributions["entry_outcomes"][entry_state] += 1
    distributions["position_outcomes"][entry.status] += 1
    if entry.exit_reason is not None:
        distributions["exit_reasons"][entry.exit_reason] += 1
    # Nullable realized valuation is excluded from the profit/loss denominator.
    if entry.realized_cash_pnl_atomic is not None:
        # Realized zero is its own outcome, never a proxy for unknown valuation.
        pnl = int(entry.realized_cash_pnl_atomic)
        distributions["realized_pnl"]["PROFIT" if pnl > 0 else "LOSS" if pnl < 0 else "FLAT"] += 1
    for attempt in entry.attempts:
        distributions["attempt_outcomes"][f"{attempt.side}:{attempt.status}"] += 1
        if attempt.failure_code is not None:
            distributions["failure_reasons"][f"{attempt.side}:{attempt.failure_code}"] += 1
        if attempt.reference_out_atomic is not None and attempt.landing_out_atomic is not None:
            # This is a quote comparison, including failed attempts, not a realized fill metric.
            delta = int(attempt.landing_out_atomic) - int(attempt.reference_out_atomic)
            distributions["quote_slippage"][
                "FAVORABLE" if delta > 0 else "ADVERSE" if delta < 0 else "UNCHANGED"
            ] += 1
    # Unexpected category cardinality rejects the whole query before transport allocation.
    if any(len(counts) > 256 for counts in distributions.values()):
        raise StrategyResultsError("RESULT_ANALYTICS_LIMIT_EXCEEDED")
