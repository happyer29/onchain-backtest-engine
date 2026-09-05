"""Measure one exact ReplayPack workload and publish its factual evidence."""

from __future__ import annotations

from backtest.application.benchmarks import BenchmarkPublication, BenchmarkSpec
from backtest.application.ports.benchmarks import BenchmarkReportPublisher, BenchmarkRunner
from backtest.domain.identifiers import ContentDigest


# Keep the run replay benchmark contract and validation rules together.
class RunReplayBenchmark:
    def __init__(
        self,
        runner: BenchmarkRunner,
        publisher: BenchmarkReportPublisher,
        # Close the init signature after its explicit inputs.
    ) -> None:
        # Execute the run replay benchmark init workflow in explicit, reviewable steps.
        self._runner = runner
        self._publisher = publisher

    def execute(
        self,
        spec: BenchmarkSpec,
        # Keep the attempt nonce input explicit in the execute contract.
        attempt_nonce: ContentDigest,
    ) -> BenchmarkPublication:
        # Execute the run replay benchmark execute workflow in explicit, reviewable steps.
        report = self._runner.run(spec, attempt_nonce)
        return self._publisher.publish(report, attempt_nonce)


__all__ = ["RunReplayBenchmark"]
