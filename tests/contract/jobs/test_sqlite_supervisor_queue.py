# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from backtest.adapters.catalog.sqlite import SQLiteJobQueue
from backtest.adapters.catalog.sqlite.schema import connect

# Import canonical json at the visible module dependency boundary.
from backtest.application.canonical_json import resolved_job_spec_hex
from backtest.application.models import AttemptState, JobType, ProcessHandle, ResolvedJobSpec
from backtest.application.ports.supervisor import SupervisorQueue
from backtest.application.supervisor import (
    AttemptFailure,
    # Include attempt failure code so the supervisor dependency remains explicit.
    AttemptFailureCode,
    AttemptFailureKind,
    JobExecutionPolicy,
    JobLane,
    JobResourceDemand,
    # Include retry policy so the supervisor dependency remains explicit.
    RetryPolicy,
)
from backtest.domain.identifiers import ContentDigest


def _spec(job_type: JobType, fixture: str) -> ResolvedJobSpec:
    # Execute the spec workflow in explicit, reviewable steps.
    payload = f'{{"fixture":"{fixture}"}}'.encode()
    digest = ContentDigest(sha256(payload).hexdigest())
    return ResolvedJobSpec(
        spec_version=1,
        spec_id=ContentDigest(
            # Include resolved job spec hex in the completed spec result.
            resolved_job_spec_hex(
                spec_version=1,
                job_type=job_type.value,
                payload_digest_hex=digest.hex,
                input_artifact_hexes=(),
                # Complete resolved_job_spec_hex only after its value and hex inputs are
                # visible in spec.
            )
        ),
        job_type=job_type,
        canonical_payload=payload,
        payload_digest=digest,
        # Complete ResolvedJobSpec only after its value and hex inputs are visible in spec.
    )


def _policy(lane: JobLane = JobLane.RUN) -> JobExecutionPolicy:
    # Execute the policy workflow in explicit, reviewable steps.
    return JobExecutionPolicy(
        lane=lane,
        demand=JobResourceDemand(
            2_000,
            native_threads=2,
            # Pass io units explicitly into JobResourceDemand within policy.
            io_units=1,
            temporary_disk_bytes=3_000,
            output_disk_bytes=4_000,
        ),
        timeout_ns=10_000,
        # Pass termination grace seconds explicitly so JobExecutionPolicy receives a
        # reviewable transient and job resource demand input in policy.
        termination_grace_seconds=0.25,
        lease_duration_ns=1_000,
        retry=RetryPolicy(
            max_attempts=2,
            retryable_kinds=frozenset({AttemptFailureKind.TRANSIENT}),
            # Pass base backoff ns explicitly so RetryPolicy receives a reviewable
            # transient and frozenset input in policy.
            base_backoff_ns=100,
            max_backoff_ns=100,
        ),
    )


def test_adapter_satisfies_complete_supervisor_queue_protocol(tmp_path: Path) -> None:
    # Verify the isinstance, supervisor queue and sqlite job queue relationship before
    # this scenario is accepted.
    assert isinstance(SQLiteJobQueue(tmp_path / "catalog.sqlite"), SupervisorQueue)


def test_claim_filters_explicit_job_types_without_default_mapping(tmp_path: Path) -> None:
    # Execute the test claim filters explicit job types without default mapping workflow
    # in explicit, reviewable steps.
    queue = SQLiteJobQueue(tmp_path / "catalog.sqlite")
    build = queue.submit(_spec(JobType.PREPARE_DATASET, "build"), "build")
    run = queue.submit(_spec(JobType.RUN_BACKTEST, "run"), "run")

    claimed_run = queue.claim_next_for_types(
        "controller",
        # Open the controller and run backtest payload explicitly for claim_next_for_types
        # within test claim filters explicit job types without default mapping.
        (JobType.RUN_BACKTEST,),
        now_ns=100,
    )
    assert claimed_run is not None
    assert claimed_run.attempt.job_id == run.job_id
    # Assemble claimed build once so the test claim filters explicit job types without
    # default mapping workflow shares one value.
    claimed_build = queue.claim_next_for_types(
        "controller",
        (JobType.PREPARE_DATASET,),
        now_ns=100,
    )
    # Verify claimed_build is not None before this scenario is accepted.
    assert claimed_build is not None
    assert claimed_build.attempt.job_id == build.job_id


def test_runtime_lease_survives_reopen_and_heartbeat_is_not_an_event(tmp_path: Path) -> None:
    # Execute the test runtime lease survives reopen and heartbeat is not an event
    # workflow in explicit, reviewable steps.
    database = tmp_path / "catalog.sqlite"
    queue = SQLiteJobQueue(database)
    queue.submit(_spec(JobType.RUN_BACKTEST, "lease"), "lease")
    claimed = queue.claim_next_for_types(
        "controller-a",
        # Open the controller-a and run backtest payload explicitly for
        # claim_next_for_types within test runtime lease survives reopen and heartbeat is
        # not an event.
        (JobType.RUN_BACKTEST,),
        now_ns=100,
    )
    assert claimed is not None
    running = queue.register_process(
        # Pass claimed explicitly so register_process receives a reviewable stable-start-
        # token and controller-a input in test runtime lease survives reopen and heartbeat
        # is not an event.
        claimed,
        ProcessHandle(321, "stable-start-token"),
        _policy(),
        supervisor_instance_id="controller-a",
        now_ns=110,
        # Complete register_process only after its stable-start-token and controller-a inputs
        # are visible in test runtime lease survives reopen and heartbeat is not an event.
    )

    reopened = SQLiteJobQueue(database)
    assert reopened.list_unfinished_attempts() == (running,)
    reopened.heartbeat(
        running.attempt.attempt_id,
        # Pass running explicitly so heartbeat receives a reviewable controller-a and
        # attempt id input in test runtime lease survives reopen and heartbeat is not an
        # event.
        running.attempt.state_version,
        supervisor_instance_id="controller-a",
        now_ns=500,
        lease_duration_ns=1_000,
    )

    # Assemble connection once so the test runtime lease survives reopen and heartbeat is
    # not an event workflow shares one value.
    connection = connect(database, busy_timeout_seconds=1.0)
    try:
        # Perform the protected test runtime lease survives reopen and heartbeat is not an
        # event operation before explicit failure handling.
        runtime = connection.execute(
            "SELECT heartbeat_at_ns, lease_expires_at_ns FROM attempt_runtime"
        ).fetchone()
        events = connection.execute(
            "SELECT event_type FROM job_events ORDER BY event_id"
            # Complete fetchall only after its declared inputs are visible in test runtime
            # lease survives reopen and heartbeat is not an event.
        ).fetchall()
    finally:
        connection.close()
    assert tuple(runtime) == (500, 1_500)
    assert [row[0] for row in events] == [
        # Keep the job submitted expectation tied to job submitted, attempt claimed and
        # attempt running in this scenario.
        "JOB_SUBMITTED",
        "ATTEMPT_CLAIMED",
        "ATTEMPT_RUNNING",
    ]


def test_bounded_retry_waits_then_allocates_a_new_attempt_id(tmp_path: Path) -> None:
    # Execute the test bounded retry waits then allocates a new attempt id workflow in
    # explicit, reviewable steps.
    database = tmp_path / "catalog.sqlite"
    queue = SQLiteJobQueue(database)
    record = queue.submit(_spec(JobType.RUN_BACKTEST, "retry"), "retry")
    first = queue.claim_next_for_types(
        "controller",
        # Open the controller and run backtest payload explicitly for claim_next_for_types
        # within test bounded retry waits then allocates a new attempt id.
        (JobType.RUN_BACKTEST,),
        now_ns=100,
    )
    assert first is not None
    running = queue.register_process(
        # Pass first explicitly so register_process receives a reviewable start-token and
        # controller input in test bounded retry waits then allocates a new attempt id.
        first,
        ProcessHandle(321, "start-token"),
        _policy(),
        supervisor_instance_id="controller",
        now_ns=110,
        # Complete register_process only after its start-token and controller inputs are
        # visible in test bounded retry waits then allocates a new attempt id.
    )
    failure = AttemptFailure(AttemptFailureKind.TRANSIENT, AttemptFailureCode.CHILD_EXITED)
    finished = queue.finish_unsuccessful(
        running.attempt.attempt_id,
        running.attempt.state_version,
        # Pass failure explicitly so finish_unsuccessful receives a reviewable attempt id
        # and attempt input in test bounded retry waits then allocates a new attempt id.
        failure,
        retry_not_before_ns=200,
        now_ns=120,
    )

    assert finished.attempt.state is AttemptState.FAILED
    # Verify finished.retry_scheduled before this scenario is accepted.
    assert finished.retry_scheduled
    queued = queue.get_job(record.job_id)
    assert queued is not None
    assert queued.state is AttemptState.QUEUED
    assert (
        # Keep the queue expectation tied to claim next for types, controller and queue in
        # this scenario.
        queue.claim_next_for_types(
            "controller",
            (JobType.RUN_BACKTEST,),
            now_ns=199,
        )
        # Verify the claim next for types, controller and queue relationship before this
        # scenario is accepted.
        is None
    )
    second = queue.claim_next_for_types(
        "controller",
        (JobType.RUN_BACKTEST,),
        # Pass now ns explicitly so claim_next_for_types receives a reviewable controller
        # and run backtest input in test bounded retry waits then allocates a new attempt
        # id.
        now_ns=200,
    )
    assert second is not None
    assert second.attempt_number == 2
    assert second.attempt.attempt_id != first.attempt.attempt_id
    # Verify the spec id, spec and attempt relationship before this scenario is accepted.
    assert second.attempt.spec.spec_id == first.attempt.spec.spec_id

    connection = connect(database, busy_timeout_seconds=1.0)
    try:
        # Perform the protected test bounded retry waits then allocates a new attempt id
        # operation before explicit failure handling.
        failure_row = connection.execute("SELECT * FROM attempt_failures").fetchone()
        runtime_count = connection.execute("SELECT COUNT(*) FROM attempt_runtime").fetchone()[0]
    finally:
        connection.close()
    assert failure_row["failure_kind"] == AttemptFailureKind.TRANSIENT.value
    # Verify failure_row['retry_scheduled'] == 1 before this scenario is accepted.
    assert failure_row["retry_scheduled"] == 1
    assert runtime_count == 0


def test_cancel_race_suppresses_requested_retry(tmp_path: Path) -> None:
    # Execute the test cancel race suppresses requested retry workflow in explicit,
    # reviewable steps.
    database = tmp_path / "catalog.sqlite"
    queue = SQLiteJobQueue(database)
    record = queue.submit(_spec(JobType.RUN_BACKTEST, "cancel"), "cancel")
    claimed = queue.claim_next_for_types(
        "controller",
        # Open the controller and run backtest payload explicitly for claim_next_for_types
        # within test cancel race suppresses requested retry.
        (JobType.RUN_BACKTEST,),
        now_ns=100,
    )
    assert claimed is not None
    running = queue.register_process(
        # Pass claimed explicitly so register_process receives a reviewable start-token
        # and controller input in test cancel race suppresses requested retry.
        claimed,
        ProcessHandle(321, "start-token"),
        _policy(),
        supervisor_instance_id="controller",
        now_ns=110,
        # Complete register_process only after its start-token and controller inputs are
        # visible in test cancel race suppresses requested retry.
    )
    queue.request_cancel(record.job_id)

    finished = queue.finish_unsuccessful(
        running.attempt.attempt_id,
        running.attempt.state_version,
        # Keep the transient AttemptFailure step visible while building finished.
        AttemptFailure(AttemptFailureKind.TRANSIENT, AttemptFailureCode.CHILD_EXITED),
        retry_not_before_ns=200,
        now_ns=120,
    )

    assert finished.attempt.state is AttemptState.CANCELLED
    # Verify not finished.retry_scheduled before this scenario is accepted.
    assert not finished.retry_scheduled
    cancelled = queue.get_job(record.job_id)
    assert cancelled is not None
    assert cancelled.state is AttemptState.CANCELLED
    connection = connect(database, busy_timeout_seconds=1.0)
    # Keep expected failures inside the test cancel race suppresses requested retry error
    # boundary.
    try:
        assert connection.execute("SELECT COUNT(*) FROM job_retry_schedule").fetchone()[0] == 0
    finally:
        connection.close()


def test_starting_attempt_without_process_metadata_is_recoverable_orphan(tmp_path: Path) -> None:
    # Execute the test starting attempt without process metadata is recoverable orphan
    # workflow in explicit, reviewable steps.
    queue = SQLiteJobQueue(tmp_path / "catalog.sqlite")
    queue.submit(_spec(JobType.RUN_BACKTEST, "starting"), "starting")
    claimed = queue.claim_next_for_types(
        "old-controller",
        (JobType.RUN_BACKTEST,),
        # Pass now ns explicitly so claim_next_for_types receives a reviewable old-
        # controller and run backtest input in test starting attempt without process
        # metadata is recoverable orphan.
        now_ns=100,
    )
    assert claimed is not None

    records = SQLiteJobQueue(queue.database_path).list_unfinished_attempts()

    assert len(records) == 1
    # Verify records[0].attempt == claimed.attempt before this scenario is accepted.
    assert records[0].attempt == claimed.attempt
    assert records[0].handle is None
