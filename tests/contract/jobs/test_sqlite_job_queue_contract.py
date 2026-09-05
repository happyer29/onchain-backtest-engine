# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

# Import sqlite at the visible module dependency boundary.
from backtest.adapters.catalog.sqlite import (
    QueueCorruptionError,
    SQLiteJobQueue,
    UnverifiedJobCompletionError,
)
from backtest.adapters.catalog.sqlite.schema import connect

# Import serialization at the visible module dependency boundary.
from backtest.adapters.catalog.sqlite.serialization import (
    deserialize_job_spec,
    serialize_job_spec,
)
from backtest.application.canonical_json import canonicalize_job_payload, resolved_job_spec_hex

# Import completion at the visible module dependency boundary.
from backtest.application.completion import AttemptCompletionReceipt, CompletionOutput
from backtest.application.errors import (
    IdempotencyConflictError,
    InvalidIdempotencyKeyError,
    JobNotFoundError,
    # Include job state conflict error so the errors dependency remains explicit.
    JobStateConflictError,
)
from backtest.application.models import (
    AttemptState,
    JobAttempt,
    # Include job type so the models dependency remains explicit.
    JobType,
    ResolvedJobSpec,
    ResourceCapacity,
)
from backtest.application.ports.jobs import JobListCursor, JobQueue

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import ArtifactId, ContentDigest, JobId


def _artifact(character: str) -> ArtifactId:
    return ArtifactId(character * 64)


def _spec(character: str = "a", *, job_type: JobType = JobType.RUN_BACKTEST) -> ResolvedJobSpec:
    # Execute the spec workflow in explicit, reviewable steps.
    spec_version = 1
    canonical_payload = canonicalize_job_payload(
        json.dumps(
            {"fixture": character},
            ensure_ascii=False,
            # Pass separators explicitly so encode receives a reviewable utf-8 input in
            # spec.
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    payload_digest = ContentDigest(sha256(canonical_payload).hexdigest())
    # Register c through _artifact so the input artifact ids table remains scannable.
    input_artifact_ids = (_artifact("c"), _artifact("d"))
    return ResolvedJobSpec(
        spec_version=spec_version,
        spec_id=ContentDigest(
            resolved_job_spec_hex(
                # Pass spec version explicitly so resolved_job_spec_hex receives a
                # reviewable value and hex input in spec.
                spec_version=spec_version,
                job_type=job_type.value,
                payload_digest_hex=payload_digest.hex,
                input_artifact_hexes=(item.hex for item in input_artifact_ids),
            )
            # Complete ContentDigest only after its value and hex inputs are visible in spec.
        ),
        job_type=job_type,
        canonical_payload=canonical_payload,
        payload_digest=payload_digest,
        input_artifact_ids=input_artifact_ids,
        # Complete ResolvedJobSpec only after its value and hex inputs are visible in spec.
    )


def _receipt(attempt: JobAttempt, artifact_id: ArtifactId) -> AttemptCompletionReceipt:
    # Execute the receipt workflow in explicit, reviewable steps.
    return AttemptCompletionReceipt(
        version=1,
        attempt_id=attempt.attempt_id,
        resolved_spec_id=attempt.spec.spec_id,
        result_artifact_id=artifact_id,
        # Include outputs in the completed receipt result.
        outputs=(CompletionOutput(artifact_id, ContentDigest("8" * 64)),),
    )


@pytest.fixture
def queue(tmp_path: Path) -> SQLiteJobQueue:
    return SQLiteJobQueue(tmp_path / "catalog" / "catalog.sqlite")


# Define test adapter satisfies job queue protocol as one focused operation with an
# explicit boundary.
def test_adapter_satisfies_job_queue_protocol(queue: SQLiteJobQueue) -> None:
    assert isinstance(queue, JobQueue)


def test_job_keyset_page_does_not_shift_when_a_newer_job_is_inserted(tmp_path: Path) -> None:
    """A continuation remains anchored below its last visible composite key."""

    queue = SQLiteJobQueue(tmp_path / "catalog" / "catalog.sqlite")
    submitted: list[JobId] = []
    for index, timestamp in enumerate((100, 200, 300), start=1):
        record = queue.submit(_spec(str(index)), f"page-{index}")
        # Set deterministic operational times without changing queue identity semantics.
        connection = connect(queue.database_path, busy_timeout_seconds=1.0)
        try:
            connection.execute(
                "UPDATE jobs SET submitted_at_ns = ?, updated_at_ns = ? WHERE job_id = ?",
                (timestamp, timestamp, record.job_id.value),
            )
        finally:
            connection.close()
        submitted.append(record.job_id)

    first = queue.list_jobs(limit=2)
    cursor = JobListCursor(None, first[-1].submitted_at_ns, first[-1].job_id)
    # Insert ahead of page one after the continuation was issued.
    newest = queue.submit(_spec("4"), "page-4")
    connection = connect(queue.database_path, busy_timeout_seconds=1.0)
    try:
        connection.execute(
            "UPDATE jobs SET submitted_at_ns = 400, updated_at_ns = 400 WHERE job_id = ?",
            (newest.job_id.value,),
        )
    finally:
        connection.close()
    second = queue.list_jobs(limit=2, after=cursor)

    assert tuple(item.job_id for item in first) == (
        submitted[2],
        submitted[1],
    )
    assert tuple(item.job_id for item in second) == (submitted[0],)
    # The concurrent insert is newer and therefore cannot leak after the cursor.
    assert newest.job_id not in {item.job_id for item in second}


def test_job_list_rejects_pathological_or_ambiguous_pagination(queue: SQLiteJobQueue) -> None:
    """Legacy offsets stay bounded and cannot be mixed with keyset state."""

    record = queue.submit(_spec(), "pagination-bounds")
    cursor = JobListCursor(None, record.submitted_at_ns, record.job_id)

    with pytest.raises(ValueError, match="between 0 and 10000"):
        queue.list_jobs(offset=10_001)
    with pytest.raises(ValueError, match="cannot use offset"):
        queue.list_jobs(offset=1, after=cursor)
    with pytest.raises(ValueError, match="match the filter"):
        queue.list_jobs(state=AttemptState.QUEUED, after=cursor)


def test_resolved_spec_serialization_is_canonical_and_round_trips() -> None:
    # Execute the test resolved spec serialization is canonical and round trips workflow
    # in explicit, reviewable steps.
    spec = _spec()

    payload = serialize_job_spec(spec)

    assert deserialize_job_spec(payload) == spec
    assert payload == serialize_job_spec(spec)
    assert b" " not in payload
    # Verify the loads, payload and canonical payload relationship before this scenario is
    # accepted.
    assert json.loads(payload) == {
        "canonical_payload": '{"fixture":"a"}',
        "input_artifact_ids": ["c" * 64, "d" * 64],
        "job_type": "RUN_BACKTEST",
        "payload_digest": spec.payload_digest.hex,
        # Keep the schema version expectation tied to loads, payload and canonical payload
        # in this scenario.
        "schema_version": 2,
        "spec_id": spec.spec_id.hex,
        "spec_version": 1,
    }


def test_digest_display_prefix_does_not_change_canonical_spec_bytes() -> None:
    # Execute the test digest display prefix does not change canonical spec bytes workflow
    # in explicit, reviewable steps.
    plain = _spec()
    prefixed = ResolvedJobSpec(
        spec_version=plain.spec_version,
        spec_id=ContentDigest(f"sha256:{plain.spec_id.hex}"),
        job_type=plain.job_type,
        # Pass canonical payload explicitly so ResolvedJobSpec receives a reviewable
        # sha256: and spec version input in test digest display prefix does not change
        # canonical spec bytes.
        canonical_payload=plain.canonical_payload,
        payload_digest=ContentDigest(f"sha256:{plain.payload_digest.hex}"),
        input_artifact_ids=tuple(
            ArtifactId(f"sha256:{artifact_id.hex}") for artifact_id in plain.input_artifact_ids
        ),
        # Complete ResolvedJobSpec only after its sha256: and spec version inputs are visible
        # in test digest display prefix does not change canonical spec bytes.
    )

    assert serialize_job_spec(prefixed) == serialize_job_spec(plain)


def test_submit_normalizes_digest_display_prefixes_for_stable_idempotent_records(
    queue: SQLiteJobQueue,
) -> None:
    # Execute the test submit normalizes digest display prefixes for stable idempotent
    # records workflow in explicit, reviewable steps.
    plain = _spec()
    prefixed = ResolvedJobSpec(
        spec_version=plain.spec_version,
        spec_id=ContentDigest(f"sha256:{plain.spec_id.hex}"),
        job_type=plain.job_type,
        # Pass canonical payload explicitly so ResolvedJobSpec receives a reviewable
        # sha256: and spec version input in test submit normalizes digest display prefixes
        # for stable idempotent records.
        canonical_payload=plain.canonical_payload,
        payload_digest=ContentDigest(f"sha256:{plain.payload_digest.hex}"),
        input_artifact_ids=tuple(
            ArtifactId(f"sha256:{artifact_id.hex}") for artifact_id in plain.input_artifact_ids
        ),
        # Complete ResolvedJobSpec only after its sha256: and spec version inputs are visible
        # in test submit normalizes digest display prefixes for stable idempotent records.
    )

    first = queue.submit(prefixed, "prefixed")
    second = queue.submit(prefixed, "prefixed")

    assert first == second
    assert first == queue.get_job(first.job_id)
    # Verify first.spec == plain before this scenario is accepted.
    assert first.spec == plain


@pytest.mark.parametrize(
    "payload",
    [
        b'{"schema_version":1}',
        # Pass schema version explicitly so parametrize receives a reviewable payload
        # input in test corrupt or legacy resolved spec is rejected.
        b'{"schema_version":2}',
        b"\xff",
    ],
)
def test_corrupt_or_legacy_resolved_spec_is_rejected(payload: bytes) -> None:
    # Execute the test corrupt or legacy resolved spec is rejected workflow in explicit,
    # reviewable steps.
    with pytest.raises(QueueCorruptionError):
        deserialize_job_spec(payload)


def test_noncanonical_resolved_spec_wrapper_is_rejected() -> None:
    # Execute the test noncanonical resolved spec wrapper is rejected workflow in
    # explicit, reviewable steps.
    payload = serialize_job_spec(_spec())

    with pytest.raises(QueueCorruptionError):
        deserialize_job_spec(b" " + payload)


@pytest.mark.parametrize(
    ("field", "value"),
    # Open the field and value payload explicitly for parametrize within test stored
    # payload digest and spec identity are verified.
    [
        ("canonical_payload", '{"fixture":"tampered"}'),
        ("payload_digest", "0" * 64),
        ("spec_id", "0" * 64),
        ("spec_version", 2),
        # Open the field and value payload explicitly for parametrize within test stored
        # payload digest and spec identity are verified.
        ("unexpected", "field"),
    ],
)
def test_stored_payload_digest_and_spec_identity_are_verified(field: str, value: object) -> None:
    # Execute the test stored payload digest and spec identity are verified workflow in
    # explicit, reviewable steps.
    document = json.loads(serialize_job_spec(_spec()))
    document[field] = value
    payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()

    with pytest.raises(QueueCorruptionError):
        deserialize_job_spec(payload)


# Define test submit is idempotent for same key and exact spec as one focused operation
# with an explicit boundary.
def test_submit_is_idempotent_for_same_key_and_exact_spec(queue: SQLiteJobQueue) -> None:
    # Execute the test submit is idempotent for same key and exact spec workflow in
    # explicit, reviewable steps.
    first = queue.submit(_spec(), "browser-submit-1")
    second = queue.submit(_spec(), "browser-submit-1")

    assert second == first
    assert queue.list_jobs() == (first,)


def test_submit_rejects_same_key_with_different_request(queue: SQLiteJobQueue) -> None:
    # Execute the test submit rejects same key with different request workflow in
    # explicit, reviewable steps.
    queue.submit(_spec("a"), "browser-submit-1")

    with pytest.raises(IdempotencyConflictError) as caught:
        queue.submit(_spec("b"), "browser-submit-1")

    assert caught.value.job_type is JobType.RUN_BACKTEST
    assert caught.value.idempotency_key == "browser-submit-1"


# Define test idempotency namespace includes command type as one focused operation with an
# explicit boundary.
def test_idempotency_namespace_includes_command_type(queue: SQLiteJobQueue) -> None:
    # Execute the test idempotency namespace includes command type workflow in explicit,
    # reviewable steps.
    run = queue.submit(_spec("a", job_type=JobType.RUN_BACKTEST), "same-key")
    prepare = queue.submit(_spec("b", job_type=JobType.PREPARE_DATASET), "same-key")

    assert run.job_id != prepare.job_id
    assert len(queue.list_jobs()) == 2


@pytest.mark.parametrize("key", ["", " leading", "trailing ", "line\nbreak"])
# Define test invalid idempotency keys are rejected as one focused operation with an
# explicit boundary.
def test_invalid_idempotency_keys_are_rejected(queue: SQLiteJobQueue, key: str) -> None:
    # Execute the test invalid idempotency keys are rejected workflow in explicit,
    # reviewable steps.
    with pytest.raises(InvalidIdempotencyKeyError):
        queue.submit(_spec(), key)


def test_missing_job_uses_application_not_found_error(queue: SQLiteJobQueue) -> None:
    # Execute the test missing job uses application not found error workflow in explicit,
    # reviewable steps.
    missing = JobId("job_missing")

    with pytest.raises(JobNotFoundError) as caught:
        queue.request_cancel(missing)

    assert caught.value.job_id == missing


def test_claim_is_atomic_and_starts_a_new_attempt(queue: SQLiteJobQueue) -> None:
    # Execute the test claim is atomic and starts a new attempt workflow in explicit,
    # reviewable steps.
    submitted = queue.submit(_spec(), "claim-1")

    attempt = queue.claim_next("supervisor-1", ResourceCapacity(1_000_000, 1))

    assert attempt is not None
    assert attempt.job_id == submitted.job_id
    assert attempt.spec == submitted.spec
    # Verify attempt.state is AttemptState.STARTING before this scenario is accepted.
    assert attempt.state is AttemptState.STARTING
    assert attempt.state_version == 1
    assert queue.claim_next("supervisor-1", ResourceCapacity(1_000_000, 1)) is None


@pytest.mark.parametrize(
    ("memory", "slots"),
    # Open the memory and slots payload explicitly for parametrize within test claim
    # respects empty capacity.
    [(0, 1), (1, 0), (-1, 1), (1, -1)],
)
def test_claim_respects_empty_capacity(
    queue: SQLiteJobQueue,
    memory: int,
    # Keep the slots input explicit in the test claim respects empty capacity contract.
    slots: int,
) -> None:
    # Execute the test claim respects empty capacity workflow in explicit, reviewable
    # steps.
    submitted = queue.submit(_spec(), "capacity")

    assert queue.claim_next("supervisor", ResourceCapacity(memory, slots)) is None
    assert queue.get_job(submitted.job_id) == submitted


def test_transition_uses_compare_and_swap(queue: SQLiteJobQueue) -> None:
    # Execute the test transition uses compare and swap workflow in explicit, reviewable
    # steps.
    queue.submit(_spec(), "cas")
    attempt = queue.claim_next("supervisor", ResourceCapacity(1, 1))
    assert attempt is not None

    running = queue.transition(
        attempt.attempt_id,
        # Pass expected version explicitly so transition receives a reviewable attempt id
        # and state version input in test transition uses compare and swap.
        expected_version=attempt.state_version,
        new_state=AttemptState.RUNNING,
    )

    assert running.state is AttemptState.RUNNING
    assert running.state_version == attempt.state_version + 1
    # Acquire raises, job state conflict error and pytest at an explicit test transition
    # uses compare and swap context boundary so cleanup remains scoped.
    with pytest.raises(JobStateConflictError) as caught:
        # Keep raises, job state conflict error and pytest active only for the bounded
        # test transition uses compare and swap operation.
        queue.transition(
            attempt.attempt_id,
            expected_version=attempt.state_version,
            new_state=AttemptState.FAILED,
        )

    # Verify caught.value.job_id == attempt.job_id before this scenario is accepted.
    assert caught.value.job_id == attempt.job_id
    assert caught.value.current_state is AttemptState.RUNNING
    assert caught.value.operation == "transition"
    assert queue.get_job(attempt.job_id).state_version == running.state_version  # type: ignore[union-attr]
    assert queue.get_job(attempt.job_id).state is AttemptState.RUNNING  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("start_state", "terminal_state"),
    [
        (AttemptState.STARTING, AttemptState.FAILED),
        (AttemptState.STARTING, AttemptState.INTERRUPTED),
        # Open the start state and terminal state payload explicitly for parametrize
        # within test non success terminal transitions.
        (AttemptState.RUNNING, AttemptState.FAILED),
        (AttemptState.RUNNING, AttemptState.INTERRUPTED),
    ],
)
def test_non_success_terminal_transitions(
    # Keep the queue input explicit in the test non success terminal transitions contract.
    queue: SQLiteJobQueue,
    start_state: AttemptState,
    terminal_state: AttemptState,
) -> None:
    # Execute the test non success terminal transitions workflow in explicit, reviewable
    # steps.
    record = queue.submit(_spec(), f"terminal-{start_state.value}-{terminal_state.value}")
    attempt = queue.claim_next("supervisor", ResourceCapacity(1, 1))
    assert attempt is not None
    if start_state is AttemptState.RUNNING:
        # Handle the test non success terminal transitions start_state is
        # AttemptState.RUNNING branch as a distinct logical block.
        attempt = queue.transition(
            attempt.attempt_id,
            attempt.state_version,
            AttemptState.RUNNING,
        )

    # Assemble terminal once so the test non success terminal transitions workflow shares
    # one value.
    terminal = queue.transition(
        attempt.attempt_id,
        attempt.state_version,
        terminal_state,
    )

    # Verify terminal.state is terminal_state before this scenario is accepted.
    assert terminal.state is terminal_state
    assert queue.get_job(record.job_id).state is terminal_state  # type: ignore[union-attr]


def test_generic_transition_cannot_bypass_verified_completion(queue: SQLiteJobQueue) -> None:
    # Execute the test generic transition cannot bypass verified completion workflow in
    # explicit, reviewable steps.
    record = queue.submit(_spec(), "success")
    attempt = queue.claim_next("supervisor", ResourceCapacity(1, 1))
    assert attempt is not None
    attempt = queue.transition(attempt.attempt_id, attempt.state_version, AttemptState.RUNNING)

    with pytest.raises(UnverifiedJobCompletionError):
        # Invoke transition for attempt id and state version as a visible test generic
        # transition cannot bypass verified completion step.
        queue.transition(attempt.attempt_id, attempt.state_version, AttemptState.SUCCEEDED)

    with pytest.raises(UnverifiedJobCompletionError):
        # Keep raises, unverified job completion error and pytest active only for the
        # bounded test generic transition cannot bypass verified completion operation.
        queue.transition(
            attempt.attempt_id,
            attempt.state_version,
            AttemptState.SUCCEEDED,
            _receipt(attempt, _artifact("9")),
            # Complete transition only after its 9 and attempt id inputs are visible in test
            # generic transition cannot bypass verified completion.
        )
    stored = queue.get_job(record.job_id)
    assert stored is not None
    assert stored.state is AttemptState.RUNNING


def test_invalid_state_transition_is_rejected(queue: SQLiteJobQueue) -> None:
    # Execute the test invalid state transition is rejected workflow in explicit,
    # reviewable steps.
    queue.submit(_spec(), "bad-transition")
    attempt = queue.claim_next("supervisor", ResourceCapacity(1, 1))
    assert attempt is not None

    with pytest.raises(JobStateConflictError) as caught:
        # Keep raises, job state conflict error and pytest active only for the bounded
        # test invalid state transition is rejected operation.
        queue.transition(
            attempt.attempt_id,
            attempt.state_version,
            AttemptState.CANCELLED,
        )

    # Verify the current state, starting and value relationship before this scenario is
    # accepted.
    assert caught.value.current_state is AttemptState.STARTING


def test_cancel_queued_job_is_immediate_and_idempotent(queue: SQLiteJobQueue) -> None:
    # Execute the test cancel queued job is immediate and idempotent workflow in explicit,
    # reviewable steps.
    record = queue.submit(_spec(), "cancel-queued")

    queue.request_cancel(record.job_id)
    queue.request_cancel(record.job_id)

    cancelled = queue.get_job(record.job_id)
    assert cancelled is not None
    # Verify the state, cancelled and attempt state relationship before this scenario is
    # accepted.
    assert cancelled.state is AttemptState.CANCELLED
    assert cancelled.state_version == 1
    assert queue.claim_next("supervisor", ResourceCapacity(1, 1)) is None


def test_cancel_running_job_is_a_durable_flag_then_transition(queue: SQLiteJobQueue) -> None:
    # Execute the test cancel running job is a durable flag then transition workflow in
    # explicit, reviewable steps.
    record = queue.submit(_spec(), "cancel-running")
    attempt = queue.claim_next("supervisor", ResourceCapacity(1, 1))
    assert attempt is not None
    attempt = queue.transition(attempt.attempt_id, attempt.state_version, AttemptState.RUNNING)

    queue.request_cancel(record.job_id)

    # Verify the is cancel requested, job id and queue relationship before this scenario
    # is accepted.
    assert queue.is_cancel_requested(record.job_id)
    still_running = queue.get_job(record.job_id)
    assert still_running is not None
    assert still_running.state is AttemptState.RUNNING
    cancelled = queue.transition(
        # Pass attempt explicitly so transition receives a reviewable attempt id and state
        # version input in test cancel running job is a durable flag then transition.
        attempt.attempt_id,
        attempt.state_version,
        AttemptState.CANCELLED,
    )
    assert cancelled.state is AttemptState.CANCELLED


# Define test cancel cannot lose to late success as one focused operation with an explicit
# boundary.
def test_cancel_cannot_lose_to_late_success(queue: SQLiteJobQueue) -> None:
    # Execute the test cancel cannot lose to late success workflow in explicit, reviewable
    # steps.
    record = queue.submit(_spec(), "cancel-success")
    attempt = queue.claim_next("supervisor", ResourceCapacity(1, 1))
    assert attempt is not None
    attempt = queue.transition(attempt.attempt_id, attempt.state_version, AttemptState.RUNNING)
    queue.request_cancel(record.job_id)

    # Acquire raises, job state conflict error and pytest at an explicit test cancel
    # cannot lose to late success context boundary so cleanup remains scoped.
    with pytest.raises(JobStateConflictError):
        # Keep raises, job state conflict error and pytest active only for the bounded
        # test cancel cannot lose to late success operation.
        queue.complete_verified(
            attempt.attempt_id,
            attempt.state_version,
            _receipt(attempt, _artifact("9")),
        )


# Define test late cancel of successful job is conflict as one focused operation with an
# explicit boundary.
def test_late_cancel_of_successful_job_is_conflict(queue: SQLiteJobQueue) -> None:
    # Execute the test late cancel of successful job is conflict workflow in explicit,
    # reviewable steps.
    record = queue.submit(_spec(), "late-cancel")
    attempt = queue.claim_next("supervisor", ResourceCapacity(1, 1))
    assert attempt is not None
    attempt = queue.transition(attempt.attempt_id, attempt.state_version, AttemptState.RUNNING)
    queue.complete_verified(
        # Pass attempt explicitly so complete_verified receives a reviewable 9 and attempt
        # id input in test late cancel of successful job is conflict.
        attempt.attempt_id,
        attempt.state_version,
        _receipt(attempt, _artifact("9")),
    )

    with pytest.raises(JobStateConflictError) as caught:
        # Invoke request_cancel for job id and record as a visible test late cancel of
        # successful job is conflict step.
        queue.request_cancel(record.job_id)

    assert caught.value.job_id == record.job_id
    assert caught.value.current_state is AttemptState.SUCCEEDED
    assert caught.value.operation == "cancel"


def test_get_and_bounded_filtered_list(queue: SQLiteJobQueue) -> None:
    # Execute the test get and bounded filtered list workflow in explicit, reviewable
    # steps.
    first = queue.submit(_spec("a"), "list-a")
    second = queue.submit(_spec("b"), "list-b")
    queue.request_cancel(first.job_id)

    assert queue.get_job(first.job_id) is not None
    assert queue.list_jobs(state=AttemptState.CANCELLED) == (queue.get_job(first.job_id),)
    # Verify the list jobs, queue and queued relationship before this scenario is
    # accepted.
    assert queue.list_jobs(state=AttemptState.QUEUED) == (queue.get_job(second.job_id),)
    assert len(queue.list_jobs(limit=1)) == 1
