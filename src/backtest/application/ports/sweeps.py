"""Execution seam for independent local sweep attempts."""

from __future__ import annotations

from typing import Protocol

from backtest.application.models import CommittedArtifact
from backtest.application.sweeps import ResolvedSweepSpec, SweepEntryResult
from backtest.application.use_cases.run_backtest import RunBacktestRequest, RunBacktestResult


# Keep the independent run executor contract and validation rules together.
class IndependentRunExecutor(Protocol):
    def execute_all(
        self,
        requests: tuple[RunBacktestRequest, ...],
    ) -> tuple[RunBacktestResult, ...]: ...


# Keep the sweep output store contract and validation rules together.
class SweepOutputStore(Protocol):
    """Publish the immutable aggregate that retains every exact run output."""

    def publish(
        self,
        spec: ResolvedSweepSpec,
        entries: tuple[SweepEntryResult, ...],
    ) -> CommittedArtifact: ...


# Bind all once as an explicit module-level contract.
__all__ = ["IndependentRunExecutor", "SweepOutputStore"]
