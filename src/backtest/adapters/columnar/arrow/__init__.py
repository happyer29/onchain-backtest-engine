"""PyArrow/DuckDB implementation of canonical local snapshots."""

from backtest.adapters.columnar.arrow.canonical import LocalArrowCanonicalStore
from backtest.adapters.columnar.arrow.incremental import GapSafePrepareDatasetJobResolver
from backtest.adapters.columnar.arrow.parquet_replay import CanonicalParquetReplaySource

__all__ = [
    "CanonicalParquetReplaySource",
    # Keep the gap safe prepare dataset job resolver component named inside the all
    # contract.
    "GapSafePrepareDatasetJobResolver",
    "LocalArrowCanonicalStore",
]
