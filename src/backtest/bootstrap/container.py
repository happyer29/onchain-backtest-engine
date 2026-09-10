"""Small composition root shared by CLI and the local Control API."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backtest.adapters.artifacts.localfs import (
    LocalArtifactRepository,
    # Include local disk capacity probe so the localfs dependency remains explicit.
    LocalDiskCapacityProbe,
)
from backtest.adapters.artifacts.source_inspection import ArtifactSourceInspectionLoader
from backtest.adapters.catalog.sqlite import (
    SQLiteArtifactCatalog,
    SQLiteCanonicalOutputObserver,
    # Include sqlite job queue so the sqlite dependency remains explicit.
    SQLiteJobQueue,
    SQLiteShardLedger,
)
from backtest.adapters.columnar.arrow import (
    GapSafePrepareDatasetJobResolver,
    # Include local arrow canonical store so the arrow dependency remains explicit.
    LocalArrowCanonicalStore,
)
from backtest.adapters.ml.numpy import (
    EXACT_LINEAR_FRAMEWORK,
    NUMPY_ML_COMPILER_VERSION,
    # Include reference all rows universe config digest so the numpy dependency remains
    # explicit.
    REFERENCE_ALL_ROWS_UNIVERSE_CONFIG_DIGEST,
    REFERENCE_ALL_ROWS_UNIVERSE_SPEC_ID,
    REFERENCE_FEATURE_NAMES,
    REFERENCE_HORIZON_LABEL_CONFIG_DIGEST,
    REFERENCE_HORIZON_LABEL_SPEC_ID,
    # Close the numpy import after its required symbols are visible.
)
from backtest.adapters.performance import (
    BenchmarkAdmissionError,
    LocalBenchmarkReportPublisher,
    LocalExactBenchmarkRunner,
    LocalExactBenchmarkSpecResolver,
    # Include physical core count so the performance dependency remains explicit.
    physical_core_count,
)

# The composition root connects generic chart reads to Pump-owned display math.
from backtest.adapters.results.market_charts import LocalCopyMarketChartReader
from backtest.adapters.results.parquet import LocalParquetRunResultReaderFactory
from backtest.adapters.source.clickhouse import load_clickhouse_capabilities
from backtest.adapters.system import LocalSystemResourceProbe
from backtest.application.build_tool_roles import (
    ML_FEATURE_BUILDER_ROLE,
    ML_FROZEN_INFERENCE_ROLE,
    ML_LABEL_BUILDER_ROLE,
    ML_TRAINER_ROLE,
    # Include ml universe builder role so the build tool roles dependency remains
    # explicit.
    ML_UNIVERSE_BUILDER_ROLE,
)
from backtest.application.ml_reference import ReferenceMlContract
from backtest.application.models import (
    BudgetLimits,
    # Include dataset planning policy so the models dependency remains explicit.
    DatasetPlanningPolicy,
    QueryLimits,
)

# Import build tool roles at the visible module dependency boundary.
from backtest.application.ports.projectors import ProtocolProjector
from backtest.application.run_contracts import QueryRunContracts
from backtest.application.use_cases.cancel_job import CancelJob

# Import compile delivery schedule at the visible module dependency boundary.
from backtest.application.use_cases.compile_delivery_schedule import CompileDeliverySchedule
from backtest.application.use_cases.compile_replay import CompileReplay
from backtest.application.use_cases.inspect_source import InspectSource
from backtest.application.use_cases.plan_dataset import PlanDataset
from backtest.application.use_cases.prepare_dataset import PrepareDataset

# Import query artifacts at the visible module dependency boundary.
from backtest.application.use_cases.query_artifacts import QueryArtifacts
from backtest.application.use_cases.query_copy_market_chart import QueryCopyMarketChart
from backtest.application.use_cases.query_job_events import ListJobEvents
from backtest.application.use_cases.query_jobs import GetJob, ListJobs
from backtest.application.use_cases.query_run_results import QueryRunResults
from backtest.application.use_cases.query_runs import QueryRuns

# Import resolve benchmark at the visible module dependency boundary.
from backtest.application.use_cases.resolve_benchmark import ResolveBenchmark
from backtest.application.use_cases.resolve_run_spec import ResolveRunSpec
from backtest.application.use_cases.resolve_sweep_spec import ResolveSweepSpec
from backtest.application.use_cases.retry_job import RetryJob
from backtest.application.use_cases.run_backtest import RunBacktest

# Import run exact benchmark at the visible module dependency boundary.
from backtest.application.use_cases.run_exact_benchmark import RunExactBenchmark
from backtest.application.use_cases.run_sweep import RunSweep
from backtest.application.use_cases.store_source_inspection import StoreSourceInspection
from backtest.application.use_cases.submit_job import SubmitJob
from backtest.bootstrap.benchmarks import SpawnExactBenchmarkTargetFactory

# Import build tools at the visible module dependency boundary.
from backtest.bootstrap.build_tools import BuildToolBundleRegistry
from backtest.bootstrap.canonical_reconciliation import (
    CanonicalShardIndexReconciler,
    ReconciledPrepareDatasetSubmitJob,
)

# Only bootstrap assembles concrete source, execution and maintenance adapters.
from backtest.bootstrap.config import ResourceSettings, Settings
from backtest.bootstrap.configured_projector import build_configured_projector
from backtest.bootstrap.execution_container import build_execution_container
from backtest.bootstrap.maintenance import MaintenanceServices, build_maintenance_services
from backtest.bootstrap.pumpfun_copy_source import build_pumpfun_copy_source_composition

# The source family is selected explicitly before wiring application ports.
from backtest.bootstrap.pumpfun_live_source import build_pumpfun_live_source_composition

# Import reference run resolver at the visible module dependency boundary.
from backtest.bootstrap.reference_run_resolver import ReferenceRunSpecResolver
from backtest.bootstrap.source import ConfiguredClickHouseSource, select_clickhouse_query_profile
from backtest.interfaces.api import ControlUseCases
from backtest.plugins.protocols.pumpfun.market_charts import pump_market_cap_state
from backtest.runtime.host_resources import (
    HostMemoryReserves,
    derive_host_memory_budget,
    measure_host_memory,
)
from backtest.runtime.resource_budget import HostCapacity
from backtest.runtime.runtime_lock import RuntimeManifest


def _measure_benchmark_host_capacity(
    resources: ResourceSettings,
    *,
    physical_cores: int,
    max_processes_by_io: int,
) -> HostCapacity:
    """Measure the host-private budget after the workload profiling child exits."""

    mebibyte = 1024**2
    memory = derive_host_memory_budget(
        measure_host_memory(),
        HostMemoryReserves(
            configured_child_ceiling_bytes=(resources.max_aggregate_child_memory_mb * mebibyte),
            safety_reserve_bytes=resources.memory_safety_reserve_mb * mebibyte,
            page_cache_floor_bytes=resources.page_cache_floor_mb * mebibyte,
            host_staging_output_reserve_bytes=(resources.host_staging_output_reserve_mb * mebibyte),
            fixed_shared_overhead_bytes=resources.fixed_shared_overhead_mb * mebibyte,
        ),
    )
    private_memory_mb = memory.available_child_private_bytes // mebibyte
    if private_memory_mb <= 0:
        raise BenchmarkAdmissionError(
            "measured host memory leaves no safe private budget for benchmark child processes"
        )
    return HostCapacity(
        private_memory_mb=private_memory_mb,
        physical_cores=physical_cores,
        max_processes_by_io=max_processes_by_io,
    )


# Keep the runtime container contract and validation rules together.
@dataclass(frozen=True, slots=True)
class RuntimeContainer:
    settings: Settings
    artifacts: LocalArtifactRepository
    catalog: SQLiteArtifactCatalog
    # Declare jobs explicitly in the runtime container contract.
    jobs: SQLiteJobQueue
    source: ConfiguredClickHouseSource
    prepare_dataset: PrepareDataset | None
    compile_replay: CompileReplay
    compile_delivery_schedule: CompileDeliverySchedule
    # Declare run backtest explicitly in the runtime container contract.
    run_backtest: RunBacktest
    run_sweep: RunSweep
    run_benchmark: RunExactBenchmark
    run_exact_benchmark: RunExactBenchmark
    resolve_benchmark: ResolveBenchmark
    # Declare resolve run spec explicitly in the runtime container contract.
    resolve_run_spec: ResolveRunSpec
    resolve_sweep_spec: ResolveSweepSpec
    runtime_manifest: RuntimeManifest
    maintenance: MaintenanceServices
    control: ControlUseCases


# Define build runtime container as one focused operation with an explicit boundary.
def build_runtime_container(
    settings: Settings,
    *,
    profile: str,
    capabilities_file: Path | None = None,
    # Keep the runtime container input explicit in the build runtime container contract.
) -> RuntimeContainer:
    """Wire concrete adapters without opening the remote source eagerly."""

    selected_capabilities = capabilities_file or settings.source.capabilities_file
    capabilities = (
        () if selected_capabilities is None else load_clickhouse_capabilities(selected_capabilities)
    )
    build_tools = BuildToolBundleRegistry().pin()
    # A recognized live source profile supplies the pinned normalization contract.
    pumpfun_live = (
        build_pumpfun_live_source_composition(capabilities)
        if capabilities and select_clickhouse_query_profile(capabilities) is not None
        else None
    )
    # Copy source configuration selects a separate fixed projector and evidence family.
    copy_source = None
    if settings.source.copy_selection is not None:
        copy_source = build_pumpfun_copy_source_composition(
            capabilities, settings.source.copy_selection, build_tools=build_tools
        )
        # The selected composition is the sole authoritative source for the prepared snapshot.
        pumpfun_live = copy_source
    # Projection uses only the one selected authoritative source composition.
    projection_capabilities = (
        capabilities if pumpfun_live is None else pumpfun_live.projection_capabilities
    )
    # Assemble projector once so the build runtime container workflow shares one value.
    projector: ProtocolProjector | None = None if copy_source is None else copy_source.projector
    if copy_source is None and settings.source.projections_file is not None:
        # Handle the build runtime container projections file, source and settings
        # condition as a distinct block.
        projector = build_configured_projector(
            settings.source.projections_file,
            projection_capabilities,
            build_tools=build_tools,
            source_normalizer_digest=(
                None if pumpfun_live is None else pumpfun_live.normalizer_digest
            ),
        )
    # Assemble execution once so the build runtime container workflow shares one value.
    execution = build_execution_container(
        settings,
        build_tools=build_tools,
        expected_projector_bundle_id=(None if projector is None else projector.bundle_id),
    )
    # Assemble runtime manifest once so the build runtime container workflow shares one
    # value.
    runtime_manifest = execution.runtime_manifest
    data_root = settings.paths.data_root.resolve()
    artifacts = execution.artifacts
    jobs = SQLiteJobQueue(
        data_root / "catalog" / "catalog.sqlite",
        # Pass backup cut lock path explicitly so SQLiteJobQueue receives a reviewable
        # sqlite and catalog input in build runtime container.
        backup_cut_lock_path=artifacts.locks_root / "backup-cut.lock",
    )
    catalog = SQLiteArtifactCatalog(data_root / "catalog" / "catalog.sqlite", artifacts)
    source = ConfiguredClickHouseSource(
        settings,
        capabilities,
        pumpfun_live=pumpfun_live,
        projector_digest=(
            None if pumpfun_live is None or projector is None else projector.config_digest
        ),
    )
    compile_replay = execution.compile_replay
    # Assemble compile delivery schedule once so the build runtime container workflow
    # shares one value.
    compile_delivery_schedule = execution.compile_delivery_schedule
    run_backtest = execution.run_backtest
    run_sweep = execution.run_sweep
    expected_projector_bundle_id = None if projector is None else projector.bundle_id
    benchmark_resolver = LocalExactBenchmarkSpecResolver(
        # Pass data root explicitly so LocalExactBenchmarkSpecResolver receives a
        # reviewable runtime lock id and max builder memory mb input in build runtime
        # container.
        data_root,
        runtime_manifest.runtime_lock_id,
        duckdb_memory_limit_mb=settings.resources.max_builder_memory_mb,
        build_tools=build_tools,
    )
    # Assemble exact benchmark runner once so the build runtime container workflow shares
    # one value.
    benchmark_physical_cores = physical_core_count()
    benchmark_max_processes_by_io = settings.resources.max_parallel_runs
    exact_benchmark_runner = LocalExactBenchmarkRunner(
        data_root,
        private_memory_budget_mb=settings.resources.max_aggregate_child_memory_mb,
        physical_cores=benchmark_physical_cores,
        max_processes_by_io=benchmark_max_processes_by_io,
        # Keep the settings SpawnExactBenchmarkTargetFactory step visible while building
        # exact benchmark runner.
        target_factory=SpawnExactBenchmarkTargetFactory(
            settings,
            runtime_manifest.runtime_lock_id,
            expected_projector_bundle_id,
        ),
        capacity_provider=lambda: _measure_benchmark_host_capacity(
            settings.resources,
            physical_cores=benchmark_physical_cores,
            max_processes_by_io=benchmark_max_processes_by_io,
        ),
        # Complete LocalExactBenchmarkRunner only after its aggregate memory and measured
        # host-capacity inputs are visible in build runtime container.
    )
    benchmark_publisher = LocalBenchmarkReportPublisher(artifacts)
    run_exact_benchmark = RunExactBenchmark(
        benchmark_resolver,
        exact_benchmark_runner,
        # Pass benchmark publisher explicitly so RunExactBenchmark receives a reviewable
        # benchmark resolver and exact benchmark runner input in build runtime container.
        benchmark_publisher,
    )
    run_benchmark = run_exact_benchmark
    reference_resolver = ReferenceRunSpecResolver(
        artifacts,
        # Pass runtime manifest explicitly so ReferenceRunSpecResolver receives a
        # reviewable runtime lock id and max builder memory mb input in build runtime
        # container.
        runtime_manifest.runtime_lock_id,
        parquet_memory_limit_mb=settings.resources.max_builder_memory_mb,
        threads=settings.resources.native_threads_per_process,
        expected_projector_bundle_id=(None if projector is None else projector.bundle_id),
        build_tools=build_tools,
        # Complete ReferenceRunSpecResolver only after its runtime lock id and max builder
        # memory mb inputs are visible in build runtime container.
    )
    resolve_run_spec = ResolveRunSpec(reference_resolver)
    resolve_sweep_spec = ResolveSweepSpec(reference_resolver)
    inspect_source = StoreSourceInspection(
        InspectSource(source, evidence_reader=source),
        # Pass artifacts explicitly so StoreSourceInspection receives a reviewable inspect
        # source and source input in build runtime container.
        artifacts,
    )
    planning = settings.planning
    gibibyte = 1024**3
    plan_dataset = PlanDataset(
        # Keep the artifacts ArtifactSourceInspectionLoader step visible while building
        # plan dataset.
        ArtifactSourceInspectionLoader(artifacts),
        DatasetPlanningPolicy(
            budget_limits=BudgetLimits(
                max_remote_bytes=planning.max_remote_gb * gibibyte,
                max_local_bytes=planning.max_local_gb * gibibyte,
                # Pass max days explicitly so BudgetLimits receives a reviewable max
                # remote gb and max local gb input in build runtime container.
                max_days=planning.max_days,
                temporary_reserve_bytes=planning.staging_reserve_gb * gibibyte,
                disk_low_watermark_bytes=(settings.resources.disk_low_watermark_gb * gibibyte),
            ),
            query_limits=QueryLimits(
                # Pass max execution seconds explicitly so QueryLimits receives a
                # reviewable max query execution seconds and max query memory mb input in
                # build runtime container.
                max_execution_seconds=planning.max_query_execution_seconds,
                max_memory_bytes=planning.max_query_memory_mb * 1024**2,
                max_result_rows=planning.max_query_result_rows,
            ),
            max_total_blocks=planning.max_total_blocks,
            # Pass max total shards explicitly so DatasetPlanningPolicy receives a
            # reviewable max days and max remote gb input in build runtime container.
            max_total_shards=planning.max_total_shards,
            max_shard_blocks=planning.max_shard_blocks,
        ),
        disk_probe=LocalDiskCapacityProbe(data_root),
    )
    # Assemble prepare dataset once so the build runtime container workflow shares one
    # value.
    prepare_dataset: PrepareDataset | None = None
    prepare_job_resolver = None
    canonical_reconciler = None
    if projector is not None:
        # Handle the build runtime container projector is not None branch as a distinct
        # logical block.
        canonical_store = LocalArrowCanonicalStore(
            artifacts,
            memory_limit_mb=settings.resources.max_builder_memory_mb,
            threads=settings.resources.native_threads_per_process,
            tmp_quota_bytes=settings.resources.tmp_quota_gb * 1024**3,
            # Pass build tools explicitly so LocalArrowCanonicalStore receives a
            # reviewable max builder memory mb and resources input in build runtime
            # container.
            build_tools=build_tools,
        )
        prepare_dataset = PrepareDataset(source, projector, canonical_store)
        shard_ledger = SQLiteShardLedger(data_root / "catalog" / "catalog.sqlite", catalog)
        canonical_reconciler = CanonicalShardIndexReconciler(
            artifacts,
            catalog,
            SQLiteCanonicalOutputObserver(artifacts, shard_ledger),
        )
        prepare_job_resolver = GapSafePrepareDatasetJobResolver(
            shard_ledger,
            projector,
            build_tools=build_tools,
        )
    artifact_queries = QueryArtifacts(catalog, artifacts)
    resources = settings.resources
    # Assemble resource probe once so the build runtime container workflow shares one
    # value.
    resource_probe = LocalSystemResourceProbe(
        data_root,
        aggregate_child_memory_bytes=(resources.max_aggregate_child_memory_mb * 1024**2),
        builder_memory_bytes=resources.max_builder_memory_mb * 1024**2,
        max_parallel_runs=resources.max_parallel_runs,
        # Pass native threads per process explicitly so LocalSystemResourceProbe receives
        # a reviewable max aggregate child memory mb and max builder memory mb input in
        # build runtime container.
        native_threads_per_process=resources.native_threads_per_process,
        tmp_quota_bytes=resources.tmp_quota_gb * gibibyte,
        disk_low_watermark_bytes=resources.disk_low_watermark_gb * gibibyte,
        disk_emergency_watermark_bytes=(resources.disk_emergency_watermark_gb * gibibyte),
        memory_safety_reserve_bytes=resources.memory_safety_reserve_mb * 1024**2,
        # Pass page cache floor bytes explicitly so LocalSystemResourceProbe receives a
        # reviewable max aggregate child memory mb and max builder memory mb input in
        # build runtime container.
        page_cache_floor_bytes=resources.page_cache_floor_mb * 1024**2,
        host_staging_output_reserve_bytes=(resources.host_staging_output_reserve_mb * 1024**2),
        fixed_shared_overhead_bytes=resources.fixed_shared_overhead_mb * 1024**2,
    )
    maintenance = build_maintenance_services(settings, artifacts)
    # Assemble control once so the build runtime container workflow shares one value.
    submit_job = SubmitJob(jobs, prepare_job_resolver)
    if canonical_reconciler is not None and prepare_job_resolver is not None:
        submit_job = ReconciledPrepareDatasetSubmitJob(
            jobs,
            prepare_job_resolver,
            canonical_reconciler,
        )
    # Results and chart selection share one bounded semantic-verification cache.
    result_readers = LocalParquetRunResultReaderFactory(artifacts)
    chart_reader = LocalCopyMarketChartReader(artifacts, pump_market_cap_state, build_tools)
    # Inject the protocol projector only at bootstrap; the query remains infrastructure-neutral.
    control = ControlUseCases(
        inspect_source=inspect_source,
        plan_dataset=plan_dataset,
        submit_job=submit_job,
        cancel_job=CancelJob(jobs, jobs),
        # Keep the jobs GetJob step visible while building control.
        get_job=GetJob(jobs),
        list_jobs=ListJobs(jobs),
        profile=profile,
        default_run_physical_settings=settings.replay.to_run_physical_settings(),
        query_artifacts=artifact_queries,
        # Keep the artifact queries QueryRuns step visible while building control.
        # The same SQLite adapter supplies a manifest-bound, rebuildable Run index.
        query_runs=QueryRuns(artifact_queries, catalog),
        query_run_results=QueryRunResults(result_readers),
        query_copy_market_chart=QueryCopyMarketChart(result_readers, chart_reader),
        # Read-only chart admission does not alter queued job resource or resolution policy.
        system_resources=resource_probe,
        resolve_run_spec=resolve_run_spec,
        resolve_sweep_spec=resolve_sweep_spec,
        # Keep the jobs RetryJob step visible while building control.
        retry_job=RetryJob(jobs),
        list_job_events=ListJobEvents(jobs, jobs),
        ml_reference_contract=ReferenceMlContract(
            runtime_lock_id=runtime_manifest.runtime_lock_id,
            compiler_version=NUMPY_ML_COMPILER_VERSION,
            # Keep the ml feature builder role require_current step visible while building
            # control.
            feature_builder_bundle_id=build_tools.require_current(ML_FEATURE_BUILDER_ROLE),
            supported_feature_names=REFERENCE_FEATURE_NAMES,
            universe_builder_bundle_id=build_tools.require_current(ML_UNIVERSE_BUILDER_ROLE),
            universe_spec_id=REFERENCE_ALL_ROWS_UNIVERSE_SPEC_ID,
            universe_config_digest=REFERENCE_ALL_ROWS_UNIVERSE_CONFIG_DIGEST,
            # Keep the ml label builder role require_current step visible while building
            # control.
            label_builder_bundle_id=build_tools.require_current(ML_LABEL_BUILDER_ROLE),
            label_spec_id=REFERENCE_HORIZON_LABEL_SPEC_ID,
            label_config_digest=REFERENCE_HORIZON_LABEL_CONFIG_DIGEST,
            trainer_bundle_id=build_tools.require_current(ML_TRAINER_ROLE),
            trainer_framework=EXACT_LINEAR_FRAMEWORK,
            # Keep the ml frozen inference role require_current step visible while
            # building control.
            frozen_inference_bundle_id=build_tools.require_current(ML_FROZEN_INFERENCE_ROLE),
        ),
        query_run_contracts=QueryRunContracts(),
    )
    return RuntimeContainer(
        # Pass settings explicitly so RuntimeContainer receives a reviewable resolve
        # benchmark and settings input in build runtime container.
        settings=settings,
        artifacts=artifacts,
        catalog=catalog,
        jobs=jobs,
        source=source,
        # Pass prepare dataset explicitly so RuntimeContainer receives a reviewable
        # resolve benchmark and settings input in build runtime container.
        prepare_dataset=prepare_dataset,
        compile_replay=compile_replay,
        compile_delivery_schedule=compile_delivery_schedule,
        run_backtest=run_backtest,
        run_sweep=run_sweep,
        # Pass run benchmark explicitly so RuntimeContainer receives a reviewable resolve
        # benchmark and settings input in build runtime container.
        run_benchmark=run_benchmark,
        run_exact_benchmark=run_exact_benchmark,
        resolve_benchmark=ResolveBenchmark(benchmark_resolver),
        resolve_run_spec=resolve_run_spec,
        resolve_sweep_spec=resolve_sweep_spec,
        # Pass runtime manifest explicitly so RuntimeContainer receives a reviewable
        # resolve benchmark and settings input in build runtime container.
        runtime_manifest=runtime_manifest,
        maintenance=maintenance,
        control=control,
    )


__all__ = ["RuntimeContainer", "build_runtime_container"]
