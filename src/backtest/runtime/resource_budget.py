"""Pure single-host resource admission calculations."""

from __future__ import annotations

from dataclasses import dataclass


class ResourceBudgetError(ValueError):
    """Raised when a job cannot fit the declared host budget."""


@dataclass(frozen=True, slots=True)
class HostCapacity:
    """Measured capacity available to execution children."""

    private_memory_mb: int
    physical_cores: int
    max_processes_by_io: int

    def __post_init__(self) -> None:
        # Execute the host capacity post init workflow in explicit, reviewable steps.
        if min(self.private_memory_mb, self.physical_cores, self.max_processes_by_io) <= 0:
            raise ResourceBudgetError("host capacity values must be positive")


@dataclass(frozen=True, slots=True)
class ProcessDemand:
    """Peak private resources for one child process."""

    private_memory_mb: int
    native_threads: int = 1

    def __post_init__(self) -> None:
        # Execute the process demand post init workflow in explicit, reviewable steps.
        if self.private_memory_mb <= 0 or self.native_threads <= 0:
            raise ResourceBudgetError("process demand values must be positive")


def admitted_processes(capacity: HostCapacity, demand: ProcessDemand, requested: int) -> int:
    """Return the number of independent processes that safely fit.

    A stateful run is never split. Returning zero means the job must not start.
    """

    if requested <= 0:
        raise ResourceBudgetError("requested process count must be positive")

    by_memory = capacity.private_memory_mb // demand.private_memory_mb
    by_cpu = capacity.physical_cores // demand.native_threads
    return min(requested, by_memory, by_cpu, capacity.max_processes_by_io)
