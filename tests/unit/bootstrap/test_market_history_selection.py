"""Verified preparation feeds exact selected history without replaying unrelated markets."""

from dataclasses import replace

import pytest
import test_pumpfun_copy_source as fixtures

# These tests use genuine committed input closure and the production Arrow reader.
from backtest.adapters.columnar.arrow import CanonicalParquetReplaySource
from backtest.adapters.columnar.arrow import parquet_replay as replay
from backtest.application.market_charts import MarketChartQueryError
from backtest.application.use_cases.prepare_dataset import PrepareDatasetRequest
from backtest.bootstrap.build_tools import BuildToolBundleRegistry

# No synthetic result or source receipt is published by the selected-history reader.
from backtest.domain.identifiers import VenueId
from backtest.domain.market_events import TokenLaunchEvent


@pytest.fixture
def canonical(tmp_path):
    """Preparation proves the same clock, initialization and settlement as a normal run."""
    plan, prepare, artifacts, _ = fixtures.planned_fixture(tmp_path)
    prepared = prepare.execute(PrepareDatasetRequest(plan))
    # Physical tools and the selected snapshot come from the same preparation closure.
    return CanonicalParquetReplaySource(
        artifacts,
        prepared.snapshot_id,
        build_tools=BuildToolBundleRegistry().pin(),
        # Small native batches exercise filtering and cross-batch transaction continuity.
        reader_batch_rows=1,
    )


# Native batch layout cannot alter selected history or its whole-transaction ordering.
@pytest.mark.parametrize("batch_rows", [1, 256])
def test_filtered_history_matches_full_verified_replay(canonical, monkeypatch, batch_rows):
    """The full replay oracle authenticates the expected sequence before filtering is tested."""
    events = tuple(canonical.events())
    venue = next(event.venue_id for event in events if isinstance(event, TokenLaunchEvent))
    expected = tuple(event for event in events if getattr(event, "venue_id", None) == venue)
    canonical._reader_batch_rows = batch_rows
    # A full replay in this path would regress interactive work to millions of Python objects.
    monkeypatch.setattr(canonical, "events", lambda: pytest.fail("full replay is forbidden"))
    actual = tuple(canonical.events_for_venue(venue, check_budget=lambda: None))
    assert actual == expected
    assert tuple(canonical.events_for_venue(VenueId("absent"), check_budget=lambda: None)) == ()


# The filtered path keeps semantic verification on every returned row.
def test_selected_semantic_corruption_is_rejected(canonical, monkeypatch):
    event = next(item for item in canonical.events() if isinstance(item, TokenLaunchEvent))
    decode = replay._event_from_row

    # Simulate a semantic mismatch despite a well-shaped physical row and stored digest.
    def corrupt(*args, **kwargs):
        value = decode(*args, **kwargs)
        return replace(value, venue_id=VenueId("wrong-venue"))

    monkeypatch.setattr(replay, "_event_from_row", corrupt)
    # A mismatch must escape as an error before a successful chart can be returned.
    with pytest.raises(replay.CanonicalDataError, match="semantic digest"):
        tuple(canonical.events_for_venue(event.venue_id, check_budget=lambda: None))


def test_deadline_is_checked_for_empty_filtered_batches(canonical):
    calls = 0

    # Even a venue with no matching rows must not scan every shard after its deadline.
    def check_budget():
        nonlocal calls
        calls += 1
        if calls > 4:
            raise MarketChartQueryError("MARKET_CHART_LIMIT_EXCEEDED")

    # The fifth checkpoint is reached while the requested venue remains completely absent.
    with pytest.raises(MarketChartQueryError, match="LIMIT_EXCEEDED"):
        tuple(canonical.events_for_venue(VenueId("absent"), check_budget=check_budget))
    assert calls == 5


def test_selected_order_corruption_is_rejected(canonical, monkeypatch):
    """One committed coordinate cannot appear twice in a successful chart series."""
    event = next(item for item in canonical.events() if isinstance(item, TokenLaunchEvent))
    digest = bytes.fromhex(replay.canonical_event_digest(event).hex)
    # Duplicate selected keys cannot be hidden by the cross-capability merge.
    monkeypatch.setattr(canonical, "_venue_events", lambda *args: iter(((event, digest),)))
    with pytest.raises(replay.CanonicalDataError, match="order"):
        tuple(canonical.events_for_venue(event.venue_id, check_budget=lambda: None))


def test_unrelated_history_is_never_decoded(canonical, monkeypatch):
    """Other tokens must not allocate Python events, even when their Parquet is scanned."""

    def forbidden(*args, **kwargs):
        pytest.fail("an unrelated venue reached the Python event decoder")

    # Predicate pushdown must work even if there is no matching row in any partition.
    monkeypatch.setattr(replay, "_event_from_row", forbidden)
    assert tuple(canonical.events_for_venue(VenueId("absent"), check_budget=lambda: None)) == ()
