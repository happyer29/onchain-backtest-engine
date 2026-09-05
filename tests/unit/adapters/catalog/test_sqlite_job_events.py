# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from backtest.adapters.catalog.sqlite import SQLiteJobQueue

# Import errors at the visible module dependency boundary.
from backtest.adapters.catalog.sqlite.errors import QueueCorruptionError
from backtest.adapters.catalog.sqlite.schema import connect
from backtest.application.canonical_json import resolved_job_spec_hex
from backtest.application.errors import JobStateConflictError
from backtest.application.models import (
    # Include attempt state so the models dependency remains explicit.
    AttemptState,
    JobProgressDetails,
    JobType,
    ProcessHandle,
    ProgressLevel,
    # Include progress stage so the models dependency remains explicit.
    ProgressStage,
    ResolvedJobSpec,
    ResourceCapacity,
)
from backtest.application.supervisor import (
    # Include job execution policy so the supervisor dependency remains explicit.
    JobExecutionPolicy,
    JobLane,
    JobResourceDemand,
)
from backtest.domain.identifiers import ContentDigest


# Define spec as one focused operation with an explicit boundary.
def _spec() -> ResolvedJobSpec:
    # Execute the spec workflow in explicit, reviewable steps.
    payload = b'{"fixture":"events"}'
    digest = ContentDigest(sha256(payload).hexdigest())
    return ResolvedJobSpec(
        spec_version=1,
        spec_id=ContentDigest(
            # Include resolved job spec hex in the completed spec result.
            resolved_job_spec_hex(
                spec_version=1,
                job_type=JobType.RUN_BACKTEST.value,
                payload_digest_hex=digest.hex,
                input_artifact_hexes=(),
                # Complete resolved_job_spec_hex only after its value and run backtest inputs
                # are visible in spec.
            )
        ),
        job_type=JobType.RUN_BACKTEST,
        canonical_payload=payload,
        payload_digest=digest,
        # Complete ResolvedJobSpec only after its value and hex inputs are visible in spec.
    )


def _running_attempt(queue: SQLiteJobQueue):
    # Execute the running attempt workflow in explicit, reviewable steps.
    record = queue.submit(_spec(), "progress-events")
    claimed = queue.claim_next_for_types(
        "supervisor",
        (JobType.RUN_BACKTEST,),
        now_ns=1,
        # Complete claim_next_for_types only after its supervisor and run backtest inputs are
        # visible in running attempt.
    )
    assert claimed is not None
    running = queue.register_process(
        claimed,
        ProcessHandle(12_345, "safe-start-token"),
        # Keep the job execution policy and run JobExecutionPolicy step visible while
        # building running.
        JobExecutionPolicy(
            lane=JobLane.RUN,
            demand=JobResourceDemand(1_000),
            timeout_ns=10_000,
            termination_grace_seconds=0,
            # Pass lease duration ns explicitly so JobExecutionPolicy receives a
            # reviewable run and job resource demand input in running attempt.
            lease_duration_ns=1_000,
        ),
        supervisor_instance_id="supervisor",
        now_ns=2,
    )
    # Return the completed running attempt result without a hidden fallback.
    return record, running.attempt


def test_job_state_changes_append_bounded_operational_events(tmp_path: Path) -> None:
    # Execute the test job state changes append bounded operational events workflow in
    # explicit, reviewable steps.
    database = tmp_path / "catalog.sqlite"
    queue = SQLiteJobQueue(database)
    queue.submit(_spec(), "events")
    attempt = queue.claim_next("supervisor", ResourceCapacity(1_000_000, 1))
    assert attempt is not None
    # Assemble attempt once so the test job state changes append bounded operational
    # events workflow shares one value.
    attempt = queue.transition(
        attempt.attempt_id,
        attempt.state_version,
        AttemptState.RUNNING,
    )
    # Invoke transition for attempt id and state version as a visible test job state
    # changes append bounded operational events step.
    queue.transition(
        attempt.attempt_id,
        attempt.state_version,
        AttemptState.FAILED,
    )

    # Assemble connection once so the test job state changes append bounded operational
    # events workflow shares one value.
    connection = connect(database, busy_timeout_seconds=1.0)
    try:
        # Perform the protected test job state changes append bounded operational events
        # operation before explicit failure handling.
        rows = connection.execute(
            """
            SELECT event_type, state_version, details
            FROM job_events
            ORDER BY event_id
            """
        ).fetchall()
    finally:
        connection.close()

    # Verify the job submitted, attempt claimed and attempt running relationship before
    # this scenario is accepted.
    assert tuple(str(row["event_type"]) for row in rows) == (
        "JOB_SUBMITTED",
        "ATTEMPT_CLAIMED",
        "ATTEMPT_RUNNING",
        "ATTEMPT_FAILED",
        # Verify the job submitted, attempt claimed and attempt running relationship before
        # this scenario is accepted.
    )
    assert tuple(int(row["state_version"]) for row in rows) == (0, 1, 2, 3)
    assert all(row["details"] is None for row in rows)


def test_manual_retry_is_bounded_and_events_are_cursor_queryable(tmp_path: Path) -> None:
    # Execute the test manual retry is bounded and events are cursor queryable workflow in
    # explicit, reviewable steps.
    queue = SQLiteJobQueue(tmp_path / "catalog.sqlite")
    record = queue.submit(_spec(), "retry-events")
    claimed = queue.claim_next("supervisor", ResourceCapacity(1_000_000, 1))
    assert claimed is not None
    running = queue.transition(
        # Pass claimed explicitly so transition receives a reviewable attempt id and state
        # version input in test manual retry is bounded and events are cursor queryable.
        claimed.attempt_id,
        claimed.state_version,
        AttemptState.RUNNING,
    )
    queue.transition(running.attempt_id, running.state_version, AttemptState.FAILED)

    # Assemble retried once so the test manual retry is bounded and events are cursor
    # queryable workflow shares one value.
    retried = queue.request_retry(record.job_id)
    assert retried.state is AttemptState.QUEUED
    events = queue.list_job_events(record.job_id, after_event_id=2, limit=10)
    assert tuple(item.event_type for item in events) == (
        "ATTEMPT_RUNNING",
        # Keep the attempt failed expectation tied to attempt running, attempt failed and
        # job manual retry requested in this scenario.
        "ATTEMPT_FAILED",
        "JOB_MANUAL_RETRY_REQUESTED",
    )
    assert tuple(item.event_id for item in events) == tuple(
        sorted(item.event_id for item in events)
        # Complete tuple only after its event id and sorted inputs are visible in test manual
        # retry is bounded and events are cursor queryable.
    )

    with pytest.raises(JobStateConflictError):
        queue.request_retry(record.job_id)


def test_supervisor_progress_is_canonical_typed_and_cursor_queryable(tmp_path: Path) -> None:
    # Execute the test supervisor progress is canonical typed and cursor queryable
    # workflow in explicit, reviewable steps.
    queue = SQLiteJobQueue(tmp_path / "catalog.sqlite")
    record, attempt = _running_attempt(queue)
    details = JobProgressDetails(
        sequence=2,
        level=ProgressLevel.INFO,
        # Pass stage explicitly so JobProgressDetails receives a reviewable info and
        # running backtest input in test supervisor progress is canonical typed and cursor
        # queryable.
        stage=ProgressStage.RUNNING_BACKTEST,
        coalesced_events=2,
        dropped_transport_frames=1,
        private_rss_bytes=100,
        total_rss_bytes=120,
        # Pass major page faults explicitly so JobProgressDetails receives a reviewable
        # info and running backtest input in test supervisor progress is canonical typed
        # and cursor queryable.
        major_page_faults=3,
        temporary_disk_bytes=4,
    )

    queue.record_progress(
        attempt.attempt_id,
        # Pass attempt explicitly so record_progress receives a reviewable supervisor and
        # attempt id input in test supervisor progress is canonical typed and cursor
        # queryable.
        attempt.state_version,
        details,
        supervisor_instance_id="supervisor",
        now_ns=3,
    )

    # Assemble events once so the test supervisor progress is canonical typed and cursor
    # queryable workflow shares one value.
    events = queue.list_job_events(record.job_id, after_event_id=0, limit=10)
    progress = events[-1]
    assert progress.event_type == "ATTEMPT_PROGRESS"
    assert progress.progress == details
    with pytest.raises(ValueError, match="sequence must increase"):
        # Keep raises, value error and pytest active only for the bounded test supervisor
        # progress is canonical typed and cursor queryable operation.
        queue.record_progress(
            attempt.attempt_id,
            attempt.state_version,
            details,
            supervisor_instance_id="supervisor",
            # Pass now ns explicitly so record_progress receives a reviewable supervisor
            # and attempt id input in test supervisor progress is canonical typed and
            # cursor queryable.
            now_ns=4,
        )
    with pytest.raises(JobStateConflictError):
        # Keep raises, job state conflict error and pytest active only for the bounded
        # test supervisor progress is canonical typed and cursor queryable operation.
        queue.record_progress(
            attempt.attempt_id,
            attempt.state_version,
            JobProgressDetails(
                sequence=3,
                # Pass level explicitly so JobProgressDetails receives a reviewable info
                # and running backtest input in test supervisor progress is canonical
                # typed and cursor queryable.
                level=ProgressLevel.INFO,
                stage=ProgressStage.RUNNING_BACKTEST,
            ),
            supervisor_instance_id="different-supervisor",
            now_ns=4,
            # Complete record_progress only after its different-supervisor and attempt id
            # inputs are visible in test supervisor progress is canonical typed and cursor
            # queryable.
        )


def test_progress_history_is_capped_and_corruption_never_reaches_reader(tmp_path: Path) -> None:
    # Execute the test progress history is capped and corruption never reaches reader
    # workflow in explicit, reviewable steps.
    database = tmp_path / "catalog.sqlite"
    queue = SQLiteJobQueue(database)
    record, attempt = _running_attempt(queue)
    for sequence in range(1, 271):
        # Process range(1, 271) inside the bounded test progress history is capped and
        # corruption never reaches reader loop.
        queue.record_progress(
            attempt.attempt_id,
            attempt.state_version,
            JobProgressDetails(
                sequence=sequence,
                # Pass level explicitly so JobProgressDetails receives a reviewable info
                # and running backtest input in test progress history is capped and
                # corruption never reaches reader.
                level=ProgressLevel.INFO,
                stage=ProgressStage.RUNNING_BACKTEST,
            ),
            supervisor_instance_id="supervisor",
            now_ns=sequence + 2,
            # Complete record_progress only after its supervisor and attempt id inputs are
            # visible in test progress history is capped and corruption never reaches reader.
        )

    connection = connect(database, busy_timeout_seconds=1.0)
    try:
        # Perform the protected test progress history is capped and corruption never
        # reaches reader operation before explicit failure handling.
        count = connection.execute(
            """
            SELECT COUNT(*) FROM job_events
            WHERE attempt_id = ? AND event_type = 'ATTEMPT_PROGRESS'
            """,
            (attempt.attempt_id.value,),
        ).fetchone()[0]
        latest_event_id = connection.execute(
            # Keep fetchone, execute and connection visible while completing fetchone
            # within test progress history is capped and corruption never reaches reader.
            """
            SELECT MAX(event_id) FROM job_events
            WHERE attempt_id = ? AND event_type = 'ATTEMPT_PROGRESS'
            """,
            (attempt.attempt_id.value,),
        ).fetchone()[0]
        connection.execute(
            "UPDATE job_events SET details = ? WHERE event_id = ?",
            # Open the update job events set details = ? where event id = ? and latest
            # event id payload explicitly for execute within test progress history is
            # capped and corruption never reaches reader.
            (b'{"unsafe":"credential-or-traceback"}', latest_event_id),
        )
        connection.commit()
    finally:
        connection.close()

    # Verify count == 256 before this scenario is accepted.
    assert count == 256
    with pytest.raises(QueueCorruptionError, match="stored progress details") as captured:
        queue.list_job_events(record.job_id, limit=1_000)
    assert "credential-or-traceback" not in str(captured.value)
