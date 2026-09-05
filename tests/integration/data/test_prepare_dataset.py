# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing

# Import dataclasses at the visible module dependency boundary.
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pyarrow as pa

# Import parquet at the visible module dependency boundary.
import pyarrow.parquet as pq
import pytest

import backtest.adapters.columnar.arrow.parquet_replay as parquet_replay_module
from backtest.adapters.artifacts.localfs import (
    DataRootLayout,
    LocalArtifactRepository,
    LocalCommittedArtifactScanner,
    # Include local completion receipt store so the localfs dependency remains explicit.
    LocalCompletionReceiptStore,
)
from backtest.adapters.artifacts.localfs.repository import (
    ArtifactIntegrityError,
    ArtifactNotCommittedError,
    # Close the repository import after its required symbols are visible.
)
from backtest.adapters.artifacts.source_inspection import ArtifactSourceInspectionLoader
from backtest.adapters.catalog.sqlite import (
    SQLiteArtifactCatalog,
    SQLiteCanonicalOutputObserver,
    SQLiteJobQueue,
    SQLiteRetentionRootProvider,
    # Include sqlite shard ledger so the sqlite dependency remains explicit.
    SQLiteShardLedger,
)
from backtest.adapters.columnar.arrow import (
    CanonicalParquetReplaySource,
    GapSafePrepareDatasetJobResolver,
    # Include local arrow canonical store so the arrow dependency remains explicit.
    LocalArrowCanonicalStore,
)
from backtest.adapters.columnar.arrow.canonical import (
    CanonicalDataError,
    canonical_distribution_build_key,
    canonical_writer_bundle_id,
)
from backtest.adapters.columnar.arrow.parquet_replay import (
    CanonicalDistributionCandidateSource,
)
from backtest.adapters.columnar.numpy import (
    NUMPY_MMAP_FIRST_SWAP_BACKEND,
    # Include numpy replay compiler version so the numpy dependency remains explicit.
    NUMPY_REPLAY_COMPILER_VERSION,
    LocalNumpyReplayPackCompiler,
    NumpyMmapFirstSwapEngine,
    NumpyMmapReplaySource,
)

# Import delivery schedule at the visible module dependency boundary.
from backtest.adapters.delivery_schedule import LocalDeliveryScheduleSourceFactory
from backtest.adapters.delivery_schedule.numpy import LocalNumpyDeliveryScheduleCompiler
from backtest.adapters.delivery_schedule.numpy.layout import (
    COMPILER_VERSION as DELIVERY_COMPILER_VERSION,
)

# Import replay at the visible module dependency boundary.
from backtest.adapters.replay import LocalReplaySourceFactory
from backtest.adapters.results import (
    LocalJobResultError,
    LocalJobResultReader,
    LocalParquetRunOutputStore,
    # Close the results import after its required symbols are visible.
)
from backtest.adapters.source.in_memory import InMemorySourceReader
from backtest.application.code_bundles import PinnedCodeBundleSet
from backtest.application.completion import CompletionOutput
from backtest.application.delivery_schedules import CompileDeliveryScheduleRequest

# Import job commands at the visible module dependency boundary.
from backtest.application.job_commands import (
    PrepareDatasetJobDraft,
    ResolvedBacktestJob,
    ResolvedCompileReplayJob,
    ResolvedPrepareDatasetJob,
    # Include resolved sweep job so the job commands dependency remains explicit.
    ResolvedSweepJob,
    ReusableCanonicalDistribution,
    resolved_prepare_dataset_job_from_bytes,
)
from backtest.application.ml_contracts import ExactInferencePolicy
from backtest.application.models import (
    # Include artifact draft so the models dependency remains explicit.
    ArtifactDraft,
    ArtifactKind,
    AttemptState,
    BudgetLimits,
    CapabilityCutEvidence,
    # Include capability descriptor so the models dependency remains explicit.
    CapabilityDescriptor,
    CapabilityStream,
    CommittedArtifact,
    DataRequirement,
    DatasetPlan,
    # Include dataset planning policy so the models dependency remains explicit.
    DatasetPlanningPolicy,
    DatasetSpec,
    JobAttempt,
    JobType,
    PlanDatasetRequest,
    # Include query limits so the models dependency remains explicit.
    QueryLimits,
    RequirementOrigin,
    SourceMetadata,
    dataset_spec_identity_digest,
)

# Import run drafts at the visible module dependency boundary.
from backtest.application.run_drafts import ReferenceRunDraft
from backtest.application.run_results import RunBackend, RunPhysicalSettings
from backtest.application.run_specs import (
    AssetBalance,
    ReplayInputFormat,
    # Include resolved component so the run specs dependency remains explicit.
    ResolvedComponent,
    ResolvedReplayInput,
    ResolvedRunSpec,
)
from backtest.application.sweeps import ResolvedSweepSpec, SweepEntry

# Import compile delivery schedule at the visible module dependency boundary.
from backtest.application.use_cases.compile_delivery_schedule import CompileDeliverySchedule
from backtest.application.use_cases.compile_replay import CompileReplay, CompileReplayRequest
from backtest.application.use_cases.inspect_source import InspectSource, InspectSourceRequest
from backtest.application.use_cases.plan_dataset import PlanDataset
from backtest.application.use_cases.prepare_dataset import (
    # Include prepare dataset so the prepare dataset dependency remains explicit.
    PrepareDataset,
    PrepareDatasetRequest,
)
from backtest.application.use_cases.run_backtest import (
    RunBacktest,
    # Include run backtest request so the run backtest dependency remains explicit.
    RunBacktestRequest,
    RunPreflightError,
)
from backtest.application.use_cases.store_source_inspection import StoreSourceInspection
from backtest.application.use_cases.submit_job import SubmitJobRequest

# Import build tools at the visible module dependency boundary.
from backtest.bootstrap.build_tools import BuildToolBundleRegistry
from backtest.bootstrap.canonical_reconciliation import (
    CanonicalShardIndexReconciler,
    ReconciledPrepareDatasetSubmitJob,
)
from backtest.bootstrap.cli import RuntimeCliBackend
from backtest.bootstrap.config import PathSettings, ResourceSettings, Settings
from backtest.bootstrap.container import build_runtime_container
from backtest.bootstrap.reference_bundles import ReferenceBundleRegistry

# Import reference run resolver at the visible module dependency boundary.
from backtest.bootstrap.reference_run_resolver import (
    ReferenceRunResolutionError,
    ReferenceRunSpecResolver,
)
from backtest.bootstrap.runtime_plugins import ReferenceRuntimeComponentsResolver

# Import supervisor at the visible module dependency boundary.
from backtest.bootstrap.supervisor import build_single_host_supervisor
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
)

# Import execution at the visible module dependency boundary.
from backtest.domain.execution import ExecutionMode
from backtest.domain.fidelity import (
    ChainFinality,
    FeesFidelity,
    IdentityFidelity,
    # Include ingestion completeness so the fidelity dependency remains explicit.
    IngestionCompleteness,
    OrderingFidelity,
    SourceConsistency,
    SourceFidelity,
    StateFidelity,
    # Close the fidelity import after its required symbols are visible.
)
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.domain.identifiers import (
    ArtifactId,
    AssetId,
    # Include bundle id so the identifiers dependency remains explicit.
    BundleId,
    CapabilityId,
    ContentDigest,
    DeliveryScheduleId,
    PoolId,
    # Include runtime lock id so the identifiers dependency remains explicit.
    RuntimeLockId,
    SourceId,
)
from backtest.domain.time import BlockRange
from backtest.engine import (
    # Include reference backtest engine so the engine dependency remains explicit.
    ReferenceBacktestEngine,
    ReferenceRunConfig,
    RunSummary,
    SlotLatencyModel,
)

# Import replay at the visible module dependency boundary.
from backtest.engine.replay import HistoricalEventSource
from backtest.engine.rng import RNG_ALGORITHM
from backtest.plugins.execution import ConstantProductExecutionModel
from backtest.plugins.protocols.reference import (
    ProjectionKind,
    # Include projection spec so the reference dependency remains explicit.
    ProjectionSpec,
    ReferenceProtocolProjector,
)
from backtest.plugins.risk import StaticRiskPolicy
from backtest.plugins.strategies import FirstSwapStrategy

# Import controller lock at the visible module dependency boundary.
from backtest.runtime.controller_lock import ControllerLock
from backtest.runtime.file_locks import FileLock, LockMode, LockUnavailableError
from backtest.runtime.host_resources import HostMemoryMeasurement, HostSwapMeasurement

BLOCKS = CapabilityId("solana.blocks.v1")
CREATIONS = CapabilityId("reference.token-creations.v1")
SWAPS = CapabilityId("reference.swaps.v1")


@pytest.mark.integration
def test_prepare_retry_recovers_committed_orphan_distribution_without_remote_rescan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A child death after shard commit cannot force an identical remote extraction."""

    source, descriptor = _identity_source(
        (_identity_swap_row(signature="orphan", transaction_index=1),),
        identity=IdentityFidelity.EXACT,
        total_key=("slot", "transaction_index", "event_index", "signature"),
        batch_size=1,
        cut_evidence=_strong_cut(to_block=101),
    )
    data_root = tmp_path / "var"
    artifacts = LocalArtifactRepository(data_root)
    plan = _identity_plan(source, artifacts, descriptor)
    projector = _identity_projector(descriptor)
    first_store = LocalArrowCanonicalStore(artifacts, memory_limit_mb=256)

    def fail_before_snapshot(**_: object) -> None:
        raise RuntimeError("simulated child death before snapshot publication")

    monkeypatch.setattr(first_store, "publish_snapshot", fail_before_snapshot)
    with pytest.raises(RuntimeError, match="simulated child death"):
        PrepareDataset(source, projector, first_store).execute(PrepareDatasetRequest(plan))

    discovered = LocalCommittedArtifactScanner(artifacts).scan()
    orphan = next(
        artifact for artifact in discovered if artifact.kind is ArtifactKind.CANONICAL_DISTRIBUTION
    )
    assert not any(artifact.kind is ArtifactKind.SNAPSHOT for artifact in discovered)

    database = data_root / "catalog" / "catalog.sqlite"
    catalog = SQLiteArtifactCatalog(database, artifacts)
    ledger = SQLiteShardLedger(database, catalog)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """
            INSERT INTO jobs (
                job_id, command_type, idempotency_key, request_digest,
                resolved_spec, state, state_version, cancel_requested,
                current_attempt_id, submitted_at_ns, updated_at_ns
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                "job_failed_prepare",
                JobType.PREPARE_DATASET.value,
                "failed-prepare",
                "f" * 64,
                b"failed-spec",
                AttemptState.FAILED.value,
                7,
                0,
                1,
                2,
            ),
        )
        connection.commit()
        failed_job_before = connection.execute(
            "SELECT * FROM jobs WHERE job_id = 'job_failed_prepare'"
        ).fetchone()
    finally:
        connection.close()
    receipt_root = data_root / "job_receipts"
    receipts_before = tuple(receipt_root.iterdir()) if receipt_root.exists() else ()

    reconciler = CanonicalShardIndexReconciler(
        artifacts,
        catalog,
        SQLiteCanonicalOutputObserver(artifacts, ledger),
    )
    queue = SQLiteJobQueue(
        database,
        backup_cut_lock_path=artifacts.locks_root / "backup-cut.lock",
    )
    original_submit = queue._submit

    def assert_retention_lock(spec: Any, idempotency_key: str) -> Any:
        with pytest.raises(LockUnavailableError):
            FileLock(
                artifacts.locks_root / "retention.lock",
                mode=LockMode.EXCLUSIVE,
                timeout=0,
            ).acquire()
        return original_submit(spec, idempotency_key)

    monkeypatch.setattr(queue, "_submit", assert_retention_lock)
    submitter = ReconciledPrepareDatasetSubmitJob(
        queue,
        GapSafePrepareDatasetJobResolver(ledger, projector),
        reconciler,
    )
    request = SubmitJobRequest(
        1,
        JobType.PREPARE_DATASET,
        PrepareDatasetJobDraft(plan).canonical_bytes(),
        "recovered-prepare",
    )
    job = submitter.execute(request)
    resolved = resolved_prepare_dataset_job_from_bytes(job.spec.canonical_payload)

    assert resolved.reusable_distributions == (
        ReusableCanonicalDistribution(0, orphan.artifact_id),
    )
    assert submitter.execute(request) == job
    assert set(SQLiteRetentionRootProvider(database).retained_roots()) == {
        plan.spec.source_inspection_artifact_id,
        orphan.artifact_id,
    }
    assert catalog.find_committed(plan.spec.source_inspection_artifact_id) is not None
    assert catalog.find_committed(orphan.artifact_id) == orphan
    assert not any(
        artifact.kind is ArtifactKind.SNAPSHOT
        for artifact in LocalCommittedArtifactScanner(artifacts).scan()
    )
    connection = sqlite3.connect(database)
    try:
        failed_job_after = connection.execute(
            "SELECT * FROM jobs WHERE job_id = 'job_failed_prepare'"
        ).fetchone()
    finally:
        connection.close()
    assert failed_job_after == failed_job_before
    assert (tuple(receipt_root.iterdir()) if receipt_root.exists() else ()) == receipts_before

    source_probe = _ScanProbe(source, fail_on_scan=True)
    prepared = PrepareDataset(
        source_probe,
        projector,
        LocalArrowCanonicalStore(artifacts, memory_limit_mb=256),
    ).execute(PrepareDatasetRequest(plan, resolved.reusable_distributions))
    assert source_probe.shard_ordinals == []
    assert prepared.distributions[0].artifact == orphan


@pytest.mark.integration
def test_canonical_shard_reconciliation_rejects_corrupt_committed_candidate(
    tmp_path: Path,
) -> None:
    source, descriptor = _identity_source(
        (_identity_swap_row(signature="corrupt-orphan", transaction_index=1),),
        identity=IdentityFidelity.EXACT,
        total_key=("slot", "transaction_index", "event_index", "signature"),
        batch_size=1,
        cut_evidence=_strong_cut(to_block=101),
    )
    data_root = tmp_path / "var"
    artifacts = LocalArtifactRepository(data_root)
    plan = _identity_plan(source, artifacts, descriptor)
    projector = _identity_projector(descriptor)
    prepared = PrepareDataset(
        source,
        projector,
        LocalArrowCanonicalStore(artifacts, memory_limit_mb=256),
    ).execute(PrepareDatasetRequest(plan))
    distribution = prepared.distributions[0].artifact
    handle = artifacts.open_committed(distribution.artifact_id)
    try:
        events_path = cast(Any, handle).local_path("events.parquet")
    finally:
        handle.close()
    events_path.write_bytes(b"corrupt")

    database = data_root / "catalog" / "catalog.sqlite"
    catalog = SQLiteArtifactCatalog(database, artifacts)
    ledger = SQLiteShardLedger(database, catalog)
    reconciler = CanonicalShardIndexReconciler(
        artifacts,
        catalog,
        SQLiteCanonicalOutputObserver(artifacts, ledger),
    )

    with pytest.raises(ArtifactIntegrityError, match="payload differs"):
        reconciler.reconcile()
    connection = sqlite3.connect(database)
    try:
        shard_count = connection.execute("SELECT COUNT(*) FROM shard_ledger").fetchone()
    finally:
        connection.close()
    assert shard_count == (0,)
    assert catalog.find_committed(distribution.artifact_id) is None


# Apply integration semantics to the following test verified prepare outputs advance each
# gap safe shard frontier contract.
@pytest.mark.integration
def test_verified_prepare_outputs_advance_each_gap_safe_shard_frontier(
    tmp_path: Path,
) -> None:
    # Execute the test verified prepare outputs advance each gap safe shard frontier
    # workflow in explicit, reviewable steps.
    data_root = tmp_path / "var"
    source = _source()
    artifacts = LocalArtifactRepository(data_root)
    inspection = StoreSourceInspection(
        InspectSource(source, now=lambda: datetime(2025, 12, 31, tzinfo=UTC)),
        # Pass artifacts explicitly so execute receives a reviewable fixture-indexer and
        # inspect source request input in test verified prepare outputs advance each gap
        # safe shard frontier.
        artifacts,
    ).execute(InspectSourceRequest(SourceId("fixture-indexer")))
    plan = PlanDataset(
        ArtifactSourceInspectionLoader(artifacts),
        _planning_policy(),
        # Keep the artifact id _plan_request step visible while building plan.
    ).execute(_plan_request(inspection.artifact.artifact_id))
    prepared = PrepareDataset(
        source,
        _projector(),
        LocalArrowCanonicalStore(artifacts, memory_limit_mb=256),
        # Keep the datetime and utc datetime step visible while building prepared.
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    ).execute(PrepareDatasetRequest(plan))
    database = data_root / "catalog" / "catalog.sqlite"
    catalog = SQLiteArtifactCatalog(database, artifacts)
    for distribution in prepared.distributions:
        # Invoke index_committed for artifact and distribution as a visible test verified
        # prepare outputs advance each gap safe shard frontier step.
        catalog.index_committed(distribution.artifact)
    ledger = SQLiteShardLedger(database, catalog)
    observer = SQLiteCanonicalOutputObserver(artifacts, ledger)

    outputs = tuple(item.artifact for item in prepared.distributions)
    observer.observe(outputs)
    # Invoke observe for outputs as a visible test verified prepare outputs advance each
    # gap safe shard frontier step.
    observer.observe(outputs)

    schema_versions = {item.capability_id: item.schema_version for item in plan.spec.capabilities}
    for capability_id in (BLOCKS, CREATIONS, SWAPS):
        # Process (BLOCKS, CREATIONS, SWAPS) inside the bounded test verified prepare
        # outputs advance each gap safe shard frontier loop.
        frontier = ledger.contiguous_frontier(
            source_id=SourceId("fixture-indexer"),
            capability_id=capability_id,
            capability_schema_version=schema_versions[capability_id],
            network_id=SOLANA_MAINNET_NETWORK_ID,
            # Pass position schema id explicitly so contiguous_frontier receives a
            # reviewable fixture-indexer and source id input in test verified prepare
            # outputs advance each gap safe shard frontier.
            position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            coverage_from_block_ordinal=100,
        )
        assert frontier.frontier_block_ordinal == 102


@pytest.mark.integration
# Define test direct and queued compile replay share exact child result and receipt as one
# focused operation with an explicit boundary.
def test_direct_and_queued_compile_replay_share_exact_child_result_and_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test direct and queued compile replay share exact child result and
    # receipt workflow in explicit, reviewable steps.
    monkeypatch.setattr(
        "backtest.bootstrap.supervisor.measure_host_memory",
        lambda: HostMemoryMeasurement(16 * 1024**3, 12 * 1024**3, 256 * 1024**2),
    )
    monkeypatch.setattr(
        # Pass version tag explicitly so setattr receives a reviewable measure host swap
        # and host swap measurement input in test direct and queued compile replay share
        # exact child result and receipt.
        "backtest.adapters.process.local.measure_host_swap",
        lambda: HostSwapMeasurement(0, 0),
    )
    data_root = tmp_path / "var"
    source = _source()
    # Assemble artifacts once so the test direct and queued compile replay share exact
    # child result and receipt workflow shares one value.
    artifacts = LocalArtifactRepository(data_root)
    stored_inspection = StoreSourceInspection(
        InspectSource(source, now=lambda: datetime(2025, 12, 31, tzinfo=UTC)),
        artifacts,
    ).execute(InspectSourceRequest(SourceId("fixture-indexer")))
    # Assemble plan once so the test direct and queued compile replay share exact child
    # result and receipt workflow shares one value.
    plan = PlanDataset(
        ArtifactSourceInspectionLoader(artifacts),
        _planning_policy(),
    ).execute(_plan_request(stored_inspection.artifact.artifact_id))
    build_tools = BuildToolBundleRegistry().pin()
    # Assemble prepared once so the test direct and queued compile replay share exact
    # child result and receipt workflow shares one value.
    prepared = PrepareDataset(
        source,
        _projector(build_tools=build_tools),
        LocalArrowCanonicalStore(
            artifacts,
            # Pass memory limit mb explicitly so LocalArrowCanonicalStore receives a
            # reviewable artifacts and build tools input in test direct and queued compile
            # replay share exact child result and receipt.
            memory_limit_mb=256,
            build_tools=build_tools,
        ),
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    ).execute(PrepareDatasetRequest(plan))
    # Assemble settings once so the test direct and queued compile replay share exact
    # child result and receipt workflow shares one value.
    settings = Settings(
        paths=PathSettings(data_root=data_root),
        resources=ResourceSettings(
            max_builder_memory_mb=256,
            max_parallel_runs=1,
            # Pass tmp quota gb explicitly into ResourceSettings within test direct and
            # queued compile replay share exact child result and receipt.
            tmp_quota_gb=1,
            disk_low_watermark_gb=1,
            disk_emergency_watermark_gb=1,
            native_threads_per_process=1,
        ),
        # Complete Settings only after its path settings and resource settings inputs are
        # visible in test direct and queued compile replay share exact child result and
        # receipt.
    )
    config_path = tmp_path / "local.toml"
    config_path.write_text(
        "[paths]\n"
        f"data_root = {json.dumps(str(data_root))}\n"
        # Pass resources n explicitly so write_text receives a reviewable [paths] data
        # root = and utf-8 input in test direct and queued compile replay share exact
        # child result and receipt.
        "[resources]\n"
        "max_builder_memory_mb = 256\n"
        "max_parallel_runs = 1\n"
        "tmp_quota_gb = 1\n"
        "disk_low_watermark_gb = 1\n"
        # Pass disk emergency watermark gb n explicitly so write_text receives a
        # reviewable [paths] data root = and utf-8 input in test direct and queued compile
        # replay share exact child result and receipt.
        "disk_emergency_watermark_gb = 1\n"
        "native_threads_per_process = 1\n",
        encoding="utf-8",
    )
    container = build_runtime_container(settings, profile="child-integration")
    # Assemble direct once so the test direct and queued compile replay share exact child
    # result and receipt workflow shares one value.
    direct = RuntimeCliBackend(container, config_path).compile_replay(
        CompileReplayRequest(prepared.snapshot_id, NUMPY_REPLAY_COMPILER_VERSION)
    )
    command = ResolvedCompileReplayJob(
        prepared.snapshot_id,
        # Pass numpy replay compiler version explicitly so ResolvedCompileReplayJob
        # receives a reviewable snapshot id and prepared input in test direct and queued
        # compile replay share exact child result and receipt.
        NUMPY_REPLAY_COMPILER_VERSION,
    )
    queued = container.control.submit_job.execute(
        SubmitJobRequest(
            spec_version=1,
            # Pass job type explicitly so SubmitJobRequest receives a reviewable compile-
            # child-equivalence and compile replay input in test direct and queued compile
            # replay share exact child result and receipt.
            job_type=JobType.COMPILE_REPLAY,
            payload_json=command.canonical_bytes(),
            idempotency_key="compile-child-equivalence",
            input_artifact_ids=(prepared.artifact.artifact_id,),
        )
        # Complete execute only after its compile-child-equivalence and compile replay inputs
        # are visible in test direct and queued compile replay share exact child result and
        # receipt.
    )
    lock = ControllerLock(data_root / "locks" / "controller.lock").acquire()
    supervisor = build_single_host_supervisor(
        container,
        authority=lock,
        # Pass config path explicitly so build_single_host_supervisor receives a
        # reviewable cwd and container input in test direct and queued compile replay
        # share exact child result and receipt.
        config_path=config_path,
        capabilities_file=None,
        working_directory=Path.cwd(),
    )
    try:
        # Perform the protected test direct and queued compile replay share exact child
        # result and receipt operation before explicit failure handling.
        assert supervisor.run_cycle().started == 1
        attempt = container.jobs.list_unfinished_attempts()[0].attempt
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            # Keep the time.monotonic() < deadline loop body bounded within test direct
            # and queued compile replay share exact child result and receipt.
            supervisor.run_cycle()
            stored = container.jobs.get_job(queued.job_id)
            assert stored is not None
            if stored.state is AttemptState.SUCCEEDED:
                break
            # Evaluate the complete test direct and queued compile replay share exact
            # child result and receipt state, stored and failed condition before guarded
            # effects.
            if stored.state in {
                AttemptState.FAILED,
                AttemptState.CANCELLED,
                AttemptState.INTERRUPTED,
            }:
                # Invoke fail for child attempt ended as and value as a visible test
                # direct and queued compile replay share exact child result and receipt
                # step.
                pytest.fail(f"child attempt ended as {stored.state.value}")
            time.sleep(0.02)
        else:
            pytest.fail("child compile did not finish before timeout")
    finally:
        # Handle the cleanup path after the protected test direct and queued compile
        # replay share exact child result and receipt operation.
        supervisor.shutdown()
        lock.release()

    receipt = LocalCompletionReceiptStore(DataRootLayout(data_root)).load(attempt.attempt_id)
    assert receipt is not None
    assert receipt.result_artifact_id == direct.artifact.artifact_id
    # Verify the outputs, receipt and completion output relationship before this scenario
    # is accepted.
    assert receipt.outputs == (
        CompletionOutput(direct.artifact.artifact_id, direct.artifact.manifest_digest),
    )
    with closing(sqlite3.connect(data_root / "catalog" / "catalog.sqlite")) as connection:
        # Keep closing, connect and sqlite3 active only for the bounded test direct and
        # queued compile replay share exact child result and receipt operation.
        stored_receipt = connection.execute(
            "SELECT receipt_digest FROM completion_receipts WHERE attempt_id = ?",
            (attempt.attempt_id.value,),
        ).fetchone()
        stored_outputs = connection.execute(
            # Pass select artifact id manifest digest from explicitly into fetchall within
            # test direct and queued compile replay share exact child result and receipt.
            "SELECT artifact_id, manifest_digest FROM completion_receipt_outputs "
            "WHERE attempt_id = ? ORDER BY artifact_id",
            (attempt.attempt_id.value,),
        ).fetchall()
    assert stored_receipt is not None
    # Verify the stored outputs, hex and artifact id relationship before this scenario is
    # accepted.
    assert stored_outputs == [
        (direct.artifact.artifact_id.hex, direct.artifact.manifest_digest.hex)
    ]
    progress_events = tuple(
        event.progress
        # Keep the job id list_job_events step visible while building progress events.
        for event in container.jobs.list_job_events(queued.job_id, limit=100)
        if event.progress is not None
    )
    assert progress_events
    assert progress_events[-1] is not None
    # Verify the value, completed and stage relationship before this scenario is accepted.
    assert progress_events[-1].stage.value == "COMPLETED"
    assert progress_events[-1].sequence == 5
    assert progress_events[-1].completed_units == 1
    assert progress_events[-1].total_units == 1


@pytest.mark.integration
# Define test direct and queued runs share canonical result with exact receipts as one
# focused operation with an explicit boundary.
def test_direct_and_queued_runs_share_canonical_result_with_exact_receipts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test direct and queued runs share canonical result with exact receipts
    # workflow in explicit, reviewable steps.
    monkeypatch.setattr(
        "backtest.bootstrap.supervisor.measure_host_memory",
        lambda: HostMemoryMeasurement(16 * 1024**3, 12 * 1024**3, 256 * 1024**2),
    )
    monkeypatch.setattr(
        # Pass version tag explicitly so setattr receives a reviewable measure host swap
        # and host swap measurement input in test direct and queued runs share canonical
        # result with exact receipts.
        "backtest.adapters.process.local.measure_host_swap",
        lambda: HostSwapMeasurement(0, 0),
    )
    data_root = tmp_path / "var"
    source = _source()
    # Assemble artifacts once so the test direct and queued runs share canonical result
    # with exact receipts workflow shares one value.
    artifacts = LocalArtifactRepository(data_root)
    stored_inspection = StoreSourceInspection(
        InspectSource(source, now=lambda: datetime(2025, 12, 31, tzinfo=UTC)),
        artifacts,
    ).execute(InspectSourceRequest(SourceId("fixture-indexer")))
    # Assemble plan once so the test direct and queued runs share canonical result with
    # exact receipts workflow shares one value.
    plan = PlanDataset(
        ArtifactSourceInspectionLoader(artifacts),
        _planning_policy(),
    ).execute(_plan_request(stored_inspection.artifact.artifact_id))
    build_tools = BuildToolBundleRegistry().pin()
    # Assemble prepared once so the test direct and queued runs share canonical result
    # with exact receipts workflow shares one value.
    prepared = PrepareDataset(
        source,
        _projector(),
        LocalArrowCanonicalStore(
            artifacts,
            # Pass memory limit mb explicitly so LocalArrowCanonicalStore receives a
            # reviewable artifacts and build tools input in test direct and queued runs
            # share canonical result with exact receipts.
            memory_limit_mb=256,
            build_tools=build_tools,
        ),
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    ).execute(PrepareDatasetRequest(plan))
    # Assemble settings once so the test direct and queued runs share canonical result
    # with exact receipts workflow shares one value.
    settings = Settings(
        paths=PathSettings(data_root=data_root),
        resources=ResourceSettings(
            max_builder_memory_mb=256,
            max_parallel_runs=1,
            # Pass tmp quota gb explicitly into ResourceSettings within test direct and
            # queued runs share canonical result with exact receipts.
            tmp_quota_gb=1,
            disk_low_watermark_gb=1,
            disk_emergency_watermark_gb=1,
            native_threads_per_process=1,
        ),
        # Complete Settings only after its path settings and resource settings inputs are
        # visible in test direct and queued runs share canonical result with exact receipts.
    )
    config_path = tmp_path / "local.toml"
    config_path.write_text(
        "[paths]\n"
        f"data_root = {json.dumps(str(data_root))}\n"
        # Pass resources n explicitly so write_text receives a reviewable [paths] data
        # root = and utf-8 input in test direct and queued runs share canonical result
        # with exact receipts.
        "[resources]\n"
        "max_builder_memory_mb = 256\n"
        "max_parallel_runs = 1\n"
        "tmp_quota_gb = 1\n"
        "disk_low_watermark_gb = 1\n"
        # Pass disk emergency watermark gb n explicitly so write_text receives a
        # reviewable [paths] data root = and utf-8 input in test direct and queued runs
        # share canonical result with exact receipts.
        "disk_emergency_watermark_gb = 1\n"
        "native_threads_per_process = 1\n",
        encoding="utf-8",
    )
    container = build_runtime_container(settings, profile="direct-run-integration")
    # Assemble replay once so the test direct and queued runs share canonical result with
    # exact receipts workflow shares one value.
    replay = CanonicalParquetReplaySource(
        artifacts,
        prepared.snapshot_id,
        build_tools=build_tools,
    )
    # Assemble resolved spec once so the test direct and queued runs share canonical
    # result with exact receipts workflow shares one value.
    resolved_spec = _resolved_run_spec(
        prepared,
        replay,
        container.runtime_manifest.runtime_lock_id,
    )
    # Assemble request once so the test direct and queued runs share canonical result with
    # exact receipts workflow shares one value.
    request = RunBacktestRequest(resolved_spec, ContentDigest("8" * 64))
    command = ResolvedBacktestJob(
        resolved_spec,
        request.attempt_nonce,
        request.physical_settings,
        # Complete ResolvedBacktestJob only after its attempt nonce and physical settings
        # inputs are visible in test direct and queued runs share canonical result with exact
        # receipts.
    )

    direct = RuntimeCliBackend(container, config_path).run_backtest(request)

    direct_job = container.jobs.list_jobs(limit=10)[0]
    direct_event = next(
        event
        # Keep the job id list_job_events step visible while building direct event.
        for event in container.jobs.list_job_events(direct_job.job_id, limit=100)
        if event.event_type == "ATTEMPT_SUCCEEDED" and event.attempt_id is not None
    )
    assert direct_event.attempt_id is not None
    direct_attempt = JobAttempt(
        # Pass direct event explicitly so JobAttempt receives a reviewable attempt id and
        # job id input in test direct and queued runs share canonical result with exact
        # receipts.
        direct_event.attempt_id,
        direct_job.job_id,
        direct_job.spec,
        AttemptState.SUCCEEDED,
        direct_event.state_version,
        # Complete JobAttempt only after its attempt id and job id inputs are visible in test
        # direct and queued runs share canonical result with exact receipts.
    )
    receipts = LocalCompletionReceiptStore(DataRootLayout(data_root))
    direct_receipt = receipts.load(direct_attempt.attempt_id)
    assert direct_receipt is not None
    assert direct_receipt.outputs == (
        # Keep the completion output expectation tied to outputs, direct receipt and
        # completion output in this scenario.
        CompletionOutput(direct.artifact.artifact_id, direct.artifact.manifest_digest),
    )

    queued_job = container.control.submit_job.execute(
        SubmitJobRequest(
            spec_version=1,
            # Pass job type explicitly so SubmitJobRequest receives a reviewable queued-
            # run-equivalence and run backtest input in test direct and queued runs share
            # canonical result with exact receipts.
            job_type=JobType.RUN_BACKTEST,
            payload_json=command.canonical_bytes(),
            idempotency_key="queued-run-equivalence",
        )
    )
    # Verify queued_job.spec == direct_job.spec before this scenario is accepted.
    assert queued_job.spec == direct_job.spec
    lock = ControllerLock(data_root / "locks" / "controller.lock").acquire()
    supervisor = build_single_host_supervisor(
        container,
        authority=lock,
        # Pass config path explicitly so build_single_host_supervisor receives a
        # reviewable cwd and container input in test direct and queued runs share
        # canonical result with exact receipts.
        config_path=config_path,
        capabilities_file=None,
        working_directory=Path.cwd(),
    )
    try:
        # Perform the protected test direct and queued runs share canonical result with
        # exact receipts operation before explicit failure handling.
        assert supervisor.run_cycle().started == 1
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            # Keep the time.monotonic() < deadline loop body bounded within test direct
            # and queued runs share canonical result with exact receipts.
            supervisor.run_cycle()
            stored = container.jobs.get_job(queued_job.job_id)
            assert stored is not None
            if stored.state is AttemptState.SUCCEEDED:
                break
            # Evaluate the complete test direct and queued runs share canonical result
            # with exact receipts state, stored and failed condition before guarded
            # effects.
            if stored.state in {
                AttemptState.FAILED,
                AttemptState.CANCELLED,
                AttemptState.INTERRUPTED,
            }:
                # Invoke fail for child run ended as and value as a visible test direct
                # and queued runs share canonical result with exact receipts step.
                pytest.fail(f"child run ended as {stored.state.value}")
            time.sleep(0.02)
        else:
            pytest.fail("child run did not finish before timeout")
    finally:
        # Handle the cleanup path after the protected test direct and queued runs share
        # canonical result with exact receipts operation.
        supervisor.shutdown()
        lock.release()

    queued_event = next(
        event
        for event in container.jobs.list_job_events(queued_job.job_id, limit=100)
        # Pass event type explicitly so next receives a reviewable attempt succeeded and
        # list job events input in test direct and queued runs share canonical result with
        # exact receipts.
        if event.event_type == "ATTEMPT_SUCCEEDED" and event.attempt_id is not None
    )
    assert queued_event.attempt_id is not None
    queued_attempt = JobAttempt(
        queued_event.attempt_id,
        # Pass queued job explicitly so JobAttempt receives a reviewable attempt id and
        # job id input in test direct and queued runs share canonical result with exact
        # receipts.
        queued_job.job_id,
        queued_job.spec,
        AttemptState.SUCCEEDED,
        queued_event.state_version,
    )
    # Assemble queued receipt once so the test direct and queued runs share canonical
    # result with exact receipts workflow shares one value.
    queued_receipt = receipts.load(queued_attempt.attempt_id)
    assert queued_receipt is not None
    with artifacts.open_committed(queued_receipt.result_artifact_id) as handle:
        queued_artifact = handle.descriptor
    assert queued_receipt.outputs == (
        # Keep the completion output expectation tied to outputs, queued receipt and
        # completion output in this scenario.
        CompletionOutput(queued_artifact.artifact_id, queued_artifact.manifest_digest),
    )
    reader = LocalJobResultReader(artifacts)
    queued = reader.run_result(command, queued_artifact, queued_attempt)

    assert queued.logical_run_id == direct.logical_run_id
    # Verify the canonical result hash, queued and direct relationship before this
    # scenario is accepted.
    assert queued.canonical_result_hash == direct.canonical_result_hash
    assert queued.execution_attempt_id != direct.execution_attempt_id
    assert queued.artifact.artifact_id != direct.artifact.artifact_id
    with pytest.raises(LocalJobResultError, match="resolved command"):
        reader.run_result(command, queued_artifact, direct_attempt)

    # Assemble sweep spec once so the test direct and queued runs share canonical result
    # with exact receipts workflow shares one value.
    sweep_spec = ResolvedSweepSpec.create(
        (
            SweepEntry(
                resolved_spec,
                ContentDigest("9" * 64),
                # Pass request explicitly so SweepEntry receives a reviewable 9 and
                # physical settings input in test direct and queued runs share canonical
                # result with exact receipts.
                request.physical_settings,
            ),
        ),
        comparison_metrics=("canonical_result_hash",),
    )
    # Assemble direct sweep once so the test direct and queued runs share canonical result
    # with exact receipts workflow shares one value.
    direct_sweep = RuntimeCliBackend(container, config_path).run_sweep(sweep_spec)
    assert len(direct_sweep.entries) == 1
    assert direct_sweep.entries[0].canonical_result_hash == direct.canonical_result_hash
    sweep_job = next(
        job
        # Keep the list jobs and jobs list_jobs step visible while building sweep job.
        for job in container.jobs.list_jobs(limit=10)
        if job.spec.job_type is JobType.RUN_SWEEP
        # Complete next only after its list jobs and job type inputs are visible in test
        # direct and queued runs share canonical result with exact receipts.
    )
    sweep_event = next(
        event
        for event in container.jobs.list_job_events(sweep_job.job_id, limit=100)
        if event.event_type == "ATTEMPT_SUCCEEDED" and event.attempt_id is not None
        # Complete next only after its attempt succeeded and list job events inputs are
        # visible in test direct and queued runs share canonical result with exact receipts.
    )
    assert sweep_event.attempt_id is not None
    sweep_receipt = receipts.load(sweep_event.attempt_id)
    assert sweep_receipt is not None
    expected_sweep_outputs = tuple(
        # Keep the sorted and completion output sorted step visible while building
        # expected sweep outputs.
        sorted(
            (
                CompletionOutput(
                    direct_sweep.artifact.artifact_id,
                    direct_sweep.artifact.manifest_digest,
                    # Complete CompletionOutput only after its artifact id and artifact inputs
                    # are visible in test direct and queued runs share canonical result with
                    # exact receipts.
                ),
                CompletionOutput(
                    direct_sweep.entries[0].run_artifact.artifact_id,
                    direct_sweep.entries[0].run_artifact.manifest_digest,
                ),
                # Complete sorted only after its artifact id and manifest digest inputs are
                # visible in test direct and queued runs share canonical result with exact
                # receipts.
            ),
            key=lambda item: item.artifact_id.hex,
        )
    )
    assert sweep_receipt.outputs == expected_sweep_outputs
    # Assemble sweep attempt once so the test direct and queued runs share canonical
    # result with exact receipts workflow shares one value.
    sweep_attempt = JobAttempt(
        sweep_event.attempt_id,
        sweep_job.job_id,
        sweep_job.spec,
        AttemptState.SUCCEEDED,
        # Pass sweep event explicitly so JobAttempt receives a reviewable attempt id and
        # job id input in test direct and queued runs share canonical result with exact
        # receipts.
        sweep_event.state_version,
    )
    sweep_command = ResolvedSweepJob(sweep_spec)
    read_back_sweep = reader.sweep_result(
        sweep_command,
        # Pass direct sweep explicitly so sweep_result receives a reviewable artifact and
        # sweep command input in test direct and queued runs share canonical result with
        # exact receipts.
        direct_sweep.artifact,
        sweep_attempt,
    )
    assert read_back_sweep == direct_sweep

    with (
        # Acquire open committed, artifact id and artifacts at an explicit test direct and
        # queued runs share canonical result with exact receipts context boundary so
        # cleanup remains scoped.
        artifacts.open_committed(direct_sweep.artifact.artifact_id) as handle,
        handle.open_binary("manifest.json") as stream,
    ):
        sweep_manifest = json.load(stream)
    noncanonical_payload = json.dumps(sweep_manifest, indent=2).encode("utf-8")
    # Assemble noncanonical writer once so the test direct and queued runs share canonical
    # result with exact receipts workflow shares one value.
    noncanonical_writer = artifacts.stage(
        ArtifactDraft(
            ArtifactKind.SWEEP,
            domain_digest("test.noncanonical-sweep-report", {"version": 1}),
            direct_sweep.artifact.input_artifact_ids,
            # Complete ArtifactDraft only after its noncanonical-sweep-report and version
            # inputs are visible in test direct and queued runs share canonical result with
            # exact receipts.
        )
    )
    noncanonical_sweep = noncanonical_writer.commit(
        noncanonical_payload,
        identity_manifest_bytes=canonical_json_bytes(sweep_manifest),
        # Complete commit only after its canonical json bytes and noncanonical payload inputs
        # are visible in test direct and queued runs share canonical result with exact
        # receipts.
    )
    with pytest.raises(LocalJobResultError, match="canonical JSON"):
        reader.sweep_result(sweep_command, noncanonical_sweep, sweep_attempt)

    sweep_manifest["entries"][0]["comparison"]["canonical_result_hash"] = "f" * 64
    tampered_payload = canonical_json_bytes(sweep_manifest)
    # Assemble tampered writer once so the test direct and queued runs share canonical
    # result with exact receipts workflow shares one value.
    tampered_writer = artifacts.stage(
        ArtifactDraft(
            ArtifactKind.SWEEP,
            domain_digest("test.tampered-sweep-report", {"version": 1}),
            direct_sweep.artifact.input_artifact_ids,
            # Complete ArtifactDraft only after its tampered-sweep-report and version inputs
            # are visible in test direct and queued runs share canonical result with exact
            # receipts.
        )
    )
    tampered_sweep = tampered_writer.commit(
        tampered_payload,
        identity_manifest_bytes=tampered_payload,
        # Complete commit only after its tampered payload inputs are visible in test direct
        # and queued runs share canonical result with exact receipts.
    )
    with pytest.raises(LocalJobResultError, match="committed run"):
        reader.sweep_result(sweep_command, tampered_sweep, sweep_attempt)

    sweep_manifest["entries"][0]["comparison"]["canonical_result_hash"] = direct_sweep.entries[
        0
        # Keep the canonical result hash component named inside the canonical result hash,
        # comparison and sweep manifest contract.
    ].canonical_result_hash.hex
    sweep_manifest["entries"][0]["run_artifact_id"] = direct.artifact.artifact_id.hex
    substituted_payload = canonical_json_bytes(sweep_manifest)
    substituted_writer = artifacts.stage(
        ArtifactDraft(
            # Pass artifact kind explicitly so ArtifactDraft receives a reviewable
            # substituted-sweep-report and version input in test direct and queued runs
            # share canonical result with exact receipts.
            ArtifactKind.SWEEP,
            domain_digest("test.substituted-sweep-report", {"version": 1}),
            (direct.artifact.artifact_id,),
        )
    )
    # Assemble substituted sweep once so the test direct and queued runs share canonical
    # result with exact receipts workflow shares one value.
    substituted_sweep = substituted_writer.commit(
        substituted_payload,
        identity_manifest_bytes=substituted_payload,
    )
    with pytest.raises(LocalJobResultError, match="committed run"):
        # Invoke sweep_result for sweep command and substituted sweep as a visible test
        # direct and queued runs share canonical result with exact receipts step.
        reader.sweep_result(sweep_command, substituted_sweep, sweep_attempt)


def test_prepare_publishes_sorted_self_contained_repeatable_snapshot(tmp_path: Path) -> None:
    # Execute the test prepare publishes sorted self contained repeatable snapshot
    # workflow in explicit, reviewable steps.
    source = _source()
    artifacts = LocalArtifactRepository(tmp_path / "var")
    stored_inspection = StoreSourceInspection(
        InspectSource(source, now=lambda: datetime(2025, 12, 31, tzinfo=UTC)),
        artifacts,
        # Keep the inspect source request and source id InspectSourceRequest step visible
        # while building stored inspection.
    ).execute(InspectSourceRequest(SourceId("fixture-indexer")))
    plan = PlanDataset(
        ArtifactSourceInspectionLoader(artifacts),
        _planning_policy(),
    ).execute(_plan_request(stored_inspection.artifact.artifact_id))
    # Assemble store once so the test prepare publishes sorted self contained repeatable
    # snapshot workflow shares one value.
    store = LocalArrowCanonicalStore(artifacts, memory_limit_mb=256)
    first_time = datetime(2026, 1, 1, tzinfo=UTC)
    projector = _projector()

    first = PrepareDataset(
        source,
        # Pass projector explicitly so execute receives a reviewable prepare dataset
        # request and plan input in test prepare publishes sorted self contained
        # repeatable snapshot.
        projector,
        store,
        clock=lambda: first_time,
    ).execute(PrepareDatasetRequest(plan))
    second = PrepareDataset(
        # Pass source explicitly so execute receives a reviewable prepare dataset request
        # and plan input in test prepare publishes sorted self contained repeatable
        # snapshot.
        source,
        projector,
        store,
        clock=lambda: first_time + timedelta(days=1),
    ).execute(PrepareDatasetRequest(plan))
    # Assemble read back once so the test prepare publishes sorted self contained
    # repeatable snapshot workflow shares one value.
    read_back = LocalJobResultReader(artifacts).prepared_snapshot(
        ResolvedPrepareDatasetJob(plan),
        first.artifact,
    )

    assert first.snapshot_id == second.snapshot_id
    # Verify read_back.artifact == first.artifact before this scenario is accepted.
    assert read_back.artifact == first.artifact
    assert read_back.dataset_revision_id == first.dataset_revision_id
    assert read_back.logical_content_hash == first.logical_content_hash
    assert [
        item.effective_source_boundary.identity_document()
        # Keep the item expectation tied to identity document, item and distributions in
        # this scenario.
        for item in read_back.distributions
        # Keep the item expectation tied to identity document, item and distributions in this
        # scenario.
    ] == [item.effective_source_boundary.identity_document() for item in first.distributions]
    assert first.logical_content_hash == second.logical_content_hash
    assert first.dataset_revision_id == second.dataset_revision_id
    assert [item.row_count for item in first.distributions] == [2, 1, 2]
    assert all(
        # Pass item explicitly so all receives a reviewable completeness and unknown input
        # in test prepare publishes sorted self contained repeatable snapshot.
        item.source_boundary.completeness is IngestionCompleteness.UNKNOWN
        for item in first.distributions
    )

    with (
        artifacts.open_committed(first.artifact.artifact_id) as snapshot_handle,  # type: ignore[attr-defined]
        snapshot_handle.open_binary("manifest.json") as stream,
    ):
        manifest = json.load(stream)
    assert manifest["artifact_schema"] == "canonical-snapshot/v4"
    assert manifest["network_id"] == SOLANA_MAINNET_NETWORK_ID.value
    # Verify the value, manifest and position schema id relationship before this scenario
    # is accepted.
    assert manifest["position_schema_id"] == BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID.value
    assert manifest["dataset_revision_id"] == first.dataset_revision_id.hex
    assert len(manifest["distributions"]) == 3
    assert [item["source_fidelity"] for item in manifest["source_boundaries"]] == [
        {
            # Keep the chain finality expectation tied to item, source fidelity and chain
            # finality in this scenario.
            "chain_finality": item.source_fidelity.chain_finality.value,
            "completeness": item.source_fidelity.completeness.value,
            "consistency": item.source_fidelity.consistency.value,
            "fees": item.source_fidelity.fees.value,
            "identity": item.source_fidelity.identity.value,
            # Keep the ordering expectation tied to item, source fidelity and chain
            # finality in this scenario.
            "ordering": item.source_fidelity.ordering.value,
            "state": item.source_fidelity.state.value,
        }
        for item in first.distributions
    ]
    # Verify the unknown, item and completeness relationship before this scenario is
    # accepted.
    assert all(
        item["source_fidelity"]["completeness"] == "UNKNOWN"
        for item in manifest["source_boundaries"]
    )

    swaps = next(item for item in first.distributions if item.capability_id == SWAPS)
    with artifacts.open_committed(swaps.artifact.artifact_id) as handle:  # type: ignore[attr-defined]
        table = pq.read_table(handle.local_path("events.parquet"))  # type: ignore[attr-defined]
    assert table.column("transaction_index").to_pylist() == [1, 2]
    assert table.column("sold_asset_id").to_pylist() == ["SOL", "TOKEN"]

    replay = CanonicalParquetReplaySource(artifacts, first.snapshot_id)
    events = tuple(replay.events())
    assert replay.logical_content_hash == first.logical_content_hash
    # Verify the block ordinal, name and event relationship before this scenario is
    # accepted.
    assert [(event.envelope.position.block_ordinal, event.kind.name) for event in events] == [
        (100, "BLOCK"),
        (100, "TOKEN_LAUNCH"),
        (100, "VENUE_TRADE"),
        (101, "BLOCK"),
        # Keep the venue trade expectation tied to block ordinal, name and event in this
        # scenario.
        (101, "VENUE_TRADE"),
    ]
    assert tuple(
        (item.block_ordinal, item.boundary_ordinal) for item in replay.boundaries()
    ) == tuple(
        # Keep the sorted expectation tied to sorted, block ordinal and boundary ordinal
        # in this scenario.
        sorted(
            {
                (
                    event.envelope.position.block_ordinal,
                    event.envelope.boundary_ordinal,
                    # Complete sorted only after its block ordinal and boundary ordinal inputs
                    # are visible in test prepare publishes sorted self contained repeatable
                    # snapshot.
                )
                for event in events
            }
        )
    )

    # Assemble compiled replay once so the test prepare publishes sorted self contained
    # repeatable snapshot workflow shares one value.
    compiled_replay = CompileReplay(
        LocalNumpyReplayPackCompiler(
            artifacts,
            lambda snapshot_id: CanonicalParquetReplaySource(
                artifacts,
                # Pass snapshot id explicitly so CanonicalParquetReplaySource receives a
                # reviewable artifacts and snapshot id input in test prepare publishes
                # sorted self contained repeatable snapshot.
                snapshot_id,
                duckdb_memory_limit_mb=256,
            ),
            runtime_lock_id=RuntimeLockId("6" * 64),
        )
        # Keep the snapshot id CompileReplayRequest step visible while building compiled
        # replay.
    ).execute(CompileReplayRequest(first.snapshot_id, NUMPY_REPLAY_COMPILER_VERSION))
    with NumpyMmapReplaySource(artifacts, compiled_replay.replay_pack_id) as mmap_replay:
        # Keep numpy mmap replay source, artifacts and replay pack id active only for the
        # bounded test prepare publishes sorted self contained repeatable snapshot
        # operation.
        assert tuple(mmap_replay.events()) == events
        assert mmap_replay.boundaries() == replay.boundaries()
        assert mmap_replay.dataset_revision_id == replay.dataset_revision_id
        assert mmap_replay.logical_content_hash == replay.logical_content_hash
        assert mmap_replay.replay_semantics_id == replay.replay_semantics_id
        # Verify the source boundaries, mmap replay and replay relationship before this
        # scenario is accepted.
        assert mmap_replay.source_boundaries == replay.source_boundaries
        replay_pack_run = _run_reference_backtest(mmap_replay)

    first_run = _run_reference_backtest(replay)
    second_run = _run_reference_backtest(CanonicalParquetReplaySource(artifacts, first.snapshot_id))
    assert first_run.audit_hash == second_run.audit_hash
    # Verify the result hash, first run and second run relationship before this scenario
    # is accepted.
    assert first_run.result_hash == second_run.result_hash
    assert replay_pack_run.audit_hash == first_run.audit_hash
    assert replay_pack_run.result_hash == first_run.result_hash
    assert first_run.accepted_order_count == first_run.filled_order_count == 1
    assert first_run.fill_count == 1
    # Assemble actual golden once so the test prepare publishes sorted self contained
    # repeatable snapshot workflow shares one value.
    actual_golden = {
        "audit_hash": first_run.audit_hash.hex,
        "dataset_revision_id": first.dataset_revision_id.hex,
        "logical_content_hash": first.logical_content_hash.hex,
        "replay_pack_id": compiled_replay.replay_pack_id.hex,
        # Keep the replay semantics id component named inside the actual golden contract.
        "replay_semantics_id": replay.replay_semantics_id.hex,
        "result_hash": first_run.result_hash.hex,
        "snapshot_id": first.snapshot_id.hex,
    }
    golden_path = Path(__file__).parents[2] / "golden" / "reference_vertical_slice_v2.json"
    # Verify the actual golden, loads and json relationship before this scenario is
    # accepted.
    assert actual_golden == json.loads(golden_path.read_text(encoding="utf-8"))

    runtime_lock_id = RuntimeLockId("9" * 64)
    resolved_from_typed_draft = ReferenceRunSpecResolver(
        artifacts,
        runtime_lock_id,
        # Pass parquet memory limit mb explicitly so ReferenceRunSpecResolver receives a
        # reviewable artifacts and runtime lock id input in test prepare publishes sorted
        # self contained repeatable snapshot.
        parquet_memory_limit_mb=256,
        threads=1,
    ).resolve(
        ReferenceRunDraft(
            snapshot_id=first.snapshot_id,
            # Pass replay pack id explicitly so ReferenceRunDraft receives a reviewable
            # pool and sol input in test prepare publishes sorted self contained
            # repeatable snapshot.
            replay_pack_id=compiled_replay.replay_pack_id,
            delivery_schedule_id=None,
            pool_id=PoolId("pool"),
            sold_asset_id=AssetId("SOL"),
            bought_asset_id=AssetId("TOKEN"),
            # Pass amount in atomic explicitly so ReferenceRunDraft receives a reviewable
            # pool and sol input in test prepare publishes sorted self contained
            # repeatable snapshot.
            amount_in_atomic=100,
            minimum_amount_out_atomic=0,
            fee_bps=30,
            execution_mode=ExecutionMode.SHADOW_STATE_REPLAY,
            maximum_order_input_atomic=1_000,
            # Pass observation slots explicitly so ReferenceRunDraft receives a reviewable
            # pool and sol input in test prepare publishes sorted self contained
            # repeatable snapshot.
            observation_slots=0,
            order_slots=0,
            initial_portfolio=(AssetBalance(AssetId("SOL"), 1_000),),
            root_seed=42,
            maximum_dynamic_items=10_000,
            # Complete ReferenceRunDraft only after its pool and sol inputs are visible in
            # test prepare publishes sorted self contained repeatable snapshot.
        )
    )
    assert resolved_from_typed_draft.snapshot_id == first.snapshot_id
    assert resolved_from_typed_draft.replay_input.replay_pack_id == compiled_replay.replay_pack_id
    assert resolved_from_typed_draft.runtime_lock_id == runtime_lock_id
    # Assemble resolved spec once so the test prepare publishes sorted self contained
    # repeatable snapshot workflow shares one value.
    resolved_spec = _resolved_run_spec(first, replay, runtime_lock_id)
    times = iter((first_time, first_time + timedelta(seconds=1)))
    run_request = RunBacktestRequest(resolved_spec, ContentDigest("8" * 64))
    result = RunBacktest(
        LocalReplaySourceFactory(artifacts, parquet_memory_limit_mb=256),
        # Keep the runtime lock id ReferenceRuntimeComponentsResolver step visible while
        # building result.
        ReferenceRuntimeComponentsResolver(runtime_lock_id),
        ReferenceBacktestEngine(),
        LocalParquetRunOutputStore(artifacts, tmp_path / "run-work"),
        clock=lambda: next(times),
    ).execute(run_request)
    # Assemble read back result once so the test prepare publishes sorted self contained
    # repeatable snapshot workflow shares one value.
    read_back_result = LocalJobResultReader(artifacts).run_result(
        ResolvedBacktestJob(
            resolved_spec,
            ContentDigest("8" * 64),
            run_request.physical_settings,
            # Complete ResolvedBacktestJob only after its 8 and physical settings inputs are
            # visible in test prepare publishes sorted self contained repeatable snapshot.
        ),
        result.artifact,
    )
    assert result.logical_run_id == resolved_spec.logical_run_id
    assert read_back_result == result
    # Acquire open committed, artifact id and artifacts at an explicit test prepare
    # publishes sorted self contained repeatable snapshot context boundary so cleanup
    # remains scoped.
    with artifacts.open_committed(result.artifact.artifact_id) as run_handle:
        # Keep open committed, artifact id and artifacts active only for the bounded test
        # prepare publishes sorted self contained repeatable snapshot operation.
        with run_handle.open_binary("manifest.json") as stream:
            run_manifest = json.load(stream)
        assert pq.read_table(run_handle.local_path("fills.parquet")).num_rows == 1  # type: ignore[attr-defined]
        ledger_table = pq.read_table(run_handle.local_path("ledger.parquet"))  # type: ignore[attr-defined]
        assert ledger_table.num_rows == 2
        assert ledger_table.schema.metadata == {b"backtest.schema": b"run-ledger/v2"}
        assert ledger_table.column("correlation_kind").to_pylist() == ["ORDER", "ORDER"]
        assert len(set(ledger_table.column("correlation_id").to_pylist())) == 1
    assert run_manifest["artifact_schema"] == "successful-run/v3"
    # Verify the hex, run manifest and logical run id relationship before this scenario is
    # accepted.
    assert run_manifest["logical_run_id"] == resolved_spec.logical_run_id.hex
    assert run_manifest["physical_settings"] == {
        "backend": "reference-python-v1",
        "output_buffer_rows": 8_192,
        "reader_batch_rows": 65_536,
        # Keep the reader readahead expectation tied to run manifest, physical settings
        # and backend in this scenario.
        "reader_readahead": 1,
        "schema": "backtest.run-physical-settings/v2",
        "threads": 1,
    }
    assert run_manifest["summary"]["comparison"]["audit_hash"] == first_run.audit_hash.hex

    # Assemble replay pack spec once so the test prepare publishes sorted self contained
    # repeatable snapshot workflow shares one value.
    replay_pack_spec = _resolved_run_spec(
        first,
        replay,
        runtime_lock_id,
        replay_input=ResolvedReplayInput(
            # Pass replay input format explicitly so ResolvedReplayInput receives a
            # reviewable replay pack and replay layout schema id input in test prepare
            # publishes sorted self contained repeatable snapshot.
            ReplayInputFormat.REPLAY_PACK,
            replay_layout_schema_id=compiled_replay.manifest.layout.replay_layout_schema_id,
            replay_pack_id=compiled_replay.replay_pack_id,
        ),
    )
    # Verify the logical run id, replay pack spec and resolved spec relationship before
    # this scenario is accepted.
    assert replay_pack_spec.logical_run_id == resolved_spec.logical_run_id
    replay_pack_times = iter(
        (first_time + timedelta(hours=1), first_time + timedelta(hours=1, seconds=1))
    )
    replay_pack_result = RunBacktest(
        # Keep the artifacts LocalReplaySourceFactory step visible while building replay
        # pack result.
        LocalReplaySourceFactory(artifacts, parquet_memory_limit_mb=256),
        ReferenceRuntimeComponentsResolver(runtime_lock_id),
        ReferenceBacktestEngine(),
        LocalParquetRunOutputStore(artifacts, tmp_path / "run-work"),
        clock=lambda: next(replay_pack_times),
        # Keep the replay pack spec RunBacktestRequest step visible while building replay pack
        # result.
    ).execute(RunBacktestRequest(replay_pack_spec, ContentDigest("8" * 64)))
    assert replay_pack_result.logical_run_id == result.logical_run_id
    assert replay_pack_result.execution_attempt_id != result.execution_attempt_id
    with (
        artifacts.open_committed(replay_pack_result.artifact.artifact_id) as pack_run_handle,
        # Acquire open committed, artifact id and artifacts at an explicit test prepare
        # publishes sorted self contained repeatable snapshot context boundary so cleanup
        # remains scoped.
        pack_run_handle.open_binary("manifest.json") as stream,
    ):
        replay_pack_run_manifest = json.load(stream)
    assert (
        replay_pack_run_manifest["summary"]["comparison"]["audit_hash"] == first_run.audit_hash.hex
        # Verify the hex, audit hash and comparison relationship before this scenario is
        # accepted.
    )
    assert (
        replay_pack_run_manifest["summary"]["comparison"]["canonical_result_hash"]
        == first_run.result_hash.hex
    )

    # Assemble optimized times once so the test prepare publishes sorted self contained
    # repeatable snapshot workflow shares one value.
    optimized_times = iter(
        (first_time + timedelta(minutes=90), first_time + timedelta(minutes=90, seconds=1))
    )
    optimized_result = RunBacktest(
        LocalReplaySourceFactory(artifacts, parquet_memory_limit_mb=256),
        # Keep the runtime lock id ReferenceRuntimeComponentsResolver step visible while
        # building optimized result.
        ReferenceRuntimeComponentsResolver(runtime_lock_id),
        ReferenceBacktestEngine(),
        LocalParquetRunOutputStore(artifacts, tmp_path / "run-work"),
        additional_engines={
            NUMPY_MMAP_FIRST_SWAP_BACKEND: NumpyMmapFirstSwapEngine(
                # Pass strategy type explicitly so NumpyMmapFirstSwapEngine receives a
                # reviewable first swap strategy and constant product execution model
                # input in test prepare publishes sorted self contained repeatable
                # snapshot.
                strategy_type=FirstSwapStrategy,
                execution_model_type=ConstantProductExecutionModel,
                risk_policy_type=StaticRiskPolicy,
            )
        },
        # Keep the optimized times next step visible while building optimized result.
        clock=lambda: next(optimized_times),
    ).execute(
        RunBacktestRequest(
            replay_pack_spec,
            ContentDigest("8" * 64),
            # Keep the run physical settings and numpy mmap first swap exact
            # RunPhysicalSettings step visible while building optimized result.
            RunPhysicalSettings(
                backend=RunBackend.NUMPY_MMAP_FIRST_SWAP_EXACT,
                reader_batch_rows=65_536,
                reader_readahead=2,
                output_buffer_rows=8_192,
                # Pass threads explicitly so RunPhysicalSettings receives a reviewable
                # numpy mmap first swap exact and run backend input in test prepare
                # publishes sorted self contained repeatable snapshot.
                threads=1,
            ),
        )
    )
    assert optimized_result.logical_run_id == replay_pack_result.logical_run_id
    # Verify the execution attempt id, optimized result and replay pack result
    # relationship before this scenario is accepted.
    assert optimized_result.execution_attempt_id != replay_pack_result.execution_attempt_id
    assert optimized_result.canonical_result_hash == replay_pack_result.canonical_result_hash
    with (
        artifacts.open_committed(replay_pack_result.artifact.artifact_id) as reference_handle,
        artifacts.open_committed(optimized_result.artifact.artifact_id) as optimized_handle,
        # Acquire open committed, artifact id and artifacts at an explicit test prepare
        # publishes sorted self contained repeatable snapshot context boundary so cleanup
        # remains scoped.
    ):
        # Keep open committed, artifact id and artifacts active only for the bounded test
        # prepare publishes sorted self contained repeatable snapshot operation.
        with optimized_handle.open_binary("manifest.json") as stream:
            optimized_manifest = json.load(stream)
        assert optimized_manifest["physical_settings"]["reader_readahead"] == 2
        for output_name in ("audit.parquet", "fills.parquet", "ledger.parquet"):
            assert pq.read_table(optimized_handle.local_path(output_name)).equals(  # type: ignore[attr-defined]
                pq.read_table(reference_handle.local_path(output_name))  # type: ignore[attr-defined]
            )

    delivery_components = tuple(
        component
        for component in replay_pack_spec.components
        if component.role in {"clock", "engine", "latency", "scheduler"}
        # Complete tuple only after its clock and engine inputs are visible in test prepare
        # publishes sorted self contained repeatable snapshot.
    )
    compiled_delivery = CompileDeliverySchedule(
        LocalNumpyDeliveryScheduleCompiler(
            artifacts,
            runtime_lock_id=runtime_lock_id,
            # Complete LocalNumpyDeliveryScheduleCompiler only after its artifacts and runtime
            # lock id inputs are visible in test prepare publishes sorted self contained
            # repeatable snapshot.
        )
    ).execute(
        CompileDeliveryScheduleRequest(
            replay_pack_id=compiled_replay.replay_pack_id,
            replay_semantics_id=replay_pack_spec.replay_semantics_id,
            # Pass replay layout schema id explicitly so CompileDeliveryScheduleRequest
            # receives a reviewable replay pack id and replay semantics id input in test
            # prepare publishes sorted self contained repeatable snapshot.
            replay_layout_schema_id=compiled_replay.manifest.layout.replay_layout_schema_id,
            components=delivery_components,
            rng_algorithm=RNG_ALGORITHM,
            root_seed=replay_pack_spec.root_seed,
            compiler_version=DELIVERY_COMPILER_VERSION,
            # Complete CompileDeliveryScheduleRequest only after its replay pack id and replay
            # semantics id inputs are visible in test prepare publishes sorted self contained
            # repeatable snapshot.
        )
    )
    materialized_spec = _resolved_run_spec(
        first,
        replay,
        # Pass runtime lock id explicitly so _resolved_run_spec receives a reviewable
        # replay input and delivery schedule id input in test prepare publishes sorted
        # self contained repeatable snapshot.
        runtime_lock_id,
        replay_input=replay_pack_spec.replay_input,
        delivery_schedule_id=compiled_delivery.delivery_schedule_id,
    )
    materialized_times = iter(
        # Keep the timedelta timedelta step visible while building materialized times.
        (first_time + timedelta(hours=2), first_time + timedelta(hours=2, seconds=1))
    )
    materialized_result = RunBacktest(
        LocalReplaySourceFactory(artifacts, parquet_memory_limit_mb=256),
        ReferenceRuntimeComponentsResolver(runtime_lock_id),
        # Keep the reference backtest engine ReferenceBacktestEngine step visible while
        # building materialized result.
        ReferenceBacktestEngine(),
        LocalParquetRunOutputStore(artifacts, tmp_path / "run-work"),
        delivery_schedules=LocalDeliveryScheduleSourceFactory(artifacts),
        clock=lambda: next(materialized_times),
    ).execute(RunBacktestRequest(materialized_spec, ContentDigest("8" * 64)))
    # Verify the logical run id, materialized result and replay pack result relationship
    # before this scenario is accepted.
    assert materialized_result.logical_run_id == replay_pack_result.logical_run_id
    assert materialized_result.execution_attempt_id != replay_pack_result.execution_attempt_id
    assert materialized_result.canonical_result_hash == replay_pack_result.canonical_result_hash
    with (
        artifacts.open_committed(materialized_result.artifact.artifact_id) as schedule_run_handle,
        # Acquire open committed, artifact id and artifacts at an explicit test prepare
        # publishes sorted self contained repeatable snapshot context boundary so cleanup
        # remains scoped.
        schedule_run_handle.open_binary("manifest.json") as stream,
    ):
        materialized_run_manifest = json.load(stream)
    assert (
        materialized_run_manifest["summary"]["comparison"]["audit_hash"] == first_run.audit_hash.hex
        # Verify the hex, audit hash and comparison relationship before this scenario is
        # accepted.
    )
    assert (
        materialized_run_manifest["summary"]["comparison"]["canonical_result_hash"]
        == first_run.result_hash.hex
    )
    # Verify the hex, delivery schedule id and materialized run manifest relationship
    # before this scenario is accepted.
    assert (
        compiled_delivery.delivery_schedule_id.hex
        in materialized_run_manifest["input_artifact_ids"]
    )

    mismatched_seed_spec = _resolved_run_spec(
        # Pass first explicitly so _resolved_run_spec receives a reviewable replay input
        # and delivery schedule id input in test prepare publishes sorted self contained
        # repeatable snapshot.
        first,
        replay,
        runtime_lock_id,
        replay_input=replay_pack_spec.replay_input,
        delivery_schedule_id=compiled_delivery.delivery_schedule_id,
        # Pass root seed explicitly so _resolved_run_spec receives a reviewable replay
        # input and delivery schedule id input in test prepare publishes sorted self
        # contained repeatable snapshot.
        root_seed=43,
    )
    mismatched_latency_spec = _resolved_run_spec(
        first,
        replay,
        # Pass runtime lock id explicitly so _resolved_run_spec receives a reviewable
        # replay input and delivery schedule id input in test prepare publishes sorted
        # self contained repeatable snapshot.
        runtime_lock_id,
        replay_input=replay_pack_spec.replay_input,
        delivery_schedule_id=compiled_delivery.delivery_schedule_id,
        observation_slots=1,
    )
    # Traverse mismatched seed spec and mismatched latency spec explicitly so each test
    # prepare publishes sorted self contained repeatable snapshot iteration remains
    # traceable.
    for mismatched_spec in (mismatched_seed_spec, mismatched_latency_spec):
        # Process mismatched seed spec and mismatched latency spec inside the bounded test
        # prepare publishes sorted self contained repeatable snapshot loop.
        with pytest.raises(RunPreflightError, match="failed exact verification"):
            # Keep raises, run preflight error and pytest active only for the bounded test
            # prepare publishes sorted self contained repeatable snapshot operation.
            RunBacktest(
                LocalReplaySourceFactory(artifacts, parquet_memory_limit_mb=256),
                ReferenceRuntimeComponentsResolver(runtime_lock_id),
                ReferenceBacktestEngine(),
                LocalParquetRunOutputStore(artifacts, tmp_path / "run-work"),
                # Pass delivery schedules explicitly to execute for 6 and run backtest
                # request.
                delivery_schedules=LocalDeliveryScheduleSourceFactory(artifacts),
            ).execute(RunBacktestRequest(mismatched_spec, ContentDigest("6" * 64)))

    later_times = iter((first_time + timedelta(days=1), first_time + timedelta(days=1, seconds=1)))
    repeated = RunBacktest(
        LocalReplaySourceFactory(artifacts, parquet_memory_limit_mb=256),
        # Keep the runtime lock id ReferenceRuntimeComponentsResolver step visible while
        # building repeated.
        ReferenceRuntimeComponentsResolver(runtime_lock_id),
        ReferenceBacktestEngine(),
        LocalParquetRunOutputStore(artifacts, tmp_path / "run-work"),
        clock=lambda: next(later_times),
    ).execute(RunBacktestRequest(resolved_spec, ContentDigest("8" * 64)))
    # Verify the execution attempt id, repeated and result relationship before this
    # scenario is accepted.
    assert repeated.execution_attempt_id == result.execution_attempt_id
    assert repeated.artifact.artifact_id == result.artifact.artifact_id

    other_times = iter((first_time + timedelta(days=2), first_time + timedelta(days=2, seconds=1)))
    other_attempt = RunBacktest(
        LocalReplaySourceFactory(artifacts, parquet_memory_limit_mb=256),
        # Keep the runtime lock id ReferenceRuntimeComponentsResolver step visible while
        # building other attempt.
        ReferenceRuntimeComponentsResolver(runtime_lock_id),
        ReferenceBacktestEngine(),
        LocalParquetRunOutputStore(artifacts, tmp_path / "run-work"),
        clock=lambda: next(other_times),
    ).execute(RunBacktestRequest(resolved_spec, ContentDigest("7" * 64)))
    # Verify the logical run id, other attempt and result relationship before this
    # scenario is accepted.
    assert other_attempt.logical_run_id == result.logical_run_id
    assert other_attempt.execution_attempt_id != result.execution_attempt_id
    assert other_attempt.artifact.artifact_id != result.artifact.artifact_id


def test_prepare_preserves_identical_payload_multiplicity_by_stable_occurrence(
    tmp_path: Path,
    # Close the test prepare preserves identical payload multiplicity by stable occurrence
    # signature after its explicit inputs.
) -> None:
    # Execute the test prepare preserves identical payload multiplicity by stable
    # occurrence workflow in explicit, reviewable steps.
    rows = (
        _identity_swap_row(signature="source-a", transaction_index=1),
        _identity_swap_row(signature="source-b", transaction_index=2),
    )
    first_source, descriptor = _identity_source(
        # Pass rows explicitly so _identity_source receives a reviewable slot and
        # transaction index input in test prepare preserves identical payload multiplicity
        # by stable occurrence.
        rows,
        identity=IdentityFidelity.EXACT,
        total_key=("slot", "transaction_index", "event_index", "signature"),
        batch_size=1,
    )
    # Assemble (second source, ) once so the test prepare preserves identical payload
    # multiplicity by stable occurrence workflow shares one value.
    second_source, _ = _identity_source(
        tuple(reversed(rows)),
        identity=IdentityFidelity.EXACT,
        total_key=("slot", "transaction_index", "event_index", "signature"),
        batch_size=2,
        # Complete _identity_source only after its slot and transaction index inputs are
        # visible in test prepare preserves identical payload multiplicity by stable
        # occurrence.
    )
    artifacts = LocalArtifactRepository(tmp_path / "var")
    plan = _identity_plan(first_source, artifacts, descriptor)
    projector = _identity_projector(descriptor)
    store = LocalArrowCanonicalStore(artifacts, memory_limit_mb=256, projection_batch_rows=1)

    # Assemble first once so the test prepare preserves identical payload multiplicity by
    # stable occurrence workflow shares one value.
    first = PrepareDataset(
        first_source,
        projector,
        store,
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
        # Keep the plan PrepareDatasetRequest step visible while building first.
    ).execute(PrepareDatasetRequest(plan))
    second = PrepareDataset(
        second_source,
        projector,
        store,
        # Keep the datetime and utc datetime step visible while building second.
        clock=lambda: datetime(2026, 1, 2, tzinfo=UTC),
    ).execute(PrepareDatasetRequest(plan))

    assert first.snapshot_id == second.snapshot_id
    assert first.logical_content_hash == second.logical_content_hash
    distribution = first.distributions[0]
    # Verify distribution.row_count == 2 before this scenario is accepted.
    assert distribution.row_count == 2
    raw_handle = artifacts.open_committed(distribution.artifact.artifact_id)
    try:
        # Perform the protected test prepare preserves identical payload multiplicity by
        # stable occurrence operation before explicit failure handling.
        handle = cast(Any, raw_handle)
        table = pq.read_table(handle.local_path("events.parquet"))
        with handle.open_binary("manifest.json") as stream:
            manifest = json.load(stream)
    finally:
        # Invoke close as a visible step within the test prepare preserves identical
        # payload multiplicity by stable occurrence workflow.
        raw_handle.close()
    assert len(set(table.column("source_record_id").to_pylist())) == 2
    assert len(set(table.column("canonical_event_id").to_pylist())) == 2
    assert table.column("sold_amount_atomic").to_pylist() == [
        (100).to_bytes(16, "big", signed=True),
        # Keep the signed expectation tied to to pylist, to bytes and big in this
        # scenario.
        (100).to_bytes(16, "big", signed=True),
    ]
    assert manifest["artifact_schema"] == "canonical-distribution/v5"
    assert manifest["source_boundary"]["source_fidelity"]["identity"] == "EXACT"


def test_prepare_identity_is_independent_of_bounded_validation_batch_rows(
    tmp_path: Path,
) -> None:
    rows = tuple(
        _identity_swap_row(signature=f"source-{index}", transaction_index=index)
        for index in range(1, 5)
    )
    source, descriptor = _identity_source(
        rows,
        identity=IdentityFidelity.EXACT,
        total_key=("slot", "transaction_index", "event_index", "signature"),
        batch_size=2,
    )
    first_artifacts = LocalArtifactRepository(tmp_path / "first")
    second_artifacts = LocalArtifactRepository(tmp_path / "second")
    first_plan = _identity_plan(source, first_artifacts, descriptor)
    second_plan = _identity_plan(source, second_artifacts, descriptor)
    assert first_plan.spec.spec_id == second_plan.spec.spec_id

    first = PrepareDataset(
        source,
        _identity_projector(descriptor),
        LocalArrowCanonicalStore(
            first_artifacts,
            memory_limit_mb=256,
            validation_batch_rows=1,
        ),
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    ).execute(PrepareDatasetRequest(first_plan))
    second = PrepareDataset(
        source,
        _identity_projector(descriptor),
        LocalArrowCanonicalStore(
            second_artifacts,
            memory_limit_mb=256,
            validation_batch_rows=4,
        ),
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    ).execute(PrepareDatasetRequest(second_plan))

    assert first.snapshot_id == second.snapshot_id
    assert first.logical_content_hash == second.logical_content_hash
    assert tuple(item.logical_content_hash for item in first.distributions) == tuple(
        item.logical_content_hash for item in second.distributions
    )


def test_prepare_rejects_ambiguous_duplicate_split_across_source_batches(
    # Keep the tmp path input explicit in the test prepare rejects ambiguous duplicate
    # split across source batches contract.
    tmp_path: Path,
) -> None:
    # Execute the test prepare rejects ambiguous duplicate split across source batches
    # workflow in explicit, reviewable steps.
    duplicate = _identity_swap_row(signature="ambiguous", transaction_index=1)
    source, descriptor = _identity_source(
        (duplicate, duplicate),
        identity=IdentityFidelity.AMBIGUOUS,
        total_key=(),
        # Pass batch size explicitly so _identity_source receives a reviewable ambiguous
        # and duplicate input in test prepare rejects ambiguous duplicate split across
        # source batches.
        batch_size=1,
    )
    artifacts = LocalArtifactRepository(tmp_path / "var")
    plan = _identity_plan(source, artifacts, descriptor)

    with pytest.raises(CanonicalDataError, match="stable source occurrence identity"):
        # Keep raises, canonical data error and pytest active only for the bounded test
        # prepare rejects ambiguous duplicate split across source batches operation.
        PrepareDataset(
            source,
            _identity_projector(descriptor),
            LocalArrowCanonicalStore(
                artifacts,
                # Pass memory limit mb explicitly so LocalArrowCanonicalStore receives a
                # reviewable artifacts input in test prepare rejects ambiguous duplicate
                # split across source batches.
                memory_limit_mb=256,
                projection_batch_rows=1,
            ),
            clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
        ).execute(PrepareDatasetRequest(plan))


# Define test reference resolver rejects snapshot below strategy minimum fidelity as one
# focused operation with an explicit boundary.
def test_reference_resolver_rejects_snapshot_below_strategy_minimum_fidelity(
    tmp_path: Path,
) -> None:
    # Execute the test reference resolver rejects snapshot below strategy minimum fidelity
    # workflow in explicit, reviewable steps.
    source, descriptor = _identity_source(
        (_identity_swap_row(signature="candidate-only", transaction_index=1),),
        identity=IdentityFidelity.CANDIDATE,
        total_key=("slot", "transaction_index", "event_index", "signature"),
        batch_size=1,
        # Complete _identity_source only after its candidate-only and slot inputs are visible
        # in test reference resolver rejects snapshot below strategy minimum fidelity.
    )
    artifacts = LocalArtifactRepository(tmp_path / "var")
    plan = _identity_plan(source, artifacts, descriptor, include_block_clock=True)
    prepared = PrepareDataset(
        source,
        # Keep the descriptor _identity_projector step visible while building prepared.
        _identity_projector(descriptor),
        LocalArrowCanonicalStore(artifacts, memory_limit_mb=256),
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    ).execute(PrepareDatasetRequest(plan))

    with pytest.raises(
        # Pass reference run resolution error explicitly so raises receives a reviewable
        # identity=candidate<exact and reference run resolution error input in test
        # reference resolver rejects snapshot below strategy minimum fidelity.
        ReferenceRunResolutionError,
        match=r"identity=CANDIDATE<EXACT",
    ):
        # Keep raises, reference run resolution error and pytest active only for the
        # bounded test reference resolver rejects snapshot below strategy minimum fidelity
        # operation.
        ReferenceRunSpecResolver(
            artifacts,
            RuntimeLockId("9" * 64),
            parquet_memory_limit_mb=256,
            threads=1,
            # Complete ReferenceRunSpecResolver only after its 9 and runtime lock id inputs
            # are visible in test reference resolver rejects snapshot below strategy minimum
            # fidelity.
        ).resolve(
            ReferenceRunDraft(
                snapshot_id=prepared.snapshot_id,
                replay_pack_id=None,
                delivery_schedule_id=None,
                # Pass pool id explicitly to resolve for pool and sol.
                pool_id=PoolId("pool"),
                sold_asset_id=AssetId("SOL"),
                bought_asset_id=AssetId("TOKEN"),
                amount_in_atomic=100,
                minimum_amount_out_atomic=0,
                # Pass fee bps explicitly so ReferenceRunDraft receives a reviewable pool
                # and sol input in test reference resolver rejects snapshot below strategy
                # minimum fidelity.
                fee_bps=30,
                execution_mode=ExecutionMode.SHADOW_STATE_REPLAY,
                maximum_order_input_atomic=1_000,
                observation_slots=0,
                order_slots=0,
                # Pass initial portfolio explicitly to resolve for pool and sol.
                initial_portfolio=(AssetBalance(AssetId("SOL"), 1_000),),
                root_seed=42,
                maximum_dynamic_items=10_000,
            )
        )


# Define test prepare and replay preserve proven cut fidelity as one focused operation
# with an explicit boundary.
def test_prepare_and_replay_preserve_proven_cut_fidelity(tmp_path: Path) -> None:
    # Execute the test prepare and replay preserve proven cut fidelity workflow in
    # explicit, reviewable steps.
    evidence = CapabilityCutEvidence(
        capability_id=SWAPS,
        block_range=_block_range(100, 101),
        snapshot_cut_to_block=101,
        chain_finality=ChainFinality.FINALIZED,
        # Pass ingestion watermark to block explicitly so CapabilityCutEvidence receives a
        # reviewable fixture-revision-7 and finalized input in test prepare and replay
        # preserve proven cut fidelity.
        ingestion_watermark_to_block=101,
        completeness=IngestionCompleteness.COMPLETE_TO_WATERMARK,
        consistency=SourceConsistency.SNAPSHOT_CONSISTENT,
        upstream_revision="fixture-revision-7",
    )
    # Assemble (source, descriptor) once so the test prepare and replay preserve proven
    # cut fidelity workflow shares one value.
    source, descriptor = _identity_source(
        (_identity_swap_row(signature="proven", transaction_index=1),),
        identity=IdentityFidelity.EXACT,
        total_key=("slot", "transaction_index", "event_index", "signature"),
        batch_size=1,
        # Pass cut evidence explicitly so _identity_source receives a reviewable proven
        # and slot input in test prepare and replay preserve proven cut fidelity.
        cut_evidence=evidence,
    )
    artifacts = LocalArtifactRepository(tmp_path / "var")
    plan = _identity_plan(source, artifacts, descriptor, include_block_clock=True)
    prepared = PrepareDataset(
        # Pass source explicitly so execute receives a reviewable prepare dataset request
        # and plan input in test prepare and replay preserve proven cut fidelity.
        source,
        _identity_projector(descriptor),
        LocalArrowCanonicalStore(artifacts, memory_limit_mb=256),
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    ).execute(PrepareDatasetRequest(plan))
    # Assemble effective once so the test prepare and replay preserve proven cut fidelity
    # workflow shares one value.
    effective = prepared.distributions[0].effective_source_boundary

    assert effective.source_fidelity == descriptor.fidelity
    assert effective.source_boundary.ingestion_watermark_to_block == 101
    assert effective.source_boundary.upstream_revision == "fixture-revision-7"

    compiled = LocalNumpyReplayPackCompiler(
        # Pass artifacts explicitly so compile receives a reviewable snapshot id and
        # prepared input in test prepare and replay preserve proven cut fidelity.
        artifacts,
        lambda snapshot_id: CanonicalParquetReplaySource(artifacts, snapshot_id),
        runtime_lock_id=RuntimeLockId("9" * 64),
    ).compile(prepared.snapshot_id, NUMPY_REPLAY_COMPILER_VERSION)
    assert [item.identity_document() for item in compiled.manifest.source_boundaries] == [
        # Keep the item expectation tied to identity document, item and source boundaries
        # in this scenario.
        item.effective_source_boundary.identity_document()
        for item in prepared.distributions
    ]


def test_incremental_prepare_reuses_exact_cross_plan_shard_and_scans_only_tail(
    tmp_path: Path,
    # Close the test incremental prepare reuses exact cross plan shard and scans only tail
    # signature after its explicit inputs.
) -> None:
    # Execute the test incremental prepare reuses exact cross plan shard and scans only
    # tail workflow in explicit, reviewable steps.
    evidence = _strong_cut(to_block=102)
    source, descriptor = _identity_source(
        (_identity_swap_row(signature="proven", transaction_index=1),),
        identity=IdentityFidelity.EXACT,
        total_key=("slot", "transaction_index", "event_index", "signature"),
        # Pass batch size explicitly so _identity_source receives a reviewable proven and
        # slot input in test incremental prepare reuses exact cross plan shard and scans
        # only tail.
        batch_size=1,
        cut_evidence=evidence,
    )
    artifacts = LocalArtifactRepository(tmp_path / "var")
    short_plan = _identity_plan(source, artifacts, descriptor)
    # Assemble long plan once so the test incremental prepare reuses exact cross plan
    # shard and scans only tail workflow shares one value.
    long_plan = _identity_plan(
        source,
        artifacts,
        descriptor,
        decision_range=_block_range(100, 102),
        # Pass max shard blocks explicitly so _identity_plan receives a reviewable block
        # range and source input in test incremental prepare reuses exact cross plan shard
        # and scans only tail.
        max_shard_blocks=1,
    )
    assert (
        short_plan.spec.source_inspection_artifact_id
        == long_plan.spec.source_inspection_artifact_id
        # Verify the source inspection artifact id, spec and short plan relationship before
        # this scenario is accepted.
    )
    projector = _identity_projector(descriptor)
    store = LocalArrowCanonicalStore(artifacts, memory_limit_mb=256)
    first = PrepareDataset(
        source,
        # Pass projector explicitly so execute receives a reviewable prepare dataset
        # request and short plan input in test incremental prepare reuses exact cross plan
        # shard and scans only tail.
        projector,
        store,
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    ).execute(PrepareDatasetRequest(short_plan))
    catalog, ledger, observer = _canonical_index(artifacts, tmp_path / "catalog.sqlite")
    # Invoke _index_canonical_outputs for distributions and catalog as a visible test
    # incremental prepare reuses exact cross plan shard and scans only tail step.
    _index_canonical_outputs(catalog, observer, first.distributions)

    resolver = GapSafePrepareDatasetJobResolver(ledger, projector)
    resolved = resolver.resolve(PrepareDatasetJobDraft(long_plan))
    assert resolved.reusable_distributions == (
        ReusableCanonicalDistribution(0, first.distributions[0].artifact.artifact_id),
        # Verify the reusable distributions, resolved and reusable canonical distribution
        # relationship before this scenario is accepted.
    )

    counting_source = _ScanProbe(source)
    second = PrepareDataset(
        counting_source,
        projector,
        # Pass store explicitly so execute receives a reviewable reusable distributions
        # and prepare dataset request input in test incremental prepare reuses exact cross
        # plan shard and scans only tail.
        store,
        clock=lambda: datetime(2026, 1, 2, tzinfo=UTC),
    ).execute(PrepareDatasetRequest(long_plan, resolved.reusable_distributions))
    assert counting_source.shard_ordinals == [1]
    assert second.distributions[0].artifact == first.distributions[0].artifact
    # Verify the ordinal, shard and item relationship before this scenario is accepted.
    assert [item.shard.ordinal for item in second.distributions] == [0, 1]

    _index_canonical_outputs(catalog, observer, (second.distributions[1],))
    fully_resolved = resolver.resolve(PrepareDatasetJobDraft(long_plan))
    assert [item.shard_ordinal for item in fully_resolved.reusable_distributions] == [0, 1]
    no_scan_source = _ScanProbe(source, fail_on_scan=True)
    # Assemble third once so the test incremental prepare reuses exact cross plan shard
    # and scans only tail workflow shares one value.
    third = PrepareDataset(
        no_scan_source,
        projector,
        store,
        clock=lambda: datetime(2026, 1, 3, tzinfo=UTC),
        # Keep the long plan PrepareDatasetRequest step visible while building third.
    ).execute(PrepareDatasetRequest(long_plan, fully_resolved.reusable_distributions))
    assert no_scan_source.shard_ordinals == []
    assert [item.artifact for item in third.distributions] == [
        item.artifact for item in second.distributions
    ]
    # Verify the snapshot id, third and second relationship before this scenario is
    # accepted.
    assert third.snapshot_id == second.snapshot_id


def test_candidate_merge_primes_one_reader_per_capability_not_per_shard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, descriptor = _identity_source(
        (_identity_swap_row(signature="bounded-readers", transaction_index=1),),
        identity=IdentityFidelity.EXACT,
        total_key=("slot", "transaction_index", "event_index", "signature"),
        batch_size=1,
        cut_evidence=_strong_cut(to_block=104),
    )
    artifacts = LocalArtifactRepository(tmp_path / "var")
    plan = _identity_plan(
        source,
        artifacts,
        descriptor,
        decision_range=_block_range(100, 104),
        max_shard_blocks=1,
        include_block_clock=True,
    )
    projector = _identity_projector(descriptor)
    prepared = PrepareDataset(
        source,
        projector,
        LocalArrowCanonicalStore(artifacts, memory_limit_mb=256),
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    ).execute(PrepareDatasetRequest(plan))
    distributions = tuple(
        replace(
            item,
            source_boundary=replace(
                item.source_boundary,
                query_fingerprints=tuple(
                    ContentDigest(fingerprint.hex)
                    for fingerprint in item.source_boundary.query_fingerprints
                ),
            ),
        )
        for item in prepared.distributions
    )
    assert len(distributions) == 8

    block = next(item for item in distributions if item.capability_id == BLOCKS)
    handle = artifacts.open_committed(block.artifact.artifact_id)
    try:
        sample = next(
            parquet_replay_module._partition_events(
                handle.local_path("events.parquet"),
                block.event_kind,
                network_id=plan.spec.network_id,
                position_schema_id=plan.spec.position_schema_id,
                batch_rows=1,
                readahead=1,
            )
        )
    finally:
        handle.close()

    candidate = CanonicalDistributionCandidateSource(
        artifacts,
        plan.spec,
        distributions,
        projector_bundle_id=projector.bundle_id,
        writer_bundle_id=canonical_writer_bundle_id(),
        reader_batch_rows=1,
        reader_readahead=1,
    )
    active = 0
    maximum_active = 0

    def tracked_partition(*_: object, **__: object) -> Any:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        try:
            yield sample
        finally:
            active -= 1

    monkeypatch.setattr(parquet_replay_module, "_partition_events", tracked_partition)

    assert len(tuple(candidate.events())) == len(distributions)
    assert maximum_active == len(plan.spec.capabilities)
    assert active == 0


def test_snapshot_replay_primes_one_reader_per_capability_not_per_shard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, descriptor = _identity_source(
        (_identity_swap_row(signature="bounded-snapshot-readers", transaction_index=1),),
        identity=IdentityFidelity.EXACT,
        total_key=("slot", "transaction_index", "event_index", "signature"),
        batch_size=1,
        cut_evidence=_strong_cut(to_block=104),
    )
    artifacts = LocalArtifactRepository(tmp_path / "var")
    plan = _identity_plan(
        source,
        artifacts,
        descriptor,
        decision_range=_block_range(100, 104),
        max_shard_blocks=1,
        include_block_clock=True,
    )
    prepared = PrepareDataset(
        source,
        _identity_projector(descriptor),
        LocalArrowCanonicalStore(artifacts, memory_limit_mb=256),
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    ).execute(PrepareDatasetRequest(plan))
    assert len(prepared.distributions) == 8

    original_partition_events = parquet_replay_module._partition_events
    active = 0
    maximum_active = 0

    def tracked_partition(*args: object, **kwargs: object) -> Any:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        try:
            yield from original_partition_events(*args, **kwargs)
        finally:
            active -= 1

    monkeypatch.setattr(parquet_replay_module, "_partition_events", tracked_partition)
    replay = CanonicalParquetReplaySource(
        artifacts,
        prepared.snapshot_id,
        duckdb_memory_limit_mb=256,
        reader_batch_rows=1,
        reader_readahead=1,
    )

    assert tuple(replay.events())
    assert maximum_active == len(plan.spec.capabilities)
    assert active == 0


def test_snapshot_and_replay_payloads_are_invariant_to_physical_sharding(
    tmp_path: Path,
) -> None:
    source, descriptor = _identity_source(
        (_identity_swap_row(signature="shard-invariant", transaction_index=1),),
        identity=IdentityFidelity.EXACT,
        total_key=("slot", "transaction_index", "event_index", "signature"),
        batch_size=1,
        cut_evidence=_strong_cut(to_block=104),
    )
    first_artifacts = LocalArtifactRepository(tmp_path / "first")
    second_artifacts = LocalArtifactRepository(tmp_path / "second")
    first_plan = _identity_plan(
        source,
        first_artifacts,
        descriptor,
        decision_range=_block_range(100, 104),
        max_shard_blocks=4,
        include_block_clock=True,
    )
    second_plan = _identity_plan(
        source,
        second_artifacts,
        descriptor,
        decision_range=_block_range(100, 104),
        max_shard_blocks=1,
        include_block_clock=True,
    )
    projector = _identity_projector(descriptor)
    first = PrepareDataset(
        source,
        projector,
        LocalArrowCanonicalStore(first_artifacts, memory_limit_mb=256),
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    ).execute(PrepareDatasetRequest(first_plan))
    second = PrepareDataset(
        source,
        projector,
        LocalArrowCanonicalStore(second_artifacts, memory_limit_mb=256),
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    ).execute(PrepareDatasetRequest(second_plan))

    assert len(first.distributions) == 2
    assert len(second.distributions) == 8
    assert first_plan.spec.spec_id != second_plan.spec.spec_id
    assert first.dataset_revision_id != second.dataset_revision_id
    assert first.snapshot_id != second.snapshot_id

    first_parquet = CanonicalParquetReplaySource(
        first_artifacts,
        first.snapshot_id,
        duckdb_memory_limit_mb=256,
        reader_batch_rows=1,
        reader_readahead=1,
    )
    second_parquet = CanonicalParquetReplaySource(
        second_artifacts,
        second.snapshot_id,
        duckdb_memory_limit_mb=256,
        reader_batch_rows=1,
        reader_readahead=1,
    )
    assert tuple(first_parquet.events()) == tuple(second_parquet.events())
    assert first_parquet.logical_content_hash == second_parquet.logical_content_hash
    assert first_parquet.boundaries() == second_parquet.boundaries()
    assert first_parquet.transaction_clock() == second_parquet.transaction_clock()

    first_compiled = CompileReplay(
        LocalNumpyReplayPackCompiler(
            first_artifacts,
            lambda snapshot_id: CanonicalParquetReplaySource(
                first_artifacts,
                snapshot_id,
                duckdb_memory_limit_mb=256,
                reader_batch_rows=1,
                reader_readahead=1,
            ),
            runtime_lock_id=RuntimeLockId("6" * 64),
        )
    ).execute(CompileReplayRequest(first.snapshot_id, NUMPY_REPLAY_COMPILER_VERSION))
    second_compiled = CompileReplay(
        LocalNumpyReplayPackCompiler(
            second_artifacts,
            lambda snapshot_id: CanonicalParquetReplaySource(
                second_artifacts,
                snapshot_id,
                duckdb_memory_limit_mb=256,
                reader_batch_rows=1,
                reader_readahead=1,
            ),
            runtime_lock_id=RuntimeLockId("6" * 64),
        )
    ).execute(CompileReplayRequest(second.snapshot_id, NUMPY_REPLAY_COMPILER_VERSION))
    assert first_compiled.replay_build_key != second_compiled.replay_build_key
    assert first_compiled.replay_pack_id != second_compiled.replay_pack_id

    with (
        NumpyMmapReplaySource(first_artifacts, first_compiled.replay_pack_id) as first_replay,
        NumpyMmapReplaySource(second_artifacts, second_compiled.replay_pack_id) as second_replay,
    ):
        assert tuple(first_replay.events()) == tuple(second_replay.events())
        assert first_replay.boundaries() == second_replay.boundaries()
        assert first_replay.transaction_clock() == second_replay.transaction_clock()
        first_arrays = first_replay.arrays()
        second_arrays = second_replay.arrays()
        assert first_arrays.keys() == second_arrays.keys()
        for path in first_arrays:
            assert first_arrays[path].dtype.str == second_arrays[path].dtype.str
            assert first_arrays[path].shape == second_arrays[path].shape
            assert first_arrays[path].tobytes() == second_arrays[path].tobytes()


def test_incremental_reuse_selects_expected_build_from_same_logical_revision(
    tmp_path: Path,
) -> None:
    evidence = _strong_cut(to_block=101)
    source, descriptor = _identity_source(
        (_identity_swap_row(signature="physical-variants", transaction_index=1),),
        identity=IdentityFidelity.EXACT,
        total_key=("slot", "transaction_index", "event_index", "signature"),
        batch_size=1,
        cut_evidence=evidence,
    )
    artifacts = LocalArtifactRepository(tmp_path / "var")
    plan = _identity_plan(source, artifacts, descriptor)
    projector = _identity_projector(descriptor)
    prepared = PrepareDataset(
        source,
        projector,
        LocalArrowCanonicalStore(artifacts, memory_limit_mb=256),
    ).execute(PrepareDatasetRequest(plan))
    current = prepared.distributions[0]
    old_writer_bundle_id = BundleId("0" * 64)
    capability = next(
        item for item in plan.spec.capabilities if item.capability_id == current.shard.capability_id
    )
    old_build_key = canonical_distribution_build_key(
        plan=plan,
        shard=current.shard,
        capability=capability,
        event_kind=current.event_kind,
        projector_bundle_id=projector.bundle_id,
        writer_bundle_id=old_writer_bundle_id,
    )
    old_variant = _distribution_with_writer_variant(
        artifacts,
        current.artifact,
        writer_bundle_id=old_writer_bundle_id,
        build_key=old_build_key,
    )
    catalog, ledger, observer = _canonical_index(artifacts, tmp_path / "catalog.sqlite")
    for artifact in (old_variant, current.artifact):
        catalog.index_committed(artifact)
    observer.observe((old_variant, current.artifact))

    resolved = GapSafePrepareDatasetJobResolver(ledger, projector).resolve(
        PrepareDatasetJobDraft(plan)
    )

    assert resolved.reusable_distributions == (
        ReusableCanonicalDistribution(0, current.artifact.artifact_id),
    )
    assert old_variant.build_key != current.artifact.build_key


def test_incremental_prepare_rescans_unknown_mutable_revision(tmp_path: Path) -> None:
    # Execute the test incremental prepare rescans unknown mutable revision workflow in
    # explicit, reviewable steps.
    source, descriptor = _identity_source(
        (_identity_swap_row(signature="mutable", transaction_index=1),),
        identity=IdentityFidelity.EXACT,
        total_key=("slot", "transaction_index", "event_index", "signature"),
        batch_size=1,
        # Complete _identity_source only after its mutable and slot inputs are visible in test
        # incremental prepare rescans unknown mutable revision.
    )
    artifacts = LocalArtifactRepository(tmp_path / "var")
    plan = _identity_plan(source, artifacts, descriptor)
    projector = _identity_projector(descriptor)
    store = LocalArrowCanonicalStore(artifacts, memory_limit_mb=256)
    # Assemble first once so the test incremental prepare rescans unknown mutable revision
    # workflow shares one value.
    first = PrepareDataset(source, projector, store).execute(PrepareDatasetRequest(plan))
    catalog, ledger, observer = _canonical_index(artifacts, tmp_path / "catalog.sqlite")
    _index_canonical_outputs(catalog, observer, first.distributions)

    resolved = GapSafePrepareDatasetJobResolver(ledger, projector).resolve(
        PrepareDatasetJobDraft(plan)
        # Complete resolve only after its prepare dataset job draft and plan inputs are
        # visible in test incremental prepare rescans unknown mutable revision.
    )
    counting_source = _ScanProbe(source)
    PrepareDataset(counting_source, projector, store).execute(
        PrepareDatasetRequest(plan, resolved.reusable_distributions)
    )

    # Verify resolved.reusable_distributions == () before this scenario is accepted.
    assert resolved.reusable_distributions == ()
    assert counting_source.shard_ordinals == [0]


def test_incremental_frontier_never_selects_a_shard_beyond_a_gap(tmp_path: Path) -> None:
    # Execute the test incremental frontier never selects a shard beyond a gap workflow in
    # explicit, reviewable steps.
    source, descriptor = _identity_source(
        (_identity_swap_row(signature="gap", transaction_index=1),),
        identity=IdentityFidelity.EXACT,
        total_key=("slot", "transaction_index", "event_index", "signature"),
        batch_size=1,
        # Keep the strong cut _strong_cut step visible while building (source,
        # descriptor).
        cut_evidence=_strong_cut(to_block=103),
    )
    artifacts = LocalArtifactRepository(tmp_path / "var")
    plan = _identity_plan(
        source,
        # Pass artifacts explicitly so _identity_plan receives a reviewable block range
        # and source input in test incremental frontier never selects a shard beyond a
        # gap.
        artifacts,
        descriptor,
        decision_range=_block_range(100, 103),
        max_shard_blocks=1,
    )
    # Assemble projector once so the test incremental frontier never selects a shard
    # beyond a gap workflow shares one value.
    projector = _identity_projector(descriptor)
    prepared = PrepareDataset(
        source,
        projector,
        LocalArrowCanonicalStore(artifacts, memory_limit_mb=256),
        # Keep the plan PrepareDatasetRequest step visible while building prepared.
    ).execute(PrepareDatasetRequest(plan))
    catalog, ledger, observer = _canonical_index(artifacts, tmp_path / "catalog.sqlite")
    _index_canonical_outputs(
        catalog,
        observer,
        # Open the distributions and catalog payload explicitly for
        # _index_canonical_outputs within test incremental frontier never selects a shard
        # beyond a gap.
        (prepared.distributions[0], prepared.distributions[2]),
    )

    resolved = GapSafePrepareDatasetJobResolver(ledger, projector).resolve(
        PrepareDatasetJobDraft(plan)
    )

    # Verify the reusable distributions, resolved and reusable canonical distribution
    # relationship before this scenario is accepted.
    assert resolved.reusable_distributions == (
        ReusableCanonicalDistribution(
            0,
            prepared.distributions[0].artifact.artifact_id,
        ),
        # Verify the reusable distributions, resolved and reusable canonical distribution
        # relationship before this scenario is accepted.
    )


def test_reusable_distribution_rejects_every_exact_contract_mismatch(
    tmp_path: Path,
) -> None:
    # Execute the test reusable distribution rejects every exact contract mismatch
    # workflow in explicit, reviewable steps.
    evidence = _strong_cut(to_block=101)
    source, descriptor = _identity_source(
        (_identity_swap_row(signature="exact", transaction_index=1),),
        identity=IdentityFidelity.EXACT,
        total_key=("slot", "transaction_index", "event_index", "signature"),
        # Pass batch size explicitly so _identity_source receives a reviewable exact and
        # slot input in test reusable distribution rejects every exact contract mismatch.
        batch_size=1,
        cut_evidence=evidence,
    )
    artifacts = LocalArtifactRepository(tmp_path / "var")
    plan = _identity_plan(source, artifacts, descriptor)
    # Assemble projector once so the test reusable distribution rejects every exact
    # contract mismatch workflow shares one value.
    projector = _identity_projector(descriptor)
    store = LocalArrowCanonicalStore(artifacts, memory_limit_mb=256)
    prepared = PrepareDataset(source, projector, store).execute(PrepareDatasetRequest(plan))
    artifact_id = prepared.distributions[0].artifact.artifact_id
    catalog, ledger, observer = _canonical_index(artifacts, tmp_path / "catalog.sqlite")
    # Invoke _index_canonical_outputs for distributions and catalog as a visible test
    # reusable distribution rejects every exact contract mismatch step.
    _index_canonical_outputs(catalog, observer, prepared.distributions)

    changed_revision = _clone_plan(
        plan,
        cut_evidence=(replace(evidence, upstream_revision="upstream-revision-2"),),
    )
    # Assemble changed cut once so the test reusable distribution rejects every exact
    # contract mismatch workflow shares one value.
    changed_cut = _clone_plan(
        plan,
        cut_evidence=(replace(evidence, block_range=_block_range(99, 101)),),
    )
    changed_capability_schema = _clone_plan(
        # Pass plan explicitly so _clone_plan receives a reviewable 2 and capabilities
        # input in test reusable distribution rejects every exact contract mismatch.
        plan,
        capabilities=(replace(plan.spec.capabilities[0], schema_version="2"),),
    )
    changed_source_schema = _clone_plan(
        plan,
        # Keep the content digest and a ContentDigest step visible while building changed
        # source schema.
        source_schema_fingerprint=ContentDigest("a" * 64),
    )
    changed_query = _clone_plan(
        plan,
        query_template_digest=ContentDigest("b" * 64),
        # Complete _clone_plan only after its b and content digest inputs are visible in test
        # reusable distribution rejects every exact contract mismatch.
    )
    changed_inspection = _clone_plan(
        plan,
        source_inspection_artifact_id=ArtifactId("c" * 64),
    )
    # Traverse changed revision, changed cut and changed capability schema explicitly so
    # each test reusable distribution rejects every exact contract mismatch iteration
    # remains traceable.
    for mismatched_plan in (
        changed_revision,
        changed_cut,
        changed_capability_schema,
        changed_source_schema,
        # Traverse changed revision, changed cut and changed capability schema explicitly
        # so each test reusable distribution rejects every exact contract mismatch
        # iteration remains traceable.
        changed_query,
        changed_inspection,
    ):
        # Process changed revision, changed cut and changed capability schema inside the
        # bounded test reusable distribution rejects every exact contract mismatch loop.
        assert (
            GapSafePrepareDatasetJobResolver(ledger, projector)
            .resolve(PrepareDatasetJobDraft(mismatched_plan))
            .reusable_distributions
            == ()
            # Verify the reusable distributions, resolve and prepare dataset job draft
            # relationship before this scenario is accepted.
        )
        with pytest.raises(CanonicalDataError):
            _open_reusable(store, projector, mismatched_plan, artifact_id)

    changed_projector = _ProjectorBundleOverride(projector, BundleId("f" * 64))
    assert (
        # Keep the gap safe prepare dataset job resolver expectation tied to reusable
        # distributions, resolve and prepare dataset job draft in this scenario.
        GapSafePrepareDatasetJobResolver(ledger, changed_projector)
        .resolve(PrepareDatasetJobDraft(plan))
        .reusable_distributions
        == ()
    )
    # Acquire raises, canonical data error and pytest at an explicit test reusable
    # distribution rejects every exact contract mismatch context boundary so cleanup
    # remains scoped.
    with pytest.raises(CanonicalDataError):
        # Keep raises, canonical data error and pytest active only for the bounded test
        # reusable distribution rejects every exact contract mismatch operation.
        store.open_reusable_distribution(
            artifact_id=artifact_id,
            plan=plan,
            shard=plan.spec.shards[0],
            capability=plan.spec.capabilities[0],
            # Pass event kind explicitly to open_reusable_distribution for f and shards.
            event_kind=projector.event_kind(SWAPS),
            projector_bundle_id=BundleId("f" * 64),
        )

    wrong_writer_artifact = _distribution_with_wrong_writer(
        artifacts,
        # Pass prepared explicitly so _distribution_with_wrong_writer receives a
        # reviewable artifact and distributions input in test reusable distribution
        # rejects every exact contract mismatch.
        prepared.distributions[0].artifact,
    )
    with pytest.raises(CanonicalDataError, match="manifest differs"):
        _open_reusable(store, projector, plan, wrong_writer_artifact.artifact_id)

    wrong_bounds_artifact = _distribution_with_out_of_bounds_block(
        # Pass artifacts explicitly so _distribution_with_out_of_bounds_block receives a
        # reviewable artifact and distributions input in test reusable distribution
        # rejects every exact contract mismatch.
        artifacts,
        prepared.distributions[0].artifact,
    )
    with pytest.raises(CanonicalDataError, match="exact shard contract"):
        _open_reusable(store, projector, plan, wrong_bounds_artifact.artifact_id)


# Define test reusable distribution missing or tampered bytes fail closed as one focused
# operation with an explicit boundary.
def test_reusable_distribution_missing_or_tampered_bytes_fail_closed(tmp_path: Path) -> None:
    # Execute the test reusable distribution missing or tampered bytes fail closed
    # workflow in explicit, reviewable steps.
    source, descriptor = _identity_source(
        (_identity_swap_row(signature="integrity", transaction_index=1),),
        identity=IdentityFidelity.EXACT,
        total_key=("slot", "transaction_index", "event_index", "signature"),
        batch_size=1,
        # Keep the strong cut _strong_cut step visible while building (source,
        # descriptor).
        cut_evidence=_strong_cut(to_block=101),
    )
    artifacts = LocalArtifactRepository(tmp_path / "var")
    plan = _identity_plan(source, artifacts, descriptor)
    projector = _identity_projector(descriptor)
    # Assemble store once so the test reusable distribution missing or tampered bytes fail
    # closed workflow shares one value.
    store = LocalArrowCanonicalStore(artifacts, memory_limit_mb=256)
    prepared = PrepareDataset(source, projector, store).execute(PrepareDatasetRequest(plan))

    with pytest.raises(ArtifactNotCommittedError):
        _open_reusable(store, projector, plan, ArtifactId("0" * 64))

    artifact_id = prepared.distributions[0].artifact.artifact_id
    # Assemble handle once so the test reusable distribution missing or tampered bytes
    # fail closed workflow shares one value.
    handle = artifacts.open_committed(artifact_id)
    try:
        event_path = cast(Any, handle).local_path("events.parquet")
    finally:
        handle.close()
    # Invoke write_bytes for read bytes and event path as a visible test reusable
    # distribution missing or tampered bytes fail closed step.
    event_path.write_bytes(event_path.read_bytes() + b"tampered")
    with pytest.raises(ArtifactIntegrityError):
        _open_reusable(store, projector, plan, artifact_id)


# Keep the scan probe contract and validation rules together.
class _ScanProbe:
    def __init__(
        self,
        delegate: InMemorySourceReader,
        *,
        # Keep the fail on scan input explicit in the init contract.
        fail_on_scan: bool = False,
    ) -> None:
        # Execute the scan probe init workflow in explicit, reviewable steps.
        self._delegate = delegate
        self._fail_on_scan = fail_on_scan
        self.shard_ordinals: list[int] = []

    def scan(self, request: Any) -> Any:
        # Execute the scan probe scan workflow in explicit, reviewable steps.
        self.shard_ordinals.append(request.shard.ordinal)
        if self._fail_on_scan:
            raise AssertionError("a proven reusable shard reached the remote source")
        return self._delegate.scan(request)


# Keep the projector bundle override contract and validation rules together.
class _ProjectorBundleOverride:
    def __init__(
        self,
        delegate: ReferenceProtocolProjector,
        bundle_id: BundleId,
        # Close the init signature after its explicit inputs.
    ) -> None:
        # Execute the projector bundle override init workflow in explicit, reviewable
        # steps.
        self._delegate = delegate
        self.bundle_id = bundle_id

    def supports(self, capability_id: CapabilityId) -> bool:
        return self._delegate.supports(capability_id)

    def event_kind(self, capability_id: CapabilityId) -> Any:
        # Return the completed projector bundle override event kind result without a
        # hidden fallback.
        return self._delegate.event_kind(capability_id)

    def project(self, batch: Any) -> Any:
        return self._delegate.project(batch)


def _strong_cut(*, to_block: int) -> CapabilityCutEvidence:
    # Execute the strong cut workflow in explicit, reviewable steps.
    return CapabilityCutEvidence(
        capability_id=SWAPS,
        block_range=_block_range(100, to_block),
        snapshot_cut_to_block=to_block,
        chain_finality=ChainFinality.FINALIZED,
        # Pass ingestion watermark to block explicitly so CapabilityCutEvidence receives a
        # reviewable upstream-revision-1 and finalized input in strong cut.
        ingestion_watermark_to_block=to_block,
        completeness=IngestionCompleteness.COMPLETE_TO_WATERMARK,
        consistency=SourceConsistency.SNAPSHOT_CONSISTENT,
        upstream_revision="upstream-revision-1",
    )


# Define canonical index as one focused operation with an explicit boundary.
def _canonical_index(
    artifacts: LocalArtifactRepository,
    database: Path,
) -> tuple[SQLiteArtifactCatalog, SQLiteShardLedger, SQLiteCanonicalOutputObserver]:
    # Execute the canonical index workflow in explicit, reviewable steps.
    catalog = SQLiteArtifactCatalog(database, artifacts)
    ledger = SQLiteShardLedger(database, catalog)
    return catalog, ledger, SQLiteCanonicalOutputObserver(artifacts, ledger)


def _index_canonical_outputs(
    catalog: SQLiteArtifactCatalog,
    # Keep the observer input explicit in the index canonical outputs contract.
    observer: SQLiteCanonicalOutputObserver,
    distributions: tuple[Any, ...],
) -> None:
    # Execute the index canonical outputs workflow in explicit, reviewable steps.
    artifacts = tuple(item.artifact for item in distributions)
    for artifact in artifacts:
        catalog.index_committed(artifact)
    observer.observe(artifacts)


def _clone_plan(plan: DatasetPlan, **changes: object) -> DatasetPlan:
    # Execute the clone plan workflow in explicit, reviewable steps.
    spec = plan.spec
    fields: dict[str, object] = {
        "spec_version": spec.spec_version,
        "source_id": spec.source_id,
        "source_inspection_artifact_id": spec.source_inspection_artifact_id,
        # Keep the source schema fingerprint component named inside the fields contract.
        "source_schema_fingerprint": spec.source_schema_fingerprint,
        "capability_mapping_digest": spec.capability_mapping_digest,
        "query_template_digest": spec.query_template_digest,
        "network_id": spec.network_id,
        "position_schema_id": spec.position_schema_id,
        # Keep the decision range component named inside the fields contract.
        "decision_range": spec.decision_range,
        "settlement_tail": spec.settlement_tail,
        "warmup_blocks": spec.warmup_blocks,
        "evidence_contracts": spec.evidence_contracts,
        "capabilities": spec.capabilities,
        # Keep the capability ranges component named inside the fields contract.
        "capability_ranges": spec.capability_ranges,
        "cut_evidence": spec.cut_evidence,
        "shards": spec.shards,
    }
    fields.update(changes)
    # Assemble spec id once so the clone plan workflow shares one value.
    spec_id = dataset_spec_identity_digest(**cast(Any, fields))
    return replace(plan, spec=DatasetSpec(spec_id=spec_id, **cast(Any, fields)))


def _open_reusable(
    store: LocalArrowCanonicalStore,
    projector: ReferenceProtocolProjector,
    # Keep the plan input explicit in the open reusable contract.
    plan: DatasetPlan,
    artifact_id: ArtifactId,
) -> Any:
    # Execute the open reusable workflow in explicit, reviewable steps.
    shard = plan.spec.shards[0]
    capability = next(
        item for item in plan.spec.capabilities if item.capability_id == shard.capability_id
    )
    return store.open_reusable_distribution(
        # Pass artifact id explicitly so open_reusable_distribution receives a reviewable
        # event kind and capability id input in open reusable.
        artifact_id=artifact_id,
        plan=plan,
        shard=shard,
        capability=capability,
        event_kind=projector.event_kind(shard.capability_id),
        # Pass projector bundle id explicitly so open_reusable_distribution receives a
        # reviewable event kind and capability id input in open reusable.
        projector_bundle_id=projector.bundle_id,
    )


def _distribution_with_wrong_writer(
    artifacts: LocalArtifactRepository,
    source: CommittedArtifact,
    # Keep the committed artifact input explicit in the distribution with wrong writer
    # contract.
) -> CommittedArtifact:
    # Execute the distribution with wrong writer workflow in explicit, reviewable steps.
    handle = artifacts.open_committed(source.artifact_id)
    try:
        # Perform the protected distribution with wrong writer operation before explicit
        # failure handling.
        with handle.open_binary("manifest.json") as stream:
            manifest = cast(dict[str, object], json.load(stream))
        with handle.open_binary("events.parquet") as stream:
            events = stream.read()
    finally:
        # Invoke close as a visible step within the distribution with wrong writer
        # workflow.
        handle.close()
    manifest["writer_bundle_id"] = "0" * 64
    identity_manifest = {key: value for key, value in manifest.items() if key != "created_at"}
    writer = artifacts.stage(
        ArtifactDraft(
            # Pass kind explicitly so ArtifactDraft receives a reviewable canonical
            # distribution and build key input in distribution with wrong writer.
            kind=ArtifactKind.CANONICAL_DISTRIBUTION,
            build_key=source.build_key,
            input_artifact_ids=source.input_artifact_ids,
        )
    )
    # Acquire open binary, parquet and writer at an explicit distribution with wrong
    # writer context boundary so cleanup remains scoped.
    with writer.open_binary("events.parquet") as stream:
        stream.write(events)
    return writer.commit(
        canonical_json_bytes(manifest),
        identity_manifest_bytes=canonical_json_bytes(identity_manifest),
        # Complete commit only after its canonical json bytes and manifest inputs are visible
        # in distribution with wrong writer.
    )


def _distribution_with_writer_variant(
    artifacts: LocalArtifactRepository,
    source: CommittedArtifact,
    *,
    writer_bundle_id: BundleId,
    build_key: ContentDigest,
) -> CommittedArtifact:
    handle = artifacts.open_committed(source.artifact_id)
    try:
        with handle.open_binary("manifest.json") as stream:
            manifest = cast(dict[str, object], json.load(stream))
        with handle.open_binary("events.parquet") as stream:
            events = stream.read()
    finally:
        handle.close()
    manifest["writer_bundle_id"] = writer_bundle_id.hex
    identity_manifest = {key: value for key, value in manifest.items() if key != "created_at"}
    writer = artifacts.stage(
        ArtifactDraft(
            kind=ArtifactKind.CANONICAL_DISTRIBUTION,
            build_key=build_key,
            input_artifact_ids=source.input_artifact_ids,
        )
    )
    with writer.open_binary("events.parquet") as stream:
        stream.write(events)
    return writer.commit(
        canonical_json_bytes(manifest),
        identity_manifest_bytes=canonical_json_bytes(identity_manifest),
    )


def _distribution_with_out_of_bounds_block(
    artifacts: LocalArtifactRepository,
    source: CommittedArtifact,
) -> CommittedArtifact:
    # Execute the distribution with out of bounds block workflow in explicit, reviewable
    # steps.
    handle = artifacts.open_committed(source.artifact_id)
    try:
        # Perform the protected distribution with out of bounds block operation before
        # explicit failure handling.
        with handle.open_binary("manifest.json") as stream:
            manifest = cast(dict[str, object], json.load(stream))
        table = pq.read_table(cast(Any, handle).local_path("events.parquet"))
    finally:
        handle.close()
    # Assemble block index once so the distribution with out of bounds block workflow
    # shares one value.
    block_index = table.schema.get_field_index("block_ordinal")
    table = table.set_column(
        block_index,
        table.schema.field(block_index),
        pa.array([99] * table.num_rows, type=pa.uint32()),
        # Complete set_column only after its field and schema inputs are visible in
        # distribution with out of bounds block.
    )
    identity_manifest = {key: value for key, value in manifest.items() if key != "created_at"}
    writer = artifacts.stage(
        ArtifactDraft(
            kind=ArtifactKind.CANONICAL_DISTRIBUTION,
            # Pass build key explicitly so ArtifactDraft receives a reviewable canonical
            # distribution and build key input in distribution with out of bounds block.
            build_key=source.build_key,
            input_artifact_ids=source.input_artifact_ids,
        )
    )
    with writer.open_binary("events.parquet") as stream:
        # Keep open binary, parquet and writer active only for the bounded distribution
        # with out of bounds block operation.
        pq.write_table(
            table,
            stream,
            compression="zstd",
            use_dictionary=True,
            # Pass write statistics explicitly so write_table receives a reviewable zstd
            # and table input in distribution with out of bounds block.
            write_statistics=True,
        )
    return writer.commit(
        canonical_json_bytes(manifest),
        identity_manifest_bytes=canonical_json_bytes(identity_manifest),
        # Complete commit only after its canonical json bytes and manifest inputs are visible
        # in distribution with out of bounds block.
    )


def _identity_source(
    rows: tuple[dict[str, object], ...],
    *,
    identity: IdentityFidelity,
    # Keep the total key input explicit in the identity source contract.
    total_key: tuple[str, ...],
    batch_size: int,
    cut_evidence: CapabilityCutEvidence | None = None,
) -> tuple[InMemorySourceReader, CapabilityDescriptor]:
    # Execute the identity source workflow in explicit, reviewable steps.
    columns = (
        "bought_amount_atomic",
        "bought_asset_id",
        "event_index",
        "fee_amount_atomic",
        # Keep the pool asset a id component named inside the columns contract.
        "pool_asset_a_id",
        "pool_asset_b_id",
        "pool_id",
        "reserve_a_after_atomic",
        "reserve_b_after_atomic",
        # Keep the signature component named inside the columns contract.
        "signature",
        "slot",
        "sold_amount_atomic",
        "sold_asset_id",
        "transaction_index",
        # Complete the columns group only after its semantic components are visible.
    )
    descriptor = CapabilityDescriptor(
        capability_id=SWAPS,
        protocol="reference_amm",
        protocol_version="1",
        # Pass schema version explicitly so CapabilityDescriptor receives a reviewable
        # reference amm and 1 input in identity source.
        schema_version="1",
        stream=CapabilityStream.PUMP_CURVE_TRADE,
        columns=columns,
        mandatory_columns=columns,
        fidelity=SourceFidelity(
            # Pass identity explicitly so SourceFidelity receives a reviewable instruction
            # exact and before after input in identity source.
            identity=identity,
            ordering=OrderingFidelity.INSTRUCTION_EXACT,
            state=StateFidelity.BEFORE_AFTER,
            fees=FeesFidelity.COMPONENTS,
            chain_finality=(
                # Pass chain finality explicitly so SourceFidelity receives a reviewable
                # instruction exact and before after input in identity source.
                ChainFinality.UNKNOWN if cut_evidence is None else cut_evidence.chain_finality
            ),
            completeness=(
                IngestionCompleteness.UNKNOWN if cut_evidence is None else cut_evidence.completeness
            ),
            # Pass consistency explicitly so SourceFidelity receives a reviewable
            # instruction exact and before after input in identity source.
            consistency=(
                SourceConsistency.UNKNOWN if cut_evidence is None else cut_evidence.consistency
            ),
        ),
        total_key=total_key,
        # Keep the total key bool step visible while building descriptor.
        keyset_key_is_proven=bool(total_key),
    )
    metadata = SourceMetadata(
        source_id=SourceId("identity-fixture-indexer"),
        network_id=SOLANA_MAINNET_NETWORK_ID,
        # Pass position schema id explicitly so SourceMetadata receives a reviewable
        # identity-fixture-indexer and fixture-v1 input in identity source.
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        server_version="fixture-v1",
        tables=(),
        capabilities=(
            descriptor,
            # Keep the blocks _descriptor step visible while building metadata.
            _descriptor(
                BLOCKS,
                "solana",
                ("block_hash", "block_time", "slot", "transaction_count"),
                ("slot",),
                # Pass ordering fidelity explicitly so _descriptor receives a reviewable
                # solana and block hash input in identity source.
                OrderingFidelity.TRANSACTION_EXACT,
            ),
        ),
        capability_mapping_digest=domain_digest(
            "test.identity-capability-mapping.v1",
            # Open the v1 and fixture payload explicitly for domain_digest within identity
            # source.
            {"fixture": 1},
        ),
        query_template_digest=domain_digest(
            "test.identity-query-template.v1",
            {"fixture": 1},
            # Complete domain_digest only after its v1 and fixture inputs are visible in
            # identity source.
        ),
        cut_evidence=() if cut_evidence is None else (cut_evidence,),
    )
    return (
        InMemorySourceReader(
            # Pass metadata explicitly so InMemorySourceReader receives a reviewable block
            # hash and block time input in identity source.
            metadata,
            {
                BLOCKS: (
                    {
                        "block_hash": "identity-h100",
                        # Keep block time named so the block hash and block time payload
                        # passed to InMemorySourceReader remains self-describing within
                        # identity source.
                        "block_time": 1_000_000_000,
                        "slot": 100,
                        "transaction_count": 3,
                    },
                ),
                # Pass swaps explicitly so InMemorySourceReader receives a reviewable
                # block hash and block time input in identity source.
                SWAPS: rows,
            },
            block_ordinal_columns={BLOCKS: "slot", SWAPS: "slot"},
            batch_size=batch_size,
        ),
        # Include descriptor in the completed identity source result.
        descriptor,
    )


def _identity_plan(
    source: InMemorySourceReader,
    artifacts: LocalArtifactRepository,
    # Keep the descriptor input explicit in the identity plan contract.
    descriptor: CapabilityDescriptor,
    *,
    decision_range: BlockRange | None = None,
    max_shard_blocks: int = 10,
    include_block_clock: bool = False,
    # Keep the dataset plan input explicit in the identity plan contract.
) -> DatasetPlan:
    # Execute the identity plan workflow in explicit, reviewable steps.
    decision_range = decision_range or _block_range(100, 101)
    stored_inspection = StoreSourceInspection(
        InspectSource(source, now=lambda: datetime(2025, 12, 31, tzinfo=UTC)),
        artifacts,
    ).execute(InspectSourceRequest(SourceId("identity-fixture-indexer")))
    # Return the completed identity plan result without a hidden fallback.
    return PlanDataset(
        ArtifactSourceInspectionLoader(artifacts),
        _planning_policy(),
    ).execute(
        PlanDatasetRequest(
            # Include source id in the completed identity plan result.
            source_id=SourceId("identity-fixture-indexer"),
            source_inspection_artifact_id=stored_inspection.artifact.artifact_id,
            network_id=SOLANA_MAINNET_NETWORK_ID,
            position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            decision_range=decision_range,
            # Pass warmup blocks explicitly so PlanDatasetRequest receives a reviewable
            # identity-fixture-indexer and identity-fixture-clock input in identity plan.
            warmup_blocks=0,
            settlement_tail_blocks=0,
            max_shard_blocks=max_shard_blocks,
            requested_days=1,
            requirements=(
                # Include data requirement in the completed identity plan result.
                DataRequirement(
                    origin=RequirementOrigin.EXECUTION,
                    origin_id="identity-fixture-clock",
                    capability_id=BLOCKS,
                    columns=_descriptor_columns_from_source(source, BLOCKS),
                    # Pass accepted protocol versions explicitly so DataRequirement
                    # receives a reviewable identity-fixture-clock and 1 input in identity
                    # plan.
                    accepted_protocol_versions=("1",),
                ),
                DataRequirement(
                    origin=RequirementOrigin.EXECUTION,
                    origin_id="identity-fixture",
                    # Pass capability id explicitly so DataRequirement receives a
                    # reviewable identity-fixture and 1 input in identity plan.
                    capability_id=descriptor.capability_id,
                    columns=descriptor.columns,
                    accepted_protocol_versions=("1",),
                ),
            )
            # Pass include block clock explicitly so PlanDatasetRequest receives a
            # reviewable identity-fixture-indexer and identity-fixture-clock input in
            # identity plan.
            if include_block_clock
            else (
                DataRequirement(
                    origin=RequirementOrigin.EXECUTION,
                    origin_id="identity-fixture",
                    # Pass capability id explicitly so DataRequirement receives a
                    # reviewable identity-fixture and 1 input in identity plan.
                    capability_id=descriptor.capability_id,
                    columns=descriptor.columns,
                    accepted_protocol_versions=("1",),
                ),
            ),
            # Include budget limits in the completed identity plan result.
            budget_limits=BudgetLimits(
                max_remote_bytes=1_000_000,
                max_local_bytes=1_000_000,
                max_days=1,
                temporary_reserve_bytes=0,
                # Pass disk low watermark bytes explicitly into BudgetLimits within
                # identity plan.
                disk_low_watermark_bytes=0,
            ),
            query_limits=QueryLimits(
                max_execution_seconds=10,
                max_memory_bytes=128 * 1024**2,
                # Pass max result rows explicitly into QueryLimits within identity plan.
                max_result_rows=1_000,
            ),
        )
    )


def _identity_projector(descriptor: CapabilityDescriptor) -> ReferenceProtocolProjector:
    # Execute the identity projector workflow in explicit, reviewable steps.
    return ReferenceProtocolProjector(
        (
            ProjectionSpec(
                capability_id=BLOCKS,
                kind=ProjectionKind.BLOCK,
                # Pass protocol explicitly so ProjectionSpec receives a reviewable solana
                # and 1 input in identity projector.
                protocol="solana",
                protocol_version="1",
                identity_fidelity=IdentityFidelity.EXACT,
                ordering_fidelity=OrderingFidelity.TRANSACTION_EXACT,
                source_total_key=("slot",),
                # Pass source total key is proven explicitly so ProjectionSpec receives a
                # reviewable solana and 1 input in identity projector.
                source_total_key_is_proven=True,
                columns=(
                    ("block_hash", "block_hash"),
                    ("block_time", "block_time"),
                    ("slot", "slot"),
                    # Open the solana and 1 payload explicitly for ProjectionSpec within
                    # identity projector.
                    ("tx_count", "transaction_count"),
                ),
            ),
            ProjectionSpec(
                capability_id=descriptor.capability_id,
                # Pass kind explicitly so ProjectionSpec receives a reviewable capability
                # id and swap input in identity projector.
                kind=ProjectionKind.SWAP,
                protocol=descriptor.protocol,
                protocol_version=descriptor.protocol_version,
                identity_fidelity=descriptor.fidelity.identity,
                ordering_fidelity=descriptor.fidelity.ordering,
                # Pass source total key explicitly so ProjectionSpec receives a reviewable
                # capability id and swap input in identity projector.
                source_total_key=descriptor.total_key,
                source_total_key_is_proven=descriptor.keyset_key_is_proven,
                columns=tuple((name, name) for name in descriptor.columns),
            ),
        )
        # Complete ReferenceProtocolProjector only after its solana and 1 inputs are visible
        # in identity projector.
    )


def _descriptor_columns_from_source(
    source: InMemorySourceReader,
    capability_id: CapabilityId,
) -> tuple[str, ...]:
    # Execute the descriptor columns from source workflow in explicit, reviewable steps.
    return next(
        item.columns
        for item in source.list_capabilities(SourceId("identity-fixture-indexer"))
        if item.capability_id == capability_id
    )


# Define identity swap row as one focused operation with an explicit boundary.
def _identity_swap_row(*, signature: str, transaction_index: int) -> dict[str, object]:
    # Execute the identity swap row workflow in explicit, reviewable steps.
    return {
        "bought_amount_atomic": 1_000,
        "bought_asset_id": "TOKEN",
        "event_index": 0,
        "fee_amount_atomic": 1,
        # Include pool asset a id in the completed identity swap row result.
        "pool_asset_a_id": "SOL",
        "pool_asset_b_id": "TOKEN",
        "pool_id": "pool",
        "reserve_a_after_atomic": 1_000,
        "reserve_b_after_atomic": 10_000,
        # Include signature in the completed identity swap row result.
        "signature": signature,
        "slot": 100,
        "sold_amount_atomic": 100,
        "sold_asset_id": "SOL",
        "transaction_index": transaction_index,
        # Return the completed identity swap row result without a hidden fallback.
    }


def _source() -> InMemorySourceReader:
    # Execute the source workflow in explicit, reviewable steps.
    descriptors = (
        _descriptor(
            BLOCKS,
            "solana",
            ("block_hash", "block_time", "slot", "transaction_count"),
            # Open the solana and block hash payload explicitly for _descriptor within
            # source.
            ("slot",),
            OrderingFidelity.TRANSACTION_EXACT,
        ),
        _descriptor(
            CREATIONS,
            # Pass reference amm explicitly so _descriptor receives a reviewable reference
            # amm and asset id input in source.
            "reference_amm",
            (
                "asset_id",
                "creator_id",
                "decimals",
                # Pass event index explicitly so _descriptor receives a reviewable
                # reference amm and asset id input in source.
                "event_index",
                "signature",
                "slot",
                "transaction_index",
            ),
            # Open the reference amm and asset id payload explicitly for _descriptor
            # within source.
            ("slot", "transaction_index", "event_index", "signature"),
            OrderingFidelity.INSTRUCTION_EXACT,
        ),
        _descriptor(
            SWAPS,
            # Pass reference amm explicitly so _descriptor receives a reviewable reference
            # amm and bought amount atomic input in source.
            "reference_amm",
            (
                "bought_amount_atomic",
                "bought_asset_id",
                "event_index",
                # Pass fee amount atomic explicitly so _descriptor receives a reviewable
                # reference amm and bought amount atomic input in source.
                "fee_amount_atomic",
                "pool_asset_a_id",
                "pool_asset_b_id",
                "pool_id",
                "reserve_a_after_atomic",
                # Pass reserve b after atomic explicitly so _descriptor receives a
                # reviewable reference amm and bought amount atomic input in source.
                "reserve_b_after_atomic",
                "signature",
                "slot",
                "sold_amount_atomic",
                "sold_asset_id",
                # Pass transaction index explicitly so _descriptor receives a reviewable
                # reference amm and bought amount atomic input in source.
                "transaction_index",
            ),
            ("slot", "transaction_index", "event_index", "signature"),
            OrderingFidelity.INSTRUCTION_EXACT,
        ),
        # Complete the descriptors group only after its semantic components are visible.
    )
    metadata = SourceMetadata(
        source_id=SourceId("fixture-indexer"),
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        # Pass server version explicitly so SourceMetadata receives a reviewable fixture-
        # indexer and fixture-v1 input in source.
        server_version="fixture-v1",
        tables=(),
        capabilities=descriptors,
        capability_mapping_digest=domain_digest("test.capability-mapping.v1", {"fixture": 1}),
        query_template_digest=domain_digest("test.query-template.v1", {"fixture": 1}),
        # Complete SourceMetadata only after its fixture-indexer and fixture-v1 inputs are
        # visible in source.
    )
    return InMemorySourceReader(
        metadata,
        {
            BLOCKS: (
                # Open the block hash and block time payload explicitly for
                # InMemorySourceReader within source.
                {
                    "block_hash": "h101",
                    "block_time": 2_000_000_000,
                    "slot": 101,
                    "transaction_count": 3,
                    # Close the block hash and block time payload only after all source fields
                    # are present.
                },
                {
                    "block_hash": "h100",
                    "block_time": 1_000_000_000,
                    "slot": 100,
                    # Keep transaction count named so the block hash and block time
                    # payload passed to InMemorySourceReader remains self-describing
                    # within source.
                    "transaction_count": 2,
                },
            ),
            CREATIONS: (
                {
                    # Keep asset id named so the block hash and block time payload passed
                    # to InMemorySourceReader remains self-describing within source.
                    "asset_id": "TOKEN",
                    "creator_id": "creator",
                    "decimals": 6,
                    "event_index": 0,
                    "signature": "tx-create",
                    # Keep slot named so the block hash and block time payload passed to
                    # InMemorySourceReader remains self-describing within source.
                    "slot": 100,
                    "transaction_index": 0,
                },
            ),
            # Deliberately reverse the source order; canonical storage sorts it.
            SWAPS: (
                {
                    "bought_amount_atomic": 100,
                    "bought_asset_id": "SOL",
                    "event_index": 0,
                    # Keep fee amount atomic named so the block hash and block time
                    # payload passed to InMemorySourceReader remains self-describing
                    # within source.
                    "fee_amount_atomic": 1,
                    "pool_asset_a_id": "SOL",
                    "pool_asset_b_id": "TOKEN",
                    "pool_id": "pool",
                    "reserve_a_after_atomic": 1_010,
                    # Keep reserve b after atomic named so the block hash and block time
                    # payload passed to InMemorySourceReader remains self-describing
                    # within source.
                    "reserve_b_after_atomic": 9_900,
                    "signature": "tx-sell",
                    "slot": 101,
                    "sold_amount_atomic": 1_000,
                    "sold_asset_id": "TOKEN",
                    # Keep transaction index named so the block hash and block time
                    # payload passed to InMemorySourceReader remains self-describing
                    # within source.
                    "transaction_index": 2,
                },
                {
                    "bought_amount_atomic": 1_000,
                    "bought_asset_id": "TOKEN",
                    # Keep event index named so the block hash and block time payload
                    # passed to InMemorySourceReader remains self-describing within
                    # source.
                    "event_index": 0,
                    "fee_amount_atomic": 1,
                    "pool_asset_a_id": "SOL",
                    "pool_asset_b_id": "TOKEN",
                    "pool_id": "pool",
                    # Keep reserve a after atomic named so the block hash and block time
                    # payload passed to InMemorySourceReader remains self-describing
                    # within source.
                    "reserve_a_after_atomic": 1_000,
                    "reserve_b_after_atomic": 10_000,
                    "signature": "tx-buy",
                    "slot": 100,
                    "sold_amount_atomic": 100,
                    # Keep sold asset id named so the block hash and block time payload
                    # passed to InMemorySourceReader remains self-describing within
                    # source.
                    "sold_asset_id": "SOL",
                    "transaction_index": 1,
                },
            ),
        },
        # Pass block ordinal columns explicitly so InMemorySourceReader receives a
        # reviewable block hash and block time input in source.
        block_ordinal_columns={
            BLOCKS: "slot",
            CREATIONS: "slot",
            SWAPS: "slot",
        },
        # Pass batch size explicitly so InMemorySourceReader receives a reviewable block
        # hash and block time input in source.
        batch_size=1,
    )


def _descriptor(
    capability_id: CapabilityId,
    protocol: str,
    # Keep the columns input explicit in the descriptor contract.
    columns: tuple[str, ...],
    total_key: tuple[str, ...],
    ordering: OrderingFidelity,
) -> CapabilityDescriptor:
    # Execute the descriptor workflow in explicit, reviewable steps.
    return CapabilityDescriptor(
        capability_id=capability_id,
        protocol=protocol,
        protocol_version="1",
        schema_version="1",
        # Pass stream explicitly so CapabilityDescriptor receives a reviewable 1 and block
        # clock input in descriptor.
        stream={
            BLOCKS: CapabilityStream.BLOCK_CLOCK,
            CREATIONS: CapabilityStream.TOKEN_LAUNCH,
            SWAPS: CapabilityStream.PUMP_CURVE_TRADE,
        }[capability_id],
        # Pass columns explicitly so CapabilityDescriptor receives a reviewable 1 and
        # block clock input in descriptor.
        columns=columns,
        mandatory_columns=columns,
        fidelity=SourceFidelity(
            identity=IdentityFidelity.EXACT,
            ordering=ordering,
            # Pass state explicitly so SourceFidelity receives a reviewable exact and
            # before after input in descriptor.
            state=StateFidelity.BEFORE_AFTER,
            fees=FeesFidelity.COMPONENTS,
            chain_finality=ChainFinality.UNKNOWN,
            completeness=IngestionCompleteness.UNKNOWN,
            consistency=SourceConsistency.UNKNOWN,
            # Complete SourceFidelity only after its exact and before after inputs are visible
            # in descriptor.
        ),
        total_key=total_key,
        keyset_key_is_proven=True,
    )


def _plan_request(source_inspection_artifact_id) -> PlanDatasetRequest:
    # Execute the plan request workflow in explicit, reviewable steps.
    requirements = tuple(
        DataRequirement(
            origin=RequirementOrigin.EXECUTION,
            origin_id="fixture-engine",
            capability_id=descriptor.capability_id,
            # Pass columns explicitly so DataRequirement receives a reviewable fixture-
            # engine and 1 input in plan request.
            columns=descriptor.columns,
            accepted_protocol_versions=("1",),
        )
        for descriptor in _source().list_capabilities(SourceId("fixture-indexer"))
    )
    # Return the completed plan request result without a hidden fallback.
    return PlanDatasetRequest(
        source_id=SourceId("fixture-indexer"),
        source_inspection_artifact_id=source_inspection_artifact_id,
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        # Include decision range in the completed plan request result.
        decision_range=_block_range(100, 102),
        warmup_blocks=0,
        settlement_tail_blocks=0,
        max_shard_blocks=10,
        requested_days=1,
        # Pass requirements explicitly so PlanDatasetRequest receives a reviewable
        # fixture-indexer and source id input in plan request.
        requirements=requirements,
        budget_limits=BudgetLimits(
            max_remote_bytes=1_000_000,
            max_local_bytes=1_000_000,
            max_days=1,
            # Pass temporary reserve bytes explicitly into BudgetLimits within plan
            # request.
            temporary_reserve_bytes=0,
            disk_low_watermark_bytes=0,
        ),
        query_limits=QueryLimits(
            max_execution_seconds=10,
            # Pass max memory bytes explicitly into QueryLimits within plan request.
            max_memory_bytes=128 * 1024**2,
            max_result_rows=1_000,
        ),
    )


def _planning_policy() -> DatasetPlanningPolicy:
    # Execute the planning policy workflow in explicit, reviewable steps.
    return DatasetPlanningPolicy(
        budget_limits=BudgetLimits(
            max_remote_bytes=1_000_000,
            max_local_bytes=1_000_000,
            max_days=1,
            # Pass temporary reserve bytes explicitly into BudgetLimits within planning
            # policy.
            temporary_reserve_bytes=0,
            disk_low_watermark_bytes=0,
        ),
        query_limits=QueryLimits(
            max_execution_seconds=10,
            # Pass max memory bytes explicitly into QueryLimits within planning policy.
            max_memory_bytes=128 * 1024**2,
            max_result_rows=1_000,
        ),
        max_total_blocks=10,
        max_total_shards=100,
        # Pass max shard blocks explicitly so DatasetPlanningPolicy receives a reviewable
        # budget limits and query limits input in planning policy.
        max_shard_blocks=10,
    )


def _block_range(from_block: int, to_block: int) -> BlockRange:
    # Execute the block range workflow in explicit, reviewable steps.
    return BlockRange(
        SOLANA_MAINNET_NETWORK_ID,
        BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        from_block,
        to_block,
        # Complete BlockRange only after its solana mainnet network id and block32
        # transaction32 position schema id inputs are visible in block range.
    )


def _projector(
    *,
    build_tools: PinnedCodeBundleSet | None = None,
) -> ReferenceProtocolProjector:
    # Execute the projector workflow in explicit, reviewable steps.
    return ReferenceProtocolProjector(
        (
            ProjectionSpec(
                capability_id=BLOCKS,
                kind=ProjectionKind.BLOCK,
                # Pass protocol explicitly so ProjectionSpec receives a reviewable solana
                # and 1 input in projector.
                protocol="solana",
                protocol_version="1",
                identity_fidelity=IdentityFidelity.EXACT,
                ordering_fidelity=OrderingFidelity.TRANSACTION_EXACT,
                source_total_key=("slot",),
                # Pass source total key is proven explicitly so ProjectionSpec receives a
                # reviewable solana and 1 input in projector.
                source_total_key_is_proven=True,
                columns=(
                    ("block_hash", "block_hash"),
                    ("block_time", "block_time"),
                    ("slot", "slot"),
                    # Open the solana and 1 payload explicitly for ProjectionSpec within
                    # projector.
                    ("tx_count", "transaction_count"),
                ),
            ),
            ProjectionSpec(
                capability_id=CREATIONS,
                # Pass kind explicitly so ProjectionSpec receives a reviewable reference
                # amm and 1 input in projector.
                kind=ProjectionKind.TOKEN_CREATION,
                protocol="reference_amm",
                protocol_version="1",
                identity_fidelity=IdentityFidelity.EXACT,
                ordering_fidelity=OrderingFidelity.INSTRUCTION_EXACT,
                # Pass source total key explicitly so ProjectionSpec receives a reviewable
                # reference amm and 1 input in projector.
                source_total_key=("slot", "transaction_index", "event_index", "signature"),
                source_total_key_is_proven=True,
                columns=tuple((name, name) for name in _descriptor_columns(CREATIONS)),
            ),
            ProjectionSpec(
                # Pass capability id explicitly so ProjectionSpec receives a reviewable
                # reference amm and 1 input in projector.
                capability_id=SWAPS,
                kind=ProjectionKind.SWAP,
                protocol="reference_amm",
                protocol_version="1",
                identity_fidelity=IdentityFidelity.EXACT,
                # Pass ordering fidelity explicitly so ProjectionSpec receives a
                # reviewable reference amm and 1 input in projector.
                ordering_fidelity=OrderingFidelity.INSTRUCTION_EXACT,
                source_total_key=("slot", "transaction_index", "event_index", "signature"),
                source_total_key_is_proven=True,
                columns=tuple((name, name) for name in _descriptor_columns(SWAPS)),
            ),
            # Complete ReferenceProtocolProjector only after its solana and 1 inputs are
            # visible in projector.
        ),
        build_tools=build_tools,
    )


def _descriptor_columns(capability_id: CapabilityId) -> tuple[str, ...]:
    # Execute the descriptor columns workflow in explicit, reviewable steps.
    return next(
        item.columns
        for item in _source().list_capabilities(SourceId("fixture-indexer"))
        if item.capability_id == capability_id
    )


# Define run reference backtest as one focused operation with an explicit boundary.
def _run_reference_backtest(replay: HistoricalEventSource) -> RunSummary:
    # Execute the run reference backtest workflow in explicit, reviewable steps.
    bundles = ReferenceBundleRegistry().snapshot()
    return ReferenceBacktestEngine().run(
        source=replay,
        strategy=FirstSwapStrategy(
            pool_id=PoolId("pool"),
            # Include sold asset id in the completed run reference backtest result.
            sold_asset_id=AssetId("SOL"),
            bought_asset_id=AssetId("TOKEN"),
            amount_in_atomic=100,
            bundle_id=bundles.manifest_for("strategy").bundle_id,
        ),
        # Include execution model in the completed run reference backtest result.
        execution_model=ConstantProductExecutionModel(
            fee_bps=30,
            bundle_id=bundles.manifest_for("execution").bundle_id,
        ),
        risk_policy=StaticRiskPolicy(
            # Pass maximum order input atomic explicitly so StaticRiskPolicy receives a
            # reviewable risk and bundle id input in run reference backtest.
            maximum_order_input_atomic=1_000,
            bundle_id=bundles.manifest_for("risk").bundle_id,
        ),
        config=ReferenceRunConfig(
            execution_mode=ExecutionMode.SHADOW_STATE_REPLAY,
            # Include latency in the completed run reference backtest result.
            latency=SlotLatencyModel(
                bundle_identity=bundles.manifest_for("latency").bundle_id,
            ),
            root_seed=42,
            initial_available={AssetId("SOL"): 1_000},
            # Include engine bundle id in the completed run reference backtest result.
            engine_bundle_id=bundles.manifest_for("engine").bundle_id,
        ),
    )


def _resolved_run_spec(
    snapshot,
    # Keep the replay input explicit in the resolved run spec contract.
    replay: HistoricalEventSource,
    runtime_lock_id: RuntimeLockId,
    *,
    replay_input: ResolvedReplayInput | None = None,
    delivery_schedule_id: DeliveryScheduleId | None = None,
    # Keep the observation slots input explicit in the resolved run spec contract.
    observation_slots: int = 0,
    root_seed: int = 42,
) -> ResolvedRunSpec:
    # Execute the resolved run spec workflow in explicit, reviewable steps.
    bundles = ReferenceBundleRegistry().snapshot()

    def bundle_id(role: str) -> BundleId:
        return bundles.manifest_for(role).bundle_id

    components = (
        ResolvedComponent.create(
            # Pass role explicitly so create receives a reviewable clock and duration
            # mapping input in resolved run spec.
            role="clock",
            bundle_id=bundle_id("clock"),
            config={"duration_mapping": "ceil-to-next-boundary-v1"},
        ),
        ResolvedComponent.create(
            # Pass role explicitly so create receives a reviewable engine and maximum
            # dynamic items input in resolved run spec.
            role="engine",
            bundle_id=bundle_id("engine"),
            config={"maximum_dynamic_items": 10_000},
        ),
        ResolvedComponent.create(
            # Pass role explicitly so create receives a reviewable execution and fee bps
            # input in resolved run spec.
            role="execution",
            bundle_id=bundle_id("execution"),
            config={"fee_bps": 30, "mode": ExecutionMode.SHADOW_STATE_REPLAY.value},
        ),
        ResolvedComponent.create(
            # Pass role explicitly so create receives a reviewable inference and document
            # input in resolved run spec.
            role="inference",
            bundle_id=bundle_id("inference"),
            config=ExactInferencePolicy.disabled().document(),
        ),
        ResolvedComponent.create(
            # Pass role explicitly so create receives a reviewable latency and observation
            # slots input in resolved run spec.
            role="latency",
            bundle_id=bundle_id("latency"),
            config={"observation_slots": observation_slots, "order_slots": 0},
        ),
        ResolvedComponent.create(
            # Pass role explicitly so create receives a reviewable protocol:reference amm
            # and version input in resolved run spec.
            role="protocol:reference_amm",
            bundle_id=bundle_id("protocol:reference_amm"),
            config={"version": 1},
        ),
        ResolvedComponent.create(
            # Pass role explicitly so create receives a reviewable risk and maximum order
            # input atomic input in resolved run spec.
            role="risk",
            bundle_id=bundle_id("risk"),
            config={"maximum_order_input_atomic": 1_000},
        ),
        ResolvedComponent.create(
            # Pass role explicitly so create receives a reviewable scheduler and phase
            # table input in resolved run spec.
            role="scheduler",
            bundle_id=bundle_id("scheduler"),
            config={"phase_table": "canonical-v1"},
        ),
        ResolvedComponent.create(
            # Pass role explicitly so create receives a reviewable strategy and amount in
            # atomic input in resolved run spec.
            role="strategy",
            bundle_id=bundle_id("strategy"),
            config={
                "amount_in_atomic": 100,
                "bought_asset_id": "TOKEN",
                # Keep minimum amount out atomic named so the strategy and amount in
                # atomic payload passed to create remains self-describing within resolved
                # run spec.
                "minimum_amount_out_atomic": 0,
                "pool_id": "pool",
                "sold_asset_id": "SOL",
            },
        ),
        # Register create and resolved component through create so the components table
        # remains scannable.
        ResolvedComponent.create(
            role="universe",
            bundle_id=bundle_id("universe"),
            config={"policy": "point-in-time-observed-assets-v1"},
        ),
        # Register create and resolved component through create so the components table
        # remains scannable.
        ResolvedComponent.create(
            role="valuation:price_source",
            bundle_id=bundle_id("valuation:price_source"),
            config={"policy": "none-v1"},
        ),
        # Complete the components group only after its semantic components are visible.
    )
    return ResolvedRunSpec.create(
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        dataset_revision_id=snapshot.dataset_revision_id,
        # Pass logical content hash explicitly so create receives a reviewable sol and
        # dataset revision id input in resolved run spec.
        logical_content_hash=snapshot.logical_content_hash,
        snapshot_id=snapshot.snapshot_id,
        replay_semantics_id=replay.replay_semantics_id,
        replay_input=replay_input or ResolvedReplayInput(ReplayInputFormat.CANONICAL_PARQUET),
        components=components,
        # Pass runtime lock id explicitly so create receives a reviewable sol and dataset
        # revision id input in resolved run spec.
        runtime_lock_id=runtime_lock_id,
        initial_portfolio=(AssetBalance(AssetId("SOL"), 1_000),),
        root_seed=root_seed,
        delivery_schedule_id=delivery_schedule_id,
    )


# Define bundle as one focused operation with an explicit boundary.
def _bundle(name: str) -> BundleId:
    return BundleId(domain_digest("test.bundle.v1", {"name": name}).hex)
