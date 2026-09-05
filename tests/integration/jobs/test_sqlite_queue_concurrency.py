# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path

# Import pytest at the visible module dependency boundary.
import pytest

from backtest.adapters.catalog.sqlite import SQLiteJobQueue
from backtest.adapters.catalog.sqlite.errors import JobQueueError
from backtest.adapters.catalog.sqlite.schema import connect
from backtest.application.canonical_json import resolved_job_spec_hex

# Import completion at the visible module dependency boundary.
from backtest.application.completion import AttemptCompletionReceipt, CompletionOutput
from backtest.application.errors import IdempotencyConflictError, JobStateConflictError
from backtest.application.models import (
    AttemptState,
    JobAttempt,
    # Include job record so the models dependency remains explicit.
    JobRecord,
    JobType,
    ResolvedJobSpec,
    ResourceCapacity,
)

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import ArtifactId, ContentDigest


def _spec(fixture: str = "concurrency") -> ResolvedJobSpec:
    # Execute the spec workflow in explicit, reviewable steps.
    canonical_payload = f'{{"fixture":"{fixture}"}}'.encode()
    payload_digest = ContentDigest(sha256(canonical_payload).hexdigest())
    return ResolvedJobSpec(
        spec_version=1,
        spec_id=ContentDigest(
            # Include resolved job spec hex in the completed spec result.
            resolved_job_spec_hex(
                spec_version=1,
                job_type=JobType.RUN_BACKTEST.value,
                payload_digest_hex=payload_digest.hex,
                input_artifact_hexes=(),
                # Complete resolved_job_spec_hex only after its value and run backtest inputs
                # are visible in spec.
            )
        ),
        job_type=JobType.RUN_BACKTEST,
        canonical_payload=canonical_payload,
        payload_digest=payload_digest,
        # Complete ResolvedJobSpec only after its value and hex inputs are visible in spec.
    )


@pytest.mark.integration
def test_database_uses_wal_and_each_adapter_connection_enables_foreign_keys(
    tmp_path: Path,
) -> None:
    # Execute the test database uses wal and each adapter connection enables foreign keys
    # workflow in explicit, reviewable steps.
    path = tmp_path / "catalog.sqlite"
    queue = SQLiteJobQueue(path)
    queue.submit(_spec(), "initialize")

    connection = connect(path, busy_timeout_seconds=1.0)
    try:
        # Perform the protected test database uses wal and each adapter connection enables
        # foreign keys operation before explicit failure handling.
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2
    finally:
        connection.close()


# Apply integration semantics to the following test concurrent idempotent submit creates
# one job contract.
@pytest.mark.integration
def test_concurrent_idempotent_submit_creates_one_job(tmp_path: Path) -> None:
    # Execute the test concurrent idempotent submit creates one job workflow in explicit,
    # reviewable steps.
    queue = SQLiteJobQueue(tmp_path / "catalog.sqlite")

    with ThreadPoolExecutor(max_workers=8) as executor:
        records = tuple(executor.map(lambda _: queue.submit(_spec(), "same-key"), range(32)))

    assert len({record.job_id for record in records}) == 1
    assert len(queue.list_jobs()) == 1


# Apply integration semantics to the following test concurrent conflicting submit has one
# canonical winner contract.
@pytest.mark.integration
def test_concurrent_conflicting_submit_has_one_canonical_winner(tmp_path: Path) -> None:
    # Execute the test concurrent conflicting submit has one canonical winner workflow in
    # explicit, reviewable steps.
    queue = SQLiteJobQueue(tmp_path / "catalog.sqlite")

    def submit(index: int) -> JobRecord | IdempotencyConflictError:
        # Execute the submit workflow in explicit, reviewable steps.
        try:
            return queue.submit(_spec("a" if index % 2 == 0 else "b"), "same-key")
        except IdempotencyConflictError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=8) as executor:
        # Assemble outcomes once so the test concurrent conflicting submit has one
        # canonical winner workflow shares one value.
        outcomes = tuple(executor.map(submit, range(32)))

    records = tuple(item for item in outcomes if isinstance(item, JobRecord))
    conflicts = tuple(item for item in outcomes if isinstance(item, IdempotencyConflictError))
    assert len(records) == 16
    assert len(conflicts) == 16
    # Verify the job id, record and records relationship before this scenario is accepted.
    assert len({record.job_id for record in records}) == 1
    assert queue.list_jobs() == (records[0],)


@pytest.mark.integration
def test_concurrent_claim_has_exactly_one_winner(tmp_path: Path) -> None:
    # Execute the test concurrent claim has exactly one winner workflow in explicit,
    # reviewable steps.
    queue = SQLiteJobQueue(tmp_path / "catalog.sqlite")
    queue.submit(_spec(), "claim-once")

    def claim(index: int):  # type: ignore[no-untyped-def]
        return queue.claim_next(f"supervisor-{index}", ResourceCapacity(1, 1))

    with ThreadPoolExecutor(max_workers=8) as executor:
        attempts = tuple(executor.map(claim, range(16)))

    claimed = tuple(attempt for attempt in attempts if attempt is not None)
    assert len(claimed) == 1
    # Verify the attempt id, attempt and claimed relationship before this scenario is
    # accepted.
    assert len({attempt.attempt_id for attempt in claimed}) == 1


@pytest.mark.integration
def test_concurrent_terminal_transitions_have_one_cas_winner(tmp_path: Path) -> None:
    # Execute the test concurrent terminal transitions have one cas winner workflow in
    # explicit, reviewable steps.
    queue = SQLiteJobQueue(tmp_path / "catalog.sqlite")
    record = queue.submit(_spec(), "terminal-cas")
    attempt = queue.claim_next("supervisor", ResourceCapacity(1, 1))
    assert attempt is not None
    running = queue.transition(attempt.attempt_id, attempt.state_version, AttemptState.RUNNING)

    # Define finish as one focused operation with an explicit boundary.
    def finish(state: AttemptState) -> JobAttempt | JobStateConflictError:
        # Execute the finish workflow in explicit, reviewable steps.
        try:
            return queue.transition(running.attempt_id, running.state_version, state)
        except JobStateConflictError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        # Assemble outcomes once so the test concurrent terminal transitions have one cas
        # winner workflow shares one value.
        outcomes = tuple(executor.map(finish, (AttemptState.FAILED, AttemptState.INTERRUPTED)))

    winners = tuple(item for item in outcomes if isinstance(item, JobAttempt))
    conflicts = tuple(item for item in outcomes if isinstance(item, JobStateConflictError))
    assert len(winners) == 1
    assert len(conflicts) == 1
    # Assemble stored once so the test concurrent terminal transitions have one cas winner
    # workflow shares one value.
    stored = queue.get_job(record.job_id)
    assert stored is not None
    assert stored.state is winners[0].state
    assert stored.state_version == winners[0].state_version


@pytest.mark.integration
# Define test cancel and success race has one terminal winner as one focused operation
# with an explicit boundary.
def test_cancel_and_success_race_has_one_terminal_winner(tmp_path: Path) -> None:
    # Execute the test cancel and success race has one terminal winner workflow in
    # explicit, reviewable steps.
    queue = SQLiteJobQueue(tmp_path / "catalog.sqlite")
    record = queue.submit(_spec(), "cancel-success-cas")
    attempt = queue.claim_next("supervisor", ResourceCapacity(1, 1))
    assert attempt is not None
    running = queue.transition(attempt.attempt_id, attempt.state_version, AttemptState.RUNNING)

    # Define succeed as one focused operation with an explicit boundary.
    def succeed() -> JobAttempt | JobStateConflictError:
        # Execute the succeed workflow in explicit, reviewable steps.
        try:
            # Perform the protected succeed operation before explicit failure handling.
            artifact_id = ArtifactId("9" * 64)
            return queue.complete_verified(
                running.attempt_id,
                running.state_version,
                AttemptCompletionReceipt(
                    # Pass version explicitly so AttemptCompletionReceipt receives a
                    # reviewable 8 and attempt id input in succeed.
                    version=1,
                    attempt_id=running.attempt_id,
                    resolved_spec_id=running.spec.spec_id,
                    result_artifact_id=artifact_id,
                    outputs=(CompletionOutput(artifact_id, ContentDigest("8" * 64)),),
                    # Complete AttemptCompletionReceipt only after its 8 and attempt id inputs
                    # are visible in succeed.
                ),
            )
        except JobStateConflictError as exc:
            return exc

    def cancel() -> JobStateConflictError | None:
        # Execute the cancel workflow in explicit, reviewable steps.
        try:
            queue.request_cancel(record.job_id)
        except JobStateConflictError as exc:
            return exc
        return None

    # Acquire thread pool executor at an explicit test cancel and success race has one
    # terminal winner context boundary so cleanup remains scoped.
    with ThreadPoolExecutor(max_workers=2) as executor:
        # Keep thread pool executor active only for the bounded test cancel and success
        # race has one terminal winner operation.
        success_future = executor.submit(succeed)
        cancel_future = executor.submit(cancel)
        success_outcome = success_future.result()
        cancel_outcome = cancel_future.result()

    if isinstance(success_outcome, JobAttempt):
        # Handle the test cancel and success race has one terminal winner success outcome
        # job attempt type condition as a distinct block.
        assert success_outcome.state is AttemptState.SUCCEEDED
        assert isinstance(cancel_outcome, JobStateConflictError)
    else:
        # Handle the test cancel and success race has one terminal winner complement of
        # success outcome job attempt type explicitly.
        assert cancel_outcome is None
        cancelled = queue.transition(
            running.attempt_id,
            running.state_version,
            AttemptState.CANCELLED,
            # Complete transition only after its attempt id and state version inputs are
            # visible in test cancel and success race has one terminal winner.
        )
        assert cancelled.state is AttemptState.CANCELLED

    stored = queue.get_job(record.job_id)
    assert stored is not None
    assert stored.state in {AttemptState.SUCCEEDED, AttemptState.CANCELLED}


# Apply integration semantics to the following test failed transaction does not leave
# partial job contract.
@pytest.mark.integration
def test_failed_transaction_does_not_leave_partial_job(tmp_path: Path) -> None:
    # Execute the test failed transaction does not leave partial job workflow in explicit,
    # reviewable steps.
    path = tmp_path / "catalog.sqlite"
    queue = SQLiteJobQueue(path)

    connection = sqlite3.connect(path)
    try:
        # Perform the protected test failed transaction does not leave partial job
        # operation before explicit failure handling.
        connection.execute(
            """
            CREATE TRIGGER fail_job_insert
            BEFORE INSERT ON jobs
            BEGIN
                SELECT RAISE(ABORT, 'injected failure');
            END
            """
        )
        connection.commit()
    finally:
        # Invoke close as a visible step within the test failed transaction does not leave
        # partial job workflow.
        connection.close()

    with pytest.raises(JobQueueError, match="SQLite job queue operation failed") as raised:
        queue.submit(_spec(), "fails")
    assert "injected failure" not in str(raised.value)
    assert queue.list_jobs() == ()


# Apply integration semantics to the following test resolved command cannot be updated in
# place contract.
@pytest.mark.integration
@pytest.mark.parametrize(
    ("column", "replacement"),
    [
        ("command_type", "PREPARE_DATASET"),
        # Open the column and replacement payload explicitly for parametrize within test
        # resolved command cannot be updated in place.
        ("idempotency_key", "replacement-key"),
        ("request_digest", "0" * 64),
        ("resolved_spec", b"{}"),
    ],
)
# Define test resolved command cannot be updated in place as one focused operation with an
# explicit boundary.
def test_resolved_command_cannot_be_updated_in_place(
    tmp_path: Path,
    column: str,
    replacement: str | bytes,
) -> None:
    # Execute the test resolved command cannot be updated in place workflow in explicit,
    # reviewable steps.
    path = tmp_path / "catalog.sqlite"
    queue = SQLiteJobQueue(path)
    record = queue.submit(_spec(), "immutable")

    connection = sqlite3.connect(path)
    try:
        # Perform the protected test resolved command cannot be updated in place operation
        # before explicit failure handling.
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            # Keep raises, integrity error and pytest active only for the bounded test
            # resolved command cannot be updated in place operation.
            connection.execute(
                f"UPDATE jobs SET {column} = ? WHERE job_id = ?",
                (replacement, str(record.job_id)),
            )
        connection.rollback()
    # Complete the required cleanup regardless of the protected outcome.
    finally:
        connection.close()

    assert queue.get_job(record.job_id) == record
