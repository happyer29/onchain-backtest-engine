# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from dataclasses import dataclass

from backtest.application.benchmarks import (
    BenchmarkLaunchRoute,
    BenchmarkPublication,
    # Include benchmark report so the benchmarks dependency remains explicit.
    BenchmarkReport,
    BenchmarkSample,
    BenchmarkSpec,
    BenchmarkWorkload,
    CacheCondition,
    # Include exact benchmark command so the benchmarks dependency remains explicit.
    ExactBenchmarkCommand,
)
from backtest.application.models import ArtifactKind, CommittedArtifact
from backtest.application.use_cases.run_exact_benchmark import RunExactBenchmark
from backtest.domain.hashing import domain_digest

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import ArtifactId, BundleId, ContentDigest, RuntimeLockId


# Keep the resolver contract and validation rules together.
@dataclass
class _Resolver:
    spec: BenchmarkSpec
    command: ExactBenchmarkCommand | None = None

    def resolve(self, command: ExactBenchmarkCommand) -> BenchmarkSpec:
        # Execute the resolver resolve workflow in explicit, reviewable steps.
        self.command = command
        return self.spec


# Keep the runner contract and validation rules together.
@dataclass
class _Runner:
    report: BenchmarkReport
    attempt_nonce: ContentDigest | None = None

    def run(self, spec: BenchmarkSpec, attempt_nonce: ContentDigest) -> BenchmarkReport:
        # Execute the runner run workflow in explicit, reviewable steps.
        assert spec == self.report.spec
        self.attempt_nonce = attempt_nonce
        return self.report


# Keep the publisher contract and validation rules together.
@dataclass
class _Publisher:
    publication: BenchmarkPublication
    attempt_nonce: ContentDigest | None = None

    def publish(
        # Keep the remaining publish inputs visible at the publisher publish boundary.
        self,
        report: BenchmarkReport,
        attempt_nonce: ContentDigest,
    ) -> BenchmarkPublication:
        # Execute the publisher publish workflow in explicit, reviewable steps.
        assert report == self.publication.report
        self.attempt_nonce = attempt_nonce
        return self.publication


def test_exact_benchmark_resolves_runs_and_publishes_one_attempt_identity() -> None:
    # Execute the test exact benchmark resolves runs and publishes one attempt identity
    # workflow in explicit, reviewable steps.
    artifact_id = ArtifactId("a" * 64)
    attempt_nonce = ContentDigest("b" * 64)
    command = ExactBenchmarkCommand(
        artifact_id,
        BenchmarkWorkload.PARQUET_SCAN,
        # Pass benchmark launch route explicitly so ExactBenchmarkCommand receives a
        # reviewable parquet scan and local artifact input in test exact benchmark
        # resolves runs and publishes one attempt identity.
        BenchmarkLaunchRoute.LOCAL_ARTIFACT,
        CacheCondition.WARM,
        65_536,
        1,
        1,
        # Keep exact benchmark command, artifact id and parquet scan visible while
        # completing ExactBenchmarkCommand within test exact benchmark resolves runs and
        # publishes one attempt identity.
        1,
        0,
        1,
        1,
        attempt_nonce,
        # Complete ExactBenchmarkCommand only after its parquet scan and local artifact inputs
        # are visible in test exact benchmark resolves runs and publishes one attempt
        # identity.
    )
    spec = BenchmarkSpec(
        workload=command.workload,
        input_artifact_ids=(artifact_id,),
        workload_bundle_id=BundleId("c" * 64),
        # Keep the runtime lock id and d RuntimeLockId step visible while building spec.
        runtime_lock_id=RuntimeLockId("d" * 64),
        cache_condition=command.cache_condition,
        batch_rows=command.batch_rows,
        readahead=command.readahead,
        process_count=command.process_count,
        # Pass native threads per process explicitly so BenchmarkSpec receives a
        # reviewable c and d input in test exact benchmark resolves runs and publishes one
        # attempt identity.
        native_threads_per_process=command.native_threads_per_process,
        warmup_iterations=0,
        measured_iterations=1,
    )
    result_hash = domain_digest("test.benchmark-result", {})
    # Assemble report once so the test exact benchmark resolves runs and publishes one
    # attempt identity workflow shares one value.
    report = BenchmarkReport(
        spec,
        (
            BenchmarkSample(
                0,
                # Keep benchmark sample and result hash visible while completing
                # BenchmarkSample within test exact benchmark resolves runs and publishes
                # one attempt identity.
                1,
                1,
                1,
                1,
                0,
                # Keep benchmark sample and result hash visible while completing
                # BenchmarkSample within test exact benchmark resolves runs and publishes
                # one attempt identity.
                0,
                0,
                0,
                result_hash,
            ),
            # Complete BenchmarkReport only after its benchmark sample and spec inputs are
            # visible in test exact benchmark resolves runs and publishes one attempt
            # identity.
        ),
    )
    committed = CommittedArtifact(
        ArtifactId("e" * 64),
        ArtifactKind.BENCHMARK,
        # Keep the content digest and f ContentDigest step visible while building
        # committed.
        ContentDigest("f" * 64),
        ContentDigest("1" * 64),
        (artifact_id,),
    )
    publication = BenchmarkPublication(report, attempt_nonce, committed)
    # Assemble resolver once so the test exact benchmark resolves runs and publishes one
    # attempt identity workflow shares one value.
    resolver = _Resolver(spec)
    runner = _Runner(report)
    publisher = _Publisher(publication)

    actual = RunExactBenchmark(resolver, runner, publisher).execute(command)

    assert actual == publication
    # Verify resolver.command == command before this scenario is accepted.
    assert resolver.command == command
    assert runner.attempt_nonce == publisher.attempt_nonce == attempt_nonce
