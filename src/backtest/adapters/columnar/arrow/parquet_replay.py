"""Readable reference replay directly from committed canonical Parquet v3."""

from __future__ import annotations

import hashlib
import heapq
import json
from bisect import bisect_left

# Import abc at the visible module dependency boundary.
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from itertools import islice, pairwise
from pathlib import Path
from typing import Any, Protocol, cast

# Import duckdb at the visible module dependency boundary.
import duckdb
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.adapters.columnar.arrow.canonical import (
    CanonicalDataError,
    # Include schema so the canonical dependency remains explicit.
    _schema,
    _schema_id,
    canonical_writer_bundle_id,
)
from backtest.application.build_tool_roles import (
    # Include canonical projector role so the build tool roles dependency remains
    # explicit.
    CANONICAL_PROJECTOR_ROLE,
    CANONICAL_WRITER_ROLE,
)
from backtest.application.canonical_data import (
    CanonicalDistributionRef,
    # Include effective source boundary so the canonical data dependency remains explicit.
    EffectiveSourceBoundary,
    ValidationStatus,
    dataset_spec_from_snapshot_document,
    decision_range_from_snapshot_document,
    effective_source_boundaries_from_snapshot_document,
    # Close the canonical data import after its required symbols are visible.
)
from backtest.application.code_bundles import PinnedCodeBundleIdentity, PinnedCodeBundleSet
from backtest.application.errors import ReprepareRequiredError
from backtest.application.models import ArtifactKind, DatasetShard, DatasetSpec
from backtest.application.replay_packs import ReplaySemanticsManifest

# Import event hashing at the visible module dependency boundary.
from backtest.domain.event_hashing import canonical_event_digest
from backtest.domain.fidelity import OrderingFidelity
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import (
    AccountId,
    # Include artifact id so the identifiers dependency remains explicit.
    ArtifactId,
    AssetId,
    BundleId,
    CapabilityId,
    ContentDigest,
    # Include dataset revision id so the identifiers dependency remains explicit.
    DatasetRevisionId,
    FeeComponentId,
    LogicalContentHash,
    NetworkId,
    PositionSchemaId,
    # Include protocol payload schema id so the identifiers dependency remains explicit.
    ProtocolPayloadSchemaId,
    SnapshotId,
    SourceId,
    VenueId,
)

# Import market events at the visible module dependency boundary.
from backtest.domain.market_events import (
    BlockEvent,
    CanonicalEvent,
    ChainPosition,
    EventEnvelope,
    # Include event kind so the market events dependency remains explicit.
    EventKind,
    FeeComponent,
    TokenLaunchEvent,
    VenueLifecycleEvent,
    VenueLifecycleKind,
    # Include venue trade event so the market events dependency remains explicit.
    VenueTradeEvent,
    canonical_event_sort_key,
)
from backtest.domain.time import BlockRange
from backtest.engine.replay import ReplayBoundary

# Import transaction clock at the visible module dependency boundary.
from backtest.engine.transaction_clock import CompactTransactionClock


# Keep the local handle contract and validation rules together.
class _LocalHandle(Protocol):
    @property
    def descriptor(self) -> Any: ...

    def local_path(self, relative_name: str) -> Path: ...

    def open_binary(self, relative_name: str) -> Any: ...

    # Define local handle close as one focused operation with an explicit boundary.
    def close(self) -> None: ...


class CanonicalParquetReplaySource:
    """Verified multi-partition reader for reference and one-off runs."""

    def __init__(
        self,
        artifacts: LocalArtifactRepository,
        snapshot_id: SnapshotId,
        *,
        # Keep the duckdb memory limit mb input explicit in the init contract.
        duckdb_memory_limit_mb: int = 1_024,
        threads: int = 1,
        reader_batch_rows: int = 65_536,
        reader_readahead: int = 1,
        expected_projector_bundle_id: BundleId | None = None,
        # Keep the build tools input explicit in the init contract.
        build_tools: PinnedCodeBundleSet | None = None,
    ) -> None:
        # Execute the canonical parquet replay source init workflow in explicit,
        # reviewable steps.
        if (
            min(
                duckdb_memory_limit_mb,
                threads,
                reader_batch_rows,
                # Pass reader readahead explicitly so min receives a reviewable duckdb
                # memory limit mb and threads input in canonical parquet replay source
                # init.
                reader_readahead,
            )
            <= 0
        ):
            raise ValueError("reader limits must be positive")
        # Assemble self artifacts once so the canonical parquet replay source init
        # workflow shares one value.
        self._artifacts = artifacts
        self._snapshot_id = snapshot_id
        self._memory_limit_mb = duckdb_memory_limit_mb
        self._threads = threads
        self._reader_batch_rows = reader_batch_rows
        # Assemble self reader readahead once so the canonical parquet replay source init
        # workflow shares one value.
        self._reader_readahead = reader_readahead
        self._build_tools = build_tools or _unit_canonical_reader_tools()
        self._writer_bundle_id = self._build_tools.require_current(CANONICAL_WRITER_ROLE)
        if expected_projector_bundle_id is not None:
            self._build_tools.require_current(CANONICAL_PROJECTOR_ROLE)

        # Assemble handle once so the canonical parquet replay source init workflow shares
        # one value.
        handle = cast(_LocalHandle, artifacts.open_committed(snapshot_id))
        try:
            # Perform the protected canonical parquet replay source init operation before
            # explicit failure handling.
            if handle.descriptor.kind is not ArtifactKind.SNAPSHOT:
                raise CanonicalDataError("requested artifact is not a canonical snapshot")
            if handle.descriptor.artifact_id.hex != snapshot_id.hex:
                raise CanonicalDataError("canonical snapshot descriptor identity mismatch")
            manifest = _canonical_json_object(handle, "snapshot manifest")
            # Assemble input ids once so the canonical parquet replay source init workflow
            # shares one value.
            input_ids = handle.descriptor.input_artifact_ids
        finally:
            handle.close()
        self._manifest = _validate_snapshot_manifest(
            manifest,
            # Pass input ids explicitly so _validate_snapshot_manifest receives a
            # reviewable manifest and input ids input in canonical parquet replay source
            # init.
            input_ids,
            expected_projector_bundle_id=expected_projector_bundle_id,
        )
        self._projector_bundle_id = BundleId(cast(str, self._manifest["projector_bundle_id"]))
        self._network_id = NetworkId(cast(str, self._manifest["network_id"]))
        # Assemble self position schema id once so the canonical parquet replay source
        # init workflow shares one value.
        self._position_schema_id = PositionSchemaId(cast(str, self._manifest["position_schema_id"]))
        self._dataset_spec = dataset_spec_from_snapshot_document(self._manifest)
        self._decision_range = decision_range_from_snapshot_document(self._manifest)
        self._source_boundaries = effective_source_boundaries_from_snapshot_document(self._manifest)
        self._distribution_ids = tuple(
            # Keep the artifact id and cast ArtifactId step visible while building self.
            # distribution ids.
            ArtifactId(cast(str, item["artifact_id"]))
            for item in cast(list[dict[str, object]], self._manifest["distributions"])
        )
        self._dataset_revision_id = DatasetRevisionId(
            cast(str, self._manifest["dataset_revision_id"])
            # Complete DatasetRevisionId only after its dataset revision id and manifest
            # inputs are visible in canonical parquet replay source init.
        )
        self._logical_content_hash = LogicalContentHash(
            cast(str, self._manifest["logical_content_hash"])
        )
        self._replay_semantics_id = ReplaySemanticsManifest.canonical_v3().replay_semantics_id
        # Invoke _validate_distribution_closure as a visible step within the canonical
        # parquet replay source init workflow.
        self._validate_distribution_closure()
        self._transaction_clock = self._load_transaction_clock()

    @property
    def dataset_revision_id(self) -> DatasetRevisionId:
        return self._dataset_revision_id

    # Apply property semantics to the following canonical parquet replay source logical
    # content hash contract.
    @property
    def logical_content_hash(self) -> LogicalContentHash:
        return self._logical_content_hash

    @property
    def replay_semantics_id(self) -> ContentDigest:
        # Return the completed canonical parquet replay source replay semantics id result
        # without a hidden fallback.
        return self._replay_semantics_id

    @property
    def network_id(self) -> NetworkId:
        return self._network_id

    @property
    # Define canonical parquet replay source position schema id as one focused operation
    # with an explicit boundary.
    def position_schema_id(self) -> PositionSchemaId:
        return self._position_schema_id

    @property
    def dataset_spec(self) -> DatasetSpec:
        return self._dataset_spec

    # Apply property semantics to the following canonical parquet replay source decision
    # range contract.
    @property
    def decision_range(self) -> BlockRange:
        return self._decision_range

    @property
    def source_boundaries(self) -> tuple[EffectiveSourceBoundary, ...]:
        # Return the completed canonical parquet replay source source boundaries result
        # without a hidden fallback.
        return self._source_boundaries

    def transaction_clock(self) -> CompactTransactionClock:
        return self._transaction_clock

    def boundaries(self) -> tuple[ReplayBoundary, ...]:
        # Execute the canonical parquet replay source boundaries workflow in explicit,
        # reviewable steps.
        with ExitStack() as stack:
            # Keep exit stack active only for the bounded canonical parquet replay source
            # boundaries operation.
            paths = self._open_distribution_paths(stack)
            connection = stack.enter_context(duckdb.connect())
            _configure_duckdb(connection, self._memory_limit_mb, self._threads)
            rows = (
                connection.read_parquet(paths, union_by_name=True)
                # Pass project explicitly so project receives a reviewable boundary
                # ordinal, block ordinal input in canonical parquet replay source
                # boundaries.
                .project("boundary_ordinal, block_ordinal")
                .distinct()
                .order("boundary_ordinal, block_ordinal")
                .fetchall()
            )
        # Assemble boundaries once so the canonical parquet replay source boundaries
        # workflow shares one value.
        boundaries = tuple(
            ReplayBoundary(
                network_id=self._network_id,
                position_schema_id=self._position_schema_id,
                boundary_ordinal=int(row[0]),
                # Keep the row int step visible while building boundaries.
                block_ordinal=int(row[1]),
            )
            for row in rows
        )
        if not boundaries:
            # Fail the canonical parquet replay source boundaries path with
            # CanonicalDataError for canonical snapshot has no replay boundaries when
            # boundaries is true; do not continue ambiguously.
            raise CanonicalDataError("canonical snapshot has no replay boundaries")
        if len({item.boundary_ordinal for item in boundaries}) != len(boundaries):
            raise CanonicalDataError("one boundary ordinal maps to multiple chain blocks")
        return boundaries

    def events(self) -> Iterator[CanonicalEvent]:
        # Execute the canonical parquet replay source events workflow in explicit,
        # reviewable steps.
        with ExitStack() as stack:
            # Keep exit stack active only for the bounded canonical parquet replay source
            # events operation.
            # Chain physical shards before the global merge. Priming is therefore
            # bounded by capability count rather than snapshot shard count.
            iterators = [
                self._capability_events(stack, group)
                for group in self._capability_distribution_groups()
            ]

            heap: list[tuple[tuple[str, str, int, str, int, str], int, CanonicalEvent, bytes]] = []
            for index, iterator in enumerate(iterators):
                # Process enumerate(iterators) inside the bounded canonical parquet replay
                # source events loop.
                try:
                    event, stored_digest = next(iterator)
                except StopIteration:
                    continue
                heapq.heappush(heap, (canonical_event_sort_key(event), index, event, stored_digest))

            # Assemble stream digest once so the canonical parquet replay source events
            # workflow shares one value.
            stream_digest = hashlib.sha256(b"backtest.canonical-logical-stream.v3\x00")
            while heap:
                # Keep the heap loop body bounded within canonical parquet replay source
                # events.
                _, index, event, stored_digest = heapq.heappop(heap)
                recomputed = canonical_event_digest(event)
                if recomputed.hex != stored_digest.hex():
                    raise CanonicalDataError("canonical row semantic digest mismatch")
                if isinstance(event, BlockEvent):
                    # Handle the canonical parquet replay source events isinstance(event,
                    # BlockEvent) branch as a distinct logical block.
                    clock_index = _clock_row(self._transaction_clock, event.envelope.position)
                    if (
                        event.block_time_ns != self._transaction_clock.block_time_ns[clock_index]
                        or event.tx_count != self._transaction_clock.transaction_counts[clock_index]
                    ):
                        # Handle the canonical parquet replay source events block time ns,
                        # tx count and event condition as a distinct block.
                        raise CanonicalDataError(
                            "block event differs from compact transaction clock"
                        )
                else:
                    self._transaction_clock.require_position(event.envelope.position)
                # Invoke update for stored digest as a visible canonical parquet replay
                # source events step.
                stream_digest.update(stored_digest)
                yield event
                try:
                    next_event, next_digest = next(iterators[index])
                except StopIteration:
                    # Keep the continue step explicit within the canonical parquet replay
                    # source events workflow.
                    continue
                heapq.heappush(
                    heap,
                    (
                        canonical_event_sort_key(next_event),
                        # Pass index explicitly so heappush receives a reviewable
                        # canonical event sort key and heap input in canonical parquet
                        # replay source events.
                        index,
                        next_event,
                        next_digest,
                    ),
                )
            if stream_digest.hexdigest() != self._logical_content_hash.hex:
                raise CanonicalDataError("snapshot logical event stream hash mismatch")

    def events_for_venue(
        self, venue_id: VenueId, *, check_budget: Callable[[], None]
    ) -> Iterator[CanonicalEvent]:
        """Project one venue from authenticated inputs; this is not an execution replay."""
        with ExitStack() as stack:
            # Merge capability shards in their canonical order without decoding other venues.
            streams = [
                self._venue_events(stack, group, venue_id, check_budget)
                for group in self._capability_distribution_groups()
            ]
            previous = None
            # A filtered projection has no claim to the whole snapshot's logical stream hash.
            for event, stored_digest in heapq.merge(
                *streams, key=lambda item: canonical_event_sort_key(item[0])
            ):
                check_budget()
                key = canonical_event_sort_key(event)
                # Revalidate selected semantics and order before any price reaches the caller.
                if previous is not None and key <= previous:
                    raise CanonicalDataError("selected market history order is invalid")
                if canonical_event_digest(event).hex != stored_digest.hex():
                    raise CanonicalDataError("canonical row semantic digest mismatch")
                # Historical coordinates must exist in the exact retained all-transaction clock.
                self._transaction_clock.require_position(event.envelope.position)
                previous = key
                yield event
            check_budget()

    # Filtering is confined to this display path; the execution iterator above stays unchanged.
    def _venue_events(
        self,
        stack: ExitStack,
        distributions: tuple[tuple[ArtifactId, EffectiveSourceBoundary, dict[str, object]], ...],
        # The selector originates from a verified stored result, not arbitrary browser SQL.
        venue_id: VenueId,
        check_budget: Callable[[], None],
    ) -> Iterator[tuple[CanonicalEvent, bytes]]:
        """Keep exact partition leases while bounded Arrow batches filter a single venue."""
        for artifact_id, boundary, document in distributions:
            # The compact clock is loaded separately; block rows have no venue column.
            check_budget()
            if boundary.event_kind is EventKind.BLOCK:
                continue
            handle = cast(_LocalHandle, self._artifacts.open_committed(artifact_id))
            stack.callback(handle.close)
            # Authentication is repeated at open; a matching manifest ID alone is insufficient.
            manifest = _read_distribution_manifest(
                handle,
                artifact_id,
                expected_boundary=boundary,
                expected_ref=document,
                # Pinned writer/projector identities bind every shard to its committed derivation.
                expected_projector_bundle_id=self._projector_bundle_id,
                expected_writer_bundle_id=self._writer_bundle_id,
                # Chain identity is checked independently of the selected venue string.
                expected_network_id=self._network_id,
                expected_position_schema_id=self._position_schema_id,
            )
            kind = EventKind[cast(str, manifest["event_kind"])]
            path = handle.local_path("events.parquet")
            # Validate the physical schema before asking Arrow to bind the predicate.
            parquet = pq.ParquetFile(path)
            if not parquet.schema_arrow.equals(_schema(kind), check_metadata=True):
                raise CanonicalDataError("canonical partition schema mismatch")
            if parquet.metadata.num_rows != manifest["row_count"]:
                raise CanonicalDataError("canonical partition row count mismatch")
            # One worker, one batch of readahead; no selected-history list or native thread pool.
            scanner = ds.dataset(path, format="parquet").scanner(
                filter=ds.field("venue_id") == venue_id.value,
                batch_size=self._reader_batch_rows,
                batch_readahead=1,
                fragment_readahead=1,
                # Interactive queries share the controller host's native-thread budget.
                use_threads=False,
                fragment_scan_options=ds.ParquetFragmentScanOptions(pre_buffer=False),
            )
            for batch in scanner.to_batches():
                # Empty filtered batches still consume time and must not evade the deadline.
                check_budget()
                for row in batch.to_pylist():
                    # Filtering is complete before Python objects and protocol payloads are built.
                    event = _event_from_row(
                        row,
                        kind,
                        network_id=self._network_id,
                        # The decoder preserves integer amounts and exact event coordinates.
                        position_schema_id=self._position_schema_id,
                    )
                    yield event, _bytes(row, "logical_row_digest", width=32)
            check_budget()

    # Both readers preserve the existing gap-free capability shard sequence.
    def _capability_distribution_groups(
        self,
    ) -> tuple[
        tuple[
            tuple[ArtifactId, EffectiveSourceBoundary, dict[str, object]],
            ...,
        ],
        ...,
    ]:
        distribution_documents = cast(list[dict[str, object]], self._manifest["distributions"])
        grouped: dict[
            tuple[str, str],
            list[tuple[ArtifactId, EffectiveSourceBoundary, dict[str, object]]],
        ] = {}
        for artifact_id, boundary, document in zip(
            self._distribution_ids,
            self._source_boundaries,
            distribution_documents,
            strict=True,
        ):
            event_kind = cast(str, document["event_kind"])
            key = (boundary.source_boundary.capability_id.value, event_kind)
            grouped.setdefault(key, []).append((artifact_id, boundary, document))

        result: list[tuple[tuple[ArtifactId, EffectiveSourceBoundary, dict[str, object]], ...]] = []
        for key in sorted(grouped):
            ordered = tuple(
                sorted(
                    grouped[key],
                    key=lambda item: (
                        item[1].source_boundary.block_range.from_block_ordinal,
                        item[1].source_boundary.block_range.to_block_ordinal,
                    ),
                )
            )
            if any(
                left[1].source_boundary.block_range.to_block_ordinal
                != right[1].source_boundary.block_range.from_block_ordinal
                for left, right in pairwise(ordered)
            ):
                raise CanonicalDataError("capability distribution shards contain a gap or overlap")
            result.append(ordered)
        return tuple(result)

    def _capability_events(
        self,
        stack: ExitStack,
        distributions: tuple[
            tuple[ArtifactId, EffectiveSourceBoundary, dict[str, object]],
            ...,
        ],
    ) -> Iterator[tuple[CanonicalEvent, bytes]]:
        for artifact_id, expected_boundary, expected_ref in distributions:
            handle = cast(_LocalHandle, self._artifacts.open_committed(artifact_id))
            stack.callback(handle.close)
            manifest = _read_distribution_manifest(
                handle,
                artifact_id,
                expected_boundary=expected_boundary,
                expected_ref=expected_ref,
                expected_projector_bundle_id=self._projector_bundle_id,
                expected_writer_bundle_id=self._writer_bundle_id,
                expected_network_id=self._network_id,
                expected_position_schema_id=self._position_schema_id,
            )
            yield from _partition_events(
                handle.local_path("events.parquet"),
                EventKind[cast(str, manifest["event_kind"])],
                network_id=self._network_id,
                position_schema_id=self._position_schema_id,
                batch_rows=self._reader_batch_rows,
                readahead=self._reader_readahead,
            )

    def _open_distribution_paths(self, stack: ExitStack) -> list[str]:
        # Execute the canonical parquet replay source open distribution paths workflow in
        # explicit, reviewable steps.
        paths: list[str] = []
        distribution_documents = cast(list[dict[str, object]], self._manifest["distributions"])
        for artifact_id, expected_boundary, expected_ref in zip(
            self._distribution_ids,
            self._source_boundaries,
            # Pass distribution documents explicitly so zip receives a reviewable
            # distribution ids and source boundaries input in canonical parquet replay
            # source open distribution paths.
            distribution_documents,
            strict=True,
        ):
            # Process distribution ids, source boundaries and distribution documents
            # inside the bounded canonical parquet replay source open distribution paths
            # loop.
            handle = cast(_LocalHandle, self._artifacts.open_committed(artifact_id))
            stack.callback(handle.close)
            _read_distribution_manifest(
                handle,
                artifact_id,
                # Pass expected boundary explicitly so _read_distribution_manifest
                # receives a reviewable projector bundle id and writer bundle id input in
                # canonical parquet replay source open distribution paths.
                expected_boundary=expected_boundary,
                expected_ref=expected_ref,
                expected_projector_bundle_id=self._projector_bundle_id,
                expected_writer_bundle_id=self._writer_bundle_id,
                expected_network_id=self._network_id,
                # Pass expected position schema id explicitly so
                # _read_distribution_manifest receives a reviewable projector bundle id
                # and writer bundle id input in canonical parquet replay source open
                # distribution paths.
                expected_position_schema_id=self._position_schema_id,
            )
            paths.append(str(handle.local_path("events.parquet")))
        return paths

    def _validate_distribution_closure(self) -> None:
        # Execute the canonical parquet replay source validate distribution closure
        # workflow in explicit, reviewable steps.
        with ExitStack() as stack:
            self._open_distribution_paths(stack)

    def _load_transaction_clock(self) -> CompactTransactionClock:
        # Execute the canonical parquet replay source load transaction clock workflow in
        # explicit, reviewable steps.
        rows: list[tuple[int, int, int]] = []
        distribution_documents = cast(list[dict[str, object]], self._manifest["distributions"])
        with ExitStack() as stack:
            # Keep exit stack active only for the bounded canonical parquet replay source
            # load transaction clock operation.
            for artifact_id, expected_boundary, expected_ref in zip(
                self._distribution_ids,
                self._source_boundaries,
                distribution_documents,
                strict=True,
                # Complete zip only after its distribution ids and source boundaries inputs
                # are visible in canonical parquet replay source load transaction clock.
            ):
                # Process distribution ids, source boundaries and distribution documents
                # inside the bounded canonical parquet replay source load transaction
                # clock loop.
                if expected_boundary.event_kind is not EventKind.BLOCK:
                    continue
                handle = cast(_LocalHandle, self._artifacts.open_committed(artifact_id))
                stack.callback(handle.close)
                _read_distribution_manifest(
                    # Pass handle explicitly so _read_distribution_manifest receives a
                    # reviewable projector bundle id and writer bundle id input in
                    # canonical parquet replay source load transaction clock.
                    handle,
                    artifact_id,
                    expected_boundary=expected_boundary,
                    expected_ref=expected_ref,
                    expected_projector_bundle_id=self._projector_bundle_id,
                    # Pass expected writer bundle id explicitly so
                    # _read_distribution_manifest receives a reviewable projector bundle
                    # id and writer bundle id input in canonical parquet replay source
                    # load transaction clock.
                    expected_writer_bundle_id=self._writer_bundle_id,
                    expected_network_id=self._network_id,
                    expected_position_schema_id=self._position_schema_id,
                )
                parquet = pq.ParquetFile(handle.local_path("events.parquet"))
                # Traverse iter batches, parquet and reader batch rows explicitly so each
                # canonical parquet replay source load transaction clock iteration remains
                # traceable.
                for batch in parquet.iter_batches(
                    columns=["block_ordinal", "block_time_ns", "transaction_count"],
                    batch_size=self._reader_batch_rows,
                ):
                    # Process iter batches, parquet and reader batch rows inside the
                    # bounded canonical parquet replay source load transaction clock loop.
                    for row in batch.to_pylist():
                        # Process batch.to_pylist() inside the bounded canonical parquet
                        # replay source load transaction clock loop.
                        rows.append(
                            (
                                _int(row, "block_ordinal"),
                                _int(row, "transaction_count"),
                                _int(row, "block_time_ns"),
                                # Complete append only after its block ordinal and transaction
                                # count inputs are visible in canonical parquet replay source
                                # load transaction clock.
                            )
                        )
        rows.sort(key=lambda item: item[0])
        prefix: list[int] = []
        cumulative = 0
        # Traverse rows explicitly so each canonical parquet replay source load
        # transaction clock iteration remains traceable.
        for _, count, _ in rows:
            # Process rows inside the bounded canonical parquet replay source load
            # transaction clock loop.
            prefix.append(cumulative)
            cumulative += count
        try:
            # Perform the protected canonical parquet replay source load transaction clock
            # operation before explicit failure handling.
            return CompactTransactionClock(
                network_id=self._network_id,
                position_schema_id=self._position_schema_id,
                block_ordinals=tuple(item[0] for item in rows),
                transaction_counts=tuple(item[1] for item in rows),
                # Include cumulative transaction prefix in the completed canonical parquet
                # replay source load transaction clock result.
                cumulative_transaction_prefix=tuple(prefix),
                block_time_ns=tuple(item[2] for item in rows),
            )
        except (TypeError, ValueError) as error:
            raise CanonicalDataError("canonical compact transaction clock is invalid") from error


# Keep the canonical distribution candidate source contract and validation rules together.
class CanonicalDistributionCandidateSource:
    """Verified pre-root view over an exact distribution closure."""

    def __init__(
        self,
        artifacts: LocalArtifactRepository,
        spec: DatasetSpec,
        distributions: tuple[CanonicalDistributionRef, ...],
        # Close the init signature after its explicit inputs.
        *,
        projector_bundle_id: BundleId,
        writer_bundle_id: BundleId,
        reader_batch_rows: int = 65_536,
        reader_readahead: int = 1,
        # Close the init signature after its explicit inputs.
    ) -> None:
        # Execute the canonical distribution candidate source init workflow in explicit,
        # reviewable steps.
        if min(reader_batch_rows, reader_readahead) <= 0:
            raise ValueError("candidate reader limits must be positive")
        self._artifacts = artifacts
        self._spec = spec
        self._distributions = distributions
        # Assemble self projector bundle id once so the canonical distribution candidate
        # source init workflow shares one value.
        self._projector_bundle_id = projector_bundle_id
        self._writer_bundle_id = writer_bundle_id
        self._reader_batch_rows = reader_batch_rows
        self._reader_readahead = reader_readahead
        self._validate_distribution_closure()
        # Assemble self transaction clock once so the canonical distribution candidate
        # source init workflow shares one value.
        self._transaction_clock = self._load_transaction_clock()

    @property
    def network_id(self) -> NetworkId:
        return self._spec.network_id

    @property
    # Define canonical distribution candidate source position schema id as one focused
    # operation with an explicit boundary.
    def position_schema_id(self) -> PositionSchemaId:
        return self._spec.position_schema_id

    def transaction_clock(self) -> CompactTransactionClock:
        return self._transaction_clock

    def events(self) -> Iterator[CanonicalEvent]:
        # Execute the canonical distribution candidate source events workflow in explicit,
        # reviewable steps.
        with ExitStack() as stack:
            # Keep exit stack active only for the bounded canonical distribution candidate
            # source events operation.
            # Shards of one capability are contiguous and non-overlapping by DatasetSpec
            # contract. Chain them before the global merge so only one Parquet iterator
            # per capability is primed, independent of the physical shard count.
            iterators = [
                self._capability_events(stack, group)
                for group in self._capability_distribution_groups()
            ]

            heap: list[tuple[tuple[str, str, int, str, int, str], int, CanonicalEvent, bytes]] = []
            for index, iterator in enumerate(iterators):
                # Process enumerate(iterators) inside the bounded canonical distribution
                # candidate source events loop.
                try:
                    event, stored_digest = next(iterator)
                except StopIteration:
                    continue
                heapq.heappush(heap, (canonical_event_sort_key(event), index, event, stored_digest))
            # Repeat the canonical distribution candidate source events step only while
            # heap remains true.
            while heap:
                # Keep the heap loop body bounded within canonical distribution candidate
                # source events.
                _, index, event, stored_digest = heapq.heappop(heap)
                if canonical_event_digest(event).hex != stored_digest.hex():
                    raise CanonicalDataError("canonical row semantic digest mismatch")
                if isinstance(event, BlockEvent):
                    # Handle the canonical distribution candidate source events
                    # isinstance(event, BlockEvent) branch as a distinct logical block.
                    clock_index = _clock_row(self._transaction_clock, event.envelope.position)
                    if (
                        event.block_time_ns != self._transaction_clock.block_time_ns[clock_index]
                        or event.tx_count != self._transaction_clock.transaction_counts[clock_index]
                    ):
                        # Handle the canonical distribution candidate source events block
                        # time ns, tx count and event condition as a distinct block.
                        raise CanonicalDataError(
                            "block event differs from compact transaction clock"
                        )
                else:
                    self._transaction_clock.require_position(event.envelope.position)
                # Keep the yield step explicit within the canonical distribution candidate
                # source events workflow.
                yield event
                try:
                    next_event, next_digest = next(iterators[index])
                except StopIteration:
                    continue
                # Invoke heappush for canonical event sort key and heap as a visible
                # canonical distribution candidate source events step.
                heapq.heappush(
                    heap,
                    (
                        canonical_event_sort_key(next_event),
                        index,
                        # Pass next event explicitly so heappush receives a reviewable
                        # canonical event sort key and heap input in canonical
                        # distribution candidate source events.
                        next_event,
                        next_digest,
                    ),
                )

    def _capability_distribution_groups(
        self,
    ) -> tuple[tuple[CanonicalDistributionRef, ...], ...]:
        """Return deterministic, range-ordered chains for the bounded global merge."""

        grouped: dict[
            tuple[str, str],
            list[CanonicalDistributionRef],
        ] = {}
        for item in self._distributions:
            key = (item.capability_id.value, item.event_kind.name)
            grouped.setdefault(key, []).append(item)

        result: list[tuple[CanonicalDistributionRef, ...]] = []
        for key in sorted(grouped):
            ordered = tuple(
                sorted(
                    grouped[key],
                    key=lambda item: (
                        item.shard.block_range.from_block_ordinal,
                        item.shard.block_range.to_block_ordinal,
                        item.shard.ordinal,
                    ),
                )
            )
            if any(
                left.shard.block_range.to_block_ordinal
                != right.shard.block_range.from_block_ordinal
                for left, right in pairwise(ordered)
            ):
                raise CanonicalDataError("capability distribution shards contain a gap or overlap")
            result.append(ordered)
        return tuple(result)

    def _capability_events(
        self,
        stack: ExitStack,
        distributions: tuple[CanonicalDistributionRef, ...],
    ) -> Iterator[tuple[CanonicalEvent, bytes]]:
        """Read one capability's shards sequentially under the shared retention lease."""

        for item in distributions:
            handle = self._open_distribution(stack, item)
            yield from _partition_events(
                handle.local_path("events.parquet"),
                item.event_kind,
                network_id=self.network_id,
                position_schema_id=self.position_schema_id,
                batch_rows=self._reader_batch_rows,
                readahead=self._reader_readahead,
            )

    def _open_distribution(
        # Keep the remaining open distribution inputs visible at the canonical
        # distribution candidate source open distribution boundary.
        self,
        stack: ExitStack,
        item: CanonicalDistributionRef,
    ) -> _LocalHandle:
        # Execute the canonical distribution candidate source open distribution workflow
        # in explicit, reviewable steps.
        handle = cast(_LocalHandle, self._artifacts.open_committed(item.artifact.artifact_id))
        stack.callback(handle.close)
        _read_distribution_manifest(
            handle,
            item.artifact.artifact_id,
            # Pass expected boundary explicitly so _read_distribution_manifest receives a
            # reviewable artifact id and artifact input in canonical distribution
            # candidate source open distribution.
            expected_boundary=item.effective_source_boundary,
            expected_ref=_candidate_distribution_reference(item),
            expected_projector_bundle_id=self._projector_bundle_id,
            expected_writer_bundle_id=self._writer_bundle_id,
            expected_network_id=self.network_id,
            # Pass expected position schema id explicitly so _read_distribution_manifest
            # receives a reviewable artifact id and artifact input in canonical
            # distribution candidate source open distribution.
            expected_position_schema_id=self.position_schema_id,
        )
        return handle

    def _validate_distribution_closure(self) -> None:
        # Execute the canonical distribution candidate source validate distribution
        # closure workflow in explicit, reviewable steps.
        with ExitStack() as stack:
            # Keep exit stack active only for the bounded canonical distribution candidate
            # source validate distribution closure operation.
            for item in self._distributions:
                self._open_distribution(stack, item)

    def _load_transaction_clock(self) -> CompactTransactionClock:
        # Execute the canonical distribution candidate source load transaction clock
        # workflow in explicit, reviewable steps.
        rows: list[tuple[int, int, int]] = []
        with ExitStack() as stack:
            # Keep exit stack active only for the bounded canonical distribution candidate
            # source load transaction clock operation.
            for item in self._distributions:
                # Process self._distributions inside the bounded canonical distribution
                # candidate source load transaction clock loop.
                if item.event_kind is not EventKind.BLOCK:
                    continue
                handle = self._open_distribution(stack, item)
                parquet = pq.ParquetFile(handle.local_path("events.parquet"))
                for batch in parquet.iter_batches(
                    # Pass columns explicitly so iter_batches receives a reviewable block
                    # ordinal and block time ns input in canonical distribution candidate
                    # source load transaction clock.
                    columns=["block_ordinal", "block_time_ns", "transaction_count"],
                    batch_size=self._reader_batch_rows,
                ):
                    # Process iter batches, parquet and reader batch rows inside the
                    # bounded canonical distribution candidate source load transaction
                    # clock loop.
                    for row in batch.to_pylist():
                        # Process batch.to_pylist() inside the bounded canonical
                        # distribution candidate source load transaction clock loop.
                        rows.append(
                            (
                                _int(row, "block_ordinal"),
                                _int(row, "transaction_count"),
                                _int(row, "block_time_ns"),
                                # Complete append only after its block ordinal and transaction
                                # count inputs are visible in canonical distribution candidate
                                # source load transaction clock.
                            )
                        )
        rows.sort(key=lambda item: item[0])
        prefix: list[int] = []
        cumulative = 0
        # Traverse rows explicitly so each canonical distribution candidate source load
        # transaction clock iteration remains traceable.
        for _, count, _ in rows:
            # Process rows inside the bounded canonical distribution candidate source load
            # transaction clock loop.
            prefix.append(cumulative)
            cumulative += count
        return CompactTransactionClock(
            network_id=self.network_id,
            position_schema_id=self.position_schema_id,
            # Include block ordinals in the completed canonical distribution candidate
            # source load transaction clock result.
            block_ordinals=tuple(item[0] for item in rows),
            transaction_counts=tuple(item[1] for item in rows),
            cumulative_transaction_prefix=tuple(prefix),
            block_time_ns=tuple(item[2] for item in rows),
        )


# Define partition events as one focused operation with an explicit boundary.
def _partition_events(
    path: Path,
    event_kind: EventKind,
    *,
    network_id: NetworkId,
    # Keep the position schema id input explicit in the partition events contract.
    position_schema_id: PositionSchemaId,
    batch_rows: int,
    readahead: int,
) -> Iterator[tuple[CanonicalEvent, bytes]]:
    # Execute the partition events workflow in explicit, reviewable steps.
    parquet = pq.ParquetFile(path)
    if not parquet.schema_arrow.equals(_schema(event_kind), check_metadata=True):
        raise CanonicalDataError("canonical partition schema mismatch")
    batches = iter(parquet.iter_batches(batch_size=batch_rows))
    while window := tuple(islice(batches, readahead)):
        # Keep the window, islice and batches loop body bounded within partition events.
        for batch in window:
            # Process window inside the bounded partition events loop.
            for row in batch.to_pylist():
                # Process batch.to_pylist() inside the bounded partition events loop.
                stored_digest = _bytes(row, "logical_row_digest", width=32)
                yield (
                    _event_from_row(
                        row,
                        event_kind,
                        # Pass network id explicitly so _event_from_row receives a
                        # reviewable row and event kind input in partition events.
                        network_id=network_id,
                        position_schema_id=position_schema_id,
                    ),
                    stored_digest,
                )


# Define event from row as one focused operation with an explicit boundary.
def _event_from_row(
    row: dict[str, Any],
    event_kind: EventKind,
    *,
    network_id: NetworkId,
    # Keep the position schema id input explicit in the event from row contract.
    position_schema_id: PositionSchemaId,
) -> CanonicalEvent:
    # Execute the event from row workflow in explicit, reviewable steps.
    envelope = EventEnvelope(
        position=ChainPosition(
            network_id=network_id,
            position_schema_id=position_schema_id,
            block_ordinal=_int(row, "block_ordinal"),
            # Keep the row _int step visible while building envelope.
            transaction_index=_int(row, "transaction_index"),
            event_index=_optional_int(row, "event_index"),
        ),
        transaction_group_id=ContentDigest(_bytes(row, "transaction_group_id", 32).hex()),
        source_record_id=ContentDigest(_bytes(row, "source_record_id", 32).hex()),
        # Keep the content digest and hex ContentDigest step visible while building
        # envelope.
        canonical_event_id=ContentDigest(_bytes(row, "canonical_event_id", 32).hex()),
        stable_causal_id=ContentDigest(_bytes(row, "stable_causal_id", 32).hex()),
        capability_id=CapabilityId(_str(row, "capability_id")),
        protocol=_str(row, "protocol"),
        protocol_version=_str(row, "protocol_version"),
        # Keep the ordering fidelity and str OrderingFidelity step visible while building
        # envelope.
        ordering_fidelity=OrderingFidelity(_str(row, "ordering_fidelity")),
    )
    if envelope.boundary_ordinal != _int(row, "boundary_ordinal"):
        raise CanonicalDataError("stored boundary ordinal does not match chain position")
    if _int(row, "event_kind") != int(event_kind):
        # Fail the event from row path with CanonicalDataError for stored event kind code
        # does not match partition when int, row and event kind is true; do not continue
        # ambiguously.
        raise CanonicalDataError("stored event kind code does not match partition")
    if event_kind is EventKind.BLOCK:
        # Handle the event from row event_kind is EventKind.BLOCK branch as a distinct
        # logical block.
        return BlockEvent(
            envelope=envelope,
            block_time_ns=_int(row, "block_time_ns"),
            tx_count=_int(row, "transaction_count"),
            block_hash=_optional_str(row, "block_hash"),
            # Complete BlockEvent only after its block time ns and transaction count inputs
            # are visible in event from row.
        )
    payload_schema = ProtocolPayloadSchemaId(_str(row, "protocol_payload_schema"))
    payload = _variable_bytes(row, "protocol_payload")
    if event_kind is EventKind.TOKEN_LAUNCH:
        # Handle the event from row event_kind is EventKind.TOKEN_LAUNCH branch as a
        # distinct logical block.
        return TokenLaunchEvent(
            envelope=envelope,
            asset_id=AssetId(_str(row, "asset_id")),
            developer_id=AccountId(_str(row, "developer_id")),
            creation_user_id=AccountId(_str(row, "creation_user_id")),
            # Include venue id in the completed event from row result.
            venue_id=VenueId(_str(row, "venue_id")),
            quote_asset_id=AssetId(_str(row, "quote_asset_id")),
            decimals=_optional_int(row, "decimals"),
            protocol_payload_schema=payload_schema,
            protocol_payload=payload,
            # Complete TokenLaunchEvent only after its asset id and developer id inputs are
            # visible in event from row.
        )
    if event_kind is EventKind.VENUE_TRADE:
        # Handle the event from row event_kind is EventKind.VENUE_TRADE branch as a
        # distinct logical block.
        raw_components = row.get("fee_components")
        if not isinstance(raw_components, list):
            raise CanonicalDataError("canonical fee_components must be a list")
        components: list[FeeComponent] = []
        for value in raw_components:
            # Process raw_components inside the bounded event from row loop.
            if not isinstance(value, dict):
                raise CanonicalDataError("canonical fee component must be an object")
            component = cast(dict[str, Any], value)
            components.append(
                FeeComponent(
                    # Pass component id explicitly to append for amount atomic and
                    # component id.
                    component_id=FeeComponentId(_str(component, "component_id")),
                    asset_id=AssetId(_str(component, "asset_id")),
                    amount_atomic=_int128(component, "amount_atomic"),
                )
            )
        # Return the completed event from row result without a hidden fallback.
        return VenueTradeEvent(
            envelope=envelope,
            venue_id=VenueId(_str(row, "venue_id")),
            sold_asset_id=AssetId(_str(row, "sold_asset_id")),
            bought_asset_id=AssetId(_str(row, "bought_asset_id")),
            # Include sold amount atomic in the completed event from row result.
            sold_amount_atomic=_int128(row, "sold_amount_atomic"),
            bought_amount_atomic=_int128(row, "bought_amount_atomic"),
            fee_components=tuple(components),
            protocol_payload_schema=payload_schema,
            protocol_payload=payload,
            # Complete VenueTradeEvent only after its venue id and sold asset id inputs are
            # visible in event from row.
        )
    if event_kind is EventKind.VENUE_LIFECYCLE:
        # Handle the event from row event kind and venue lifecycle condition as a distinct
        # block.
        return VenueLifecycleEvent(
            envelope=envelope,
            venue_id=VenueId(_str(row, "venue_id")),
            lifecycle_kind=VenueLifecycleKind(_str(row, "lifecycle_kind")),
            protocol_payload_schema=payload_schema,
            # Pass protocol payload explicitly so VenueLifecycleEvent receives a
            # reviewable venue id and lifecycle kind input in event from row.
            protocol_payload=payload,
        )
    raise CanonicalDataError(f"reference reader does not support {event_kind.name}")


def _validate_snapshot_manifest(
    manifest: dict[str, Any],
    # Keep the input ids input explicit in the validate snapshot manifest contract.
    input_ids: tuple[ArtifactId, ...],
    *,
    expected_projector_bundle_id: BundleId | None = None,
) -> dict[str, Any]:
    # Execute the validate snapshot manifest workflow in explicit, reviewable steps.
    artifact_schema = manifest.get("artifact_schema")
    if artifact_schema in {
        "canonical-snapshot/v1",
        "canonical-snapshot/v2",
        "canonical-snapshot/v3",
        # Evaluate the complete validate snapshot manifest artifact schema condition before
        # guarded effects.
    }:
        raise ReprepareRequiredError(cast(str, artifact_schema))
    required = {
        "artifact_schema",
        "canonical_schema_version",
        # Keep the capability ranges component named inside the required contract.
        "capability_ranges",
        "created_at",
        "dataset_revision_id",
        "dataset_spec",
        "distributions",
        # Keep the logical content hash component named inside the required contract.
        "logical_content_hash",
        "network_id",
        "position_schema_id",
        "projector_bundle_id",
        "requested_decision_range",
        # Keep the settlement tail component named inside the required contract.
        "settlement_tail",
        "source_boundaries",
        "source_id",
        "spec_id",
        "validation_status",
        # Complete the required group only after its semantic components are visible.
    }
    if (
        set(manifest) != required
        or artifact_schema != "canonical-snapshot/v4"
        or manifest.get("canonical_schema_version") != 3
        # Evaluate the complete validate snapshot manifest required, artifact schema and
        # manifest condition before guarded effects.
    ):
        raise CanonicalDataError("snapshot manifest schema is invalid")
    distributions = manifest.get("distributions")
    if not isinstance(distributions, list) or not distributions:
        raise CanonicalDataError("snapshot has no canonical distributions")
    # Keep expected failures inside the validate snapshot manifest error boundary.
    try:
        # Perform the protected validate snapshot manifest operation before explicit
        # failure handling.
        spec = dataset_spec_from_snapshot_document(manifest)
        boundaries = effective_source_boundaries_from_snapshot_document(manifest)
        source_id = SourceId(cast(str, manifest["source_id"]))
        network_id = NetworkId(cast(str, manifest["network_id"]))
        position_schema_id = PositionSchemaId(cast(str, manifest["position_schema_id"]))
        # Evaluate the complete validate snapshot manifest source id, network id and
        # position schema id condition before guarded effects.
        if (
            spec.source_id != source_id
            or spec.network_id != network_id
            or spec.position_schema_id != position_schema_id
        ):
            # Fail the validate snapshot manifest path with CanonicalDataError for
            # snapshot dataset spec identity is inconsistent when source id, network id
            # and position schema id is true; do not continue ambiguously.
            raise CanonicalDataError("snapshot DatasetSpec identity is inconsistent")
        if manifest["validation_status"] != ValidationStatus.PASS.value or any(
            boundary.source_boundary.source_id != source_id
            or boundary.source_boundary.validation_status is not ValidationStatus.PASS
            for boundary in boundaries
            # Complete any only after its source id and validation status inputs are visible
            # in validate snapshot manifest.
        ):
            raise CanonicalDataError("snapshot source boundaries are not validated")
        if len(boundaries) != len(distributions) or len(spec.shards) != len(distributions):
            # Handle the validate snapshot manifest boundaries, distributions and shards
            # condition as a distinct block.
            raise CanonicalDataError(
                "snapshot source boundaries do not cover canonical distributions"
            )
        for ordinal, (item, boundary, shard) in enumerate(
            zip(distributions, boundaries, spec.shards, strict=True)
            # Complete enumerate only after its shards and zip inputs are visible in validate
            # snapshot manifest.
        ):
            # Process distributions, boundaries and shards inside the bounded validate
            # snapshot manifest loop.
            if not isinstance(item, dict) or set(item) != {
                "artifact_id",
                "capability_id",
                "event_kind",
                "logical_content_hash",
                # Keep manifest digest visible while evaluating the isinstance, item and
                # artifact id guard.
                "manifest_digest",
                "row_count",
                "shard",
            }:
                raise CanonicalDataError("snapshot distribution reference schema is invalid")
            # Assemble row count once so the validate snapshot manifest workflow shares
            # one value.
            row_count = item["row_count"]
            if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count < 0:
                raise CanonicalDataError("snapshot distribution row count is invalid")
            EventKind[cast(str, item["event_kind"])]
            _validate_snapshot_shard(item["shard"], boundary, shard, ordinal)
        # Assemble referenced once so the validate snapshot manifest workflow shares one
        # value.
        referenced = tuple(
            sorted(
                (ArtifactId(cast(str, item["artifact_id"])) for item in distributions),
                key=lambda item: item.hex,
            )
            # Complete tuple only after its artifact id and hex inputs are visible in validate
            # snapshot manifest.
        )
        DatasetRevisionId(cast(str, manifest["dataset_revision_id"]))
        LogicalContentHash(cast(str, manifest["logical_content_hash"]))
        if manifest["capability_ranges"] != [
            {
                # Keep block range visible while evaluating the manifest, capability
                # ranges and block range guard.
                "block_range": _range_document(item.block_range),
                "capability_id": item.capability_id.value,
            }
            for item in spec.capability_ranges
        ]:
            # Fail the validate snapshot manifest path with CanonicalDataError for
            # snapshot capability ranges differ from dataset spec when manifest,
            # capability ranges and block range is true; do not continue ambiguously.
            raise CanonicalDataError("snapshot capability ranges differ from DatasetSpec")
        expected_tail = (
            None if spec.settlement_tail is None else _range_document(spec.settlement_tail)
        )
        if manifest["settlement_tail"] != expected_tail:
            # Fail the validate snapshot manifest path with CanonicalDataError for
            # snapshot settlement tail differs from dataset spec when expected tail,
            # manifest and settlement tail is true; do not continue ambiguously.
            raise CanonicalDataError("snapshot settlement tail differs from DatasetSpec")
    except (KeyError, TypeError, ValueError) as error:
        # Translate the (KeyError, TypeError, ValueError) failure through the validate
        # snapshot manifest boundary.
        if isinstance(error, CanonicalDataError):
            raise
        raise CanonicalDataError("snapshot manifest identities are invalid") from error
    if referenced != tuple(sorted(input_ids, key=lambda item: item.hex)):
        raise CanonicalDataError("snapshot manifest references differ from committed inputs")
    # Evaluate the complete validate snapshot manifest expected projector bundle id, hex
    # and get condition before guarded effects.
    if (
        expected_projector_bundle_id is not None
        and manifest.get("projector_bundle_id") != expected_projector_bundle_id.hex
    ):
        raise CanonicalDataError("snapshot projector differs from installed exact projection")
    # Return the completed validate snapshot manifest result without a hidden fallback.
    return manifest


def _read_distribution_manifest(
    handle: _LocalHandle,
    artifact_id: ArtifactId,
    *,
    # Keep the expected boundary input explicit in the read distribution manifest
    # contract.
    expected_boundary: EffectiveSourceBoundary,
    expected_ref: dict[str, object],
    expected_projector_bundle_id: BundleId,
    expected_writer_bundle_id: BundleId,
    expected_network_id: NetworkId,
    # Keep the expected position schema id input explicit in the read distribution
    # manifest contract.
    expected_position_schema_id: PositionSchemaId,
) -> dict[str, Any]:
    # Execute the read distribution manifest workflow in explicit, reviewable steps.
    if handle.descriptor.kind is not ArtifactKind.CANONICAL_DISTRIBUTION:
        raise CanonicalDataError("snapshot input is not a canonical distribution")
    if handle.descriptor.artifact_id != artifact_id:
        raise CanonicalDataError("canonical distribution identity mismatch")
    manifest = _canonical_json_object(handle, "canonical distribution manifest")
    # Assemble artifact schema once so the read distribution manifest workflow shares one
    # value.
    artifact_schema = manifest.get("artifact_schema")
    if artifact_schema in {
        "canonical-distribution/v1",
        "canonical-distribution/v2",
        "canonical-distribution/v3",
        # Keep canonical-distribution v4 visible while evaluating the artifact schema
        # guard.
        "canonical-distribution/v4",
    }:
        raise ReprepareRequiredError(cast(str, artifact_schema))
    expected_keys = {
        "artifact_schema",
        # Keep the canonical schema id component named inside the expected keys contract.
        "canonical_schema_id",
        "canonical_schema_version",
        "capability_id",
        "created_at",
        "event_file",
        # Keep the event kind component named inside the expected keys contract.
        "event_kind",
        "logical_content_hash",
        "maximum_boundary_ordinal",
        "minimum_boundary_ordinal",
        "network_id",
        # Keep the position schema id component named inside the expected keys contract.
        "position_schema_id",
        "projector_bundle_id",
        "row_count",
        "source_boundary",
        "source_contract",
        # Keep the writer bundle id component named inside the expected keys contract.
        "writer_bundle_id",
    }
    if (
        set(manifest) != expected_keys
        or artifact_schema != "canonical-distribution/v5"
        # Keep manifest visible while evaluating the expected keys, artifact schema and
        # parquet guard.
        or manifest.get("canonical_schema_version") != 3
        or manifest.get("event_file") != "events.parquet"
        or manifest.get("network_id") != expected_network_id.value
        or manifest.get("position_schema_id") != expected_position_schema_id.value
        or manifest.get("projector_bundle_id") != expected_projector_bundle_id.hex
        # Keep manifest visible while evaluating the expected keys, artifact schema and
        # parquet guard.
        or manifest.get("writer_bundle_id") != expected_writer_bundle_id.hex
    ):
        raise CanonicalDataError("canonical distribution manifest schema is invalid")
    try:
        # Perform the protected read distribution manifest operation before explicit
        # failure handling.
        actual_boundary = EffectiveSourceBoundary.from_document(manifest["source_boundary"])
        event_kind = EventKind[cast(str, manifest["event_kind"])]
    except (KeyError, TypeError, ValueError) as error:
        raise CanonicalDataError("canonical distribution source fidelity is invalid") from error
    if (
        # Keep actual boundary visible while evaluating the actual boundary, expected
        # boundary and network id guard.
        actual_boundary != expected_boundary
        or actual_boundary.source_boundary.block_range.network_id != expected_network_id
        or actual_boundary.source_boundary.block_range.position_schema_id
        != expected_position_schema_id
    ):
        # Fail the read distribution manifest path with CanonicalDataError for snapshot
        # and distribution source fidelity differ when actual boundary, expected boundary
        # and network id is true; do not continue ambiguously.
        raise CanonicalDataError("snapshot and distribution source fidelity differ")
    if manifest.get("canonical_schema_id") != _schema_id(event_kind, _schema(event_kind)).hex:
        raise CanonicalDataError("canonical distribution schema identity is invalid")
    expected_values = {
        "artifact_id": artifact_id.hex,
        # Keep the capability id component named inside the expected values contract.
        "capability_id": actual_boundary.source_boundary.capability_id.value,
        "event_kind": actual_boundary.event_kind.name,
        "logical_content_hash": manifest.get("logical_content_hash"),
        "manifest_digest": handle.descriptor.manifest_digest.hex,
        "row_count": manifest.get("row_count"),
        # Register shard through get so the expected values table remains scannable.
        "shard": expected_ref.get("shard"),
    }
    if expected_ref != expected_values:
        raise CanonicalDataError("snapshot distribution reference differs from its manifest")
    if (
        # Keep manifest visible while evaluating the value, name and get guard.
        manifest.get("capability_id") != actual_boundary.source_boundary.capability_id.value
        or manifest.get("event_kind") != actual_boundary.event_kind.name
    ):
        raise CanonicalDataError("distribution source boundary metadata is inconsistent")
    return manifest


# Define unit canonical reader tools as one focused operation with an explicit boundary.
def _unit_canonical_reader_tools() -> PinnedCodeBundleSet:
    # Execute the unit canonical reader tools workflow in explicit, reviewable steps.
    return PinnedCodeBundleSet(
        (
            PinnedCodeBundleIdentity.for_unit_tests(
                CANONICAL_WRITER_ROLE, canonical_writer_bundle_id()
            ),
            # Complete PinnedCodeBundleSet only after its for unit tests and canonical writer
            # bundle id inputs are visible in unit canonical reader tools.
        )
    )


def _validate_snapshot_shard(
    value: object,
    boundary: EffectiveSourceBoundary,
    # Keep the expected shard input explicit in the validate snapshot shard contract.
    expected_shard: DatasetShard,
    ordinal: int,
) -> None:
    # Execute the validate snapshot shard workflow in explicit, reviewable steps.
    expected = {
        "block_range": _range_document(expected_shard.block_range),
        "capability_id": expected_shard.capability_id.value,
        "columns": list(expected_shard.columns),
        "ordinal": ordinal,
        # Complete the expected group only after its semantic components are visible.
    }
    if value != expected or boundary.source_boundary.block_range != expected_shard.block_range:
        raise CanonicalDataError("snapshot shard differs from its source boundary or DatasetSpec")


def _candidate_distribution_reference(item: CanonicalDistributionRef) -> dict[str, object]:
    # Execute the candidate distribution reference workflow in explicit, reviewable steps.
    return {
        "artifact_id": item.artifact.artifact_id.hex,
        "capability_id": item.capability_id.value,
        "event_kind": item.event_kind.name,
        "logical_content_hash": item.logical_content_hash.hex,
        # Include manifest digest in the completed candidate distribution reference
        # result.
        "manifest_digest": item.artifact.manifest_digest.hex,
        "row_count": item.row_count,
        "shard": {
            "block_range": _range_document(item.shard.block_range),
            "capability_id": item.shard.capability_id.value,
            # Include columns in the completed candidate distribution reference result.
            "columns": list(item.shard.columns),
            "ordinal": item.shard.ordinal,
        },
    }


def _clock_row(clock: CompactTransactionClock, position: ChainPosition) -> int:
    # Execute the clock row workflow in explicit, reviewable steps.
    index = bisect_left(clock.block_ordinals, position.block_ordinal)
    if index == len(clock.block_ordinals) or clock.block_ordinals[index] != position.block_ordinal:
        raise CanonicalDataError("block event is absent from compact transaction clock")
    return index


def _range_document(value: BlockRange) -> dict[str, object]:
    # Execute the range document workflow in explicit, reviewable steps.
    return {
        "from_block_ordinal": value.from_block_ordinal,
        "network_id": value.network_id.value,
        "position_schema_id": value.position_schema_id.value,
        "to_block_ordinal": value.to_block_ordinal,
        # Return the completed range document result without a hidden fallback.
    }


def _configure_duckdb(connection: Any, memory_limit_mb: int, threads: int) -> None:
    # Execute the configure duckdb workflow in explicit, reviewable steps.
    connection.execute(f"SET memory_limit='{memory_limit_mb}MB'")
    connection.execute(f"SET threads={threads}")
    connection.execute("SET preserve_insertion_order=false")


def _canonical_json_object(handle: _LocalHandle, label: str) -> dict[str, Any]:
    # Execute the canonical json object workflow in explicit, reviewable steps.
    with handle.open_binary("manifest.json") as stream:
        payload = stream.read()
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, ValueError) as error:
        # Fail the canonical json object path with CanonicalDataError for is invalid json
        # and label; do not continue ambiguously.
        raise CanonicalDataError(f"{label} is invalid JSON") from error
    if (
        not isinstance(value, dict)
        or not all(isinstance(key, str) for key in value)
        or canonical_json_bytes(value) != payload
        # Evaluate the complete canonical json object payload, isinstance and value condition
        # before guarded effects.
    ):
        raise CanonicalDataError(f"{label} must be canonical JSON")
    return cast(dict[str, Any], value)


def _bytes(row: dict[str, Any], field: str, width: int) -> bytes:
    # Execute the bytes workflow in explicit, reviewable steps.
    value = row.get(field)
    if not isinstance(value, bytes) or len(value) != width:
        raise CanonicalDataError(f"canonical {field} has an invalid binary width")
    return value


def _variable_bytes(row: dict[str, Any], field: str) -> bytes:
    # Execute the variable bytes workflow in explicit, reviewable steps.
    value = row.get(field)
    if not isinstance(value, bytes):
        raise CanonicalDataError(f"canonical {field} must be bytes")
    return value


def _str(row: dict[str, Any], field: str) -> str:
    # Execute the str workflow in explicit, reviewable steps.
    value = row.get(field)
    if not isinstance(value, str) or not value or value != value.strip():
        raise CanonicalDataError(f"canonical {field} must be a non-empty trimmed string")
    return value


def _optional_str(row: dict[str, Any], field: str) -> str | None:
    # Return the completed optional str result without a hidden fallback.
    return None if row.get(field) is None else _str(row, field)


def _int(row: dict[str, Any], field: str) -> int:
    # Execute the int workflow in explicit, reviewable steps.
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise CanonicalDataError(f"canonical {field} must be an integer")
    return value


def _optional_int(row: dict[str, Any], field: str) -> int | None:
    # Return the completed optional int result without a hidden fallback.
    return None if row.get(field) is None else _int(row, field)


def _int128(row: dict[str, Any], field: str) -> int:
    return int.from_bytes(_bytes(row, field, 16), "big", signed=True)


__all__ = ["CanonicalDistributionCandidateSource", "CanonicalParquetReplaySource"]
