"""Portable best-effort host counters with explicit configured ceilings."""

from __future__ import annotations

import os
import resource
import shutil
import sys

# Import pathlib at the visible module dependency boundary.
from pathlib import Path

from backtest.application.ports.system import SystemResourceSnapshot
from backtest.runtime.host_resources import (
    HostMemoryReserves,
    derive_host_memory_budget,
    # Include directory tree bytes so the host resources dependency remains explicit.
    directory_tree_bytes,
    measure_host_memory,
)


# Keep the local system resource probe contract and validation rules together.
class LocalSystemResourceProbe:
    def __init__(
        self,
        data_root: Path,
        *,
        # Keep the aggregate child memory bytes input explicit in the init contract.
        aggregate_child_memory_bytes: int,
        builder_memory_bytes: int,
        max_parallel_runs: int,
        native_threads_per_process: int,
        tmp_quota_bytes: int,
        # Keep the disk low watermark bytes input explicit in the init contract.
        disk_low_watermark_bytes: int,
        disk_emergency_watermark_bytes: int,
        memory_safety_reserve_bytes: int,
        page_cache_floor_bytes: int,
        host_staging_output_reserve_bytes: int,
        # Keep the fixed shared overhead bytes input explicit in the init contract.
        fixed_shared_overhead_bytes: int,
    ) -> None:
        # Execute the local system resource probe init workflow in explicit, reviewable
        # steps.
        values = (
            aggregate_child_memory_bytes,
            builder_memory_bytes,
            max_parallel_runs,
            native_threads_per_process,
            # Keep the tmp quota bytes component named inside the values contract.
            tmp_quota_bytes,
            disk_low_watermark_bytes,
            disk_emergency_watermark_bytes,
            memory_safety_reserve_bytes,
            page_cache_floor_bytes,
            # Keep the host staging output reserve bytes component named inside the values
            # contract.
            host_staging_output_reserve_bytes,
            fixed_shared_overhead_bytes,
        )
        if min(values) <= 0:
            raise ValueError("configured resource ceilings must be positive")
        # Assemble self data root once so the local system resource probe init workflow
        # shares one value.
        self._data_root = data_root
        self._aggregate_child_memory_bytes = aggregate_child_memory_bytes
        self._builder_memory_bytes = builder_memory_bytes
        self._max_parallel_runs = max_parallel_runs
        self._native_threads_per_process = native_threads_per_process
        # Assemble self tmp quota bytes once so the local system resource probe init
        # workflow shares one value.
        self._tmp_quota_bytes = tmp_quota_bytes
        self._disk_low_watermark_bytes = disk_low_watermark_bytes
        self._disk_emergency_watermark_bytes = disk_emergency_watermark_bytes
        self._memory_safety_reserve_bytes = memory_safety_reserve_bytes
        self._page_cache_floor_bytes = page_cache_floor_bytes
        # Assemble host staging output reserve bytes once so the local system resource
        # probe init workflow shares one value.
        self._host_staging_output_reserve_bytes = host_staging_output_reserve_bytes
        self._fixed_shared_overhead_bytes = fixed_shared_overhead_bytes
        if self._disk_emergency_watermark_bytes > self._disk_low_watermark_bytes:
            raise ValueError("disk emergency watermark cannot exceed the low watermark")

    def snapshot(self) -> SystemResourceSnapshot:
        # Execute the local system resource probe snapshot workflow in explicit,
        # reviewable steps.
        disk = shutil.disk_usage(self._data_root)
        memory = measure_host_memory()
        budget = derive_host_memory_budget(
            memory,
            HostMemoryReserves(
                # Pass configured child ceiling bytes explicitly so HostMemoryReserves
                # receives a reviewable aggregate child memory bytes and memory safety
                # reserve bytes input in local system resource probe snapshot.
                configured_child_ceiling_bytes=self._aggregate_child_memory_bytes,
                safety_reserve_bytes=self._memory_safety_reserve_bytes,
                page_cache_floor_bytes=self._page_cache_floor_bytes,
                host_staging_output_reserve_bytes=self._host_staging_output_reserve_bytes,
                fixed_shared_overhead_bytes=self._fixed_shared_overhead_bytes,
                # Complete HostMemoryReserves only after its aggregate child memory bytes and
                # memory safety reserve bytes inputs are visible in local system resource
                # probe snapshot.
            ),
        )
        try:
            # Perform the protected local system resource probe snapshot operation before
            # explicit failure handling.
            raw_load = os.getloadavg()
            load = (
                round(raw_load[0] * 1000),
                round(raw_load[1] * 1000),
                round(raw_load[2] * 1000),
                # Complete the load group only after its semantic components are visible.
            )
        except OSError:  # pragma: no cover - platforms without getloadavg
            load = None
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        peak_bytes = peak if sys.platform == "darwin" else peak * 1024
        return SystemResourceSnapshot(
            logical_cpu_count=os.cpu_count() or 1,
            # Pass load average milli explicitly so SystemResourceSnapshot receives a
            # reviewable tmp and staging input in local system resource probe snapshot.
            load_average_milli=load,
            process_peak_rss_bytes=peak_bytes,
            process_current_private_rss_bytes=memory.controller_private_rss_bytes,
            physical_memory_total_bytes=memory.total_physical_bytes,
            physical_memory_available_bytes=memory.available_physical_bytes,
            # Pass measured safe child private budget bytes explicitly so
            # SystemResourceSnapshot receives a reviewable tmp and staging input in local
            # system resource probe snapshot.
            measured_safe_child_private_budget_bytes=budget.available_child_private_bytes,
            disk_total_bytes=disk.total,
            disk_free_bytes=disk.free,
            temporary_used_bytes=directory_tree_bytes(
                (self._data_root / "tmp", self._data_root / "staging")
                # Complete directory_tree_bytes only after its tmp and staging inputs are
                # visible in local system resource probe snapshot.
            ),
            configured_aggregate_child_memory_bytes=self._aggregate_child_memory_bytes,
            configured_builder_memory_bytes=self._builder_memory_bytes,
            configured_max_parallel_runs=self._max_parallel_runs,
            configured_native_threads_per_process=self._native_threads_per_process,
            # Pass configured tmp quota bytes explicitly so SystemResourceSnapshot
            # receives a reviewable tmp and staging input in local system resource probe
            # snapshot.
            configured_tmp_quota_bytes=self._tmp_quota_bytes,
            configured_disk_low_watermark_bytes=self._disk_low_watermark_bytes,
            configured_disk_emergency_watermark_bytes=(self._disk_emergency_watermark_bytes),
            configured_memory_safety_reserve_bytes=self._memory_safety_reserve_bytes,
            configured_page_cache_floor_bytes=self._page_cache_floor_bytes,
            # Pass configured host staging output reserve bytes explicitly so
            # SystemResourceSnapshot receives a reviewable tmp and staging input in local
            # system resource probe snapshot.
            configured_host_staging_output_reserve_bytes=(self._host_staging_output_reserve_bytes),
            configured_fixed_shared_overhead_bytes=self._fixed_shared_overhead_bytes,
        )


__all__ = ["LocalSystemResourceProbe"]
