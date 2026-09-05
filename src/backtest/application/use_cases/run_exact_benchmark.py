"""Resolve, measure and publish one exact artifact-bound benchmark command."""

from __future__ import annotations

from backtest.application.benchmarks import BenchmarkPublication, ExactBenchmarkCommand
from backtest.application.ports.benchmarks import (
    BenchmarkReportPublisher,
    BenchmarkRunner,
    # Include exact benchmark resolver so the benchmarks dependency remains explicit.
    ExactBenchmarkResolver,
)


# Keep the run exact benchmark contract and validation rules together.
class RunExactBenchmark:
    def __init__(
        self,
        resolver: ExactBenchmarkResolver,
        runner: BenchmarkRunner,
        # Keep the publisher input explicit in the init contract.
        publisher: BenchmarkReportPublisher,
    ) -> None:
        # Execute the run exact benchmark init workflow in explicit, reviewable steps.
        self._resolver = resolver
        self._runner = runner
        self._publisher = publisher

    def execute(self, command: ExactBenchmarkCommand) -> BenchmarkPublication:
        # Execute the run exact benchmark execute workflow in explicit, reviewable steps.
        spec = self._resolver.resolve(command)
        report = self._runner.run(spec, command.attempt_nonce)
        return self._publisher.publish(report, command.attempt_nonce)


__all__ = ["RunExactBenchmark"]
