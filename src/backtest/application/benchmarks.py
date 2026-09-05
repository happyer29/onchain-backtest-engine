"""Typed, reproducible performance measurements without invented targets."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum

from backtest.application.models import ArtifactKind, CommittedArtifact

# Import hashing at the visible module dependency boundary.
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.domain.identifiers import (
    ArtifactId,
    BundleId,
    ContentDigest,
    # Include replay pack id so the identifiers dependency remains explicit.
    ReplayPackId,
    RuntimeLockId,
)

MAX_BENCHMARK_WARMUP_ITERATIONS = 10
MAX_BENCHMARK_MEASURED_ITERATIONS = 100


# Keep the cache condition contract and validation rules together.
class CacheCondition(StrEnum):
    WARM = "WARM"
    UNCONTROLLED = "UNCONTROLLED"
    EXTERNALLY_COLD = "EXTERNALLY_COLD"


class CapacityModel(StrEnum):
    """How the one-day base stream is scaled without claiming stateful history."""

    REPEATED_INDEPENDENT_BASE_STREAM = "REPEATED_INDEPENDENT_BASE_STREAM"


class PrivateRssBasis(StrEnum):
    """How a sample's private-memory counter was obtained."""

    LINUX_SMAPS_ROLLUP = "LINUX_SMAPS_ROLLUP"
    DARWIN_PHYSICAL_FOOTPRINT = "DARWIN_PHYSICAL_FOOTPRINT"
    TOTAL_RSS_CONSERVATIVE_FALLBACK = "TOTAL_RSS_CONSERVATIVE_FALLBACK"


class IoCounterBasis(StrEnum):
    """How factual process I/O byte counters were obtained."""

    LINUX_PROC_IO = "LINUX_PROC_IO"
    DARWIN_PROC_PID_RUSAGE = "DARWIN_PROC_PID_RUSAGE"
    UNAVAILABLE = "UNAVAILABLE"


# Keep the benchmark workload contract and validation rules together.
class BenchmarkWorkload(StrEnum):
    PARQUET_SCAN = "PARQUET_SCAN"
    REPLAY_PACK_SCAN = "REPLAY_PACK_SCAN"
    REFERENCE_REDUCER = "REFERENCE_REDUCER"
    OPTIMIZED_REDUCER = "OPTIMIZED_REDUCER"
    # Declare full backtest explicitly in the benchmark workload contract.
    FULL_BACKTEST = "FULL_BACKTEST"
    EMBEDDED_INFERENCE = "EMBEDDED_INFERENCE"
    FROZEN_INFERENCE = "FROZEN_INFERENCE"
    CONTROL_PLANE_ROUND_TRIP = "CONTROL_PLANE_ROUND_TRIP"


class BenchmarkLaunchRoute(StrEnum):
    """Exact execution route measured by one benchmark target."""

    LOCAL_ARTIFACT = "LOCAL_ARTIFACT"
    DIRECT = "DIRECT"
    CONTROL = "CONTROL"


# Keep the benchmark execution phase contract and validation rules together.
class BenchmarkExecutionPhase(StrEnum):
    PROFILE = "PROFILE"
    MEASURED = "MEASURED"


# Keep the replay benchmark workload contract and validation rules together.
class ReplayBenchmarkWorkload(StrEnum):
    REPLAY_PACK_SCAN = "REPLAY_PACK_SCAN"
    REFERENCE_REDUCER = "REFERENCE_REDUCER"
    OPTIMIZED_REDUCER = "OPTIMIZED_REDUCER"


# Keep the replay benchmark command contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ReplayBenchmarkCommand:
    replay_pack_id: ReplayPackId
    workload: ReplayBenchmarkWorkload
    cache_condition: CacheCondition
    # Declare batch rows explicitly in the replay benchmark command contract.
    batch_rows: int
    readahead: int
    process_count: int
    native_threads_per_process: int
    warmup_iterations: int
    # Declare measured iterations explicitly in the replay benchmark command contract.
    measured_iterations: int
    capacity_days: int
    attempt_nonce: ContentDigest

    def __post_init__(self) -> None:
        # Reuse the exact grid validation without inventing a second transport policy.
        BenchmarkSpec(
            workload=BenchmarkWorkload(self.workload.value),
            input_artifact_ids=(ArtifactId(self.replay_pack_id.hex),),
            workload_bundle_id=BundleId("0" * 64),
            runtime_lock_id=RuntimeLockId("0" * 64),
            # Pass cache condition explicitly so BenchmarkSpec receives a reviewable 0 and
            # value input in replay benchmark command post init.
            cache_condition=self.cache_condition,
            batch_rows=self.batch_rows,
            readahead=self.readahead,
            process_count=self.process_count,
            native_threads_per_process=self.native_threads_per_process,
            # Pass warmup iterations explicitly so BenchmarkSpec receives a reviewable 0
            # and value input in replay benchmark command post init.
            warmup_iterations=self.warmup_iterations,
            measured_iterations=self.measured_iterations,
            capacity_days=self.capacity_days,
            launch_route=BenchmarkLaunchRoute.LOCAL_ARTIFACT,
        )


# Apply dataclass semantics to the following exact benchmark command contract.
@dataclass(frozen=True, slots=True)
class ExactBenchmarkCommand:
    """Versioned public command selecting one exact committed target artifact."""

    target_artifact_id: ArtifactId
    workload: BenchmarkWorkload
    launch_route: BenchmarkLaunchRoute
    cache_condition: CacheCondition
    batch_rows: int
    # Declare readahead explicitly in the exact benchmark command contract.
    readahead: int
    process_count: int
    native_threads_per_process: int
    warmup_iterations: int
    measured_iterations: int
    # Declare capacity days explicitly in the exact benchmark command contract.
    capacity_days: int
    attempt_nonce: ContentDigest

    def __post_init__(self) -> None:
        # Execute the exact benchmark command post init workflow in explicit, reviewable
        # steps.
        BenchmarkSpec(
            workload=self.workload,
            input_artifact_ids=(self.target_artifact_id,),
            workload_bundle_id=BundleId("0" * 64),
            runtime_lock_id=RuntimeLockId("0" * 64),
            # Pass cache condition explicitly so BenchmarkSpec receives a reviewable 0 and
            # workload input in exact benchmark command post init.
            cache_condition=self.cache_condition,
            batch_rows=self.batch_rows,
            readahead=self.readahead,
            process_count=self.process_count,
            native_threads_per_process=self.native_threads_per_process,
            # Pass warmup iterations explicitly so BenchmarkSpec receives a reviewable 0
            # and workload input in exact benchmark command post init.
            warmup_iterations=self.warmup_iterations,
            measured_iterations=self.measured_iterations,
            capacity_days=self.capacity_days,
            launch_route=self.launch_route,
        )

    # Define exact benchmark command document as one focused operation with an explicit
    # boundary.
    def document(self) -> dict[str, object]:
        # Execute the exact benchmark command document workflow in explicit, reviewable
        # steps.
        return {
            "attempt_nonce": self.attempt_nonce.hex,
            "batch_rows": self.batch_rows,
            "cache_condition": self.cache_condition.value,
            "capacity_days": self.capacity_days,
            # Include launch route in the completed exact benchmark command document
            # result.
            "launch_route": self.launch_route.value,
            "measured_iterations": self.measured_iterations,
            "native_threads_per_process": self.native_threads_per_process,
            "process_count": self.process_count,
            "readahead": self.readahead,
            # Include schema in the completed exact benchmark command document result.
            "schema": "backtest.exact-benchmark-command.v1",
            "target_artifact_id": self.target_artifact_id.hex,
            "warmup_iterations": self.warmup_iterations,
            "workload": self.workload.value,
        }

    # Define exact benchmark command canonical bytes as one focused operation with an
    # explicit boundary.
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.document())


# Keep the benchmark spec contract and validation rules together.
@dataclass(frozen=True, slots=True)
class BenchmarkSpec:
    workload: BenchmarkWorkload
    input_artifact_ids: tuple[ArtifactId, ...]
    workload_bundle_id: BundleId
    # Declare runtime lock id explicitly in the benchmark spec contract.
    runtime_lock_id: RuntimeLockId
    cache_condition: CacheCondition
    batch_rows: int
    readahead: int
    process_count: int
    # Declare native threads per process explicitly in the benchmark spec contract.
    native_threads_per_process: int
    warmup_iterations: int = 1
    measured_iterations: int = 5
    capacity_days: int = 1
    capacity_model: CapacityModel = CapacityModel.REPEATED_INDEPENDENT_BASE_STREAM
    # Declare launch route explicitly in the benchmark spec contract.
    launch_route: BenchmarkLaunchRoute = BenchmarkLaunchRoute.LOCAL_ARTIFACT
    semantic_equivalence_id: ContentDigest | None = None

    def __post_init__(self) -> None:
        # Execute the benchmark spec post init workflow in explicit, reviewable steps.
        if tuple(sorted(self.input_artifact_ids, key=lambda item: item.hex)) != (
            self.input_artifact_ids
        ) or len(self.input_artifact_ids) != len(set(self.input_artifact_ids)):
            raise ValueError("benchmark inputs must be sorted and unique")
        if len(self.input_artifact_ids) != 1:
            # Fail the benchmark spec post init path with ValueError for benchmark
            # requires exactly one committed target artifact when input artifact ids is
            # true; do not continue ambiguously.
            raise ValueError("benchmark requires exactly one committed target artifact")
        for field in (
            "batch_rows",
            "readahead",
            "process_count",
            # Traverse batch rows, readahead and process count explicitly so each
            # benchmark spec post init iteration remains traceable.
            "native_threads_per_process",
            "measured_iterations",
        ):
            # Process batch rows, readahead and process count inside the bounded benchmark
            # spec post init loop.
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field} must be a positive integer")
        if (
            isinstance(self.warmup_iterations, bool)
            # Keep isinstance visible while evaluating the isinstance, warmup iterations
            # and max benchmark warmup iterations guard.
            or not isinstance(self.warmup_iterations, int)
            or not 0 <= self.warmup_iterations <= MAX_BENCHMARK_WARMUP_ITERATIONS
        ):
            # Handle the benchmark spec post init isinstance, warmup iterations and max
            # benchmark warmup iterations condition as a distinct block.
            raise ValueError(
                f"warmup_iterations must be between 0 and {MAX_BENCHMARK_WARMUP_ITERATIONS}"
            )
        if self.measured_iterations > MAX_BENCHMARK_MEASURED_ITERATIONS:
            # Handle the benchmark spec post init measured iterations and max benchmark
            # measured iterations condition as a distinct block.
            raise ValueError(
                f"measured_iterations must not exceed {MAX_BENCHMARK_MEASURED_ITERATIONS}"
            )
        if (
            isinstance(self.capacity_days, bool)
            # Keep isinstance visible while evaluating the isinstance and capacity days
            # guard.
            or not isinstance(self.capacity_days, int)
            or self.capacity_days not in {1, 7, 30}
        ):
            raise ValueError("capacity_days must be one of 1, 7 or 30")
        if self.batch_rows not in {32_768, 65_536, 131_072, 262_144}:
            # Fail the benchmark spec post init path with ValueError for batch rows must
            # be one of the normative benchmark candidates when batch rows is true; do not
            # continue ambiguously.
            raise ValueError("batch_rows must be one of the normative benchmark candidates")
        if self.readahead not in {1, 2, 4}:
            raise ValueError("readahead must be one of 1, 2 or 4")
        if self.process_count not in {1, 2, 4}:
            raise ValueError("process_count must be one of 1, 2 or 4")
        # Evaluate the complete benchmark spec post init workload, control plane round
        # trip and benchmark workload condition before guarded effects.
        if self.workload is BenchmarkWorkload.CONTROL_PLANE_ROUND_TRIP:
            # Handle the benchmark spec post init workload, control plane round trip and
            # benchmark workload condition as a distinct block.
            if self.launch_route not in {
                BenchmarkLaunchRoute.DIRECT,
                BenchmarkLaunchRoute.CONTROL,
            }:
                raise ValueError("control-plane benchmark requires DIRECT or CONTROL route")
            # Guard this path with self.process_count != 1 before applying effects.
            if self.process_count != 1:
                raise ValueError("one local controller benchmark requires process_count=1")
        # Handle the benchmark spec post init complement of workload, control plane round
        # trip and benchmark workload explicitly.
        elif self.launch_route is not BenchmarkLaunchRoute.LOCAL_ARTIFACT:
            raise ValueError("non-control benchmark requires LOCAL_ARTIFACT route")

    @property
    def benchmark_spec_id(self) -> ContentDigest:
        # Execute the benchmark spec benchmark spec id workflow in explicit, reviewable
        # steps.
        return domain_digest(
            "backtest.benchmark-spec.v1",
            {
                "batch_rows": self.batch_rows,
                "cache_condition": self.cache_condition.value,
                # Keep capacity days named so the v1 and batch rows payload passed to
                # domain_digest remains self-describing within benchmark spec benchmark
                # spec id.
                "capacity_days": self.capacity_days,
                "capacity_model": self.capacity_model.value,
                "input_artifact_ids": [item.hex for item in self.input_artifact_ids],
                "launch_route": self.launch_route.value,
                "measured_iterations": self.measured_iterations,
                # Keep native threads per process named so the v1 and batch rows payload
                # passed to domain_digest remains self-describing within benchmark spec
                # benchmark spec id.
                "native_threads_per_process": self.native_threads_per_process,
                "process_count": self.process_count,
                "readahead": self.readahead,
                "runtime_lock_id": self.runtime_lock_id.hex,
                "semantic_equivalence_id": (
                    # Keep domain digest, v1 and batch rows visible while completing
                    # domain_digest within benchmark spec benchmark spec id.
                    None
                    if self.semantic_equivalence_id is None
                    else self.semantic_equivalence_id.hex
                ),
                "warmup_iterations": self.warmup_iterations,
                # Keep workload named so the v1 and batch rows payload passed to
                # domain_digest remains self-describing within benchmark spec benchmark
                # spec id.
                "workload": self.workload.value,
                "workload_bundle_id": self.workload_bundle_id.hex,
            },
        )


# Keep the benchmark workload result contract and validation rules together.
@dataclass(frozen=True, slots=True)
class BenchmarkWorkloadResult:
    items_processed: int
    canonical_result_hash: ContentDigest

    def __post_init__(self) -> None:
        # Execute the benchmark workload result post init workflow in explicit, reviewable
        # steps.
        if self.items_processed < 0:
            raise ValueError("items_processed must be non-negative")


@dataclass(frozen=True, slots=True)
class ControlPlaneBenchmarkInvocation:
    """Collision-free operational identity for one real control route call."""

    outer_attempt_nonce: ContentDigest
    phase: BenchmarkExecutionPhase
    invocation_ordinal: int

    def __post_init__(self) -> None:
        # Execute the control plane benchmark invocation post init workflow in explicit,
        # reviewable steps.
        if (
            isinstance(self.invocation_ordinal, bool)
            or not isinstance(self.invocation_ordinal, int)
            or self.invocation_ordinal < 0
        ):
            # Fail the control plane benchmark invocation post init path with ValueError
            # for benchmark invocation ordinal must be non-negative when isinstance and
            # invocation ordinal is true; do not continue ambiguously.
            raise ValueError("benchmark invocation ordinal must be non-negative")

    @property
    def invocation_id(self) -> ContentDigest:
        # Execute the control plane benchmark invocation invocation id workflow in
        # explicit, reviewable steps.
        return domain_digest(
            "backtest.control-plane-benchmark-invocation.v1",
            {
                "invocation_ordinal": self.invocation_ordinal,
                "outer_attempt_nonce": self.outer_attempt_nonce.hex,
                # Keep phase named so the v1 and invocation ordinal payload passed to
                # domain_digest remains self-describing within control plane benchmark
                # invocation invocation id.
                "phase": self.phase.value,
            },
        )


# Keep the benchmark sample contract and validation rules together.
@dataclass(frozen=True, slots=True)
class BenchmarkSample:
    iteration: int
    items_processed: int
    wall_time_ns: int
    # Declare cpu time ns explicitly in the benchmark sample contract.
    cpu_time_ns: int
    peak_rss_bytes: int
    minor_faults: int
    major_faults: int
    block_input_operations: int
    # Declare block output operations explicitly in the benchmark sample contract.
    block_output_operations: int
    canonical_result_hash: ContentDigest
    swap_operations: int = 0
    peak_private_rss_bytes: int | None = None
    private_rss_basis: PrivateRssBasis = PrivateRssBasis.TOTAL_RSS_CONSERVATIVE_FALLBACK
    # Declare storage read bytes explicitly in the benchmark sample contract.
    storage_read_bytes: int | None = None
    storage_write_bytes: int | None = None
    io_counter_basis: IoCounterBasis = IoCounterBasis.UNAVAILABLE
    worker_process_ids: tuple[int, ...] = ()
    cache_evidence_id: ContentDigest | None = None

    # Define benchmark sample post init as one focused operation with an explicit
    # boundary.
    def __post_init__(self) -> None:
        # Execute the benchmark sample post init workflow in explicit, reviewable steps.
        values = (
            self.iteration,
            self.items_processed,
            self.wall_time_ns,
            self.cpu_time_ns,
            # Keep the self component named inside the values contract.
            self.peak_rss_bytes,
            self.minor_faults,
            self.major_faults,
            self.block_input_operations,
            self.block_output_operations,
            # Keep the self component named inside the values contract.
            self.swap_operations,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values
        ):
            # Fail the benchmark sample post init path with ValueError for benchmark
            # counters must be non-negative integers when value, values and isinstance is
            # true; do not continue ambiguously.
            raise ValueError("benchmark counters must be non-negative integers")
        if self.wall_time_ns == 0:
            raise ValueError("wall_time_ns must be positive")
        for name in ("peak_private_rss_bytes", "storage_read_bytes", "storage_write_bytes"):
            # Process peak private rss bytes, storage read bytes and storage write bytes
            # inside the bounded benchmark sample post init loop.
            optional_value = getattr(self, name)
            if optional_value is not None and (
                isinstance(optional_value, bool)
                or not isinstance(optional_value, int)
                or optional_value < 0
                # Evaluate the complete benchmark sample post init optional value and
                # isinstance condition before guarded effects.
            ):
                raise ValueError(f"{name} must be a non-negative integer or None")
        if (
            self.private_rss_basis is not PrivateRssBasis.TOTAL_RSS_CONSERVATIVE_FALLBACK
            and self.peak_private_rss_bytes is None
            # Evaluate the complete benchmark sample post init private rss basis, total rss
            # conservative fallback and peak private rss bytes condition before guarded
            # effects.
        ):
            raise ValueError("a measured private RSS basis requires a private RSS value")
        if self.io_counter_basis is IoCounterBasis.UNAVAILABLE:
            # Handle the benchmark sample post init io counter basis and unavailable
            # condition as a distinct block.
            if self.storage_read_bytes is not None or self.storage_write_bytes is not None:
                raise ValueError("unavailable I/O counters cannot carry byte values")
        # Handle the benchmark sample post init complement of io counter basis and
        # unavailable explicitly.
        elif self.storage_read_bytes is None or self.storage_write_bytes is None:
            raise ValueError("an available I/O basis requires both byte counters")
        if self.worker_process_ids and (
            tuple(sorted(self.worker_process_ids)) != self.worker_process_ids
            or len(set(self.worker_process_ids)) != len(self.worker_process_ids)
            # Keep any visible while evaluating the worker process ids, sorted and value
            # guard.
            or any(value <= 0 for value in self.worker_process_ids)
        ):
            raise ValueError("worker_process_ids must be sorted, positive and unique")

    @property
    def items_per_second(self) -> int:
        # Return the completed benchmark sample items per second result without a hidden
        # fallback.
        return self.items_processed * 1_000_000_000 // self.wall_time_ns

    def document(self) -> dict[str, object]:
        # Execute the benchmark sample document workflow in explicit, reviewable steps.
        return {
            "block_input_operations": self.block_input_operations,
            "block_output_operations": self.block_output_operations,
            "cache_evidence_id": (
                None if self.cache_evidence_id is None else self.cache_evidence_id.hex
                # Return the completed benchmark sample document result without a hidden
                # fallback.
            ),
            "canonical_result_hash": self.canonical_result_hash.hex,
            "cpu_time_ns": self.cpu_time_ns,
            "items_per_second": self.items_per_second,
            "items_processed": self.items_processed,
            # Include iteration in the completed benchmark sample document result.
            "iteration": self.iteration,
            "major_faults": self.major_faults,
            "minor_faults": self.minor_faults,
            "io_counter_basis": self.io_counter_basis.value,
            "peak_rss_bytes": self.peak_rss_bytes,
            # Include peak private rss bytes in the completed benchmark sample document
            # result.
            "peak_private_rss_bytes": self.peak_private_rss_bytes,
            "private_rss_basis": self.private_rss_basis.value,
            "storage_read_bytes": self.storage_read_bytes,
            "storage_write_bytes": self.storage_write_bytes,
            "swap_operations": self.swap_operations,
            # Include wall time ns in the completed benchmark sample document result.
            "wall_time_ns": self.wall_time_ns,
            "worker_process_ids": list(self.worker_process_ids),
        }


# Keep the profiler entry contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ProfilerEntry:
    module: str
    function: str
    line: int
    # Declare primitive calls explicitly in the profiler entry contract.
    primitive_calls: int
    total_calls: int
    self_time_ns: int
    cumulative_time_ns: int

    def __post_init__(self) -> None:
        # Execute the profiler entry post init workflow in explicit, reviewable steps.
        if not self.module or not self.function:
            raise ValueError("profiler function identity must be non-empty")
        counters = (
            self.line,
            self.primitive_calls,
            # Keep the self component named inside the counters contract.
            self.total_calls,
            self.self_time_ns,
            self.cumulative_time_ns,
        )
        if any(
            # Keep isinstance visible while evaluating the value, counters and isinstance
            # guard.
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in counters
        ):
            raise ValueError("profiler counters must be non-negative integers")

    def document(self) -> dict[str, object]:
        # Execute the profiler entry document workflow in explicit, reviewable steps.
        return {
            "cumulative_time_ns": self.cumulative_time_ns,
            "function": self.function,
            "line": self.line,
            "module": self.module,
            # Include primitive calls in the completed profiler entry document result.
            "primitive_calls": self.primitive_calls,
            "self_time_ns": self.self_time_ns,
            "total_calls": self.total_calls,
        }


# Keep the benchmark report contract and validation rules together.
@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    spec: BenchmarkSpec
    samples: tuple[BenchmarkSample, ...]
    base_events_per_day: int | None = None
    # Declare profiler items processed explicitly in the benchmark report contract.
    profiler_items_processed: int | None = None
    profiler: tuple[ProfilerEntry, ...] = ()
    admission_private_rss_bytes_per_process: int | None = None
    admission_private_rss_basis: PrivateRssBasis | None = None

    def __post_init__(self) -> None:
        # Execute the benchmark report post init workflow in explicit, reviewable steps.
        if len(self.samples) != self.spec.measured_iterations:
            raise ValueError("sample count differs from measured_iterations")
        if tuple(item.iteration for item in self.samples) != tuple(range(len(self.samples))):
            raise ValueError("benchmark sample ordinals must be contiguous")
        hashes = {item.canonical_result_hash for item in self.samples}
        # Assemble counts once so the benchmark report post init workflow shares one
        # value.
        counts = {item.items_processed for item in self.samples}
        if len(hashes) != 1 or len(counts) != 1:
            raise ValueError("benchmark workload changed its semantic result between iterations")
        for name in (
            "base_events_per_day",
            # Traverse base events per day, profiler items processed and admission private
            # rss bytes per process explicitly so each benchmark report post init
            # iteration remains traceable.
            "profiler_items_processed",
            "admission_private_rss_bytes_per_process",
        ):
            # Process base events per day, profiler items processed and admission private
            # rss bytes per process inside the bounded benchmark report post init loop.
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
            ):
                raise ValueError(f"{name} must be a positive integer or None")
        # Evaluate the complete benchmark report post init admission private rss bytes per
        # process and admission private rss basis condition before guarded effects.
        if (self.admission_private_rss_bytes_per_process is None) != (
            self.admission_private_rss_basis is None
        ):
            raise ValueError("admission RSS value and basis must be present together")
        if self.base_events_per_day is not None:
            # Handle the benchmark report post init self.base_events_per_day is not None
            # branch as a distinct logical block.
            expected = self.base_events_per_day * self.spec.capacity_days * self.spec.process_count
            if self.samples and self.samples[0].items_processed != expected:
                raise ValueError("measured items differ from the declared capacity profile")
        if self.spec.cache_condition is CacheCondition.EXTERNALLY_COLD:
            # Handle the benchmark report post init cache condition, externally cold and
            # spec condition as a distinct block.
            if any(item.cache_evidence_id is None for item in self.samples):
                raise ValueError("cold-cache samples require external eviction evidence")
        # Handle the benchmark report post init complement of cache condition, externally
        # cold and spec explicitly.
        elif any(item.cache_evidence_id is not None for item in self.samples):
            raise ValueError("cache eviction evidence is only valid for externally cold samples")

    @property
    def canonical_result_hash(self) -> ContentDigest:
        return self.samples[0].canonical_result_hash

    # Apply property semantics to the following benchmark report median items per second
    # contract.
    @property
    def median_items_per_second(self) -> int:
        return _percentile(tuple(item.items_per_second for item in self.samples), 50)

    @property
    def p95_wall_time_ns(self) -> int:
        # Return the completed benchmark report p95 wall time ns result without a hidden
        # fallback.
        return _percentile(tuple(item.wall_time_ns for item in self.samples), 95)

    @property
    def report_digest(self) -> ContentDigest:
        # Execute the benchmark report report digest workflow in explicit, reviewable
        # steps.
        return domain_digest(
            "backtest.benchmark-report.v1",
            {
                "benchmark_spec_id": self.spec.benchmark_spec_id.hex,
                "admission_private_rss_basis": (
                    # Keep domain digest, v1 and benchmark spec id visible while
                    # completing domain_digest within benchmark report report digest.
                    None
                    if self.admission_private_rss_basis is None
                    else self.admission_private_rss_basis.value
                ),
                "admission_private_rss_bytes_per_process": (
                    # Pass self explicitly so domain_digest receives a reviewable v1 and
                    # benchmark spec id input in benchmark report report digest.
                    self.admission_private_rss_bytes_per_process
                ),
                "base_events_per_day": self.base_events_per_day,
                "profiler": [item.document() for item in self.profiler],
                "profiler_items_processed": self.profiler_items_processed,
                # Include samples in the completed benchmark report report digest result.
                "samples": [item.document() for item in self.samples],
            },
        )

    def document(self) -> dict[str, object]:
        # Execute the benchmark report document workflow in explicit, reviewable steps.
        return {
            "admission": {
                "private_rss_basis": (
                    None
                    if self.admission_private_rss_basis is None
                    # Route all remaining cases through the explicit alternative branch.
                    else self.admission_private_rss_basis.value
                ),
                "private_rss_bytes_per_process": self.admission_private_rss_bytes_per_process,
            },
            "base_events_per_day": self.base_events_per_day,
            # Include benchmark spec in the completed benchmark report document result.
            "benchmark_spec": benchmark_spec_document(self.spec),
            "benchmark_spec_id": self.spec.benchmark_spec_id.hex,
            "canonical_result_hash": self.canonical_result_hash.hex,
            "median_items_per_second": self.median_items_per_second,
            "p95_wall_time_ns": self.p95_wall_time_ns,
            # Include profiler in the completed benchmark report document result.
            "profiler": [item.document() for item in self.profiler],
            "profiler_items_processed": self.profiler_items_processed,
            "report_digest": self.report_digest.hex,
            "samples": [item.document() for item in self.samples],
            "schema": "backtest.benchmark-report.v1",
            # Return the completed benchmark report document result without a hidden fallback.
        }


# Keep the benchmark publication contract and validation rules together.
@dataclass(frozen=True, slots=True)
class BenchmarkPublication:
    report: BenchmarkReport
    attempt_nonce: ContentDigest
    artifact: CommittedArtifact

    # Define benchmark publication post init as one focused operation with an explicit
    # boundary.
    def __post_init__(self) -> None:
        # Execute the benchmark publication post init workflow in explicit, reviewable
        # steps.
        if self.artifact.kind is not ArtifactKind.BENCHMARK:
            raise ValueError("benchmark publication requires a BENCHMARK artifact")

    @property
    def benchmark_build_key(self) -> ContentDigest:
        return benchmark_build_key(self.report.spec, self.attempt_nonce)


# Keep the benchmark equivalence kind contract and validation rules together.
class BenchmarkEquivalenceKind(StrEnum):
    PARQUET_REPLAY_PACK = "PARQUET_REPLAY_PACK"
    EMBEDDED_FROZEN = "EMBEDDED_FROZEN"
    DIRECT_CONTROL = "DIRECT_CONTROL"


# Keep the benchmark equivalence evidence contract and validation rules together.
@dataclass(frozen=True, slots=True)
class BenchmarkEquivalenceEvidence:
    kind: BenchmarkEquivalenceKind
    first_spec_id: ContentDigest
    second_spec_id: ContentDigest
    # Declare canonical result hash explicitly in the benchmark equivalence evidence
    # contract.
    canonical_result_hash: ContentDigest

    @property
    def evidence_id(self) -> ContentDigest:
        # Execute the benchmark equivalence evidence evidence id workflow in explicit,
        # reviewable steps.
        return domain_digest(
            "backtest.benchmark-equivalence.v1",
            {
                "canonical_result_hash": self.canonical_result_hash.hex,
                "first_spec_id": self.first_spec_id.hex,
                # Keep kind named so the v1 and canonical result hash payload passed to
                # domain_digest remains self-describing within benchmark equivalence
                # evidence evidence id.
                "kind": self.kind.value,
                "second_spec_id": self.second_spec_id.hex,
            },
        )


def prove_benchmark_equivalence(
    # Keep the first input explicit in the prove benchmark equivalence contract.
    first: BenchmarkReport,
    second: BenchmarkReport,
) -> BenchmarkEquivalenceEvidence:
    """Require one normative exact equivalence pair; timing is never compared."""

    kind = _equivalence_kind(first.spec, second.spec)
    if _physical_comparison_grid(first.spec) != _physical_comparison_grid(second.spec):
        raise ValueError("benchmark equivalence requires the same physical comparison grid")
    if (
        first.spec.semantic_equivalence_id is None
        # Keep first visible while evaluating the semantic equivalence id, spec and first
        # guard.
        or first.spec.semantic_equivalence_id != second.spec.semantic_equivalence_id
    ):
        raise ValueError("benchmark targets do not declare the same exact semantic closure")
    if first.canonical_result_hash != second.canonical_result_hash:
        raise ValueError("benchmark targets produced different canonical results")
    # Return the completed prove benchmark equivalence result without a hidden fallback.
    return BenchmarkEquivalenceEvidence(
        kind,
        first.spec.benchmark_spec_id,
        second.spec.benchmark_spec_id,
        first.canonical_result_hash,
        # Complete BenchmarkEquivalenceEvidence only after its benchmark spec id and spec
        # inputs are visible in prove benchmark equivalence.
    )


def benchmark_build_key(spec: BenchmarkSpec, attempt_nonce: ContentDigest) -> ContentDigest:
    """Separate operational benchmark attempt lookup from committed report identity."""

    return domain_digest(
        "backtest.benchmark-build.v1",
        {
            "attempt_nonce": attempt_nonce.hex,
            "benchmark_spec_id": spec.benchmark_spec_id.hex,
            # Close the v1 and attempt nonce payload only after all benchmark build key fields
            # are present.
        },
    )


def exact_benchmark_command_from_bytes(payload: bytes) -> ExactBenchmarkCommand:
    # Execute the exact benchmark command from bytes workflow in explicit, reviewable
    # steps.
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError("benchmark command is not valid JSON") from error
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        # Fail the exact benchmark command from bytes path with ValueError for benchmark
        # command must be an object when isinstance, value and key is true; do not
        # continue ambiguously.
        raise ValueError("benchmark command must be an object")
    expected = {
        "attempt_nonce",
        "batch_rows",
        "cache_condition",
        # Keep the capacity days component named inside the expected contract.
        "capacity_days",
        "launch_route",
        "measured_iterations",
        "native_threads_per_process",
        "process_count",
        # Keep the readahead component named inside the expected contract.
        "readahead",
        "schema",
        "target_artifact_id",
        "warmup_iterations",
        "workload",
        # Complete the expected group only after its semantic components are visible.
    }
    if set(value) != expected or value["schema"] != "backtest.exact-benchmark-command.v1":
        raise ValueError("unsupported benchmark command schema")
    try:
        # Perform the protected exact benchmark command from bytes operation before
        # explicit failure handling.
        command = ExactBenchmarkCommand(
            target_artifact_id=ArtifactId(_command_string(value, "target_artifact_id")),
            workload=BenchmarkWorkload(_command_string(value, "workload")),
            launch_route=BenchmarkLaunchRoute(_command_string(value, "launch_route")),
            cache_condition=CacheCondition(_command_string(value, "cache_condition")),
            # Keep the value _command_integer step visible while building command.
            batch_rows=_command_integer(value, "batch_rows"),
            readahead=_command_integer(value, "readahead"),
            process_count=_command_integer(value, "process_count"),
            native_threads_per_process=_command_integer(value, "native_threads_per_process"),
            warmup_iterations=_command_integer(value, "warmup_iterations"),
            # Keep the value _command_integer step visible while building command.
            measured_iterations=_command_integer(value, "measured_iterations"),
            capacity_days=_command_integer(value, "capacity_days"),
            attempt_nonce=ContentDigest(_command_string(value, "attempt_nonce")),
        )
    except (TypeError, ValueError) as error:
        # Fail the exact benchmark command from bytes path with ValueError for benchmark
        # command fields are invalid; do not continue ambiguously.
        raise ValueError("benchmark command fields are invalid") from error
    if command.canonical_bytes() != payload:
        raise ValueError("benchmark command is not canonically serialized")
    return command


def benchmark_spec_document(spec: BenchmarkSpec) -> dict[str, object]:
    # Execute the benchmark spec document workflow in explicit, reviewable steps.
    return {
        "batch_rows": spec.batch_rows,
        "cache_condition": spec.cache_condition.value,
        "capacity_days": spec.capacity_days,
        "capacity_model": spec.capacity_model.value,
        # Include input artifact ids in the completed benchmark spec document result.
        "input_artifact_ids": [item.hex for item in spec.input_artifact_ids],
        "launch_route": spec.launch_route.value,
        "measured_iterations": spec.measured_iterations,
        "native_threads_per_process": spec.native_threads_per_process,
        "process_count": spec.process_count,
        # Include readahead in the completed benchmark spec document result.
        "readahead": spec.readahead,
        "runtime_lock_id": spec.runtime_lock_id.hex,
        "semantic_equivalence_id": (
            None if spec.semantic_equivalence_id is None else spec.semantic_equivalence_id.hex
        ),
        # Include warmup iterations in the completed benchmark spec document result.
        "warmup_iterations": spec.warmup_iterations,
        "workload": spec.workload.value,
        "workload_bundle_id": spec.workload_bundle_id.hex,
    }


def _equivalence_kind(
    # Keep the first input explicit in the equivalence kind contract.
    first: BenchmarkSpec,
    second: BenchmarkSpec,
) -> BenchmarkEquivalenceKind:
    # Execute the equivalence kind workflow in explicit, reviewable steps.
    workloads = {first.workload, second.workload}
    if workloads == {BenchmarkWorkload.PARQUET_SCAN, BenchmarkWorkload.REPLAY_PACK_SCAN}:
        return BenchmarkEquivalenceKind.PARQUET_REPLAY_PACK
    if workloads == {
        BenchmarkWorkload.EMBEDDED_INFERENCE,
        # Keep benchmark workload visible while evaluating the workloads, embedded
        # inference and frozen inference guard.
        BenchmarkWorkload.FROZEN_INFERENCE,
    }:
        return BenchmarkEquivalenceKind.EMBEDDED_FROZEN
    if (
        first.workload is BenchmarkWorkload.CONTROL_PLANE_ROUND_TRIP
        # Keep second visible while evaluating the workload, control plane round trip and
        # first guard.
        and second.workload is BenchmarkWorkload.CONTROL_PLANE_ROUND_TRIP
        and {first.launch_route, second.launch_route}
        == {BenchmarkLaunchRoute.DIRECT, BenchmarkLaunchRoute.CONTROL}
    ):
        return BenchmarkEquivalenceKind.DIRECT_CONTROL
    # Fail the equivalence kind path with ValueError for reports are not a normative
    # benchmark equivalence pair; do not continue ambiguously.
    raise ValueError("reports are not a normative benchmark equivalence pair")


def _physical_comparison_grid(spec: BenchmarkSpec) -> tuple[object, ...]:
    # Execute the physical comparison grid workflow in explicit, reviewable steps.
    return (
        spec.batch_rows,
        spec.cache_condition,
        spec.capacity_days,
        spec.capacity_model,
        # Include spec in the completed physical comparison grid result.
        spec.measured_iterations,
        spec.native_threads_per_process,
        spec.process_count,
        spec.readahead,
        spec.warmup_iterations,
        # Return the completed physical comparison grid result without a hidden fallback.
    )


def _percentile(values: tuple[int, ...], percentile: int) -> int:
    # Execute the percentile workflow in explicit, reviewable steps.
    if not values:
        raise ValueError("percentile requires values")
    ordered = sorted(values)
    index = ((len(ordered) - 1) * percentile + 99) // 100
    return ordered[index]


# Define command string as one focused operation with an explicit boundary.
def _command_string(value: dict[str, object], key: str) -> str:
    # Execute the command string workflow in explicit, reviewable steps.
    item = value[key]
    if not isinstance(item, str):
        raise ValueError(f"benchmark command {key} must be a string")
    return item


def _command_integer(value: dict[str, object], key: str) -> int:
    # Execute the command integer workflow in explicit, reviewable steps.
    item = value[key]
    if isinstance(item, bool) or not isinstance(item, int):
        raise ValueError(f"benchmark command {key} must be an integer")
    return item


__all__ = [
    # Keep the benchmark equivalence evidence component named inside the all contract.
    "BenchmarkEquivalenceEvidence",
    "BenchmarkEquivalenceKind",
    "BenchmarkExecutionPhase",
    "BenchmarkLaunchRoute",
    "BenchmarkPublication",
    # Keep the benchmark report component named inside the all contract.
    "BenchmarkReport",
    "BenchmarkSample",
    "BenchmarkSpec",
    "BenchmarkWorkload",
    "BenchmarkWorkloadResult",
    # Keep the cache condition component named inside the all contract.
    "CacheCondition",
    "CapacityModel",
    "ControlPlaneBenchmarkInvocation",
    "ExactBenchmarkCommand",
    "IoCounterBasis",
    # Keep the private rss basis component named inside the all contract.
    "PrivateRssBasis",
    "ProfilerEntry",
    "ReplayBenchmarkCommand",
    "ReplayBenchmarkWorkload",
    "benchmark_build_key",
    # Keep the benchmark spec document component named inside the all contract.
    "benchmark_spec_document",
    "exact_benchmark_command_from_bytes",
    "prove_benchmark_equivalence",
]
