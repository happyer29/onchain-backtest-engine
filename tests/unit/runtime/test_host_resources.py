# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import os
from pathlib import Path

import backtest.runtime.host_resources as host_resources_module
from backtest.runtime.host_resources import (
    # Include host memory measurement so the host resources dependency remains explicit.
    HostMemoryMeasurement,
    HostMemoryReserves,
    derive_host_memory_budget,
    directory_tree_bytes,
    measure_host_memory,
    # Include measure process group resources so the host resources dependency remains
    # explicit.
    measure_process_group_resources,
    measure_process_resources,
)


def test_host_budget_reserves_measured_and_fixed_host_overhead_once() -> None:
    # Execute the test host budget reserves measured and fixed host overhead once workflow
    # in explicit, reviewable steps.
    gib = 1024**3
    measurement = HostMemoryMeasurement(
        total_physical_bytes=16 * gib,
        available_physical_bytes=12 * gib,
        controller_private_rss_bytes=256 * 1024**2,
        # Complete HostMemoryMeasurement only after its gib inputs are visible in test host
        # budget reserves measured and fixed host overhead once.
    )
    reserves = HostMemoryReserves(
        configured_child_ceiling_bytes=8 * gib,
        safety_reserve_bytes=1 * gib,
        page_cache_floor_bytes=2 * gib,
        # Pass host staging output reserve bytes explicitly so HostMemoryReserves receives
        # a reviewable gib input in test host budget reserves measured and fixed host
        # overhead once.
        host_staging_output_reserve_bytes=512 * 1024**2,
        fixed_shared_overhead_bytes=256 * 1024**2,
    )

    budget = derive_host_memory_budget(measurement, reserves)

    assert budget.measured_os_baseline_bytes == 4 * gib - 256 * 1024**2
    # Verify the measured controller overhead bytes and budget relationship before this
    # scenario is accepted.
    assert budget.measured_controller_overhead_bytes == 256 * 1024**2
    assert budget.available_child_private_bytes == 8 * gib


def test_host_budget_can_reject_all_children_without_negative_arithmetic() -> None:
    # Execute the test host budget can reject all children without negative arithmetic
    # workflow in explicit, reviewable steps.
    measurement = HostMemoryMeasurement(1_000, 100, 50)
    budget = derive_host_memory_budget(
        measurement,
        HostMemoryReserves(
            configured_child_ceiling_bytes=1_000,
            # Pass safety reserve bytes explicitly into HostMemoryReserves within test
            # host budget can reject all children without negative arithmetic.
            safety_reserve_bytes=50,
            page_cache_floor_bytes=50,
            host_staging_output_reserve_bytes=1,
            fixed_shared_overhead_bytes=1,
        ),
        # Complete derive_host_memory_budget only after its host memory reserves and
        # measurement inputs are visible in test host budget can reject all children without
        # negative arithmetic.
    )

    assert budget.available_child_private_bytes == 0


def test_darwin_available_memory_uses_each_reclaimable_page_once(
    monkeypatch,
) -> None:
    # Execute the test darwin available memory uses each reclaimable page once workflow in
    # explicit, reviewable steps.
    statistics = host_resources_module._DarwinVmStatistics64()
    statistics.free_count = 10
    statistics.active_count = 20
    statistics.inactive_count = 30
    statistics.speculative_count = 7
    # Assemble statistics purgeable count once so the test darwin available memory uses
    # each reclaimable page once workflow shares one value.
    statistics.purgeable_count = 11
    monkeypatch.setattr(
        host_resources_module,
        "_darwin_vm_statistics",
        lambda: (16_384, statistics),
        # Complete setattr only after its darwin vm statistics and host resources module
        # inputs are visible in test darwin available memory uses each reclaimable page once.
    )

    assert host_resources_module._darwin_available_memory() == 40 * 16_384


def test_local_mac_or_linux_measurements_are_non_negative() -> None:
    # Execute the test local mac or linux measurements are non negative workflow in
    # explicit, reviewable steps.
    host = measure_host_memory()
    process = measure_process_resources(os.getpid())

    assert host.total_physical_bytes >= host.available_physical_bytes >= 0
    assert host.controller_private_rss_bytes > 0
    assert process is not None
    # Verify the total rss bytes, private rss bytes and process relationship before this
    # scenario is accepted.
    assert process.total_rss_bytes >= process.private_rss_bytes > 0
    assert process.child_swap_bytes >= 0
    assert process.major_page_faults >= 0
    process_group = measure_process_group_resources(os.getpgrp())
    assert process_group is not None
    # Verify the private rss bytes, process group and process relationship before this
    # scenario is accepted.
    assert process_group.private_rss_bytes >= process.private_rss_bytes


def test_directory_measurement_does_not_follow_or_double_count_links(tmp_path: Path) -> None:
    # Execute the test directory measurement does not follow or double count links
    # workflow in explicit, reviewable steps.
    root = tmp_path / "root"
    root.mkdir()
    payload = root / "payload"
    payload.write_bytes(b"1234")
    os.link(payload, root / "hard-link")
    # Invoke symlink_to for tmp path as a visible test directory measurement does not
    # follow or double count links step.
    (root / "symbolic").symlink_to(tmp_path, target_is_directory=True)

    assert directory_tree_bytes((root,)) == 4
    assert directory_tree_bytes((root / "symbolic",)) == 0
