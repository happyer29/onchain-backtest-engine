# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

# Import repository at the visible module dependency boundary.
from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.adapters.columnar.numpy import LocalNumpyReplayPackCompiler
from backtest.adapters.columnar.numpy import layout as physical
from backtest.adapters.performance import replay as replay_module
from backtest.adapters.performance.publisher import LocalBenchmarkReportPublisher

# Import replay at the visible module dependency boundary.
from backtest.adapters.performance.replay import (
    OPTIMIZED_REDUCER_BENCHMARK_BUNDLE_ID,
    REFERENCE_REDUCER_BENCHMARK_BUNDLE_ID,
    REPLAY_SCAN_BENCHMARK_BUNDLE_ID,
    BenchmarkAdmissionError,
    # Include local replay benchmark runner so the replay dependency remains explicit.
    LocalReplayBenchmarkRunner,
    UnsupportedCacheConditionError,
)
from backtest.application.benchmarks import (
    BenchmarkSpec,
    # Include benchmark workload so the benchmarks dependency remains explicit.
    BenchmarkWorkload,
    BenchmarkWorkloadResult,
    CacheCondition,
)
from backtest.application.models import ArtifactDraft, ArtifactKind, DatasetSpec

# Import replay packs at the visible module dependency boundary.
from backtest.application.replay_packs import ReplaySemanticsManifest
from backtest.application.use_cases.run_replay_benchmark import RunReplayBenchmark
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
    # Close the chain import after its required symbols are visible.
)
from backtest.domain.event_hashing import canonical_event_stream_hash
from backtest.domain.fidelity import OrderingFidelity
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import (
    # Include artifact id so the identifiers dependency remains explicit.
    ArtifactId,
    CapabilityId,
    ContentDigest,
    DatasetRevisionId,
    LogicalContentHash,
    # Include replay pack id so the identifiers dependency remains explicit.
    ReplayPackId,
    RuntimeLockId,
    SnapshotId,
)
from backtest.domain.market_events import (
    # Include block event so the market events dependency remains explicit.
    BlockEvent,
    CanonicalEvent,
    ChainPosition,
    EventEnvelope,
)

# Import time at the visible module dependency boundary.
from backtest.domain.time import BlockRange
from backtest.engine.replay import ReplayBoundary
from backtest.runtime.resource_budget import HostCapacity
from tests.support.replay_v3 import (
    FIXTURE_DECISION_RANGE,
    fixture_dataset_spec,
    # Include fixture snapshot manifest so the replay v3 dependency remains explicit.
    fixture_snapshot_manifest,
)


# Keep the canonical source contract and validation rules together.
class _CanonicalSource:
    def __init__(self, events: tuple[CanonicalEvent, ...]) -> None:
        self._events = events

    @property
    def dataset_revision_id(self) -> DatasetRevisionId:
        # Return the completed canonical source dataset revision id result without a
        # hidden fallback.
        return DatasetRevisionId("d" * 64)

    @property
    def logical_content_hash(self) -> LogicalContentHash:
        return canonical_event_stream_hash(self._events)

    @property
    # Define canonical source replay semantics id as one focused operation with an
    # explicit boundary.
    def replay_semantics_id(self) -> ContentDigest:
        return ReplaySemanticsManifest.canonical_v3().replay_semantics_id

    @property
    def decision_range(self) -> BlockRange:
        return FIXTURE_DECISION_RANGE

    # Apply property semantics to the following canonical source dataset spec contract.
    @property
    def dataset_spec(self) -> DatasetSpec:
        return fixture_dataset_spec()

    def boundaries(self) -> tuple[ReplayBoundary, ...]:
        # Execute the canonical source boundaries workflow in explicit, reviewable steps.
        return tuple(
            ReplayBoundary.from_position(event.envelope.position) for event in self._events
        )

    def events(self) -> Iterator[CanonicalEvent]:
        yield from self._events


# Keep the closable target contract and validation rules together.
class _ClosableTarget:
    def __init__(self, *, fail: bool = False) -> None:
        # Execute the closable target init workflow in explicit, reviewable steps.
        self.fail = fail
        self.closed = False

    def execute_once(self) -> BenchmarkWorkloadResult:
        # Execute the closable target execute once workflow in explicit, reviewable steps.
        if self.fail:
            raise RuntimeError("target failed")
        return BenchmarkWorkloadResult(1, ContentDigest("1" * 64))

    def close(self) -> None:
        self.closed = True


# Define test worker closes target after observation and on failure as one focused
# operation with an explicit boundary.
def test_worker_closes_target_after_observation_and_on_failure() -> None:
    # Execute the test worker closes target after observation and on failure workflow in
    # explicit, reviewable steps.
    successful = _ClosableTarget()
    replay_module._WORKER_TARGET = replay_module._CapacityTarget(successful, 1)

    observation = replay_module._execute_worker(0, False, True)

    assert observation.finished_ns > observation.started_ns
    assert successful.closed
    # Verify replay_module._WORKER_TARGET is None before this scenario is accepted.
    assert replay_module._WORKER_TARGET is None

    failing = _ClosableTarget(fail=True)
    replay_module._WORKER_TARGET = replay_module._CapacityTarget(failing, 1)
    with pytest.raises(RuntimeError, match="target failed"):
        replay_module._execute_worker(0, False, False)
    # Verify failing.closed before this scenario is accepted.
    assert failing.closed
    assert replay_module._WORKER_TARGET is None


def test_physical_core_count_fails_closed_when_topology_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test physical core count fails closed when topology is unknown workflow
    # in explicit, reviewable steps.
    monkeypatch.setattr(replay_module.sys, "platform", "unknown")
    monkeypatch.setattr(replay_module.Path, "is_file", lambda _path: False)
    monkeypatch.setattr(replay_module.os, "cpu_count", lambda: 128)

    assert replay_module.physical_core_count() == 1


def test_capacity_scan_profiles_publish_exact_benchmark_artifact(tmp_path: Path) -> None:
    # Execute the test capacity scan profiles publish exact benchmark artifact workflow in
    # explicit, reviewable steps.
    artifacts, replay_pack_id = _replay_pack(tmp_path)
    spec = _spec(replay_pack_id.hex, capacity_days=7)
    runner = LocalReplayBenchmarkRunner(
        artifacts.data_root,
        private_memory_budget_mb=4_096,
        # Pass physical cores explicitly so LocalReplayBenchmarkRunner receives a
        # reviewable data root and artifacts input in test capacity scan profiles publish
        # exact benchmark artifact.
        physical_cores=4,
        max_processes_by_io=4,
    )

    published = RunReplayBenchmark(
        runner,
        # Keep the artifacts LocalBenchmarkReportPublisher step visible while building
        # published.
        LocalBenchmarkReportPublisher(artifacts),
    ).execute(spec, ContentDigest("f" * 64))

    assert published.report.base_events_per_day == 64
    assert published.report.samples[0].items_processed == 64 * 7
    assert published.report.profiler
    # Verify the admission private rss bytes per process, report and published
    # relationship before this scenario is accepted.
    assert published.report.admission_private_rss_bytes_per_process is not None
    assert published.artifact.kind is ArtifactKind.BENCHMARK
    assert tuple(item.hex for item in published.artifact.input_artifact_ids) == (
        replay_pack_id.hex,
    )
    # Assemble handle once so the test capacity scan profiles publish exact benchmark
    # artifact workflow shares one value.
    handle = artifacts.open_committed(published.artifact.artifact_id)
    try:
        # Perform the protected test capacity scan profiles publish exact benchmark
        # artifact operation before explicit failure handling.
        with handle.open_binary("report.json") as stream:
            document = json.load(stream)
    finally:
        handle.close()
    assert document["report_digest"] == published.report.report_digest.hex


# Define test reference reducer is hash equivalent across batch and readahead as one
# focused operation with an explicit boundary.
def test_reference_reducer_is_hash_equivalent_across_batch_and_readahead(
    tmp_path: Path,
) -> None:
    # Execute the test reference reducer is hash equivalent across batch and readahead
    # workflow in explicit, reviewable steps.
    artifacts, replay_pack_id = _replay_pack(tmp_path)
    runner = LocalReplayBenchmarkRunner(
        artifacts.data_root,
        private_memory_budget_mb=4_096,
        physical_cores=4,
        # Pass max processes by io explicitly so LocalReplayBenchmarkRunner receives a
        # reviewable data root and artifacts input in test reference reducer is hash
        # equivalent across batch and readahead.
        max_processes_by_io=4,
    )
    first = runner.run(
        _spec(
            replay_pack_id.hex,
            # Pass workload explicitly so _spec receives a reviewable hex and reference
            # reducer input in test reference reducer is hash equivalent across batch and
            # readahead.
            workload=BenchmarkWorkload.REFERENCE_REDUCER,
            capacity_days=1,
            batch_rows=32_768,
            readahead=1,
        )
        # Complete run only after its hex and reference reducer inputs are visible in test
        # reference reducer is hash equivalent across batch and readahead.
    )
    second = runner.run(
        _spec(
            replay_pack_id.hex,
            workload=BenchmarkWorkload.REFERENCE_REDUCER,
            # Pass capacity days explicitly so _spec receives a reviewable hex and
            # reference reducer input in test reference reducer is hash equivalent across
            # batch and readahead.
            capacity_days=1,
            batch_rows=262_144,
            readahead=4,
        )
    )

    # Verify the canonical result hash, first and second relationship before this scenario
    # is accepted.
    assert first.canonical_result_hash == second.canonical_result_hash
    assert first.samples[0].items_processed == 64
    assert first.profiler[0].cumulative_time_ns > 0


def test_optimized_reducer_is_reference_equivalent_across_batch_and_readahead(
    tmp_path: Path,
    # Close the test optimized reducer is reference equivalent across batch and readahead
    # signature after its explicit inputs.
) -> None:
    # Execute the test optimized reducer is reference equivalent across batch and
    # readahead workflow in explicit, reviewable steps.
    artifacts, replay_pack_id = _replay_pack(tmp_path)
    runner = LocalReplayBenchmarkRunner(
        artifacts.data_root,
        private_memory_budget_mb=4_096,
        physical_cores=4,
        # Pass max processes by io explicitly so LocalReplayBenchmarkRunner receives a
        # reviewable data root and artifacts input in test optimized reducer is reference
        # equivalent across batch and readahead.
        max_processes_by_io=4,
    )
    reference = runner.run(
        _spec(
            replay_pack_id.hex,
            # Pass workload explicitly so _spec receives a reviewable hex and reference
            # reducer input in test optimized reducer is reference equivalent across batch
            # and readahead.
            workload=BenchmarkWorkload.REFERENCE_REDUCER,
            capacity_days=1,
            batch_rows=65_536,
            readahead=1,
        )
        # Complete run only after its hex and reference reducer inputs are visible in test
        # optimized reducer is reference equivalent across batch and readahead.
    )
    optimized = runner.run(
        _spec(
            replay_pack_id.hex,
            workload=BenchmarkWorkload.OPTIMIZED_REDUCER,
            # Pass capacity days explicitly so _spec receives a reviewable hex and
            # optimized reducer input in test optimized reducer is reference equivalent
            # across batch and readahead.
            capacity_days=1,
            batch_rows=262_144,
            readahead=4,
        )
    )

    # Verify the items processed, samples and optimized relationship before this scenario
    # is accepted.
    assert optimized.samples[0].items_processed == 64
    assert optimized.samples[0].canonical_result_hash == (
        reference.samples[0].canonical_result_hash
    )


def test_scan_semantic_hash_is_identical_for_serial_and_two_independent_workers(
    # Keep the tmp path input explicit in the test scan semantic hash is identical for
    # serial and two independent workers contract.
    tmp_path: Path,
) -> None:
    # Execute the test scan semantic hash is identical for serial and two independent
    # workers workflow in explicit, reviewable steps.
    artifacts, replay_pack_id = _replay_pack(tmp_path)
    runner = LocalReplayBenchmarkRunner(
        artifacts.data_root,
        private_memory_budget_mb=4_096,
        physical_cores=2,
        # Pass max processes by io explicitly so LocalReplayBenchmarkRunner receives a
        # reviewable data root and artifacts input in test scan semantic hash is identical
        # for serial and two independent workers.
        max_processes_by_io=2,
    )

    serial = runner.run(_spec(replay_pack_id.hex, process_count=1))
    parallel = runner.run(_spec(replay_pack_id.hex, process_count=2))

    assert parallel.canonical_result_hash == serial.canonical_result_hash
    # Verify the items processed, samples and serial relationship before this scenario is
    # accepted.
    assert serial.samples[0].items_processed == 64
    assert parallel.samples[0].items_processed == 128
    assert len(parallel.samples[0].worker_process_ids) == 2


def test_process_admission_and_cold_cache_fail_closed(tmp_path: Path) -> None:
    # Execute the test process admission and cold cache fail closed workflow in explicit,
    # reviewable steps.
    artifacts, replay_pack_id = _replay_pack(tmp_path)
    runner = LocalReplayBenchmarkRunner(
        artifacts.data_root,
        private_memory_budget_mb=4_096,
        physical_cores=4,
        # Pass max processes by io explicitly so LocalReplayBenchmarkRunner receives a
        # reviewable data root and artifacts input in test process admission and cold
        # cache fail closed.
        max_processes_by_io=2,
    )

    with pytest.raises(BenchmarkAdmissionError, match="allows 2"):
        runner.run(_spec(replay_pack_id.hex, process_count=4))
    with pytest.raises(UnsupportedCacheConditionError, match="unavailable"):
        # Keep raises, unsupported cache condition error and pytest active only for the
        # bounded test process admission and cold cache fail closed operation.
        runner.run(
            _spec(
                replay_pack_id.hex,
                cache_condition=CacheCondition.EXTERNALLY_COLD,
            )
            # Complete run only after its hex and externally cold inputs are visible in test
            # process admission and cold cache fail closed.
        )


def test_measured_capacity_is_resolved_after_workload_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts, replay_pack_id = _replay_pack(tmp_path)
    order: list[str] = []

    def profile(_: object) -> replay_module._WorkerObservation:
        order.append("profile")
        return replay_module._WorkerObservation(
            process_id=1,
            started_ns=1,
            finished_ns=2,
            result=BenchmarkWorkloadResult(1, ContentDigest("1" * 64)),
            cpu_time_ns=1,
            peak_total_rss_bytes=2 * 1024**2,
            peak_private_rss_bytes=2 * 1024**2,
            private_rss_basis=replay_module.PrivateRssBasis.TOTAL_RSS_CONSERVATIVE_FALLBACK,
            minor_faults=0,
            major_faults=0,
            block_input_operations=0,
            block_output_operations=0,
            swap_operations=0,
            storage_read_bytes=None,
            storage_write_bytes=None,
            io_counter_basis=replay_module.IoCounterBasis.UNAVAILABLE,
        )

    def capacity() -> HostCapacity:
        order.append("capacity")
        return HostCapacity(private_memory_mb=1, physical_cores=1, max_processes_by_io=1)

    runner = LocalReplayBenchmarkRunner(
        artifacts.data_root,
        private_memory_budget_mb=4_096,
        physical_cores=4,
        max_processes_by_io=4,
        capacity_provider=capacity,
    )
    monkeypatch.setattr(runner, "_run_profile", profile)

    with pytest.raises(BenchmarkAdmissionError, match="allows 0"):
        runner.run(_spec(replay_pack_id.hex))

    assert order == ["profile", "capacity"]


def _spec(
    replay_pack_id: str,
    *,
    workload: BenchmarkWorkload = BenchmarkWorkload.REPLAY_PACK_SCAN,
    # Keep the capacity days input explicit in the spec contract.
    capacity_days: int = 1,
    batch_rows: int = 65_536,
    readahead: int = 1,
    process_count: int = 1,
    cache_condition: CacheCondition = CacheCondition.WARM,
    # Keep the benchmark spec input explicit in the spec contract.
) -> BenchmarkSpec:
    # Execute the spec workflow in explicit, reviewable steps.
    bundle = {
        BenchmarkWorkload.REPLAY_PACK_SCAN: REPLAY_SCAN_BENCHMARK_BUNDLE_ID,
        BenchmarkWorkload.REFERENCE_REDUCER: REFERENCE_REDUCER_BENCHMARK_BUNDLE_ID,
        BenchmarkWorkload.OPTIMIZED_REDUCER: OPTIMIZED_REDUCER_BENCHMARK_BUNDLE_ID,
    }[workload]
    # Return the completed spec result without a hidden fallback.
    return BenchmarkSpec(
        workload=workload,
        input_artifact_ids=(ArtifactId(replay_pack_id),),
        workload_bundle_id=bundle,
        runtime_lock_id=RuntimeLockId("9" * 64),
        # Pass cache condition explicitly so BenchmarkSpec receives a reviewable 9 and
        # artifact id input in spec.
        cache_condition=cache_condition,
        batch_rows=batch_rows,
        readahead=readahead,
        process_count=process_count,
        native_threads_per_process=1,
        # Pass warmup iterations explicitly so BenchmarkSpec receives a reviewable 9 and
        # artifact id input in spec.
        warmup_iterations=0,
        measured_iterations=1,
        capacity_days=capacity_days,
    )


def _replay_pack(tmp_path: Path) -> tuple[LocalArtifactRepository, ReplayPackId]:
    # Execute the replay pack workflow in explicit, reviewable steps.
    artifacts = LocalArtifactRepository(tmp_path / "var")
    snapshot_writer = artifacts.stage(ArtifactDraft(ArtifactKind.SNAPSHOT, ContentDigest("a" * 64)))
    snapshot = snapshot_writer.commit(canonical_json_bytes(fixture_snapshot_manifest()))
    snapshot_id = SnapshotId(snapshot.artifact_id.hex)
    events = tuple(_block_event(index) for index in range(64))
    # Assemble compiled once so the replay pack workflow shares one value.
    compiled = LocalNumpyReplayPackCompiler(
        artifacts,
        lambda requested: _source_for(requested, snapshot_id, events),
        runtime_lock_id=RuntimeLockId("9" * 64),
    ).compile(snapshot_id, physical.COMPILER_VERSION)
    # Return the completed replay pack result without a hidden fallback.
    return artifacts, compiled.replay_pack_id


def _source_for(
    requested: SnapshotId,
    expected: SnapshotId,
    events: tuple[CanonicalEvent, ...],
    # Keep the canonical source input explicit in the source for contract.
) -> _CanonicalSource:
    # Execute the source for workflow in explicit, reviewable steps.
    if requested != expected:
        raise AssertionError("compiler requested another snapshot")
    return _CanonicalSource(events)


def _block_event(index: int) -> BlockEvent:
    # Execute the block event workflow in explicit, reviewable steps.
    block_ordinal = index

    def digest(value: int) -> ContentDigest:
        return ContentDigest(f"{value:064x}")

    return BlockEvent(
        envelope=EventEnvelope(
            # Include position in the completed block event result.
            position=ChainPosition(
                network_id=SOLANA_MAINNET_NETWORK_ID,
                position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
                block_ordinal=block_ordinal,
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
            capability_id=CapabilityId("benchmark.blocks.v1"),
            protocol="benchmark",
            protocol_version="1",
            ordering_fidelity=OrderingFidelity.INSTRUCTION_EXACT,
            # Complete EventEnvelope only after its v1 and benchmark inputs are visible in
            # block event.
        ),
        block_time_ns=block_ordinal * 1_000_000_000,
        tx_count=0,
        block_hash=None,
    )
