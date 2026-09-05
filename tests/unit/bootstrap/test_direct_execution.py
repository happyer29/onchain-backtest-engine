# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path

import pytest

# Import localfs at the visible module dependency boundary.
from backtest.adapters.artifacts.localfs import (
    DataRootLayout,
    LocalArtifactRepository,
    LocalCompletionReceiptStore,
)

# Import sqlite at the visible module dependency boundary.
from backtest.adapters.catalog.sqlite import SQLiteArtifactCatalog, SQLiteJobQueue
from backtest.application.job_commands import ResolvedCompileReplayJob
from backtest.application.models import (
    AttemptState,
    JobAttempt,
    # Include job type so the models dependency remains explicit.
    JobType,
    ProcessHandle,
    ProcessStatus,
)
from backtest.application.supervisor import (
    # Include host resource budget so the supervisor dependency remains explicit.
    HostResourceBudget,
    JobExecutionPolicy,
    JobLane,
    JobResourceDemand,
    SupervisorCycleResult,
    # Close the supervisor import after its required symbols are visible.
)
from backtest.application.use_cases.complete_job_attempt import CompleteJobAttempt
from backtest.application.use_cases.submit_job import SubmitJob, SubmitJobRequest
from backtest.application.use_cases.supervise_jobs import SingleHostSupervisor
from backtest.bootstrap.direct_execution import DirectJobExecutionError, DirectJobExecutor

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import AttemptId, SnapshotId
from backtest.runtime.local_admission import LocalAdmissionController
from backtest.runtime.system_clock import SystemClock


def test_direct_job_execution_error_is_spawn_transport_safe() -> None:
    # Execute the test direct job execution error is spawn transport safe workflow in
    # explicit, reviewable steps.
    expected = DirectJobExecutionError(
        "DIRECT_JOB_ADMISSION_REJECTED",
        "The direct job does not fit the configured resource budget.",
    )

    actual = pickle.loads(pickle.dumps(expected))

    # Verify the direct job execution error, type and actual relationship before this
    # scenario is accepted.
    assert type(actual) is DirectJobExecutionError
    assert actual.code == expected.code
    assert actual.safe_message == expected.safe_message
    assert str(actual) == str(expected)


# Keep the authority contract and validation rules together.
@dataclass(frozen=True, slots=True)
class _Authority:
    instance_id: str = "direct-unit"
    locked: bool = True


# Keep the processes must not start contract and validation rules together.
class _ProcessesMustNotStart:
    def spawn(self, attempt: JobAttempt, *, native_threads: int) -> ProcessHandle:
        # Execute the processes must not start spawn workflow in explicit, reviewable
        # steps.
        del attempt, native_threads
        raise AssertionError("admission-rejected work must not spawn")

    def probe(self, handle: ProcessHandle) -> ProcessStatus:
        # Execute the processes must not start probe workflow in explicit, reviewable
        # steps.
        del handle
        raise AssertionError("there is no process to probe")

    def terminate(self, handle: ProcessHandle, grace_seconds: float) -> None:
        # Execute the processes must not start terminate workflow in explicit, reviewable
        # steps.
        del handle, grace_seconds
        raise AssertionError("there is no process to terminate")

    def cleanup_launch(self, attempt_id: AttemptId) -> None:
        del attempt_id


# Keep the supervisor must not run contract and validation rules together.
class _SupervisorMustNotRun:
    def reconcile_startup(self) -> SupervisorCycleResult:
        raise AssertionError("invalid configuration must fail before supervision")

    def run_cycle(self) -> SupervisorCycleResult:
        raise AssertionError("invalid configuration must fail before supervision")

    # Define supervisor must not run shutdown as one focused operation with an explicit
    # boundary.
    def shutdown(self) -> SupervisorCycleResult:
        raise AssertionError("invalid configuration must fail before supervision")


def _request(key: str) -> SubmitJobRequest:
    # Execute the request workflow in explicit, reviewable steps.
    command = ResolvedCompileReplayJob(SnapshotId("a" * 64))
    return SubmitJobRequest(
        spec_version=1,
        job_type=JobType.COMPILE_REPLAY,
        payload_json=command.canonical_bytes(),
        # Pass idempotency key explicitly so SubmitJobRequest receives a reviewable
        # compile replay and canonical bytes input in request.
        idempotency_key=key,
    )


def _services(
    tmp_path: Path,
) -> tuple[
    # Keep the local artifact repository input explicit in the services contract.
    LocalArtifactRepository,
    SQLiteJobQueue,
    SQLiteArtifactCatalog,
    LocalCompletionReceiptStore,
    CompleteJobAttempt,
    # Close the services signature after its explicit inputs.
]:
    # Execute the services workflow in explicit, reviewable steps.
    data_root = tmp_path / "var"
    artifacts = LocalArtifactRepository(data_root)
    database = data_root / "catalog" / "catalog.sqlite"
    queue = SQLiteJobQueue(database)
    catalog = SQLiteArtifactCatalog(database, artifacts)
    # Assemble receipts once so the services workflow shares one value.
    receipts = LocalCompletionReceiptStore(DataRootLayout(data_root))
    return (
        artifacts,
        queue,
        catalog,
        # Include receipts in the completed services result.
        receipts,
        CompleteJobAttempt(
            queue,
            catalog,
            receipts,
            # Pass artifacts explicitly so CompleteJobAttempt receives a reviewable queue
            # and catalog input in services.
            artifacts,
        ),
    )


def test_direct_execution_fails_fast_when_job_does_not_fit_admission(
    tmp_path: Path,
    # Close the test direct execution fails fast when job does not fit admission signature
    # after its explicit inputs.
) -> None:
    # Execute the test direct execution fails fast when job does not fit admission
    # workflow in explicit, reviewable steps.
    artifacts, queue, _, _, completer = _services(tmp_path)
    policy = JobExecutionPolicy(
        lane=JobLane.BUILD,
        demand=JobResourceDemand(private_memory_bytes=2, native_threads=1, io_units=1),
        timeout_ns=1_000_000,
        # Pass termination grace seconds explicitly so JobExecutionPolicy receives a
        # reviewable build and job resource demand input in test direct execution fails
        # fast when job does not fit admission.
        termination_grace_seconds=0,
        lease_duration_ns=1_000,
    )
    supervisor = SingleHostSupervisor(
        authority=_Authority(),
        # Pass queue explicitly so SingleHostSupervisor receives a reviewable compile
        # replay and authority input in test direct execution fails fast when job does not
        # fit admission.
        queue=queue,
        processes=_ProcessesMustNotStart(),
        admission=LocalAdmissionController(
            HostResourceBudget(
                private_memory_bytes=1,
                # Pass physical cores explicitly into HostResourceBudget within test
                # direct execution fails fast when job does not fit admission.
                physical_cores=1,
                io_units=1,
                max_children=1,
                max_builders=1,
                max_runs=0,
                # Complete HostResourceBudget only after its declared inputs are visible in
                # test direct execution fails fast when job does not fit admission.
            )
        ),
        completer=completer,
        policies={JobType.COMPILE_REPLAY: policy},
        clock=SystemClock(),
        # Complete SingleHostSupervisor only after its compile replay and authority inputs are
        # visible in test direct execution fails fast when job does not fit admission.
    )
    executor = DirectJobExecutor(
        submitter=SubmitJob(queue),
        queue=queue,
        supervisor=supervisor,
        # Pass verifier explicitly so DirectJobExecutor receives a reviewable submit job
        # and queue input in test direct execution fails fast when job does not fit
        # admission.
        verifier=completer,
        artifacts=artifacts,
        poll_interval_seconds=0.01,
        maximum_wait_seconds=1,
    )

    # Acquire raises, direct job execution error and pytest at an explicit test direct
    # execution fails fast when job does not fit admission context boundary so cleanup
    # remains scoped.
    with pytest.raises(DirectJobExecutionError) as caught:
        executor.execute(_request("admission-rejected"))

    assert caught.value.code == "DIRECT_JOB_ADMISSION_REJECTED"
    assert queue.list_jobs(limit=10)[0].state is AttemptState.CANCELLED


def test_direct_execution_refuses_to_drain_preexisting_queue(tmp_path: Path) -> None:
    # Execute the test direct execution refuses to drain preexisting queue workflow in
    # explicit, reviewable steps.
    artifacts, queue, _, _, completer = _services(tmp_path)
    submitter = SubmitJob(queue)
    existing = submitter.execute(_request("existing"))
    policy = JobExecutionPolicy(
        lane=JobLane.BUILD,
        # Keep the job resource demand JobResourceDemand step visible while building
        # policy.
        demand=JobResourceDemand(private_memory_bytes=1, native_threads=1, io_units=1),
        timeout_ns=1_000_000,
        termination_grace_seconds=0,
        lease_duration_ns=1_000,
    )
    # Assemble supervisor once so the test direct execution refuses to drain preexisting
    # queue workflow shares one value.
    supervisor = SingleHostSupervisor(
        authority=_Authority(),
        queue=queue,
        processes=_ProcessesMustNotStart(),
        admission=LocalAdmissionController(
            # Keep the host resource budget HostResourceBudget step visible while building
            # supervisor.
            HostResourceBudget(
                private_memory_bytes=1,
                physical_cores=1,
                io_units=1,
                max_children=1,
                # Pass max builders explicitly into HostResourceBudget within test direct
                # execution refuses to drain preexisting queue.
                max_builders=1,
                max_runs=0,
            )
        ),
        completer=completer,
        # Pass policies explicitly so SingleHostSupervisor receives a reviewable compile
        # replay and authority input in test direct execution refuses to drain preexisting
        # queue.
        policies={JobType.COMPILE_REPLAY: policy},
        clock=SystemClock(),
    )
    executor = DirectJobExecutor(
        submitter=submitter,
        # Pass queue explicitly so DirectJobExecutor receives a reviewable submitter and
        # queue input in test direct execution refuses to drain preexisting queue.
        queue=queue,
        supervisor=supervisor,
        verifier=completer,
        artifacts=artifacts,
        poll_interval_seconds=0.01,
        # Pass maximum wait seconds explicitly so DirectJobExecutor receives a reviewable
        # submitter and queue input in test direct execution refuses to drain preexisting
        # queue.
        maximum_wait_seconds=1,
    )

    with pytest.raises(DirectJobExecutionError) as caught:
        executor.execute(_request("new-direct"))

    assert caught.value.code == "DIRECT_QUEUE_NOT_IDLE"
    # Assemble jobs once so the test direct execution refuses to drain preexisting queue
    # workflow shares one value.
    jobs = queue.list_jobs(limit=10)
    assert jobs == (existing,)
    assert jobs[0].state is AttemptState.QUEUED


def test_direct_executor_rejects_invalid_timing_configuration(tmp_path: Path) -> None:
    # Execute the test direct executor rejects invalid timing configuration workflow in
    # explicit, reviewable steps.
    artifacts, queue, _, _, completer = _services(tmp_path)
    with pytest.raises(ValueError, match="polling interval"):
        # Keep raises, value error and pytest active only for the bounded test direct
        # executor rejects invalid timing configuration operation.
        DirectJobExecutor(
            submitter=SubmitJob(queue),
            queue=queue,
            supervisor=_SupervisorMustNotRun(),
            verifier=completer,
            # Pass artifacts explicitly so DirectJobExecutor receives a reviewable submit
            # job and supervisor must not run input in test direct executor rejects
            # invalid timing configuration.
            artifacts=artifacts,
            poll_interval_seconds=0,
        )
