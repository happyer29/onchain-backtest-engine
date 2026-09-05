# Declare this module's dependencies and contracts before execution.
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository

# Import numpy at the visible module dependency boundary.
from backtest.adapters.columnar.numpy import LocalNumpyReplayPackCompiler
from backtest.adapters.columnar.numpy import layout as physical
from backtest.adapters.performance.replay import (
    OPTIMIZED_REDUCER_BENCHMARK_BUNDLE_ID,
    REFERENCE_REDUCER_BENCHMARK_BUNDLE_ID,
    # Include replay scan benchmark bundle id so the replay dependency remains explicit.
    REPLAY_SCAN_BENCHMARK_BUNDLE_ID,
    LocalReplayBenchmarkRunner,
)
from backtest.application.benchmarks import (
    BenchmarkSpec,
    # Include benchmark workload so the benchmarks dependency remains explicit.
    BenchmarkWorkload,
    CacheCondition,
)
from backtest.application.models import (
    ArtifactDraft,
    # Include artifact kind so the models dependency remains explicit.
    ArtifactKind,
    CapabilityStream,
    DatasetSpec,
)
from backtest.application.replay_packs import ReplaySemanticsManifest

# Import chain at the visible module dependency boundary.
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
)
from backtest.domain.event_hashing import canonical_event_stream_hash

# Import fidelity at the visible module dependency boundary.
from backtest.domain.fidelity import OrderingFidelity
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import (
    ArtifactId,
    CapabilityId,
    # Include content digest so the identifiers dependency remains explicit.
    ContentDigest,
    DatasetRevisionId,
    LogicalContentHash,
    ReplayPackId,
    RuntimeLockId,
    # Include snapshot id so the identifiers dependency remains explicit.
    SnapshotId,
)
from backtest.domain.market_events import BlockEvent, CanonicalEvent, ChainPosition, EventEnvelope
from backtest.domain.time import BlockRange
from backtest.engine.replay import ReplayBoundary

# Import replay v3 at the visible module dependency boundary.
from tests.support.replay_v3 import fixture_dataset_spec, fixture_snapshot_manifest

_BENCHMARK_CAPABILITY_ID = CapabilityId("benchmark.blocks.v1")
_BENCHMARK_DECISION_RANGE = BlockRange(
    SOLANA_MAINNET_NETWORK_ID,
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    # Keep block range, solana mainnet network id and block32 transaction32 position
    # schema id visible while completing BlockRange within module.
    100,
    5_100,
)


@pytest.mark.performance
def test_synthetic_30_day_capacity_scan_and_reference_reducer(tmp_path: Path) -> None:
    """Opt-in capacity path; production-sized event density is a CLI input artifact concern."""

    artifacts, replay_pack_id = _replay_pack(tmp_path)
    runner = LocalReplayBenchmarkRunner(
        artifacts.data_root,
        private_memory_budget_mb=4_096,
        physical_cores=4,
        # Pass max processes by io explicitly so LocalReplayBenchmarkRunner receives a
        # reviewable data root and artifacts input in test synthetic 30 day capacity scan
        # and reference reducer.
        max_processes_by_io=4,
    )

    scans_by_process = {
        process_count: runner.run(
            _spec(
                # Pass replay pack id explicitly so _spec receives a reviewable hex and
                # replay pack id input in test synthetic 30 day capacity scan and
                # reference reducer.
                replay_pack_id.hex,
                capacity_days=30,
                process_count=process_count,
            )
        )
        # Keep the process count component named inside the scans by process contract.
        for process_count in (1, 2, 4)
    }
    scan = scans_by_process[1]
    reducer = runner.run(
        _spec(
            # Pass replay pack id explicitly so _spec receives a reviewable hex and
            # reference reducer input in test synthetic 30 day capacity scan and reference
            # reducer.
            replay_pack_id.hex,
            workload=BenchmarkWorkload.REFERENCE_REDUCER,
            capacity_days=30,
        )
    )
    # Assemble optimized once so the test synthetic 30 day capacity scan and reference
    # reducer workflow shares one value.
    optimized = runner.run(
        _spec(
            replay_pack_id.hex,
            workload=BenchmarkWorkload.OPTIMIZED_REDUCER,
            capacity_days=30,
            # Complete _spec only after its hex and optimized reducer inputs are visible in
            # test synthetic 30 day capacity scan and reference reducer.
        )
    )

    expected_items = 5_000 * 30
    assert scan.samples[0].items_processed == expected_items
    assert reducer.samples[0].items_processed == expected_items
    # Verify the items processed, expected items and samples relationship before this
    # scenario is accepted.
    assert optimized.samples[0].items_processed == expected_items
    assert optimized.samples[0].canonical_result_hash == (reducer.samples[0].canonical_result_hash)
    assert scan.samples[0].major_faults >= 0
    assert reducer.samples[0].peak_private_rss_bytes is not None
    grid = {
        # Keep the run and runner run step visible while building grid.
        (batch_rows, readahead): runner.run(
            _spec(
                replay_pack_id.hex,
                capacity_days=1,
                batch_rows=batch_rows,
                # Pass readahead explicitly so _spec receives a reviewable hex and replay
                # pack id input in test synthetic 30 day capacity scan and reference
                # reducer.
                readahead=readahead,
            )
        )
        for batch_rows in (32_768, 65_536, 131_072, 262_144)
        for readahead in (1, 2, 4)
        # Complete the grid group only after its semantic components are visible.
    }
    assert len({report.canonical_result_hash for report in grid.values()}) == 1
    print(
        json.dumps(
            {
                # Keep batch readahead items per second named so the batch readahead items
                # per second and process scaling payload passed to dumps remains self-
                # describing within test synthetic 30 day capacity scan and reference
                # reducer.
                "batch_readahead_items_per_second": {
                    f"{batch_rows}/{readahead}": report.median_items_per_second
                    for (batch_rows, readahead), report in grid.items()
                },
                "process_scaling": {
                    # Pass str explicitly to print for batch readahead items per second
                    # and process scaling.
                    str(process_count): {
                        "items_per_second": report.median_items_per_second,
                        "private_rss_bytes": report.samples[0].peak_private_rss_bytes,
                        "wall_time_ns": report.samples[0].wall_time_ns,
                    }
                    # Pass process count explicitly to print for batch readahead items per
                    # second and process scaling.
                    for process_count, report in scans_by_process.items()
                },
                "reducer": reducer.document(),
                "optimized_reducer": optimized.document(),
                "optimized_speedup_x": (
                    # Pass optimized explicitly so dumps receives a reviewable batch
                    # readahead items per second and process scaling input in test
                    # synthetic 30 day capacity scan and reference reducer.
                    optimized.median_items_per_second / reducer.median_items_per_second
                ),
                "scan": scan.document(),
                "synthetic_events_per_day": 5_000,
            },
            # Pass sort keys explicitly so dumps receives a reviewable batch readahead
            # items per second and process scaling input in test synthetic 30 day capacity
            # scan and reference reducer.
            sort_keys=True,
        )
    )


# Keep the canonical source contract and validation rules together.
class _CanonicalSource:
    def __init__(self, events: tuple[CanonicalEvent, ...], dataset_spec: DatasetSpec) -> None:
        # Execute the canonical source init workflow in explicit, reviewable steps.
        self._events = events
        self._dataset_spec = dataset_spec

    @property
    def dataset_revision_id(self) -> DatasetRevisionId:
        return DatasetRevisionId("d" * 64)

    # Apply property semantics to the following canonical source logical content hash
    # contract.
    @property
    def logical_content_hash(self) -> LogicalContentHash:
        return canonical_event_stream_hash(self._events)

    @property
    def replay_semantics_id(self) -> ContentDigest:
        # Return the completed canonical source replay semantics id result without a
        # hidden fallback.
        return ReplaySemanticsManifest.canonical_v3().replay_semantics_id

    @property
    def decision_range(self) -> BlockRange:
        return self._dataset_spec.decision_range

    @property
    # Define canonical source dataset spec as one focused operation with an explicit
    # boundary.
    def dataset_spec(self) -> DatasetSpec:
        return self._dataset_spec

    def boundaries(self) -> tuple[ReplayBoundary, ...]:
        # Execute the canonical source boundaries workflow in explicit, reviewable steps.
        return tuple(
            ReplayBoundary.from_position(event.envelope.position) for event in self._events
        )

    def events(self) -> Iterator[CanonicalEvent]:
        yield from self._events


# Define spec as one focused operation with an explicit boundary.
def _spec(
    replay_pack_id: str,
    *,
    workload: BenchmarkWorkload = BenchmarkWorkload.REPLAY_PACK_SCAN,
    capacity_days: int,
    # Keep the batch rows input explicit in the spec contract.
    batch_rows: int = 65_536,
    readahead: int = 1,
    process_count: int = 1,
) -> BenchmarkSpec:
    # Execute the spec workflow in explicit, reviewable steps.
    return BenchmarkSpec(
        workload=workload,
        input_artifact_ids=(ArtifactId(replay_pack_id),),
        workload_bundle_id={
            BenchmarkWorkload.REPLAY_PACK_SCAN: REPLAY_SCAN_BENCHMARK_BUNDLE_ID,
            # Pass benchmark workload explicitly so BenchmarkSpec receives a reviewable 9
            # and replay pack scan input in spec.
            BenchmarkWorkload.REFERENCE_REDUCER: REFERENCE_REDUCER_BENCHMARK_BUNDLE_ID,
            BenchmarkWorkload.OPTIMIZED_REDUCER: OPTIMIZED_REDUCER_BENCHMARK_BUNDLE_ID,
        }[workload],
        runtime_lock_id=RuntimeLockId("9" * 64),
        cache_condition=CacheCondition.WARM,
        # Pass batch rows explicitly so BenchmarkSpec receives a reviewable 9 and replay
        # pack scan input in spec.
        batch_rows=batch_rows,
        readahead=readahead,
        process_count=process_count,
        native_threads_per_process=1,
        warmup_iterations=0,
        # Pass measured iterations explicitly so BenchmarkSpec receives a reviewable 9 and
        # replay pack scan input in spec.
        measured_iterations=1,
        capacity_days=capacity_days,
    )


def _replay_pack(tmp_path: Path) -> tuple[LocalArtifactRepository, ReplayPackId]:
    # Execute the replay pack workflow in explicit, reviewable steps.
    artifacts = LocalArtifactRepository(tmp_path / "var")
    dataset_spec = fixture_dataset_spec(
        capability_id=_BENCHMARK_CAPABILITY_ID,
        stream=CapabilityStream.BLOCK_CLOCK,
        columns=("block_hash", "block_ordinal", "block_time_ns", "transaction_count"),
        # Pass extraction range explicitly so fixture_dataset_spec receives a reviewable
        # block hash and block ordinal input in replay pack.
        extraction_range=_BENCHMARK_DECISION_RANGE,
        decision_range=_BENCHMARK_DECISION_RANGE,
        warmup_blocks=0,
    )
    snapshot_writer = artifacts.stage(ArtifactDraft(ArtifactKind.SNAPSHOT, ContentDigest("a" * 64)))
    # Assemble snapshot once so the replay pack workflow shares one value.
    snapshot = snapshot_writer.commit(
        canonical_json_bytes(fixture_snapshot_manifest(spec=dataset_spec, event_kind="BLOCK"))
    )
    snapshot_id = SnapshotId(snapshot.artifact_id.hex)
    events = tuple(_block_event(index) for index in range(5_000))
    # Assemble compiled once so the replay pack workflow shares one value.
    compiled = LocalNumpyReplayPackCompiler(
        artifacts,
        lambda requested: _source_for(requested, snapshot_id, events, dataset_spec),
        runtime_lock_id=RuntimeLockId("9" * 64),
    ).compile(snapshot_id, physical.COMPILER_VERSION)
    # Return the completed replay pack result without a hidden fallback.
    return artifacts, compiled.replay_pack_id


def _source_for(
    requested: SnapshotId,
    expected: SnapshotId,
    events: tuple[CanonicalEvent, ...],
    # Keep the dataset spec input explicit in the source for contract.
    dataset_spec: DatasetSpec,
) -> _CanonicalSource:
    # Execute the source for workflow in explicit, reviewable steps.
    if requested != expected:
        raise AssertionError("compiler requested another snapshot")
    return _CanonicalSource(events, dataset_spec)


def _block_event(index: int) -> BlockEvent:
    # Execute the block event workflow in explicit, reviewable steps.
    slot = 100 + index

    def digest(value: int) -> ContentDigest:
        return ContentDigest(f"{value:064x}")

    return BlockEvent(
        envelope=EventEnvelope(
            # Include position in the completed block event result.
            position=ChainPosition(
                network_id=SOLANA_MAINNET_NETWORK_ID,
                position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
                block_ordinal=slot,
                transaction_index=-1,
                # Pass event index explicitly so ChainPosition receives a reviewable
                # solana mainnet network id and block32 transaction32 position schema id
                # input in block event.
                event_index=0,
            ),
            transaction_group_id=digest(index + 1),
            source_record_id=digest(index + 1_000),
            canonical_event_id=digest(index + 2_000),
            # Include stable causal id in the completed block event result.
            stable_causal_id=digest(index + 3_000),
            capability_id=_BENCHMARK_CAPABILITY_ID,
            protocol="benchmark",
            protocol_version="1",
            ordering_fidelity=OrderingFidelity.INSTRUCTION_EXACT,
            # Complete EventEnvelope only after its benchmark and 1 inputs are visible in
            # block event.
        ),
        block_time_ns=slot * 1_000_000_000,
        tx_count=0,
        block_hash=None,
    )
