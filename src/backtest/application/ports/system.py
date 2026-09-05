"""Host-resource status visible to admission, CLI and the local UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


# Keep the system resource snapshot contract and validation rules together.
@dataclass(frozen=True, slots=True)
class SystemResourceSnapshot:
    logical_cpu_count: int
    load_average_milli: tuple[int, int, int] | None
    process_peak_rss_bytes: int
    # Declare process current private rss bytes explicitly in the system resource snapshot
    # contract.
    process_current_private_rss_bytes: int
    physical_memory_total_bytes: int
    physical_memory_available_bytes: int
    measured_safe_child_private_budget_bytes: int
    disk_total_bytes: int
    # Declare disk free bytes explicitly in the system resource snapshot contract.
    disk_free_bytes: int
    temporary_used_bytes: int
    configured_aggregate_child_memory_bytes: int
    configured_builder_memory_bytes: int
    configured_max_parallel_runs: int
    # Declare configured native threads per process explicitly in the system resource
    # snapshot contract.
    configured_native_threads_per_process: int
    configured_tmp_quota_bytes: int
    configured_disk_low_watermark_bytes: int
    configured_disk_emergency_watermark_bytes: int
    configured_memory_safety_reserve_bytes: int
    # Declare configured page cache floor bytes explicitly in the system resource snapshot
    # contract.
    configured_page_cache_floor_bytes: int
    configured_host_staging_output_reserve_bytes: int
    configured_fixed_shared_overhead_bytes: int

    def __post_init__(self) -> None:
        # Execute the system resource snapshot post init workflow in explicit, reviewable
        # steps.
        values = (
            self.logical_cpu_count,
            self.process_peak_rss_bytes,
            self.process_current_private_rss_bytes,
            self.physical_memory_total_bytes,
            # Keep the self component named inside the values contract.
            self.physical_memory_available_bytes,
            self.measured_safe_child_private_budget_bytes,
            self.disk_total_bytes,
            self.disk_free_bytes,
            self.temporary_used_bytes,
            # Keep the self component named inside the values contract.
            self.configured_aggregate_child_memory_bytes,
            self.configured_builder_memory_bytes,
            self.configured_max_parallel_runs,
            self.configured_native_threads_per_process,
            self.configured_tmp_quota_bytes,
            # Keep the self component named inside the values contract.
            self.configured_disk_low_watermark_bytes,
            self.configured_disk_emergency_watermark_bytes,
            self.configured_memory_safety_reserve_bytes,
            self.configured_page_cache_floor_bytes,
            self.configured_host_staging_output_reserve_bytes,
            # Keep the self component named inside the values contract.
            self.configured_fixed_shared_overhead_bytes,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values
        ):
            # Fail the system resource snapshot post init path with ValueError for system
            # resource counters must be non-negative integers when value, values and
            # isinstance is true; do not continue ambiguously.
            raise ValueError("system resource counters must be non-negative integers")
        if self.logical_cpu_count == 0:
            raise ValueError("logical CPU count must be positive")
        if self.physical_memory_available_bytes > self.physical_memory_total_bytes:
            raise ValueError("available physical memory cannot exceed total memory")
        # Evaluate the complete system resource snapshot post init configured disk
        # emergency watermark bytes and configured disk low watermark bytes condition
        # before guarded effects.
        if (
            self.configured_disk_emergency_watermark_bytes
            > self.configured_disk_low_watermark_bytes
        ):
            raise ValueError("disk emergency watermark cannot exceed the low watermark")
        # Evaluate the complete system resource snapshot post init load average milli and
        # value condition before guarded effects.
        if self.load_average_milli is not None and any(
            value < 0 for value in self.load_average_milli
        ):
            raise ValueError("load averages must be non-negative")


class SystemResourceProbe(Protocol):
    # Define system resource probe snapshot as one focused operation with an explicit
    # boundary.
    def snapshot(self) -> SystemResourceSnapshot: ...


__all__ = ["SystemResourceProbe", "SystemResourceSnapshot"]
