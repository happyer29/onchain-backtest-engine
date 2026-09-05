# Declare this module's dependencies and contracts before execution.
from backtest.runtime.resource_budget import HostCapacity, ProcessDemand, admitted_processes


def test_admission_uses_tightest_host_constraint() -> None:
    # Execute the test admission uses tightest host constraint workflow in explicit,
    # reviewable steps.
    capacity = HostCapacity(private_memory_mb=12_000, physical_cores=8, max_processes_by_io=2)
    demand = ProcessDemand(private_memory_mb=4_000, native_threads=2)

    assert admitted_processes(capacity, demand, requested=4) == 2


def test_admission_returns_zero_when_one_process_does_not_fit() -> None:
    # Execute the test admission returns zero when one process does not fit workflow in
    # explicit, reviewable steps.
    capacity = HostCapacity(private_memory_mb=2_000, physical_cores=8, max_processes_by_io=4)
    demand = ProcessDemand(private_memory_mb=4_000)

    assert admitted_processes(capacity, demand, requested=1) == 0
