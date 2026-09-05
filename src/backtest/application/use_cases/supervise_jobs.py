"""One-controller orchestration of isolated single-host job attempts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from backtest.application.completion import (
    CompletionReceiptError,
    # Include completion receipt not found error so the completion dependency remains
    # explicit.
    CompletionReceiptNotFoundError,
)
from backtest.application.errors import JobStateConflictError
from backtest.application.models import (
    AttemptState,
    # Include job progress details so the models dependency remains explicit.
    JobProgressDetails,
    JobType,
    ProcessState,
    ProcessStatus,
    ProgressEvent,
    # Close the models import after its required symbols are visible.
)
from backtest.application.ports.processes import ProcessRunner, ProcessRunnerError
from backtest.application.ports.supervisor import (
    AdmissionController,
    ControllerAuthority,
    # Include supervisor clock so the supervisor dependency remains explicit.
    SupervisorClock,
    SupervisorQueue,
)
from backtest.application.supervisor import (
    AttemptFailure,
    # Include attempt failure code so the supervisor dependency remains explicit.
    AttemptFailureCode,
    AttemptFailureKind,
    JobExecutionPolicy,
    JobLane,
    SupervisorAttempt,
    # Include supervisor cycle result so the supervisor dependency remains explicit.
    SupervisorCycleResult,
)
from backtest.application.use_cases.complete_job_attempt import (
    CompleteJobAttempt,
    CompleteJobAttemptRequest,
    # Close the complete job attempt import after its required symbols are visible.
)
from backtest.domain.identifiers import AttemptId


class ControllerAuthorityLostError(RuntimeError):
    """The supervisor cannot mutate state without the one-controller lock."""


@dataclass(frozen=True, slots=True)
class _StartResult:
    started: int
    failed: int
    cancelled: int


# Keep the runtime resource guard contract and validation rules together.
@dataclass(slots=True)
class _RuntimeResourceGuard:
    consecutive_missing_observations: int = 0
    consecutive_memory_breaches: int = 0
    consecutive_swap_activity: int = 0
    # Declare previous child swap bytes explicitly in the runtime resource guard contract.
    previous_child_swap_bytes: int | None = None
    previous_host_swap_in_bytes: int | None = None
    previous_host_swap_out_bytes: int | None = None


# Keep the progress runtime contract and validation rules together.
@dataclass(slots=True)
class _ProgressRuntime:
    last_sequence: int = 0
    last_persisted_at_ns: int | None = None
    pending: ProgressEvent | None = None
    # Declare coalesced events explicitly in the progress runtime contract.
    coalesced_events: int = 0
    dropped_transport_frames: int = 0
    private_rss_bytes: int | None = None
    total_rss_bytes: int | None = None
    major_page_faults: int | None = None
    # Declare temporary disk bytes explicitly in the progress runtime contract.
    temporary_disk_bytes: int | None = None


class SingleHostSupervisor:
    """Non-blocking supervisor cycle; the composition root owns loop timing.

    Restart never adopts a child launched by a previous controller instance.
    A valid receipt may recover exact success; otherwise the exact process
    group is terminated and the attempt becomes interrupted before retry.
    """

    def __init__(
        self,
        *,
        authority: ControllerAuthority,
        queue: SupervisorQueue,
        # Keep the processes input explicit in the init contract.
        processes: ProcessRunner,
        admission: AdmissionController,
        completer: CompleteJobAttempt,
        policies: Mapping[JobType, JobExecutionPolicy],
        clock: SupervisorClock,
        # Keep the progress interval ns input explicit in the init contract.
        progress_interval_ns: int = 500_000_000,
    ) -> None:
        # Execute the single host supervisor init workflow in explicit, reviewable steps.
        if not policies:
            raise ValueError("at least one explicit job execution policy is required")
        if any(not isinstance(job_type, JobType) for job_type in policies):
            raise TypeError("execution policies must be keyed by JobType")
        if (
            # Keep isinstance visible while evaluating the isinstance and progress
            # interval ns guard.
            isinstance(progress_interval_ns, bool)
            or not isinstance(progress_interval_ns, int)
            or progress_interval_ns <= 0
        ):
            raise ValueError("progress interval must be a positive integer")
        # Assemble self authority once so the single host supervisor init workflow shares
        # one value.
        self._authority = authority
        self._queue = queue
        self._processes = processes
        self._admission = admission
        self._completer = completer
        # Assemble self policies once so the single host supervisor init workflow shares
        # one value.
        self._policies = dict(policies)
        self._clock = clock
        self._progress_interval_ns = progress_interval_ns
        self._active: dict[AttemptId, SupervisorAttempt] = {}
        self._resource_guards: dict[AttemptId, _RuntimeResourceGuard] = {}
        # Assemble self progress runtime once so the single host supervisor init workflow
        # shares one value.
        self._progress_runtime: dict[AttemptId, _ProgressRuntime] = {}
        self._reconciled = False

    def reconcile_startup(self) -> SupervisorCycleResult:
        # Execute the single host supervisor reconcile startup workflow in explicit,
        # reviewable steps.
        self._require_authority()
        if self._reconciled:
            return SupervisorCycleResult()
        now_ns = self._clock.now_ns()
        completed = 0
        # Assemble failed once so the single host supervisor reconcile startup workflow
        # shares one value.
        failed = 0
        cancelled = 0
        for record in self._queue.list_unfinished_attempts():
            # Process self._queue.list_unfinished_attempts() inside the bounded single
            # host supervisor reconcile startup loop.
            try:
                # Perform the protected single host supervisor reconcile startup operation
                # before explicit failure handling.
                self._completer.verify(CompleteJobAttemptRequest(record.attempt))
                if record.handle is not None:
                    # Handle the single host supervisor reconcile startup record.handle is
                    # not None branch as a distinct logical block.
                    self._processes.terminate(
                        record.handle,
                        self._termination_grace(record),
                    )
                succeeded = self._completer.execute(CompleteJobAttemptRequest(record.attempt))
            # Translate job state conflict error through the single host supervisor
            # reconcile startup boundary without hiding other errors.
            except JobStateConflictError:
                # Translate the JobStateConflictError failure through the single host
                # supervisor reconcile startup boundary.
                if not self._queue.is_cancel_requested(record.attempt.job_id):
                    raise
                if record.handle is not None:
                    # Handle the single host supervisor reconcile startup record.handle is
                    # not None branch as a distinct logical block.
                    self._processes.terminate(
                        record.handle,
                        self._termination_grace(record),
                    )
                self._queue.finish_cancelled(
                    # Pass record explicitly so finish_cancelled receives a reviewable
                    # attempt id and attempt input in single host supervisor reconcile
                    # startup.
                    record.attempt.attempt_id,
                    record.attempt.state_version,
                    now_ns=now_ns,
                )
                cancelled += 1
            # Translate completion receipt error through the single host supervisor
            # reconcile startup boundary without hiding other errors.
            except CompletionReceiptError:
                # Translate the CompletionReceiptError failure through the single host
                # supervisor reconcile startup boundary.
                if record.handle is not None:
                    # Handle the single host supervisor reconcile startup record.handle is
                    # not None branch as a distinct logical block.
                    self._processes.terminate(
                        record.handle,
                        self._termination_grace(record),
                    )
                finish = self._finish_record(
                    # Pass record explicitly so _finish_record receives a reviewable
                    # orphaned and orphaned on restart input in single host supervisor
                    # reconcile startup.
                    record,
                    AttemptFailure(
                        AttemptFailureKind.ORPHANED,
                        AttemptFailureCode.ORPHANED_ON_RESTART,
                    ),
                    # Pass now ns explicitly so _finish_record receives a reviewable
                    # orphaned and orphaned on restart input in single host supervisor
                    # reconcile startup.
                    now_ns=now_ns,
                )
                if finish is AttemptState.CANCELLED:
                    cancelled += 1
                else:
                    # Assemble failed once so the single host supervisor reconcile startup
                    # workflow shares one value.
                    failed += 1
            else:
                # Handle the alternative path after the protected single host supervisor
                # reconcile startup operation.
                if succeeded.state is not AttemptState.SUCCEEDED:
                    raise RuntimeError("verified completion returned a non-success state")
                completed += 1
            finally:
                self._admission.release(record.attempt.attempt_id)
            # Invoke cleanup_launch for attempt id and attempt as a visible single host
            # supervisor reconcile startup step.
            self._processes.cleanup_launch(record.attempt.attempt_id)
        self._reconciled = True
        return SupervisorCycleResult(
            completed=completed,
            failed=failed,
            # Pass cancelled explicitly so SupervisorCycleResult receives a reviewable
            # completed and failed input in single host supervisor reconcile startup.
            cancelled=cancelled,
        )

    def run_cycle(self) -> SupervisorCycleResult:
        # Execute the single host supervisor run cycle workflow in explicit, reviewable
        # steps.
        self._require_authority()
        recovery = self.reconcile_startup()
        now_ns = self._clock.now_ns()
        completed = recovery.completed
        failed = recovery.failed
        # Assemble cancelled once so the single host supervisor run cycle workflow shares
        # one value.
        cancelled = recovery.cancelled
        heartbeats = recovery.heartbeats

        for attempt_id in sorted(self._active, key=lambda item: item.value):
            # Process sorted, active and value inside the bounded single host supervisor
            # run cycle loop.
            record = self._active.get(attempt_id)
            if record is None:
                continue
            if self._queue.is_cancel_requested(record.attempt.job_id):
                # Handle the single host supervisor run cycle is cancel requested, job id
                # and queue condition as a distinct block.
                self._terminate(record)
                self._queue.finish_cancelled(
                    record.attempt.attempt_id,
                    record.attempt.state_version,
                    now_ns=now_ns,
                    # Complete finish_cancelled only after its attempt id and attempt inputs
                    # are visible in single host supervisor run cycle.
                )
                self._release(record)
                cancelled += 1
                continue
            if record.lane is not None and self._admission.emergency_stop_required(record.lane):
                # Handle the single host supervisor run cycle lane, emergency stop
                # required and record condition as a distinct block.
                self._terminate(record)
                self._finish_record(
                    record,
                    AttemptFailure(
                        AttemptFailureKind.RESOURCE_EXHAUSTED,
                        # Pass attempt failure code explicitly so AttemptFailure receives
                        # a reviewable resource exhausted and disk emergency input in
                        # single host supervisor run cycle.
                        AttemptFailureCode.DISK_EMERGENCY,
                    ),
                    now_ns=now_ns,
                )
                self._release(record)
                # Assemble failed once so the single host supervisor run cycle workflow
                # shares one value.
                failed += 1
                continue
            if record.lease_expires_at_ns is None or record.lease_expires_at_ns <= now_ns:
                # Handle the single host supervisor run cycle lease expires at ns, now ns
                # and record condition as a distinct block.
                self._terminate(record)
                self._finish_record(
                    record,
                    AttemptFailure(
                        AttemptFailureKind.ORPHANED,
                        # Pass attempt failure code explicitly so AttemptFailure receives
                        # a reviewable orphaned and orphaned on restart input in single
                        # host supervisor run cycle.
                        AttemptFailureCode.ORPHANED_ON_RESTART,
                    ),
                    now_ns=now_ns,
                )
                self._release(record)
                # Assemble failed once so the single host supervisor run cycle workflow
                # shares one value.
                failed += 1
                continue
            if record.deadline_at_ns is None or record.deadline_at_ns <= now_ns:
                # Handle the single host supervisor run cycle deadline at ns, now ns and
                # record condition as a distinct block.
                self._terminate(record)
                self._finish_record(
                    record,
                    AttemptFailure(
                        AttemptFailureKind.TIMEOUT,
                        # Pass attempt failure code explicitly so AttemptFailure receives
                        # a reviewable timeout and attempt failure kind input in single
                        # host supervisor run cycle.
                        AttemptFailureCode.TIMEOUT,
                    ),
                    now_ns=now_ns,
                )
                self._release(record)
                # Assemble failed once so the single host supervisor run cycle workflow
                # shares one value.
                failed += 1
                continue

            if record.handle is None:
                raise RuntimeError("active attempt has no process handle")
            try:
                # Assemble status once so the single host supervisor run cycle workflow
                # shares one value.
                status = self._processes.probe(record.handle)
            except ProcessRunnerError:
                # Translate the ProcessRunnerError failure through the single host
                # supervisor run cycle boundary.
                self._terminate(record)
                self._finish_record(
                    record,
                    AttemptFailure(
                        AttemptFailureKind.TRANSIENT,
                        # Pass attempt failure code explicitly so AttemptFailure receives
                        # a reviewable transient and child exited input in single host
                        # supervisor run cycle.
                        AttemptFailureCode.CHILD_EXITED,
                    ),
                    now_ns=now_ns,
                )
                self._release(record)
                # Assemble failed once so the single host supervisor run cycle workflow
                # shares one value.
                failed += 1
                continue
            self._observe_progress(
                record,
                status,
                # Pass now ns explicitly so _observe_progress receives a reviewable state
                # and exited input in single host supervisor run cycle.
                now_ns=now_ns,
                force=status.state is ProcessState.EXITED,
            )
            if status.state is ProcessState.RUNNING:
                # Handle the single host supervisor run cycle status.state is
                # ProcessState.RUNNING branch as a distinct logical block.
                policy = self._policy(record)
                resource_failure = self._runtime_resource_failure(
                    record,
                    policy,
                    status,
                    # Complete _runtime_resource_failure only after its record and policy
                    # inputs are visible in single host supervisor run cycle.
                )
                if resource_failure is not None:
                    # Handle the single host supervisor run cycle resource_failure is not
                    # None branch as a distinct logical block.
                    self._terminate(record)
                    self._finish_record(record, resource_failure, now_ns=now_ns)
                    self._release(record)
                    failed += 1
                    continue
                # Verify record.heartbeat_at_ns is not None before this scenario is
                # accepted.
                assert record.heartbeat_at_ns is not None
                heartbeat_interval = max(1, policy.lease_duration_ns // 3)
                if now_ns - record.heartbeat_at_ns >= heartbeat_interval:
                    # Handle the single host supervisor run cycle heartbeat interval, now
                    # ns and heartbeat at ns condition as a distinct block.
                    self._queue.heartbeat(
                        record.attempt.attempt_id,
                        record.attempt.state_version,
                        supervisor_instance_id=self._authority.instance_id,
                        now_ns=now_ns,
                        # Pass lease duration ns explicitly so heartbeat receives a
                        # reviewable attempt id and attempt input in single host
                        # supervisor run cycle.
                        lease_duration_ns=policy.lease_duration_ns,
                    )
                    self._active[attempt_id] = replace(
                        record,
                        heartbeat_at_ns=now_ns,
                        # Pass lease expires at ns explicitly so replace receives a
                        # reviewable lease duration ns and record input in single host
                        # supervisor run cycle.
                        lease_expires_at_ns=now_ns + policy.lease_duration_ns,
                    )
                    heartbeats += 1
                continue

            if status.exit_code == 0:
                # Handle the single host supervisor run cycle status.exit_code == 0 branch
                # as a distinct logical block.
                try:
                    self._completer.execute(CompleteJobAttemptRequest(record.attempt))
                except JobStateConflictError:
                    # Translate the JobStateConflictError failure through the single host
                    # supervisor run cycle boundary.
                    if not self._queue.is_cancel_requested(record.attempt.job_id):
                        raise
                    self._queue.finish_cancelled(
                        record.attempt.attempt_id,
                        record.attempt.state_version,
                        # Pass now ns explicitly so finish_cancelled receives a reviewable
                        # attempt id and attempt input in single host supervisor run
                        # cycle.
                        now_ns=now_ns,
                    )
                    cancelled += 1
                except CompletionReceiptNotFoundError:
                    # Translate the CompletionReceiptNotFoundError failure through the
                    # single host supervisor run cycle boundary.
                    self._finish_record(
                        record,
                        AttemptFailure(
                            AttemptFailureKind.COMPLETION_INVALID,
                            AttemptFailureCode.COMPLETION_MISSING,
                            # Complete AttemptFailure only after its completion invalid and
                            # completion missing inputs are visible in single host supervisor
                            # run cycle.
                        ),
                        now_ns=now_ns,
                    )
                    failed += 1
                except CompletionReceiptError:
                    # Translate the CompletionReceiptError failure through the single host
                    # supervisor run cycle boundary.
                    self._finish_record(
                        record,
                        AttemptFailure(
                            AttemptFailureKind.COMPLETION_INVALID,
                            AttemptFailureCode.COMPLETION_INVALID,
                            # Complete AttemptFailure only after its completion invalid and
                            # attempt failure kind inputs are visible in single host
                            # supervisor run cycle.
                        ),
                        now_ns=now_ns,
                    )
                    failed += 1
                else:
                    # Assemble completed once so the single host supervisor run cycle
                    # workflow shares one value.
                    completed += 1
            else:
                # Handle the single host supervisor run cycle complement of
                # status.exit_code == 0 explicitly.
                self._finish_record(
                    record,
                    _classify_exit(status.exit_code),
                    now_ns=now_ns,
                )
                # Assemble failed once so the single host supervisor run cycle workflow
                # shares one value.
                failed += 1
            self._release(record)

        start_result = self._start_available(now_ns)
        return SupervisorCycleResult(
            started=start_result.started,
            # Pass completed explicitly so SupervisorCycleResult receives a reviewable
            # started and failed input in single host supervisor run cycle.
            completed=completed,
            failed=failed + start_result.failed,
            cancelled=cancelled + start_result.cancelled,
            heartbeats=heartbeats,
        )

    # Define single host supervisor shutdown as one focused operation with an explicit
    # boundary.
    def shutdown(self) -> SupervisorCycleResult:
        """Stop owned children without claiming new work before releasing authority."""

        self._require_authority()
        now_ns = self._clock.now_ns()
        completed = 0
        failed = 0
        cancelled = 0
        # Traverse sorted, active and value explicitly so each single host supervisor
        # shutdown iteration remains traceable.
        for attempt_id in sorted(self._active, key=lambda item: item.value):
            # Process sorted, active and value inside the bounded single host supervisor
            # shutdown loop.
            record = self._active.get(attempt_id)
            if record is None:
                continue
            try:
                self._completer.verify(CompleteJobAttemptRequest(record.attempt))
            # Translate completion receipt error through the single host supervisor
            # shutdown boundary without hiding other errors.
            except CompletionReceiptError:
                # Translate the CompletionReceiptError failure through the single host
                # supervisor shutdown boundary.
                self._terminate(record)
                state = self._finish_record(
                    record,
                    AttemptFailure(
                        AttemptFailureKind.ORPHANED,
                        # Pass attempt failure code explicitly so AttemptFailure receives
                        # a reviewable orphaned and orphaned on restart input in single
                        # host supervisor shutdown.
                        AttemptFailureCode.ORPHANED_ON_RESTART,
                    ),
                    now_ns=now_ns,
                )
                if state is AttemptState.CANCELLED:
                    # Assemble cancelled once so the single host supervisor shutdown
                    # workflow shares one value.
                    cancelled += 1
                else:
                    failed += 1
            else:
                # Handle the alternative path after the protected single host supervisor
                # shutdown operation.
                self._terminate(record)
                try:
                    self._completer.execute(CompleteJobAttemptRequest(record.attempt))
                except JobStateConflictError:
                    # Translate the JobStateConflictError failure through the single host
                    # supervisor shutdown boundary.
                    if not self._queue.is_cancel_requested(record.attempt.job_id):
                        raise
                    self._queue.finish_cancelled(
                        record.attempt.attempt_id,
                        record.attempt.state_version,
                        # Pass now ns explicitly so finish_cancelled receives a reviewable
                        # attempt id and attempt input in single host supervisor shutdown.
                        now_ns=now_ns,
                    )
                    cancelled += 1
                else:
                    completed += 1
            # Invoke _release for record as a visible single host supervisor shutdown
            # step.
            self._release(record)
        return SupervisorCycleResult(
            completed=completed,
            failed=failed,
            cancelled=cancelled,
            # Complete SupervisorCycleResult only after its completed and failed inputs are
            # visible in single host supervisor shutdown.
        )

    def _start_available(self, now_ns: int) -> _StartResult:
        # Execute the single host supervisor start available workflow in explicit,
        # reviewable steps.
        started = 0
        failed = 0
        cancelled = 0
        while True:
            # Keep the True loop body bounded within single host supervisor start
            # available.
            made_progress = False
            for lane in (JobLane.BUILD, JobLane.RUN):
                # Process (JobLane.BUILD, JobLane.RUN) inside the bounded single host
                # supervisor start available loop.
                job_types = tuple(
                    sorted(
                        (
                            job_type
                            for job_type, policy in self._policies.items()
                            # Pass policy explicitly so sorted receives a reviewable items
                            # and policies input in single host supervisor start
                            # available.
                            if policy.lane is lane
                            and self._admission.can_reserve(policy.lane, policy.demand)
                        ),
                        key=lambda item: item.value,
                    )
                    # Complete tuple only after its value and items inputs are visible in
                    # single host supervisor start available.
                )
                if not job_types:
                    continue
                claimed = self._queue.claim_next_for_types(
                    self._authority.instance_id,
                    # Pass job types explicitly so claim_next_for_types receives a
                    # reviewable instance id and authority input in single host supervisor
                    # start available.
                    job_types,
                    now_ns=now_ns,
                )
                if claimed is None:
                    continue
                # Assemble policy once so the single host supervisor start available
                # workflow shares one value.
                policy = self._policies[claimed.attempt.spec.job_type]
                if not self._admission.try_reserve(
                    claimed.attempt.attempt_id,
                    policy.lane,
                    policy.demand,
                    # Complete try_reserve only after its attempt id and attempt inputs are
                    # visible in single host supervisor start available.
                ):
                    # Handle the single host supervisor start available try reserve,
                    # attempt id and lane condition as a distinct block.
                    retry_at = policy.retry.retry_not_before_ns(
                        attempt_number=claimed.attempt_number,
                        failure=AttemptFailure(
                            AttemptFailureKind.RESOURCE_EXHAUSTED,
                            AttemptFailureCode.ADMISSION_LOST,
                            # Complete AttemptFailure only after its resource exhausted and
                            # admission lost inputs are visible in single host supervisor
                            # start available.
                        ),
                        now_ns=now_ns,
                    )
                    finish = self._queue.finish_unsuccessful(
                        claimed.attempt.attempt_id,
                        # Pass claimed explicitly so finish_unsuccessful receives a
                        # reviewable attempt id and attempt input in single host
                        # supervisor start available.
                        claimed.attempt.state_version,
                        AttemptFailure(
                            AttemptFailureKind.RESOURCE_EXHAUSTED,
                            AttemptFailureCode.ADMISSION_LOST,
                        ),
                        # Pass retry not before ns explicitly so finish_unsuccessful
                        # receives a reviewable attempt id and attempt input in single
                        # host supervisor start available.
                        retry_not_before_ns=retry_at,
                        now_ns=now_ns,
                    )
                    if finish.attempt.state is AttemptState.CANCELLED:
                        cancelled += 1
                    # Route all remaining cases through the explicit alternative branch.
                    else:
                        failed += 1
                    made_progress = True
                    continue
                if self._queue.is_cancel_requested(claimed.attempt.job_id):
                    # Handle the single host supervisor start available is cancel
                    # requested, job id and queue condition as a distinct block.
                    self._queue.finish_cancelled(
                        claimed.attempt.attempt_id,
                        claimed.attempt.state_version,
                        now_ns=now_ns,
                    )
                    # Invoke release for attempt id and attempt as a visible single host
                    # supervisor start available step.
                    self._admission.release(claimed.attempt.attempt_id)
                    cancelled += 1
                    made_progress = True
                    continue
                try:
                    # Perform the protected single host supervisor start available
                    # operation before explicit failure handling.
                    handle = self._processes.spawn(
                        claimed.attempt,
                        native_threads=policy.demand.native_threads,
                    )
                except ProcessRunnerError:
                    # Translate the ProcessRunnerError failure through the single host
                    # supervisor start available boundary.
                    failure = AttemptFailure(
                        AttemptFailureKind.TRANSIENT,
                        AttemptFailureCode.SPAWN_FAILED,
                    )
                    retry_at = policy.retry.retry_not_before_ns(
                        # Pass attempt number explicitly so retry_not_before_ns receives a
                        # reviewable attempt number and claimed input in single host
                        # supervisor start available.
                        attempt_number=claimed.attempt_number,
                        failure=failure,
                        now_ns=now_ns,
                    )
                    finish = self._queue.finish_unsuccessful(
                        # Pass claimed explicitly so finish_unsuccessful receives a
                        # reviewable attempt id and attempt input in single host
                        # supervisor start available.
                        claimed.attempt.attempt_id,
                        claimed.attempt.state_version,
                        failure,
                        retry_not_before_ns=retry_at,
                        now_ns=now_ns,
                        # Complete finish_unsuccessful only after its attempt id and attempt
                        # inputs are visible in single host supervisor start available.
                    )
                    self._admission.release(claimed.attempt.attempt_id)
                    if finish.attempt.state is AttemptState.CANCELLED:
                        cancelled += 1
                    else:
                        # Assemble failed once so the single host supervisor start
                        # available workflow shares one value.
                        failed += 1
                    made_progress = True
                    continue
                try:
                    # Perform the protected single host supervisor start available
                    # operation before explicit failure handling.
                    running = self._queue.register_process(
                        claimed,
                        handle,
                        policy,
                        supervisor_instance_id=self._authority.instance_id,
                        # Pass now ns explicitly so register_process receives a reviewable
                        # instance id and authority input in single host supervisor start
                        # available.
                        now_ns=now_ns,
                    )
                except JobStateConflictError:
                    # Translate the JobStateConflictError failure through the single host
                    # supervisor start available boundary.
                    self._processes.terminate(handle, policy.termination_grace_seconds)
                    self._processes.cleanup_launch(claimed.attempt.attempt_id)
                    if self._queue.is_cancel_requested(claimed.attempt.job_id):
                        # Handle the single host supervisor start available is cancel
                        # requested, job id and queue condition as a distinct block.
                        self._queue.finish_cancelled(
                            claimed.attempt.attempt_id,
                            claimed.attempt.state_version,
                            now_ns=now_ns,
                        )
                        # Invoke release for attempt id and attempt as a visible single
                        # host supervisor start available step.
                        self._admission.release(claimed.attempt.attempt_id)
                        cancelled += 1
                        made_progress = True
                        continue
                    self._admission.release(claimed.attempt.attempt_id)
                    # Fail the single host supervisor start available path with typed
                    # failure; do not continue ambiguously.
                    raise
                except Exception:
                    # Translate the Exception failure through the single host supervisor
                    # start available boundary.
                    self._processes.terminate(handle, policy.termination_grace_seconds)
                    self._processes.cleanup_launch(claimed.attempt.attempt_id)
                    self._admission.release(claimed.attempt.attempt_id)
                    raise
                self._active[running.attempt.attempt_id] = running
                # Assemble resource guards, attempt id and attempt once so the single host
                # supervisor start available workflow shares one value.
                self._resource_guards[running.attempt.attempt_id] = _RuntimeResourceGuard()
                self._progress_runtime[running.attempt.attempt_id] = _ProgressRuntime()
                started += 1
                made_progress = True
            if not made_progress:
                # Return the completed single host supervisor start available result
                # without a hidden fallback.
                return _StartResult(started, failed, cancelled)

    def _finish_record(
        self,
        record: SupervisorAttempt,
        failure: AttemptFailure,
        # Close the finish record signature after its explicit inputs.
        *,
        now_ns: int,
    ) -> AttemptState:
        # Execute the single host supervisor finish record workflow in explicit,
        # reviewable steps.
        policy = self._policies.get(record.attempt.spec.job_type)
        retry_at = (
            None
            if policy is None
            else policy.retry.retry_not_before_ns(
                # Pass attempt number explicitly so retry_not_before_ns receives a
                # reviewable attempt number and record input in single host supervisor
                # finish record.
                attempt_number=record.attempt_number,
                failure=failure,
                now_ns=now_ns,
            )
        )
        # Assemble finish once so the single host supervisor finish record workflow shares
        # one value.
        finish = self._queue.finish_unsuccessful(
            record.attempt.attempt_id,
            record.attempt.state_version,
            failure,
            retry_not_before_ns=retry_at,
            # Pass now ns explicitly so finish_unsuccessful receives a reviewable attempt
            # id and attempt input in single host supervisor finish record.
            now_ns=now_ns,
        )
        return finish.attempt.state

    def _terminate(self, record: SupervisorAttempt) -> None:
        # Execute the single host supervisor terminate workflow in explicit, reviewable
        # steps.
        if record.handle is None:
            return
        self._processes.terminate(record.handle, self._termination_grace(record))

    def _termination_grace(self, record: SupervisorAttempt) -> float:
        # Execute the single host supervisor termination grace workflow in explicit,
        # reviewable steps.
        policy = self._policies.get(record.attempt.spec.job_type)
        return 0.0 if policy is None else policy.termination_grace_seconds

    def _policy(self, record: SupervisorAttempt) -> JobExecutionPolicy:
        # Execute the single host supervisor policy workflow in explicit, reviewable
        # steps.
        try:
            return self._policies[record.attempt.spec.job_type]
        except KeyError as exc:
            raise RuntimeError("active attempt has no execution policy") from exc

    def _runtime_resource_failure(
        # Keep the remaining runtime resource failure inputs visible at the single host
        # supervisor runtime resource failure boundary.
        self,
        record: SupervisorAttempt,
        policy: JobExecutionPolicy,
        status: ProcessStatus,
    ) -> AttemptFailure | None:
        # Execute the single host supervisor runtime resource failure workflow in
        # explicit, reviewable steps.
        guard = self._resource_guards.setdefault(
            record.attempt.attempt_id,
            _RuntimeResourceGuard(),
        )
        observed_private = (
            # Keep the status component named inside the observed private contract.
            status.private_rss_bytes
            if status.private_rss_bytes is not None
            else status.total_rss_bytes
        )
        swap_observed = status.child_swap_bytes is not None or any(
            # Pass counter explicitly so any receives a reviewable host swap in bytes and
            # host swap out bytes input in single host supervisor runtime resource
            # failure.
            counter is not None
            for counter in (status.host_swap_in_bytes, status.host_swap_out_bytes)
        )
        observation_missing = (
            observed_private is None or status.temporary_disk_bytes is None or not swap_observed
            # Complete the observation missing group only after its semantic components are
            # visible.
        )
        if policy.require_resource_observation and observation_missing:
            guard.consecutive_missing_observations += 1
        else:
            guard.consecutive_missing_observations = 0
        # Evaluate the complete single host supervisor runtime resource failure
        # consecutive missing observations, memory breach samples and guard condition
        # before guarded effects.
        if guard.consecutive_missing_observations >= policy.memory_breach_samples:
            # Handle the single host supervisor runtime resource failure consecutive
            # missing observations, memory breach samples and guard condition as a
            # distinct block.
            return AttemptFailure(
                AttemptFailureKind.RESOURCE_EXHAUSTED,
                AttemptFailureCode.RESOURCE_OBSERVATION_UNAVAILABLE,
            )
        if observed_private is not None and observed_private > policy.demand.private_memory_bytes:
            # Assemble guard consecutive memory breaches once so the single host
            # supervisor runtime resource failure workflow shares one value.
            guard.consecutive_memory_breaches += 1
        else:
            guard.consecutive_memory_breaches = 0
        if guard.consecutive_memory_breaches >= policy.memory_breach_samples:
            # Handle the single host supervisor runtime resource failure consecutive
            # memory breaches, memory breach samples and guard condition as a distinct
            # block.
            return AttemptFailure(
                AttemptFailureKind.RESOURCE_EXHAUSTED,
                AttemptFailureCode.MEMORY_LIMIT_EXCEEDED,
            )

        if (
            # Keep status visible while evaluating the temporary disk bytes, reserved disk
            # bytes and status guard.
            status.temporary_disk_bytes is not None
            and status.temporary_disk_bytes > policy.demand.reserved_disk_bytes
        ):
            # Handle the single host supervisor runtime resource failure temporary disk
            # bytes, reserved disk bytes and status condition as a distinct block.
            return AttemptFailure(
                AttemptFailureKind.RESOURCE_EXHAUSTED,
                AttemptFailureCode.TEMPORARY_DISK_QUOTA_EXCEEDED,
            )

        swap_activity = (
            # Keep the previous child swap bytes _counter_increased step visible while
            # building swap activity.
            _counter_increased(
                guard.previous_child_swap_bytes,
                status.child_swap_bytes,
            )
            or _counter_increased(
                guard.previous_host_swap_out_bytes,
                # Pass status explicitly so _counter_increased receives a reviewable
                # previous host swap out bytes and host swap out bytes input in single
                # host supervisor runtime resource failure.
                status.host_swap_out_bytes,
            )
        )
        # Host-wide swap-in is retained as telemetry/baseline, but it cannot be
        # attributed to a newly spawned child. On macOS it commonly represents another
        # application reading pages that were evicted before this attempt started.
        guard.previous_child_swap_bytes = status.child_swap_bytes
        guard.previous_host_swap_in_bytes = status.host_swap_in_bytes
        # Assemble guard previous host swap out bytes once so the single host supervisor
        # runtime resource failure workflow shares one value.
        guard.previous_host_swap_out_bytes = status.host_swap_out_bytes
        if swap_activity:
            guard.consecutive_swap_activity += 1
        else:
            guard.consecutive_swap_activity = 0
        # Evaluate the complete single host supervisor runtime resource failure
        # consecutive swap activity, swap activity samples and guard condition before
        # guarded effects.
        if guard.consecutive_swap_activity >= policy.swap_activity_samples:
            # Handle the single host supervisor runtime resource failure consecutive swap
            # activity, swap activity samples and guard condition as a distinct block.
            return AttemptFailure(
                AttemptFailureKind.RESOURCE_EXHAUSTED,
                AttemptFailureCode.SUSTAINED_SWAP,
            )
        return None

    # Define single host supervisor observe progress as one focused operation with an
    # explicit boundary.
    def _observe_progress(
        self,
        record: SupervisorAttempt,
        status: ProcessStatus,
        *,
        # Keep the now ns input explicit in the observe progress contract.
        now_ns: int,
        force: bool,
    ) -> None:
        # Execute the single host supervisor observe progress workflow in explicit,
        # reviewable steps.
        runtime = self._progress_runtime.setdefault(
            record.attempt.attempt_id,
            _ProgressRuntime(),
        )
        runtime.private_rss_bytes = _latest_counter(
            # Pass runtime explicitly so _latest_counter receives a reviewable private rss
            # bytes and runtime input in single host supervisor observe progress.
            runtime.private_rss_bytes,
            status.private_rss_bytes,
        )
        runtime.total_rss_bytes = _latest_counter(
            runtime.total_rss_bytes,
            # Pass status explicitly so _latest_counter receives a reviewable total rss
            # bytes and runtime input in single host supervisor observe progress.
            status.total_rss_bytes,
        )
        runtime.major_page_faults = _latest_counter(
            runtime.major_page_faults,
            status.major_page_faults,
            # Complete _latest_counter only after its major page faults and runtime inputs are
            # visible in single host supervisor observe progress.
        )
        runtime.temporary_disk_bytes = _latest_counter(
            runtime.temporary_disk_bytes,
            status.temporary_disk_bytes,
        )
        # Assemble runtime dropped transport frames once so the single host supervisor
        # observe progress workflow shares one value.
        runtime.dropped_transport_frames = _bounded_progress_count(
            runtime.dropped_transport_frames,
            status.dropped_progress_frames,
        )
        for event in status.progress_events:
            # Process status.progress_events inside the bounded single host supervisor
            # observe progress loop.
            if (
                event.attempt_id != record.attempt.attempt_id
                or event.sequence <= runtime.last_sequence
            ):
                # Handle the single host supervisor observe progress attempt id, sequence
                # and last sequence condition as a distinct block.
                runtime.dropped_transport_frames = _bounded_progress_count(
                    runtime.dropped_transport_frames,
                    1,
                )
                continue
            # Assemble runtime last sequence once so the single host supervisor observe
            # progress workflow shares one value.
            runtime.last_sequence = event.sequence
            runtime.pending = event
            runtime.coalesced_events = _bounded_progress_count(
                runtime.coalesced_events,
                1,
                # Complete _bounded_progress_count only after its coalesced events and runtime
                # inputs are visible in single host supervisor observe progress.
            )

        pending = runtime.pending
        if pending is None:
            return
        due = (
            # Keep the runtime component named inside the due contract.
            runtime.last_persisted_at_ns is None
            or now_ns - runtime.last_persisted_at_ns >= self._progress_interval_ns
        )
        if not due and not force:
            return
        # Invoke record_progress for attempt id and attempt as a visible single host
        # supervisor observe progress step.
        self._queue.record_progress(
            record.attempt.attempt_id,
            record.attempt.state_version,
            JobProgressDetails(
                sequence=pending.sequence,
                # Pass level explicitly so JobProgressDetails receives a reviewable
                # sequence and level input in single host supervisor observe progress.
                level=pending.level,
                stage=pending.stage,
                completed_units=pending.completed_units,
                total_units=pending.total_units,
                coalesced_events=runtime.coalesced_events,
                # Pass dropped transport frames explicitly so JobProgressDetails receives
                # a reviewable sequence and level input in single host supervisor observe
                # progress.
                dropped_transport_frames=runtime.dropped_transport_frames,
                private_rss_bytes=runtime.private_rss_bytes,
                total_rss_bytes=runtime.total_rss_bytes,
                major_page_faults=runtime.major_page_faults,
                temporary_disk_bytes=runtime.temporary_disk_bytes,
                # Complete JobProgressDetails only after its sequence and level inputs are
                # visible in single host supervisor observe progress.
            ),
            supervisor_instance_id=self._authority.instance_id,
            now_ns=now_ns,
        )
        runtime.last_persisted_at_ns = now_ns
        # Assemble runtime pending once so the single host supervisor observe progress
        # workflow shares one value.
        runtime.pending = None
        runtime.coalesced_events = 0
        runtime.dropped_transport_frames = 0

    def _release(self, record: SupervisorAttempt) -> None:
        # Execute the single host supervisor release workflow in explicit, reviewable
        # steps.
        self._active.pop(record.attempt.attempt_id, None)
        self._resource_guards.pop(record.attempt.attempt_id, None)
        self._progress_runtime.pop(record.attempt.attempt_id, None)
        self._admission.release(record.attempt.attempt_id)
        self._processes.cleanup_launch(record.attempt.attempt_id)

    # Define single host supervisor require authority as one focused operation with an
    # explicit boundary.
    def _require_authority(self) -> None:
        # Execute the single host supervisor require authority workflow in explicit,
        # reviewable steps.
        if not self._authority.locked or not self._authority.instance_id:
            # Handle the single host supervisor require authority locked, instance id and
            # authority condition as a distinct block.
            raise ControllerAuthorityLostError(
                "single-host supervisor requires the held controller lock"
            )


def _classify_exit(exit_code: int | None) -> AttemptFailure:
    # Execute the classify exit workflow in explicit, reviewable steps.
    if exit_code == 75:
        # Handle the classify exit exit_code == 75 branch as a distinct logical block.
        return AttemptFailure(
            AttemptFailureKind.TRANSIENT,
            AttemptFailureCode.CHILD_EXITED,
        )
    if exit_code in (137, -9):
        # Handle the classify exit exit_code in (137, -9) branch as a distinct logical
        # block.
        return AttemptFailure(
            AttemptFailureKind.RESOURCE_EXHAUSTED,
            AttemptFailureCode.CHILD_SIGNALED,
        )
    if exit_code == 78:
        # Handle the classify exit exit_code == 78 branch as a distinct logical block.
        return AttemptFailure(
            AttemptFailureKind.USER_ERROR,
            AttemptFailureCode.CHILD_EXITED,
        )
    if exit_code is not None and exit_code < 0:
        # Handle the classify exit exit code condition as a distinct block.
        return AttemptFailure(
            AttemptFailureKind.INTERNAL_ERROR,
            AttemptFailureCode.CHILD_SIGNALED,
        )
    return AttemptFailure(
        # Pass attempt failure kind explicitly so AttemptFailure receives a reviewable
        # internal error and child exited input in classify exit.
        AttemptFailureKind.INTERNAL_ERROR,
        AttemptFailureCode.CHILD_EXITED,
    )


def _counter_increased(previous: int | None, current: int | None) -> bool:
    return previous is not None and current is not None and current > previous


# Define latest counter as one focused operation with an explicit boundary.
def _latest_counter(previous: int | None, current: int | None) -> int | None:
    return previous if current is None else current


def _bounded_progress_count(current: int, increment: int) -> int:
    return min(2**31 - 1, current + increment)


__all__ = ["ControllerAuthorityLostError", "SingleHostSupervisor"]
