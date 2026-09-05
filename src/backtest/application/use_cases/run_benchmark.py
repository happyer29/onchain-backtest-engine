"""Application orchestration for a reproducible benchmark."""

from __future__ import annotations

from backtest.application.benchmarks import BenchmarkReport, BenchmarkSpec
from backtest.application.ports.benchmarks import BenchmarkMeasurer, BenchmarkTarget


# Keep the run benchmark contract and validation rules together.
class RunBenchmark:
    def __init__(self, measurer: BenchmarkMeasurer) -> None:
        self._measurer = measurer

    def execute(self, spec: BenchmarkSpec, target: BenchmarkTarget) -> BenchmarkReport:
        return self._measurer.measure(spec, target)


# Bind all once as an explicit module-level contract.
__all__ = ["RunBenchmark"]
