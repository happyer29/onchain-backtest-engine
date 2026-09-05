"""Synchronous Direct CLI execution through the durable local supervisor.

The direct command owns ``controller.lock`` outside this module.  It submits
the same strict command as the Control API, lets the same supervisor perform
resource admission and child-process isolation, and waits for the durable
terminal state.  The child never receives a SQLite adapter.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

# Import completion at the visible module dependency boundary.
from backtest.application.completion import AttemptCompletionReceipt
from backtest.application.errors import JobNotFoundError, JobStateConflictError
from backtest.application.models import (
    AttemptState,
    CommittedArtifact,
    # Include job attempt so the models dependency remains explicit.
    JobAttempt,
    JobEventRecord,
    JobRecord,
)
from backtest.application.ports.artifacts import ArtifactRepository

# Import supervisor at the visible module dependency boundary.
from backtest.application.supervisor import SupervisorCycleResult
from backtest.application.use_cases.complete_job_attempt import (
    CompleteJobAttempt,
    CompleteJobAttemptRequest,
)

# Import submit job at the visible module dependency boundary.
from backtest.application.use_cases.submit_job import SubmitJobRequest
from backtest.domain.identifiers import ArtifactId, JobId

_UNFINISHED_STATES = (
    AttemptState.QUEUED,
    AttemptState.STARTING,
    # Keep the attempt state component named inside the unfinished states contract.
    AttemptState.RUNNING,
)
_TERMINAL_STATES = frozenset(
    {
        AttemptState.SUCCEEDED,
        # Pass attempt state explicitly so frozenset receives a reviewable succeeded and
        # failed input in module.
        AttemptState.FAILED,
        AttemptState.CANCELLED,
        AttemptState.INTERRUPTED,
    }
)


# Keep the direct queue contract and validation rules together.
class _DirectQueue(Protocol):
    def get_job(self, job_id: JobId) -> JobRecord | None: ...

    def list_jobs(
        self,
        *,
        # Keep the state input explicit in the list jobs contract.
        state: AttemptState | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[JobRecord, ...]: ...

    def list_job_events(
        # Keep the remaining list job events inputs visible at the direct queue list job
        # events boundary.
        self,
        job_id: JobId,
        *,
        after_event_id: int = 0,
        limit: int = 200,
        # Keep the tuple step explicit within the direct queue list job events workflow.
    ) -> tuple[JobEventRecord, ...]: ...

    def request_cancel(self, job_id: JobId) -> None: ...


class _JobSubmitter(Protocol):
    def execute(self, request: SubmitJobRequest) -> JobRecord: ...


# Keep the synchronous supervisor contract and validation rules together.
class _SynchronousSupervisor(Protocol):
    def reconcile_startup(self) -> SupervisorCycleResult: ...

    def run_cycle(self) -> SupervisorCycleResult: ...

    def shutdown(self) -> SupervisorCycleResult: ...


class DirectJobExecutionError(RuntimeError):
    """Safe terminal failure from synchronous Direct CLI orchestration."""

    def __init__(self, code: str, safe_message: str) -> None:
        # Execute the direct job execution error init workflow in explicit, reviewable
        # steps.
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)

    def __reduce__(
        self,
        # Keep the tuple input explicit in the reduce contract.
    ) -> tuple[type[DirectJobExecutionError], tuple[str, str]]:
        """Preserve the typed safe failure across a spawn ProcessPool boundary."""

        return type(self), (self.code, self.safe_message)


# Keep the direct job completion contract and validation rules together.
@dataclass(frozen=True, slots=True)
class DirectJobCompletion:
    job: JobRecord
    attempt: JobAttempt
    receipt: AttemptCompletionReceipt
    # Declare outputs explicitly in the direct job completion contract.
    outputs: tuple[CommittedArtifact, ...]

    def __post_init__(self) -> None:
        # Execute the direct job completion post init workflow in explicit, reviewable
        # steps.
        if self.job.state is not AttemptState.SUCCEEDED:
            raise ValueError("direct completion requires a successful durable job")
        if self.attempt.state is not AttemptState.SUCCEEDED:
            raise ValueError("direct completion requires a successful attempt")
        if self.attempt.job_id != self.job.job_id or self.attempt.spec != self.job.spec:
            # Fail the direct job completion post init path with ValueError for direct
            # completion attempt differs from its durable job when job id, spec and
            # attempt is true; do not continue ambiguously.
            raise ValueError("direct completion attempt differs from its durable job")
        expected_ids = tuple(item.artifact_id for item in self.receipt.outputs)
        actual_ids = tuple(item.artifact_id for item in self.outputs)
        if actual_ids != expected_ids:
            raise ValueError("direct completion outputs differ from the durable receipt")

    # Apply property semantics to the following direct job completion result artifact
    # contract.
    @property
    def result_artifact(self) -> CommittedArtifact:
        # Execute the direct job completion result artifact workflow in explicit,
        # reviewable steps.
        for artifact in self.outputs:
            # Process self.outputs inside the bounded direct job completion result
            # artifact loop.
            if artifact.artifact_id == self.receipt.result_artifact_id:
                return artifact
        raise AssertionError("receipt result artifact disappeared from verified outputs")


class DirectJobExecutor:
    """Drive exactly one synchronous job while holding controller authority.

    Existing queued work is never executed as a side effect of a Direct CLI
    command.  Startup reconciliation may close stale attempts, after which an
    already queued job makes the direct command fail closed and asks the user
    to run the normal supervisor.
    """

    def __init__(
        self,
        *,
        submitter: _JobSubmitter,
        queue: _DirectQueue,
        # Keep the supervisor input explicit in the init contract.
        supervisor: _SynchronousSupervisor,
        verifier: CompleteJobAttempt,
        artifacts: ArtifactRepository,
        poll_interval_seconds: float = 0.1,
        maximum_wait_seconds: float = 49 * 60 * 60,
        # Keep the monotonic input explicit in the init contract.
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        # Execute the direct job executor init workflow in explicit, reviewable steps.
        if poll_interval_seconds <= 0 or poll_interval_seconds > 1:
            raise ValueError("direct polling interval must be in (0, 1] seconds")
        if maximum_wait_seconds <= 0:
            raise ValueError("direct maximum wait must be positive")
        self._submitter = submitter
        # Assemble self queue once so the direct job executor init workflow shares one
        # value.
        self._queue = queue
        self._supervisor = supervisor
        self._verifier = verifier
        self._artifacts = artifacts
        self._poll_interval_seconds = poll_interval_seconds
        # Assemble self maximum wait seconds once so the direct job executor init workflow
        # shares one value.
        self._maximum_wait_seconds = maximum_wait_seconds
        self._monotonic = monotonic
        self._sleep = sleep

    def execute(self, request: SubmitJobRequest) -> DirectJobCompletion:
        # Execute the direct job executor execute workflow in explicit, reviewable steps.
        job: JobRecord | None = None
        try:
            # Perform the protected direct job executor execute operation before explicit
            # failure handling.
            self._supervisor.reconcile_startup()
            self._require_idle_queue()
            job = self._submitter.execute(request)
            terminal = self._wait_for_terminal(job)
            if terminal.state is AttemptState.SUCCEEDED:
                # Return the completed direct job executor execute result without a hidden
                # fallback.
                return self._verified_completion(terminal)
            raise _terminal_error(terminal.state)
        except KeyboardInterrupt:
            # Translate the KeyboardInterrupt failure through the direct job executor
            # execute boundary.
            if job is not None:
                self._cancel_and_drain(job.job_id)
            raise DirectJobExecutionError(
                "DIRECT_JOB_CANCELLED",
                "The direct job was cancelled before completion.",
                # Complete DirectJobExecutionError only after its direct job cancelled and
                # value inputs are visible in direct job executor execute.
            ) from None
        finally:
            self._supervisor.shutdown()

    def _require_idle_queue(self) -> None:
        # Execute the direct job executor require idle queue workflow in explicit,
        # reviewable steps.
        for state in _UNFINISHED_STATES:
            # Process _UNFINISHED_STATES inside the bounded direct job executor require
            # idle queue loop.
            if self._queue.list_jobs(state=state, limit=1, offset=0):
                # Handle the direct job executor require idle queue list jobs, queue and
                # state condition as a distinct block.
                raise DirectJobExecutionError(
                    "DIRECT_QUEUE_NOT_IDLE",
                    "Queued work already exists; run the local supervisor before Direct CLI.",
                )

    def _wait_for_terminal(self, submitted: JobRecord) -> JobRecord:
        # Execute the direct job executor wait for terminal workflow in explicit,
        # reviewable steps.
        deadline = self._monotonic() + self._maximum_wait_seconds
        attempt_observed = False
        while True:
            # Keep the True loop body bounded within direct job executor wait for
            # terminal.
            cycle = self._supervisor.run_cycle()
            current = self._required_job(submitted.job_id)
            if current.spec != submitted.spec:
                # Handle the direct job executor wait for terminal current.spec !=
                # submitted.spec branch as a distinct logical block.
                raise DirectJobExecutionError(
                    "DIRECT_JOB_STATE_INVALID",
                    "The durable direct job changed its resolved specification.",
                )
            if current.state in _TERMINAL_STATES:
                # Return the completed direct job executor wait for terminal result
                # without a hidden fallback.
                return current
            if cycle.started or cycle.failed or cycle.cancelled or cycle.completed:
                attempt_observed = True
            if (
                not attempt_observed
                # Keep current visible while evaluating the attempt observed, state and
                # queued guard.
                and current.state is AttemptState.QUEUED
                and cycle == SupervisorCycleResult()
            ):
                # Handle the direct job executor wait for terminal attempt observed, state
                # and queued condition as a distinct block.
                self._cancel_and_drain(current.job_id)
                raise DirectJobExecutionError(
                    "DIRECT_JOB_ADMISSION_REJECTED",
                    "The direct job does not fit the configured RAM, CPU, I/O or disk budget.",
                )
            # Guard this path with self._monotonic() >= deadline before applying effects.
            if self._monotonic() >= deadline:
                # Handle the direct job executor wait for terminal self._monotonic() >=
                # deadline branch as a distinct logical block.
                self._cancel_and_drain(current.job_id)
                raise DirectJobExecutionError(
                    "DIRECT_JOB_WAIT_TIMEOUT",
                    "The synchronous direct-job wait exceeded its bounded timeout.",
                )
            # Invoke _sleep for poll interval seconds as a visible direct job executor
            # wait for terminal step.
            self._sleep(self._poll_interval_seconds)

    def _verified_completion(self, job: JobRecord) -> DirectJobCompletion:
        # Execute the direct job executor verified completion workflow in explicit,
        # reviewable steps.
        events = self._queue.list_job_events(job.job_id, after_event_id=0, limit=1_000)
        succeeded = tuple(
            event
            for event in events
            if event.event_type == "ATTEMPT_SUCCEEDED" and event.attempt_id is not None
            # Complete tuple only after its attempt succeeded and event type inputs are
            # visible in direct job executor verified completion.
        )
        if len(succeeded) != 1:
            # Handle the direct job executor verified completion len(succeeded) != 1
            # branch as a distinct logical block.
            raise DirectJobExecutionError(
                "DIRECT_COMPLETION_INVALID",
                "The successful direct job has no unique durable completion attempt.",
            )
        event = succeeded[0]
        # Verify event.attempt_id is not None before this scenario is accepted.
        assert event.attempt_id is not None
        attempt = JobAttempt(
            attempt_id=event.attempt_id,
            job_id=job.job_id,
            spec=job.spec,
            # Pass state explicitly so JobAttempt receives a reviewable attempt id and job
            # id input in direct job executor verified completion.
            state=AttemptState.SUCCEEDED,
            state_version=event.state_version,
        )
        try:
            # Perform the protected direct job executor verified completion operation
            # before explicit failure handling.
            receipt = self._verifier.verify(CompleteJobAttemptRequest(attempt))
            outputs = tuple(
                self._verified_descriptor(output.artifact_id, output.manifest_digest.hex)
                for output in receipt.outputs
            )
        # Translate file not found error through the direct job executor verified
        # completion boundary without hiding other errors.
        except (FileNotFoundError, RuntimeError, ValueError):
            # Translate the file not found error, runtime error and value error failure
            # through the direct job executor verified completion boundary.
            raise DirectJobExecutionError(
                "DIRECT_COMPLETION_INVALID",
                "The direct completion receipt or committed output failed verification.",
            ) from None
        return DirectJobCompletion(job, attempt, receipt, outputs)

    # Define direct job executor verified descriptor as one focused operation with an
    # explicit boundary.
    def _verified_descriptor(
        self,
        artifact_id: ArtifactId,
        expected_manifest_digest: str,
    ) -> CommittedArtifact:
        # Execute the direct job executor verified descriptor workflow in explicit,
        # reviewable steps.
        handle = self._artifacts.open_committed(artifact_id)
        try:
            descriptor = handle.descriptor
        finally:
            handle.close()
        # Evaluate the complete direct job executor verified descriptor hex, expected
        # manifest digest and manifest digest condition before guarded effects.
        if descriptor.manifest_digest.hex != expected_manifest_digest:
            raise ValueError("committed output differs from completion receipt")
        return descriptor

    def _required_job(self, job_id: JobId) -> JobRecord:
        # Execute the direct job executor required job workflow in explicit, reviewable
        # steps.
        job = self._queue.get_job(job_id)
        if job is None:
            # Handle the direct job executor required job job is None branch as a distinct
            # logical block.
            raise DirectJobExecutionError(
                "DIRECT_JOB_STATE_INVALID",
                "The durable direct job disappeared from local operational state.",
            )
        return job

    # Define direct job executor cancel and drain as one focused operation with an
    # explicit boundary.
    def _cancel_and_drain(self, job_id: JobId) -> None:
        # Execute the direct job executor cancel and drain workflow in explicit,
        # reviewable steps.
        try:
            self._queue.request_cancel(job_id)
        except (JobNotFoundError, JobStateConflictError):
            return
        self._supervisor.run_cycle()


# Define terminal error as one focused operation with an explicit boundary.
def _terminal_error(state: AttemptState) -> DirectJobExecutionError:
    # Execute the terminal error workflow in explicit, reviewable steps.
    if state is AttemptState.CANCELLED:
        # Handle the terminal error state is AttemptState.CANCELLED branch as a distinct
        # logical block.
        return DirectJobExecutionError(
            "DIRECT_JOB_CANCELLED",
            "The direct job was cancelled before completion.",
        )
    if state is AttemptState.INTERRUPTED:
        # Handle the terminal error state is AttemptState.INTERRUPTED branch as a distinct
        # logical block.
        return DirectJobExecutionError(
            "DIRECT_JOB_INTERRUPTED",
            "The isolated direct-job attempt was interrupted and produced no canonical result.",
        )
    return DirectJobExecutionError(
        # Pass direct job failed explicitly so DirectJobExecutionError receives a
        # reviewable direct job failed input in terminal error.
        "DIRECT_JOB_FAILED",
        "The isolated direct-job attempt failed and produced no canonical result.",
    )


__all__ = [
    "DirectJobCompletion",
    # Keep the direct job execution error component named inside the all contract.
    "DirectJobExecutionError",
    "DirectJobExecutor",
]
