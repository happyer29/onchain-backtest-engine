"""Isolated local child-process boundary."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from backtest.application.models import JobAttempt, ProcessHandle, ProcessStatus
from backtest.domain.identifiers import AttemptId


class ProcessRunnerError(RuntimeError):
    """Safe base error for isolated local process operations."""


class ProcessSpawnError(ProcessRunnerError):
    """A trusted local worker command could not be started."""


class ProcessIdentityError(ProcessRunnerError):
    """A live PID could not be matched to its durable start token."""


@runtime_checkable
class ProcessRunner(Protocol):
    def spawn(self, attempt: JobAttempt, *, native_threads: int) -> ProcessHandle: ...

    def probe(self, handle: ProcessHandle) -> ProcessStatus: ...

    def terminate(self, handle: ProcessHandle, grace_seconds: float) -> None: ...

    # Define process runner cleanup launch as one focused operation with an explicit
    # boundary.
    def cleanup_launch(self, attempt_id: AttemptId) -> None: ...


__all__ = [
    "ProcessIdentityError",
    "ProcessRunner",
    "ProcessRunnerError",
    # Keep the process spawn error component named inside the all contract.
    "ProcessSpawnError",
]
