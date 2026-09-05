# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import sys
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
from backtest.adapters.process.local import LocalSubprocessRunner
from backtest.application.job_commands import ResolvedCompileReplayJob
from backtest.application.models import AttemptState, JobType
from backtest.application.supervisor import (
    # Include host resource budget so the supervisor dependency remains explicit.
    HostResourceBudget,
    JobExecutionPolicy,
    JobLane,
    JobResourceDemand,
)

# Import complete job attempt at the visible module dependency boundary.
from backtest.application.use_cases.complete_job_attempt import CompleteJobAttempt
from backtest.application.use_cases.submit_job import SubmitJob, SubmitJobRequest
from backtest.application.use_cases.supervise_jobs import SingleHostSupervisor
from backtest.bootstrap.direct_execution import DirectJobExecutionError, DirectJobExecutor
from backtest.domain.identifiers import SnapshotId

# Import local admission at the visible module dependency boundary.
from backtest.runtime.local_admission import LocalAdmissionController
from backtest.runtime.system_clock import SystemClock


# Keep the authority contract and validation rules together.
@dataclass(frozen=True, slots=True)
class _Authority:
    instance_id: str = "direct-crash-test"
    locked: bool = True


@pytest.mark.integration
# Define test direct child crash finishes failed without receipt or result as one focused
# operation with an explicit boundary.
def test_direct_child_crash_finishes_failed_without_receipt_or_result(tmp_path: Path) -> None:
    # Execute the test direct child crash finishes failed without receipt or result
    # workflow in explicit, reviewable steps.
    data_root = tmp_path / "var"
    database = data_root / "catalog" / "catalog.sqlite"
    artifacts = LocalArtifactRepository(data_root)
    queue = SQLiteJobQueue(database)
    catalog = SQLiteArtifactCatalog(database, artifacts)
    # Assemble receipts once so the test direct child crash finishes failed without
    # receipt or result workflow shares one value.
    receipts = LocalCompletionReceiptStore(DataRootLayout(data_root))
    completer = CompleteJobAttempt(queue, catalog, receipts, artifacts)
    processes = LocalSubprocessRunner(
        (sys.executable, "-c", "raise SystemExit(70)"),
        working_directory=Path.cwd(),
        # Pass envelope directory explicitly so LocalSubprocessRunner receives a
        # reviewable -c and raise system exit(70) input in test direct child crash
        # finishes failed without receipt or result.
        envelope_directory=data_root / "tmp" / "job-launch",
    )
    policy = JobExecutionPolicy(
        lane=JobLane.BUILD,
        demand=JobResourceDemand(
            # Pass private memory bytes explicitly into JobResourceDemand within test
            # direct child crash finishes failed without receipt or result.
            private_memory_bytes=64 * 1024**2,
            native_threads=1,
            io_units=1,
        ),
        timeout_ns=10_000_000_000,
        # Pass termination grace seconds explicitly so JobExecutionPolicy receives a
        # reviewable build and job resource demand input in test direct child crash
        # finishes failed without receipt or result.
        termination_grace_seconds=0.1,
        lease_duration_ns=1_000_000_000,
    )
    supervisor = SingleHostSupervisor(
        authority=_Authority(),
        # Pass queue explicitly so SingleHostSupervisor receives a reviewable compile
        # replay and authority input in test direct child crash finishes failed without
        # receipt or result.
        queue=queue,
        processes=processes,
        admission=LocalAdmissionController(
            HostResourceBudget(
                private_memory_bytes=128 * 1024**2,
                # Pass physical cores explicitly into HostResourceBudget within test
                # direct child crash finishes failed without receipt or result.
                physical_cores=1,
                io_units=1,
                max_children=1,
                max_builders=1,
                max_runs=0,
                # Complete HostResourceBudget only after its declared inputs are visible in
                # test direct child crash finishes failed without receipt or result.
            )
        ),
        completer=completer,
        policies={JobType.COMPILE_REPLAY: policy},
        clock=SystemClock(),
        # Complete SingleHostSupervisor only after its compile replay and authority inputs are
        # visible in test direct child crash finishes failed without receipt or result.
    )
    command = ResolvedCompileReplayJob(SnapshotId("a" * 64))
    executor = DirectJobExecutor(
        submitter=SubmitJob(queue),
        queue=queue,
        # Pass supervisor explicitly so DirectJobExecutor receives a reviewable submit job
        # and queue input in test direct child crash finishes failed without receipt or
        # result.
        supervisor=supervisor,
        verifier=completer,
        artifacts=artifacts,
        poll_interval_seconds=0.01,
        maximum_wait_seconds=5,
        # Complete DirectJobExecutor only after its submit job and queue inputs are visible in
        # test direct child crash finishes failed without receipt or result.
    )

    with pytest.raises(DirectJobExecutionError) as caught:
        # Keep raises, direct job execution error and pytest active only for the bounded
        # test direct child crash finishes failed without receipt or result operation.
        executor.execute(
            SubmitJobRequest(
                spec_version=1,
                job_type=JobType.COMPILE_REPLAY,
                payload_json=command.canonical_bytes(),
                # Pass idempotency key explicitly so SubmitJobRequest receives a
                # reviewable direct-child-crash and compile replay input in test direct
                # child crash finishes failed without receipt or result.
                idempotency_key="direct-child-crash",
            )
        )

    assert caught.value.code == "DIRECT_JOB_FAILED"
    jobs = queue.list_jobs(limit=10)
    # Verify len(jobs) == 1 before this scenario is accepted.
    assert len(jobs) == 1
    assert jobs[0].state is AttemptState.FAILED
    events = queue.list_job_events(jobs[0].job_id, limit=100)
    attempts = tuple(event.attempt_id for event in events if event.attempt_id is not None)
    assert attempts
    # Verify the attempt id, attempts and load relationship before this scenario is
    # accepted.
    assert all(receipts.load(attempt_id) is None for attempt_id in attempts)
    assert not tuple((data_root / "tmp" / "job-launch").glob("*.json"))
