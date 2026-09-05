# Declare this module's dependencies and contracts before execution.
from pathlib import Path

import pytest

from backtest.adapters.system.local import LocalSystemResourceProbe


def test_local_resource_probe_reports_host_and_configured_disk_thresholds(
    tmp_path: Path,
    # Close the test local resource probe reports host and configured disk thresholds
    # signature after its explicit inputs.
) -> None:
    # Execute the test local resource probe reports host and configured disk thresholds
    # workflow in explicit, reviewable steps.
    probe = LocalSystemResourceProbe(
        tmp_path,
        aggregate_child_memory_bytes=4096,
        builder_memory_bytes=1024,
        max_parallel_runs=1,
        # Pass native threads per process explicitly so LocalSystemResourceProbe receives
        # a reviewable tmp path input in test local resource probe reports host and
        # configured disk thresholds.
        native_threads_per_process=1,
        tmp_quota_bytes=2048,
        disk_low_watermark_bytes=512,
        disk_emergency_watermark_bytes=256,
        memory_safety_reserve_bytes=1,
        # Pass page cache floor bytes explicitly so LocalSystemResourceProbe receives a
        # reviewable tmp path input in test local resource probe reports host and
        # configured disk thresholds.
        page_cache_floor_bytes=1,
        host_staging_output_reserve_bytes=1,
        fixed_shared_overhead_bytes=1,
    )

    snapshot = probe.snapshot()

    # Verify snapshot.logical_cpu_count >= 1 before this scenario is accepted.
    assert snapshot.logical_cpu_count >= 1
    assert snapshot.disk_total_bytes >= snapshot.disk_free_bytes >= 0
    assert snapshot.configured_disk_low_watermark_bytes == 512
    assert snapshot.configured_disk_emergency_watermark_bytes == 256
    assert snapshot.physical_memory_total_bytes >= snapshot.physical_memory_available_bytes
    # Verify the configured aggregate child memory bytes and snapshot relationship before
    # this scenario is accepted.
    assert snapshot.configured_aggregate_child_memory_bytes == 4096


def test_local_resource_probe_rejects_inverted_disk_thresholds(tmp_path: Path) -> None:
    # Execute the test local resource probe rejects inverted disk thresholds workflow in
    # explicit, reviewable steps.
    with pytest.raises(ValueError, match="emergency watermark"):
        # Keep raises, value error and pytest active only for the bounded test local
        # resource probe rejects inverted disk thresholds operation.
        LocalSystemResourceProbe(
            tmp_path,
            aggregate_child_memory_bytes=4096,
            builder_memory_bytes=1024,
            max_parallel_runs=1,
            # Pass native threads per process explicitly so LocalSystemResourceProbe
            # receives a reviewable tmp path input in test local resource probe rejects
            # inverted disk thresholds.
            native_threads_per_process=1,
            tmp_quota_bytes=2048,
            disk_low_watermark_bytes=256,
            disk_emergency_watermark_bytes=512,
            memory_safety_reserve_bytes=1,
            # Pass page cache floor bytes explicitly so LocalSystemResourceProbe receives
            # a reviewable tmp path input in test local resource probe rejects inverted
            # disk thresholds.
            page_cache_floor_bytes=1,
            host_staging_output_reserve_bytes=1,
            fixed_shared_overhead_bytes=1,
        )
