# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from backtest.application.benchmarks import (
    # Include benchmark launch route so the benchmarks dependency remains explicit.
    BenchmarkLaunchRoute,
    BenchmarkPublication,
    BenchmarkReport,
    BenchmarkSample,
    BenchmarkSpec,
    # Include benchmark workload so the benchmarks dependency remains explicit.
    BenchmarkWorkload,
    ExactBenchmarkCommand,
)
from backtest.application.models import ArtifactKind, CommittedArtifact
from backtest.domain.hashing import domain_digest

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import ArtifactId, BundleId, RuntimeLockId
from backtest.interfaces.cli import create_cli


# Keep the benchmark backend contract and validation rules together.
class _BenchmarkBackend:
    command: ExactBenchmarkCommand | None = None

    def run_benchmark(self, command: ExactBenchmarkCommand) -> BenchmarkPublication:
        # Execute the benchmark backend run benchmark workflow in explicit, reviewable
        # steps.
        self.command = command
        spec = BenchmarkSpec(
            workload=command.workload,
            input_artifact_ids=(command.target_artifact_id,),
            workload_bundle_id=BundleId(domain_digest("test.cli-benchmark-bundle", {}).hex),
            # Keep the hex RuntimeLockId step visible while building spec.
            runtime_lock_id=RuntimeLockId(domain_digest("test.cli-benchmark-runtime", {}).hex),
            cache_condition=command.cache_condition,
            batch_rows=command.batch_rows,
            readahead=command.readahead,
            process_count=command.process_count,
            # Pass native threads per process explicitly so BenchmarkSpec receives a
            # reviewable cli-benchmark-bundle and cli-benchmark-runtime input in benchmark
            # backend run benchmark.
            native_threads_per_process=command.native_threads_per_process,
            warmup_iterations=command.warmup_iterations,
            measured_iterations=command.measured_iterations,
            capacity_days=command.capacity_days,
            launch_route=command.launch_route,
            # Keep the cli-benchmark-semantic domain_digest step visible while building
            # spec.
            semantic_equivalence_id=domain_digest("test.cli-benchmark-semantic", {}),
        )
        report = BenchmarkReport(
            spec,
            (
                # Keep the benchmark sample and domain digest BenchmarkSample step visible
                # while building report.
                BenchmarkSample(
                    iteration=0,
                    items_processed=2,
                    wall_time_ns=2,
                    cpu_time_ns=1,
                    # Pass peak rss bytes explicitly so BenchmarkSample receives a
                    # reviewable cli-benchmark-result and domain digest input in benchmark
                    # backend run benchmark.
                    peak_rss_bytes=1,
                    minor_faults=0,
                    major_faults=0,
                    block_input_operations=0,
                    block_output_operations=0,
                    # Keep the cli-benchmark-result domain_digest step visible while
                    # building report.
                    canonical_result_hash=domain_digest("test.cli-benchmark-result", {}),
                ),
            ),
        )
        artifact = CommittedArtifact(
            # Keep the artifact id and e ArtifactId step visible while building artifact.
            artifact_id=ArtifactId("e" * 64),
            kind=ArtifactKind.BENCHMARK,
            manifest_digest=domain_digest("test.cli-benchmark-manifest", {}),
            build_key=domain_digest("test.cli-benchmark-build", {}),
            input_artifact_ids=(command.target_artifact_id,),
            # Complete CommittedArtifact only after its e and cli-benchmark-manifest inputs
            # are visible in benchmark backend run benchmark.
        )
        return BenchmarkPublication(report, command.attempt_nonce, artifact)


# Keep the factory contract and validation rules together.
class _Factory:
    def __init__(self, backend: _BenchmarkBackend) -> None:
        self.backend = backend

    def __call__(
        self,
        # Keep the config path input explicit in the call contract.
        config_path: Path,
        capabilities_file: Path | None,
        *,
        require_capabilities: bool = False,
        prefer_running_controller: bool = False,
        # Keep the benchmark backend input explicit in the call contract.
    ) -> _BenchmarkBackend:
        # Execute the factory call workflow in explicit, reviewable steps.
        del config_path, capabilities_file, require_capabilities, prefer_running_controller
        return self.backend


def test_cli_sends_one_exact_control_benchmark_command() -> None:
    # Execute the test cli sends one exact control benchmark command workflow in explicit,
    # reviewable steps.
    backend = _BenchmarkBackend()
    target = "a" * 64
    nonce = "b" * 64

    result = CliRunner().invoke(
        create_cli(_Factory(backend)),
        # Open the benchmark and --attempt-nonce payload explicitly for invoke within test
        # cli sends one exact control benchmark command.
        [
            "benchmark",
            target,
            "--attempt-nonce",
            nonce,
            # Pass workload explicitly so invoke receives a reviewable benchmark and
            # --attempt-nonce input in test cli sends one exact control benchmark command.
            "--workload",
            "CONTROL_PLANE_ROUND_TRIP",
            "--launch-route",
            "CONTROL",
            "--warmup-iterations",
            # Pass declared text explicitly so invoke receives a reviewable benchmark and
            # --attempt-nonce input in test cli sends one exact control benchmark command.
            "0",
            "--measured-iterations",
            "1",
        ],
    )

    # Verify result.exit_code == 0 before this scenario is accepted.
    assert result.exit_code == 0, result.output
    assert backend.command is not None
    assert backend.command.target_artifact_id == ArtifactId(target)
    assert backend.command.workload is BenchmarkWorkload.CONTROL_PLANE_ROUND_TRIP
    assert backend.command.launch_route is BenchmarkLaunchRoute.CONTROL
    # Verify the benchmark artifact id, e and loads relationship before this scenario is
    # accepted.
    assert json.loads(result.stdout)["benchmark_artifact_id"] == "e" * 64


def test_cli_rejects_launch_route_outside_workload_contract() -> None:
    # Execute the test cli rejects launch route outside workload contract workflow in
    # explicit, reviewable steps.
    backend = _BenchmarkBackend()
    result = CliRunner().invoke(
        create_cli(_Factory(backend)),
        [
            "benchmark",
            # Pass a explicitly so invoke receives a reviewable benchmark and --attempt-
            # nonce input in test cli rejects launch route outside workload contract.
            "a" * 64,
            "--attempt-nonce",
            "b" * 64,
            "--workload",
            "PARQUET_SCAN",
            # Pass launch-route explicitly so invoke receives a reviewable benchmark and
            # --attempt-nonce input in test cli rejects launch route outside workload
            # contract.
            "--launch-route",
            "CONTROL",
        ],
    )

    assert result.exit_code == 2
    # Verify backend.command is None before this scenario is accepted.
    assert backend.command is None
    assert json.loads(result.stderr)["code"] == "INVALID_LOCAL_COMMAND"
