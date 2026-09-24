"""Single-host durable SQLite implementation of the :class:`JobQueue` port."""

from __future__ import annotations

import sqlite3
import time
import uuid
from collections.abc import Iterator

# Import contextlib at the visible module dependency boundary.
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any, Final, NoReturn

from backtest.adapters.catalog.sqlite.errors import (
    AttemptNotFoundError,
    # Include job queue error so the errors dependency remains explicit.
    JobQueueError,
    QueueCorruptionError,
)
from backtest.adapters.catalog.sqlite.progress_serialization import (
    deserialize_progress_details,
    # Include serialize progress details so the progress serialization dependency remains
    # explicit.
    serialize_progress_details,
)
from backtest.adapters.catalog.sqlite.schema import connect, initialize
from backtest.adapters.catalog.sqlite.serialization import (
    deserialize_job_spec,
    # Include job spec request digest so the serialization dependency remains explicit.
    job_spec_request_digest,
    serialize_job_spec,
)
from backtest.application.completion import (
    AttemptCompletionReceipt,
    # Include unverified job completion error so the completion dependency remains
    # explicit.
    UnverifiedJobCompletionError,
    completion_receipt_digest,
)
from backtest.application.errors import (
    IdempotencyConflictError,
    # Include invalid idempotency key error so the errors dependency remains explicit.
    InvalidIdempotencyKeyError,
    JobNotFoundError,
    JobStateConflictError,
    LocalStateUnavailableError,
)

# Import models at the visible module dependency boundary.
from backtest.application.models import (
    AttemptState,
    JobAttempt,
    JobEventRecord,
    JobProgressDetails,
    # Include job record so the models dependency remains explicit.
    JobRecord,
    JobType,
    ProcessHandle,
    ResolvedJobSpec,
    ResourceCapacity,
    # Close the models import after its required symbols are visible.
)
from backtest.application.ports.jobs import JobCompletionQueue, JobListCursor, JobQueue
from backtest.application.ports.supervisor import SupervisorJobQueue
from backtest.application.supervisor import (
    AttemptFailure,
    # Include attempt failure kind so the supervisor dependency remains explicit.
    AttemptFailureKind,
    AttemptFinish,
    ClaimedAttempt,
    JobExecutionPolicy,
    JobLane,
    # Include job resource demand so the supervisor dependency remains explicit.
    JobResourceDemand,
    SupervisorAttempt,
)
from backtest.domain.identifiers import ArtifactId, AttemptId, JobId
from backtest.runtime.file_locks import FileLock, LockMode

# Bind terminal states once as an explicit module-level contract.
_TERMINAL_STATES = frozenset(
    {
        AttemptState.SUCCEEDED,
        AttemptState.FAILED,
        AttemptState.CANCELLED,
        # Pass attempt state explicitly so frozenset receives a reviewable succeeded and
        # failed input in module.
        AttemptState.INTERRUPTED,
    }
)

# One extra row is reserved for bounded API continuation lookahead.
_MAX_JOB_QUERY_ROWS: Final = 1_001
# Legacy offset remains available for CLI compatibility but cannot force huge scans.
_MAX_JOB_QUERY_OFFSET: Final = 10_000

_LEGAL_TRANSITIONS: dict[AttemptState, frozenset[AttemptState]] = {
    AttemptState.STARTING: frozenset(
        # Open the running and failed payload explicitly for frozenset within module.
        {
            AttemptState.RUNNING,
            AttemptState.FAILED,
            AttemptState.CANCELLED,
            AttemptState.INTERRUPTED,
            # Close the running and failed payload only after all module fields are present.
        }
    ),
    AttemptState.RUNNING: frozenset(
        {
            AttemptState.SUCCEEDED,
            # Pass attempt state explicitly so frozenset receives a reviewable succeeded
            # and failed input in module.
            AttemptState.FAILED,
            AttemptState.CANCELLED,
            AttemptState.INTERRUPTED,
        }
    ),
    # Complete the legal transitions group only after its semantic components are visible.
}
_MAX_PROGRESS_EVENTS_PER_ATTEMPT = 256
_UNAVAILABLE_SQLITE_PRIMARY_CODES: Final = frozenset(
    {
        sqlite3.SQLITE_BUSY,
        # Pass sqlite3 explicitly so frozenset receives a reviewable sqlite busy and
        # sqlite cantopen input in module.
        sqlite3.SQLITE_CANTOPEN,
        sqlite3.SQLITE_FULL,
        sqlite3.SQLITE_IOERR,
        sqlite3.SQLITE_LOCKED,
        sqlite3.SQLITE_READONLY,
        # Close the sqlite busy and sqlite cantopen payload only after all module fields are
        # present.
    }
)


class SQLiteJobQueue(JobQueue, JobCompletionQueue, SupervisorJobQueue):
    """A queue with short explicit transactions and atomic claim/CAS operations.

    Connections are deliberately scoped to one method.  Child processes never
    receive this adapter; a supervisor serializes their bounded progress and
    state changes.
    """

    def __init__(
        self,
        database_path: str | Path,
        *,
        busy_timeout_seconds: float = 5.0,
        # Keep the backup cut lock path input explicit in the init contract.
        backup_cut_lock_path: Path | None = None,
    ) -> None:
        # Execute the sqlite job queue init workflow in explicit, reviewable steps.
        self.database_path = Path(database_path)
        self.busy_timeout_seconds = busy_timeout_seconds
        self._backup_cut_lock_path = backup_cut_lock_path
        initialize(self.database_path, busy_timeout_seconds=busy_timeout_seconds)

    def submit(self, spec: ResolvedJobSpec, idempotency_key: str) -> JobRecord:
        # Execute the sqlite job queue submit workflow in explicit, reviewable steps.
        with self._backup_cut_barrier():
            return self._submit(spec, idempotency_key)

    def _submit(self, spec: ResolvedJobSpec, idempotency_key: str) -> JobRecord:
        # Execute the sqlite job queue submit workflow in explicit, reviewable steps.
        key = _validate_idempotency_key(idempotency_key)
        spec_bytes = serialize_job_spec(spec)
        stored_spec = deserialize_job_spec(spec_bytes)
        request_digest = job_spec_request_digest(spec_bytes)

        with self._transaction(immediate=True) as connection:
            # Keep transaction active only for the bounded sqlite job queue submit
            # operation.
            existing = connection.execute(
                """
                SELECT * FROM jobs
                WHERE command_type = ? AND idempotency_key = ?
                """,
                (spec.job_type.value, key),
            ).fetchone()
            if existing is not None:
                # Handle the sqlite job queue submit existing is not None branch as a
                # distinct logical block.
                if (
                    existing["request_digest"] != request_digest
                    or bytes(existing["resolved_spec"]) != spec_bytes
                ):
                    raise IdempotencyConflictError(spec.job_type, key)
                # Return the completed sqlite job queue submit result without a hidden
                # fallback.
                return _job_from_row(existing)

            now = time.time_ns()
            job_id = JobId(f"job_{uuid.uuid4().hex}")
            connection.execute(
                """
                INSERT INTO jobs (
                    job_id, command_type, idempotency_key, request_digest,
                    resolved_spec, state, state_version, cancel_requested,
                    current_attempt_id, submitted_at_ns, updated_at_ns
                ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, NULL, ?, ?)
                """,
                # Open the value and job type payload explicitly for execute within sqlite
                # job queue submit.
                (
                    str(job_id),
                    spec.job_type.value,
                    key,
                    request_digest,
                    # Pass spec bytes explicitly so execute receives a reviewable value
                    # and job type input in sqlite job queue submit.
                    spec_bytes,
                    AttemptState.QUEUED.value,
                    now,
                    now,
                ),
                # Complete execute only after its value and job type inputs are visible in
                # sqlite job queue submit.
            )
            _append_job_event(
                connection,
                job_id=job_id,
                attempt_id=None,
                # Pass event type explicitly so _append_job_event receives a reviewable
                # job submitted and connection input in sqlite job queue submit.
                event_type="JOB_SUBMITTED",
                state_version=0,
                created_at_ns=now,
            )
            return JobRecord(job_id, stored_spec, AttemptState.QUEUED, 0, now, now)

    # Define sqlite job queue request cancel as one focused operation with an explicit
    # boundary.
    def request_cancel(self, job_id: JobId) -> None:
        # Execute the sqlite job queue request cancel workflow in explicit, reviewable
        # steps.
        with self._backup_cut_barrier():
            self._request_cancel(job_id)

    def _request_cancel(self, job_id: JobId) -> None:
        # Execute the sqlite job queue request cancel workflow in explicit, reviewable
        # steps.
        with self._transaction(immediate=True) as connection:
            # Keep transaction active only for the bounded sqlite job queue request cancel
            # operation.
            row = connection.execute(
                "SELECT state, state_version, cancel_requested FROM jobs WHERE job_id = ?",
                (str(job_id),),
            ).fetchone()
            if row is None:
                # Fail the sqlite job queue request cancel path with JobNotFoundError for
                # job id when row is true; do not continue ambiguously.
                raise JobNotFoundError(job_id)

            state = _parse_state(row["state"])
            if state is AttemptState.CANCELLED:
                return
            if state in _TERMINAL_STATES:
                # Fail the sqlite job queue request cancel path with JobStateConflictError
                # for cancel and job id when state and terminal states is true; do not
                # continue ambiguously.
                raise JobStateConflictError(job_id, state, "cancel")
            if bool(row["cancel_requested"]):
                return

            now = time.time_ns()
            if state is AttemptState.QUEUED:
                # Handle the sqlite job queue request cancel state is AttemptState.QUEUED
                # branch as a distinct logical block.
                connection.execute(
                    """
                    UPDATE jobs
                    SET cancel_requested = 1, state = ?,
                        state_version = state_version + 1, updated_at_ns = ?
                    WHERE job_id = ?
                    """,
                    (AttemptState.CANCELLED.value, now, str(job_id)),
                )
                event_type = "JOB_CANCELLED_BEFORE_CLAIM"
                # Assemble event version once so the sqlite job queue request cancel
                # workflow shares one value.
                event_version = int(row["state_version"]) + 1
                connection.execute(
                    "DELETE FROM job_retry_schedule WHERE job_id = ?",
                    (str(job_id),),
                )
            # Route all remaining cases through the explicit alternative branch.
            else:
                # Handle the sqlite job queue request cancel complement of state is
                # AttemptState.QUEUED explicitly.
                connection.execute(
                    """
                    UPDATE jobs
                    SET cancel_requested = 1, updated_at_ns = ?
                    WHERE job_id = ?
                    """,
                    (now, str(job_id)),
                )
                event_type = "JOB_CANCEL_REQUESTED"
                # Assemble event version once so the sqlite job queue request cancel
                # workflow shares one value.
                event_version = int(row["state_version"])
            _append_job_event(
                connection,
                job_id=job_id,
                attempt_id=None,
                # Pass event type explicitly so _append_job_event receives a reviewable
                # connection and job id input in sqlite job queue request cancel.
                event_type=event_type,
                state_version=event_version,
                created_at_ns=now,
            )

    def request_retry(self, job_id: JobId) -> JobRecord:
        # Execute the sqlite job queue request retry workflow in explicit, reviewable
        # steps.
        with self._backup_cut_barrier():
            return self._request_retry(job_id)

    def _request_retry(self, job_id: JobId) -> JobRecord:
        # Execute the sqlite job queue request retry workflow in explicit, reviewable
        # steps.
        with self._transaction(immediate=True) as connection:
            # Keep transaction active only for the bounded sqlite job queue request retry
            # operation.
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?",
                (str(job_id),),
            ).fetchone()
            if row is None:
                # Fail the sqlite job queue request retry path with JobNotFoundError for
                # job id when row is true; do not continue ambiguously.
                raise JobNotFoundError(job_id)
            state = _parse_state(row["state"])
            if state not in {AttemptState.FAILED, AttemptState.INTERRUPTED}:
                raise JobStateConflictError(job_id, state, "retry")
            now = time.time_ns()
            # Assemble next version once so the sqlite job queue request retry workflow
            # shares one value.
            next_version = int(row["state_version"]) + 1
            changed = connection.execute(
                """
                UPDATE jobs
                SET state = ?, state_version = ?, cancel_requested = 0,
                    current_attempt_id = NULL, updated_at_ns = ?
                WHERE job_id = ? AND state = ? AND state_version = ?
                """,
                (
                    AttemptState.QUEUED.value,
                    # Pass next version explicitly so execute receives a reviewable state
                    # version and value input in sqlite job queue request retry.
                    next_version,
                    now,
                    str(job_id),
                    state.value,
                    int(row["state_version"]),
                    # Complete execute only after its state version and value inputs are
                    # visible in sqlite job queue request retry.
                ),
            ).rowcount
            if changed != 1:
                raise JobStateConflictError(job_id, state, "retry")
            connection.execute(
                # Pass delete from job retry schedule where explicitly so execute receives
                # a reviewable delete from job retry schedule where job id = ? and str
                # input in sqlite job queue request retry.
                "DELETE FROM job_retry_schedule WHERE job_id = ?",
                (str(job_id),),
            )
            _append_job_event(
                connection,
                # Pass job id explicitly so _append_job_event receives a reviewable job
                # manual retry requested and connection input in sqlite job queue request
                # retry.
                job_id=job_id,
                attempt_id=None,
                event_type="JOB_MANUAL_RETRY_REQUESTED",
                state_version=next_version,
                created_at_ns=now,
                # Complete _append_job_event only after its job manual retry requested and
                # connection inputs are visible in sqlite job queue request retry.
            )
            updated = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?",
                (str(job_id),),
            ).fetchone()
            if updated is None:  # pragma: no cover - row cannot disappear in transaction
                raise QueueCorruptionError("retried job disappeared")
            return _job_from_row(updated)

    def claim_next(
        self,
        supervisor_instance_id: str,
        # Keep the capacity input explicit in the claim next contract.
        capacity: ResourceCapacity,
    ) -> JobAttempt | None:
        # Execute the sqlite job queue claim next workflow in explicit, reviewable steps.
        if capacity.available_process_slots <= 0 or capacity.available_memory_bytes <= 0:
            return None

        claimed = self.claim_next_for_types(
            supervisor_instance_id,
            tuple(JobType),
            # Keep the time ns and time time_ns step visible while building claimed.
            now_ns=time.time_ns(),
        )
        return None if claimed is None else claimed.attempt

    def claim_next_for_types(
        self,
        # Keep the supervisor instance id input explicit in the claim next for types
        # contract.
        supervisor_instance_id: str,
        job_types: tuple[JobType, ...],
        *,
        now_ns: int,
    ) -> ClaimedAttempt | None:
        # Execute the sqlite job queue claim next for types workflow in explicit,
        # reviewable steps.
        supervisor_id = _validate_non_empty(
            supervisor_instance_id,
            field="supervisor_instance_id",
            max_length=256,
        )
        # Guard this path with now_ns < 0 before applying effects.
        if now_ns < 0:
            raise ValueError("now_ns must be non-negative")
        if not job_types:
            return None
        if len(set(job_types)) != len(job_types):
            # Fail the sqlite job queue claim next for types path with ValueError for job
            # types must not contain duplicates when job types is true; do not continue
            # ambiguously.
            raise ValueError("job_types must not contain duplicates")
        if any(not isinstance(job_type, JobType) for job_type in job_types):
            raise TypeError("job_types must contain JobType values")

        with self._transaction(immediate=True) as connection:
            # Keep transaction active only for the bounded sqlite job queue claim next for
            # types operation.
            placeholders = ",".join("?" for _ in job_types)
            job_row = connection.execute(
                f"""
                SELECT j.* FROM jobs AS j
                LEFT JOIN job_retry_schedule AS r ON r.job_id = j.job_id
                WHERE j.state = ? AND j.cancel_requested = 0
                  AND j.command_type IN ({placeholders})
                  AND (r.job_id IS NULL OR r.not_before_ns <= ?)
                ORDER BY submitted_at_ns, job_id
                LIMIT 1
                """,
                # Open the declared payload explicitly for fetchone within sqlite job
                # queue claim next for types.
                (
                    AttemptState.QUEUED.value,
                    *(job_type.value for job_type in job_types),
                    now_ns,
                ),
                # Complete fetchone only after its declared inputs are visible in sqlite job
                # queue claim next for types.
            ).fetchone()
            if job_row is None:
                return None

            job_id = JobId(job_row["job_id"])
            spec = _spec_from_job_row(job_row)
            # Assemble next version once so the sqlite job queue claim next for types
            # workflow shares one value.
            next_version = int(job_row["state_version"]) + 1
            attempt_number_row = connection.execute(
                "SELECT COALESCE(MAX(attempt_number), 0) + 1 FROM job_attempts WHERE job_id = ?",
                (str(job_id),),
            ).fetchone()
            # Guard this path with attempt_number_row is None before applying effects.
            if attempt_number_row is None:
                raise QueueCorruptionError("could not allocate attempt number")
            attempt_number = int(attempt_number_row[0])
            attempt_id = AttemptId(f"attempt_{uuid.uuid4().hex}")
            now = now_ns

            # Invoke execute for value and starting as a visible sqlite job queue claim
            # next for types step.
            connection.execute(
                """
                INSERT INTO job_attempts (
                    attempt_id, job_id, attempt_number, supervisor_instance_id,
                    state, state_version, result_artifact_id, created_at_ns, updated_at_ns
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    str(attempt_id),
                    str(job_id),
                    # Pass attempt number explicitly so execute receives a reviewable
                    # value and starting input in sqlite job queue claim next for types.
                    attempt_number,
                    supervisor_id,
                    AttemptState.STARTING.value,
                    next_version,
                    now,
                    # Pass now explicitly so execute receives a reviewable value and
                    # starting input in sqlite job queue claim next for types.
                    now,
                ),
            )
            changed = connection.execute(
                """
                UPDATE jobs
                SET state = ?, state_version = ?, current_attempt_id = ?, updated_at_ns = ?
                WHERE job_id = ? AND state = ? AND state_version = ?
                  AND cancel_requested = 0
                """,
                # Open the state version and value payload explicitly for execute within
                # sqlite job queue claim next for types.
                (
                    AttemptState.STARTING.value,
                    next_version,
                    str(attempt_id),
                    now,
                    # Keep the job id str step visible while building changed.
                    str(job_id),
                    AttemptState.QUEUED.value,
                    int(job_row["state_version"]),
                ),
            ).rowcount
            # Guard this path with changed != 1 before applying effects.
            if changed != 1:
                raise QueueCorruptionError("atomic claim lost its selected queued job")
            connection.execute(
                "DELETE FROM job_retry_schedule WHERE job_id = ?",
                (str(job_id),),
                # Complete execute only after its delete from job retry schedule where job id
                # = ? and str inputs are visible in sqlite job queue claim next for types.
            )
            _append_job_event(
                connection,
                job_id=job_id,
                attempt_id=attempt_id,
                # Pass event type explicitly so _append_job_event receives a reviewable
                # attempt claimed and connection input in sqlite job queue claim next for
                # types.
                event_type="ATTEMPT_CLAIMED",
                state_version=next_version,
                created_at_ns=now,
            )
            return ClaimedAttempt(
                # Include attempt in the completed sqlite job queue claim next for types
                # result.
                attempt=JobAttempt(
                    attempt_id=attempt_id,
                    job_id=job_id,
                    spec=spec,
                    state=AttemptState.STARTING,
                    # Pass state version explicitly so JobAttempt receives a reviewable
                    # starting and attempt id input in sqlite job queue claim next for
                    # types.
                    state_version=next_version,
                ),
                attempt_number=attempt_number,
            )

    def transition(
        # Keep the remaining transition inputs visible at the sqlite job queue transition
        # boundary.
        self,
        attempt_id: AttemptId,
        expected_version: int,
        new_state: AttemptState,
        result_artifact_id: ArtifactId | None = None,
        # Keep the job attempt input explicit in the transition contract.
    ) -> JobAttempt:
        # Execute the sqlite job queue transition workflow in explicit, reviewable steps.
        if new_state is AttemptState.SUCCEEDED:
            # Handle the sqlite job queue transition new_state is AttemptState.SUCCEEDED
            # branch as a distinct logical block.
            raise UnverifiedJobCompletionError(
                "SUCCEEDED requires CompleteJobAttempt receipt verification"
            )
        return self._transition(
            attempt_id,
            # Pass expected version explicitly so _transition receives a reviewable
            # attempt id and expected version input in sqlite job queue transition.
            expected_version,
            new_state,
            result_artifact_id,
            allow_success=False,
        )

    # Define sqlite job queue complete verified as one focused operation with an explicit
    # boundary.
    def complete_verified(
        self,
        attempt_id: AttemptId,
        expected_version: int,
        receipt: AttemptCompletionReceipt,
        # Keep the job attempt input explicit in the complete verified contract.
    ) -> JobAttempt:
        # Execute the sqlite job queue complete verified workflow in explicit, reviewable
        # steps.
        if receipt.attempt_id != attempt_id:
            raise ValueError("completion receipt belongs to another attempt")
        return self._transition(
            attempt_id,
            expected_version,
            # Pass attempt state explicitly so _transition receives a reviewable succeeded
            # and result artifact id input in sqlite job queue complete verified.
            AttemptState.SUCCEEDED,
            receipt.result_artifact_id,
            allow_success=True,
            completion_receipt=receipt,
        )

    # Define sqlite job queue finish cancelled as one focused operation with an explicit
    # boundary.
    def finish_cancelled(
        self,
        attempt_id: AttemptId,
        expected_version: int,
        *,
        # Keep the now ns input explicit in the finish cancelled contract.
        now_ns: int,
    ) -> JobAttempt:
        # Execute the sqlite job queue finish cancelled workflow in explicit, reviewable
        # steps.
        return self._transition(
            attempt_id,
            expected_version,
            AttemptState.CANCELLED,
            None,
            # Pass allow success explicitly so _transition receives a reviewable cancelled
            # and attempt id input in sqlite job queue finish cancelled.
            allow_success=False,
            now_ns=now_ns,
        )

    def _transition(
        self,
        # Keep the attempt id input explicit in the transition contract.
        attempt_id: AttemptId,
        expected_version: int,
        new_state: AttemptState,
        result_artifact_id: ArtifactId | None,
        *,
        # Keep the allow success input explicit in the transition contract.
        allow_success: bool,
        now_ns: int | None = None,
        completion_receipt: AttemptCompletionReceipt | None = None,
    ) -> JobAttempt:
        # Execute the sqlite job queue transition workflow in explicit, reviewable steps.
        with self._backup_cut_barrier():
            # Keep backup cut barrier active only for the bounded sqlite job queue
            # transition operation.
            return self._transition_with_barrier(
                attempt_id,
                expected_version,
                new_state,
                result_artifact_id,
                # Pass allow success explicitly so _transition_with_barrier receives a
                # reviewable attempt id and expected version input in sqlite job queue
                # transition.
                allow_success=allow_success,
                now_ns=now_ns,
                completion_receipt=completion_receipt,
            )

    def _transition_with_barrier(
        # Keep the remaining transition with barrier inputs visible at the sqlite job
        # queue transition with barrier boundary.
        self,
        attempt_id: AttemptId,
        expected_version: int,
        new_state: AttemptState,
        result_artifact_id: ArtifactId | None,
        # Close the transition with barrier signature after its explicit inputs.
        *,
        allow_success: bool,
        now_ns: int | None = None,
        completion_receipt: AttemptCompletionReceipt | None = None,
    ) -> JobAttempt:
        # Execute the sqlite job queue transition with barrier workflow in explicit,
        # reviewable steps.
        if expected_version < 0:
            raise ValueError("expected_version must be non-negative")
        if now_ns is not None and now_ns < 0:
            raise ValueError("now_ns must be non-negative")
        if new_state is AttemptState.SUCCEEDED and not allow_success:
            # Handle the sqlite job queue transition with barrier new state, succeeded and
            # allow success condition as a distinct block.
            raise UnverifiedJobCompletionError(
                "SUCCEEDED requires CompleteJobAttempt receipt verification"
            )
        if (new_state is AttemptState.SUCCEEDED) != (completion_receipt is not None):
            raise ValueError("verified success and completion receipt must be supplied together")

        # Acquire transaction at an explicit sqlite job queue transition with barrier
        # context boundary so cleanup remains scoped.
        with self._transaction(immediate=True) as connection:
            # Keep transaction active only for the bounded sqlite job queue transition
            # with barrier operation.
            row = connection.execute(
                """
                SELECT
                    a.*, j.current_attempt_id, j.cancel_requested,
                    j.state AS job_state, j.state_version AS job_state_version,
                    j.resolved_spec
                FROM job_attempts AS a
                JOIN jobs AS j ON j.job_id = a.job_id
                WHERE a.attempt_id = ?
                """,
                (str(attempt_id),),
            ).fetchone()
            if row is None:
                # Fail the sqlite job queue transition with barrier path with
                # AttemptNotFoundError for attempt id when row is true; do not continue
                # ambiguously.
                raise AttemptNotFoundError(attempt_id)
            job_id = JobId(row["job_id"])
            job_state = _parse_state(row["job_state"])
            if row["current_attempt_id"] != str(attempt_id):
                raise JobStateConflictError(job_id, job_state, "transition")

            # Assemble actual version once so the sqlite job queue transition with barrier
            # workflow shares one value.
            actual_version = int(row["state_version"])
            if actual_version != expected_version:
                raise JobStateConflictError(job_id, job_state, "transition")
            if int(row["job_state_version"]) != actual_version:
                raise QueueCorruptionError("job and current attempt versions diverged")

            # Assemble current state once so the sqlite job queue transition with barrier
            # workflow shares one value.
            current_state = _parse_state(row["state"])
            if job_state is not current_state:
                raise QueueCorruptionError("job and current attempt states diverged")
            if new_state not in _LEGAL_TRANSITIONS.get(current_state, frozenset()):
                raise JobStateConflictError(job_id, current_state, "transition")
            # Guard this path with new_state is AttemptState.SUCCEEDED before applying
            # effects.
            if new_state is AttemptState.SUCCEEDED:
                # Handle the sqlite job queue transition with barrier new_state is
                # AttemptState.SUCCEEDED branch as a distinct logical block.
                if result_artifact_id is None:
                    raise ValueError("SUCCEEDED requires result_artifact_id")
                if bool(row["cancel_requested"]):
                    raise JobStateConflictError(job_id, current_state, "transition")
                assert completion_receipt is not None
                # Evaluate the complete sqlite job queue transition with barrier hex,
                # resolved spec id and spec id condition before guarded effects.
                if completion_receipt.resolved_spec_id.hex != _spec_from_job_row(row).spec_id.hex:
                    raise JobStateConflictError(job_id, current_state, "transition")
            # Handle the sqlite job queue transition with barrier complement of new_state
            # is AttemptState.SUCCEEDED explicitly.
            elif result_artifact_id is not None:
                raise ValueError("result_artifact_id is only valid for SUCCEEDED")
            if new_state is AttemptState.CANCELLED and not bool(row["cancel_requested"]):
                raise JobStateConflictError(job_id, current_state, "transition")

            next_version = actual_version + 1
            # Assemble now once so the sqlite job queue transition with barrier workflow
            # shares one value.
            now = time.time_ns() if now_ns is None else now_ns
            changed_attempt = connection.execute(
                """
                UPDATE job_attempts
                SET state = ?, state_version = ?, result_artifact_id = ?, updated_at_ns = ?
                WHERE attempt_id = ? AND state_version = ?
                """,
                (
                    new_state.value,
                    # Pass next version explicitly so execute receives a reviewable value
                    # and str input in sqlite job queue transition with barrier.
                    next_version,
                    None if result_artifact_id is None else str(result_artifact_id),
                    now,
                    str(attempt_id),
                    expected_version,
                    # Complete execute only after its value and str inputs are visible in
                    # sqlite job queue transition with barrier.
                ),
            ).rowcount
            changed_job = connection.execute(
                """
                UPDATE jobs
                SET state = ?, state_version = ?, updated_at_ns = ?
                WHERE job_id = ? AND current_attempt_id = ? AND state_version = ?
                  AND (? <> 'SUCCEEDED' OR cancel_requested = 0)
                """,
                (
                    # Pass new state explicitly so execute receives a reviewable job id
                    # and value input in sqlite job queue transition with barrier.
                    new_state.value,
                    next_version,
                    now,
                    row["job_id"],
                    str(attempt_id),
                    # Pass expected version explicitly so execute receives a reviewable
                    # job id and value input in sqlite job queue transition with barrier.
                    expected_version,
                    new_state.value,
                ),
            ).rowcount
            if changed_attempt != 1 or changed_job != 1:
                # Fail the sqlite job queue transition with barrier path with
                # JobStateConflictError for transition and job id when changed attempt and
                # changed job is true; do not continue ambiguously.
                raise JobStateConflictError(job_id, current_state, "transition")
            if completion_receipt is not None:
                # Handle the sqlite job queue transition with barrier completion_receipt
                # is not None branch as a distinct logical block.
                self._index_completion_receipt(
                    connection,
                    completion_receipt,
                    indexed_at_ns=now,
                )
            # Guard this path with new_state in _TERMINAL_STATES before applying effects.
            if new_state in _TERMINAL_STATES:
                # Handle the sqlite job queue transition with barrier new_state in
                # _TERMINAL_STATES branch as a distinct logical block.
                connection.execute(
                    "DELETE FROM attempt_runtime WHERE attempt_id = ?",
                    (str(attempt_id),),
                )
            _append_job_event(
                # Pass connection explicitly so _append_job_event receives a reviewable
                # attempt and value input in sqlite job queue transition with barrier.
                connection,
                job_id=job_id,
                attempt_id=attempt_id,
                event_type=f"ATTEMPT_{new_state.value}",
                state_version=next_version,
                # Pass created at ns explicitly so _append_job_event receives a reviewable
                # attempt and value input in sqlite job queue transition with barrier.
                created_at_ns=now,
            )

            return JobAttempt(
                attempt_id=attempt_id,
                job_id=job_id,
                # Include spec in the completed sqlite job queue transition with barrier
                # result.
                spec=deserialize_job_spec(bytes(row["resolved_spec"])),
                state=new_state,
                state_version=next_version,
            )

    def register_process(
        # Keep the remaining register process inputs visible at the sqlite job queue
        # register process boundary.
        self,
        claimed: ClaimedAttempt,
        handle: ProcessHandle,
        policy: JobExecutionPolicy,
        *,
        # Keep the supervisor instance id input explicit in the register process contract.
        supervisor_instance_id: str,
        now_ns: int,
    ) -> SupervisorAttempt:
        # Execute the sqlite job queue register process workflow in explicit, reviewable
        # steps.
        supervisor_id = _validate_non_empty(
            supervisor_instance_id,
            field="supervisor_instance_id",
            max_length=256,
        )
        # Assemble start token once so the sqlite job queue register process workflow
        # shares one value.
        start_token = _validate_non_empty(
            handle.start_token,
            field="process_start_token",
            max_length=512,
        )
        # Guard this path with handle.process_id <= 0 before applying effects.
        if handle.process_id <= 0:
            raise ValueError("process_id must be positive")
        if now_ns < 0:
            raise ValueError("now_ns must be non-negative")

        attempt = claimed.attempt
        # Acquire transaction at an explicit sqlite job queue register process context
        # boundary so cleanup remains scoped.
        with self._transaction(immediate=True) as connection:
            # Keep transaction active only for the bounded sqlite job queue register
            # process operation.
            row = connection.execute(
                """
                SELECT
                    a.*, j.current_attempt_id, j.cancel_requested,
                    j.state AS job_state, j.state_version AS job_state_version,
                    j.resolved_spec
                FROM job_attempts AS a
                JOIN jobs AS j ON j.job_id = a.job_id
                WHERE a.attempt_id = ?
                """,
                (str(attempt.attempt_id),),
            ).fetchone()
            if row is None:
                # Fail the sqlite job queue register process path with
                # AttemptNotFoundError for attempt id and attempt when row is true; do not
                # continue ambiguously.
                raise AttemptNotFoundError(attempt.attempt_id)
            job_id = JobId(row["job_id"])
            _require_current_attempt(
                row,
                attempt_id=attempt.attempt_id,
                # Pass expected version explicitly so _require_current_attempt receives a
                # reviewable register process and attempt id input in sqlite job queue
                # register process.
                expected_version=attempt.state_version,
                expected_state=AttemptState.STARTING,
                operation="register process",
            )
            if row["supervisor_instance_id"] != supervisor_id:
                # Fail the sqlite job queue register process path with
                # JobStateConflictError for register process and starting when supervisor
                # id, row and supervisor instance id is true; do not continue ambiguously.
                raise JobStateConflictError(job_id, AttemptState.STARTING, "register process")
            if int(row["attempt_number"]) != claimed.attempt_number:
                raise QueueCorruptionError("claimed attempt number changed")
            if bool(row["cancel_requested"]):
                raise JobStateConflictError(job_id, AttemptState.STARTING, "register process")

            # Assemble next version once so the sqlite job queue register process workflow
            # shares one value.
            next_version = attempt.state_version + 1
            lease_expires_at_ns = now_ns + policy.lease_duration_ns
            deadline_at_ns = now_ns + policy.timeout_ns
            connection.execute(
                """
                INSERT INTO attempt_runtime (
                    attempt_id, supervisor_instance_id, process_id,
                    process_start_token, lane, private_memory_bytes,
                    native_threads, io_units, temporary_disk_bytes,
                    output_disk_bytes, registered_at_ns,
                    heartbeat_at_ns, lease_expires_at_ns, deadline_at_ns
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                # Open the process id and value payload explicitly for execute within
                # sqlite job queue register process.
                (
                    str(attempt.attempt_id),
                    supervisor_id,
                    handle.process_id,
                    start_token,
                    # Pass policy explicitly so execute receives a reviewable process id
                    # and value input in sqlite job queue register process.
                    policy.lane.value,
                    policy.demand.private_memory_bytes,
                    policy.demand.native_threads,
                    policy.demand.io_units,
                    policy.demand.temporary_disk_bytes,
                    # Pass policy explicitly so execute receives a reviewable process id
                    # and value input in sqlite job queue register process.
                    policy.demand.output_disk_bytes,
                    now_ns,
                    now_ns,
                    lease_expires_at_ns,
                    deadline_at_ns,
                    # Complete execute only after its process id and value inputs are visible
                    # in sqlite job queue register process.
                ),
            )
            changed_attempt = connection.execute(
                """
                UPDATE job_attempts
                SET state = ?, state_version = ?, updated_at_ns = ?
                WHERE attempt_id = ? AND state = ? AND state_version = ?
                """,
                (
                    # Pass attempt state explicitly so execute receives a reviewable value
                    # and state version input in sqlite job queue register process.
                    AttemptState.RUNNING.value,
                    next_version,
                    now_ns,
                    str(attempt.attempt_id),
                    AttemptState.STARTING.value,
                    # Pass attempt explicitly so execute receives a reviewable value and
                    # state version input in sqlite job queue register process.
                    attempt.state_version,
                ),
            ).rowcount
            changed_job = connection.execute(
                """
                UPDATE jobs
                SET state = ?, state_version = ?, updated_at_ns = ?
                WHERE job_id = ? AND current_attempt_id = ?
                  AND state = ? AND state_version = ? AND cancel_requested = 0
                """,
                # Open the value and state version payload explicitly for execute within
                # sqlite job queue register process.
                (
                    AttemptState.RUNNING.value,
                    next_version,
                    now_ns,
                    str(job_id),
                    # Keep the attempt id str step visible while building changed job.
                    str(attempt.attempt_id),
                    AttemptState.STARTING.value,
                    attempt.state_version,
                ),
            ).rowcount
            # Evaluate the complete sqlite job queue register process changed attempt and
            # changed job condition before guarded effects.
            if changed_attempt != 1 or changed_job != 1:
                raise JobStateConflictError(job_id, AttemptState.STARTING, "register process")
            _append_job_event(
                connection,
                job_id=job_id,
                # Pass attempt id explicitly so _append_job_event receives a reviewable
                # attempt running and attempt id input in sqlite job queue register
                # process.
                attempt_id=attempt.attempt_id,
                event_type="ATTEMPT_RUNNING",
                state_version=next_version,
                created_at_ns=now_ns,
            )

        # Assemble running once so the sqlite job queue register process workflow shares
        # one value.
        running = JobAttempt(
            attempt_id=attempt.attempt_id,
            job_id=job_id,
            spec=attempt.spec,
            state=AttemptState.RUNNING,
            # Pass state version explicitly so JobAttempt receives a reviewable attempt id
            # and spec input in sqlite job queue register process.
            state_version=next_version,
        )
        return SupervisorAttempt(
            attempt=running,
            attempt_number=claimed.attempt_number,
            # Pass supervisor instance id explicitly so SupervisorAttempt receives a
            # reviewable attempt number and lane input in sqlite job queue register
            # process.
            supervisor_instance_id=supervisor_id,
            handle=handle,
            lane=policy.lane,
            demand=policy.demand,
            heartbeat_at_ns=now_ns,
            # Pass lease expires at ns explicitly so SupervisorAttempt receives a
            # reviewable attempt number and lane input in sqlite job queue register
            # process.
            lease_expires_at_ns=lease_expires_at_ns,
            deadline_at_ns=deadline_at_ns,
        )

    def heartbeat(
        self,
        # Keep the attempt id input explicit in the heartbeat contract.
        attempt_id: AttemptId,
        expected_version: int,
        *,
        supervisor_instance_id: str,
        now_ns: int,
        # Keep the lease duration ns input explicit in the heartbeat contract.
        lease_duration_ns: int,
    ) -> None:
        # Execute the sqlite job queue heartbeat workflow in explicit, reviewable steps.
        supervisor_id = _validate_non_empty(
            supervisor_instance_id,
            field="supervisor_instance_id",
            max_length=256,
        )
        # Guard this path with now_ns < 0 or lease_duration_ns <= 0 before applying
        # effects.
        if now_ns < 0 or lease_duration_ns <= 0:
            raise ValueError("heartbeat time must be non-negative and lease positive")
        with self._transaction(immediate=True) as connection:
            # Keep transaction active only for the bounded sqlite job queue heartbeat
            # operation.
            row = connection.execute(
                """
                SELECT a.job_id, a.state, a.state_version,
                       j.current_attempt_id, j.state AS job_state,
                       j.state_version AS job_state_version
                FROM job_attempts AS a
                JOIN jobs AS j ON j.job_id = a.job_id
                WHERE a.attempt_id = ?
                """,
                (str(attempt_id),),
            ).fetchone()
            if row is None:
                # Fail the sqlite job queue heartbeat path with AttemptNotFoundError for
                # attempt id when row is true; do not continue ambiguously.
                raise AttemptNotFoundError(attempt_id)
            _require_current_attempt(
                row,
                attempt_id=attempt_id,
                expected_version=expected_version,
                # Pass expected state explicitly so _require_current_attempt receives a
                # reviewable heartbeat and running input in sqlite job queue heartbeat.
                expected_state=AttemptState.RUNNING,
                operation="heartbeat",
            )
            changed = connection.execute(
                """
                UPDATE attempt_runtime
                SET heartbeat_at_ns = ?, lease_expires_at_ns = ?
                WHERE attempt_id = ? AND supervisor_instance_id = ?
                """,
                # Open the str and now ns payload explicitly for execute within sqlite job
                # queue heartbeat.
                (
                    now_ns,
                    now_ns + lease_duration_ns,
                    str(attempt_id),
                    supervisor_id,
                    # Complete execute only after its str and now ns inputs are visible in
                    # sqlite job queue heartbeat.
                ),
            ).rowcount
            if changed != 1:
                raise QueueCorruptionError("running attempt has no matching process lease")

    def record_progress(
        # Keep the remaining record progress inputs visible at the sqlite job queue record
        # progress boundary.
        self,
        attempt_id: AttemptId,
        expected_version: int,
        details: JobProgressDetails,
        *,
        # Keep the supervisor instance id input explicit in the record progress contract.
        supervisor_instance_id: str,
        now_ns: int,
    ) -> None:
        """Persist one coalesced safe frame in a short supervisor transaction."""

        supervisor_id = _validate_non_empty(
            supervisor_instance_id,
            field="supervisor_instance_id",
            max_length=256,
        )
        # Guard this path with now_ns < 0 before applying effects.
        if now_ns < 0:
            raise ValueError("progress timestamp must be non-negative")
        payload = serialize_progress_details(details)
        with self._transaction(immediate=True) as connection:
            # Keep transaction active only for the bounded sqlite job queue record
            # progress operation.
            row = connection.execute(
                """
                SELECT a.job_id, a.state, a.state_version,
                       j.current_attempt_id, j.state AS job_state,
                       j.state_version AS job_state_version,
                       r.supervisor_instance_id AS runtime_supervisor_instance_id
                FROM job_attempts AS a
                JOIN jobs AS j ON j.job_id = a.job_id
                JOIN attempt_runtime AS r ON r.attempt_id = a.attempt_id
                WHERE a.attempt_id = ?
                """,
                (str(attempt_id),),
            ).fetchone()
            if row is None:
                # Fail the sqlite job queue record progress path with AttemptNotFoundError
                # for attempt id when row is true; do not continue ambiguously.
                raise AttemptNotFoundError(attempt_id)
            _require_current_attempt(
                row,
                attempt_id=attempt_id,
                expected_version=expected_version,
                # Pass expected state explicitly so _require_current_attempt receives a
                # reviewable record progress and running input in sqlite job queue record
                # progress.
                expected_state=AttemptState.RUNNING,
                operation="record progress",
            )
            job_id = JobId(str(row["job_id"]))
            if str(row["runtime_supervisor_instance_id"]) != supervisor_id:
                # Fail the sqlite job queue record progress path with
                # JobStateConflictError for record progress and running when supervisor
                # id, row and runtime supervisor instance id is true; do not continue
                # ambiguously.
                raise JobStateConflictError(job_id, AttemptState.RUNNING, "record progress")
            previous = connection.execute(
                """
                SELECT details FROM job_events
                WHERE attempt_id = ? AND event_type = 'ATTEMPT_PROGRESS'
                ORDER BY event_id DESC
                LIMIT 1
                """,
                (str(attempt_id),),
            ).fetchone()
            # Guard this path with previous is not None before applying effects.
            if previous is not None:
                # Handle the sqlite job queue record progress previous is not None branch
                # as a distinct logical block.
                previous_payload = previous["details"]
                if previous_payload is None:
                    raise QueueCorruptionError("stored progress event has no details")
                previous_details = deserialize_progress_details(bytes(previous_payload))
                if details.sequence <= previous_details.sequence:
                    # Fail the sqlite job queue record progress path with ValueError for
                    # progress sequence must increase within an attempt when sequence,
                    # details and previous details is true; do not continue ambiguously.
                    raise ValueError("progress sequence must increase within an attempt")
            _append_job_event(
                connection,
                job_id=job_id,
                attempt_id=attempt_id,
                # Pass event type explicitly so _append_job_event receives a reviewable
                # attempt progress and connection input in sqlite job queue record
                # progress.
                event_type="ATTEMPT_PROGRESS",
                state_version=expected_version,
                created_at_ns=now_ns,
                details=payload,
            )
            # Invoke execute for str and max progress events per attempt as a visible
            # sqlite job queue record progress step.
            connection.execute(
                """
                DELETE FROM job_events
                WHERE event_id IN (
                    SELECT event_id FROM job_events
                    WHERE attempt_id = ? AND event_type = 'ATTEMPT_PROGRESS'
                    ORDER BY event_id DESC
                    LIMIT -1 OFFSET ?
                )
                """,
                (str(attempt_id), _MAX_PROGRESS_EVENTS_PER_ATTEMPT),
            )

    def list_unfinished_attempts(self) -> tuple[SupervisorAttempt, ...]:
        # Execute the sqlite job queue list unfinished attempts workflow in explicit,
        # reviewable steps.
        with self._connection() as connection:
            # Keep connection active only for the bounded sqlite job queue list unfinished
            # attempts operation.
            rows = connection.execute(
                """
                SELECT
                    a.*, j.current_attempt_id,
                    j.state AS job_state, j.state_version AS job_state_version,
                    j.resolved_spec,
                    r.supervisor_instance_id AS runtime_supervisor_instance_id,
                    r.process_id, r.process_start_token, r.lane,
                    r.private_memory_bytes, r.native_threads, r.io_units,
                    r.temporary_disk_bytes, r.output_disk_bytes,
                    r.heartbeat_at_ns, r.lease_expires_at_ns, r.deadline_at_ns
                FROM job_attempts AS a
                JOIN jobs AS j ON j.job_id = a.job_id
                LEFT JOIN attempt_runtime AS r ON r.attempt_id = a.attempt_id
                WHERE a.state IN (?, ?)
                  AND j.current_attempt_id = a.attempt_id
                ORDER BY a.created_at_ns, a.attempt_id
                """,
                (AttemptState.STARTING.value, AttemptState.RUNNING.value),
            ).fetchall()

        records: list[SupervisorAttempt] = []
        # Traverse rows explicitly so each sqlite job queue list unfinished attempts
        # iteration remains traceable.
        for row in rows:
            # Process rows inside the bounded sqlite job queue list unfinished attempts
            # loop.
            state = _parse_state(row["state"])
            attempt_id = AttemptId(row["attempt_id"])
            _require_current_attempt(
                row,
                attempt_id=attempt_id,
                # Pass expected version explicitly to _require_current_attempt for state
                # version and list unfinished attempts.
                expected_version=int(row["state_version"]),
                expected_state=state,
                operation="list unfinished attempts",
            )
            has_runtime = row["process_id"] is not None
            # Evaluate the complete sqlite job queue list unfinished attempts has runtime,
            # state and running condition before guarded effects.
            if (state is AttemptState.RUNNING) != has_runtime:
                raise QueueCorruptionError("unfinished attempt process metadata is inconsistent")
            attempt = JobAttempt(
                attempt_id=attempt_id,
                job_id=JobId(row["job_id"]),
                # Keep the deserialize job spec and bytes deserialize_job_spec step
                # visible while building attempt.
                spec=deserialize_job_spec(bytes(row["resolved_spec"])),
                state=state,
                state_version=int(row["state_version"]),
            )
            if has_runtime:
                # Handle the sqlite job queue list unfinished attempts has_runtime branch
                # as a distinct logical block.
                runtime_supervisor_id = str(row["runtime_supervisor_instance_id"])
                if runtime_supervisor_id != row["supervisor_instance_id"]:
                    raise QueueCorruptionError("attempt and runtime supervisor IDs disagree")
                record = SupervisorAttempt(
                    attempt=attempt,
                    # Keep the row and attempt number int step visible while building
                    # record.
                    attempt_number=int(row["attempt_number"]),
                    supervisor_instance_id=runtime_supervisor_id,
                    handle=ProcessHandle(
                        process_id=int(row["process_id"]),
                        start_token=str(row["process_start_token"]),
                        # Complete ProcessHandle only after its process id and process start
                        # token inputs are visible in sqlite job queue list unfinished
                        # attempts.
                    ),
                    lane=JobLane(str(row["lane"])),
                    demand=JobResourceDemand(
                        private_memory_bytes=int(row["private_memory_bytes"]),
                        native_threads=int(row["native_threads"]),
                        # Keep the row and io units int step visible while building
                        # record.
                        io_units=int(row["io_units"]),
                        temporary_disk_bytes=int(row["temporary_disk_bytes"]),
                        output_disk_bytes=int(row["output_disk_bytes"]),
                    ),
                    heartbeat_at_ns=int(row["heartbeat_at_ns"]),
                    # Keep the row and lease expires at ns int step visible while building
                    # record.
                    lease_expires_at_ns=int(row["lease_expires_at_ns"]),
                    deadline_at_ns=int(row["deadline_at_ns"]),
                )
            else:
                # Handle the sqlite job queue list unfinished attempts complement of
                # has_runtime explicitly.
                record = SupervisorAttempt(
                    attempt=attempt,
                    attempt_number=int(row["attempt_number"]),
                    supervisor_instance_id=str(row["supervisor_instance_id"]),
                    handle=None,
                    # Pass lane explicitly so SupervisorAttempt receives a reviewable
                    # attempt number and supervisor instance id input in sqlite job queue
                    # list unfinished attempts.
                    lane=None,
                    demand=None,
                    heartbeat_at_ns=None,
                    lease_expires_at_ns=None,
                    deadline_at_ns=None,
                    # Complete SupervisorAttempt only after its attempt number and supervisor
                    # instance id inputs are visible in sqlite job queue list unfinished
                    # attempts.
                )
            records.append(record)
        return tuple(records)

    def finish_unsuccessful(
        self,
        # Keep the attempt id input explicit in the finish unsuccessful contract.
        attempt_id: AttemptId,
        expected_version: int,
        failure: AttemptFailure,
        *,
        retry_not_before_ns: int | None,
        # Keep the now ns input explicit in the finish unsuccessful contract.
        now_ns: int,
    ) -> AttemptFinish:
        # Execute the sqlite job queue finish unsuccessful workflow in explicit,
        # reviewable steps.
        with self._backup_cut_barrier():
            # Keep backup cut barrier active only for the bounded sqlite job queue finish
            # unsuccessful operation.
            return self._finish_unsuccessful_with_barrier(
                attempt_id,
                expected_version,
                failure,
                retry_not_before_ns=retry_not_before_ns,
                # Pass now ns explicitly so _finish_unsuccessful_with_barrier receives a
                # reviewable attempt id and expected version input in sqlite job queue
                # finish unsuccessful.
                now_ns=now_ns,
            )

    def _finish_unsuccessful_with_barrier(
        self,
        attempt_id: AttemptId,
        # Keep the expected version input explicit in the finish unsuccessful with barrier
        # contract.
        expected_version: int,
        failure: AttemptFailure,
        *,
        retry_not_before_ns: int | None,
        now_ns: int,
        # Keep the attempt finish input explicit in the finish unsuccessful with barrier
        # contract.
    ) -> AttemptFinish:
        # Execute the sqlite job queue finish unsuccessful with barrier workflow in
        # explicit, reviewable steps.
        if now_ns < 0:
            raise ValueError("now_ns must be non-negative")
        if retry_not_before_ns is not None and retry_not_before_ns < now_ns:
            raise ValueError("retry_not_before_ns cannot be in the past")

        with self._transaction(immediate=True) as connection:
            # Keep transaction active only for the bounded sqlite job queue finish
            # unsuccessful with barrier operation.
            row = connection.execute(
                """
                SELECT
                    a.*, j.current_attempt_id, j.cancel_requested,
                    j.state AS job_state, j.state_version AS job_state_version,
                    j.resolved_spec
                FROM job_attempts AS a
                JOIN jobs AS j ON j.job_id = a.job_id
                WHERE a.attempt_id = ?
                """,
                (str(attempt_id),),
            ).fetchone()
            if row is None:
                # Fail the sqlite job queue finish unsuccessful with barrier path with
                # AttemptNotFoundError for attempt id when row is true; do not continue
                # ambiguously.
                raise AttemptNotFoundError(attempt_id)
            current_state = _parse_state(row["state"])
            if current_state not in (AttemptState.STARTING, AttemptState.RUNNING):
                # Handle the sqlite job queue finish unsuccessful with barrier current
                # state, starting and running condition as a distinct block.
                raise JobStateConflictError(
                    JobId(row["job_id"]), current_state, "finish unsuccessful attempt"
                )
            _require_current_attempt(
                row,
                # Pass attempt id explicitly so _require_current_attempt receives a
                # reviewable finish unsuccessful attempt and row input in sqlite job queue
                # finish unsuccessful with barrier.
                attempt_id=attempt_id,
                expected_version=expected_version,
                expected_state=current_state,
                operation="finish unsuccessful attempt",
            )
            # Assemble job id once so the sqlite job queue finish unsuccessful with
            # barrier workflow shares one value.
            job_id = JobId(row["job_id"])
            cancel_requested = bool(row["cancel_requested"])
            effective_retry_at = None if cancel_requested else retry_not_before_ns
            terminal_state = (
                AttemptState.CANCELLED
                # Keep the cancel requested component named inside the terminal state
                # contract.
                if cancel_requested
                else (
                    AttemptState.INTERRUPTED
                    if failure.kind is AttemptFailureKind.ORPHANED
                    else AttemptState.FAILED
                    # Complete the terminal state group only after its semantic components are
                    # visible.
                )
            )
            next_version = expected_version + 1
            changed_attempt = connection.execute(
                """
                UPDATE job_attempts
                SET state = ?, state_version = ?, updated_at_ns = ?
                WHERE attempt_id = ? AND state = ? AND state_version = ?
                """,
                # Open the value and str payload explicitly for execute within sqlite job
                # queue finish unsuccessful with barrier.
                (
                    terminal_state.value,
                    next_version,
                    now_ns,
                    str(attempt_id),
                    # Pass current state explicitly so execute receives a reviewable value
                    # and str input in sqlite job queue finish unsuccessful with barrier.
                    current_state.value,
                    expected_version,
                ),
            ).rowcount
            if effective_retry_at is None:
                # Handle the sqlite job queue finish unsuccessful with barrier
                # effective_retry_at is None branch as a distinct logical block.
                changed_job = connection.execute(
                    """
                    UPDATE jobs
                    SET state = ?, state_version = ?, updated_at_ns = ?
                    WHERE job_id = ? AND current_attempt_id = ? AND state_version = ?
                    """,
                    (
                        terminal_state.value,
                        next_version,
                        # Pass now ns explicitly so execute receives a reviewable value
                        # and str input in sqlite job queue finish unsuccessful with
                        # barrier.
                        now_ns,
                        str(job_id),
                        str(attempt_id),
                        expected_version,
                    ),
                    # Complete execute only after its value and str inputs are visible in
                    # sqlite job queue finish unsuccessful with barrier.
                ).rowcount
            else:
                # Handle the sqlite job queue finish unsuccessful with barrier complement
                # of effective_retry_at is None explicitly.
                changed_job = connection.execute(
                    """
                    UPDATE jobs
                    SET state = ?, state_version = ?, current_attempt_id = NULL,
                        updated_at_ns = ?
                    WHERE job_id = ? AND current_attempt_id = ? AND state_version = ?
                      AND cancel_requested = 0
                    """,
                    (
                        AttemptState.QUEUED.value,
                        next_version,
                        # Pass now ns explicitly so execute receives a reviewable value
                        # and queued input in sqlite job queue finish unsuccessful with
                        # barrier.
                        now_ns,
                        str(job_id),
                        str(attempt_id),
                        expected_version,
                    ),
                    # Complete execute only after its value and queued inputs are visible in
                    # sqlite job queue finish unsuccessful with barrier.
                ).rowcount
            if changed_attempt != 1 or changed_job != 1:
                raise JobStateConflictError(job_id, current_state, "finish unsuccessful attempt")
            connection.execute(
                "DELETE FROM attempt_runtime WHERE attempt_id = ?",
                # Pass str explicitly to execute for delete from attempt runtime where
                # attempt id = ? and str.
                (str(attempt_id),),
            )
            connection.execute(
                """
                INSERT INTO attempt_failures (
                    attempt_id, failure_kind, failure_code, retry_scheduled,
                    retry_not_before_ns, recorded_at_ns
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    # Pass str explicitly to execute for value and kind.
                    str(attempt_id),
                    failure.kind.value,
                    failure.code.value,
                    int(effective_retry_at is not None),
                    effective_retry_at,
                    # Pass now ns explicitly so execute receives a reviewable value and
                    # kind input in sqlite job queue finish unsuccessful with barrier.
                    now_ns,
                ),
            )
            if effective_retry_at is not None:
                # Handle the sqlite job queue finish unsuccessful with barrier
                # effective_retry_at is not None branch as a distinct logical block.
                connection.execute(
                    """
                    INSERT INTO job_retry_schedule (
                        job_id, previous_attempt_id, not_before_ns, created_at_ns
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (str(job_id), str(attempt_id), effective_retry_at, now_ns),
                )
            _append_job_event(
                # Pass connection explicitly so _append_job_event receives a reviewable
                # attempt and value input in sqlite job queue finish unsuccessful with
                # barrier.
                connection,
                job_id=job_id,
                attempt_id=attempt_id,
                event_type=f"ATTEMPT_{terminal_state.value}",
                state_version=next_version,
                # Pass created at ns explicitly so _append_job_event receives a reviewable
                # attempt and value input in sqlite job queue finish unsuccessful with
                # barrier.
                created_at_ns=now_ns,
            )
            if effective_retry_at is not None:
                # Handle the sqlite job queue finish unsuccessful with barrier
                # effective_retry_at is not None branch as a distinct logical block.
                _append_job_event(
                    connection,
                    job_id=job_id,
                    attempt_id=attempt_id,
                    event_type="JOB_RETRY_SCHEDULED",
                    # Pass state version explicitly so _append_job_event receives a
                    # reviewable job retry scheduled and connection input in sqlite job
                    # queue finish unsuccessful with barrier.
                    state_version=next_version,
                    created_at_ns=now_ns,
                )

        finished = JobAttempt(
            attempt_id=attempt_id,
            # Pass job id explicitly so JobAttempt receives a reviewable resolved spec and
            # deserialize job spec input in sqlite job queue finish unsuccessful with
            # barrier.
            job_id=job_id,
            spec=deserialize_job_spec(bytes(row["resolved_spec"])),
            state=terminal_state,
            state_version=next_version,
        )
        # Return the completed sqlite job queue finish unsuccessful with barrier result
        # without a hidden fallback.
        return AttemptFinish(
            attempt=finished,
            retry_scheduled=effective_retry_at is not None,
            retry_not_before_ns=effective_retry_at,
        )

    # Define sqlite job queue get job as one focused operation with an explicit boundary.
    def get_job(self, job_id: JobId) -> JobRecord | None:
        # Execute the sqlite job queue get job workflow in explicit, reviewable steps.
        with self._connection() as connection:
            # Keep connection active only for the bounded sqlite job queue get job
            # operation.
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?",
                (str(job_id),),
            ).fetchone()
        return None if row is None else _job_from_row(row)

    # Operational result lookup never marks missing filesystem bytes as committed.
    def get_successful_result(self, job_id: JobId) -> ArtifactId | None:
        """Return only the current successful attempt's candidate, not artifact authority."""

        with self._connection() as connection:
            row = connection.execute(
                "SELECT a.result_artifact_id FROM jobs j JOIN job_attempts a "
                "ON a.job_id=j.job_id AND a.state_version=j.state_version "
                # A stale, cancelled or failed attempt cannot expose another attempt's result.
                "WHERE j.job_id=? AND j.state='SUCCEEDED' AND a.state='SUCCEEDED' "
                "ORDER BY a.attempt_number DESC LIMIT 1",
                (job_id.value,),
            ).fetchone()
        return None if row is None or row[0] is None else ArtifactId(row[0])

    # Define sqlite job queue list jobs as one focused operation with an explicit
    # boundary.
    def list_jobs(
        self,
        *,
        state: AttemptState | None = None,
        limit: int = 100,
        # Keep the offset input explicit in the list jobs contract.
        offset: int = 0,
        after: JobListCursor | None = None,
    ) -> tuple[JobRecord, ...]:
        # Execute the sqlite job queue list jobs workflow in explicit, reviewable steps.
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an integer")
        if not 1 <= limit <= _MAX_JOB_QUERY_ROWS:
            raise ValueError("limit must be between 1 and 1001")
        # Bound legacy scans and forbid mixing positional and keyset pagination.
        if isinstance(offset, bool) or not isinstance(offset, int):
            raise TypeError("offset must be an integer")
        if not 0 <= offset <= _MAX_JOB_QUERY_OFFSET:
            raise ValueError("offset must be between 0 and 10000")
        if after is not None and (offset != 0 or after.state is not state):
            raise ValueError("job cursor must match the filter and cannot use offset")
        with self._connection() as connection:
            # Keep connection active only for the bounded sqlite job queue list jobs
            # operation.
            if state is None and after is None:
                # Handle the sqlite job queue list jobs state is None branch as a distinct
                # logical block.
                rows = connection.execute(
                    """
                    SELECT * FROM jobs
                    ORDER BY submitted_at_ns DESC, job_id DESC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                ).fetchall()
            elif state is not None and after is None:
                # Apply state filtering before the bounded legacy page offset.
                rows = connection.execute(
                    """
                    SELECT * FROM jobs
                    WHERE state = ?
                    ORDER BY submitted_at_ns DESC, job_id DESC
                    LIMIT ? OFFSET ?
                    """,
                    (state.value, limit, offset),
                ).fetchall()
            elif state is None:
                # Descending tuple comparison resumes strictly after the prior row.
                assert after is not None
                rows = connection.execute(
                    """
                    SELECT * FROM jobs
                    WHERE submitted_at_ns < ?
                       OR (submitted_at_ns = ? AND job_id < ?)
                    ORDER BY submitted_at_ns DESC, job_id DESC
                    LIMIT ?
                    """,
                    (
                        after.submitted_at_ns,
                        after.submitted_at_ns,
                        after.job_id.value,
                        limit,
                    ),
                ).fetchall()
            else:
                # The cursor scope and SQL state predicate remain identical.
                assert after is not None
                rows = connection.execute(
                    """
                    SELECT * FROM jobs
                    WHERE state = ?
                      AND (submitted_at_ns < ?
                       OR (submitted_at_ns = ? AND job_id < ?))
                    ORDER BY submitted_at_ns DESC, job_id DESC
                    LIMIT ?
                    """,
                    (
                        state.value,
                        after.submitted_at_ns,
                        after.submitted_at_ns,
                        after.job_id.value,
                        limit,
                    ),
                ).fetchall()
        return tuple(_job_from_row(row) for row in rows)

    # Define sqlite job queue list job events as one focused operation with an explicit
    # boundary.
    def list_job_events(
        self,
        job_id: JobId,
        *,
        after_event_id: int = 0,
        # Keep the limit input explicit in the list job events contract.
        limit: int = 200,
    ) -> tuple[JobEventRecord, ...]:
        # Execute the sqlite job queue list job events workflow in explicit, reviewable
        # steps.
        if after_event_id < 0:
            raise ValueError("after_event_id must be non-negative")
        if not 1 <= limit <= 1_000:
            raise ValueError("job event limit must be between 1 and 1000")
        with self._connection() as connection:
            # Keep connection active only for the bounded sqlite job queue list job events
            # operation.
            rows = connection.execute(
                """
                SELECT event_id, job_id, attempt_id, event_type,
                       state_version, created_at_ns, details
                FROM job_events
                WHERE job_id = ? AND event_id > ?
                ORDER BY event_id
                LIMIT ?
                """,
                (str(job_id), after_event_id, limit),
            ).fetchall()
        return tuple(_job_event_from_row(row) for row in rows)

    # Define sqlite job queue is cancel requested as one focused operation with an
    # explicit boundary.
    def is_cancel_requested(self, job_id: JobId) -> bool:
        # Execute the sqlite job queue is cancel requested workflow in explicit,
        # reviewable steps.
        with self._connection() as connection:
            # Keep connection active only for the bounded sqlite job queue is cancel
            # requested operation.
            row = connection.execute(
                "SELECT cancel_requested FROM jobs WHERE job_id = ?",
                (str(job_id),),
            ).fetchone()
        if row is None:
            # Fail the sqlite job queue is cancel requested path with JobNotFoundError for
            # job id when row is true; do not continue ambiguously.
            raise JobNotFoundError(job_id)
        return bool(row["cancel_requested"])

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        # Execute the sqlite job queue connection workflow in explicit, reviewable steps.
        try:
            # Perform the protected sqlite job queue connection operation before explicit
            # failure handling.
            connection = connect(
                self.database_path,
                busy_timeout_seconds=self.busy_timeout_seconds,
            )
        except sqlite3.Error as error:
            # Invoke _raise_safe_sqlite_error for error as a visible sqlite job queue
            # connection step.
            _raise_safe_sqlite_error(error)
        try:
            # Perform the protected sqlite job queue connection operation before explicit
            # failure handling.
            try:
                yield connection
            except sqlite3.Error as error:
                _raise_safe_sqlite_error(error)
        finally:
            # Handle the cleanup path after the protected sqlite job queue connection
            # operation.
            with suppress(sqlite3.Error):
                connection.close()

    @contextmanager
    def _backup_cut_barrier(self) -> Iterator[None]:
        # Execute the sqlite job queue backup cut barrier workflow in explicit, reviewable
        # steps.
        if self._backup_cut_lock_path is None:
            # Handle the sqlite job queue backup cut barrier self._backup_cut_lock_path is
            # None branch as a distinct logical block.
            yield
            return
        with FileLock(
            self._backup_cut_lock_path,
            mode=LockMode.SHARED,
            # Pass timeout explicitly so FileLock receives a reviewable backup cut lock
            # path and shared input in sqlite job queue backup cut barrier.
            timeout=self.busy_timeout_seconds,
        ):
            yield

    @staticmethod
    def _index_completion_receipt(
        # Keep the connection input explicit in the index completion receipt contract.
        connection: sqlite3.Connection,
        receipt: AttemptCompletionReceipt,
        *,
        indexed_at_ns: int,
    ) -> None:
        # Execute the sqlite job queue index completion receipt workflow in explicit,
        # reviewable steps.
        digest = completion_receipt_digest(receipt)
        connection.execute(
            """
            INSERT INTO completion_receipts (
                attempt_id, resolved_spec_id, receipt_digest, indexed_at_ns
            ) VALUES (?, ?, ?, ?)
            """,
            (
                receipt.attempt_id.value,
                # Pass receipt explicitly so execute receives a reviewable value and hex
                # input in sqlite job queue index completion receipt.
                receipt.resolved_spec_id.hex,
                digest.hex,
                indexed_at_ns,
            ),
        )
        # Invoke executemany for value and hex as a visible sqlite job queue index
        # completion receipt step.
        connection.executemany(
            """
            INSERT INTO completion_receipt_outputs (
                attempt_id, artifact_id, manifest_digest, ordinal
            ) VALUES (?, ?, ?, ?)
            """,
            (
                (
                    receipt.attempt_id.value,
                    # Pass output explicitly so executemany receives a reviewable value
                    # and hex input in sqlite job queue index completion receipt.
                    output.artifact_id.hex,
                    output.manifest_digest.hex,
                    ordinal,
                )
                for ordinal, output in enumerate(receipt.outputs)
                # Complete executemany only after its value and hex inputs are visible in
                # sqlite job queue index completion receipt.
            ),
        )

    @contextmanager
    def _transaction(self, *, immediate: bool) -> Iterator[sqlite3.Connection]:
        # Execute the sqlite job queue transaction workflow in explicit, reviewable steps.
        with self._connection() as connection:
            # Keep connection active only for the bounded sqlite job queue transaction
            # operation.
            try:
                # Perform the protected sqlite job queue transaction operation before
                # explicit failure handling.
                connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
                yield connection
                connection.commit()
            except BaseException:
                # Translate the BaseException failure through the sqlite job queue
                # transaction boundary.
                with suppress(sqlite3.Error):
                    connection.rollback()
                raise


def _raise_safe_sqlite_error(error: sqlite3.Error) -> NoReturn:
    """Translate operational SQLite details at the adapter boundary.

    Extended result codes retain their primary code in the low byte.  Busy,
    locked and storage failures are retryable local-state unavailability; no
    SQLite message, path or SQL text crosses into the application transport.
    """

    error_code = getattr(error, "sqlite_errorcode", None)
    primary_code = error_code & 0xFF if isinstance(error_code, int) else None
    if primary_code in _UNAVAILABLE_SQLITE_PRIMARY_CODES:
        raise LocalStateUnavailableError from None
    if primary_code in {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB}:
        # Fail the raise safe sqlite error path with QueueCorruptionError for sqlite job
        # queue integrity verification failed when primary code, sqlite corrupt and sqlite
        # notadb is true; do not continue ambiguously.
        raise QueueCorruptionError("SQLite job queue integrity verification failed") from None
    raise JobQueueError("SQLite job queue operation failed") from None


def _job_from_row(row: sqlite3.Row) -> JobRecord:
    # Execute the job from row workflow in explicit, reviewable steps.
    spec = _spec_from_job_row(row)
    if row["command_type"] != spec.job_type.value:
        raise QueueCorruptionError("job command type does not match serialized spec")
    request_digest = job_spec_request_digest(bytes(row["resolved_spec"]))
    if row["request_digest"] != request_digest:
        # Fail the job from row path with QueueCorruptionError for job request digest does
        # not match serialized spec when request digest and row is true; do not continue
        # ambiguously.
        raise QueueCorruptionError("job request digest does not match serialized spec")
    return JobRecord(
        job_id=JobId(row["job_id"]),
        spec=spec,
        state=_parse_state(row["state"]),
        # Include state version in the completed job from row result.
        state_version=int(row["state_version"]),
        submitted_at_ns=int(row["submitted_at_ns"]),
        updated_at_ns=int(row["updated_at_ns"]),
    )


def _spec_from_job_row(row: sqlite3.Row) -> ResolvedJobSpec:
    return deserialize_job_spec(bytes(row["resolved_spec"]))


def _parse_state(value: Any) -> AttemptState:
    # Execute the parse state workflow in explicit, reviewable steps.
    try:
        # Perform the protected parse state operation before explicit failure handling.
        if not isinstance(value, str):
            raise TypeError("state is not a string")
        return AttemptState(value)
    except (TypeError, ValueError) as exc:
        raise QueueCorruptionError("stored job state is invalid") from exc


# Define require current attempt as one focused operation with an explicit boundary.
def _require_current_attempt(
    row: sqlite3.Row,
    *,
    attempt_id: AttemptId,
    expected_version: int,
    # Keep the expected state input explicit in the require current attempt contract.
    expected_state: AttemptState,
    operation: str,
) -> None:
    # Execute the require current attempt workflow in explicit, reviewable steps.
    job_id = JobId(row["job_id"])
    job_state = _parse_state(row["job_state"])
    attempt_state = _parse_state(row["state"])
    if row["current_attempt_id"] != str(attempt_id):
        raise JobStateConflictError(job_id, job_state, operation)
    # Evaluate the complete require current attempt expected version, row and state
    # version condition before guarded effects.
    if int(row["state_version"]) != expected_version:
        raise JobStateConflictError(job_id, job_state, operation)
    if int(row["job_state_version"]) != expected_version:
        raise QueueCorruptionError("job and current attempt versions diverged")
    if attempt_state is not job_state:
        # Fail the require current attempt path with QueueCorruptionError for job and
        # current attempt states diverged when attempt state and job state is true; do not
        # continue ambiguously.
        raise QueueCorruptionError("job and current attempt states diverged")
    if attempt_state is not expected_state:
        raise JobStateConflictError(job_id, attempt_state, operation)


def _validate_non_empty(value: str, *, field: str, max_length: int) -> str:
    # Execute the validate non empty workflow in explicit, reviewable steps.
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    if not value or value != value.strip():
        raise ValueError(f"{field} must be non-empty and trimmed")
    if len(value) > max_length:
        # Fail the validate non empty path with ValueError for is too long and field when
        # max length and value is true; do not continue ambiguously.
        raise ValueError(f"{field} is too long")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"{field} must not contain control characters")
    return value


def _validate_idempotency_key(value: str) -> str:
    # Execute the validate idempotency key workflow in explicit, reviewable steps.
    try:
        return _validate_non_empty(value, field="idempotency_key", max_length=512)
    except (TypeError, ValueError):
        raise InvalidIdempotencyKeyError from None


def _append_job_event(
    # Keep the connection input explicit in the append job event contract.
    connection: sqlite3.Connection,
    *,
    job_id: JobId,
    attempt_id: AttemptId | None,
    event_type: str,
    # Keep the state version input explicit in the append job event contract.
    state_version: int,
    created_at_ns: int,
    details: bytes | None = None,
) -> None:
    # Execute the append job event workflow in explicit, reviewable steps.
    if (event_type == "ATTEMPT_PROGRESS") != (details is not None):
        raise ValueError("only ATTEMPT_PROGRESS events carry details")
    connection.execute(
        """
        INSERT INTO job_events (
            job_id, attempt_id, event_type,
            state_version, created_at_ns, details
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            # Pass job id explicitly so execute receives a reviewable value and event type
            # input in append job event.
            job_id.value,
            None if attempt_id is None else attempt_id.value,
            event_type,
            state_version,
            created_at_ns,
            # Pass details explicitly so execute receives a reviewable value and event
            # type input in append job event.
            details,
        ),
    )


def _job_event_from_row(row: sqlite3.Row) -> JobEventRecord:
    # Execute the job event from row workflow in explicit, reviewable steps.
    event_type = str(row["event_type"])
    raw_details = row["details"]
    if event_type == "ATTEMPT_PROGRESS":
        # Handle the job event from row event_type == 'ATTEMPT_PROGRESS' branch as a
        # distinct logical block.
        if raw_details is None:
            raise QueueCorruptionError("stored progress event has no details")
        progress = deserialize_progress_details(bytes(raw_details))
    else:
        # Handle the job event from row complement of event_type == 'ATTEMPT_PROGRESS'
        # explicitly.
        if raw_details is not None:
            raise QueueCorruptionError("state event unexpectedly contains progress details")
        progress = None
    return JobEventRecord(
        event_id=int(row["event_id"]),
        # Include job id in the completed job event from row result.
        job_id=JobId(str(row["job_id"])),
        attempt_id=(None if row["attempt_id"] is None else AttemptId(str(row["attempt_id"]))),
        event_type=event_type,
        state_version=int(row["state_version"]),
        created_at_ns=int(row["created_at_ns"]),
        # Pass progress explicitly so JobEventRecord receives a reviewable event id and
        # job id input in job event from row.
        progress=progress,
    )
