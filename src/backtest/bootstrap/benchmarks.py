"""Spawn-safe production composition for exact local benchmark targets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backtest.adapters.performance.targets import (
    LocalExactBenchmarkSpecResolver,
    # Include local exact benchmark target factory so the targets dependency remains
    # explicit.
    LocalExactBenchmarkTargetFactory,
)
from backtest.application.benchmarks import (
    BenchmarkExecutionPhase,
    BenchmarkLaunchRoute,
    # Include benchmark spec so the benchmarks dependency remains explicit.
    BenchmarkSpec,
    BenchmarkWorkload,
)
from backtest.application.ports.benchmarks import BenchmarkTarget
from backtest.application.run_results import RunPhysicalSettings

# Import run specs at the visible module dependency boundary.
from backtest.application.run_specs import ResolvedRunSpec
from backtest.bootstrap.benchmark_control import (
    IsolatedDirectControlBenchmarkExecutor,
    IsolatedHttpControlBenchmarkExecutor,
)

# Import build tools at the visible module dependency boundary.
from backtest.bootstrap.build_tools import BuildToolBundleRegistry
from backtest.bootstrap.config import Settings
from backtest.bootstrap.execution_container import build_execution_container
from backtest.domain.identifiers import BundleId, ContentDigest, RuntimeLockId
from backtest.engine.reference import RunSummary

# Import sniping at the visible module dependency boundary.
from backtest.engine.sniping import SnipingRunSummary


@dataclass(frozen=True, slots=True)
class SpawnRunSummaryExecutor:
    """Serializable declaration; concrete execution services are built in child."""

    settings: Settings
    expected_projector_bundle_id: BundleId | None

    def execute_summary(
        self,
        spec: ResolvedRunSpec,
        # Keep the physical settings input explicit in the execute summary contract.
        physical_settings: RunPhysicalSettings,
    ) -> RunSummary | SnipingRunSummary:
        # Execute the spawn run summary executor execute summary workflow in explicit,
        # reviewable steps.
        execution = build_execution_container(
            self.settings,
            expected_projector_bundle_id=self.expected_projector_bundle_id,
        )
        return execution.run_backtest.execute_summary(spec, physical_settings)


# Apply dataclass semantics to the following spawn exact benchmark target factory
# contract.
@dataclass(frozen=True, slots=True)
class SpawnExactBenchmarkTargetFactory:
    """Keep ProcessPool initializer state limited to canonical host declarations."""

    settings: Settings
    runtime_lock_id: RuntimeLockId
    expected_projector_bundle_id: BundleId | None

    def validate(self, spec: BenchmarkSpec, data_root: Path) -> None:
        # Execute the spawn exact benchmark target factory validate workflow in explicit,
        # reviewable steps.
        self._delegate(
            control_executor_available=(
                spec.workload is BenchmarkWorkload.CONTROL_PLANE_ROUND_TRIP
                and spec.launch_route in {BenchmarkLaunchRoute.DIRECT, BenchmarkLaunchRoute.CONTROL}
            )
            # Complete validate only after its spec and data root inputs are visible in spawn
            # exact benchmark target factory validate.
        ).validate(spec, data_root)

    def create(
        self,
        spec: BenchmarkSpec,
        data_root: Path,
        # Keep the attempt nonce input explicit in the create contract.
        attempt_nonce: ContentDigest,
        phase: BenchmarkExecutionPhase,
    ) -> BenchmarkTarget:
        # Execute the spawn exact benchmark target factory create workflow in explicit,
        # reviewable steps.
        if spec.workload is BenchmarkWorkload.CONTROL_PLANE_ROUND_TRIP:
            # Handle the spawn exact benchmark target factory create workload, control
            # plane round trip and spec condition as a distinct block.
            executor = (
                IsolatedDirectControlBenchmarkExecutor(
                    self.settings,
                    spec.input_artifact_ids[0],
                )
                # Keep the spec component named inside the executor contract.
                if spec.launch_route is BenchmarkLaunchRoute.DIRECT
                else IsolatedHttpControlBenchmarkExecutor(
                    self.settings,
                    spec.input_artifact_ids[0],
                )
                # Complete the executor group only after its semantic components are visible.
            )
            try:
                # Perform the protected spawn exact benchmark target factory create
                # operation before explicit failure handling.
                return self._delegate(control_executor=executor).create(
                    spec,
                    data_root,
                    attempt_nonce,
                    phase,
                    # Complete create only after its spec and data root inputs are visible in
                    # spawn exact benchmark target factory create.
                )
            except BaseException:
                # Translate the BaseException failure through the spawn exact benchmark
                # target factory create boundary.
                executor.close()
                raise
        return self._delegate().create(spec, data_root, attempt_nonce, phase)

    def _delegate(
        self,
        # Close the delegate signature after its explicit inputs.
        *,
        control_executor: (
            IsolatedDirectControlBenchmarkExecutor | IsolatedHttpControlBenchmarkExecutor | None
        ) = None,
        control_executor_available: bool = False,
        # Keep the local exact benchmark target factory input explicit in the delegate
        # contract.
    ) -> LocalExactBenchmarkTargetFactory:
        # Execute the spawn exact benchmark target factory delegate workflow in explicit,
        # reviewable steps.
        tools = BuildToolBundleRegistry().pin()
        resolver = LocalExactBenchmarkSpecResolver(
            self.settings.paths.data_root.resolve(),
            self.runtime_lock_id,
            duckdb_memory_limit_mb=self.settings.resources.max_builder_memory_mb,
            # Pass build tools explicitly so LocalExactBenchmarkSpecResolver receives a
            # reviewable resolve and data root input in spawn exact benchmark target
            # factory delegate.
            build_tools=tools,
        )
        return LocalExactBenchmarkTargetFactory(
            resolver,
            run_executor=SpawnRunSummaryExecutor(
                # Pass self explicitly so SpawnRunSummaryExecutor receives a reviewable
                # settings and expected projector bundle id input in spawn exact benchmark
                # target factory delegate.
                self.settings,
                self.expected_projector_bundle_id,
            ),
            control_executor=control_executor,
            control_executor_available=control_executor_available,
            # Complete LocalExactBenchmarkTargetFactory only after its settings and expected
            # projector bundle id inputs are visible in spawn exact benchmark target factory
            # delegate.
        )


__all__ = ["SpawnExactBenchmarkTargetFactory", "SpawnRunSummaryExecutor"]
