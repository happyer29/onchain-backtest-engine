"""Bounded spawn-process execution for independent sweep entries only."""

from __future__ import annotations

import multiprocessing
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed

from backtest.application.use_cases.run_backtest import (
    # Include run backtest request so the run backtest dependency remains explicit.
    RunBacktestRequest,
    RunBacktestResult,
)


class ParallelRunExecutionError(RuntimeError):
    """An isolated sweep-entry process failed before returning an exact result."""


class SpawnProcessIndependentRunExecutor:
    """Run independent requests in bounded, non-reused spawned processes.

    ``worker`` must be a top-level picklable composition function. The adapter
    owns only process mechanics and never constructs application infrastructure.
    One worker handles one run and is then recycled, preventing hidden state or
    RSS growth from leaking between logically independent attempts.
    """

    def __init__(
        self,
        worker: Callable[[RunBacktestRequest], RunBacktestResult],
        *,
        max_workers: int,
        # Close the init signature after its explicit inputs.
    ) -> None:
        # Execute the spawn process independent run executor init workflow in explicit,
        # reviewable steps.
        if isinstance(max_workers, bool) or not isinstance(max_workers, int):
            raise TypeError("max_workers must be an integer")
        if not 2 <= max_workers <= 64:
            raise ValueError("parallel sweep workers must be between 2 and 64")
        self._worker = worker
        # Assemble self max workers once so the spawn process independent run executor
        # init workflow shares one value.
        self._max_workers = max_workers

    def execute_all(
        self,
        requests: tuple[RunBacktestRequest, ...],
    ) -> tuple[RunBacktestResult, ...]:
        # Execute the spawn process independent run executor execute all workflow in
        # explicit, reviewable steps.
        if not requests:
            return ()
        worker_count = min(self._max_workers, len(requests))
        if worker_count == 1:
            return (self._worker(requests[0]),)
        # Assemble context once so the spawn process independent run executor execute all
        # workflow shares one value.
        context = multiprocessing.get_context("spawn")
        try:
            # Perform the protected spawn process independent run executor execute all
            # operation before explicit failure handling.
            with ProcessPoolExecutor(
                max_workers=worker_count,
                mp_context=context,
                max_tasks_per_child=1,
            ) as pool:
                # Keep process pool executor, worker count and context active only for the
                # bounded spawn process independent run executor execute all operation.
                futures = tuple(pool.submit(self._worker, request) for request in requests)
                # Completion order is intentionally not semantic. RunSweep
                # validates identities and canonical-sorts returned entries.
                return tuple(future.result() for future in as_completed(futures))
        except Exception as error:
            # Translate the Exception failure through the spawn process independent run
            # executor execute all boundary.
            raise ParallelRunExecutionError(
                "an isolated sweep entry failed; no aggregate result was published"
            ) from error


__all__ = ["ParallelRunExecutionError", "SpawnProcessIndependentRunExecutor"]
