"""Spawn-safe ReplayPack scan and reference-reducer capacity benchmarks."""

from __future__ import annotations

import cProfile
import gc
import multiprocessing
import os

# Import resource at the visible module dependency boundary.
import resource
import sys
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ProcessPoolExecutor

# Import dataclasses at the visible module dependency boundary.
from dataclasses import dataclass, replace
from pathlib import Path
from types import CodeType
from typing import Protocol

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository

# Import compiler at the visible module dependency boundary.
from backtest.adapters.columnar.numpy.compiler import unit_replay_build_tools
from backtest.adapters.columnar.numpy.optimized_engine import NumpyMmapFirstSwapEngine
from backtest.adapters.columnar.numpy.reader import NumpyMmapReplaySource
from backtest.adapters.performance.metrics import (
    PeakPrivateRssSampler,
    # Include process io counters so the metrics dependency remains explicit.
    ProcessIoCounters,
    current_io_counters,
    peak_total_rss_bytes,
)
from backtest.application.benchmarks import (
    # Include benchmark execution phase so the benchmarks dependency remains explicit.
    BenchmarkExecutionPhase,
    BenchmarkReport,
    BenchmarkSample,
    BenchmarkSpec,
    BenchmarkWorkload,
    # Include benchmark workload result so the benchmarks dependency remains explicit.
    BenchmarkWorkloadResult,
    CacheCondition,
    IoCounterBasis,
    PrivateRssBasis,
    ProfilerEntry,
    # Close the benchmarks import after its required symbols are visible.
)
from backtest.application.build_tool_roles import REPLAY_COMPILER_ROLE, REPLAY_WRITER_ROLE
from backtest.application.code_bundles import PinnedCodeBundleSet
from backtest.application.models import ArtifactKind
from backtest.application.ports.benchmarks import BenchmarkTarget

# Import execution at the visible module dependency boundary.
from backtest.domain.execution import ExecutionMode, ExecutionNotification, ExecutionPlan
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import (
    ArtifactId,
    BundleId,
    # Include content digest so the identifiers dependency remains explicit.
    ContentDigest,
    DatasetRevisionId,
    LogicalContentHash,
    PoolId,
    ReplayPackId,
    # Close the identifiers import after its required symbols are visible.
)
from backtest.domain.intents import Intent, SwapExactInIntent
from backtest.domain.market_events import CanonicalEvent
from backtest.engine.contracts import EnginePhysicalSettings, PortfolioView, StrategyContext
from backtest.engine.reference import ReferenceBacktestEngine, ReferenceRunConfig, SlotLatencyModel

# Import replay at the visible module dependency boundary.
from backtest.engine.replay import ReplayBoundary
from backtest.engine.state import SimulationVenueState
from backtest.runtime.resource_budget import HostCapacity, ProcessDemand, admitted_processes
from backtest.runtime.thread_limits import apply_thread_limits

REPLAY_SCAN_BENCHMARK_BUNDLE_ID = BundleId(
    # Keep the v2 domain_digest step visible while building replay scan benchmark bundle
    # id.
    domain_digest(
        "backtest.replay-scan-benchmark-bundle.v2",
        {"algorithm": "sequential-mmap-touch-logical-hash-v2"},
    ).hex
)
# Bind reference reducer benchmark bundle id once as an explicit module-level contract.
REFERENCE_REDUCER_BENCHMARK_BUNDLE_ID = BundleId(
    domain_digest(
        "backtest.reference-reducer-benchmark-bundle.v1",
        {"engine": "reference", "strategy": "no-intent-v1"},
    ).hex
    # Complete BundleId only after its v1 and engine inputs are visible in module.
)
OPTIMIZED_REDUCER_BENCHMARK_BUNDLE_ID = BundleId(
    domain_digest(
        "backtest.optimized-reducer-benchmark-bundle.v1",
        {
            # Keep engine named so the v1 and engine payload passed to domain_digest
            # remains self-describing within module.
            "engine": "numpy-mmap-first-swap-exact-v1",
            "semantic_oracle": "reference",
            "strategy": "benchmark-no-intent-absent-pool-v1",
        },
    ).hex
    # Complete BundleId only after its v1 and engine inputs are visible in module.
)
_NOOP_STRATEGY_BUNDLE_ID = BundleId(domain_digest("benchmark.noop-strategy.v1", {}).hex)
_NOOP_EXECUTION_BUNDLE_ID = BundleId(domain_digest("benchmark.noop-execution.v1", {}).hex)
_NOOP_RISK_BUNDLE_ID = BundleId(domain_digest("benchmark.noop-risk.v1", {}).hex)
_DEFAULT_BENCHMARK_POOL_ID = PoolId("backtest-benchmark-default-pool")
# Bind default benchmark attempt nonce once as an explicit module-level contract.
_DEFAULT_BENCHMARK_ATTEMPT_NONCE = ContentDigest("0" * 64)


class BenchmarkAdmissionError(RuntimeError):
    """The exact requested process count does not fit measured host limits."""


class VerifiedColdCacheController(Protocol):
    """Privileged external boundary able to prove one page-cache eviction."""

    def evict(self, artifact_id: ArtifactId) -> ContentDigest: ...


class BenchmarkTargetFactory(Protocol):
    """Spawn-safe factory that validates and opens one exact target artifact."""

    def validate(self, spec: BenchmarkSpec, data_root: Path) -> None: ...

    def create(
        self,
        spec: BenchmarkSpec,
        data_root: Path,
        # Keep the attempt nonce input explicit in the create contract.
        attempt_nonce: ContentDigest,
        phase: BenchmarkExecutionPhase,
    ) -> BenchmarkTarget: ...


class _DigestSink(Protocol):
    def update(self, data: bytes | bytearray | memoryview, /) -> None: ...


# Keep the worker config contract and validation rules together.
@dataclass(frozen=True, slots=True)
class _WorkerConfig:
    data_root: str
    spec: BenchmarkSpec
    target_factory: BenchmarkTargetFactory
    # Declare attempt nonce explicitly in the worker config contract.
    attempt_nonce: ContentDigest
    phase: BenchmarkExecutionPhase


# Keep the worker observation contract and validation rules together.
@dataclass(frozen=True, slots=True)
class _WorkerObservation:
    process_id: int
    started_ns: int
    finished_ns: int
    # Declare result explicitly in the worker observation contract.
    result: BenchmarkWorkloadResult
    cpu_time_ns: int
    peak_total_rss_bytes: int
    peak_private_rss_bytes: int | None
    private_rss_basis: PrivateRssBasis
    # Declare minor faults explicitly in the worker observation contract.
    minor_faults: int
    major_faults: int
    block_input_operations: int
    block_output_operations: int
    swap_operations: int
    # Declare storage read bytes explicitly in the worker observation contract.
    storage_read_bytes: int | None
    storage_write_bytes: int | None
    io_counter_basis: IoCounterBasis
    profiler: tuple[ProfilerEntry, ...] = ()


# Keep the no intent strategy contract and validation rules together.
class _NoIntentStrategy:
    bundle_id = _NOOP_STRATEGY_BUNDLE_ID
    component_id = domain_digest("benchmark.noop-strategy-component.v1", {})

    def __init__(self, pool_id: PoolId = _DEFAULT_BENCHMARK_POOL_ID) -> None:
        self.pool_id = pool_id

    # Define no intent strategy on event as one focused operation with an explicit
    # boundary.
    def on_event(
        self,
        event: CanonicalEvent,
        context: StrategyContext,
    ) -> tuple[Intent, ...]:
        # Execute the no intent strategy on event workflow in explicit, reviewable steps.
        del event, context
        return ()

    def on_exact_primitive_swap(
        self,
        *,
        # Keep the event id input explicit in the on exact primitive swap contract.
        event_id: ContentDigest,
        decision_boundary_ordinal: int,
    ) -> tuple[Intent, ...]:
        # Execute the no intent strategy on exact primitive swap workflow in explicit,
        # reviewable steps.
        del event_id, decision_boundary_ordinal
        raise AssertionError("benchmark absent-pool sentinel unexpectedly matched replay data")

    def on_execution(
        self,
        notification: ExecutionNotification,
        # Keep the context input explicit in the on execution contract.
        context: StrategyContext,
    ) -> None:
        del notification, context


# Keep the unused execution model contract and validation rules together.
class _UnusedExecutionModel:
    bundle_id = _NOOP_EXECUTION_BUNDLE_ID

    def execute(
        self,
        intent: SwapExactInIntent,
        # Keep the venue state input explicit in the execute contract.
        venue_state: SimulationVenueState,
        *,
        boundary_ordinal: int,
        mode: ExecutionMode,
    ) -> ExecutionPlan:
        # Execute the unused execution model execute workflow in explicit, reviewable
        # steps.
        del intent, venue_state, boundary_ordinal, mode
        raise AssertionError("no-intent benchmark strategy must not execute an order")


# Keep the reject all risk contract and validation rules together.
class _RejectAllRisk:
    bundle_id = _NOOP_RISK_BUNDLE_ID

    def accept(self, intent: SwapExactInIntent, portfolio: PortfolioView) -> bool:
        # Execute the reject all risk accept workflow in explicit, reviewable steps.
        del intent, portfolio
        return False


class _BatchedReplayView:
    """Expose the verified pack through bounded row windows to the reference engine."""

    def __init__(self, source: NumpyMmapReplaySource, batch_rows: int, readahead: int) -> None:
        # Execute the batched replay view init workflow in explicit, reviewable steps.
        self._source = source
        self._batch_rows = batch_rows
        self._readahead = readahead

    @property
    def dataset_revision_id(self) -> DatasetRevisionId:
        # Return the completed batched replay view dataset revision id result without a
        # hidden fallback.
        return self._source.dataset_revision_id

    @property
    def logical_content_hash(self) -> LogicalContentHash:
        return self._source.logical_content_hash

    @property
    # Define batched replay view replay semantics id as one focused operation with an
    # explicit boundary.
    def replay_semantics_id(self) -> ContentDigest:
        return self._source.replay_semantics_id

    def boundaries(self) -> tuple[ReplayBoundary, ...]:
        return self._source.boundaries()

    def events(self) -> Iterator[CanonicalEvent]:
        # Execute the batched replay view events workflow in explicit, reviewable steps.
        count = self._source.event_count
        window_rows = self._batch_rows * self._readahead
        for window_start in range(0, count, window_rows):
            # Process range(0, count, window_rows) inside the bounded batched replay view
            # events loop.
            window_stop = min(count, window_start + window_rows)
            for batch_start in range(window_start, window_stop, self._batch_rows):
                # Process window start, window stop and batch rows inside the bounded
                # batched replay view events loop.
                batch_stop = min(window_stop, batch_start + self._batch_rows)
                for row in range(batch_start, batch_stop):
                    yield self._source.event_at(row)


class LocalReplayBenchmarkTargetFactory:
    """Exact ReplayPack target implementation reused by the complete harness."""

    def __init__(self, build_tools: PinnedCodeBundleSet | None = None) -> None:
        self._build_tools = build_tools or unit_replay_build_tools()

    def validate(self, spec: BenchmarkSpec, data_root: Path) -> None:
        # Execute the local replay benchmark target factory validate workflow in explicit,
        # reviewable steps.
        replay_pack_id = _validate_replay_spec(spec)
        self._build_tools.require_current(REPLAY_COMPILER_ROLE)
        self._build_tools.require_current(REPLAY_WRITER_ROLE)
        artifacts = LocalArtifactRepository(data_root)
        handle = artifacts.open_committed(ArtifactId(replay_pack_id.hex))
        # Keep expected failures inside the local replay benchmark target factory validate
        # error boundary.
        try:
            # Perform the protected local replay benchmark target factory validate
            # operation before explicit failure handling.
            if handle.descriptor.kind is not ArtifactKind.REPLAY_PACK:
                raise ValueError("ReplayPack benchmark target has another artifact kind")
        finally:
            handle.close()

    def create(
        # Keep the remaining create inputs visible at the local replay benchmark target
        # factory create boundary.
        self,
        spec: BenchmarkSpec,
        data_root: Path,
        attempt_nonce: ContentDigest,
        phase: BenchmarkExecutionPhase,
        # Keep the benchmark target input explicit in the create contract.
    ) -> BenchmarkTarget:
        # Execute the local replay benchmark target factory create workflow in explicit,
        # reviewable steps.
        del attempt_nonce, phase
        self.validate(spec, data_root)
        return _ReplayTarget(spec, data_root, self._build_tools)


# Keep the replay target contract and validation rules together.
class _ReplayTarget:
    def __init__(
        self,
        spec: BenchmarkSpec,
        data_root: Path,
        # Keep the build tools input explicit in the init contract.
        build_tools: PinnedCodeBundleSet,
    ) -> None:
        # Execute the replay target init workflow in explicit, reviewable steps.
        self._spec = spec
        artifacts = LocalArtifactRepository(data_root)
        self._source = NumpyMmapReplaySource(
            artifacts,
            ReplayPackId(spec.input_artifact_ids[0].hex),
            # Pass build tools explicitly so NumpyMmapReplaySource receives a reviewable
            # hex and input artifact ids input in replay target init.
            build_tools=build_tools,
        )
        if self._source.event_count <= 0:
            raise ValueError("benchmark ReplayPack must contain events")

    @property
    # Define replay target base event count as one focused operation with an explicit
    # boundary.
    def base_event_count(self) -> int:
        return self._source.event_count

    def execute_once(self) -> BenchmarkWorkloadResult:
        # Execute the replay target execute once workflow in explicit, reviewable steps.
        workload = self._spec.workload
        if workload is BenchmarkWorkload.REPLAY_PACK_SCAN:
            return self._scan()
        if workload is BenchmarkWorkload.REFERENCE_REDUCER:
            return self._reduce_reference()
        # Evaluate the complete replay target execute once workload, optimized reducer and
        # benchmark workload condition before guarded effects.
        if workload is BenchmarkWorkload.OPTIMIZED_REDUCER:
            return self._reduce_optimized()
        raise ValueError(
            "local ReplayPack benchmark supports scan, reference reducer and optimized reducer"
        )

    # Define replay target scan as one focused operation with an explicit boundary.
    def _scan(self) -> BenchmarkWorkloadResult:
        # Execute the replay target scan workflow in explicit, reviewable steps.
        import hashlib

        digest = hashlib.sha256(b"backtest/replay-scan-touch/v2\0")
        arrays = self._source.arrays()
        for path in sorted(arrays):
            # Process sorted(arrays) inside the bounded replay target scan loop.
            encoded_path = path.encode("utf-8")
            digest.update(len(encoded_path).to_bytes(2, "little"))
            digest.update(encoded_path)
            array = arrays[path]
            raw = memoryview(array).cast("B")
            # Assemble batch bytes once so the replay target scan workflow shares one
            # value.
            batch_bytes = max(1, self._spec.batch_rows * max(1, array.dtype.itemsize))
            _update_sequential(
                digest,
                raw,
                batch_bytes=batch_bytes,
                # Pass readahead explicitly so _update_sequential receives a reviewable
                # readahead and spec input in replay target scan.
                readahead=self._spec.readahead,
            )
            raw.release()
        digest.digest()
        return BenchmarkWorkloadResult(
            # Pass items processed explicitly so BenchmarkWorkloadResult receives a
            # reviewable base event count and hex input in replay target scan.
            items_processed=self.base_event_count,
            canonical_result_hash=ContentDigest(self._source.logical_content_hash.hex),
        )

    def _reduce_reference(self) -> BenchmarkWorkloadResult:
        # Execute the replay target reduce reference workflow in explicit, reviewable
        # steps.
        source = _BatchedReplayView(
            self._source,
            self._spec.batch_rows,
            self._spec.readahead,
        )
        # Assemble summary once so the replay target reduce reference workflow shares one
        # value.
        summary = ReferenceBacktestEngine().run(
            source=source,
            strategy=_NoIntentStrategy(),
            execution_model=_UnusedExecutionModel(),
            risk_policy=_RejectAllRisk(),
            # Keep the reference run config and exogenous replay ReferenceRunConfig step
            # visible while building summary.
            config=ReferenceRunConfig(
                execution_mode=ExecutionMode.EXOGENOUS_REPLAY,
                latency=SlotLatencyModel(),
                root_seed=0,
                initial_available={},
                # Keep the batch rows and readahead max step visible while building
                # summary.
                maximum_dynamic_items=max(
                    1_024,
                    self._spec.batch_rows * self._spec.readahead,
                ),
            ),
            # Complete run only after its exogenous replay and batch rows inputs are visible
            # in replay target reduce reference.
        )
        return BenchmarkWorkloadResult(
            items_processed=self.base_event_count,
            canonical_result_hash=summary.result_hash,
        )

    # Define replay target reduce optimized as one focused operation with an explicit
    # boundary.
    def _reduce_optimized(self) -> BenchmarkWorkloadResult:
        # Execute the replay target reduce optimized workflow in explicit, reviewable
        # steps.
        engine = NumpyMmapFirstSwapEngine(
            strategy_type=_NoIntentStrategy,
            execution_model_type=_UnusedExecutionModel,
            risk_policy_type=_RejectAllRisk,
        )
        # Assemble missing pool once so the replay target reduce optimized workflow shares
        # one value.
        missing_pool = _absent_pool_id(self._source)
        summary = engine.run(
            source=self._source,
            strategy=_NoIntentStrategy(missing_pool),
            execution_model=_UnusedExecutionModel(),
            # Keep the reject all risk _RejectAllRisk step visible while building summary.
            risk_policy=_RejectAllRisk(),
            config=ReferenceRunConfig(
                execution_mode=ExecutionMode.EXOGENOUS_REPLAY,
                latency=SlotLatencyModel(),
                root_seed=0,
                # Pass initial available explicitly so ReferenceRunConfig receives a
                # reviewable exogenous replay and batch rows input in replay target reduce
                # optimized.
                initial_available={},
                maximum_dynamic_items=max(
                    1_024,
                    self._spec.batch_rows * self._spec.readahead,
                ),
                # Complete ReferenceRunConfig only after its exogenous replay and batch rows
                # inputs are visible in replay target reduce optimized.
            ),
            physical_settings=EnginePhysicalSettings(
                reader_batch_rows=self._spec.batch_rows,
                reader_readahead=self._spec.readahead,
                threads=1,
                # Complete EnginePhysicalSettings only after its batch rows and spec inputs
                # are visible in replay target reduce optimized.
            ),
        )
        return BenchmarkWorkloadResult(
            items_processed=self.base_event_count,
            canonical_result_hash=summary.result_hash,
            # Complete BenchmarkWorkloadResult only after its base event count and result hash
            # inputs are visible in replay target reduce optimized.
        )


def _absent_pool_id(source: NumpyMmapReplaySource) -> PoolId:
    # Execute the absent pool id workflow in explicit, reviewable steps.
    value = "backtest-benchmark-absent-pool"
    while source.dictionary_code("venues", value) is not None:
        value += "-next"
    return PoolId(value)


class _CapacityTarget:
    """Repeat one independent exact base target without time-sharding state."""

    def __init__(self, target: BenchmarkTarget, capacity_days: int) -> None:
        # Execute the capacity target init workflow in explicit, reviewable steps.
        self._target = target
        self._capacity_days = capacity_days

    def execute_once(self) -> BenchmarkWorkloadResult:
        # Execute the capacity target execute once workflow in explicit, reviewable steps.
        if self._capacity_days == 1:
            return self._target.execute_once()
        daily = tuple(self._target.execute_once() for _ in range(self._capacity_days))
        if not daily or len({item.items_processed for item in daily}) != 1:
            raise RuntimeError("benchmark base target changed its item count across capacity days")
        # Return the completed capacity target execute once result without a hidden
        # fallback.
        return BenchmarkWorkloadResult(
            items_processed=sum(item.items_processed for item in daily),
            canonical_result_hash=domain_digest(
                "backtest.repeated-independent-benchmark-result.v1",
                {"daily_result_hashes": [item.canonical_result_hash.hex for item in daily]},
                # Complete domain_digest only after its v1 and daily result hashes inputs are
                # visible in capacity target execute once.
            ),
        )

    def close(self) -> None:
        # Execute the capacity target close workflow in explicit, reviewable steps.
        closer = getattr(self._target, "close", None)
        if closer is not None:
            closer()


_WORKER_TARGET: _CapacityTarget | None = None


def _initialize_worker(config: _WorkerConfig) -> None:
    # Execute the initialize worker workflow in explicit, reviewable steps.
    global _WORKER_TARGET
    apply_thread_limits(config.spec.native_threads_per_process)
    target = config.target_factory.create(
        config.spec,
        Path(config.data_root),
        # Pass config explicitly so create receives a reviewable spec and data root input
        # in initialize worker.
        config.attempt_nonce,
        config.phase,
    )
    _WORKER_TARGET = _CapacityTarget(target, config.spec.capacity_days)


def _close_worker_target() -> None:
    # Execute the close worker target workflow in explicit, reviewable steps.
    global _WORKER_TARGET
    target = _WORKER_TARGET
    _WORKER_TARGET = None
    if target is not None:
        target.close()


# Define execute worker as one focused operation with an explicit boundary.
def _execute_worker(
    release_at_ns: int,
    collect_profile: bool,
    close_after: bool,
) -> _WorkerObservation:
    # Execute the execute worker workflow in explicit, reviewable steps.
    target = _WORKER_TARGET
    if target is None:  # pragma: no cover - ProcessPoolExecutor contract
        raise RuntimeError("benchmark worker was not initialized")
    succeeded = False
    try:
        # Perform the protected execute worker operation before explicit failure handling.
        while (remaining := release_at_ns - time.perf_counter_ns()) > 0:
            time.sleep(min(remaining / 1_000_000_000, 0.005))
        gc.collect()
        before_usage = resource.getrusage(resource.RUSAGE_SELF)
        before_io = current_io_counters()
        # Assemble sampler once so the execute worker workflow shares one value.
        sampler = PeakPrivateRssSampler()
        profiler = cProfile.Profile() if collect_profile else None
        sampler.start()
        cpu_started = time.process_time_ns()
        started = time.perf_counter_ns()
        # Keep expected failures inside the execute worker error boundary.
        try:
            # Perform the protected execute worker operation before explicit failure
            # handling.
            result = (
                target.execute_once() if profiler is None else profiler.runcall(target.execute_once)
            )
            finished = time.perf_counter_ns()
            cpu_time = max(0, time.process_time_ns() - cpu_started)
        # Complete the required cleanup regardless of the protected outcome.
        finally:
            sampler.stop()
        after_io = current_io_counters()
        after_usage = resource.getrusage(resource.RUSAGE_SELF)
        read_bytes, write_bytes, io_basis = _io_delta(before_io, after_io)
        # Assemble observation once so the execute worker workflow shares one value.
        observation = _WorkerObservation(
            process_id=os.getpid(),
            started_ns=started,
            finished_ns=max(started + 1, finished),
            result=result,
            # Pass cpu time ns explicitly so _WorkerObservation receives a reviewable
            # getpid and peak bytes input in execute worker.
            cpu_time_ns=cpu_time,
            peak_total_rss_bytes=peak_total_rss_bytes(),
            peak_private_rss_bytes=sampler.peak_bytes,
            private_rss_basis=sampler.basis,
            minor_faults=max(0, after_usage.ru_minflt - before_usage.ru_minflt),
            # Keep the ru majflt and after usage max step visible while building
            # observation.
            major_faults=max(0, after_usage.ru_majflt - before_usage.ru_majflt),
            block_input_operations=max(0, after_usage.ru_inblock - before_usage.ru_inblock),
            block_output_operations=max(0, after_usage.ru_oublock - before_usage.ru_oublock),
            swap_operations=max(0, after_usage.ru_nswap - before_usage.ru_nswap),
            storage_read_bytes=read_bytes,
            # Pass storage write bytes explicitly so _WorkerObservation receives a
            # reviewable getpid and peak bytes input in execute worker.
            storage_write_bytes=write_bytes,
            io_counter_basis=io_basis,
            profiler=() if profiler is None else _profiler_entries(profiler),
        )
        succeeded = True
        # Return the completed execute worker result without a hidden fallback.
        return observation
    finally:
        # Handle the cleanup path after the protected execute worker operation.
        if close_after or not succeeded:
            _close_worker_target()


class LocalReplayBenchmarkRunner:
    """One shared spawn harness for exact 1/7/30-day independent targets."""

    def __init__(
        self,
        data_root: Path,
        *,
        private_memory_budget_mb: int,
        # Keep the physical cores input explicit in the init contract.
        physical_cores: int,
        max_processes_by_io: int,
        cold_cache_controller: VerifiedColdCacheController | None = None,
        build_tools: PinnedCodeBundleSet | None = None,
        target_factory: BenchmarkTargetFactory | None = None,
        capacity_provider: Callable[[], HostCapacity] | None = None,
        # Close the init signature after its explicit inputs.
    ) -> None:
        # Execute the local replay benchmark runner init workflow in explicit, reviewable
        # steps.
        self._data_root = data_root.resolve()
        self._capacity = HostCapacity(
            private_memory_mb=private_memory_budget_mb,
            physical_cores=physical_cores,
            max_processes_by_io=max_processes_by_io,
            # Complete HostCapacity only after its private memory budget mb and physical cores
            # inputs are visible in local replay benchmark runner init.
        )
        self._capacity_provider = capacity_provider
        self._cold_cache = cold_cache_controller
        if build_tools is not None and target_factory is not None:
            raise ValueError("build_tools belong to the default ReplayPack target factory")
        self._target_factory = target_factory or LocalReplayBenchmarkTargetFactory(build_tools)

    # Define local replay benchmark runner run as one focused operation with an explicit
    # boundary.
    def run(
        self,
        spec: BenchmarkSpec,
        attempt_nonce: ContentDigest = _DEFAULT_BENCHMARK_ATTEMPT_NONCE,
    ) -> BenchmarkReport:
        # Execute the local replay benchmark runner run workflow in explicit, reviewable
        # steps.
        self._target_factory.validate(spec, self._data_root)
        target_artifact_id = spec.input_artifact_ids[0]
        if spec.cache_condition is CacheCondition.EXTERNALLY_COLD and self._cold_cache is None:
            # Handle the local replay benchmark runner run cache condition, externally
            # cold and cold cache condition as a distinct block.
            raise UnsupportedCacheConditionError(
                "cold page-cache measurement is unavailable without verified external eviction"
            )
        profile_config = _worker_config(
            self._data_root,
            # Keep the spec replace step visible while building profile config.
            replace(spec, capacity_days=1),
            self._target_factory,
            attempt_nonce,
            BenchmarkExecutionPhase.PROFILE,
        )
        # Assemble profile once so the local replay benchmark runner run workflow shares
        # one value.
        profile = self._run_profile(profile_config)
        measured_private = profile.peak_private_rss_bytes
        rss_basis = profile.private_rss_basis
        if measured_private is None:
            # Handle the local replay benchmark runner run measured_private is None branch
            # as a distinct logical block.
            measured_private = profile.peak_total_rss_bytes
            rss_basis = PrivateRssBasis.TOTAL_RSS_CONSERVATIVE_FALLBACK
        demand_mb = max(1, (measured_private + 1024**2 - 1) // 1024**2)
        capacity = self._capacity if self._capacity_provider is None else self._capacity_provider()
        admitted = admitted_processes(
            capacity,
            # Keep the process demand and demand mb ProcessDemand step visible while
            # building admitted.
            ProcessDemand(
                private_memory_mb=demand_mb,
                native_threads=spec.native_threads_per_process,
            ),
            spec.process_count,
            # Complete admitted_processes only after its capacity and native threads per
            # process inputs are visible in local replay benchmark runner run.
        )
        if admitted != spec.process_count:
            # Handle the local replay benchmark runner run admitted != spec.process_count
            # branch as a distinct logical block.
            raise BenchmarkAdmissionError(
                f"requested {spec.process_count} processes but measured admission allows {admitted}"
            )

        worker_config = _worker_config(
            self._data_root,
            # Pass spec explicitly so _worker_config receives a reviewable data root and
            # target factory input in local replay benchmark runner run.
            spec,
            self._target_factory,
            attempt_nonce,
            BenchmarkExecutionPhase.MEASURED,
        )
        # Assemble context once so the local replay benchmark runner run workflow shares
        # one value.
        context = multiprocessing.get_context("spawn")
        samples: list[BenchmarkSample] = []
        with ProcessPoolExecutor(
            max_workers=spec.process_count,
            mp_context=context,
            # Pass initializer explicitly so ProcessPoolExecutor receives a reviewable
            # process count and spec input in local replay benchmark runner run.
            initializer=_initialize_worker,
            initargs=(worker_config,),
        ) as executor:
            # Keep process pool executor, process count and context active only for the
            # bounded local replay benchmark runner run operation.
            for _ in range(spec.warmup_iterations):
                # Process range(spec.warmup_iterations) inside the bounded local replay
                # benchmark runner run loop.
                self._round(
                    executor,
                    spec.process_count,
                    collect_profile=False,
                    close_after=False,
                    # Complete _round only after its process count and executor inputs are
                    # visible in local replay benchmark runner run.
                )
            for iteration in range(spec.measured_iterations):
                # Process range(spec.measured_iterations) inside the bounded local replay
                # benchmark runner run loop.
                evidence = self._evict_if_required(spec, target_artifact_id)
                observations = self._round(
                    executor,
                    spec.process_count,
                    collect_profile=False,
                    # Pass close after explicitly so _round receives a reviewable process
                    # count and measured iterations input in local replay benchmark runner
                    # run.
                    close_after=iteration == spec.measured_iterations - 1,
                )
                samples.append(_aggregate_sample(iteration, observations, evidence))
        return BenchmarkReport(
            spec=spec,
            # Include samples in the completed local replay benchmark runner run result.
            samples=tuple(samples),
            base_events_per_day=profile.result.items_processed,
            profiler_items_processed=profile.result.items_processed,
            profiler=profile.profiler,
            admission_private_rss_bytes_per_process=measured_private,
            # Pass admission private rss basis explicitly so BenchmarkReport receives a
            # reviewable items processed and result input in local replay benchmark runner
            # run.
            admission_private_rss_basis=rss_basis,
        )

    @staticmethod
    def _run_profile(config: _WorkerConfig) -> _WorkerObservation:
        # Execute the local replay benchmark runner run profile workflow in explicit,
        # reviewable steps.
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=1,
            mp_context=context,
            initializer=_initialize_worker,
            # Pass initargs explicitly so ProcessPoolExecutor receives a reviewable
            # context and initialize worker input in local replay benchmark runner run
            # profile.
            initargs=(config,),
        ) as executor:
            # Keep process pool executor, context and initialize worker active only for
            # the bounded local replay benchmark runner run profile operation.
            release = time.perf_counter_ns() + 20_000_000
            return executor.submit(_execute_worker, release, True, True).result()

    @staticmethod
    def _round(
        executor: ProcessPoolExecutor,
        # Keep the process count input explicit in the round contract.
        process_count: int,
        *,
        collect_profile: bool,
        close_after: bool,
    ) -> tuple[_WorkerObservation, ...]:
        # Execute the local replay benchmark runner round workflow in explicit, reviewable
        # steps.
        release = time.perf_counter_ns() + 20_000_000
        futures = tuple(
            executor.submit(_execute_worker, release, collect_profile, close_after)
            for _ in range(process_count)
        )
        # Assemble observations once so the local replay benchmark runner round workflow
        # shares one value.
        observations = tuple(future.result() for future in futures)
        if len({item.process_id for item in observations}) != process_count:
            raise RuntimeError("process pool did not execute the benchmark concurrently")
        return observations

    def _evict_if_required(
        # Keep the remaining evict if required inputs visible at the local replay
        # benchmark runner evict if required boundary.
        self,
        spec: BenchmarkSpec,
        target_artifact_id: ArtifactId,
    ) -> ContentDigest | None:
        # Execute the local replay benchmark runner evict if required workflow in
        # explicit, reviewable steps.
        if spec.cache_condition is not CacheCondition.EXTERNALLY_COLD:
            return None
        controller = self._cold_cache
        if controller is None:  # guarded before profiling
            raise AssertionError("cold-cache controller disappeared")
        return controller.evict(target_artifact_id)


# Compatibility name: there is one harness, not a second ReplayPack runner.
LocalExactBenchmarkRunner = LocalReplayBenchmarkRunner


class UnsupportedCacheConditionError(RuntimeError):
    """The harness cannot truthfully establish the requested cache state."""


def physical_core_count() -> int:
    # Execute the physical core count workflow in explicit, reviewable steps.
    if sys.platform.startswith("linux"):
        # Handle the physical core count sys.platform.startswith('linux') branch as a
        # distinct logical block.
        try:
            # Perform the protected physical core count operation before explicit failure
            # handling.
            pairs: set[tuple[str, str]] = set()
            physical = "0"
            core = "0"
            for line in Path("/proc/cpuinfo").read_text(encoding="ascii").splitlines():
                # Process splitlines, read text and ascii inside the bounded physical core
                # count loop.
                if not line.strip():
                    # Handle the physical core count not line.strip() branch as a distinct
                    # logical block.
                    pairs.add((physical, core))
                    physical = core = "0"
                    continue
                key, separator, value = line.partition(":")
                if not separator:
                    # Keep the continue step explicit within the physical core count
                    # workflow.
                    continue
                if key.strip() == "physical id":
                    physical = value.strip()
                # Handle the physical core count complement of key.strip() == 'physical
                # id' explicitly.
                elif key.strip() == "core id":
                    core = value.strip()
            if pairs:
                return len(pairs)
        except (OSError, UnicodeError):
            # Keep this explicitly supported no-op branch visible.
            pass
    if sys.platform == "darwin":
        # Handle the physical core count sys.platform == 'darwin' branch as a distinct
        # logical block.
        try:
            # Perform the protected physical core count operation before explicit failure
            # handling.
            import subprocess

            completed = subprocess.run(
                ("/usr/sbin/sysctl", "-n", "hw.physicalcpu"),
                check=True,
                capture_output=True,
                # Pass text explicitly so run receives a reviewable /usr/sbin/sysctl and
                # -n input in physical core count.
                text=True,
                timeout=1,
            )
            count = int(completed.stdout.strip())
            if count > 0:
                # Return the completed physical core count result without a hidden
                # fallback.
                return count
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    # Logical CPU count is not a safe substitute here: admission is explicitly
    # bounded by physical cores so SMT cannot silently double the worker count.
    # Unknown topology therefore fails closed to one process.
    return 1


def _worker_config(
    data_root: Path,
    spec: BenchmarkSpec,
    target_factory: BenchmarkTargetFactory,
    # Keep the attempt nonce input explicit in the worker config contract.
    attempt_nonce: ContentDigest,
    phase: BenchmarkExecutionPhase,
) -> _WorkerConfig:
    # Execute the worker config workflow in explicit, reviewable steps.
    return _WorkerConfig(
        data_root=os.fspath(data_root),
        spec=spec,
        target_factory=target_factory,
        attempt_nonce=attempt_nonce,
        # Pass phase explicitly so _WorkerConfig receives a reviewable fspath and data
        # root input in worker config.
        phase=phase,
    )


def _validate_replay_spec(spec: BenchmarkSpec) -> ReplayPackId:
    # Execute the validate replay spec workflow in explicit, reviewable steps.
    expected_bundle = {
        BenchmarkWorkload.REPLAY_PACK_SCAN: REPLAY_SCAN_BENCHMARK_BUNDLE_ID,
        BenchmarkWorkload.REFERENCE_REDUCER: REFERENCE_REDUCER_BENCHMARK_BUNDLE_ID,
        BenchmarkWorkload.OPTIMIZED_REDUCER: OPTIMIZED_REDUCER_BENCHMARK_BUNDLE_ID,
    }.get(spec.workload)
    # Guard this path with expected_bundle is None before applying effects.
    if expected_bundle is None:
        raise ValueError("unsupported ReplayPack benchmark workload")
    if spec.workload_bundle_id != expected_bundle:
        raise ValueError("benchmark workload bundle does not match the selected implementation")
    return ReplayPackId(spec.input_artifact_ids[0].hex)


# Define update sequential as one focused operation with an explicit boundary.
def _update_sequential(
    digest: _DigestSink,
    raw: memoryview,
    *,
    batch_bytes: int,
    # Keep the readahead input explicit in the update sequential contract.
    readahead: int,
) -> None:
    # Execute the update sequential workflow in explicit, reviewable steps.
    window_bytes = batch_bytes * readahead
    for window_start in range(0, len(raw), window_bytes):
        # Process range(0, len(raw), window_bytes) inside the bounded update sequential
        # loop.
        window_stop = min(len(raw), window_start + window_bytes)
        batches = tuple(
            raw[start : min(window_stop, start + batch_bytes)]
            for start in range(window_start, window_stop, batch_bytes)
        )
        # Traverse batches explicitly so each update sequential iteration remains
        # traceable.
        for batch in batches:
            # Process batches inside the bounded update sequential loop.
            digest.update(batch)
            batch.release()


def _io_delta(
    before: ProcessIoCounters,
    after: ProcessIoCounters,
    # Keep the tuple input explicit in the io delta contract.
) -> tuple[int | None, int | None, IoCounterBasis]:
    # Execute the io delta workflow in explicit, reviewable steps.
    if (
        before.basis is not after.basis
        or before.basis is IoCounterBasis.UNAVAILABLE
        or before.read_bytes is None
        or before.write_bytes is None
        # Keep after visible while evaluating the basis, unavailable and read bytes guard.
        or after.read_bytes is None
        or after.write_bytes is None
    ):
        return None, None, IoCounterBasis.UNAVAILABLE
    return (
        # Include max in the completed io delta result.
        max(0, after.read_bytes - before.read_bytes),
        max(0, after.write_bytes - before.write_bytes),
        after.basis,
    )


def _profiler_entries(profiler: cProfile.Profile) -> tuple[ProfilerEntry, ...]:
    # Execute the profiler entries workflow in explicit, reviewable steps.
    rows: list[ProfilerEntry] = []
    for entry in profiler.getstats():
        # Process profiler.getstats() inside the bounded profiler entries loop.
        code = entry.code
        if isinstance(code, CodeType):
            # Handle the profiler entries isinstance(code, CodeType) branch as a distinct
            # logical block.
            module = Path(code.co_filename).name
            function = code.co_name
            line = code.co_firstlineno
        else:
            # Handle the profiler entries complement of isinstance(code, CodeType)
            # explicitly.
            module = "builtins"
            function = str(code)
            line = 0
        rows.append(
            ProfilerEntry(
                # Pass module explicitly so ProfilerEntry receives a reviewable callcount
                # and reccallcount input in profiler entries.
                module=module,
                function=function,
                line=line,
                primitive_calls=max(0, entry.callcount - entry.reccallcount),
                total_calls=entry.callcount,
                # Pass self time ns explicitly to append for callcount and reccallcount.
                self_time_ns=max(0, round(entry.inlinetime * 1_000_000_000)),
                cumulative_time_ns=max(0, round(entry.totaltime * 1_000_000_000)),
            )
        )
    rows.sort(key=lambda item: (-item.cumulative_time_ns, item.module, item.line, item.function))
    # Return the completed profiler entries result without a hidden fallback.
    return tuple(rows[:12])


def _aggregate_sample(
    iteration: int,
    observations: tuple[_WorkerObservation, ...],
    cache_evidence_id: ContentDigest | None,
    # Keep the benchmark sample input explicit in the aggregate sample contract.
) -> BenchmarkSample:
    # Execute the aggregate sample workflow in explicit, reviewable steps.
    hashes = {item.result.canonical_result_hash for item in observations}
    counts = {item.result.items_processed for item in observations}
    if len(hashes) != 1 or len(counts) != 1:
        raise RuntimeError("independent benchmark workers produced different semantic results")
    private_values = tuple(item.peak_private_rss_bytes for item in observations)
    # Assemble private bases once so the aggregate sample workflow shares one value.
    private_bases = {item.private_rss_basis for item in observations}
    peak_private: int | None
    if len(private_bases) == 1 and all(value is not None for value in private_values):
        # Handle the aggregate sample private bases, value and private values condition as
        # a distinct block.
        peak_private = sum(value for value in private_values if value is not None)
        private_basis = next(iter(private_bases))
    else:
        # Handle the aggregate sample complement of private bases, value and private
        # values explicitly.
        peak_private = None
        private_basis = PrivateRssBasis.TOTAL_RSS_CONSERVATIVE_FALLBACK
    io_bases = {item.io_counter_basis for item in observations}
    read_bytes: int | None
    write_bytes: int | None
    # Evaluate the complete aggregate sample unavailable, io bases and io counter basis
    # condition before guarded effects.
    if (
        len(io_bases) == 1
        and IoCounterBasis.UNAVAILABLE not in io_bases
        and all(item.storage_read_bytes is not None for item in observations)
        and all(item.storage_write_bytes is not None for item in observations)
        # Evaluate the complete aggregate sample unavailable, io bases and io counter basis
        # condition before guarded effects.
    ):
        # Handle the aggregate sample unavailable, io bases and io counter basis condition
        # as a distinct block.
        read_bytes = sum(item.storage_read_bytes or 0 for item in observations)
        write_bytes = sum(item.storage_write_bytes or 0 for item in observations)
        io_basis = next(iter(io_bases))
    else:
        # Handle the aggregate sample complement of unavailable, io bases and io counter
        # basis explicitly.
        read_bytes = write_bytes = None
        io_basis = IoCounterBasis.UNAVAILABLE
    worker_hash = next(iter(hashes))
    worker_ids = tuple(sorted(item.process_id for item in observations))
    return BenchmarkSample(
        # Pass iteration explicitly so BenchmarkSample receives a reviewable items
        # processed and result input in aggregate sample.
        iteration=iteration,
        items_processed=sum(item.result.items_processed for item in observations),
        wall_time_ns=max(item.finished_ns for item in observations)
        - min(item.started_ns for item in observations),
        cpu_time_ns=sum(item.cpu_time_ns for item in observations),
        # Include peak rss bytes in the completed aggregate sample result.
        peak_rss_bytes=sum(item.peak_total_rss_bytes for item in observations),
        minor_faults=sum(item.minor_faults for item in observations),
        major_faults=sum(item.major_faults for item in observations),
        block_input_operations=sum(item.block_input_operations for item in observations),
        block_output_operations=sum(item.block_output_operations for item in observations),
        # Include swap operations in the completed aggregate sample result.
        swap_operations=sum(item.swap_operations for item in observations),
        # Process count is physical provenance, not a semantic result input.
        canonical_result_hash=worker_hash,
        peak_private_rss_bytes=peak_private,
        private_rss_basis=private_basis,
        storage_read_bytes=read_bytes,
        storage_write_bytes=write_bytes,
        # Pass io counter basis explicitly so BenchmarkSample receives a reviewable items
        # processed and result input in aggregate sample.
        io_counter_basis=io_basis,
        worker_process_ids=worker_ids,
        cache_evidence_id=cache_evidence_id,
    )


__all__ = [
    # Keep the optimized reducer benchmark bundle id component named inside the all
    # contract.
    "OPTIMIZED_REDUCER_BENCHMARK_BUNDLE_ID",
    "REFERENCE_REDUCER_BENCHMARK_BUNDLE_ID",
    "REPLAY_SCAN_BENCHMARK_BUNDLE_ID",
    "BenchmarkAdmissionError",
    "BenchmarkTargetFactory",
    # Keep the local exact benchmark runner component named inside the all contract.
    "LocalExactBenchmarkRunner",
    "LocalReplayBenchmarkRunner",
    "LocalReplayBenchmarkTargetFactory",
    "UnsupportedCacheConditionError",
    "VerifiedColdCacheController",
    # Keep the physical core count component named inside the all contract.
    "physical_core_count",
]
