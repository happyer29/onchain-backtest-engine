# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from backtest.application.supervisor import (
    HostResourceBudget,
    # Include job lane so the supervisor dependency remains explicit.
    JobLane,
    JobResourceDemand,
)
from backtest.domain.identifiers import AttemptId
from backtest.runtime.local_admission import LocalAdmissionController


# Define attempt as one focused operation with an explicit boundary.
def _attempt(index: int) -> AttemptId:
    return AttemptId(f"attempt-{index}")


def test_admission_enforces_aggregate_ram_physical_cores_and_io() -> None:
    # Execute the test admission enforces aggregate ram physical cores and io workflow in
    # explicit, reviewable steps.
    admission = LocalAdmissionController(
        HostResourceBudget(
            private_memory_bytes=8_000,
            physical_cores=4,
            io_units=3,
            # Pass max children explicitly into HostResourceBudget within test admission
            # enforces aggregate ram physical cores and io.
            max_children=4,
            max_builders=1,
            max_runs=4,
        )
    )
    # Assemble demand once so the test admission enforces aggregate ram physical cores and
    # io workflow shares one value.
    demand = JobResourceDemand(private_memory_bytes=3_000, native_threads=2, io_units=1)

    assert admission.try_reserve(_attempt(1), JobLane.RUN, demand)
    assert admission.try_reserve(_attempt(2), JobLane.RUN, demand)
    assert not admission.try_reserve(_attempt(3), JobLane.RUN, demand)
    snapshot = admission.snapshot()
    # Verify the reserved private memory bytes and snapshot relationship before this
    # scenario is accepted.
    assert snapshot.reserved_private_memory_bytes == 6_000
    assert snapshot.reserved_native_threads == 4
    assert snapshot.active_runs == 2

    admission.release(_attempt(1))
    assert admission.try_reserve(_attempt(3), JobLane.RUN, demand)


# Define test build and run lanes have separate caps but share global budget as one
# focused operation with an explicit boundary.
def test_build_and_run_lanes_have_separate_caps_but_share_global_budget() -> None:
    # Execute the test build and run lanes have separate caps but share global budget
    # workflow in explicit, reviewable steps.
    admission = LocalAdmissionController(
        HostResourceBudget(
            private_memory_bytes=10_000,
            physical_cores=6,
            io_units=4,
            # Pass max children explicitly into HostResourceBudget within test build and
            # run lanes have separate caps but share global budget.
            max_children=3,
            max_builders=1,
            max_runs=2,
        )
    )
    # Assemble builder once so the test build and run lanes have separate caps but share
    # global budget workflow shares one value.
    builder = JobResourceDemand(4_000, native_threads=2, io_units=2)
    run = JobResourceDemand(2_000, native_threads=1, io_units=1)

    assert admission.try_reserve(_attempt(1), JobLane.BUILD, builder)
    assert not admission.can_reserve(JobLane.BUILD, builder)
    assert admission.try_reserve(_attempt(2), JobLane.RUN, run)
    # Verify the try reserve, run and admission relationship before this scenario is
    # accepted.
    assert admission.try_reserve(_attempt(3), JobLane.RUN, run)
    assert not admission.can_reserve(JobLane.RUN, run)


def test_concurrent_reservation_never_oversubscribes_one_slot() -> None:
    # Execute the test concurrent reservation never oversubscribes one slot workflow in
    # explicit, reviewable steps.
    admission = LocalAdmissionController(
        HostResourceBudget(
            private_memory_bytes=1_000,
            physical_cores=1,
            io_units=1,
            # Pass max children explicitly into HostResourceBudget within test concurrent
            # reservation never oversubscribes one slot.
            max_children=1,
            max_builders=0,
            max_runs=1,
        )
    )
    # Assemble demand once so the test concurrent reservation never oversubscribes one
    # slot workflow shares one value.
    demand = JobResourceDemand(1_000)

    with ThreadPoolExecutor(max_workers=16) as executor:
        # Keep thread pool executor active only for the bounded test concurrent
        # reservation never oversubscribes one slot operation.
        results = tuple(
            executor.map(
                lambda index: admission.try_reserve(_attempt(index), JobLane.RUN, demand),
                range(32),
            )
            # Complete tuple only after its map and try reserve inputs are visible in test
            # concurrent reservation never oversubscribes one slot.
        )

    assert sum(results) == 1
    assert admission.snapshot().active_children == 1


def test_one_job_that_does_not_fit_is_rejected_without_partial_reservation() -> None:
    # Execute the test one job that does not fit is rejected without partial reservation
    # workflow in explicit, reviewable steps.
    admission = LocalAdmissionController(
        HostResourceBudget(
            private_memory_bytes=1_000,
            physical_cores=2,
            io_units=1,
            # Pass max children explicitly into HostResourceBudget within test one job
            # that does not fit is rejected without partial reservation.
            max_children=1,
            max_builders=0,
            max_runs=1,
        )
    )

    # Verify the try reserve, run and admission relationship before this scenario is
    # accepted.
    assert not admission.try_reserve(
        _attempt(1),
        JobLane.RUN,
        JobResourceDemand(private_memory_bytes=1_001),
    )
    # Verify the active children, snapshot and admission relationship before this scenario
    # is accepted.
    assert admission.snapshot().active_children == 0


def test_zero_private_memory_budget_keeps_control_plane_idle() -> None:
    # Execute the test zero private memory budget keeps control plane idle workflow in
    # explicit, reviewable steps.
    admission = LocalAdmissionController(
        HostResourceBudget(
            private_memory_bytes=0,
            physical_cores=2,
            io_units=1,
            # Pass max children explicitly into HostResourceBudget within test zero
            # private memory budget keeps control plane idle.
            max_children=1,
            max_builders=1,
            max_runs=1,
        )
    )
    # Assemble demand once so the test zero private memory budget keeps control plane idle
    # workflow shares one value.
    demand = JobResourceDemand(private_memory_bytes=1)

    assert not admission.can_reserve(JobLane.BUILD, demand)
    assert not admission.try_reserve(_attempt(1), JobLane.RUN, demand)
    assert admission.snapshot().active_children == 0


def test_host_budget_rejects_negative_or_boolean_memory_capacity() -> None:
    # Execute the test host budget rejects negative or boolean memory capacity workflow in
    # explicit, reviewable steps.
    for private_memory_bytes in (-1, False):
        # Process (-1, False) inside the bounded test host budget rejects negative or
        # boolean memory capacity loop.
        with pytest.raises(ValueError, match="non-negative"):
            # Keep raises, value error and pytest active only for the bounded test host
            # budget rejects negative or boolean memory capacity operation.
            HostResourceBudget(
                private_memory_bytes=private_memory_bytes,
                physical_cores=1,
                io_units=1,
                max_children=1,
                # Pass max builders explicitly so HostResourceBudget receives a reviewable
                # private memory bytes input in test host budget rejects negative or
                # boolean memory capacity.
                max_builders=1,
                max_runs=0,
            )


def test_disk_reservations_preserve_low_watermark_for_every_active_job() -> None:
    # Execute the test disk reservations preserve low watermark for every active job
    # workflow in explicit, reviewable steps.
    free_bytes = 700
    admission = LocalAdmissionController(
        HostResourceBudget(
            private_memory_bytes=10_000,
            physical_cores=4,
            # Pass io units explicitly into HostResourceBudget within test disk
            # reservations preserve low watermark for every active job.
            io_units=4,
            max_children=4,
            max_builders=0,
            max_runs=4,
        ),
        # Pass disk free bytes explicitly so LocalAdmissionController receives a
        # reviewable host resource budget and free bytes input in test disk reservations
        # preserve low watermark for every active job.
        disk_free_bytes=lambda: free_bytes,
        disk_low_watermark_bytes=100,
    )
    demand = JobResourceDemand(
        1_000,
        # Pass temporary disk bytes explicitly into JobResourceDemand within test disk
        # reservations preserve low watermark for every active job.
        temporary_disk_bytes=200,
        output_disk_bytes=100,
    )

    assert admission.try_reserve(_attempt(1), JobLane.RUN, demand)
    assert admission.try_reserve(_attempt(2), JobLane.RUN, demand)
    # Verify the try reserve, run and demand relationship before this scenario is
    # accepted.
    assert not admission.try_reserve(_attempt(3), JobLane.RUN, demand)
    snapshot = admission.snapshot()
    assert snapshot.reserved_temporary_disk_bytes == 400
    assert snapshot.reserved_output_disk_bytes == 200


def test_low_watermark_and_temporary_quota_fail_closed() -> None:
    # Execute the test low watermark and temporary quota fail closed workflow in explicit,
    # reviewable steps.
    state = {"free": 99, "temporary": 0}
    admission = LocalAdmissionController(
        HostResourceBudget(
            private_memory_bytes=1_000,
            physical_cores=1,
            # Pass io units explicitly into HostResourceBudget within test low watermark
            # and temporary quota fail closed.
            io_units=1,
            max_children=1,
            max_builders=1,
            max_runs=0,
        ),
        # Pass disk free bytes explicitly so LocalAdmissionController receives a
        # reviewable free and temporary input in test low watermark and temporary quota
        # fail closed.
        disk_free_bytes=lambda: state["free"],
        temporary_used_bytes=lambda: state["temporary"],
        temporary_quota_bytes=50,
        disk_low_watermark_bytes=100,
        disk_emergency_watermark_bytes=25,
        # Complete LocalAdmissionController only after its free and temporary inputs are
        # visible in test low watermark and temporary quota fail closed.
    )
    demand = JobResourceDemand(1_000)

    assert not admission.can_reserve(JobLane.BUILD, demand)
    state.update(free=1_000, temporary=51)
    assert not admission.can_reserve(JobLane.BUILD, demand)
    # Verify the emergency stop required, build and admission relationship before this
    # scenario is accepted.
    assert admission.emergency_stop_required(JobLane.BUILD)
    assert not admission.emergency_stop_required(JobLane.RUN)


def test_disk_probe_failure_never_admits_or_keeps_a_builder_running() -> None:
    # Execute the test disk probe failure never admits or keeps a builder running workflow
    # in explicit, reviewable steps.
    def unavailable() -> int:
        raise OSError("probe unavailable")

    admission = LocalAdmissionController(
        HostResourceBudget(
            private_memory_bytes=1_000,
            # Pass physical cores explicitly into HostResourceBudget within test disk
            # probe failure never admits or keeps a builder running.
            physical_cores=1,
            io_units=1,
            max_children=1,
            max_builders=1,
            max_runs=0,
            # Complete HostResourceBudget only after its declared inputs are visible in test
            # disk probe failure never admits or keeps a builder running.
        ),
        disk_free_bytes=unavailable,
        disk_low_watermark_bytes=100,
        disk_emergency_watermark_bytes=50,
    )

    # Verify the can reserve, build and admission relationship before this scenario is
    # accepted.
    assert not admission.can_reserve(JobLane.BUILD, JobResourceDemand(1_000))
    assert admission.emergency_stop_required(JobLane.BUILD)
