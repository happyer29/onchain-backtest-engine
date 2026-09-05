"""Local performance measurement adapters."""

from backtest.adapters.performance.local import LocalBenchmarkMeasurer
from backtest.adapters.performance.publisher import LocalBenchmarkReportPublisher
from backtest.adapters.performance.replay import (
    OPTIMIZED_REDUCER_BENCHMARK_BUNDLE_ID,
    REFERENCE_REDUCER_BENCHMARK_BUNDLE_ID,
    # Include replay scan benchmark bundle id so the replay dependency remains explicit.
    REPLAY_SCAN_BENCHMARK_BUNDLE_ID,
    BenchmarkAdmissionError,
    LocalExactBenchmarkRunner,
    LocalReplayBenchmarkRunner,
    UnsupportedCacheConditionError,
    # Include physical core count so the replay dependency remains explicit.
    physical_core_count,
)
from backtest.adapters.performance.targets import (
    CONTROL_DIRECT_BENCHMARK_BUNDLE_ID,
    CONTROL_QUEUED_BENCHMARK_BUNDLE_ID,
    # Include embedded inference benchmark bundle id so the targets dependency remains
    # explicit.
    EMBEDDED_INFERENCE_BENCHMARK_BUNDLE_ID,
    FROZEN_INFERENCE_BENCHMARK_BUNDLE_ID,
    FULL_BACKTEST_BENCHMARK_BUNDLE_ID,
    PARQUET_SCAN_BENCHMARK_BUNDLE_ID,
    LocalExactBenchmarkSpecResolver,
    # Include local exact benchmark target factory so the targets dependency remains
    # explicit.
    LocalExactBenchmarkTargetFactory,
)

__all__ = [
    "CONTROL_DIRECT_BENCHMARK_BUNDLE_ID",
    "CONTROL_QUEUED_BENCHMARK_BUNDLE_ID",
    # Keep the embedded inference benchmark bundle id component named inside the all
    # contract.
    "EMBEDDED_INFERENCE_BENCHMARK_BUNDLE_ID",
    "FROZEN_INFERENCE_BENCHMARK_BUNDLE_ID",
    "FULL_BACKTEST_BENCHMARK_BUNDLE_ID",
    "OPTIMIZED_REDUCER_BENCHMARK_BUNDLE_ID",
    "PARQUET_SCAN_BENCHMARK_BUNDLE_ID",
    # Keep the reference reducer benchmark bundle id component named inside the all
    # contract.
    "REFERENCE_REDUCER_BENCHMARK_BUNDLE_ID",
    "REPLAY_SCAN_BENCHMARK_BUNDLE_ID",
    "BenchmarkAdmissionError",
    "LocalBenchmarkMeasurer",
    "LocalBenchmarkReportPublisher",
    # Keep the local exact benchmark runner component named inside the all contract.
    "LocalExactBenchmarkRunner",
    "LocalExactBenchmarkSpecResolver",
    "LocalExactBenchmarkTargetFactory",
    "LocalReplayBenchmarkRunner",
    "UnsupportedCacheConditionError",
    # Keep the physical core count component named inside the all contract.
    "physical_core_count",
]
