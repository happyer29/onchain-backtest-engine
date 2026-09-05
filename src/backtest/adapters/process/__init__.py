"""Single-host child-process and direct execution adapters."""

from backtest.adapters.process.parallel import (
    ParallelRunExecutionError,
    SpawnProcessIndependentRunExecutor,
)
from backtest.adapters.process.serial import SerialIndependentRunExecutor

# Bind all once as an explicit module-level contract.
__all__ = [
    "ParallelRunExecutionError",
    "SerialIndependentRunExecutor",
    "SpawnProcessIndependentRunExecutor",
]
