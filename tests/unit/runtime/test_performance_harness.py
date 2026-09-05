# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from dataclasses import replace

import pytest

from backtest.adapters.performance.local import (
    LocalBenchmarkMeasurer,
    # Include unsupported cache condition error so the local dependency remains explicit.
    UnsupportedCacheConditionError,
)
from backtest.application.benchmarks import (
    BenchmarkEquivalenceKind,
    BenchmarkLaunchRoute,
    # Include benchmark report so the benchmarks dependency remains explicit.
    BenchmarkReport,
    BenchmarkSample,
    BenchmarkSpec,
    BenchmarkWorkload,
    BenchmarkWorkloadResult,
    # Include cache condition so the benchmarks dependency remains explicit.
    CacheCondition,
    ExactBenchmarkCommand,
    exact_benchmark_command_from_bytes,
    prove_benchmark_equivalence,
)

# Import run benchmark at the visible module dependency boundary.
from backtest.application.use_cases.run_benchmark import RunBenchmark
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import ArtifactId, BundleId, ContentDigest, RuntimeLockId


# Keep the target contract and validation rules together.
class _Target:
    def __init__(self) -> None:
        self.calls = 0

    def execute_once(self) -> BenchmarkWorkloadResult:
        # Execute the target execute once workflow in explicit, reviewable steps.
        self.calls += 1
        sum(range(100))
        return BenchmarkWorkloadResult(100, domain_digest("test.result", {"value": 1}))


def _spec(cache: CacheCondition = CacheCondition.WARM) -> BenchmarkSpec:
    # Execute the spec workflow in explicit, reviewable steps.
    return BenchmarkSpec(
        workload=BenchmarkWorkload.REPLAY_PACK_SCAN,
        input_artifact_ids=(ArtifactId("a" * 64),),
        workload_bundle_id=BundleId(domain_digest("test.bundle", {}).hex),
        runtime_lock_id=RuntimeLockId(domain_digest("test.runtime", {}).hex),
        # Pass cache condition explicitly so BenchmarkSpec receives a reviewable a and
        # bundle input in spec.
        cache_condition=cache,
        batch_rows=65_536,
        readahead=1,
        process_count=1,
        native_threads_per_process=1,
        # Pass warmup iterations explicitly so BenchmarkSpec receives a reviewable a and
        # bundle input in spec.
        warmup_iterations=2,
        measured_iterations=3,
    )


def test_harness_measures_warmup_and_exact_repeated_results() -> None:
    # Execute the test harness measures warmup and exact repeated results workflow in
    # explicit, reviewable steps.
    target = _Target()
    report = RunBenchmark(LocalBenchmarkMeasurer()).execute(_spec(), target)

    assert target.calls == 5
    assert len(report.samples) == 3
    assert report.median_items_per_second >= 0
    # Verify report.p95_wall_time_ns > 0 before this scenario is accepted.
    assert report.p95_wall_time_ns > 0
    assert report.report_digest == report.report_digest
    assert all(sample.peak_rss_bytes > 0 for sample in report.samples)


def test_harness_refuses_to_fake_a_cold_page_cache() -> None:
    # Execute the test harness refuses to fake a cold page cache workflow in explicit,
    # reviewable steps.
    with pytest.raises(UnsupportedCacheConditionError, match="external privileged"):
        LocalBenchmarkMeasurer().measure(_spec(CacheCondition.EXTERNALLY_COLD), _Target())


def test_report_rejects_semantically_unstable_workload() -> None:
    # Execute the test report rejects semantically unstable workload workflow in explicit,
    # reviewable steps.
    class _Unstable:
        def __init__(self) -> None:
            self.value = 0

        def execute_once(self) -> BenchmarkWorkloadResult:
            # Execute the unstable execute once workflow in explicit, reviewable steps.
            self.value += 1
            return BenchmarkWorkloadResult(
                1,
                domain_digest("test.unstable", {"value": self.value}),
            )

    # Acquire raises, value error and pytest at an explicit test report rejects
    # semantically unstable workload context boundary so cleanup remains scoped.
    with pytest.raises(ValueError, match="semantic result"):
        # Keep raises, value error and pytest active only for the bounded test report
        # rejects semantically unstable workload operation.
        LocalBenchmarkMeasurer().measure(
            BenchmarkSpec(
                workload=BenchmarkWorkload.FULL_BACKTEST,
                input_artifact_ids=(ArtifactId("a" * 64),),
                workload_bundle_id=_spec().workload_bundle_id,
                # Pass runtime lock id explicitly to measure for a and full backtest.
                runtime_lock_id=_spec().runtime_lock_id,
                cache_condition=CacheCondition.UNCONTROLLED,
                batch_rows=32_768,
                readahead=1,
                process_count=1,
                # Pass native threads per process explicitly so BenchmarkSpec receives a
                # reviewable a and full backtest input in test report rejects semantically
                # unstable workload.
                native_threads_per_process=1,
                warmup_iterations=0,
                measured_iterations=2,
            ),
            _Unstable(),
            # Complete measure only after its a and full backtest inputs are visible in test
            # report rejects semantically unstable workload.
        )


def test_exact_command_is_canonical_versioned_and_round_trips() -> None:
    # Execute the test exact command is canonical versioned and round trips workflow in
    # explicit, reviewable steps.
    command = ExactBenchmarkCommand(
        target_artifact_id=ArtifactId("b" * 64),
        workload=BenchmarkWorkload.PARQUET_SCAN,
        launch_route=BenchmarkLaunchRoute.LOCAL_ARTIFACT,
        cache_condition=CacheCondition.WARM,
        # Pass batch rows explicitly so ExactBenchmarkCommand receives a reviewable b and
        # benchmark-attempt input in test exact command is canonical versioned and round
        # trips.
        batch_rows=65_536,
        readahead=2,
        process_count=1,
        native_threads_per_process=1,
        warmup_iterations=1,
        # Pass measured iterations explicitly so ExactBenchmarkCommand receives a
        # reviewable b and benchmark-attempt input in test exact command is canonical
        # versioned and round trips.
        measured_iterations=2,
        capacity_days=7,
        attempt_nonce=domain_digest("test.benchmark-attempt", {}),
    )

    assert exact_benchmark_command_from_bytes(command.canonical_bytes()) == command
    # Acquire raises, value error and pytest at an explicit test exact command is
    # canonical versioned and round trips context boundary so cleanup remains scoped.
    with pytest.raises(ValueError, match="canonically serialized"):
        exact_benchmark_command_from_bytes(command.canonical_bytes() + b"\n")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        # Open the field and value payload explicitly for parametrize within test exact
        # command bounds transport iteration counts.
        ("warmup_iterations", 11, "warmup_iterations"),
        ("measured_iterations", 101, "measured_iterations"),
        ("capacity_days", True, "capacity_days"),
    ],
)
# Define test exact command bounds transport iteration counts as one focused operation
# with an explicit boundary.
def test_exact_command_bounds_transport_iteration_counts(
    field: str,
    value: int,
    message: str,
) -> None:
    # Execute the test exact command bounds transport iteration counts workflow in
    # explicit, reviewable steps.
    command = ExactBenchmarkCommand(
        target_artifact_id=ArtifactId("b" * 64),
        workload=BenchmarkWorkload.PARQUET_SCAN,
        launch_route=BenchmarkLaunchRoute.LOCAL_ARTIFACT,
        cache_condition=CacheCondition.WARM,
        # Pass batch rows explicitly so ExactBenchmarkCommand receives a reviewable b and
        # benchmark-attempt input in test exact command bounds transport iteration counts.
        batch_rows=65_536,
        readahead=1,
        process_count=1,
        native_threads_per_process=1,
        warmup_iterations=1,
        # Pass measured iterations explicitly so ExactBenchmarkCommand receives a
        # reviewable b and benchmark-attempt input in test exact command bounds transport
        # iteration counts.
        measured_iterations=1,
        capacity_days=1,
        attempt_nonce=domain_digest("test.benchmark-attempt", {}),
    )

    with pytest.raises(ValueError, match=message):
        # Invoke replace for command and field as a visible test exact command bounds
        # transport iteration counts step.
        replace(command, **{field: value})


def test_equivalence_requires_same_exact_semantic_closure() -> None:
    # Execute the test equivalence requires same exact semantic closure workflow in
    # explicit, reviewable steps.
    semantic_id = domain_digest("test.semantic-closure", {})
    parquet = _report(
        BenchmarkWorkload.PARQUET_SCAN,
        ArtifactId("1" * 64),
        semantic_id,
        # Complete _report only after its 1 and parquet scan inputs are visible in test
        # equivalence requires same exact semantic closure.
    )
    replay = _report(
        BenchmarkWorkload.REPLAY_PACK_SCAN,
        ArtifactId("2" * 64),
        semantic_id,
        # Complete _report only after its 2 and replay pack scan inputs are visible in test
        # equivalence requires same exact semantic closure.
    )

    evidence = prove_benchmark_equivalence(parquet, replay)

    assert evidence.kind is BenchmarkEquivalenceKind.PARQUET_REPLAY_PACK
    with pytest.raises(ValueError, match="semantic closure"):
        # Keep raises, value error and pytest active only for the bounded test equivalence
        # requires same exact semantic closure operation.
        prove_benchmark_equivalence(
            parquet,
            _report(
                BenchmarkWorkload.REPLAY_PACK_SCAN,
                ArtifactId("2" * 64),
                # Pass domain digest explicitly to prove_benchmark_equivalence for other-
                # semantic-closure and 2.
                domain_digest("test.other-semantic-closure", {}),
            ),
        )


def _report(
    workload: BenchmarkWorkload,
    # Keep the artifact id input explicit in the report contract.
    artifact_id: ArtifactId,
    semantic_id: ContentDigest,
) -> BenchmarkReport:
    # Execute the report workflow in explicit, reviewable steps.
    result_hash = domain_digest("test.canonical-result", {})
    spec = BenchmarkSpec(
        workload=workload,
        input_artifact_ids=(artifact_id,),
        workload_bundle_id=BundleId(domain_digest("test.bundle", {"workload": workload}).hex),
        # Keep the hex RuntimeLockId step visible while building spec.
        runtime_lock_id=RuntimeLockId(domain_digest("test.runtime", {}).hex),
        cache_condition=CacheCondition.WARM,
        batch_rows=65_536,
        readahead=1,
        process_count=1,
        # Pass native threads per process explicitly so BenchmarkSpec receives a
        # reviewable bundle and workload input in report.
        native_threads_per_process=1,
        warmup_iterations=0,
        measured_iterations=1,
        semantic_equivalence_id=semantic_id,
    )
    # Return the completed report result without a hidden fallback.
    return BenchmarkReport(
        spec,
        (
            BenchmarkSample(
                iteration=0,
                # Pass items processed explicitly so BenchmarkSample receives a reviewable
                # result hash input in report.
                items_processed=1,
                wall_time_ns=1,
                cpu_time_ns=1,
                peak_rss_bytes=1,
                minor_faults=0,
                # Pass major faults explicitly so BenchmarkSample receives a reviewable
                # result hash input in report.
                major_faults=0,
                block_input_operations=0,
                block_output_operations=0,
                canonical_result_hash=result_hash,
            ),
            # Complete BenchmarkReport only after its benchmark sample and spec inputs are
            # visible in report.
        ),
    )
