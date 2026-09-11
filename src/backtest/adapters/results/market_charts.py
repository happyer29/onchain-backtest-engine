"""Quota-limited canonical history reads for one recorded Copy Buy position."""

import json
from bisect import bisect_right
from collections.abc import Callable, Generator
from contextlib import ExitStack
from dataclasses import replace

# Query timing and single-flight admission are operational, never replay inputs.
from threading import Lock
from time import monotonic
from typing import cast, overload

import pyarrow.parquet as pq

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.adapters.columnar.arrow import CanonicalParquetReplaySource
from backtest.adapters.columnar.arrow.canonical import _schema

# The protocol projector is injected by bootstrap; storage knows no Pump reserve formula.
from backtest.application.code_bundles import PinnedCodeBundleSet
from backtest.application.market_charts import (
    MAX_MARKET_CHART_EVENTS,
    MAX_MARKET_CHART_POINTS,
    MAX_MARKET_CHART_SELECTED_EVENTS,
    CopyChartMarker,
    # Display records are application-owned; this adapter supplies their verified history.
    CopyMarketChart,
    MarketCapPoint,
    MarketCapState,
    MarketChartQueryError,
    StrategyMarketChart,
)

# Exact run and snapshot descriptors are the authority for input selection.
from backtest.application.models import ArtifactKind
from backtest.application.run_results import SuccessfulRunManifest
from backtest.domain.chain import ChainPosition
from backtest.domain.identifiers import ArtifactId, AssetId, ContentDigest, VenueId
from backtest.domain.market_events import (
    # Only these market event kinds can alter the selected curve display.
    CanonicalEvent,
    EventKind,
    TokenLaunchEvent,
    VenueLifecycleEvent,
    VenueTradeEvent,
)
from backtest.domain.roundtrips import RoundTripRecord

# Existing frozen records and compact clock supply actual attempt positions and time.
from backtest.engine.copytrading_results import CopyPositionRecord
from backtest.engine.transaction_clock import CompactTransactionClock

# Operational caps prevent an HTTP request from becoming an unconstrained scan.
MAX_CHART_PARTITIONS = 128
MAX_CHART_INPUT_BYTES = 1024**3
MAX_CHART_READ_SECONDS = 10.0
# Compact clock construction also has a separate bound on its Python coordinate arrays.
MAX_CHART_CLOCK_ROWS = 500_000


class LocalCopyMarketChartReader:
    """One bounded post-run scan at a time; no strategy, writes, or source connection."""

    # Bootstrap supplies the exact artifact repository and versioned protocol projector.
    def __init__(
        self,
        artifacts: LocalArtifactRepository,
        projector: Callable[[CanonicalEvent], MarketCapState],
        build_tools: PinnedCodeBundleSet,
        # Pinned build tools verify canonical storage without discovering arbitrary code.
    ) -> None:
        self._artifacts, self._projector = artifacts, projector
        self._build_tools = build_tools
        self._admission = Lock()

    @overload
    def read(
        self, artifact_id: ArtifactId, manifest: SuccessfulRunManifest, position: CopyPositionRecord
    ) -> CopyMarketChart: ...

    @overload
    def read(
        self, artifact_id: ArtifactId, manifest: SuccessfulRunManifest, position: RoundTripRecord
    ) -> StrategyMarketChart: ...

    @overload
    def read(
        self,
        artifact_id: ArtifactId,
        manifest: SuccessfulRunManifest,
        position: CopyPositionRecord | RoundTripRecord,
    ) -> StrategyMarketChart: ...

    # A chart read is selected through an already authenticated result row.
    def read(
        self,
        artifact_id: ArtifactId,
        manifest: SuccessfulRunManifest,
        position: CopyPositionRecord | RoundTripRecord,
        # No caller-supplied source range or filesystem path enters the reader.
    ) -> StrategyMarketChart:
        """Resource rejection is explicit instead of accumulating concurrent scans."""
        if not self._admission.acquire(blocking=False):
            raise MarketChartQueryError("MARKET_CHART_BUSY")
        try:
            deadline = monotonic() + MAX_CHART_READ_SECONDS
            with ExitStack() as leases:
                # Quota prechecks run while their exact source refs remain leased.
                self._check_input_budget(manifest, leases)
                return self._read_history(artifact_id, manifest, position, deadline)
        finally:
            self._admission.release()

    # Metadata admission happens before the potentially larger compact clock is loaded.
    def _check_input_budget(self, run: SuccessfulRunManifest, leases: ExitStack) -> None:
        """Reject oversized input metadata before constructing a replay reader or clock."""
        handle = self._artifacts.open_committed(run.resolved_spec.snapshot_id)
        leases.callback(handle.close)
        if handle.descriptor.kind is not ArtifactKind.SNAPSHOT:
            raise ValueError("chart input is not a snapshot")
        # This is a quota precheck; the canonical reader subsequently validates the full schema.
        with handle.open_binary("manifest.json") as stream:
            payload = stream.read(1024**2 + 1)
        if len(payload) > 1024**2:
            raise MarketChartQueryError("MARKET_CHART_LIMIT_EXCEEDED")
        document = json.loads(payload)
        # Malformed JSON shape is an unavailable input, never an empty dataset.
        if not isinstance(document, dict):
            raise ValueError("invalid chart snapshot manifest")
        refs = document.get("distributions")
        # Both reference count and actual committed payload bytes have hard ceilings.
        if not isinstance(refs, list):
            raise ValueError("invalid chart distribution references")
        if len(refs) > MAX_CHART_PARTITIONS:
            raise MarketChartQueryError("MARKET_CHART_LIMIT_EXCEEDED")
        rows, size, clock_rows = 0, 0, 0
        # Accumulate every referenced stream before admitting canonical replay reads.
        for ref in refs:
            if not isinstance(ref, dict) or type(ref.get("row_count")) is not int:
                raise ValueError("invalid chart input reference")
            # Count every canonical stream, including the compact block clock.
            rows += ref["row_count"]
            if ref["row_count"] < 0 or rows > MAX_MARKET_CHART_EVENTS:
                raise MarketChartQueryError("MARKET_CHART_LIMIT_EXCEEDED")
            # A highly compressed block-only snapshot cannot exhaust the controller's RAM.
            if ref.get("event_kind") == "BLOCK":
                clock_rows += ref["row_count"]
            if clock_rows > MAX_CHART_CLOCK_ROWS:
                raise MarketChartQueryError("MARKET_CHART_LIMIT_EXCEEDED")
            artifact = self._artifacts.open_committed(ArtifactId(ref["artifact_id"]))
            leases.callback(artifact.close)
            # Fixed names come from the canonical storage contract, never from the client.
            with artifact.open_binary("events.parquet") as stream:
                stream.seek(0, 2)
                size += stream.tell()
            if size > MAX_CHART_INPUT_BYTES:
                raise MarketChartQueryError("MARKET_CHART_LIMIT_EXCEEDED")
            # Physical row counts and schemas must agree even for streams excluded by the filter.
            with artifact.open_binary("events.parquet") as stream:
                parquet = pq.ParquetFile(stream)
                if parquet.metadata.num_rows != ref["row_count"]:
                    raise ValueError("chart input row count mismatch")
                # Block-clock schema is verified here before its compact projection is loaded.
                expected_schema = _schema(EventKind[ref["event_kind"]])
                if not parquet.schema_arrow.equals(expected_schema, check_metadata=True):
                    raise ValueError("chart input schema mismatch")

    # The verified run is the sole authority for selecting history dependencies.
    def _read_history(
        self,
        artifact_id: ArtifactId,
        manifest: SuccessfulRunManifest,
        position: CopyPositionRecord | RoundTripRecord,
        # The same operational deadline covers metadata and streaming work.
        deadline: float,
    ) -> StrategyMarketChart:
        """The chart always names its canonical snapshot, regardless of the run's backend."""
        spec = manifest.resolved_spec
        source = CanonicalParquetReplaySource(
            self._artifacts,
            spec.snapshot_id,
            duckdb_memory_limit_mb=128,
            # One small batch and one worker keep this interactive projection bounded.
            threads=1,
            reader_batch_rows=256,
            reader_readahead=1,
            build_tools=self._build_tools,
        )
        # Reusing a matching ID string cannot substitute for source-manifest verification.
        if (
            source.dataset_revision_id != spec.dataset_revision_id
            or source.logical_content_hash != spec.logical_content_hash
            or source.network_id != spec.network_id
            or source.position_schema_id != spec.position_schema_id
            # Replay semantics must match in addition to dataset and chain identities.
            or source.replay_semantics_id != spec.replay_semantics_id
        ):
            raise ValueError("chart snapshot differs from resolved run")
        # The successful run pins this authenticated input closure; only its venue is decoded.
        clock = source.transaction_clock()
        points = self._collect_points(source, position, clock, deadline)
        markers = _markers(position, points, clock)
        # Attach the input provenance to the bounded output rather than persisting a new artifact.
        chart_type = (
            CopyMarketChart if isinstance(position, CopyPositionRecord) else StrategyMarketChart
        )
        return chart_type(
            artifact_id,
            position.roundtrip_id,
            spec.snapshot_id,
            _asset(position),
            # The ordinate unit comes from the recorded pair; it is never guessed.
            _quote_asset(position),
            tuple(points),
            markers,
        )

    # Grouping is performed over verified chronological events, not sorted output quotes.
    def _collect_points(
        self,
        source: CanonicalParquetReplaySource,
        position: CopyPositionRecord | RoundTripRecord,
        clock: CompactTransactionClock,
        # The source clock is read-only and never fabricated for display.
        deadline: float,
    ) -> list[MarketCapPoint]:
        """Retain only the selected venue's final state at each whole transaction."""
        points: list[MarketCapPoint] = []
        signal_found = False
        seen_creation = False

        # The caller's deadline includes compact-clock construction and metadata admission.
        def check_budget() -> None:
            """Even empty native filter batches remain subject to the same query deadline."""
            if monotonic() > deadline:
                raise MarketChartQueryError("MARKET_CHART_LIMIT_EXCEEDED")

        # This projection cannot be substituted for full execution replay verification.
        events = cast(
            Generator[CanonicalEvent],
            source.events_for_venue(_venue(position), check_budget=check_budget),
        )
        try:
            for count, event in enumerate(events, 1):
                # Time and row quotas bound query work without altering run semantics.
                if count > MAX_MARKET_CHART_SELECTED_EVENTS or monotonic() > deadline:
                    raise MarketChartQueryError("MARKET_CHART_LIMIT_EXCEEDED")
                if not _belongs_to_position(event, position):
                    continue
                projected = self._projector(event)
                # Initialization must come from the actual retained creation of this mint.
                if isinstance(event, TokenLaunchEvent):
                    if seen_creation or event.asset_id != _asset(position):
                        raise ValueError("ambiguous chart creation")
                    seen_creation = True
                # A retained trade without its initialization is incomplete history.
                elif not seen_creation:
                    raise ValueError("chart history has no initial creation")
                # Bind the selected signal to its exact source event, signer and direction.
                if event.envelope.canonical_event_id == _signal_id(position):
                    _verify_signal(event, projected, position, signal_found)
                    signal_found = True
                # Only the final state of a whole transaction is exposed to the browser.
                boundary = replace(event.envelope.position, event_index=None)
                point = MarketCapPoint(
                    boundary,
                    clock.block_time_for_position(boundary),
                    projected.market_cap_atomic,
                    # Lifecycle remains explicit even when the terminal market cap is nonzero.
                    projected.lifecycle,
                )
                # Multiple instructions at one boundary expose only the terminal group state.
                if points and points[-1].position.boundary_ordinal == boundary.boundary_ordinal:
                    points[-1] = point
                else:
                    points.append(point)
                # Reserve one point for the proven quiet-market coverage boundary.
                if len(points) >= MAX_MARKET_CHART_POINTS:
                    raise MarketChartQueryError("MARKET_CHART_LIMIT_EXCEEDED")
        finally:
            events.close()
        # No empty, incomplete or unsourced series is a valid chart response.
        if not signal_found or not points:
            raise ValueError("recorded signal is absent from chart history")
        end = _last_transaction(clock)
        # Carry the last state to the proven clock end so timer exits can be located.
        if end.boundary_ordinal > points[-1].position.boundary_ordinal:
            points.append(
                replace(points[-1], position=end, block_time_ns=clock.block_time_for_position(end))
            )
        return points


# Unrelated venues do not require protocol decoding or per-token allocation.
def _belongs_to_position(
    event: CanonicalEvent, position: CopyPositionRecord | RoundTripRecord
) -> bool:
    """Venue and asset must agree; unrelated market actors are still included for this venue."""
    if not isinstance(event, (TokenLaunchEvent, VenueTradeEvent, VenueLifecycleEvent)):
        return False
    if event.venue_id != _venue(position):
        return False
    # A wrong pair must not be decoded using a coincidentally matching venue identifier.
    if isinstance(event, VenueTradeEvent):
        expected = {_asset(position), _quote_asset(position)}
        if {event.sold_asset_id, event.bought_asset_id} != expected:
            raise ValueError("chart trade has the wrong asset pair")
    return True


# A matching venue alone does not authenticate the leader signal.
def _verify_signal(
    event: CanonicalEvent,
    projected: MarketCapState,
    position: CopyPositionRecord | RoundTripRecord,
    already_found: bool,
    # Duplicate canonical signal identity is a query failure, not deduplication.
) -> None:
    """The signal is the original leader BUY, not a payer or another trade in its group."""
    if isinstance(position, RoundTripRecord):
        if already_found or not isinstance(event, TokenLaunchEvent):
            raise ValueError("ambiguous creation signal")
        # The stored developer is creation ownership, not payer or transaction signer.
        if (
            event.envelope.position != position.target_position
            or event.developer_id != position.developer_id
            or event.asset_id != position.asset_id
            or event.quote_asset_id != position.quote_asset_id
        ):
            raise ValueError("chart creation binding mismatch")
        return
    signal = position.intent.signal
    if already_found or not isinstance(event, VenueTradeEvent):
        raise ValueError("ambiguous chart signal")
    # Actor and coordinate checks bind the chart to the exact consumed source BUY.
    if (
        event.envelope.position != signal.position
        or projected.signing_wallet != signal.signing_wallet
    ):
        raise ValueError("chart signer or signal position mismatch")
    # Direction is necessary even though the selected token pair already matches.
    if event.bought_asset_id != signal.asset_id or event.sold_asset_id != signal.quote_asset_id:
        raise ValueError("chart source signal is not the recorded BUY")


def _last_transaction(clock: CompactTransactionClock) -> ChainPosition:
    """Produced empty blocks and skipped slots do not become invented execution boundaries."""
    for index in range(len(clock.block_ordinals) - 1, -1, -1):
        count = clock.transaction_counts[index]
        if count:
            return ChainPosition(
                clock.network_id,
                # Use the last real transaction; empty blocks never invent a landing coordinate.
                clock.position_schema_id,
                clock.block_ordinals[index],
                count - 1,
                None,
            )
    # A clock with no transactions cannot host the recorded copy signal.
    raise ValueError("chart clock has no transaction")


# Attempt markers use their actual effective coordinates independently of trade density.
def _markers(
    position: CopyPositionRecord | RoundTripRecord,
    points: list[MarketCapPoint],
    clock: CompactTransactionClock,
) -> tuple[CopyChartMarker, ...]:
    """As-of historical marginal market cap is separate from the actual execution quote."""
    keys = [point.position.boundary_ordinal for point in points]

    def at(coordinate: ChainPosition) -> MarketCapPoint:
        """Orders can land between market trades; never look forward to the next price."""
        boundary = replace(coordinate, event_index=None)
        index = bisect_right(keys, boundary.boundary_ordinal) - 1
        if index < 0:
            raise ValueError("chart marker precedes initialization")
        # A marker retains its own clock time while using only a prior historical state.
        return replace(
            points[index], position=boundary, block_time_ns=clock.block_time_for_position(boundary)
        )

    # A signal marks the entire historical transaction, not an intermediate callback.
    result = [CopyChartMarker("SIGNAL", "OBSERVED_SOURCE", None, at(position.target_position))]
    if isinstance(position, RoundTripRecord):
        for number, leg in enumerate((position.buy, position.sell)):
            if leg is None:
                continue
            coordinate = leg.landing_position or leg.decision_position
            # Suppressed targets have no own-order marker; rejects remain at decision time.
            status = (
                "FILLED"
                if leg.failure_code is None
                else "FAILED"
                if leg.landing_position
                else "REJECTED"
            )
            result.append(
                CopyChartMarker(leg.side.value, status, number, at(coordinate), leg.failure_code)
            )
        return tuple(result)
    for attempt in position.attempts:
        coordinate = attempt.landed_at or attempt.decision
        result.append(
            CopyChartMarker(
                # Attempt zero is the entry; subsequent ordinals preserve sell retry order.
                "BUY" if attempt.number == 0 else "SELL",
                attempt.status.value,
                attempt.number,
                at(coordinate),
                attempt.failure_code,
                # Marker construction validates failed-versus-filled lifecycle semantics.
            )
        )
    return tuple(result)


def _asset(position: CopyPositionRecord | RoundTripRecord) -> AssetId:
    """The result family supplies its own immutable pair identity."""
    return position.asset_id if isinstance(position, RoundTripRecord) else position.intent.asset_id


def _quote_asset(position: CopyPositionRecord | RoundTripRecord) -> AssetId:
    """No implicit SOL substitution is allowed at the selector boundary."""
    return (
        position.quote_asset_id
        if isinstance(position, RoundTripRecord)
        else position.intent.quote_asset_id
    )


def _venue(position: CopyPositionRecord | RoundTripRecord) -> VenueId:
    """Venue scope is fixed by the recorded result, never by a client path."""
    return position.venue_id if isinstance(position, RoundTripRecord) else position.intent.venue_id


def _signal_id(position: CopyPositionRecord | RoundTripRecord) -> ContentDigest:
    """Creation and copy BUY signals retain their existing distinct event identities."""
    return (
        position.target_event_id
        if isinstance(position, RoundTripRecord)
        else position.intent.signal.event_id
    )
