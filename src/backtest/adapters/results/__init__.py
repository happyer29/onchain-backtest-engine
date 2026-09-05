"""Result artifact adapters."""

from backtest.adapters.results.job_completion import (
    LocalJobResultError,
    LocalJobResultReader,
)
from backtest.adapters.results.parquet import LocalParquetRunOutputStore

# Import sweep at the visible module dependency boundary.
from backtest.adapters.results.sweep import LocalSweepOutputStore

__all__ = [
    "LocalJobResultError",
    "LocalJobResultReader",
    "LocalParquetRunOutputStore",
    # Keep the local sweep output store component named inside the all contract.
    "LocalSweepOutputStore",
]
