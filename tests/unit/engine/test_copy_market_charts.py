"""Historical chart queries over shared financial fixtures: causality, math and quotas."""

from contextlib import ExitStack, contextmanager
from dataclasses import replace
from time import monotonic
from types import SimpleNamespace

# Reuse independent financial fixtures; charts never execute trades themselves.
import pytest
import test_copytrading_execution as execution
import test_copytrading_replay as replay
import test_sniping_engine as base

# The real reader and protocol projector are exercised with an explicitly bounded test stream.
import backtest.adapters.results.market_charts as adapter
import backtest.application.use_cases.query_copy_market_chart as query_module
from backtest.application.market_charts import (
    CopyMarketChart,
    MarketChartQueryError,
    # The query is tested through its own ports, separately from the concrete adapter.
    MarketLifecycle,
)
from backtest.application.ports.run_results import RoundTripPage
from backtest.domain.identifiers import AccountId, ArtifactId, AssetId, ContentDigest, SnapshotId
from backtest.engine.copytrading_results import freeze_copy_position

# Domain IDs and protocol decoding keep fixture units explicit.
from backtest.plugins.protocols.pumpfun.market_charts import pump_market_cap_state


@pytest.fixture
def position_and_clock():
    """An actual filled round trip supplies immutable signal and attempt coordinates."""
    executor, state, _ = execution._setup()
    execution._buy(executor, state)
    sale = executor.begin_sell(state, execution._trigger(executor, state))
    executor.land(state, sale.expected_landing)
    # Freeze after actual execution so chart tests cannot invent a successful exit.
    return freeze_copy_position(state, executor), executor.clock


class Stream:
    """Expose closure so quota/error paths must release the streaming resource."""

    def __init__(self, events):
        self.values, self.closed = events, False

    def events(self):
        """Generator finalization models the canonical reader's held artifact leases."""
        try:
            yield from self.values
        finally:
            self.closed = True


def collect(position_and_clock, events, *, deadline=None, projector=pump_market_cap_state):
    """The test isolates streaming logic from immutable-publication integration tests."""
    position, clock = position_and_clock
    stream = Stream(events)
    reader = adapter.LocalCopyMarketChartReader(None, projector, None)
    try:
        # The stream must close on both complete scans and exceptions.
        return reader._collect_points(stream, position, clock, deadline or monotonic() + 5)
    finally:
        assert stream.closed


# Use a literal independent expected capitalization to catch unit and supply errors.
def test_market_cap_uses_full_supply_and_floors_exact_lamports():
    # The familiar initial Pump ratio is 30 SOL * 1e15 / 1.073e15 token atoms.
    initial = pump_market_cap_state(base._launch())
    assert initial.market_cap_atomic == 27_958_993_476
    assert initial.lifecycle is MarketLifecycle.ACTIVE
    trade = pump_market_cap_state(replay._trade(1))
    assert trade.signing_wallet == execution.SIGNER
    # An unsupported payload or excluded launch cannot silently produce display prices.
    with pytest.raises(ValueError, match="unsupported"):
        pump_market_cap_state(
            base._trade(base._state(), block=100, transaction=1, event_index=0, group=2)
        )
    # Mayhem exclusion is preserved even in a read-only display projection.
    with pytest.raises(ValueError, match="unsupported"):
        pump_market_cap_state(base._launch(state=base._state(mode=base.PumpMode.MAYHEM)))


def test_post_transaction_state_and_quiet_timer_marks(position_and_clock):
    # Two Pump instructions at one transaction expose exactly one terminal market-cap point.
    terminal = replay._trade(
        1, event_index=1, state=base._state(virtual_sol_reserves_lamports=33_000_000_000)
    )
    points = collect(position_and_clock, (base._launch(), replay._trade(1), terminal))
    # An extra clock-end point covers quiet periods without adding a price transition.
    assert len(points) == 3
    assert points[1].market_cap_atomic == 30_754_892_823
    assert points[-1].position.block_ordinal == 139
    # Own orders in an otherwise quiet market use the prior state, never a future trade.
    position, clock = position_and_clock
    markers = adapter._markers(position, points, clock)
    assert [m.kind for m in markers] == ["SIGNAL", "BUY", "SELL"]
    assert all(m.point.market_cap_atomic == 30_754_892_823 for m in markers)
    # Verify both outcome identity and instruction-free transaction coordinates.
    assert all(m.point.position.event_index is None for m in markers)


# Each corruption breaks a different proof needed for a trustworthy chart.
@pytest.mark.parametrize(
    "fault",
    ["no_creation", "duplicate_creation", "no_signal", "duplicate_signal", "signer", "wrong_pair"],
)
def test_missing_or_conflicting_history_is_not_a_chart(position_and_clock, fault):
    # Missing initialization is different from a missing leader signal.
    events = [base._launch(), replay._trade(1)]
    if fault == "no_creation":
        events.pop(0)
    elif fault == "duplicate_creation":
        events.insert(1, base._launch())
    # Signal identity is checked independently of mere token/venue membership.
    elif fault == "no_signal":
        events.pop()
    elif fault == "duplicate_signal":
        events.append(events[-1])
    # The correct venue does not authorize interpreting a different asset pair.
    elif fault == "wrong_pair":
        events[-1] = replace(events[-1], bought_asset_id=AssetId("OTHER"))

    # A projected actor mismatch cannot substitute payer/user for signing_wallet.
    # Replace only the actor projection to exercise the independent signer check.
    def projector(event):
        value = pump_market_cap_state(event)
        return replace(value, signing_wallet=AccountId("wrong")) if fault == "signer" else value

    with pytest.raises(ValueError):
        # The caller receives an error instead of a fabricated partial history.
        collect(position_and_clock, events, projector=projector)


@pytest.mark.parametrize(
    "quota",
    ["MAX_MARKET_CHART_EVENTS", "MAX_MARKET_CHART_POINTS", "deadline"],
    # Rows, output points and elapsed time impose independent hard ceilings.
)
def test_stream_limits_close_inputs_and_never_return_a_truncated_series(
    position_and_clock, monkeypatch, quota
):
    deadline = monotonic() - 1 if quota == "deadline" else monotonic() + 5
    # Quota failure is exercised while an iterator holds resources.
    if quota != "deadline":
        monkeypatch.setattr(adapter, quota, 1)
    with pytest.raises(MarketChartQueryError, match="MARKET_CHART_LIMIT_EXCEEDED"):
        collect(position_and_clock, (base._launch(), replay._trade(1)), deadline=deadline)


def test_metadata_limits_reject_before_constructing_replay_reader(monkeypatch):
    """Input metadata admission rejects before allocating a canonical replay reader."""
    import json

    # Metadata admission must complete before opening the historical clock.
    from io import BytesIO

    # A minimal committed-handle double proves pre-admission order, independent of replay math.
    closed = []
    manifest = {"distributions": [{"row_count": 50_001, "artifact_id": "1" * 64}]}
    handle = SimpleNamespace(
        descriptor=SimpleNamespace(kind=adapter.ArtifactKind.SNAPSHOT),
        # The byte stream emulates only manifest admission, not canonical artifact proof.
        open_binary=lambda _: BytesIO(json.dumps(manifest).encode()),
        close=lambda: closed.append(True),
    )
    # Opening another partition would be a bug once manifest row count exceeds the limit.
    repository = SimpleNamespace(open_committed=lambda _: handle)
    reader = adapter.LocalCopyMarketChartReader(repository, pump_market_cap_state, None)
    run = SimpleNamespace(resolved_spec=SimpleNamespace(snapshot_id="snapshot"))
    with ExitStack() as leases, pytest.raises(MarketChartQueryError, match="LIMIT"):
        reader._check_input_budget(run, leases)
    # Quota rejection closes the retained manifest lease.
    assert closed == [True]
    # Malformed manifests must fail as unavailable, not escape through an AttributeError.
    manifest = []
    with ExitStack() as leases, pytest.raises(ValueError, match="manifest"):
        reader._check_input_budget(run, leases)


# Even a schema-invalid manifest releases its handle.


def test_chart_reader_releases_admission_after_input_failure(monkeypatch):
    reader = adapter.LocalCopyMarketChartReader(None, pump_market_cap_state, None)

    # A storage failure must not poison the single-flight admission lock.
    def fail(*args):
        raise ValueError("unreadable snapshot")

    # An unsuccessful request must not leave every future chart permanently busy.
    monkeypatch.setattr(reader, "_check_input_budget", fail)
    with pytest.raises(ValueError, match="unreadable"):
        reader.read(None, None, None)
    assert reader._admission.acquire(blocking=False)
    # The next request must be able to acquire the slot after the exception.
    reader._admission.release()


def chart_fixture(position_and_clock):
    """A display fixture has actual filled coordinates but no claimed production artifact."""
    position, clock = position_and_clock
    points = collect(position_and_clock, (base._launch(), replay._trade(1)))
    return CopyMarketChart(
        ArtifactId("1" * 64),
        # Synthetic test IDs are not published artifacts or source evidence.
        position.roundtrip_id,
        SnapshotId("2" * 64),
        # The retained point/marker clocks share the position's immutable network and schema.
        position.intent.asset_id,
        position.intent.quote_asset_id,
        tuple(points),
        adapter._markers(position, points, clock),
        # Markers come from the same actual execution clock as the retained state points.
    )


def query_fixture(monkeypatch, position_and_clock, *, chart=None, events=2, failure=None):
    """A replaceable reader double records exact-key seeking and lease lifetime."""
    position, _ = position_and_clock
    result = chart or chart_fixture(position_and_clock)
    calls, lease = [], []

    class Summary:
        """Isolate query dispatch; real immutable summary construction is integration-tested."""

        comparison = SimpleNamespace(historical_event_count=events)

    # The unit spy isolates port orchestration from the already proven result codec.
    monkeypatch.setattr(query_module, "CopySummaryMetadata", Summary)
    manifest = SimpleNamespace(
        bounded_summary=Summary(), resolved_spec=SimpleNamespace(snapshot_id=SnapshotId("2" * 64))
    )

    # A page failure can be injected before result verification runs.
    def page(**kwargs):
        calls.append(kwargs)
        if failure:
            raise failure
        return RoundTripPage((position,), None)

    # Verification and chart reading must happen under the same authenticated run lease.
    reader = SimpleNamespace(
        manifest=manifest, roundtrips=page, verify=lambda: calls.append("verified")
    )

    # Track the lifetime of the exact authenticated run handle.
    @contextmanager
    def opened(artifact_id):
        lease.append(artifact_id)
        try:
            # Reader release is mandatory when any downstream operation raises.
            yield reader
        finally:
            lease.clear()

    # The historical port receives only the already selected immutable row.
    def read(artifact_id, manifest, record):
        assert lease == [artifact_id]
        assert record is position
        return result

    # These structural doubles implement only the two application ports under test.
    query = query_module.QueryCopyMarketChart(
        SimpleNamespace(open_exact=opened), SimpleNamespace(read=read)
    )
    return query, calls, manifest


# Exact-key seeking must never broaden into a scan of arbitrary tokens.
def test_query_seeks_one_exact_position_under_the_verified_run_lease(
    monkeypatch, position_and_clock
):
    query, calls, _ = query_fixture(monkeypatch, position_and_clock)
    position, _ = position_and_clock
    # Both operands of the selector are independently checked against the result.
    result = query.execute(
        ArtifactId("1" * 64), position.roundtrip_id, position.target_position.boundary_ordinal
    )
    assert result.position_id == position.roundtrip_id
    assert len(calls) == 2 and calls[1] == "verified"
    # The composite predecessor preserves exact UInt64 boundary precision and never uses OFFSET.
    assert calls[0]["limit"] == 1
    assert calls[0]["after"].target_boundary_ordinal == position.target_position.boundary_ordinal
    assert int(calls[0]["after"].roundtrip_id.hex, 16) + 1 == int(position.roundtrip_id.hex, 16)


# Attack each identity dimension while preserving a structurally valid chart.
@pytest.mark.parametrize("fault", ["run", "snapshot", "asset", "signal", "attempt", "count"])
def test_query_rejects_history_reader_identity_or_marker_substitution(
    monkeypatch, position_and_clock, fault
):
    chart = chart_fixture(position_and_clock)
    # Content IDs and the selected mint are separate binding invariants.
    changes = {
        "run": {"run_artifact_id": ArtifactId("3" * 64)},
        "snapshot": {"snapshot_id": SnapshotId("3" * 64)},
        "asset": {"asset_id": AssetId("OTHER")},
    }
    # Each substitution is structurally valid but belongs to the wrong source identity.
    if fault in changes:
        chart = replace(chart, **changes[fault])
    # A marker inside the history interval can still be the wrong recorded boundary.
    elif fault in {"signal", "attempt"}:
        index = 0 if fault == "signal" else 1
        marks = list(chart.markers)
        marks[index] = replace(marks[index], point=chart.points[0])
        chart = replace(chart, markers=tuple(marks))
    # Omitting an actual attempt is also an incomplete chart.
    else:
        chart = replace(chart, markers=chart.markers[:-1])
    # Errors expose only a stable safe code even when a storage adapter misbehaves.
    query, _, _ = query_fixture(monkeypatch, position_and_clock, chart=chart)
    position, _ = position_and_clock
    with pytest.raises(MarketChartQueryError, match="MARKET_CHART_UNAVAILABLE"):
        # All exact selector operands remain valid while the adapter output is corrupted.
        query.execute(
            ArtifactId("1" * 64),
            position.roundtrip_id,
            position.target_position.boundary_ordinal,
            # No raw identity mismatch detail may enter the public error message.
        )


# Large result families reject before page or history I/O.
def test_query_limits_and_redaction_prevent_unbounded_or_unsafe_reads(
    monkeypatch, position_and_clock
):
    position, _ = position_and_clock
    # Use the same valid key for both resource and corruption failure checks.
    operands = (
        ArtifactId("1" * 64),
        position.roundtrip_id,
        position.target_position.boundary_ordinal,
    )
    # The unbounded input count must block all lower-level calls.
    query, calls, _ = query_fixture(monkeypatch, position_and_clock, events=50_001)
    with pytest.raises(MarketChartQueryError, match="LIMIT"):
        query.execute(*operands)
    assert not calls
    # A corrupt missing field is translated; the browser receives no path or raw exception.
    query, _, _ = query_fixture(monkeypatch, position_and_clock, failure=KeyError("private-path"))
    with pytest.raises(MarketChartQueryError) as raised:
        query.execute(*operands)
    assert str(raised.value) == "MARKET_CHART_UNAVAILABLE"
    # A result from another strategy family has no selectable Copy Buy position.
    query, _, manifest = query_fixture(monkeypatch, position_and_clock)
    manifest.bounded_summary = object()
    with pytest.raises(MarketChartQueryError, match="COPY_POSITION_NOT_FOUND"):
        query.execute(*operands)


# A zero digest has no smaller same-boundary key.
def test_zero_digest_cursor_edges_preserve_exact_keyset_semantics():
    assert query_module._predecessor(0, ContentDigest("0" * 64)) is None
    before = query_module._predecessor(1, ContentDigest("0" * 64))
    assert before.target_boundary_ordinal == 0 and before.roundtrip_id == ContentDigest("f" * 64)
    # The largest boundary is UInt64; overflow cannot wrap into another signal.
    with pytest.raises(ValueError):
        query_module._predecessor(1 << 64, ContentDigest("1" * 64))


# Reuse the production HTTP middleware while substituting only the application query.
def api_fixture(monkeypatch, tmp_path, chart, *, failure=None, maximum=2 * 1024**2):
    from tests.unit.interfaces import test_api

    # Inject only the new read-only use case into the existing security/session test composition.
    calls = []
    constructor = test_api.ControlUseCases

    # Capture requests after validation so malformed selectors must not appear here.
    def execute(*args):
        calls.append(args)
        if failure:
            raise failure
        return chart

    # Keep the existing composition intact and inject only the new query port.
    def composition(**kwargs):
        return replace(
            constructor(**kwargs), query_copy_market_chart=SimpleNamespace(execute=execute)
        )

    # All HTTP validation and response sizing use the real FastAPI transport implementation.
    monkeypatch.setattr(test_api, "ControlUseCases", composition)
    return test_api._client(tmp_path, enforce_session=True, max_request_bytes=maximum), calls


# These transport assertions use the public URL and real Pydantic response models.
def test_chart_http_preserves_exact_units_and_rejects_untyped_selectors(
    monkeypatch, tmp_path, position_and_clock
):
    chart = chart_fixture(position_and_clock)
    client, calls = api_fixture(monkeypatch, tmp_path, chart)
    # The selector is an immutable row key, never a client-specified storage path.
    path = (
        f"/api/v1/run-artifacts/{chart.run_artifact_id.hex}/"
        f"copy-positions/{chart.position_id.hex}/market-cap"
    )
    key = str(chart.markers[0].point.position.boundary_ordinal)
    # Packaged navigation establishes the same-origin session and serves the new assets.
    response = client.get("/copy-results")
    assert response.status_code == 200 and "copy-market-chart.js" in response.text
    assert "unsafe-inline" not in response.headers["content-security-policy"]
    assert client.get("/static/copy-market-chart.js").status_code == 200
    response = client.get(path, params={"signal_boundary_ordinal": key})
    # Nanoseconds, market cap and boundary ordinal remain strings across the HTTP boundary.
    assert response.status_code == 200
    point = response.json()["markers"][0]["point"]
    assert point["position"]["boundary_ordinal"] == key
    assert point["market_cap_atomic"] == "27958993476"
    assert len(calls) == 1
    # Malformed/overflow/ambiguous selectors fail before touching any artifact reader.
    for suffix in (
        "",
        "?signal_boundary_ordinal=01",
        "?signal_boundary_ordinal=18446744073709551616",
        f"?signal_boundary_ordinal={key}&sql=select",
        # Duplicate scalar parameters are ambiguous and must not be resolved by precedence.
        f"?signal_boundary_ordinal={key}&signal_boundary_ordinal={key}",
    ):
        assert client.get(path + suffix).status_code == 422
    assert len(calls) == 1
    # A valid session cookie does not bypass Host validation.
    assert (
        client.get(
            path, params={"signal_boundary_ordinal": key}, headers={"Host": "evil.invalid"}
        ).status_code
        == 400
        # Unexpected hosts are rejected before routing to the query.
    )


# Every supported failure has a stable status and safe response vocabulary.
@pytest.mark.parametrize(
    "code,status",
    [
        ("COPY_POSITION_NOT_FOUND", 404),
        ("MARKET_CHART_UNAVAILABLE", 404),
        # Quota and contention are distinct from missing data.
        ("MARKET_CHART_LIMIT_EXCEEDED", 422),
        ("MARKET_CHART_BUSY", 503),
    ],
)
def test_chart_http_returns_safe_typed_errors(
    # Test the same session and route for every closed failure code.
    monkeypatch,
    tmp_path,
    position_and_clock,
    code,
    status,
    # Error classification changes without changing the selected historical position.
):
    chart = chart_fixture(position_and_clock)
    client, _ = api_fixture(monkeypatch, tmp_path, chart, failure=MarketChartQueryError(code))
    client.get("/copy-results")
    # Only the exact row key reaches the failed use case.
    path = (
        f"/api/v1/run-artifacts/{chart.run_artifact_id.hex}/"
        f"copy-positions/{chart.position_id.hex}/market-cap"
    )
    # The route maps typed domain output only after selector validation succeeds.
    response = client.get(
        path,
        params={"signal_boundary_ordinal": str(chart.markers[0].point.position.boundary_ordinal)},
    )
    # Safe errors contain neither tracebacks nor filesystem/source details.
    assert response.status_code == status and response.json()["code"] == code
    assert set(response.json()) == {"code", "message"}


# Even a valid chart must respect the configured transport byte ceiling.
def test_chart_http_response_size_remains_bounded(monkeypatch, tmp_path, position_and_clock):
    """Response admission cannot be bypassed by an otherwise valid chart body."""
    chart = chart_fixture(position_and_clock)
    client, _ = api_fixture(monkeypatch, tmp_path, chart, maximum=1024)
    client.get("/copy-results")
    # The caller cannot request a looser size limit through the exact row selector.
    path = (
        f"/api/v1/run-artifacts/{chart.run_artifact_id.hex}/"
        f"copy-positions/{chart.position_id.hex}/market-cap"
    )
    # The response-size guard runs after typed projection and before sending bytes.
    response = client.get(
        path,
        params={"signal_boundary_ordinal": str(chart.markers[0].point.position.boundary_ordinal)},
    )
    assert response.status_code == 413
