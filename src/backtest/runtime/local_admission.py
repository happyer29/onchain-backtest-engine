"""Thread-safe aggregate admission for one local supervisor process."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from backtest.application.supervisor import (
    # Include admission snapshot so the supervisor dependency remains explicit.
    AdmissionSnapshot,
    HostResourceBudget,
    JobLane,
    JobResourceDemand,
)

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import AttemptId


# Keep the reservation contract and validation rules together.
@dataclass(frozen=True, slots=True)
class _Reservation:
    lane: JobLane
    demand: JobResourceDemand


class LocalAdmissionController:
    """Reserve measured RAM, physical-core and I/O budgets atomically."""

    def __init__(
        self,
        budget: HostResourceBudget,
        *,
        disk_free_bytes: Callable[[], int] | None = None,
        # Keep the temporary used bytes input explicit in the init contract.
        temporary_used_bytes: Callable[[], int] | None = None,
        temporary_quota_bytes: int = 0,
        disk_low_watermark_bytes: int = 0,
        disk_emergency_watermark_bytes: int = 0,
    ) -> None:
        # Execute the local admission controller init workflow in explicit, reviewable
        # steps.
        if (
            min(
                disk_low_watermark_bytes,
                disk_emergency_watermark_bytes,
                temporary_quota_bytes,
                # Complete min only after its disk low watermark bytes and disk emergency
                # watermark bytes inputs are visible in local admission controller init.
            )
            < 0
        ):
            raise ValueError("disk limits must be non-negative")
        if disk_emergency_watermark_bytes > disk_low_watermark_bytes:
            # Fail the local admission controller init path with ValueError for disk
            # emergency watermark cannot exceed the low watermark when disk emergency
            # watermark bytes and disk low watermark bytes is true; do not continue
            # ambiguously.
            raise ValueError("disk emergency watermark cannot exceed the low watermark")
        if disk_free_bytes is None and (
            disk_low_watermark_bytes or disk_emergency_watermark_bytes or temporary_quota_bytes
        ):
            raise ValueError("disk limits require a free-space probe")
        # Evaluate the complete local admission controller init temporary quota bytes and
        # temporary used bytes condition before guarded effects.
        if temporary_quota_bytes and temporary_used_bytes is None:
            raise ValueError("temporary quota requires a temporary-usage probe")
        self._budget = budget
        self._disk_free_bytes = disk_free_bytes
        self._temporary_used_bytes = temporary_used_bytes
        # Assemble self temporary quota bytes once so the local admission controller init
        # workflow shares one value.
        self._temporary_quota_bytes = temporary_quota_bytes
        self._disk_low_watermark_bytes = disk_low_watermark_bytes
        self._disk_emergency_watermark_bytes = disk_emergency_watermark_bytes
        self._reservations: dict[AttemptId, _Reservation] = {}
        self._lock = Lock()

    # Define local admission controller can reserve as one focused operation with an
    # explicit boundary.
    def can_reserve(self, lane: JobLane, demand: JobResourceDemand) -> bool:
        # Execute the local admission controller can reserve workflow in explicit,
        # reviewable steps.
        with self._lock:
            # Keep lock active only for the bounded local admission controller can reserve
            # operation.
            current = self._snapshot()
            return self._disk_allows_start(demand, current) and self._fits(
                lane,
                demand,
                current,
                # Complete _fits only after its lane and demand inputs are visible in local
                # admission controller can reserve.
            )

    def try_reserve(
        self,
        attempt_id: AttemptId,
        lane: JobLane,
        # Keep the demand input explicit in the try reserve contract.
        demand: JobResourceDemand,
    ) -> bool:
        # Execute the local admission controller try reserve workflow in explicit,
        # reviewable steps.
        with self._lock:
            # Keep lock active only for the bounded local admission controller try reserve
            # operation.
            if attempt_id in self._reservations:
                raise ValueError("attempt already owns a resource reservation")
            current = self._snapshot()
            if not self._disk_allows_start(demand, current) or not self._fits(
                lane,
                # Pass demand explicitly so _fits receives a reviewable lane and demand
                # input in local admission controller try reserve.
                demand,
                current,
            ):
                return False
            self._reservations[attempt_id] = _Reservation(lane, demand)
            # Return the completed local admission controller try reserve result without a
            # hidden fallback.
            return True

    def release(self, attempt_id: AttemptId) -> None:
        # Execute the local admission controller release workflow in explicit, reviewable
        # steps.
        with self._lock:
            self._reservations.pop(attempt_id, None)

    def snapshot(self) -> AdmissionSnapshot:
        # Execute the local admission controller snapshot workflow in explicit, reviewable
        # steps.
        with self._lock:
            return self._snapshot()

    def emergency_stop_required(self, lane: JobLane) -> bool:
        # Execute the local admission controller emergency stop required workflow in
        # explicit, reviewable steps.
        if lane is not JobLane.BUILD:
            return False
        if self._disk_free_bytes is not None:
            # Handle the local admission controller emergency stop required
            # self._disk_free_bytes is not None branch as a distinct logical block.
            try:
                # Perform the protected local admission controller emergency stop required
                # operation before explicit failure handling.
                if self._disk_free_bytes() < self._disk_emergency_watermark_bytes:
                    return True
            except OSError:
                return True
        if self._temporary_used_bytes is not None and self._temporary_quota_bytes:
            # Handle the local admission controller emergency stop required temporary
            # quota bytes and temporary used bytes condition as a distinct block.
            try:
                return self._temporary_used_bytes() > self._temporary_quota_bytes
            except OSError:
                return True
        return False

    # Define local admission controller disk allows start as one focused operation with an
    # explicit boundary.
    def _disk_allows_start(
        self,
        demand: JobResourceDemand,
        current: AdmissionSnapshot,
    ) -> bool:
        # Execute the local admission controller disk allows start workflow in explicit,
        # reviewable steps.
        if self._disk_free_bytes is None:
            return True
        try:
            # Perform the protected local admission controller disk allows start operation
            # before explicit failure handling.
            free_bytes = self._disk_free_bytes()
            temporary_used = (
                0 if self._temporary_used_bytes is None else self._temporary_used_bytes()
            )
        except OSError:
            # Return the completed local admission controller disk allows start result
            # without a hidden fallback.
            return False
        if free_bytes < 0 or temporary_used < 0:
            return False
        if self._temporary_quota_bytes and temporary_used > self._temporary_quota_bytes:
            return False
        # Assemble already reserved once so the local admission controller disk allows
        # start workflow shares one value.
        already_reserved = (
            current.reserved_temporary_disk_bytes + current.reserved_output_disk_bytes
        )
        required_free = (
            self._disk_low_watermark_bytes + already_reserved + demand.reserved_disk_bytes
            # Complete the required free group only after its semantic components are visible.
        )
        return free_bytes >= required_free

    def _snapshot(self) -> AdmissionSnapshot:
        # Execute the local admission controller snapshot workflow in explicit, reviewable
        # steps.
        reservations = tuple(self._reservations.values())
        return AdmissionSnapshot(
            reserved_private_memory_bytes=sum(
                item.demand.private_memory_bytes for item in reservations
            ),
            # Include reserved native threads in the completed local admission controller
            # snapshot result.
            reserved_native_threads=sum(item.demand.native_threads for item in reservations),
            reserved_io_units=sum(item.demand.io_units for item in reservations),
            active_children=len(reservations),
            active_builders=sum(item.lane is JobLane.BUILD for item in reservations),
            active_runs=sum(item.lane is JobLane.RUN for item in reservations),
            # Include reserved temporary disk bytes in the completed local admission
            # controller snapshot result.
            reserved_temporary_disk_bytes=sum(
                item.demand.temporary_disk_bytes for item in reservations
            ),
            reserved_output_disk_bytes=sum(item.demand.output_disk_bytes for item in reservations),
        )

    # Define local admission controller fits as one focused operation with an explicit
    # boundary.
    def _fits(
        self,
        lane: JobLane,
        demand: JobResourceDemand,
        current: AdmissionSnapshot,
        # Keep the bool input explicit in the fits contract.
    ) -> bool:
        # Execute the local admission controller fits workflow in explicit, reviewable
        # steps.
        lane_fits = (
            current.active_builders < self._budget.max_builders
            if lane is JobLane.BUILD
            else current.active_runs < self._budget.max_runs
        )
        # Return the completed local admission controller fits result without a hidden
        # fallback.
        return (
            lane_fits
            and current.active_children < self._budget.max_children
            and current.reserved_private_memory_bytes + demand.private_memory_bytes
            <= self._budget.private_memory_bytes
            # Include current in the completed local admission controller fits result.
            and current.reserved_native_threads + demand.native_threads
            <= self._budget.physical_cores
            and current.reserved_io_units + demand.io_units <= self._budget.io_units
        )


__all__ = ["LocalAdmissionController"]
