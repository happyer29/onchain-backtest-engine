"""Composition root for isolated local execution with no source or SQLite access."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import partial
from typing import Final

from backtest.adapters.artifacts.localfs import LocalArtifactRepository

# Import arrow at the visible module dependency boundary.
from backtest.adapters.columnar.arrow import CanonicalParquetReplaySource
from backtest.adapters.columnar.numpy import (
    NUMPY_MMAP_FIRST_SWAP_BACKEND,
    NUMPY_MMAP_PUMPFUN_SNIPING_BACKEND,
    LocalNumpyReplayPackCompiler,
    # Include numpy mmap first swap engine so the numpy dependency remains explicit.
    NumpyMmapFirstSwapEngine,
    NumpyMmapPumpfunSnipingEngine,
)
from backtest.adapters.delivery_schedule import LocalDeliveryScheduleSourceFactory
from backtest.adapters.delivery_schedule.numpy import LocalNumpyDeliveryScheduleCompiler

# Import numpy at the visible module dependency boundary.
from backtest.adapters.ml.numpy import (
    LocalExactFrozenPredictionBuilder,
    LocalExactIntegerLinearTrainer,
    LocalNumpyCausalOverlayFactory,
    LocalNumpyMlArtifactPublisher,
    # Include local reference ml row builders so the numpy dependency remains explicit.
    LocalReferenceMlRowBuilders,
)
from backtest.adapters.process.parallel import SpawnProcessIndependentRunExecutor
from backtest.adapters.process.serial import SerialIndependentRunExecutor
from backtest.adapters.replay import LocalReplaySourceFactory

# Import results at the visible module dependency boundary.
from backtest.adapters.results import LocalParquetRunOutputStore, LocalSweepOutputStore
from backtest.application.code_bundles import PinnedCodeBundleSet
from backtest.application.use_cases.compile_delivery_schedule import CompileDeliverySchedule
from backtest.application.use_cases.compile_replay import CompileReplay
from backtest.application.use_cases.publish_ml_artifacts import (
    # Include build feature set so the publish ml artifacts dependency remains explicit.
    BuildFeatureSet,
    BuildFrozenPredictions,
    BuildLabelSet,
    BuildUniverse,
    PublishModelSchedule,
    # Include train exact linear model so the publish ml artifacts dependency remains
    # explicit.
    TrainExactLinearModel,
)
from backtest.application.use_cases.run_backtest import (
    RunBacktest,
    RunBacktestRequest,
    # Include run backtest result so the run backtest dependency remains explicit.
    RunBacktestResult,
)
from backtest.application.use_cases.run_sweep import RunSweep
from backtest.bootstrap.build_tools import BuildToolBundleRegistry
from backtest.bootstrap.config import Settings

# Import runtime plugins at the visible module dependency boundary.
from backtest.bootstrap.runtime_plugins import ReferenceRuntimeComponentsResolver
from backtest.bootstrap.sniping_runtime import PumpfunSnipingRuntimeComponentsResolver
from backtest.domain.identifiers import BundleId
from backtest.engine import ReferenceBacktestEngine, SnipingReferenceEngine
from backtest.plugins.execution import ConstantProductExecutionModel

# Import solana at the visible module dependency boundary.
from backtest.plugins.networks.solana import SolanaSnipingCostModel
from backtest.plugins.protocols.pumpfun import PumpfunSnipingProtocolRuntime
from backtest.plugins.risk import StaticRiskPolicy
from backtest.plugins.strategies import FirstSwapStrategy, PumpfunSnipingStrategy
from backtest.runtime.runtime_lock import RuntimeManifest, build_runtime_manifest

# Import thread limits at the visible module dependency boundary.
from backtest.runtime.thread_limits import (
    apply_child_process_determinism,
    apply_thread_limits,
    require_child_process_determinism,
)

# Compilation retains the compact clock and deterministic dictionaries while scanning.
# Keep decoded Parquet batches smaller than run-time batches so that this bounded state
# and one batch per capability fit the declared single-host builder envelope.
_REPLAY_COMPILER_READER_BATCH_ROWS: Final = 8_192


# Apply dataclass semantics to the following execution container contract.
@dataclass(frozen=True, slots=True)
class ExecutionContainer:
    """Only verified local artifact and deterministic execution capabilities."""

    settings: Settings
    artifacts: LocalArtifactRepository
    compile_replay: CompileReplay
    compile_delivery_schedule: CompileDeliverySchedule
    run_backtest: RunBacktest
    # Declare run sweep explicitly in the execution container contract.
    run_sweep: RunSweep
    ml_rows: LocalReferenceMlRowBuilders
    build_feature_set: BuildFeatureSet
    build_universe: BuildUniverse
    build_label_set: BuildLabelSet
    # Declare train model explicitly in the execution container contract.
    train_model: TrainExactLinearModel
    publish_model_schedule: PublishModelSchedule
    build_frozen_predictions: BuildFrozenPredictions
    runtime_manifest: RuntimeManifest


def _execute_isolated_sweep_entry(
    # Keep the settings input explicit in the execute isolated sweep entry contract.
    settings: Settings,
    request: RunBacktestRequest,
) -> RunBacktestResult:
    """Spawn-worker composition: local artifacts only, no source and no SQLite."""

    container = build_execution_container(
        settings,
        verify_isolated_child_environment=True,
    )
    return container.run_backtest.execute(request)


# Define build execution container as one focused operation with an explicit boundary.
def build_execution_container(
    settings: Settings,
    *,
    verify_isolated_child_environment: bool = False,
    build_tools: PinnedCodeBundleSet | None = None,
    # Keep the expected projector bundle id input explicit in the build execution
    # container contract.
    expected_projector_bundle_id: BundleId | None = None,
) -> ExecutionContainer:
    """Build child-safe execution services without importing a source credential."""

    resources = settings.resources
    runtime_environment = dict(os.environ)
    if verify_isolated_child_environment:
        require_child_process_determinism(resources.native_threads_per_process)
    else:
        # Handle the build execution container complement of
        # verify_isolated_child_environment explicitly.
        apply_thread_limits(resources.native_threads_per_process)
        runtime_environment = dict(os.environ)
        apply_child_process_determinism(
            resources.native_threads_per_process,
            runtime_environment,
            # Complete apply_child_process_determinism only after its native threads per
            # process and resources inputs are visible in build execution container.
        )
    runtime_manifest = build_runtime_manifest(
        native_threads_per_process=resources.native_threads_per_process,
        environ=runtime_environment,
    )
    # Assemble physical tools once so the build execution container workflow shares one
    # value.
    physical_tools = build_tools or BuildToolBundleRegistry().pin()
    data_root = settings.paths.data_root.resolve()
    artifacts = LocalArtifactRepository(
        data_root,
        staging_quota_bytes=resources.tmp_quota_gb * 1024**3,
        # Complete LocalArtifactRepository only after its tmp quota gb and data root inputs
        # are visible in build execution container.
    )
    ml_publisher = LocalNumpyMlArtifactPublisher(
        artifacts,
        runtime_lock_id=runtime_manifest.runtime_lock_id,
        build_tools=physical_tools,
        # Complete LocalNumpyMlArtifactPublisher only after its runtime lock id and artifacts
        # inputs are visible in build execution container.
    )
    ml_rows = LocalReferenceMlRowBuilders(
        artifacts,
        runtime_lock_id=runtime_manifest.runtime_lock_id,
        build_tools=physical_tools,
        # Complete LocalReferenceMlRowBuilders only after its runtime lock id and artifacts
        # inputs are visible in build execution container.
    )
    replay_factory = LocalReplaySourceFactory(
        artifacts,
        parquet_memory_limit_mb=resources.max_builder_memory_mb,
        threads=resources.native_threads_per_process,
        # Pass expected projector bundle id explicitly so LocalReplaySourceFactory
        # receives a reviewable max builder memory mb and native threads per process input
        # in build execution container.
        expected_projector_bundle_id=expected_projector_bundle_id,
        build_tools=physical_tools,
    )
    compile_replay = CompileReplay(
        LocalNumpyReplayPackCompiler(
            # Pass artifacts explicitly so LocalNumpyReplayPackCompiler receives a
            # reviewable max builder memory mb and native threads per process input in
            # build execution container.
            artifacts,
            lambda snapshot_id: CanonicalParquetReplaySource(
                artifacts,
                snapshot_id,
                duckdb_memory_limit_mb=resources.max_builder_memory_mb,
                # Pass threads explicitly so CanonicalParquetReplaySource receives a
                # reviewable max builder memory mb and native threads per process input in
                # build execution container.
                threads=resources.native_threads_per_process,
                reader_batch_rows=_REPLAY_COMPILER_READER_BATCH_ROWS,
                reader_readahead=1,
                expected_projector_bundle_id=expected_projector_bundle_id,
                build_tools=physical_tools,
            ),
            runtime_lock_id=runtime_manifest.runtime_lock_id,
            # Pass build tools explicitly so LocalNumpyReplayPackCompiler receives a
            # reviewable max builder memory mb and native threads per process input in
            # build execution container.
            build_tools=physical_tools,
        )
    )
    compile_delivery_schedule = CompileDeliverySchedule(
        LocalNumpyDeliveryScheduleCompiler(
            # Pass artifacts explicitly so LocalNumpyDeliveryScheduleCompiler receives a
            # reviewable runtime lock id and artifacts input in build execution container.
            artifacts,
            runtime_lock_id=runtime_manifest.runtime_lock_id,
            build_tools=physical_tools,
        )
    )
    # Assemble run backtest once so the build execution container workflow shares one
    # value.
    run_backtest = RunBacktest(
        replay_factory,
        ReferenceRuntimeComponentsResolver(runtime_manifest.runtime_lock_id),
        ReferenceBacktestEngine(),
        LocalParquetRunOutputStore(artifacts, data_root / "tmp" / "runs"),
        # Keep the artifacts LocalDeliveryScheduleSourceFactory step visible while
        # building run backtest.
        delivery_schedules=LocalDeliveryScheduleSourceFactory(
            artifacts,
            build_tools=physical_tools,
        ),
        causal_overlays=LocalNumpyCausalOverlayFactory(
            # Pass artifacts explicitly so LocalNumpyCausalOverlayFactory receives a
            # reviewable embedded-inference and tmp input in build execution container.
            artifacts,
            embedded_temporary_parent=data_root / "tmp" / "embedded-inference",
            embedded_maximum_temporary_bytes=resources.max_run_tmp_gb * 1024**3,
            build_tools=physical_tools,
        ),
        # Pass additional engines explicitly so RunBacktest receives a reviewable runs and
        # tmp input in build execution container.
        additional_engines={
            NUMPY_MMAP_FIRST_SWAP_BACKEND: NumpyMmapFirstSwapEngine(
                strategy_type=FirstSwapStrategy,
                execution_model_type=ConstantProductExecutionModel,
                risk_policy_type=StaticRiskPolicy,
                # Complete NumpyMmapFirstSwapEngine only after its first swap strategy and
                # constant product execution model inputs are visible in build execution
                # container.
            )
        },
        sniping_components=PumpfunSnipingRuntimeComponentsResolver(
            runtime_manifest.runtime_lock_id
        ),
        # Keep the sniping reference engine SnipingReferenceEngine step visible while
        # building run backtest.
        sniping_engine=SnipingReferenceEngine(),
        additional_sniping_engines={
            NUMPY_MMAP_PUMPFUN_SNIPING_BACKEND: NumpyMmapPumpfunSnipingEngine(
                strategy_type=PumpfunSnipingStrategy,
                protocol_type=PumpfunSnipingProtocolRuntime,
                # Pass network cost type explicitly so NumpyMmapPumpfunSnipingEngine
                # receives a reviewable pumpfun sniping strategy and pumpfun sniping
                # protocol runtime input in build execution container.
                network_cost_type=SolanaSnipingCostModel,
            )
        },
        required_threads=resources.native_threads_per_process,
    )
    # Assemble independent runs once so the build execution container workflow shares one
    # value.
    independent_runs = (
        SerialIndependentRunExecutor(run_backtest)
        if resources.max_parallel_runs == 1
        else SpawnProcessIndependentRunExecutor(
            partial(_execute_isolated_sweep_entry, settings),
            # Pass max workers explicitly so SpawnProcessIndependentRunExecutor receives a
            # reviewable max parallel runs and partial input in build execution container.
            max_workers=resources.max_parallel_runs,
        )
    )
    run_sweep = RunSweep(independent_runs, LocalSweepOutputStore(artifacts))
    return ExecutionContainer(
        # Pass settings explicitly so ExecutionContainer receives a reviewable build
        # feature set and build universe input in build execution container.
        settings=settings,
        artifacts=artifacts,
        compile_replay=compile_replay,
        compile_delivery_schedule=compile_delivery_schedule,
        run_backtest=run_backtest,
        # Pass run sweep explicitly so ExecutionContainer receives a reviewable build
        # feature set and build universe input in build execution container.
        run_sweep=run_sweep,
        ml_rows=ml_rows,
        build_feature_set=BuildFeatureSet(ml_publisher),
        build_universe=BuildUniverse(ml_publisher),
        build_label_set=BuildLabelSet(ml_publisher),
        # Include train model in the completed build execution container result.
        train_model=TrainExactLinearModel(
            LocalExactIntegerLinearTrainer(
                artifacts,
                ml_publisher,
                build_tools=physical_tools,
                # Complete LocalExactIntegerLinearTrainer only after its artifacts and ml
                # publisher inputs are visible in build execution container.
            )
        ),
        publish_model_schedule=PublishModelSchedule(ml_publisher),
        build_frozen_predictions=BuildFrozenPredictions(
            LocalExactFrozenPredictionBuilder(
                # Pass artifacts explicitly so LocalExactFrozenPredictionBuilder receives
                # a reviewable artifacts and ml publisher input in build execution
                # container.
                artifacts,
                ml_publisher,
                build_tools=physical_tools,
            )
        ),
        # Pass runtime manifest explicitly so ExecutionContainer receives a reviewable
        # build feature set and build universe input in build execution container.
        runtime_manifest=runtime_manifest,
    )


__all__ = ["ExecutionContainer", "build_execution_container"]
