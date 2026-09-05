"""Durable local job-queue boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from backtest.application.completion import AttemptCompletionReceipt
from backtest.application.models import (
    AttemptState,
    # Include job attempt so the models dependency remains explicit.
    JobAttempt,
    JobEventRecord,
    JobRecord,
    ResolvedJobSpec,
    ResourceCapacity,
    # Close the models import after its required symbols are visible.
)
from backtest.domain.identifiers import ArtifactId, AttemptId, JobId

# SQLite INTEGER is the durable ordering domain for operational timestamps.
_MAX_OPERATIONAL_TIMESTAMP_NS = 2**63 - 1


@dataclass(frozen=True, slots=True)
class JobListCursor:
    """Typed exclusive keyset for one deterministically filtered job list."""

    state: AttemptState | None
    submitted_at_ns: int
    job_id: JobId

    def __post_init__(self) -> None:
        """Reject keys that cannot be compared by the durable SQLite queue."""

        # Booleans must not enter integer ordering through Python's int subtype.
        if isinstance(self.submitted_at_ns, bool) or not isinstance(
            self.submitted_at_ns,
            int,
        ):
            raise TypeError("job cursor timestamp must be an integer")
        # A cursor can name only the non-negative SQLite timestamp domain.
        if not 0 <= self.submitted_at_ns <= _MAX_OPERATIONAL_TIMESTAMP_NS:
            raise ValueError("job cursor timestamp is outside the SQLite integer range")


@runtime_checkable
class JobQueue(Protocol):
    """Operational command port; it is not a distributed execution contract.

    ``submit`` raises :class:`IdempotencyConflictError` when the same command
    namespace/key is reused for different canonical spec bytes.  Cancellation
    raises :class:`JobNotFoundError` or :class:`JobStateConflictError` for a
    missing or incompatible current state.
    """

    def submit(self, spec: ResolvedJobSpec, idempotency_key: str) -> JobRecord: ...

    def request_cancel(self, job_id: JobId) -> None: ...

    def claim_next(
        self,
        supervisor_instance_id: str,
        # Keep the capacity input explicit in the claim next contract.
        capacity: ResourceCapacity,
    ) -> JobAttempt | None: ...

    def transition(
        self,
        attempt_id: AttemptId,
        # Keep the expected version input explicit in the transition contract.
        expected_version: int,
        new_state: AttemptState,
        result_artifact_id: ArtifactId | None = None,
    ) -> JobAttempt: ...


@runtime_checkable
# Keep the job completion queue contract and validation rules together.
class JobCompletionQueue(Protocol):
    """Narrow success transition used only after receipt/artifact verification."""

    def complete_verified(
        self,
        attempt_id: AttemptId,
        expected_version: int,
        receipt: AttemptCompletionReceipt,
        # Keep the job attempt step explicit within the job completion queue complete verified
        # workflow.
    ) -> JobAttempt: ...


@runtime_checkable
class JobQuery(Protocol):
    """Separate bounded read/query port used by API and CLI query use cases."""

    def get_job(self, job_id: JobId) -> JobRecord | None: ...

    def list_jobs(
        self,
        *,
        state: AttemptState | None = None,
        # Keep the limit input explicit in the list jobs contract.
        limit: int = 100,
        offset: int = 0,
        # Keyset continuation is exclusive and scoped to the same state filter.
        after: JobListCursor | None = None,
    ) -> tuple[JobRecord, ...]: ...


@runtime_checkable
class JobRetryQueue(Protocol):
    # Define job retry queue request retry as one focused operation with an explicit
    # boundary.
    def request_retry(self, job_id: JobId) -> JobRecord: ...


# Keep the job event query contract and validation rules together.
@runtime_checkable
class JobEventQuery(Protocol):
    def list_job_events(
        self,
        job_id: JobId,
        # Close the list job events signature after its explicit inputs.
        *,
        after_event_id: int = 0,
        limit: int = 200,
    ) -> tuple[JobEventRecord, ...]: ...


__all__ = [
    # Keep the job completion queue component named inside the all contract.
    "JobCompletionQueue",
    "JobEventQuery",
    "JobListCursor",
    "JobQuery",
    "JobQueue",
    "JobRetryQueue",
    # Complete the all group only after its semantic components are visible.
]
