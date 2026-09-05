"""Outbound ports used by the single-host supervisor application service."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from backtest.application.models import JobAttempt, JobProgressDetails, JobType, ProcessHandle
from backtest.application.ports.jobs import JobCompletionQueue
from backtest.application.supervisor import (
    # Include admission snapshot so the supervisor dependency remains explicit.
    AdmissionSnapshot,
    AttemptFailure,
    AttemptFinish,
    ClaimedAttempt,
    JobExecutionPolicy,
    # Include job lane so the supervisor dependency remains explicit.
    JobLane,
    JobResourceDemand,
    SupervisorAttempt,
)
from backtest.domain.identifiers import AttemptId, JobId


# Apply runtime checkable semantics to the following controller authority contract.
@runtime_checkable
class ControllerAuthority(Protocol):
    """Proof that this process currently owns the one-controller lock."""

    @property
    def instance_id(self) -> str: ...

    @property
    def locked(self) -> bool: ...


@runtime_checkable
# Keep the supervisor clock contract and validation rules together.
class SupervisorClock(Protocol):
    def now_ns(self) -> int: ...


# Keep the admission controller contract and validation rules together.
@runtime_checkable
class AdmissionController(Protocol):
    def can_reserve(self, lane: JobLane, demand: JobResourceDemand) -> bool: ...

    def try_reserve(
        self,
        # Keep the attempt id input explicit in the try reserve contract.
        attempt_id: AttemptId,
        lane: JobLane,
        demand: JobResourceDemand,
    ) -> bool: ...

    def release(self, attempt_id: AttemptId) -> None: ...

    # Define admission controller snapshot as one focused operation with an explicit
    # boundary.
    def snapshot(self) -> AdmissionSnapshot: ...

    def emergency_stop_required(self, lane: JobLane) -> bool: ...


@runtime_checkable
class SupervisorJobQueue(Protocol):
    """Durable operational state owned exclusively by the supervisor."""

    def claim_next_for_types(
        self,
        supervisor_instance_id: str,
        job_types: tuple[JobType, ...],
        *,
        # Keep the now ns input explicit in the claim next for types contract.
        now_ns: int,
    ) -> ClaimedAttempt | None: ...

    def register_process(
        self,
        claimed: ClaimedAttempt,
        # Keep the handle input explicit in the register process contract.
        handle: ProcessHandle,
        policy: JobExecutionPolicy,
        *,
        supervisor_instance_id: str,
        now_ns: int,
        # Keep the supervisor attempt step explicit within the supervisor job queue register
        # process workflow.
    ) -> SupervisorAttempt: ...

    def heartbeat(
        self,
        attempt_id: AttemptId,
        expected_version: int,
        # Close the heartbeat signature after its explicit inputs.
        *,
        supervisor_instance_id: str,
        now_ns: int,
        lease_duration_ns: int,
    ) -> None: ...

    # Define supervisor job queue record progress as one focused operation with an
    # explicit boundary.
    def record_progress(
        self,
        attempt_id: AttemptId,
        expected_version: int,
        details: JobProgressDetails,
        # Close the record progress signature after its explicit inputs.
        *,
        supervisor_instance_id: str,
        now_ns: int,
    ) -> None: ...

    def list_unfinished_attempts(self) -> tuple[SupervisorAttempt, ...]: ...

    # Define supervisor job queue finish unsuccessful as one focused operation with an
    # explicit boundary.
    def finish_unsuccessful(
        self,
        attempt_id: AttemptId,
        expected_version: int,
        failure: AttemptFailure,
        # Close the finish unsuccessful signature after its explicit inputs.
        *,
        retry_not_before_ns: int | None,
        now_ns: int,
    ) -> AttemptFinish: ...

    def finish_cancelled(
        # Keep the remaining finish cancelled inputs visible at the supervisor job queue
        # finish cancelled boundary.
        self,
        attempt_id: AttemptId,
        expected_version: int,
        *,
        now_ns: int,
        # Keep the job attempt step explicit within the supervisor job queue finish cancelled
        # workflow.
    ) -> JobAttempt: ...

    def is_cancel_requested(self, job_id: JobId) -> bool: ...


@runtime_checkable
class SupervisorQueue(SupervisorJobQueue, JobCompletionQueue, Protocol):
    """Complete durable queue boundary required by the supervisor."""


__all__ = [
    "AdmissionController",
    "ControllerAuthority",
    "SupervisorClock",
    "SupervisorJobQueue",
    # Keep the supervisor queue component named inside the all contract.
    "SupervisorQueue",
]
