# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import pickle
from collections.abc import Iterator
from pathlib import Path

from backtest.adapters.columnar.numpy.compiler import LocalNumpyReplayPackCompiler

# Import layout at the visible module dependency boundary.
from backtest.adapters.columnar.numpy.layout import COMPILER_VERSION
from backtest.adapters.performance.replay import LocalExactBenchmarkRunner
from backtest.adapters.performance.targets import LocalExactBenchmarkSpecResolver
from backtest.adapters.results.job_completion import LocalJobResultReader
from backtest.application.benchmarks import (
    # Include benchmark equivalence kind so the benchmarks dependency remains explicit.
    BenchmarkEquivalenceKind,
    BenchmarkLaunchRoute,
    BenchmarkWorkload,
    CacheCondition,
    ExactBenchmarkCommand,
    # Include prove benchmark equivalence so the benchmarks dependency remains explicit.
    prove_benchmark_equivalence,
)
from backtest.application.models import ArtifactDraft, ArtifactKind, DatasetSpec
from backtest.application.replay_packs import ReplaySemanticsManifest
from backtest.application.run_drafts import ReferenceRunDraft

# Import run results at the visible module dependency boundary.
from backtest.application.run_results import RunComparisonProjection
from backtest.application.run_specs import AssetBalance
from backtest.application.use_cases.run_backtest import RunBacktestRequest
from backtest.bootstrap.benchmarks import (
    SpawnExactBenchmarkTargetFactory,
    # Include spawn run summary executor so the benchmarks dependency remains explicit.
    SpawnRunSummaryExecutor,
)
from backtest.bootstrap.build_tools import BuildToolBundleRegistry
from backtest.bootstrap.config import PathSettings, ResourceSettings, Settings
from backtest.bootstrap.execution_container import build_execution_container

# Import reference run resolver at the visible module dependency boundary.
from backtest.bootstrap.reference_run_resolver import ReferenceRunSpecResolver
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
)

# Import event hashing at the visible module dependency boundary.
from backtest.domain.event_hashing import canonical_event_stream_hash
from backtest.domain.execution import ExecutionMode
from backtest.domain.fidelity import OrderingFidelity
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import (
    # Include artifact id so the identifiers dependency remains explicit.
    ArtifactId,
    AssetId,
    CapabilityId,
    ContentDigest,
    DatasetRevisionId,
    # Include logical content hash so the identifiers dependency remains explicit.
    LogicalContentHash,
    PoolId,
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


# Define test production full backtest target is spawnable and two worker exact as one
# focused operation with an explicit boundary.
def test_production_full_backtest_target_is_spawnable_and_two_worker_exact(
    tmp_path: Path,
) -> None:
    # Execute the test production full backtest target is spawnable and two worker exact
    # workflow in explicit, reviewable steps.
    data_root = tmp_path / "var"
    settings = Settings(
        paths=PathSettings(data_root),
        resources=ResourceSettings(
            max_aggregate_child_memory_mb=1_024,
            # Pass max builder memory mb explicitly into ResourceSettings within test
            # production full backtest target is spawnable and two worker exact.
            max_builder_memory_mb=512,
            builder_peak_private_memory_mb=640,
            run_peak_private_memory_mb=256,
            max_parallel_runs=2,
            tmp_quota_gb=4,
            # Pass max run tmp gb explicitly into ResourceSettings within test production
            # full backtest target is spawnable and two worker exact.
            max_run_tmp_gb=1,
            max_run_output_gb=1,
            disk_low_watermark_gb=1,
            disk_emergency_watermark_gb=1,
            memory_safety_reserve_mb=128,
            # Pass page cache floor mb explicitly into ResourceSettings within test
            # production full backtest target is spawnable and two worker exact.
            page_cache_floor_mb=256,
            host_staging_output_reserve_mb=128,
            fixed_shared_overhead_mb=64,
        ),
    )
    # Assemble build tools once so the test production full backtest target is spawnable
    # and two worker exact workflow shares one value.
    build_tools = BuildToolBundleRegistry().pin()
    execution = build_execution_container(settings, build_tools=build_tools)
    artifacts = execution.artifacts
    snapshot_writer = artifacts.stage(ArtifactDraft(ArtifactKind.SNAPSHOT, ContentDigest("a" * 64)))
    snapshot = snapshot_writer.commit(canonical_json_bytes(fixture_snapshot_manifest()))
    # Assemble snapshot id once so the test production full backtest target is spawnable
    # and two worker exact workflow shares one value.
    snapshot_id = SnapshotId(snapshot.artifact_id.hex)
    events = tuple(_block_event(index) for index in range(8))
    replay = LocalNumpyReplayPackCompiler(
        artifacts,
        lambda requested: _source_for(requested, snapshot_id, events),
        # Pass runtime lock id explicitly so compile receives a reviewable snapshot id and
        # compiler version input in test production full backtest target is spawnable and
        # two worker exact.
        runtime_lock_id=execution.runtime_manifest.runtime_lock_id,
        build_tools=build_tools,
    ).compile(snapshot_id, COMPILER_VERSION)
    run_spec = ReferenceRunSpecResolver(
        artifacts,
        # Pass execution explicitly so ReferenceRunSpecResolver receives a reviewable
        # runtime lock id and runtime manifest input in test production full backtest
        # target is spawnable and two worker exact.
        execution.runtime_manifest.runtime_lock_id,
        parquet_memory_limit_mb=256,
        threads=1,
        build_tools=build_tools,
    ).resolve(
        # Keep the reference run draft and snapshot id ReferenceRunDraft step visible
        # while building run spec.
        ReferenceRunDraft(
            snapshot_id=snapshot_id,
            replay_pack_id=replay.replay_pack_id,
            delivery_schedule_id=None,
            pool_id=PoolId("absent-pool"),
            # Keep the sol AssetId step visible while building run spec.
            sold_asset_id=AssetId("SOL"),
            bought_asset_id=AssetId("TOKEN"),
            amount_in_atomic=1,
            minimum_amount_out_atomic=0,
            fee_bps=30,
            # Pass execution mode explicitly so ReferenceRunDraft receives a reviewable
            # absent-pool and sol input in test production full backtest target is
            # spawnable and two worker exact.
            execution_mode=ExecutionMode.SHADOW_STATE_REPLAY,
            maximum_order_input_atomic=1,
            observation_slots=0,
            order_slots=0,
            initial_portfolio=(AssetBalance(AssetId("SOL"), 10),),
            # Pass root seed explicitly so ReferenceRunDraft receives a reviewable absent-
            # pool and sol input in test production full backtest target is spawnable and
            # two worker exact.
            root_seed=7,
            maximum_dynamic_items=1_024,
        )
    )
    seed = execution.run_backtest.execute(
        # Keep the run spec RunBacktestRequest step visible while building seed.
        RunBacktestRequest(
            run_spec,
            ContentDigest("8" * 64),
            settings.replay.to_run_physical_settings(),
        )
        # Complete execute only after its 8 and to run physical settings inputs are visible in
        # test production full backtest target is spawnable and two worker exact.
    )
    resolver = LocalExactBenchmarkSpecResolver(
        data_root,
        execution.runtime_manifest.runtime_lock_id,
        duckdb_memory_limit_mb=256,
        # Pass build tools explicitly so LocalExactBenchmarkSpecResolver receives a
        # reviewable runtime lock id and runtime manifest input in test production full
        # backtest target is spawnable and two worker exact.
        build_tools=build_tools,
    )
    factory = SpawnExactBenchmarkTargetFactory(
        settings,
        execution.runtime_manifest.runtime_lock_id,
        # Keep spawn exact benchmark target factory, settings and runtime lock id visible
        # while completing SpawnExactBenchmarkTargetFactory within test production full
        # backtest target is spawnable and two worker exact.
        None,
    )
    expected_summary = (
        LocalJobResultReader(artifacts).successful_run_manifest(seed.artifact.artifact_id).summary
    )
    # Verify the from summary, expected summary and run comparison projection relationship
    # before this scenario is accepted.
    assert RunComparisonProjection.from_summary(
        SpawnRunSummaryExecutor(settings, None).execute_summary(
            run_spec,
            settings.replay.to_run_physical_settings(),
        )
        # Keep the run comparison projection expectation tied to from summary, expected
        # summary and run comparison projection in this scenario.
    ) == RunComparisonProjection.from_summary(expected_summary)
    assert pickle.loads(pickle.dumps(factory)) == factory
    runner = LocalExactBenchmarkRunner(
        data_root,
        private_memory_budget_mb=4_096,
        # Pass physical cores explicitly so LocalExactBenchmarkRunner receives a
        # reviewable data root and factory input in test production full backtest target
        # is spawnable and two worker exact.
        physical_cores=2,
        max_processes_by_io=2,
        target_factory=factory,
    )
    serial_spec = resolver.resolve(_command(seed.artifact.artifact_id, process_count=1))
    # Assemble parallel spec once so the test production full backtest target is spawnable
    # and two worker exact workflow shares one value.
    parallel_spec = resolver.resolve(_command(seed.artifact.artifact_id, process_count=2))

    serial = runner.run(serial_spec, ContentDigest("1" * 64))
    parallel = runner.run(parallel_spec, ContentDigest("2" * 64))
    direct = runner.run(
        resolver.resolve(_control_command(seed.artifact.artifact_id, BenchmarkLaunchRoute.DIRECT)),
        # Keep the content digest ContentDigest step visible while building direct.
        ContentDigest("4" * 64),
    )
    control = runner.run(
        resolver.resolve(_control_command(seed.artifact.artifact_id, BenchmarkLaunchRoute.CONTROL)),
        ContentDigest("5" * 64),
        # Complete run only after its 5 and resolve inputs are visible in test production full
        # backtest target is spawnable and two worker exact.
    )
    control_workspace_parent = data_root / "tmp" / "benchmark-control"

    assert serial.canonical_result_hash == seed.canonical_result_hash
    assert parallel.canonical_result_hash == serial.canonical_result_hash
    assert serial.samples[0].items_processed == 8
    # Verify the items processed, samples and parallel relationship before this scenario
    # is accepted.
    assert parallel.samples[0].items_processed == 16
    assert len(parallel.samples[0].worker_process_ids) == 2
    assert direct.canonical_result_hash == serial.canonical_result_hash
    assert direct.samples[0].items_processed == 8
    assert control.canonical_result_hash == direct.canonical_result_hash
    # Verify the kind, direct control and benchmark equivalence kind relationship before
    # this scenario is accepted.
    assert (
        prove_benchmark_equivalence(direct, control).kind is BenchmarkEquivalenceKind.DIRECT_CONTROL
    )
    assert not control_workspace_parent.exists() or not tuple(control_workspace_parent.iterdir())


def _command(artifact_id: ArtifactId, *, process_count: int) -> ExactBenchmarkCommand:
    # Execute the command workflow in explicit, reviewable steps.
    return ExactBenchmarkCommand(
        target_artifact_id=artifact_id,
        workload=BenchmarkWorkload.FULL_BACKTEST,
        launch_route=BenchmarkLaunchRoute.LOCAL_ARTIFACT,
        cache_condition=CacheCondition.WARM,
        # Pass batch rows explicitly so ExactBenchmarkCommand receives a reviewable 3 and
        # full backtest input in command.
        batch_rows=65_536,
        readahead=1,
        process_count=process_count,
        native_threads_per_process=1,
        warmup_iterations=0,
        # Pass measured iterations explicitly so ExactBenchmarkCommand receives a
        # reviewable 3 and full backtest input in command.
        measured_iterations=1,
        capacity_days=1,
        attempt_nonce=ContentDigest("3" * 64),
    )


def _control_command(
    # Keep the artifact id input explicit in the control command contract.
    artifact_id: ArtifactId,
    route: BenchmarkLaunchRoute,
) -> ExactBenchmarkCommand:
    # Execute the control command workflow in explicit, reviewable steps.
    return ExactBenchmarkCommand(
        target_artifact_id=artifact_id,
        workload=BenchmarkWorkload.CONTROL_PLANE_ROUND_TRIP,
        launch_route=route,
        cache_condition=CacheCondition.WARM,
        # Pass batch rows explicitly so ExactBenchmarkCommand receives a reviewable 6 and
        # control plane round trip input in control command.
        batch_rows=65_536,
        readahead=1,
        process_count=1,
        native_threads_per_process=1,
        warmup_iterations=0,
        # Pass measured iterations explicitly so ExactBenchmarkCommand receives a
        # reviewable 6 and control plane round trip input in control command.
        measured_iterations=1,
        capacity_days=1,
        attempt_nonce=ContentDigest("6" * 64),
    )


def _source_for(
    # Keep the requested input explicit in the source for contract.
    requested: SnapshotId,
    expected: SnapshotId,
    events: tuple[CanonicalEvent, ...],
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
