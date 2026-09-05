# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import json
from dataclasses import replace

import pytest

from backtest.application.errors import (
    # Include idempotency conflict error so the errors dependency remains explicit.
    IdempotencyConflictError,
    InvalidIdempotencyKeyError,
    InvalidJobPayloadError,
    JobNotFoundError,
    JobStateConflictError,
    # Close the errors import after its required symbols are visible.
)
from backtest.application.job_commands import (
    ResolvedBacktestJob,
    ResolvedJobCommandError,
    resolved_backtest_job_from_bytes,
    # Close the job commands import after its required symbols are visible.
)
from backtest.application.ml_contracts import ExactInferencePolicy
from backtest.application.models import (
    AttemptState,
    JobAttempt,
    # Include job record so the models dependency remains explicit.
    JobRecord,
    JobType,
    ListJobsRequest,
    ResolvedJobSpec,
    ResourceCapacity,
    # Close the models import after its required symbols are visible.
)
from backtest.application.run_results import RunBackend, RunPhysicalSettings
from backtest.application.run_specs import (
    AssetBalance,
    ReplayInputFormat,
    # Include resolved component so the run specs dependency remains explicit.
    ResolvedComponent,
    ResolvedReplayInput,
    ResolvedRunSpec,
)
from backtest.application.use_cases.cancel_job import CancelJob, CancelJobRequest

# Import query jobs at the visible module dependency boundary.
from backtest.application.use_cases.query_jobs import GetJob, GetJobRequest, ListJobs
from backtest.application.use_cases.submit_job import SubmitJob, SubmitJobRequest
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
    # Close the chain import after its required symbols are visible.
)
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import (
    ArtifactId,
    AssetId,
    # Include attempt id so the identifiers dependency remains explicit.
    AttemptId,
    BundleId,
    ContentDigest,
    DatasetRevisionId,
    JobId,
    # Include logical content hash so the identifiers dependency remains explicit.
    LogicalContentHash,
    RuntimeLockId,
    SnapshotId,
)


# Keep the jobs contract and validation rules together.
class _Jobs:
    def __init__(self) -> None:
        # Execute the jobs init workflow in explicit, reviewable steps.
        self.records: dict[JobId, JobRecord] = {}
        self.keys: dict[tuple[JobType, str], JobRecord] = {}
        self.submitted_specs: list[ResolvedJobSpec] = []
        self.cancel_calls = 0

    def submit(self, spec: ResolvedJobSpec, idempotency_key: str) -> JobRecord:
        # Execute the jobs submit workflow in explicit, reviewable steps.
        namespace = (spec.job_type, idempotency_key)
        existing = self.keys.get(namespace)
        if existing is not None:
            # Handle the jobs submit existing is not None branch as a distinct logical
            # block.
            if existing.spec != spec:
                raise IdempotencyConflictError(spec.job_type, idempotency_key)
            return existing
        record = JobRecord(
            job_id=JobId(f"job-{len(self.records) + 1}"),
            # Pass spec explicitly so JobRecord receives a reviewable job- and records
            # input in jobs submit.
            spec=spec,
            state=AttemptState.QUEUED,
            state_version=0,
        )
        self.records[record.job_id] = record
        # Assemble self keys[namespace] once so the jobs submit workflow shares one value.
        self.keys[namespace] = record
        self.submitted_specs.append(spec)
        return record

    def request_cancel(self, job_id: JobId) -> None:
        # Execute the jobs request cancel workflow in explicit, reviewable steps.
        self.cancel_calls += 1
        record = self.records[job_id]
        self.records[job_id] = replace(
            record,
            state=AttemptState.CANCELLED,
            # Pass state version explicitly so replace receives a reviewable cancelled and
            # state version input in jobs request cancel.
            state_version=record.state_version + 1,
        )

    def claim_next(
        self,
        supervisor_instance_id: str,
        # Keep the capacity input explicit in the claim next contract.
        capacity: ResourceCapacity,
    ) -> JobAttempt | None:
        # Execute the jobs claim next workflow in explicit, reviewable steps.
        del supervisor_instance_id, capacity
        return None

    def transition(
        self,
        attempt_id: AttemptId,
        # Keep the expected version input explicit in the transition contract.
        expected_version: int,
        new_state: AttemptState,
        result_artifact_id: ArtifactId | None = None,
    ) -> JobAttempt:
        # Execute the jobs transition workflow in explicit, reviewable steps.
        del attempt_id, expected_version, new_state, result_artifact_id
        raise AssertionError("transition is not part of these use-case tests")

    def get_job(self, job_id: JobId) -> JobRecord | None:
        return self.records.get(job_id)

    def list_jobs(
        # Keep the remaining list jobs inputs visible at the jobs list jobs boundary.
        self,
        *,
        state: AttemptState | None = None,
        limit: int = 100,
        offset: int = 0,
        # Keep the tuple input explicit in the list jobs contract.
    ) -> tuple[JobRecord, ...]:
        # Execute the jobs list jobs workflow in explicit, reviewable steps.
        records = tuple(reversed(tuple(self.records.values())))
        if state is not None:
            records = tuple(record for record in records if record.state is state)
        return records[offset : offset + limit]


def _request(
    # Keep the payload input explicit in the request contract.
    payload: bytes,
    *,
    key: str = "submit-1",
    artifacts: tuple[ArtifactId, ...] = (),
) -> SubmitJobRequest:
    # Execute the request workflow in explicit, reviewable steps.
    return SubmitJobRequest(
        spec_version=1,
        job_type=JobType.RUN_BACKTEST,
        payload_json=payload,
        idempotency_key=key,
        # Pass input artifact ids explicitly so SubmitJobRequest receives a reviewable run
        # backtest and job type input in request.
        input_artifact_ids=artifacts,
    )


def _payload(*, attempt: str = "a") -> bytes:
    # Execute the payload workflow in explicit, reviewable steps.
    roles = (
        "clock",
        "engine",
        "execution",
        "inference",
        # Keep the latency component named inside the roles contract.
        "latency",
        "protocol:reference",
        "risk",
        "scheduler",
        "strategy",
        # Keep the universe component named inside the roles contract.
        "universe",
        "valuation:price_source",
    )
    components = tuple(
        ResolvedComponent.create(
            # Pass role explicitly so create receives a reviewable x and inference input
            # in payload.
            role=role,
            bundle_id=BundleId(f"{index:x}" * 64),
            config=(
                ExactInferencePolicy.disabled().document()
                if role == "inference"
                # Route all remaining cases through the explicit alternative branch.
                else {"mode": "SHADOW_STATE_REPLAY"}
                if role == "execution"
                else {"version": 1}
            ),
        )
        # Keep the roles enumerate step visible while building components.
        for index, role in enumerate(roles, start=1)
    )
    spec = ResolvedRunSpec.create(
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        # Keep the dataset revision id DatasetRevisionId step visible while building spec.
        dataset_revision_id=DatasetRevisionId("1" * 64),
        logical_content_hash=LogicalContentHash("2" * 64),
        snapshot_id=SnapshotId("3" * 64),
        replay_semantics_id=ContentDigest("4" * 64),
        replay_input=ResolvedReplayInput(ReplayInputFormat.CANONICAL_PARQUET),
        # Pass components explicitly so create receives a reviewable 1 and 2 input in
        # payload.
        components=components,
        runtime_lock_id=RuntimeLockId("5" * 64),
        initial_portfolio=(AssetBalance(AssetId("SOL"), 1_000),),
        root_seed=42,
    )
    # Return the completed payload result without a hidden fallback.
    return ResolvedBacktestJob(
        spec,
        ContentDigest(attempt * 64),
        RunPhysicalSettings(RunBackend.REFERENCE_PYTHON, 65_536, 1, 8_192, 1),
    ).canonical_bytes()


# Define test submit canonicalizes payload and derives stable spec identity as one focused
# operation with an explicit boundary.
def test_submit_canonicalizes_payload_and_derives_stable_spec_identity() -> None:
    # Execute the test submit canonicalizes payload and derives stable spec identity
    # workflow in explicit, reviewable steps.
    jobs = _Jobs()
    use_case = SubmitJob(jobs)
    payload = _payload()
    formatted = json.dumps(json.loads(payload), indent=2).encode()
    expected_input = (ArtifactId("3" * 64),)
    # Assemble first once so the test submit canonicalizes payload and derives stable spec
    # identity workflow shares one value.
    first = use_case.execute(_request(formatted, key="first", artifacts=expected_input))
    second = use_case.execute(_request(payload, key="second"))

    assert first.spec == second.spec
    assert first.spec.canonical_payload == payload
    assert first.spec.input_artifact_ids == expected_input


# Define test resolved backtest parser accepts only installed exact backend as one focused
# operation with an explicit boundary.
def test_resolved_backtest_parser_accepts_only_installed_exact_backend() -> None:
    # Execute the test resolved backtest parser accepts only installed exact backend
    # workflow in explicit, reviewable steps.
    document = json.loads(_payload())
    assert document["schema"] == "backtest.run-job/v2"
    assert document["physical_settings"]["schema"] == "backtest.run-physical-settings/v2"
    document["physical_settings"]["backend"] = "numpy-mmap-first-swap-exact-v1"
    parsed = resolved_backtest_job_from_bytes(canonical_json_bytes(document))

    # Verify the backend, numpy mmap first swap exact and physical settings relationship
    # before this scenario is accepted.
    assert parsed.physical_settings.backend is RunBackend.NUMPY_MMAP_FIRST_SWAP_EXACT

    document["physical_settings"]["backend"] = "silent-fallback"
    with pytest.raises(ResolvedJobCommandError, match="not installed"):
        resolved_backtest_job_from_bytes(canonical_json_bytes(document))


@pytest.mark.parametrize(
    # Open the field and value payload explicitly for parametrize within test resolved
    # backtest parser rejects unsupported physical settings.
    ("field", "value", "message"),
    (
        ("reader_readahead", 3, "1, 2 or 4"),
        ("reader_readahead", True, "integer"),
        ("reader_batch_rows", 0, "positive"),
        # Open the field and value payload explicitly for parametrize within test resolved
        # backtest parser rejects unsupported physical settings.
        ("threads", 0, "positive"),
        ("schema", "backtest.run-physical-settings/v1", "v2 schema"),
    ),
)
def test_resolved_backtest_parser_rejects_unsupported_physical_settings(
    # Keep the field input explicit in the test resolved backtest parser rejects
    # unsupported physical settings contract.
    field: str,
    value: object,
    message: str,
) -> None:
    # Execute the test resolved backtest parser rejects unsupported physical settings
    # workflow in explicit, reviewable steps.
    document = json.loads(_payload())
    document["physical_settings"][field] = value

    with pytest.raises(ResolvedJobCommandError, match=message):
        resolved_backtest_job_from_bytes(canonical_json_bytes(document))


def test_resolved_backtest_parser_rejects_old_unversioned_job_shape() -> None:
    # Execute the test resolved backtest parser rejects old unversioned job shape workflow
    # in explicit, reviewable steps.
    document = json.loads(_payload())
    document["schema"] = "backtest.run-job/v1"
    document["physical_settings"].pop("schema")
    document["physical_settings"].pop("reader_readahead")

    with pytest.raises(ResolvedJobCommandError, match="unsupported backtest job schema"):
        # Invoke resolved_backtest_job_from_bytes for canonical json bytes and document as
        # a visible test resolved backtest parser rejects old unversioned job shape step.
        resolved_backtest_job_from_bytes(canonical_json_bytes(document))


def test_same_idempotency_key_and_same_spec_returns_existing_job() -> None:
    # Execute the test same idempotency key and same spec returns existing job workflow in
    # explicit, reviewable steps.
    jobs = _Jobs()
    use_case = SubmitJob(jobs)
    request = _request(_payload())

    assert use_case.execute(request) == use_case.execute(request)
    assert len(jobs.submitted_specs) == 1


# Define test same idempotency key with different spec is stable conflict as one focused
# operation with an explicit boundary.
def test_same_idempotency_key_with_different_spec_is_stable_conflict() -> None:
    # Execute the test same idempotency key with different spec is stable conflict
    # workflow in explicit, reviewable steps.
    jobs = _Jobs()
    use_case = SubmitJob(jobs)
    use_case.execute(_request(_payload(attempt="a")))

    with pytest.raises(IdempotencyConflictError):
        use_case.execute(_request(_payload(attempt="b")))


# Apply parametrize semantics to the following test invalid or secret bearing payload is
# rejected before queue contract.
@pytest.mark.parametrize(
    "payload",
    [
        b'{"threshold":0.75}',
        b'{"seed":1,"seed":2}',
        # Pass credentials explicitly so parametrize receives a reviewable payload input
        # in test invalid or secret bearing payload is rejected before queue.
        b'{"credentials":{"password":"must-not-persist"}}',
        b'["root-must-be-object"]',
        b"not-json",
    ],
)
# Define test invalid or secret bearing payload is rejected before queue as one focused
# operation with an explicit boundary.
def test_invalid_or_secret_bearing_payload_is_rejected_before_queue(payload: bytes) -> None:
    # Execute the test invalid or secret bearing payload is rejected before queue workflow
    # in explicit, reviewable steps.
    jobs = _Jobs()
    with pytest.raises(InvalidJobPayloadError):
        SubmitJob(jobs).execute(_request(payload))

    assert not jobs.submitted_specs


@pytest.mark.parametrize("key", ["", " leading", "trailing ", "line\nbreak"])
# Define test invalid idempotency key is rejected before queue as one focused operation
# with an explicit boundary.
def test_invalid_idempotency_key_is_rejected_before_queue(key: str) -> None:
    # Execute the test invalid idempotency key is rejected before queue workflow in
    # explicit, reviewable steps.
    jobs = _Jobs()
    with pytest.raises(InvalidIdempotencyKeyError):
        SubmitJob(jobs).execute(_request(_payload(), key=key))

    assert not jobs.submitted_specs


def test_resolved_spec_rejects_mismatched_payload_digest() -> None:
    # Execute the test resolved spec rejects mismatched payload digest workflow in
    # explicit, reviewable steps.
    jobs = _Jobs()
    spec = SubmitJob(jobs).execute(_request(_payload())).spec

    with pytest.raises(ValueError, match="payload_digest"):
        replace(spec, payload_digest=ContentDigest("f" * 64))


def test_get_and_bounded_filtered_list_use_read_only_query_port() -> None:
    # Execute the test get and bounded filtered list use read only query port workflow in
    # explicit, reviewable steps.
    jobs = _Jobs()
    submit = SubmitJob(jobs)
    first = submit.execute(_request(_payload(attempt="a"), key="first"))
    second = submit.execute(_request(_payload(attempt="b"), key="second"))
    jobs.records[first.job_id] = replace(first, state=AttemptState.CANCELLED)

    # Verify the second, execute and get job request relationship before this scenario is
    # accepted.
    assert GetJob(jobs).execute(GetJobRequest(second.job_id)) == second
    assert ListJobs(jobs).execute(ListJobsRequest(limit=1)) == (second,)
    assert ListJobs(jobs).execute(ListJobsRequest(state=AttemptState.CANCELLED)) == (
        jobs.records[first.job_id],
    )


# Define test get missing job raises stable not found as one focused operation with an
# explicit boundary.
def test_get_missing_job_raises_stable_not_found() -> None:
    # Execute the test get missing job raises stable not found workflow in explicit,
    # reviewable steps.
    with pytest.raises(JobNotFoundError):
        GetJob(_Jobs()).execute(GetJobRequest(JobId("missing")))


def test_cancel_is_durable_and_already_cancelled_is_idempotent() -> None:
    # Execute the test cancel is durable and already cancelled is idempotent workflow in
    # explicit, reviewable steps.
    jobs = _Jobs()
    record = SubmitJob(jobs).execute(_request(_payload()))
    cancel = CancelJob(jobs, jobs)

    cancelled = cancel.execute(CancelJobRequest(record.job_id))
    repeated = cancel.execute(CancelJobRequest(record.job_id))

    # Verify the state, cancelled and attempt state relationship before this scenario is
    # accepted.
    assert cancelled.state is AttemptState.CANCELLED
    assert repeated == cancelled
    assert jobs.cancel_calls == 1


@pytest.mark.parametrize(
    "state",
    # Open the state and succeeded payload explicitly for parametrize within test cancel
    # rejects non cancellable terminal state.
    [AttemptState.SUCCEEDED, AttemptState.FAILED, AttemptState.INTERRUPTED],
)
def test_cancel_rejects_non_cancellable_terminal_state(state: AttemptState) -> None:
    # Execute the test cancel rejects non cancellable terminal state workflow in explicit,
    # reviewable steps.
    jobs = _Jobs()
    record = SubmitJob(jobs).execute(_request(_payload()))
    jobs.records[record.job_id] = replace(record, state=state)

    with pytest.raises(JobStateConflictError) as caught:
        CancelJob(jobs, jobs).execute(CancelJobRequest(record.job_id))

    # Verify caught.value.current_state is state before this scenario is accepted.
    assert caught.value.current_state is state
    assert jobs.cancel_calls == 0
