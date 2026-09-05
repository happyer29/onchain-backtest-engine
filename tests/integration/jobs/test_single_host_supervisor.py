# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass, replace
from hashlib import sha256

# Import pathlib at the visible module dependency boundary.
from pathlib import Path

import pytest

from backtest.adapters.artifacts.localfs import (
    DataRootLayout,
    LocalArtifactRepository,
    # Include local completion receipt store so the localfs dependency remains explicit.
    LocalCompletionReceiptStore,
)
from backtest.adapters.catalog.sqlite import SQLiteArtifactCatalog, SQLiteJobQueue
from backtest.adapters.process.local import ProcessSpawnError
from backtest.application.canonical_json import resolved_job_spec_hex

# Import completion at the visible module dependency boundary.
from backtest.application.completion import AttemptCompletionReceipt, CompletionOutput
from backtest.application.errors import JobStateConflictError
from backtest.application.models import (
    ArtifactDraft,
    ArtifactKind,
    # Include attempt state so the models dependency remains explicit.
    AttemptState,
    JobAttempt,
    JobType,
    ProcessHandle,
    ProcessState,
    # Include process status so the models dependency remains explicit.
    ProcessStatus,
    ProgressEvent,
    ProgressLevel,
    ProgressStage,
    ResolvedJobSpec,
    # Close the models import after its required symbols are visible.
)
from backtest.application.supervisor import (
    AttemptFailureKind,
    HostResourceBudget,
    JobExecutionPolicy,
    # Include job lane so the supervisor dependency remains explicit.
    JobLane,
    JobResourceDemand,
    RetryPolicy,
)
from backtest.application.use_cases.complete_job_attempt import (
    # Include complete job attempt so the complete job attempt dependency remains
    # explicit.
    CompleteJobAttempt,
    CompleteJobAttemptRequest,
)
from backtest.application.use_cases.supervise_jobs import (
    ControllerAuthorityLostError,
    # Include single host supervisor so the supervise jobs dependency remains explicit.
    SingleHostSupervisor,
)
from backtest.domain.identifiers import ArtifactId, AttemptId, ContentDigest, JobId
from backtest.runtime.local_admission import LocalAdmissionController


# Keep the authority contract and validation rules together.
@dataclass
class _Authority:
    instance_id: str
    locked: bool = True


# Keep the clock contract and validation rules together.
@dataclass
class _Clock:
    value: int = 0

    def now_ns(self) -> int:
        return self.value


# Keep the processes contract and validation rules together.
class _Processes:
    def __init__(self) -> None:
        # Execute the processes init workflow in explicit, reviewable steps.
        self.spawned: list[tuple[JobAttempt, int, ProcessHandle]] = []
        self.terminated: list[tuple[ProcessHandle, float]] = []
        self.statuses: dict[ProcessHandle, ProcessStatus] = {}
        self.fail_next_spawn = False
        self.cleaned: list[AttemptId] = []

    # Define processes spawn as one focused operation with an explicit boundary.
    def spawn(self, attempt: JobAttempt, *, native_threads: int) -> ProcessHandle:
        # Execute the processes spawn workflow in explicit, reviewable steps.
        if self.fail_next_spawn:
            # Handle the processes spawn self.fail_next_spawn branch as a distinct logical
            # block.
            self.fail_next_spawn = False
            raise ProcessSpawnError("safe test spawn failure")
        handle = ProcessHandle(10_000 + len(self.spawned), f"token-{len(self.spawned)}")
        self.spawned.append((attempt, native_threads, handle))
        self.statuses[handle] = ProcessStatus(ProcessState.RUNNING)
        # Return the completed processes spawn result without a hidden fallback.
        return handle

    def probe(self, handle: ProcessHandle) -> ProcessStatus:
        return self.statuses[handle]

    def terminate(self, handle: ProcessHandle, grace_seconds: float) -> None:
        # Execute the processes terminate workflow in explicit, reviewable steps.
        self.terminated.append((handle, grace_seconds))
        self.statuses[handle] = ProcessStatus(ProcessState.EXITED, -15)

    def exit(self, handle: ProcessHandle, exit_code: int) -> None:
        self.statuses[handle] = ProcessStatus(ProcessState.EXITED, exit_code)

    def cleanup_launch(self, attempt_id: AttemptId) -> None:
        # Invoke append for attempt id as a visible processes cleanup launch step.
        self.cleaned.append(attempt_id)


# Keep the harness contract and validation rules together.
@dataclass
class _Harness:
    queue: SQLiteJobQueue
    repository: LocalArtifactRepository
    catalog: SQLiteArtifactCatalog
    # Declare receipts explicitly in the harness contract.
    receipts: LocalCompletionReceiptStore
    completer: CompleteJobAttempt


def _harness(tmp_path: Path) -> _Harness:
    # Execute the harness workflow in explicit, reviewable steps.
    database = tmp_path / "catalog.sqlite"
    queue = SQLiteJobQueue(database)
    repository = LocalArtifactRepository(tmp_path / "var")
    catalog = SQLiteArtifactCatalog(database, repository)
    receipts = LocalCompletionReceiptStore(DataRootLayout(tmp_path / "var"))
    # Return the completed harness result without a hidden fallback.
    return _Harness(
        queue=queue,
        repository=repository,
        catalog=catalog,
        receipts=receipts,
        # Include completer in the completed harness result.
        completer=CompleteJobAttempt(queue, catalog, receipts),
    )


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


def _policy(
    lane: JobLane,
    *,
    retryable: frozenset[AttemptFailureKind] = frozenset(),
    # Keep the max attempts input explicit in the policy contract.
    max_attempts: int = 1,
    backoff_ns: int = 0,
    timeout_ns: int = 1_000,
    lease_ns: int = 300,
) -> JobExecutionPolicy:
    # Execute the policy workflow in explicit, reviewable steps.
    return JobExecutionPolicy(
        lane=lane,
        demand=JobResourceDemand(
            private_memory_bytes=2_000,
            native_threads=2,
            # Pass io units explicitly into JobResourceDemand within policy.
            io_units=1,
        ),
        timeout_ns=timeout_ns,
        termination_grace_seconds=0.25,
        lease_duration_ns=lease_ns,
        # Include retry in the completed policy result.
        retry=RetryPolicy(
            max_attempts=max_attempts,
            retryable_kinds=retryable,
            base_backoff_ns=backoff_ns,
            max_backoff_ns=backoff_ns,
            # Complete RetryPolicy only after its max attempts and retryable inputs are
            # visible in policy.
        ),
    )


def _supervisor(
    harness: _Harness,
    processes: _Processes,
    # Keep the clock input explicit in the supervisor contract.
    clock: _Clock,
    authority: _Authority,
    policies: dict[JobType, JobExecutionPolicy],
    *,
    max_runs: int = 2,
    # Keep the progress interval ns input explicit in the supervisor contract.
    progress_interval_ns: int = 500_000_000,
) -> SingleHostSupervisor:
    # Execute the supervisor workflow in explicit, reviewable steps.
    admission = LocalAdmissionController(
        HostResourceBudget(
            private_memory_bytes=8_000,
            physical_cores=8,
            io_units=4,
            # Pass max children explicitly so HostResourceBudget receives a reviewable max
            # runs input in supervisor.
            max_children=3,
            max_builders=1,
            max_runs=max_runs,
        )
    )
    # Return the completed supervisor result without a hidden fallback.
    return SingleHostSupervisor(
        authority=authority,
        queue=harness.queue,
        processes=processes,
        admission=admission,
        # Pass completer explicitly so SingleHostSupervisor receives a reviewable queue
        # and completer input in supervisor.
        completer=harness.completer,
        policies=policies,
        clock=clock,
        progress_interval_ns=progress_interval_ns,
    )


# Define publish completion as one focused operation with an explicit boundary.
def _publish_completion(
    harness: _Harness,
    attempt: JobAttempt,
    *,
    build_character: str = "1",
    # Keep the artifact id input explicit in the publish completion contract.
) -> ArtifactId:
    # Execute the publish completion workflow in explicit, reviewable steps.
    writer = harness.repository.stage(
        ArtifactDraft(
            kind=ArtifactKind.RUN,
            build_key=ContentDigest(build_character * 64),
        )
        # Complete stage only after its run and artifact draft inputs are visible in publish
        # completion.
    )
    with writer.open_binary("summary.json") as stream:
        stream.write(b"{}")
    manifest = (
        b'{"execution_attempt_id":"'
        + sha256(attempt.attempt_id.value.encode()).hexdigest().encode()
        + b'","logical_run_id":"'
        + sha256(attempt.job_id.value.encode()).hexdigest().encode()
        + b'","version":1}'
    )
    artifact = writer.commit(manifest, identity_manifest_bytes=manifest)
    harness.catalog.index_committed(artifact)
    # Invoke publish for attempt id and spec id as a visible publish completion step.
    harness.receipts.publish(
        AttemptCompletionReceipt(
            version=1,
            attempt_id=attempt.attempt_id,
            resolved_spec_id=attempt.spec.spec_id,
            # Pass result artifact id explicitly so AttemptCompletionReceipt receives a
            # reviewable attempt id and spec id input in publish completion.
            result_artifact_id=artifact.artifact_id,
            outputs=(CompletionOutput(artifact.artifact_id, artifact.manifest_digest),),
        )
    )
    return artifact.artifact_id


# Define failure code as one focused operation with an explicit boundary.
def _failure_code(harness: _Harness, job_id: JobId) -> str:
    # Execute the failure code workflow in explicit, reviewable steps.
    connection = sqlite3.connect(harness.queue.database_path)
    try:
        # Perform the protected failure code operation before explicit failure handling.
        row = connection.execute(
            """
            SELECT f.failure_code
            FROM attempt_failures AS f
            JOIN job_attempts AS a ON a.attempt_id = f.attempt_id
            WHERE a.job_id = ?
            ORDER BY a.attempt_number DESC
            LIMIT 1
            """,
            (str(job_id),),
        ).fetchone()
    finally:
        # Invoke close as a visible step within the failure code workflow.
        connection.close()
    assert row is not None
    return str(row[0])


@pytest.mark.integration
def test_separate_build_and_run_lanes_share_global_admission(tmp_path: Path) -> None:
    # Execute the test separate build and run lanes share global admission workflow in
    # explicit, reviewable steps.
    harness = _harness(tmp_path)
    for index in range(2):
        # Process range(2) inside the bounded test separate build and run lanes share
        # global admission loop.
        harness.queue.submit(_spec(JobType.PREPARE_DATASET, f"build-{index}"), f"build-{index}")
        harness.queue.submit(_spec(JobType.RUN_BACKTEST, f"run-{index}"), f"run-{index}")
    unknown = harness.queue.submit(_spec(JobType.GC, "unconfigured"), "unconfigured")
    processes = _Processes()
    supervisor = _supervisor(
        # Pass harness explicitly so _supervisor receives a reviewable controller and
        # prepare dataset input in test separate build and run lanes share global
        # admission.
        harness,
        processes,
        _Clock(),
        _Authority("controller"),
        {
            # Keep the build _policy step visible while building supervisor.
            JobType.PREPARE_DATASET: _policy(JobLane.BUILD),
            JobType.RUN_BACKTEST: _policy(JobLane.RUN),
        },
        max_runs=1,
    )

    # Assemble result once so the test separate build and run lanes share global admission
    # workflow shares one value.
    result = supervisor.run_cycle()

    assert result.started == 2
    assert {item[0].spec.job_type for item in processes.spawned} == {
        JobType.PREPARE_DATASET,
        JobType.RUN_BACKTEST,
        # Verify the job type, prepare dataset and run backtest relationship before this
        # scenario is accepted.
    }
    assert {item[1] for item in processes.spawned} == {2}
    unconfigured = harness.queue.get_job(unknown.job_id)
    assert unconfigured is not None
    assert unconfigured.state is AttemptState.QUEUED


# Apply integration semantics to the following test exit zero without verified receipt
# fails closed contract.
@pytest.mark.integration
def test_exit_zero_without_verified_receipt_fails_closed(tmp_path: Path) -> None:
    # Execute the test exit zero without verified receipt fails closed workflow in
    # explicit, reviewable steps.
    harness = _harness(tmp_path)
    record = harness.queue.submit(_spec(JobType.RUN_BACKTEST, "missing"), "missing")
    processes = _Processes()
    supervisor = _supervisor(
        harness,
        # Pass processes explicitly so _supervisor receives a reviewable controller and
        # run backtest input in test exit zero without verified receipt fails closed.
        processes,
        _Clock(),
        _Authority("controller"),
        {JobType.RUN_BACKTEST: _policy(JobLane.RUN)},
    )
    # Invoke run_cycle as a visible step within the test exit zero without verified
    # receipt fails closed workflow.
    supervisor.run_cycle()
    processes.exit(processes.spawned[0][2], 0)

    result = supervisor.run_cycle()

    assert result.failed == 1
    stored = harness.queue.get_job(record.job_id)
    # Verify stored is not None before this scenario is accepted.
    assert stored is not None
    assert stored.state is AttemptState.FAILED


@pytest.mark.integration
def test_verified_receipt_is_the_only_success_path(tmp_path: Path) -> None:
    # Execute the test verified receipt is the only success path workflow in explicit,
    # reviewable steps.
    harness = _harness(tmp_path)
    record = harness.queue.submit(_spec(JobType.RUN_BACKTEST, "success"), "success")
    processes = _Processes()
    supervisor = _supervisor(
        harness,
        # Pass processes explicitly so _supervisor receives a reviewable controller and
        # run backtest input in test verified receipt is the only success path.
        processes,
        _Clock(),
        _Authority("controller"),
        {JobType.RUN_BACKTEST: _policy(JobLane.RUN)},
    )
    # Invoke run_cycle as a visible step within the test verified receipt is the only
    # success path workflow.
    supervisor.run_cycle()
    running = harness.queue.list_unfinished_attempts()[0].attempt
    _publish_completion(harness, running)
    processes.exit(processes.spawned[0][2], 0)

    result = supervisor.run_cycle()

    # Verify result.completed == 1 before this scenario is accepted.
    assert result.completed == 1
    stored = harness.queue.get_job(record.job_id)
    assert stored is not None
    assert stored.state is AttemptState.SUCCEEDED


@pytest.mark.integration
# Define test transient failure retries with new attempt and exact same spec as one
# focused operation with an explicit boundary.
def test_transient_failure_retries_with_new_attempt_and_exact_same_spec(tmp_path: Path) -> None:
    # Execute the test transient failure retries with new attempt and exact same spec
    # workflow in explicit, reviewable steps.
    harness = _harness(tmp_path)
    record = harness.queue.submit(_spec(JobType.RUN_BACKTEST, "retry"), "retry")
    processes = _Processes()
    clock = _Clock()
    supervisor = _supervisor(
        # Pass harness explicitly so _supervisor receives a reviewable controller and run
        # backtest input in test transient failure retries with new attempt and exact same
        # spec.
        harness,
        processes,
        clock,
        _Authority("controller"),
        {
            # Keep the run _policy step visible while building supervisor.
            JobType.RUN_BACKTEST: _policy(
                JobLane.RUN,
                retryable=frozenset({AttemptFailureKind.TRANSIENT}),
                max_attempts=2,
                backoff_ns=10,
                # Complete _policy only after its run and transient inputs are visible in test
                # transient failure retries with new attempt and exact same spec.
            )
        },
    )
    supervisor.run_cycle()
    first = harness.queue.list_unfinished_attempts()[0].attempt
    # Invoke exit for spawned and processes as a visible test transient failure retries
    # with new attempt and exact same spec step.
    processes.exit(processes.spawned[0][2], 75)
    clock.value = 20

    supervisor.run_cycle()
    queued = harness.queue.get_job(record.job_id)
    assert queued is not None
    # Verify queued.state is AttemptState.QUEUED before this scenario is accepted.
    assert queued.state is AttemptState.QUEUED
    assert harness.queue.list_unfinished_attempts() == ()

    clock.value = 30
    supervisor.run_cycle()
    second = harness.queue.list_unfinished_attempts()[0].attempt
    # Verify second.attempt_id != first.attempt_id before this scenario is accepted.
    assert second.attempt_id != first.attempt_id
    assert second.spec == first.spec

    processes.exit(processes.spawned[-1][2], 75)
    clock.value = 40
    supervisor.run_cycle()
    # Assemble failed once so the test transient failure retries with new attempt and
    # exact same spec workflow shares one value.
    failed = harness.queue.get_job(record.job_id)
    assert failed is not None
    assert failed.state is AttemptState.FAILED


@pytest.mark.integration
def test_cancel_and_timeout_terminate_before_terminal_transition(tmp_path: Path) -> None:
    # Execute the test cancel and timeout terminate before terminal transition workflow in
    # explicit, reviewable steps.
    harness = _harness(tmp_path)
    cancelled_record = harness.queue.submit(
        _spec(JobType.RUN_BACKTEST, "cancel"),
        "cancel",
    )
    # Assemble processes once so the test cancel and timeout terminate before terminal
    # transition workflow shares one value.
    processes = _Processes()
    clock = _Clock()
    supervisor = _supervisor(
        harness,
        processes,
        # Pass clock explicitly so _supervisor receives a reviewable controller and run
        # backtest input in test cancel and timeout terminate before terminal transition.
        clock,
        _Authority("controller"),
        {JobType.RUN_BACKTEST: _policy(JobLane.RUN, timeout_ns=100)},
        max_runs=1,
    )
    # Invoke run_cycle as a visible step within the test cancel and timeout terminate
    # before terminal transition workflow.
    supervisor.run_cycle()
    harness.queue.request_cancel(cancelled_record.job_id)

    cancel_result = supervisor.run_cycle()

    assert cancel_result.cancelled == 1
    assert processes.terminated[0][1] == 0.25
    # Assemble cancelled once so the test cancel and timeout terminate before terminal
    # transition workflow shares one value.
    cancelled = harness.queue.get_job(cancelled_record.job_id)
    assert cancelled is not None
    assert cancelled.state is AttemptState.CANCELLED

    timeout_record = harness.queue.submit(
        _spec(JobType.RUN_BACKTEST, "timeout"),
        # Pass timeout explicitly so submit receives a reviewable timeout and run backtest
        # input in test cancel and timeout terminate before terminal transition.
        "timeout",
    )
    supervisor.run_cycle()
    clock.value = 100

    timeout_result = supervisor.run_cycle()

    # Verify timeout_result.failed == 1 before this scenario is accepted.
    assert timeout_result.failed == 1
    timed_out = harness.queue.get_job(timeout_record.job_id)
    assert timed_out is not None
    assert timed_out.state is AttemptState.FAILED
    assert len(processes.terminated) == 2


# Apply integration semantics to the following test cancel after result publication never
# attaches success to job contract.
@pytest.mark.integration
def test_cancel_after_result_publication_never_attaches_success_to_job(tmp_path: Path) -> None:
    # Execute the test cancel after result publication never attaches success to job
    # workflow in explicit, reviewable steps.
    harness = _harness(tmp_path)
    record = harness.queue.submit(
        _spec(JobType.RUN_BACKTEST, "cancel-during-publication"),
        "cancel-during-publication",
    )
    # Assemble processes once so the test cancel after result publication never attaches
    # success to job workflow shares one value.
    processes = _Processes()
    supervisor = _supervisor(
        harness,
        processes,
        _Clock(),
        # Keep the controller _Authority step visible while building supervisor.
        _Authority("controller"),
        {JobType.RUN_BACKTEST: _policy(JobLane.RUN)},
    )
    supervisor.run_cycle()
    running = harness.queue.list_unfinished_attempts()[0].attempt

    # Assemble published artifact id once so the test cancel after result publication
    # never attaches success to job workflow shares one value.
    published_artifact_id = _publish_completion(harness, running)
    harness.queue.request_cancel(record.job_id)

    result = supervisor.run_cycle()

    assert result.cancelled == 1
    assert result.completed == 0
    # Assemble cancelled once so the test cancel after result publication never attaches
    # success to job workflow shares one value.
    cancelled = harness.queue.get_job(record.job_id)
    assert cancelled is not None
    assert cancelled.state is AttemptState.CANCELLED
    with closing(sqlite3.connect(harness.queue.database_path)) as connection:
        # Keep closing, connect and database path active only for the bounded test cancel
        # after result publication never attaches success to job operation.
        stored_result = connection.execute(
            "SELECT result_artifact_id FROM job_attempts WHERE attempt_id = ?",
            (str(running.attempt_id),),
        ).fetchone()
    assert stored_result == (None,)
    # Acquire open committed, published artifact id and repository at an explicit test
    # cancel after result publication never attaches success to job context boundary so
    # cleanup remains scoped.
    with harness.repository.open_committed(published_artifact_id) as orphan:
        assert orphan.descriptor.artifact_id == published_artifact_id
    assert processes.terminated == [(processes.spawned[0][2], 0.25)]


@pytest.mark.integration
def test_heartbeat_renews_durable_lease_without_job_event_spam(tmp_path: Path) -> None:
    # Execute the test heartbeat renews durable lease without job event spam workflow in
    # explicit, reviewable steps.
    harness = _harness(tmp_path)
    harness.queue.submit(_spec(JobType.RUN_BACKTEST, "heartbeat"), "heartbeat")
    processes = _Processes()
    clock = _Clock()
    supervisor = _supervisor(
        # Pass harness explicitly so _supervisor receives a reviewable controller and run
        # backtest input in test heartbeat renews durable lease without job event spam.
        harness,
        processes,
        clock,
        _Authority("controller"),
        {JobType.RUN_BACKTEST: _policy(JobLane.RUN, lease_ns=90)},
        # Complete _supervisor only after its controller and run backtest inputs are visible
        # in test heartbeat renews durable lease without job event spam.
    )
    supervisor.run_cycle()
    clock.value = 30

    result = supervisor.run_cycle()

    assert result.heartbeats == 1
    # Assemble runtime once so the test heartbeat renews durable lease without job event
    # spam workflow shares one value.
    runtime = harness.queue.list_unfinished_attempts()[0]
    assert runtime.heartbeat_at_ns == 30
    assert runtime.lease_expires_at_ns == 120


@pytest.mark.integration
def test_progress_is_coalesced_rate_limited_and_written_only_by_supervisor(
    # Keep the tmp path input explicit in the test progress is coalesced rate limited and
    # written only by supervisor contract.
    tmp_path: Path,
) -> None:
    # Execute the test progress is coalesced rate limited and written only by supervisor
    # workflow in explicit, reviewable steps.
    harness = _harness(tmp_path)
    record = harness.queue.submit(_spec(JobType.RUN_BACKTEST, "progress"), "progress")
    processes = _Processes()
    clock = _Clock()
    supervisor = _supervisor(
        # Pass harness explicitly so _supervisor receives a reviewable controller and run
        # backtest input in test progress is coalesced rate limited and written only by
        # supervisor.
        harness,
        processes,
        clock,
        _Authority("controller"),
        {JobType.RUN_BACKTEST: _policy(JobLane.RUN)},
        # Pass progress interval ns explicitly so _supervisor receives a reviewable
        # controller and run backtest input in test progress is coalesced rate limited and
        # written only by supervisor.
        progress_interval_ns=10,
    )
    supervisor.run_cycle()
    attempt = harness.queue.list_unfinished_attempts()[0].attempt
    handle = processes.spawned[0][2]
    # Assemble processes statuses[handle] once so the test progress is coalesced rate
    # limited and written only by supervisor workflow shares one value.
    processes.statuses[handle] = ProcessStatus(
        ProcessState.RUNNING,
        private_rss_bytes=100,
        total_rss_bytes=120,
        major_page_faults=2,
        # Pass temporary disk bytes explicitly so ProcessStatus receives a reviewable
        # running and attempt id input in test progress is coalesced rate limited and
        # written only by supervisor.
        temporary_disk_bytes=0,
        progress_events=(
            ProgressEvent(
                attempt.attempt_id,
                1,
                # Pass progress level explicitly so ProgressEvent receives a reviewable
                # attempt id and info input in test progress is coalesced rate limited and
                # written only by supervisor.
                ProgressLevel.INFO,
                ProgressStage.VALIDATING_INPUTS,
            ),
            ProgressEvent(
                attempt.attempt_id,
                # Keep progress event, attempt id and info visible while completing
                # ProgressEvent within test progress is coalesced rate limited and written
                # only by supervisor.
                2,
                ProgressLevel.INFO,
                ProgressStage.RUNNING_BACKTEST,
            ),
        ),
        # Complete ProcessStatus only after its running and attempt id inputs are visible in
        # test progress is coalesced rate limited and written only by supervisor.
    )
    clock.value = 1

    supervisor.run_cycle()

    progress = tuple(
        event
        # Keep the job id list_job_events step visible while building progress.
        for event in harness.queue.list_job_events(record.job_id)
        if event.progress is not None
    )
    assert len(progress) == 1
    assert progress[0].progress is not None
    # Verify the stage, running backtest and progress relationship before this scenario is
    # accepted.
    assert progress[0].progress.stage is ProgressStage.RUNNING_BACKTEST
    assert progress[0].progress.coalesced_events == 2
    assert progress[0].progress.private_rss_bytes == 100

    processes.statuses[handle] = ProcessStatus(
        ProcessState.RUNNING,
        # Pass progress events explicitly so ProcessStatus receives a reviewable running
        # and attempt id input in test progress is coalesced rate limited and written only
        # by supervisor.
        progress_events=(
            ProgressEvent(
                attempt.attempt_id,
                3,
                ProgressLevel.INFO,
                # Pass progress stage explicitly so ProgressEvent receives a reviewable
                # attempt id and info input in test progress is coalesced rate limited and
                # written only by supervisor.
                ProgressStage.VERIFYING_OUTPUTS,
            ),
        ),
    )
    clock.value = 2
    # Invoke run_cycle as a visible step within the test progress is coalesced rate
    # limited and written only by supervisor workflow.
    supervisor.run_cycle()
    assert (
        sum(event.progress is not None for event in harness.queue.list_job_events(record.job_id))
        == 1
    )

    # Assemble processes statuses[handle] once so the test progress is coalesced rate
    # limited and written only by supervisor workflow shares one value.
    processes.statuses[handle] = ProcessStatus(ProcessState.RUNNING)
    clock.value = 11
    supervisor.run_cycle()
    progress = tuple(
        event.progress
        # Keep the job id list_job_events step visible while building progress.
        for event in harness.queue.list_job_events(record.job_id)
        if event.progress is not None
    )
    assert len(progress) == 2
    assert progress[-1] is not None
    # Verify the stage, verifying outputs and progress stage relationship before this
    # scenario is accepted.
    assert progress[-1].stage is ProgressStage.VERIFYING_OUTPUTS
    assert progress[-1].sequence == 3


@pytest.mark.integration
def test_sustained_private_rss_breach_terminates_before_oom(tmp_path: Path) -> None:
    # Execute the test sustained private rss breach terminates before oom workflow in
    # explicit, reviewable steps.
    harness = _harness(tmp_path)
    record = harness.queue.submit(_spec(JobType.RUN_BACKTEST, "rss-limit"), "rss-limit")
    processes = _Processes()
    policy = replace(
        _policy(JobLane.RUN),
        # Pass memory breach samples explicitly so replace receives a reviewable run and
        # policy input in test sustained private rss breach terminates before oom.
        memory_breach_samples=2,
    )
    supervisor = _supervisor(
        harness,
        processes,
        # Keep the clock _Clock step visible while building supervisor.
        _Clock(),
        _Authority("controller"),
        {JobType.RUN_BACKTEST: policy},
    )
    supervisor.run_cycle()
    # Assemble handle once so the test sustained private rss breach terminates before oom
    # workflow shares one value.
    handle = processes.spawned[0][2]
    processes.statuses[handle] = ProcessStatus(
        ProcessState.RUNNING,
        private_rss_bytes=policy.demand.private_memory_bytes + 1,
    )

    # Verify supervisor.run_cycle().failed == 0 before this scenario is accepted.
    assert supervisor.run_cycle().failed == 0
    result = supervisor.run_cycle()

    assert result.failed == 1
    assert processes.terminated == [(handle, 0.25)]
    failed = harness.queue.get_job(record.job_id)
    # Verify the failed, state and attempt state relationship before this scenario is
    # accepted.
    assert failed is not None and failed.state is AttemptState.FAILED
    assert _failure_code(harness, record.job_id) == "MEMORY_LIMIT_EXCEEDED"


@pytest.mark.integration
def test_required_resource_observation_fails_closed_when_probe_stays_empty(
    tmp_path: Path,
    # Close the test required resource observation fails closed when probe stays empty
    # signature after its explicit inputs.
) -> None:
    # Execute the test required resource observation fails closed when probe stays empty
    # workflow in explicit, reviewable steps.
    harness = _harness(tmp_path)
    record = harness.queue.submit(_spec(JobType.RUN_BACKTEST, "no-metrics"), "no-metrics")
    processes = _Processes()
    policy = replace(
        _policy(JobLane.RUN),
        # Pass memory breach samples explicitly so replace receives a reviewable run and
        # policy input in test required resource observation fails closed when probe stays
        # empty.
        memory_breach_samples=2,
        require_resource_observation=True,
    )
    supervisor = _supervisor(
        harness,
        # Pass processes explicitly so _supervisor receives a reviewable controller and
        # run backtest input in test required resource observation fails closed when probe
        # stays empty.
        processes,
        _Clock(),
        _Authority("controller"),
        {JobType.RUN_BACKTEST: policy},
    )
    # Invoke run_cycle as a visible step within the test required resource observation
    # fails closed when probe stays empty workflow.
    supervisor.run_cycle()

    assert supervisor.run_cycle().failed == 0
    assert supervisor.run_cycle().failed == 1
    assert _failure_code(harness, record.job_id) == "RESOURCE_OBSERVATION_UNAVAILABLE"


@pytest.mark.integration
# Define test sustained swap activity and tmp overage fail with distinct codes as one
# focused operation with an explicit boundary.
def test_sustained_swap_activity_and_tmp_overage_fail_with_distinct_codes(
    tmp_path: Path,
) -> None:
    # Execute the test sustained swap activity and tmp overage fail with distinct codes
    # workflow in explicit, reviewable steps.
    harness = _harness(tmp_path)
    swap_job = harness.queue.submit(_spec(JobType.RUN_BACKTEST, "swap"), "swap")
    processes = _Processes()
    policy = replace(_policy(JobLane.RUN), swap_activity_samples=2)
    supervisor = _supervisor(
        # Pass harness explicitly so _supervisor receives a reviewable controller and run
        # backtest input in test sustained swap activity and tmp overage fail with
        # distinct codes.
        harness,
        processes,
        _Clock(),
        _Authority("controller"),
        {JobType.RUN_BACKTEST: policy},
        # Pass max runs explicitly so _supervisor receives a reviewable controller and run
        # backtest input in test sustained swap activity and tmp overage fail with
        # distinct codes.
        max_runs=1,
    )
    supervisor.run_cycle()
    swap_handle = processes.spawned[0][2]
    for counter in (100, 200):
        # Process (100, 200) inside the bounded test sustained swap activity and tmp
        # overage fail with distinct codes loop.
        processes.statuses[swap_handle] = ProcessStatus(
            ProcessState.RUNNING,
            private_rss_bytes=1_000,
            host_swap_out_bytes=counter,
        )
        # Verify supervisor.run_cycle().failed == 0 before this scenario is accepted.
        assert supervisor.run_cycle().failed == 0
    processes.statuses[swap_handle] = ProcessStatus(
        ProcessState.RUNNING,
        private_rss_bytes=1_000,
        host_swap_out_bytes=300,
        # Complete ProcessStatus only after its running and process state inputs are visible
        # in test sustained swap activity and tmp overage fail with distinct codes.
    )
    assert supervisor.run_cycle().failed == 1
    assert _failure_code(harness, swap_job.job_id) == "SUSTAINED_SWAP"

    tmp_job = harness.queue.submit(_spec(JobType.RUN_BACKTEST, "tmp"), "tmp")
    supervisor.run_cycle()
    # Assemble tmp handle once so the test sustained swap activity and tmp overage fail
    # with distinct codes workflow shares one value.
    tmp_handle = processes.spawned[-1][2]
    processes.statuses[tmp_handle] = ProcessStatus(
        ProcessState.RUNNING,
        private_rss_bytes=1_000,
        temporary_disk_bytes=1,
        # Complete ProcessStatus only after its running and process state inputs are visible
        # in test sustained swap activity and tmp overage fail with distinct codes.
    )

    assert supervisor.run_cycle().failed == 1
    assert _failure_code(harness, tmp_job.job_id) == "TEMPORARY_DISK_QUOTA_EXCEEDED"


@pytest.mark.integration
def test_host_swap_in_alone_is_not_attributed_to_the_running_child(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.queue.submit(_spec(JobType.RUN_BACKTEST, "host-swap-in"), "host-swap-in")
    processes = _Processes()
    policy = replace(_policy(JobLane.RUN), swap_activity_samples=2)
    supervisor = _supervisor(
        harness,
        processes,
        _Clock(),
        _Authority("controller"),
        {JobType.RUN_BACKTEST: policy},
        max_runs=1,
    )
    supervisor.run_cycle()
    handle = processes.spawned[0][2]

    for counter in (100, 200, 300, 400):
        processes.statuses[handle] = ProcessStatus(
            ProcessState.RUNNING,
            private_rss_bytes=1_000,
            host_swap_in_bytes=counter,
            host_swap_out_bytes=0,
        )
        assert supervisor.run_cycle().failed == 0


@pytest.mark.integration
def test_expired_lease_terminates_child_and_interrupts_attempt(tmp_path: Path) -> None:
    # Execute the test expired lease terminates child and interrupts attempt workflow in
    # explicit, reviewable steps.
    harness = _harness(tmp_path)
    record = harness.queue.submit(_spec(JobType.RUN_BACKTEST, "lease-expired"), "lease-expired")
    processes = _Processes()
    clock = _Clock()
    supervisor = _supervisor(
        # Pass harness explicitly so _supervisor receives a reviewable controller and run
        # backtest input in test expired lease terminates child and interrupts attempt.
        harness,
        processes,
        clock,
        _Authority("controller"),
        {JobType.RUN_BACKTEST: _policy(JobLane.RUN, lease_ns=90)},
        # Complete _supervisor only after its controller and run backtest inputs are visible
        # in test expired lease terminates child and interrupts attempt.
    )
    supervisor.run_cycle()
    clock.value = 91

    result = supervisor.run_cycle()

    assert result.failed == 1
    # Verify len(processes.terminated) == 1 before this scenario is accepted.
    assert len(processes.terminated) == 1
    interrupted = harness.queue.get_job(record.job_id)
    assert interrupted is not None
    assert interrupted.state is AttemptState.INTERRUPTED


@pytest.mark.integration
# Define test restart never adopts live child without receipt as one focused operation
# with an explicit boundary.
def test_restart_never_adopts_live_child_without_receipt(tmp_path: Path) -> None:
    # Execute the test restart never adopts live child without receipt workflow in
    # explicit, reviewable steps.
    harness = _harness(tmp_path)
    record = harness.queue.submit(_spec(JobType.RUN_BACKTEST, "orphan"), "orphan")
    processes = _Processes()
    clock = _Clock()
    policy = _policy(
        # Pass job lane explicitly so _policy receives a reviewable run and orphaned input
        # in test restart never adopts live child without receipt.
        JobLane.RUN,
        retryable=frozenset({AttemptFailureKind.ORPHANED}),
        max_attempts=2,
    )
    old_authority = _Authority("old-controller")
    # Assemble old once so the test restart never adopts live child without receipt
    # workflow shares one value.
    old = _supervisor(
        harness,
        processes,
        clock,
        old_authority,
        # Open the run backtest and harness payload explicitly for _supervisor within test
        # restart never adopts live child without receipt.
        {JobType.RUN_BACKTEST: policy},
    )
    old.run_cycle()
    old_attempt = harness.queue.list_unfinished_attempts()[0].attempt
    old_authority.locked = False
    # Assemble restarted once so the test restart never adopts live child without receipt
    # workflow shares one value.
    restarted = _supervisor(
        harness,
        processes,
        clock,
        _Authority("new-controller"),
        # Open the new-controller and run backtest payload explicitly for _supervisor
        # within test restart never adopts live child without receipt.
        {JobType.RUN_BACKTEST: policy},
    )

    recovery = restarted.reconcile_startup()

    assert recovery.failed == 1
    assert len(processes.terminated) == 1
    # Assemble queued once so the test restart never adopts live child without receipt
    # workflow shares one value.
    queued = harness.queue.get_job(record.job_id)
    assert queued is not None
    assert queued.state is AttemptState.QUEUED

    restarted.run_cycle()
    new_attempt = harness.queue.list_unfinished_attempts()[0].attempt
    # Verify the attempt id, new attempt and old attempt relationship before this scenario
    # is accepted.
    assert new_attempt.attempt_id != old_attempt.attempt_id
    assert new_attempt.spec == old_attempt.spec

    _publish_completion(harness, old_attempt)
    with pytest.raises(JobStateConflictError):
        harness.completer.execute(CompleteJobAttemptRequest(old_attempt))


# Apply integration semantics to the following test restart recovers verified receipt then
# terminates leftover child contract.
@pytest.mark.integration
def test_restart_recovers_verified_receipt_then_terminates_leftover_child(
    tmp_path: Path,
) -> None:
    # Execute the test restart recovers verified receipt then terminates leftover child
    # workflow in explicit, reviewable steps.
    harness = _harness(tmp_path)
    record = harness.queue.submit(_spec(JobType.RUN_BACKTEST, "recover"), "recover")
    processes = _Processes()
    clock = _Clock()
    policy = _policy(JobLane.RUN)
    # Assemble old authority once so the test restart recovers verified receipt then
    # terminates leftover child workflow shares one value.
    old_authority = _Authority("old-controller")
    old = _supervisor(
        harness,
        processes,
        clock,
        # Pass old authority explicitly so _supervisor receives a reviewable run backtest
        # and harness input in test restart recovers verified receipt then terminates
        # leftover child.
        old_authority,
        {JobType.RUN_BACKTEST: policy},
    )
    old.run_cycle()
    running = harness.queue.list_unfinished_attempts()[0].attempt
    # Invoke _publish_completion for harness and running as a visible test restart
    # recovers verified receipt then terminates leftover child step.
    _publish_completion(harness, running)
    old_authority.locked = False
    restarted = _supervisor(
        harness,
        processes,
        # Pass clock explicitly so _supervisor receives a reviewable new-controller and
        # run backtest input in test restart recovers verified receipt then terminates
        # leftover child.
        clock,
        _Authority("new-controller"),
        {JobType.RUN_BACKTEST: policy},
    )

    recovery = restarted.reconcile_startup()

    # Verify recovery.completed == 1 before this scenario is accepted.
    assert recovery.completed == 1
    assert len(processes.terminated) == 1
    succeeded = harness.queue.get_job(record.job_id)
    assert succeeded is not None
    assert succeeded.state is AttemptState.SUCCEEDED


# Define test supervisor refuses to run without controller lock as one focused operation
# with an explicit boundary.
def test_supervisor_refuses_to_run_without_controller_lock(tmp_path: Path) -> None:
    # Execute the test supervisor refuses to run without controller lock workflow in
    # explicit, reviewable steps.
    harness = _harness(tmp_path)
    supervisor = _supervisor(
        harness,
        _Processes(),
        _Clock(),
        # Keep the controller _Authority step visible while building supervisor.
        _Authority("controller", locked=False),
        {JobType.RUN_BACKTEST: _policy(JobLane.RUN)},
    )

    with pytest.raises(ControllerAuthorityLostError):
        supervisor.run_cycle()


# Apply integration semantics to the following test spawn failure is bounded and leaves no
# running attempt contract.
@pytest.mark.integration
def test_spawn_failure_is_bounded_and_leaves_no_running_attempt(tmp_path: Path) -> None:
    # Execute the test spawn failure is bounded and leaves no running attempt workflow in
    # explicit, reviewable steps.
    harness = _harness(tmp_path)
    record = harness.queue.submit(_spec(JobType.RUN_BACKTEST, "spawn"), "spawn")
    processes = _Processes()
    processes.fail_next_spawn = True
    supervisor = _supervisor(
        # Pass harness explicitly so _supervisor receives a reviewable controller and run
        # backtest input in test spawn failure is bounded and leaves no running attempt.
        harness,
        processes,
        _Clock(),
        _Authority("controller"),
        {JobType.RUN_BACKTEST: _policy(JobLane.RUN)},
        # Complete _supervisor only after its controller and run backtest inputs are visible
        # in test spawn failure is bounded and leaves no running attempt.
    )

    result = supervisor.run_cycle()

    assert result.failed == 1
    stored = harness.queue.get_job(record.job_id)
    assert stored is not None
    # Verify stored.state is AttemptState.FAILED before this scenario is accepted.
    assert stored.state is AttemptState.FAILED
    assert harness.queue.list_unfinished_attempts() == ()
