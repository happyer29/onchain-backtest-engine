"""Reference serial sweep executor used by direct CLI and equivalence tests."""

from __future__ import annotations

from backtest.application.use_cases.run_backtest import (
    RunBacktest,
    RunBacktestRequest,
    RunBacktestResult,
    # Close the run backtest import after its required symbols are visible.
)


# Keep the serial independent run executor contract and validation rules together.
class SerialIndependentRunExecutor:
    def __init__(self, run_backtest: RunBacktest) -> None:
        self._run_backtest = run_backtest

    def execute_all(
        self,
        # Keep the requests input explicit in the execute all contract.
        requests: tuple[RunBacktestRequest, ...],
    ) -> tuple[RunBacktestResult, ...]:
        return tuple(self._run_backtest.execute(request) for request in requests)


__all__ = ["SerialIndependentRunExecutor"]
