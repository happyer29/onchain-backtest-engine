"""Typed operational contracts for the single-host job supervisor.

These values are intentionally outside semantic job identity.  They describe
how one resolved job attempt may consume this host, not what result the job
must produce.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from backtest.application.models import JobAttempt, ProcessHandle


class JobLane(StrEnum):
    """Independent admission lanes with separate concurrency ceilings."""

    BUILD = "BUILD"
    RUN = "RUN"


class AttemptFailureKind(StrEnum):
    """Finite failure families used by the bounded retry policy."""

    TRANSIENT = "TRANSIENT"
    RESOURCE_EXHAUSTED = "RESOURCE_EXHAUSTED"
    USER_ERROR = "USER_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    TIMEOUT = "TIMEOUT"
    # Declare orphaned explicitly in the attempt failure kind contract.
    ORPHANED = "ORPHANED"
    COMPLETION_INVALID = "COMPLETION_INVALID"


class AttemptFailureCode(StrEnum):
    """Safe persisted reason codes; raw exception/process text is excluded."""

    SPAWN_FAILED = "SPAWN_FAILED"
    REGISTRATION_FAILED = "REGISTRATION_FAILED"
    CHILD_EXITED = "CHILD_EXITED"
    CHILD_SIGNALED = "CHILD_SIGNALED"
    TIMEOUT = "TIMEOUT"
    # Declare orphaned on restart explicitly in the attempt failure code contract.
    ORPHANED_ON_RESTART = "ORPHANED_ON_RESTART"
    COMPLETION_MISSING = "COMPLETION_MISSING"
    COMPLETION_INVALID = "COMPLETION_INVALID"
    ADMISSION_LOST = "ADMISSION_LOST"
    DISK_EMERGENCY = "DISK_EMERGENCY"
    # Declare memory limit exceeded explicitly in the attempt failure code contract.
    MEMORY_LIMIT_EXCEEDED = "MEMORY_LIMIT_EXCEEDED"
    RESOURCE_OBSERVATION_UNAVAILABLE = "RESOURCE_OBSERVATION_UNAVAILABLE"
    SUSTAINED_SWAP = "SUSTAINED_SWAP"
    TEMPORARY_DISK_QUOTA_EXCEEDED = "TEMPORARY_DISK_QUOTA_EXCEEDED"


# Keep the attempt failure contract and validation rules together.
@dataclass(frozen=True, slots=True)
class AttemptFailure:
    kind: AttemptFailureKind
    code: AttemptFailureCode


@dataclass(frozen=True, slots=True)
# Keep the retry policy contract and validation rules together.
class RetryPolicy:
    """Bounded retry policy where ``max_attempts`` includes the first try."""

    max_attempts: int = 1
    retryable_kinds: frozenset[AttemptFailureKind] = frozenset()
    base_backoff_ns: int = 0
    max_backoff_ns: int = 0

    def __post_init__(self) -> None:
        # Execute the retry policy post init workflow in explicit, reviewable steps.
        if isinstance(self.max_attempts, bool) or self.max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if self.base_backoff_ns < 0 or self.max_backoff_ns < 0:
            raise ValueError("retry backoff must be non-negative")
        if self.base_backoff_ns > self.max_backoff_ns:
            # Fail the retry policy post init path with ValueError for base backoff ns
            # cannot exceed max backoff ns when base backoff ns and max backoff ns is
            # true; do not continue ambiguously.
            raise ValueError("base_backoff_ns cannot exceed max_backoff_ns")
        if self.max_attempts == 1 and self.retryable_kinds:
            raise ValueError("a single-attempt policy cannot declare retryable failures")

    def retry_not_before_ns(
        self,
        # Close the retry not before ns signature after its explicit inputs.
        *,
        attempt_number: int,
        failure: AttemptFailure,
        now_ns: int,
    ) -> int | None:
        # Execute the retry policy retry not before ns workflow in explicit, reviewable
        # steps.
        if attempt_number <= 0:
            raise ValueError("attempt_number must be positive")
        if now_ns < 0:
            raise ValueError("now_ns must be non-negative")
        if attempt_number >= self.max_attempts or failure.kind not in self.retryable_kinds:
            # Return explicit absence from the retry policy retry not before ns path.
            return None
        exponent = min(attempt_number - 1, 62)
        delay = min(self.base_backoff_ns * (1 << exponent), self.max_backoff_ns)
        return now_ns + delay


# Keep the job resource demand contract and validation rules together.
@dataclass(frozen=True, slots=True)
class JobResourceDemand:
    private_memory_bytes: int
    native_threads: int = 1
    io_units: int = 1
    # Declare temporary disk bytes explicitly in the job resource demand contract.
    temporary_disk_bytes: int = 0
    output_disk_bytes: int = 0

    def __post_init__(self) -> None:
        # Execute the job resource demand post init workflow in explicit, reviewable
        # steps.
        positive = (self.private_memory_bytes, self.native_threads, self.io_units)
        disk = (self.temporary_disk_bytes, self.output_disk_bytes)
        if any(isinstance(value, bool) or value <= 0 for value in positive):
            raise ValueError("job resource demand values must be positive")
        if any(isinstance(value, bool) or value < 0 for value in disk):
            # Fail the job resource demand post init path with ValueError for job disk
            # demand values must be non-negative when value, disk and isinstance is true;
            # do not continue ambiguously.
            raise ValueError("job disk demand values must be non-negative")

    @property
    def reserved_disk_bytes(self) -> int:
        """Worst-case additional bytes reserved until this attempt finishes."""

        return self.temporary_disk_bytes + self.output_disk_bytes


@dataclass(frozen=True, slots=True)
class HostResourceBudget:
    """Measured aggregate budget available to isolated child processes."""

    private_memory_bytes: int
    physical_cores: int
    io_units: int
    max_children: int
    max_builders: int
    # Declare max runs explicitly in the host resource budget contract.
    max_runs: int

    def __post_init__(self) -> None:
        # Execute the host resource budget post init workflow in explicit, reviewable
        # steps.
        if isinstance(self.private_memory_bytes, bool) or self.private_memory_bytes < 0:
            raise ValueError("aggregate private-memory budget must be non-negative")
        positive = (self.physical_cores, self.io_units, self.max_children)
        if any(isinstance(value, bool) or value <= 0 for value in positive):
            raise ValueError("non-memory aggregate host budget values must be positive")
        # Assemble lanes once so the host resource budget post init workflow shares one
        # value.
        lanes = (self.max_builders, self.max_runs)
        if any(isinstance(value, bool) or value < 0 for value in lanes):
            raise ValueError("lane limits must be non-negative")
        if self.max_builders > 1:
            raise ValueError("the single-host policy admits at most one builder")
        # Guard this path with self.max_builders + self.max_runs <= 0 before applying
        # effects.
        if self.max_builders + self.max_runs <= 0:
            raise ValueError("at least one lane must admit work")


@dataclass(frozen=True, slots=True)
class JobExecutionPolicy:
    """Operational execution policy selected explicitly for a job type."""

    lane: JobLane
    demand: JobResourceDemand
    timeout_ns: int
    termination_grace_seconds: float
    lease_duration_ns: int
    # Declare retry explicitly in the job execution policy contract.
    retry: RetryPolicy = RetryPolicy()
    memory_breach_samples: int = 2
    swap_activity_samples: int = 3
    require_resource_observation: bool = False

    def __post_init__(self) -> None:
        # Execute the job execution policy post init workflow in explicit, reviewable
        # steps.
        if self.timeout_ns <= 0 or self.lease_duration_ns <= 0:
            raise ValueError("timeout and lease duration must be positive")
        if self.termination_grace_seconds < 0:
            raise ValueError("termination grace must be non-negative")
        if (
            # Keep isinstance visible while evaluating the isinstance, memory breach
            # samples and swap activity samples guard.
            isinstance(self.memory_breach_samples, bool)
            or self.memory_breach_samples <= 0
            or isinstance(self.swap_activity_samples, bool)
            or self.swap_activity_samples <= 0
        ):
            # Fail the job execution policy post init path with ValueError for runtime
            # resource guard sample counts must be positive when isinstance, memory breach
            # samples and swap activity samples is true; do not continue ambiguously.
            raise ValueError("runtime resource guard sample counts must be positive")
        if not isinstance(self.require_resource_observation, bool):
            raise ValueError("require_resource_observation must be boolean")


# Keep the admission snapshot contract and validation rules together.
@dataclass(frozen=True, slots=True)
class AdmissionSnapshot:
    reserved_private_memory_bytes: int
    reserved_native_threads: int
    reserved_io_units: int
    # Declare active children explicitly in the admission snapshot contract.
    active_children: int
    active_builders: int
    active_runs: int
    reserved_temporary_disk_bytes: int = 0
    reserved_output_disk_bytes: int = 0


# Keep the claimed attempt contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ClaimedAttempt:
    attempt: JobAttempt
    attempt_number: int

    def __post_init__(self) -> None:
        # Execute the claimed attempt post init workflow in explicit, reviewable steps.
        if self.attempt_number <= 0:
            raise ValueError("attempt_number must be positive")


@dataclass(frozen=True, slots=True)
class SupervisorAttempt:
    """Durable restart record for a STARTING or RUNNING attempt."""

    attempt: JobAttempt
    attempt_number: int
    supervisor_instance_id: str
    handle: ProcessHandle | None
    lane: JobLane | None
    # Declare demand explicitly in the supervisor attempt contract.
    demand: JobResourceDemand | None
    heartbeat_at_ns: int | None
    lease_expires_at_ns: int | None
    deadline_at_ns: int | None

    def __post_init__(self) -> None:
        # Execute the supervisor attempt post init workflow in explicit, reviewable steps.
        if self.attempt_number <= 0:
            raise ValueError("attempt_number must be positive")
        runtime_values = (
            self.handle,
            self.lane,
            # Keep the self component named inside the runtime values contract.
            self.demand,
            self.heartbeat_at_ns,
            self.lease_expires_at_ns,
            self.deadline_at_ns,
        )
        # Evaluate the complete supervisor attempt post init value and runtime values
        # condition before guarded effects.
        if any(value is None for value in runtime_values) and not all(
            value is None for value in runtime_values
        ):
            raise ValueError("runtime process metadata must be wholly present or absent")


# Keep the attempt finish contract and validation rules together.
@dataclass(frozen=True, slots=True)
class AttemptFinish:
    attempt: JobAttempt
    retry_scheduled: bool
    retry_not_before_ns: int | None

    # Define attempt finish post init as one focused operation with an explicit boundary.
    def __post_init__(self) -> None:
        # Execute the attempt finish post init workflow in explicit, reviewable steps.
        if self.retry_scheduled != (self.retry_not_before_ns is not None):
            raise ValueError("retry schedule flag and timestamp disagree")


# Keep the supervisor cycle result contract and validation rules together.
@dataclass(frozen=True, slots=True)
class SupervisorCycleResult:
    started: int = 0
    completed: int = 0
    failed: int = 0
    # Declare cancelled explicitly in the supervisor cycle result contract.
    cancelled: int = 0
    heartbeats: int = 0


__all__ = [
    "AdmissionSnapshot",
    "AttemptFailure",
    # Keep the attempt failure code component named inside the all contract.
    "AttemptFailureCode",
    "AttemptFailureKind",
    "AttemptFinish",
    "ClaimedAttempt",
    "HostResourceBudget",
    # Keep the job execution policy component named inside the all contract.
    "JobExecutionPolicy",
    "JobLane",
    "JobResourceDemand",
    "RetryPolicy",
    "SupervisorAttempt",
    # Keep the supervisor cycle result component named inside the all contract.
    "SupervisorCycleResult",
]
