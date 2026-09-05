"""Exact artifact-bound benchmark target resolution and workload dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository

# Import parquet replay at the visible module dependency boundary.
from backtest.adapters.columnar.arrow.parquet_replay import CanonicalParquetReplaySource
from backtest.adapters.columnar.numpy.compiler import unit_replay_build_tools
from backtest.adapters.columnar.numpy.reader import NumpyMmapReplaySource
from backtest.adapters.performance.replay import (
    OPTIMIZED_REDUCER_BENCHMARK_BUNDLE_ID,
    # Include reference reducer benchmark bundle id so the replay dependency remains
    # explicit.
    REFERENCE_REDUCER_BENCHMARK_BUNDLE_ID,
    REPLAY_SCAN_BENCHMARK_BUNDLE_ID,
    BenchmarkTargetFactory,
    LocalReplayBenchmarkTargetFactory,
)

# Import job completion at the visible module dependency boundary.
from backtest.adapters.results.job_completion import LocalJobResultReader
from backtest.application.benchmarks import (
    BenchmarkExecutionPhase,
    BenchmarkLaunchRoute,
    BenchmarkSpec,
    # Include benchmark workload so the benchmarks dependency remains explicit.
    BenchmarkWorkload,
    BenchmarkWorkloadResult,
    ControlPlaneBenchmarkInvocation,
    ExactBenchmarkCommand,
)

# Import code bundles at the visible module dependency boundary.
from backtest.application.code_bundles import PinnedCodeBundleSet
from backtest.application.job_commands import run_input_artifact_ids
from backtest.application.ml_contracts import InferenceMode
from backtest.application.ports.benchmarks import BenchmarkTarget
from backtest.application.run_results import (
    # Include first swap summary metadata so the run results dependency remains explicit.
    FirstSwapSummaryMetadata,
    PumpfunSnipingSummaryMetadata,
    RunComparisonProjection,
    RunPhysicalSettings,
    SuccessfulRunManifest,
    # Include successful run summary so the run results dependency remains explicit.
    SuccessfulRunSummary,
)
from backtest.application.run_specs import ResolvedRunSpec
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import (
    # Include artifact id so the identifiers dependency remains explicit.
    ArtifactId,
    BundleId,
    ContentDigest,
    ReplayPackId,
    RuntimeLockId,
    # Include snapshot id so the identifiers dependency remains explicit.
    SnapshotId,
)
from backtest.engine.reference import RunSummary
from backtest.engine.sniping import SnipingRunSummary

PARQUET_SCAN_BENCHMARK_BUNDLE_ID = BundleId(
    # Keep the v1 domain_digest step visible while building parquet scan benchmark bundle
    # id.
    domain_digest(
        "backtest.parquet-scan-benchmark-bundle.v1",
        {"algorithm": "verified-canonical-event-stream-logical-hash-v1"},
    ).hex
)
# Bind full backtest benchmark bundle id once as an explicit module-level contract.
FULL_BACKTEST_BENCHMARK_BUNDLE_ID = BundleId(
    domain_digest(
        "backtest.full-backtest-benchmark-bundle.v1",
        {"algorithm": "resolved-run-output-free-summary-v1"},
    ).hex
    # Complete BundleId only after its v1 and algorithm inputs are visible in module.
)
EMBEDDED_INFERENCE_BENCHMARK_BUNDLE_ID = BundleId(
    domain_digest(
        "backtest.embedded-inference-benchmark-bundle.v1",
        {"algorithm": "resolved-run-embedded-batch-output-free-summary-v1"},
        # Complete domain_digest only after its v1 and algorithm inputs are visible in module.
    ).hex
)
FROZEN_INFERENCE_BENCHMARK_BUNDLE_ID = BundleId(
    domain_digest(
        "backtest.frozen-inference-benchmark-bundle.v1",
        # Open the v1 and algorithm payload explicitly for domain_digest within module.
        {"algorithm": "resolved-run-frozen-predictions-output-free-summary-v1"},
    ).hex
)
CONTROL_DIRECT_BENCHMARK_BUNDLE_ID = BundleId(
    domain_digest(
        # Pass version tag explicitly so domain_digest receives a reviewable v1 and route
        # input in module.
        "backtest.control-plane-direct-benchmark-bundle.v1",
        {"route": "resolved-direct-supervisor-completion-v1"},
    ).hex
)
CONTROL_QUEUED_BENCHMARK_BUNDLE_ID = BundleId(
    # Keep the v1 domain_digest step visible while building control queued benchmark
    # bundle id.
    domain_digest(
        "backtest.control-plane-queued-benchmark-bundle.v1",
        {"route": "durable-queue-supervisor-completion-v1"},
    ).hex
)
# Bind default benchmark attempt nonce once as an explicit module-level contract.
_DEFAULT_BENCHMARK_ATTEMPT_NONCE = ContentDigest("0" * 64)


class ResolvedRunSummaryExecutor(Protocol):
    """Child-safe execution of the exact resolved run without publication."""

    def execute_summary(
        self,
        spec: ResolvedRunSpec,
        physical_settings: RunPhysicalSettings,
    ) -> RunSummary | SnipingRunSummary | SuccessfulRunSummary: ...


# Keep the control plane benchmark executor contract and validation rules together.
class ControlPlaneBenchmarkExecutor(Protocol):
    """Real direct/control route adapter; never an in-memory semantic surrogate."""

    def execute(
        self,
        run_artifact_id: ArtifactId,
        route: BenchmarkLaunchRoute,
        physical_settings: RunPhysicalSettings,
        # Keep the invocation input explicit in the execute contract.
        invocation: ControlPlaneBenchmarkInvocation,
    ) -> RunComparisonProjection: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class LocalExactBenchmarkSpecResolver:
    """Resolve public v1 benchmark commands to exact, executable specs."""

    data_root: Path
    runtime_lock_id: RuntimeLockId
    duckdb_memory_limit_mb: int
    build_tools: PinnedCodeBundleSet | None = None

    def resolve(self, command: ExactBenchmarkCommand) -> BenchmarkSpec:
        # Execute the local exact benchmark spec resolver resolve workflow in explicit,
        # reviewable steps.
        artifacts = LocalArtifactRepository(self.data_root.resolve())
        workload = command.workload
        bundle_id = _workload_bundle_id(workload, command.launch_route)
        semantic_id: ContentDigest
        target_id = command.target_artifact_id
        # Evaluate the complete local exact benchmark spec resolver resolve workload,
        # parquet scan and benchmark workload condition before guarded effects.
        if workload is BenchmarkWorkload.PARQUET_SCAN:
            # Handle the local exact benchmark spec resolver resolve workload, parquet
            # scan and benchmark workload condition as a distinct block.
            source = CanonicalParquetReplaySource(
                artifacts,
                SnapshotId(target_id.hex),
                duckdb_memory_limit_mb=self.duckdb_memory_limit_mb,
                threads=command.native_threads_per_process,
                # Pass build tools explicitly so CanonicalParquetReplaySource receives a
                # reviewable hex and duckdb memory limit mb input in local exact benchmark
                # spec resolver resolve.
                build_tools=self.build_tools,
            )
            semantic_id = _stream_equivalence_id(
                source.dataset_revision_id.hex,
                source.logical_content_hash.hex,
                # Pass source explicitly so _stream_equivalence_id receives a reviewable
                # hex and dataset revision id input in local exact benchmark spec resolver
                # resolve.
                source.replay_semantics_id.hex,
            )
        # Handle the local exact benchmark spec resolver resolve complement of workload,
        # parquet scan and benchmark workload explicitly.
        elif workload in {
            BenchmarkWorkload.REPLAY_PACK_SCAN,
            BenchmarkWorkload.REFERENCE_REDUCER,
            BenchmarkWorkload.OPTIMIZED_REDUCER,
        }:
            # Handle the local exact benchmark spec resolver resolve workload, replay pack
            # scan and reference reducer condition as a distinct block.
            replay = NumpyMmapReplaySource(
                artifacts,
                ReplayPackId(target_id.hex),
                build_tools=self.build_tools or unit_replay_build_tools(),
            )
            # Assemble semantic id once so the local exact benchmark spec resolver resolve
            # workflow shares one value.
            semantic_id = _stream_equivalence_id(
                replay.dataset_revision_id.hex,
                replay.logical_content_hash.hex,
                replay.replay_semantics_id.hex,
            )
        # Route all remaining cases through the explicit alternative branch.
        else:
            # Handle the local exact benchmark spec resolver resolve complement of
            # workload, replay pack scan and reference reducer explicitly.
            manifest = LocalJobResultReader(artifacts).successful_run_manifest(target_id)
            _validate_run_workload(workload, manifest)
            if manifest.resolved_spec.runtime_lock_id != self.runtime_lock_id:
                raise ValueError("benchmark Run artifact belongs to another runtime lock")
            semantic_id = _run_equivalence_id(manifest)
        # Return the completed local exact benchmark spec resolver resolve result without
        # a hidden fallback.
        return BenchmarkSpec(
            workload=workload,
            input_artifact_ids=(target_id,),
            workload_bundle_id=bundle_id,
            runtime_lock_id=self.runtime_lock_id,
            # Pass cache condition explicitly so BenchmarkSpec receives a reviewable
            # runtime lock id and cache condition input in local exact benchmark spec
            # resolver resolve.
            cache_condition=command.cache_condition,
            batch_rows=command.batch_rows,
            readahead=command.readahead,
            process_count=command.process_count,
            native_threads_per_process=command.native_threads_per_process,
            # Pass warmup iterations explicitly so BenchmarkSpec receives a reviewable
            # runtime lock id and cache condition input in local exact benchmark spec
            # resolver resolve.
            warmup_iterations=command.warmup_iterations,
            measured_iterations=command.measured_iterations,
            capacity_days=command.capacity_days,
            launch_route=command.launch_route,
            semantic_equivalence_id=semantic_id,
            # Complete BenchmarkSpec only after its runtime lock id and cache condition inputs
            # are visible in local exact benchmark spec resolver resolve.
        )


class LocalExactBenchmarkTargetFactory(BenchmarkTargetFactory):
    """Spawn-safe dispatch for every executable Phase 7 benchmark workload."""

    def __init__(
        self,
        resolver: LocalExactBenchmarkSpecResolver,
        *,
        run_executor: ResolvedRunSummaryExecutor | None = None,
        # Keep the control executor input explicit in the init contract.
        control_executor: ControlPlaneBenchmarkExecutor | None = None,
        control_executor_available: bool = False,
    ) -> None:
        # Execute the local exact benchmark target factory init workflow in explicit,
        # reviewable steps.
        self._resolver = resolver
        self._run_executor = run_executor
        self._control_executor = control_executor
        self._control_executor_available = (
            control_executor_available or control_executor is not None
            # Complete the self control executor available group only after its semantic
            # components are visible.
        )
        self._replay = LocalReplayBenchmarkTargetFactory(resolver.build_tools)

    def validate(self, spec: BenchmarkSpec, data_root: Path) -> None:
        # Execute the local exact benchmark target factory validate workflow in explicit,
        # reviewable steps.
        if data_root.resolve() != self._resolver.data_root.resolve():
            raise ValueError("benchmark target factory is bound to another data root")
        resolved = self._resolver.resolve(_command_from_spec(spec))
        if resolved != spec:
            raise ValueError("benchmark spec differs from independently resolved target closure")
        # Evaluate the complete local exact benchmark target factory validate workload,
        # spec and replay pack scan condition before guarded effects.
        if spec.workload in {
            BenchmarkWorkload.REPLAY_PACK_SCAN,
            BenchmarkWorkload.REFERENCE_REDUCER,
            BenchmarkWorkload.OPTIMIZED_REDUCER,
        }:
            # Invoke validate for spec and data root as a visible local exact benchmark
            # target factory validate step.
            self._replay.validate(spec, data_root)
        # Handle the local exact benchmark target factory validate complement of workload,
        # spec and replay pack scan explicitly.
        elif (
            spec.workload
            in {
                BenchmarkWorkload.FULL_BACKTEST,
                BenchmarkWorkload.EMBEDDED_INFERENCE,
                # Keep benchmark workload visible while evaluating the workload, run
                # executor and spec guard.
                BenchmarkWorkload.FROZEN_INFERENCE,
            }
            and self._run_executor is None
        ):
            raise ValueError("resolved-run benchmark executor is not installed")
        # Handle the local exact benchmark target factory validate complement of workload,
        # run executor and spec explicitly.
        elif (
            spec.workload is BenchmarkWorkload.CONTROL_PLANE_ROUND_TRIP
            and not self._control_executor_available
        ):
            raise ValueError("real control-plane benchmark executor is not installed")

    # Define local exact benchmark target factory create as one focused operation with an
    # explicit boundary.
    def create(
        self,
        spec: BenchmarkSpec,
        data_root: Path,
        attempt_nonce: ContentDigest = _DEFAULT_BENCHMARK_ATTEMPT_NONCE,
        # Keep the phase input explicit in the create contract.
        phase: BenchmarkExecutionPhase = BenchmarkExecutionPhase.MEASURED,
    ) -> BenchmarkTarget:
        # Execute the local exact benchmark target factory create workflow in explicit,
        # reviewable steps.
        self.validate(spec, data_root)
        if spec.workload in {
            BenchmarkWorkload.REPLAY_PACK_SCAN,
            BenchmarkWorkload.REFERENCE_REDUCER,
            BenchmarkWorkload.OPTIMIZED_REDUCER,
            # Evaluate the complete local exact benchmark target factory create workload, spec
            # and replay pack scan condition before guarded effects.
        }:
            return self._replay.create(spec, data_root, attempt_nonce, phase)
        if spec.workload is BenchmarkWorkload.PARQUET_SCAN:
            return _ParquetScanTarget(spec, data_root, self._resolver)
        manifest = LocalJobResultReader(LocalArtifactRepository(data_root)).successful_run_manifest(
            # Pass spec explicitly so successful_run_manifest receives a reviewable input
            # artifact ids and spec input in local exact benchmark target factory create.
            spec.input_artifact_ids[0]
        )
        physical = RunPhysicalSettings(
            backend=manifest.physical_settings.backend,
            reader_batch_rows=spec.batch_rows,
            # Pass reader readahead explicitly so RunPhysicalSettings receives a
            # reviewable backend and physical settings input in local exact benchmark
            # target factory create.
            reader_readahead=spec.readahead,
            output_buffer_rows=manifest.physical_settings.output_buffer_rows,
            threads=spec.native_threads_per_process,
        )
        if spec.workload is BenchmarkWorkload.CONTROL_PLANE_ROUND_TRIP:
            # Handle the local exact benchmark target factory create workload, control
            # plane round trip and spec condition as a distinct block.
            control_executor = self._control_executor
            if control_executor is None:  # guarded by validate
                raise AssertionError("control executor disappeared")
            return _ControlPlaneTarget(
                spec,
                manifest,
                physical,
                # Pass control executor explicitly so _ControlPlaneTarget receives a
                # reviewable spec and manifest input in local exact benchmark target
                # factory create.
                control_executor,
                attempt_nonce,
                phase,
            )
        run_executor = self._run_executor
        if run_executor is None:  # guarded by validate
            raise AssertionError("run executor disappeared")
        return _ResolvedRunTarget(manifest, physical, run_executor)


# Keep the parquet scan target contract and validation rules together.
class _ParquetScanTarget:
    def __init__(
        self,
        spec: BenchmarkSpec,
        data_root: Path,
        # Keep the resolver input explicit in the init contract.
        resolver: LocalExactBenchmarkSpecResolver,
    ) -> None:
        # Execute the parquet scan target init workflow in explicit, reviewable steps.
        self._source = CanonicalParquetReplaySource(
            LocalArtifactRepository(data_root),
            SnapshotId(spec.input_artifact_ids[0].hex),
            duckdb_memory_limit_mb=resolver.duckdb_memory_limit_mb,
            threads=spec.native_threads_per_process,
            # Pass reader batch rows explicitly so CanonicalParquetReplaySource receives a
            # reviewable hex and input artifact ids input in parquet scan target init.
            reader_batch_rows=spec.batch_rows,
            reader_readahead=spec.readahead,
            build_tools=resolver.build_tools,
        )

    def execute_once(self) -> BenchmarkWorkloadResult:
        # Execute the parquet scan target execute once workflow in explicit, reviewable
        # steps.
        count = sum(1 for _ in self._source.events())
        if count <= 0:
            raise ValueError("benchmark snapshot must contain events")
        return BenchmarkWorkloadResult(
            count,
            # Include content digest in the completed parquet scan target execute once
            # result.
            ContentDigest(self._source.logical_content_hash.hex),
        )


# Keep the resolved run target contract and validation rules together.
@dataclass(slots=True)
class _ResolvedRunTarget:
    manifest: SuccessfulRunManifest
    physical_settings: RunPhysicalSettings
    executor: ResolvedRunSummaryExecutor

    # Define resolved run target execute once as one focused operation with an explicit
    # boundary.
    def execute_once(self) -> BenchmarkWorkloadResult:
        # Execute the resolved run target execute once workflow in explicit, reviewable
        # steps.
        summary = self.executor.execute_summary(
            self.manifest.resolved_spec,
            self.physical_settings,
        )
        _require_exact_summary(summary, self.manifest.bounded_summary)
        # Assemble comparison once so the resolved run target execute once workflow shares
        # one value.
        comparison = RunComparisonProjection.from_summary(summary)
        return BenchmarkWorkloadResult(
            comparison.historical_event_count,
            comparison.canonical_result_hash,
        )


# Keep the control plane target contract and validation rules together.
@dataclass(slots=True)
class _ControlPlaneTarget:
    spec: BenchmarkSpec
    manifest: SuccessfulRunManifest
    physical_settings: RunPhysicalSettings
    # Declare executor explicitly in the control plane target contract.
    executor: ControlPlaneBenchmarkExecutor
    outer_attempt_nonce: ContentDigest
    phase: BenchmarkExecutionPhase
    invocation_ordinal: int = 0

    def execute_once(self) -> BenchmarkWorkloadResult:
        # Execute the control plane target execute once workflow in explicit, reviewable
        # steps.
        invocation = ControlPlaneBenchmarkInvocation(
            self.outer_attempt_nonce,
            self.phase,
            self.invocation_ordinal,
        )
        # Assemble self invocation ordinal once so the control plane target execute once
        # workflow shares one value.
        self.invocation_ordinal += 1
        comparison = self.executor.execute(
            self.spec.input_artifact_ids[0],
            self.spec.launch_route,
            self.physical_settings,
            # Pass invocation explicitly so execute receives a reviewable input artifact
            # ids and spec input in control plane target execute once.
            invocation,
        )
        if comparison != self.manifest.comparison:
            raise ValueError("control benchmark result differs from its exact Run seed")
        return BenchmarkWorkloadResult(
            # Pass comparison explicitly so BenchmarkWorkloadResult receives a reviewable
            # historical event count and canonical result hash input in control plane
            # target execute once.
            comparison.historical_event_count,
            comparison.canonical_result_hash,
        )

    def close(self) -> None:
        self.executor.close()


# Define command from spec as one focused operation with an explicit boundary.
def _command_from_spec(spec: BenchmarkSpec) -> ExactBenchmarkCommand:
    # Execute the command from spec workflow in explicit, reviewable steps.
    return ExactBenchmarkCommand(
        target_artifact_id=spec.input_artifact_ids[0],
        workload=spec.workload,
        launch_route=spec.launch_route,
        cache_condition=spec.cache_condition,
        # Pass batch rows explicitly so ExactBenchmarkCommand receives a reviewable 0 and
        # input artifact ids input in command from spec.
        batch_rows=spec.batch_rows,
        readahead=spec.readahead,
        process_count=spec.process_count,
        native_threads_per_process=spec.native_threads_per_process,
        warmup_iterations=spec.warmup_iterations,
        # Pass measured iterations explicitly so ExactBenchmarkCommand receives a
        # reviewable 0 and input artifact ids input in command from spec.
        measured_iterations=spec.measured_iterations,
        capacity_days=spec.capacity_days,
        attempt_nonce=ContentDigest("0" * 64),
    )


def _workload_bundle_id(
    # Keep the workload input explicit in the workload bundle id contract.
    workload: BenchmarkWorkload,
    launch_route: BenchmarkLaunchRoute,
) -> BundleId:
    # Execute the workload bundle id workflow in explicit, reviewable steps.
    if workload is BenchmarkWorkload.CONTROL_PLANE_ROUND_TRIP:
        # Handle the workload bundle id workload, control plane round trip and benchmark
        # workload condition as a distinct block.
        return (
            CONTROL_DIRECT_BENCHMARK_BUNDLE_ID
            if launch_route is BenchmarkLaunchRoute.DIRECT
            else CONTROL_QUEUED_BENCHMARK_BUNDLE_ID
        )
    # Keep expected failures inside the workload bundle id error boundary.
    try:
        # Perform the protected workload bundle id operation before explicit failure
        # handling.
        return {
            BenchmarkWorkload.PARQUET_SCAN: PARQUET_SCAN_BENCHMARK_BUNDLE_ID,
            BenchmarkWorkload.REPLAY_PACK_SCAN: REPLAY_SCAN_BENCHMARK_BUNDLE_ID,
            BenchmarkWorkload.REFERENCE_REDUCER: REFERENCE_REDUCER_BENCHMARK_BUNDLE_ID,
            BenchmarkWorkload.OPTIMIZED_REDUCER: OPTIMIZED_REDUCER_BENCHMARK_BUNDLE_ID,
            # Include benchmark workload in the completed workload bundle id result.
            BenchmarkWorkload.FULL_BACKTEST: FULL_BACKTEST_BENCHMARK_BUNDLE_ID,
            BenchmarkWorkload.EMBEDDED_INFERENCE: EMBEDDED_INFERENCE_BENCHMARK_BUNDLE_ID,
            BenchmarkWorkload.FROZEN_INFERENCE: FROZEN_INFERENCE_BENCHMARK_BUNDLE_ID,
        }[workload]
    except KeyError as error:  # pragma: no cover - enum is exhaustively dispatched
        raise ValueError("unsupported benchmark workload") from error


def _validate_run_workload(
    workload: BenchmarkWorkload,
    manifest: SuccessfulRunManifest,
) -> None:
    # Execute the validate run workload workflow in explicit, reviewable steps.
    if manifest.input_artifact_ids != run_input_artifact_ids(manifest.resolved_spec):
        raise ValueError("benchmark Run artifact does not retain its exact input closure")
    mode = manifest.resolved_spec.inference_policy().mode
    if mode is not InferenceMode.DISABLED and (
        manifest.resolved_spec.replay_input.replay_pack_id is None
        # Keep manifest visible while evaluating the mode, disabled and inference mode
        # guard.
        or manifest.resolved_spec.replay_input.replay_layout_schema_id is None
    ):
        raise ValueError("ML benchmark Run artifact has no exact ReplayPack contract")
    if (
        workload is BenchmarkWorkload.EMBEDDED_INFERENCE
        # Keep mode visible while evaluating the workload, embedded inference and mode
        # guard.
        and mode is not InferenceMode.EMBEDDED_BATCH
    ):
        raise ValueError("embedded inference benchmark requires an embedded Run artifact")
    if workload is BenchmarkWorkload.FROZEN_INFERENCE and mode is not InferenceMode.FROZEN:
        raise ValueError("frozen inference benchmark requires a frozen Run artifact")
    # Evaluate the complete validate run workload workload, full backtest and embedded
    # inference condition before guarded effects.
    if workload not in {
        BenchmarkWorkload.FULL_BACKTEST,
        BenchmarkWorkload.EMBEDDED_INFERENCE,
        BenchmarkWorkload.FROZEN_INFERENCE,
        BenchmarkWorkload.CONTROL_PLANE_ROUND_TRIP,
        # Evaluate the complete validate run workload workload, full backtest and embedded
        # inference condition before guarded effects.
    }:
        raise ValueError("benchmark workload does not accept a Run artifact")


def _stream_equivalence_id(
    dataset_revision_id: str,
    logical_content_hash: str,
    # Keep the replay semantics id input explicit in the stream equivalence id contract.
    replay_semantics_id: str,
) -> ContentDigest:
    # Execute the stream equivalence id workflow in explicit, reviewable steps.
    return domain_digest(
        "backtest.benchmark-stream-equivalence.v1",
        {
            "dataset_revision_id": dataset_revision_id,
            "logical_content_hash": logical_content_hash,
            # Keep replay semantics id named so the v1 and dataset revision id payload
            # passed to domain_digest remains self-describing within stream equivalence
            # id.
            "replay_semantics_id": replay_semantics_id,
        },
    )


def _run_equivalence_id(manifest: SuccessfulRunManifest) -> ContentDigest:
    # Execute the run equivalence id workflow in explicit, reviewable steps.
    summary = manifest.bounded_summary
    return domain_digest(
        "backtest.benchmark-run-equivalence.v1",
        {
            "dataset_logical_content_hash": summary.dataset_logical_content_hash.hex,
            # Keep replay semantics id named so the v1 and dataset logical content hash
            # payload passed to domain_digest remains self-describing within run
            # equivalence id.
            "replay_semantics_id": summary.replay_semantics_id.hex,
            "result_hash": summary.result_hash.hex,
        },
    )


def _require_exact_summary(
    # Keep the actual input explicit in the require exact summary contract.
    actual: RunSummary | SnipingRunSummary | SuccessfulRunSummary,
    expected: SuccessfulRunSummary,
) -> None:
    # Execute the require exact summary workflow in explicit, reviewable steps.
    common_mismatch = (
        actual.dataset_logical_content_hash.hex != expected.dataset_logical_content_hash.hex
        or actual.replay_semantics_id != expected.replay_semantics_id
        or actual.engine_bundle_id.hex != expected.engine_bundle_id.hex
        or RunComparisonProjection.from_summary(actual) != expected.comparison
        # Complete the common mismatch group only after its semantic components are visible.
    )
    type_mismatch = (
        isinstance(expected, FirstSwapSummaryMetadata)
        and (
            not isinstance(actual, (RunSummary, FirstSwapSummaryMetadata))
            # Keep the actual component named inside the type mismatch contract.
            or actual.latency_bundle_id.hex != expected.latency_bundle_id.hex
        )
    ) or (
        isinstance(expected, PumpfunSnipingSummaryMetadata)
        and not isinstance(actual, (SnipingRunSummary, PumpfunSnipingSummaryMetadata))
        # Complete the type mismatch group only after its semantic components are visible.
    )
    if common_mismatch or type_mismatch:
        raise RuntimeError("benchmark execution differs from the exact committed Run seed")


__all__ = [
    "CONTROL_DIRECT_BENCHMARK_BUNDLE_ID",
    # Keep the control queued benchmark bundle id component named inside the all contract.
    "CONTROL_QUEUED_BENCHMARK_BUNDLE_ID",
    "EMBEDDED_INFERENCE_BENCHMARK_BUNDLE_ID",
    "FROZEN_INFERENCE_BENCHMARK_BUNDLE_ID",
    "FULL_BACKTEST_BENCHMARK_BUNDLE_ID",
    "PARQUET_SCAN_BENCHMARK_BUNDLE_ID",
    # Keep the control plane benchmark executor component named inside the all contract.
    "ControlPlaneBenchmarkExecutor",
    "LocalExactBenchmarkSpecResolver",
    "LocalExactBenchmarkTargetFactory",
    "ResolvedRunSummaryExecutor",
]
