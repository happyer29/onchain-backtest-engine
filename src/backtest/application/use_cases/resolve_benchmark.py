"""Resolve a typed benchmark command before any measured child is spawned."""

from __future__ import annotations

from backtest.application.benchmarks import BenchmarkSpec, ExactBenchmarkCommand
from backtest.application.ports.benchmarks import ExactBenchmarkResolver


# Keep the resolve benchmark contract and validation rules together.
class ResolveBenchmark:
    def __init__(self, resolver: ExactBenchmarkResolver) -> None:
        self._resolver = resolver

    def execute(self, command: ExactBenchmarkCommand) -> BenchmarkSpec:
        return self._resolver.resolve(command)


# Bind all once as an explicit module-level contract.
__all__ = ["ResolveBenchmark"]
