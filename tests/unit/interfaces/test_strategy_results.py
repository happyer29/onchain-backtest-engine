"""Common result precision, family semantics, bounded pagination and safe transport."""

from contextlib import contextmanager
from dataclasses import fields
from types import SimpleNamespace

import pytest
import test_api as fixtures

from backtest.application.ports.run_results import RoundTripCursor, RoundTripPage
from backtest.application.run_results import FirstSwapSummaryMetadata, RunComparisonProjection
from backtest.application.strategy_result_projection import project_entry, project_summary
from backtest.application.strategy_results import StrategyResultsError
from backtest.application.use_cases.query_strategy_results import QueryStrategyResults

# Existing immutable ID and transport contracts remain the authority for output shape.
from backtest.domain.identifiers import ArtifactId, BundleId, ContentDigest
from backtest.interfaces.api.strategy_results import StrategyEntryResponse

ARTIFACT = ArtifactId("1" * 64)


def _generic_manifest():
    """Use a real typed summary while isolating storage from interface tests."""
    source = fixtures._sniping_summary()
    comparison = RunComparisonProjection(
        **{field.name: getattr(source, field.name) for field in fields(RunComparisonProjection)}
    )
    # A FirstSwap summary contains comparison only, not any Pump financial defaults.
    summary = FirstSwapSummaryMetadata(
        ContentDigest("2" * 64),
        ContentDigest("3" * 64),
        BundleId("4" * 64),
        BundleId("5" * 64),
        comparison,
    )
    return SimpleNamespace(
        bounded_summary=summary,
        logical_run_id=source.logical_run_id,
        resolved_spec=fixtures._resolved_spec(),
    )


class Reader:
    """Controlled result source records page requests and failures without disk access."""

    def __init__(self, *, failure=None):
        self.manifest = _generic_manifest()
        self.failure = failure
        self.row = fixtures._sniping_roundtrip()
        self.pages = []
        self.closed = False

    def verify(self):
        """Failures must propagate safely instead of returning default metrics."""
        if self.failure:
            raise self.failure

    def roundtrips(self, *, after, limit):
        self.pages.append((after, limit))
        self.verify()
        key = RoundTripCursor(self.row.target_position.boundary_ordinal, self.row.roundtrip_id)
        return RoundTripPage((self.row,) if after is None or after < key else (), None)

    @contextmanager
    def entry_records(self):
        """The scan lease must close even when reduction or transport fails."""
        try:
            self.verify()
            yield iter((self.row,))
        finally:
            self.closed = True


class Factory:
    def __init__(self, reader):
        self.reader = reader
        self.opened = []

    @contextmanager
    def open_exact(self, artifact_id):
        self.opened.append(artifact_id)
        yield self.reader


def test_sniping_precision_actor_role_and_actual_landing():
    row = fixtures._sniping_roundtrip()
    entry = project_entry(row)
    response = StrategyEntryResponse.from_view(entry)
    assert entry.actor_role == "creator" and entry.actor_id == "developer"
    # Nested source times exceed Number.MAX_SAFE_INTEGER and must remain decimal strings.
    assert response.details["target_time_ns"] == "1800000000000000000"
    assert response.attempts[0].decision_boundary == str(row.buy.decision_position.boundary_ordinal)
    assert response.realized_cash_pnl_atomic == str(row.realized_cash_pnl_atomic)


def test_first_swap_summary_has_no_invented_pnl_or_close_rate():
    summary = project_summary(ARTIFACT, _generic_manifest())
    metrics = {item.key: item for item in summary.metrics}
    assert summary.family == "FIRST_SWAP"
    assert metrics["economic_pnl_atomic"].availability == "NOT_APPLICABLE"
    assert metrics["closed_position_count"].value is None


def test_common_query_pages_and_analytics_are_independent():
    reader = Reader()
    reader.manifest.bounded_summary = object()
    queries = QueryStrategyResults(Factory(reader))
    page = queries.entries(ARTIFACT, limit=1)
    assert len(page.items) == 1 and reader.pages == [(None, 1)]
    # A wrong digest cannot select a neighboring entry at the same chain coordinate.
    key = RoundTripCursor(int(page.items[0].boundary_ordinal), ContentDigest("f" * 64))
    with pytest.raises(StrategyResultsError, match="STRATEGY_ENTRY_NOT_FOUND"):
        queries.entry(ARTIFACT, key)
    analytics = queries.analytics(ARTIFACT)
    assert analytics.entry_count == 1 and reader.closed
    assert (
        next(item for item in analytics.distributions if item.key == "attempt_outcomes").total == 2
    )


@pytest.mark.parametrize(
    "code,status",
    [
        ("RESULT_ANALYTICS_LIMIT_EXCEEDED", 422),
        ("RESULT_ANALYTICS_BUSY", 503),
        ("STRATEGY_RESULT_UNAVAILABLE", 404),
    ],
)
def test_analytics_failure_is_typed_and_never_partial(tmp_path, code, status):
    reader = Reader(failure=StrategyResultsError(code))
    client = fixtures._client(
        tmp_path, query_strategy_results=QueryStrategyResults(Factory(reader))
    )
    response = client.get(f"/api/v1/run-artifacts/{ARTIFACT.hex}/analytics")
    assert response.status_code == status
    assert response.json()["code"] == code and "distributions" not in response.json()


def test_common_api_rejects_unknown_parameters_and_preserves_precision(tmp_path):
    reader = Reader()
    reader.manifest.bounded_summary = object()
    client = fixtures._client(
        tmp_path, query_strategy_results=QueryStrategyResults(Factory(reader))
    )
    url = f"/api/v1/run-artifacts/{ARTIFACT.hex}/entries"
    response = client.get(url, params={"limit": 1})
    assert response.status_code == 200
    assert response.json()["items"][0]["details"]["target_time_ns"] == "1800000000000000000"
    # Unknown paths/selectors cannot widen the query; incomplete cursor pairs are rejected.
    assert client.get(url, params={"path": "/private"}).status_code == 422
    assert client.get(url, params={"after_roundtrip_id": "f" * 64}).status_code == 422
    assert client.get(url, params={"limit": 201}).status_code == 422
    assert client.get(url.replace(ARTIFACT.hex, "latest")).status_code == 422


def test_query_redacts_infrastructure_errors(tmp_path):
    reader = Reader(failure=OSError("/private/secret/source credentials"))
    client = fixtures._client(
        tmp_path, query_strategy_results=QueryStrategyResults(Factory(reader))
    )
    response = client.get(f"/api/v1/run-artifacts/{ARTIFACT.hex}/strategy-summary")
    assert response.status_code == 404
    assert "secret" not in response.text and "private" not in response.text
