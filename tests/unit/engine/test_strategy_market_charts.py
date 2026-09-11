"""Shared chart history preserves actual Sniping creation and execution coordinates."""

from dataclasses import replace
from time import monotonic

import pytest
import test_copy_market_charts as charts
import test_sniping_engine as base

from backtest.adapters.results.market_charts import LocalCopyMarketChartReader, _markers
from backtest.application.market_charts import CopyMarketChart, StrategyMarketChart
from backtest.application.use_cases.query_strategy_results import _verify_sniping_chart
from backtest.domain.identifiers import AccountId, ArtifactId, SnapshotId
from backtest.plugins.protocols.pumpfun.market_charts import pump_strategy_market_cap_state


def _chart(record, events):
    """Read-only projection consumes the exact events already used by the reference oracle."""
    reader = LocalCopyMarketChartReader(None, pump_strategy_market_cap_state, None)
    clock = base._clock()
    source = charts.Stream(events)
    points = reader._collect_points(source, record, clock, monotonic() + 5)
    assert source.closed
    # The common chart binds to the same immutable signal/position identity.
    return StrategyMarketChart(
        ArtifactId("1" * 64),
        record.roundtrip_id,
        SnapshotId("2" * 64),
        record.asset_id,
        record.quote_asset_id,
        tuple(points),
        _markers(record, points, clock),
    )


def test_sniping_chart_uses_post_creation_group_and_actual_landings():
    state = base._state(virtual_sol_reserves_lamports=32_000_000_000)
    events = (base._launch(), base._trade(state, block=100, transaction=0, event_index=1, group=1))
    _, sink = base._run(events)
    record = sink.roundtrips[0]
    chart = _chart(record, events)
    _verify_sniping_chart(chart, record)
    # One terminal point represents both creation and bundled buy; no intermediate callback.
    assert chart.points[0].market_cap_atomic == 29_822_926_374
    assert [item.kind for item in chart.markers] == ["SIGNAL", "BUY", "SELL"]
    assert chart.markers[1].point.position == record.buy.landing_position
    assert chart.markers[2].point.position == record.sell.landing_position


def test_suppressed_creation_has_no_fabricated_own_order_marker():
    events = (
        base._launch(),
        base._launch(event_index=1, group=1, token="SECOND", venue="second-curve"),
    )
    _, sink = base._run(events)
    record = next(item for item in sink.roundtrips if item.status.value == "COOLDOWN_SKIPPED")
    chart = _chart(record, events)
    assert len(chart.markers) == 1 and chart.markers[0].kind == "SIGNAL"
    _verify_sniping_chart(chart, record)
    # The old copy contract still requires its consumed entry attempt.
    with pytest.raises(ValueError, match="entry attempt"):
        CopyMarketChart(
            chart.run_artifact_id,
            chart.position_id,
            chart.snapshot_id,
            chart.asset_id,
            chart.quote_asset_id,
            chart.points,
            chart.markers,
        )


def test_sniping_chart_rejects_another_creator_even_with_same_event_identity():
    launch = base._launch()
    _, sink = base._run((launch,))
    forged = replace(launch, developer_id=AccountId("another-creator"))
    with pytest.raises(ValueError, match="creation binding"):
        _chart(sink.roundtrips[0], (forged,))
