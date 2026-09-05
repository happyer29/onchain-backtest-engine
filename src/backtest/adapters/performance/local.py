"""Low-overhead single-process benchmark measurer."""

from __future__ import annotations

import gc
import os
import resource
import time

# Import metrics at the visible module dependency boundary.
from backtest.adapters.performance.metrics import (
    PeakPrivateRssSampler,
    current_io_counters,
    peak_total_rss_bytes,
)

# Import benchmarks at the visible module dependency boundary.
from backtest.application.benchmarks import (
    BenchmarkReport,
    BenchmarkSample,
    BenchmarkSpec,
    CacheCondition,
    # Include io counter basis so the benchmarks dependency remains explicit.
    IoCounterBasis,
)
from backtest.application.ports.benchmarks import BenchmarkTarget


class UnsupportedCacheConditionError(RuntimeError):
    """The harness cannot truthfully establish the requested cache state."""


class LocalBenchmarkMeasurer:
    def measure(self, spec: BenchmarkSpec, target: BenchmarkTarget) -> BenchmarkReport:
        # Execute the local benchmark measurer measure workflow in explicit, reviewable
        # steps.
        if spec.process_count != 1:
            raise ValueError("generic in-process benchmark target supports one process only")
        if spec.cache_condition is CacheCondition.EXTERNALLY_COLD:
            # Handle the local benchmark measurer measure cache condition, externally cold
            # and spec condition as a distinct block.
            raise UnsupportedCacheConditionError(
                "EXTERNALLY_COLD requires an external privileged cache controller"
            )
        for _ in range(spec.warmup_iterations):
            target.execute_once()

        # Assemble samples once so the local benchmark measurer measure workflow shares
        # one value.
        samples: list[BenchmarkSample] = []
        for iteration in range(spec.measured_iterations):
            # Process range(spec.measured_iterations) inside the bounded local benchmark
            # measurer measure loop.
            gc.collect()
            before = resource.getrusage(resource.RUSAGE_SELF)
            before_io = current_io_counters()
            sampler = PeakPrivateRssSampler()
            sampler.start()
            # Assemble cpu started once so the local benchmark measurer measure workflow
            # shares one value.
            cpu_started = time.process_time_ns()
            wall_started = time.perf_counter_ns()
            result = target.execute_once()
            wall_time = max(1, time.perf_counter_ns() - wall_started)
            cpu_time = max(0, time.process_time_ns() - cpu_started)
            # Invoke stop as a visible step within the local benchmark measurer measure
            # workflow.
            sampler.stop()
            after_io = current_io_counters()
            after = resource.getrusage(resource.RUSAGE_SELF)
            same_io_basis = before_io.basis is after_io.basis
            io_available = (
                # Keep the same io basis component named inside the io available contract.
                same_io_basis
                and before_io.read_bytes is not None
                and before_io.write_bytes is not None
                and after_io.read_bytes is not None
                and after_io.write_bytes is not None
                # Complete the io available group only after its semantic components are
                # visible.
            )
            samples.append(
                BenchmarkSample(
                    iteration=iteration,
                    items_processed=result.items_processed,
                    # Pass wall time ns explicitly so BenchmarkSample receives a
                    # reviewable items processed and ru minflt input in local benchmark
                    # measurer measure.
                    wall_time_ns=wall_time,
                    cpu_time_ns=cpu_time,
                    peak_rss_bytes=peak_total_rss_bytes(),
                    minor_faults=max(0, after.ru_minflt - before.ru_minflt),
                    major_faults=max(0, after.ru_majflt - before.ru_majflt),
                    # Pass block input operations explicitly to append for items processed
                    # and canonical result hash.
                    block_input_operations=max(0, after.ru_inblock - before.ru_inblock),
                    block_output_operations=max(0, after.ru_oublock - before.ru_oublock),
                    canonical_result_hash=result.canonical_result_hash,
                    swap_operations=max(0, after.ru_nswap - before.ru_nswap),
                    peak_private_rss_bytes=sampler.peak_bytes,
                    # Pass private rss basis explicitly so BenchmarkSample receives a
                    # reviewable items processed and ru minflt input in local benchmark
                    # measurer measure.
                    private_rss_basis=sampler.basis,
                    storage_read_bytes=(
                        max(0, after_io.read_bytes - before_io.read_bytes)
                        if io_available
                        and after_io.read_bytes is not None
                        # Pass before io explicitly so BenchmarkSample receives a
                        # reviewable items processed and ru minflt input in local
                        # benchmark measurer measure.
                        and before_io.read_bytes is not None
                        else None
                    ),
                    storage_write_bytes=(
                        max(0, after_io.write_bytes - before_io.write_bytes)
                        # Pass io available explicitly so BenchmarkSample receives a
                        # reviewable items processed and ru minflt input in local
                        # benchmark measurer measure.
                        if io_available
                        and after_io.write_bytes is not None
                        and before_io.write_bytes is not None
                        else None
                    ),
                    # Pass io counter basis explicitly so BenchmarkSample receives a
                    # reviewable items processed and ru minflt input in local benchmark
                    # measurer measure.
                    io_counter_basis=(
                        after_io.basis if io_available else IoCounterBasis.UNAVAILABLE
                    ),
                    worker_process_ids=(os.getpid(),),
                )
                # Complete append only after its items processed and canonical result hash
                # inputs are visible in local benchmark measurer measure.
            )
        return BenchmarkReport(spec, tuple(samples))


__all__ = ["LocalBenchmarkMeasurer", "UnsupportedCacheConditionError"]
