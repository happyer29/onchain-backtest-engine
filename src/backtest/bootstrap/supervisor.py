"""Trusted single-host supervisor composition and explicit resource policy."""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys

# Import pathlib at the visible module dependency boundary.
from pathlib import Path
from typing import Final

from backtest.adapters.artifacts.localfs import DataRootLayout, LocalCompletionReceiptStore
from backtest.adapters.catalog.sqlite import (
    SQLiteCanonicalOutputObserver,
    # Include sqlite shard ledger so the sqlite dependency remains explicit.
    SQLiteShardLedger,
)
from backtest.adapters.process.local import LocalSubprocessRunner
from backtest.application.models import JobType
from backtest.application.supervisor import (
    # Include attempt failure kind so the supervisor dependency remains explicit.
    AttemptFailureKind,
    HostResourceBudget,
    JobExecutionPolicy,
    JobLane,
    JobResourceDemand,
    # Include retry policy so the supervisor dependency remains explicit.
    RetryPolicy,
)
from backtest.application.use_cases.complete_job_attempt import CompleteJobAttempt
from backtest.application.use_cases.supervise_jobs import SingleHostSupervisor
from backtest.bootstrap.container import RuntimeContainer

# Import controller lock at the visible module dependency boundary.
from backtest.runtime.controller_lock import ControllerLock
from backtest.runtime.host_resources import (
    HostMemoryReserves,
    derive_host_memory_budget,
    directory_tree_bytes,
    # Include measure host memory so the host resources dependency remains explicit.
    measure_host_memory,
)
from backtest.runtime.local_admission import LocalAdmissionController
from backtest.runtime.system_clock import SystemClock

_MIB: Final = 1024**2
# Bind gib once as an explicit module-level contract.
_GIB: Final = 1024**3
_SECOND_NS: Final = 1_000_000_000


def build_single_host_supervisor(
    container: RuntimeContainer,
    *,
    # Keep the authority input explicit in the build single host supervisor contract.
    authority: ControllerLock,
    config_path: Path,
    capabilities_file: Path | None,
    working_directory: Path,
) -> SingleHostSupervisor:
    """Bind the held controller authority to one child runner and queue."""

    settings = container.settings
    resources = settings.resources
    data_root = container.artifacts.data_root
    config = config_path.resolve(strict=True)
    command: tuple[str, ...] = (
        # Keep the sys component named inside the command contract.
        sys.executable,
        "-m",
        "backtest.bootstrap.job_child",
        "--config",
        str(config),
        # Complete the command group only after its semantic components are visible.
    )
    if capabilities_file is not None:
        command = (*command, "--capabilities", str(capabilities_file.resolve(strict=True)))
    processes = LocalSubprocessRunner(
        command,
        # Pass working directory explicitly so LocalSubprocessRunner receives a reviewable
        # job-launch and tmp input in build single host supervisor.
        working_directory=working_directory,
        envelope_directory=data_root / "tmp" / "job-launch",
        source_secret_refs=(settings.source.secret_ref,),
        temporary_roots=(data_root / "tmp", data_root / "staging"),
    )
    # Assemble memory once so the build single host supervisor workflow shares one value.
    memory = derive_host_memory_budget(
        measure_host_memory(),
        HostMemoryReserves(
            configured_child_ceiling_bytes=(resources.max_aggregate_child_memory_mb * _MIB),
            safety_reserve_bytes=resources.memory_safety_reserve_mb * _MIB,
            # Pass page cache floor bytes explicitly so HostMemoryReserves receives a
            # reviewable max aggregate child memory mb and memory safety reserve mb input
            # in build single host supervisor.
            page_cache_floor_bytes=resources.page_cache_floor_mb * _MIB,
            host_staging_output_reserve_bytes=(resources.host_staging_output_reserve_mb * _MIB),
            fixed_shared_overhead_bytes=resources.fixed_shared_overhead_mb * _MIB,
        ),
    )
    # Assemble aggregate memory once so the build single host supervisor workflow shares
    # one value.
    aggregate_memory = memory.available_child_private_bytes
    maximum_runs = resources.max_parallel_runs
    physical_cores = _physical_core_count()
    io_units = max(1, maximum_runs)
    admission = LocalAdmissionController(
        # Keep the host resource budget and aggregate memory HostResourceBudget step
        # visible while building admission.
        HostResourceBudget(
            private_memory_bytes=aggregate_memory,
            physical_cores=physical_cores,
            io_units=io_units,
            max_children=max(1, maximum_runs),
            # Pass max builders explicitly so HostResourceBudget receives a reviewable max
            # and aggregate memory input in build single host supervisor.
            max_builders=1,
            max_runs=maximum_runs,
        ),
        disk_free_bytes=lambda: shutil.disk_usage(data_root).free,
        temporary_used_bytes=lambda: directory_tree_bytes(
            # Open the tmp and staging payload explicitly for directory_tree_bytes within
            # build single host supervisor.
            (data_root / "tmp", data_root / "staging")
        ),
        temporary_quota_bytes=resources.tmp_quota_gb * _GIB,
        disk_low_watermark_bytes=resources.disk_low_watermark_gb * _GIB,
        disk_emergency_watermark_bytes=resources.disk_emergency_watermark_gb * _GIB,
        # Complete LocalAdmissionController only after its tmp and staging inputs are visible
        # in build single host supervisor.
    )
    receipts = LocalCompletionReceiptStore(DataRootLayout(data_root))
    shard_ledger = SQLiteShardLedger(
        data_root / "catalog" / "catalog.sqlite",
        container.catalog,
        # Complete SQLiteShardLedger only after its sqlite and catalog inputs are visible in
        # build single host supervisor.
    )
    completer = CompleteJobAttempt(
        container.jobs,
        container.catalog,
        receipts,
        # Pass container explicitly so CompleteJobAttempt receives a reviewable jobs and
        # catalog input in build single host supervisor.
        container.artifacts,
        output_observer=SQLiteCanonicalOutputObserver(
            container.artifacts,
            shard_ledger,
        ),
        # Complete CompleteJobAttempt only after its jobs and catalog inputs are visible in
        # build single host supervisor.
    )
    return SingleHostSupervisor(
        authority=authority,
        queue=container.jobs,
        processes=processes,
        # Pass admission explicitly so SingleHostSupervisor receives a reviewable jobs and
        # native threads per process input in build single host supervisor.
        admission=admission,
        completer=completer,
        policies=_execution_policies(
            builder_memory_bytes=resources.builder_peak_private_memory_mb * _MIB,
            run_memory_bytes=resources.run_peak_private_memory_mb * _MIB,
            # Pass maximum runs explicitly so _execution_policies receives a reviewable
            # builder peak private memory mb and run peak private memory mb input in build
            # single host supervisor.
            maximum_runs=maximum_runs,
            native_threads=resources.native_threads_per_process,
            io_units=io_units,
            builder_temporary_bytes=resources.tmp_quota_gb * _GIB,
            builder_output_bytes=settings.planning.max_local_gb * _GIB,
            # Pass run temporary bytes explicitly so _execution_policies receives a
            # reviewable builder peak private memory mb and run peak private memory mb
            # input in build single host supervisor.
            run_temporary_bytes=resources.max_run_tmp_gb * _GIB,
            run_output_bytes=resources.max_run_output_gb * _GIB,
            memory_breach_samples=resources.memory_breach_samples,
            swap_activity_samples=resources.swap_activity_samples,
        ),
        # Include clock in the completed build single host supervisor result.
        clock=SystemClock(),
        progress_interval_ns=settings.control.progress_interval_ms * 1_000_000,
    )


def _execution_policies(
    *,
    # Keep the builder memory bytes input explicit in the execution policies contract.
    builder_memory_bytes: int,
    run_memory_bytes: int,
    maximum_runs: int,
    native_threads: int,
    io_units: int,
    # Keep the builder temporary bytes input explicit in the execution policies contract.
    builder_temporary_bytes: int,
    builder_output_bytes: int,
    run_temporary_bytes: int,
    run_output_bytes: int,
    memory_breach_samples: int,
    # Keep the swap activity samples input explicit in the execution policies contract.
    swap_activity_samples: int,
) -> dict[JobType, JobExecutionPolicy]:
    # Execute the execution policies workflow in explicit, reviewable steps.
    retry = RetryPolicy(
        max_attempts=2,
        retryable_kinds=frozenset({AttemptFailureKind.TRANSIENT, AttemptFailureKind.ORPHANED}),
        base_backoff_ns=5 * _SECOND_NS,
        max_backoff_ns=5 * _SECOND_NS,
        # Complete RetryPolicy only after its transient and orphaned inputs are visible in
        # execution policies.
    )
    build = JobExecutionPolicy(
        lane=JobLane.BUILD,
        demand=JobResourceDemand(
            private_memory_bytes=builder_memory_bytes,
            # Pass native threads explicitly so JobResourceDemand receives a reviewable
            # builder memory bytes and native threads input in execution policies.
            native_threads=native_threads,
            io_units=io_units,
            temporary_disk_bytes=builder_temporary_bytes,
            output_disk_bytes=builder_output_bytes,
        ),
        # Pass timeout ns explicitly so JobExecutionPolicy receives a reviewable build and
        # job resource demand input in execution policies.
        timeout_ns=12 * 60 * 60 * _SECOND_NS,
        termination_grace_seconds=10.0,
        lease_duration_ns=30 * _SECOND_NS,
        retry=retry,
        memory_breach_samples=memory_breach_samples,
        # Pass swap activity samples explicitly so JobExecutionPolicy receives a
        # reviewable build and job resource demand input in execution policies.
        swap_activity_samples=swap_activity_samples,
        require_resource_observation=True,
    )
    run = JobExecutionPolicy(
        lane=JobLane.RUN,
        # Keep the job resource demand and run memory bytes JobResourceDemand step visible
        # while building run.
        demand=JobResourceDemand(
            private_memory_bytes=run_memory_bytes,
            native_threads=native_threads,
            io_units=1,
            temporary_disk_bytes=run_temporary_bytes,
            # Pass output disk bytes explicitly so JobResourceDemand receives a reviewable
            # run memory bytes and native threads input in execution policies.
            output_disk_bytes=run_output_bytes,
        ),
        timeout_ns=24 * 60 * 60 * _SECOND_NS,
        termination_grace_seconds=10.0,
        lease_duration_ns=30 * _SECOND_NS,
        # Pass retry explicitly so JobExecutionPolicy receives a reviewable run and job
        # resource demand input in execution policies.
        retry=retry,
        memory_breach_samples=memory_breach_samples,
        swap_activity_samples=swap_activity_samples,
        require_resource_observation=True,
    )
    # Assemble sweep once so the execution policies workflow shares one value.
    sweep = JobExecutionPolicy(
        lane=JobLane.RUN,
        demand=JobResourceDemand(
            private_memory_bytes=run_memory_bytes * maximum_runs,
            native_threads=native_threads * maximum_runs,
            # Pass io units explicitly so JobResourceDemand receives a reviewable run
            # memory bytes and maximum runs input in execution policies.
            io_units=maximum_runs,
            temporary_disk_bytes=run_temporary_bytes * maximum_runs,
            output_disk_bytes=run_output_bytes * maximum_runs,
        ),
        timeout_ns=24 * 60 * 60 * _SECOND_NS,
        # Pass termination grace seconds explicitly so JobExecutionPolicy receives a
        # reviewable run and job resource demand input in execution policies.
        termination_grace_seconds=10.0,
        lease_duration_ns=30 * _SECOND_NS,
        retry=retry,
        memory_breach_samples=memory_breach_samples,
        swap_activity_samples=swap_activity_samples,
        # Pass require resource observation explicitly so JobExecutionPolicy receives a
        # reviewable run and job resource demand input in execution policies.
        require_resource_observation=True,
    )
    return {
        JobType.PREPARE_DATASET: build,
        JobType.COMPILE_REPLAY: build,
        # Include job type in the completed execution policies result.
        JobType.COMPILE_DELIVERY_SCHEDULE: build,
        JobType.BUILD_FEATURES: build,
        JobType.BUILD_UNIVERSE: build,
        JobType.BUILD_LABELS: build,
        JobType.TRAIN_MODEL: build,
        # Include job type in the completed execution policies result.
        JobType.BUILD_MODEL_SCHEDULE: build,
        JobType.PREDICT: build,
        JobType.RUN_BACKTEST: run,
        JobType.RUN_SWEEP: sweep,
    }


# Define physical core count as one focused operation with an explicit boundary.
def _physical_core_count() -> int:
    """Measure physical cores conservatively; never use logical ``cpu_count`` policy."""

    system = platform.system()
    if system == "Darwin":
        # Handle the physical core count system == 'Darwin' branch as a distinct logical
        # block.
        try:
            # Perform the protected physical core count operation before explicit failure
            # handling.
            result = subprocess.run(
                ("/usr/sbin/sysctl", "-n", "hw.physicalcpu"),
                check=False,
                capture_output=True,
                text=True,
                # Pass timeout explicitly so run receives a reviewable /usr/sbin/sysctl
                # and -n input in physical core count.
                timeout=1.0,
            )
            value = int(result.stdout.strip())
        except (OSError, subprocess.SubprocessError, ValueError):
            return 1
        # Return the completed physical core count result without a hidden fallback.
        return max(1, value) if result.returncode == 0 else 1
    if system == "Linux":
        # Handle the physical core count system == 'Linux' branch as a distinct logical
        # block.
        try:
            blocks = Path("/proc/cpuinfo").read_text(encoding="ascii").split("\n\n")
        except (OSError, UnicodeDecodeError):
            return 1
        pairs: set[tuple[str, str]] = set()
        # Traverse blocks explicitly so each physical core count iteration remains
        # traceable.
        for block in blocks:
            # Process blocks inside the bounded physical core count loop.
            fields = {}
            for line in block.splitlines():
                # Process block.splitlines() inside the bounded physical core count loop.
                if ":" not in line:
                    continue
                name, core_value = line.split(":", 1)
                fields[name.strip()] = core_value.strip()
            physical = fields.get("physical id")
            # Assemble core once so the physical core count workflow shares one value.
            core = fields.get("core id")
            if physical is not None and core is not None:
                pairs.add((physical, core))
        return max(1, len(pairs))
    return 1


# Bind all once as an explicit module-level contract.
__all__ = ["build_single_host_supervisor"]
