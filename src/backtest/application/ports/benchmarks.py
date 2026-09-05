"""Ports for measuring one exact, side-effect-bounded workload."""

from __future__ import annotations

from typing import Protocol

from backtest.application.benchmarks import (
    BenchmarkPublication,
    BenchmarkReport,
    # Include benchmark spec so the benchmarks dependency remains explicit.
    BenchmarkSpec,
    BenchmarkWorkloadResult,
    ExactBenchmarkCommand,
)
from backtest.domain.identifiers import ContentDigest


# Keep the benchmark target contract and validation rules together.
class BenchmarkTarget(Protocol):
    def execute_once(self) -> BenchmarkWorkloadResult: ...


class BenchmarkMeasurer(Protocol):
    def measure(self, spec: BenchmarkSpec, target: BenchmarkTarget) -> BenchmarkReport: ...


# Keep the benchmark runner contract and validation rules together.
class BenchmarkRunner(Protocol):
    def run(
        self,
        spec: BenchmarkSpec,
        attempt_nonce: ContentDigest,
        # Keep the benchmark report step explicit within the benchmark runner run workflow.
    ) -> BenchmarkReport: ...


ReplayBenchmarkRunner = BenchmarkRunner


class ExactBenchmarkResolver(Protocol):
    def resolve(self, command: ExactBenchmarkCommand) -> BenchmarkSpec: ...


# Keep the benchmark report publisher contract and validation rules together.
class BenchmarkReportPublisher(Protocol):
    def publish(
        self,
        report: BenchmarkReport,
        attempt_nonce: ContentDigest,
        # Keep the benchmark publication step explicit within the benchmark report publisher
        # publish workflow.
    ) -> BenchmarkPublication: ...


__all__ = [
    "BenchmarkMeasurer",
    "BenchmarkReportPublisher",
    "BenchmarkRunner",
    # Keep the benchmark target component named inside the all contract.
    "BenchmarkTarget",
    "ExactBenchmarkResolver",
    "ReplayBenchmarkRunner",
]
