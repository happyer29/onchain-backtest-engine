# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from backtest.application.errors import IdempotencyConflictError

# Import job commands at the visible module dependency boundary.
from backtest.application.job_commands import (
    ResolvedBacktestJob,
    ResolvedSweepJob,
    resolved_backtest_job_from_bytes,
    resolved_sweep_job_from_bytes,
    # Close the job commands import after its required symbols are visible.
)
from backtest.application.ml_contracts import ExactInferencePolicy
from backtest.application.models import AttemptState, JobRecord, JobType, ResolvedJobSpec
from backtest.application.run_results import RunBackend, RunPhysicalSettings
from backtest.application.run_specs import (
    # Include asset balance so the run specs dependency remains explicit.
    AssetBalance,
    ReplayInputFormat,
    ResolvedComponent,
    ResolvedReplayInput,
    ResolvedRunSpec,
    # Close the run specs import after its required symbols are visible.
)
from backtest.application.sweeps import (
    ResolvedSweepSpec,
    SweepEntry,
    resolved_sweep_spec_bytes,
    # Close the sweeps import after its required symbols are visible.
)
from backtest.application.use_cases.submit_job import SubmitJob, SubmitJobRequest
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
    # Close the chain import after its required symbols are visible.
)
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import (
    AssetId,
    BundleId,
    # Include content digest so the identifiers dependency remains explicit.
    ContentDigest,
    DatasetRevisionId,
    JobId,
    LogicalContentHash,
    RuntimeLockId,
    # Include snapshot id so the identifiers dependency remains explicit.
    SnapshotId,
)
from backtest.interfaces.cli import create_cli


# Keep the memory queue contract and validation rules together.
class _MemoryQueue:
    def __init__(self) -> None:
        self.records: dict[tuple[JobType, str], JobRecord] = {}

    def submit(self, spec: ResolvedJobSpec, idempotency_key: str) -> JobRecord:
        # Execute the memory queue submit workflow in explicit, reviewable steps.
        key = (spec.job_type, idempotency_key)
        existing = self.records.get(key)
        if existing is not None:
            # Handle the memory queue submit existing is not None branch as a distinct
            # logical block.
            if existing.spec != spec:
                raise IdempotencyConflictError(spec.job_type, idempotency_key)
            return existing
        record = JobRecord(JobId(f"job_{len(self.records) + 1}"), spec, AttemptState.QUEUED, 0)
        self.records[key] = record
        # Return the completed memory queue submit result without a hidden fallback.
        return record


# Keep the enqueue backend contract and validation rules together.
class _EnqueueBackend:
    def __init__(self) -> None:
        # Execute the enqueue backend init workflow in explicit, reviewable steps.
        self.queue = _MemoryQueue()
        self.submitter = SubmitJob(self.queue)
        self.requests: list[SubmitJobRequest] = []

    def submit_job(self, request: SubmitJobRequest) -> JobRecord:
        # Execute the enqueue backend submit job workflow in explicit, reviewable steps.
        self.requests.append(request)
        return self.submitter.execute(request)

    def default_run_physical_settings(self) -> RunPhysicalSettings:
        return RunPhysicalSettings(RunBackend.REFERENCE_PYTHON, 65_536, 1, 8_192, 2)


# Keep the factory contract and validation rules together.
class _Factory:
    def __init__(self, backend: _EnqueueBackend) -> None:
        self.backend = backend

    def __call__(
        self,
        # Keep the config path input explicit in the call contract.
        config_path: Path,
        capabilities_file: Path | None,
        *,
        require_capabilities: bool = False,
        prefer_running_controller: bool = False,
        # Keep the enqueue backend input explicit in the call contract.
    ) -> _EnqueueBackend:
        # Execute the factory call workflow in explicit, reviewable steps.
        del config_path, capabilities_file, require_capabilities, prefer_running_controller
        return self.backend


def _resolved_spec() -> ResolvedRunSpec:
    # Execute the resolved spec workflow in explicit, reviewable steps.
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
            # in resolved spec.
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
    return ResolvedRunSpec.create(
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        # Include dataset revision id in the completed resolved spec result.
        dataset_revision_id=DatasetRevisionId("1" * 64),
        logical_content_hash=LogicalContentHash("2" * 64),
        snapshot_id=SnapshotId("3" * 64),
        replay_semantics_id=ContentDigest("4" * 64),
        replay_input=ResolvedReplayInput(ReplayInputFormat.CANONICAL_PARQUET),
        # Pass components explicitly so create receives a reviewable 1 and 2 input in
        # resolved spec.
        components=components,
        runtime_lock_id=RuntimeLockId("5" * 64),
        initial_portfolio=(AssetBalance(AssetId("SOL"), 1_000),),
        root_seed=42,
    )


# Define test run enqueue alias submits the strict canonical command as one focused
# operation with an explicit boundary.
def test_run_enqueue_alias_submits_the_strict_canonical_command(tmp_path: Path) -> None:
    # Execute the test run enqueue alias submits the strict canonical command workflow in
    # explicit, reviewable steps.
    backend = _EnqueueBackend()
    spec = _resolved_spec()
    spec_file = tmp_path / "run.json"
    spec_file.write_bytes(canonical_json_bytes(spec.document()))

    result = CliRunner().invoke(
        # Keep the create cli and factory create_cli step visible while building result.
        create_cli(_Factory(backend)),
        [
            "run",
            str(spec_file),
            "--attempt-nonce",
            # Pass a explicitly so invoke receives a reviewable run and --attempt-nonce
            # input in test run enqueue alias submits the strict canonical command.
            "a" * 64,
            "--enqueue",
            "--idempotency-key",
            "run-key",
            "--backend",
            # Pass numpy-mmap-first-swap-exact-v1 explicitly so invoke receives a
            # reviewable run and --attempt-nonce input in test run enqueue alias submits
            # the strict canonical command.
            "numpy-mmap-first-swap-exact-v1",
            "--reader-batch-rows",
            "131072",
            "--reader-readahead",
            "4",
            # Pass output-buffer-rows explicitly so invoke receives a reviewable run and
            # --attempt-nonce input in test run enqueue alias submits the strict canonical
            # command.
            "--output-buffer-rows",
            "16384",
            "--threads",
            "2",
        ],
        # Complete invoke only after its run and --attempt-nonce inputs are visible in test
        # run enqueue alias submits the strict canonical command.
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["state"] == "QUEUED"
    assert len(backend.requests) == 1
    request = backend.requests[0]
    # Verify the job type, run backtest and request relationship before this scenario is
    # accepted.
    assert request.job_type is JobType.RUN_BACKTEST
    assert request.idempotency_key == "run-key"
    command = resolved_backtest_job_from_bytes(request.payload_json)
    assert isinstance(command, ResolvedBacktestJob)
    assert command.resolved_spec == spec
    # Verify the attempt nonce, command and content digest relationship before this
    # scenario is accepted.
    assert command.attempt_nonce == ContentDigest("a" * 64)
    assert command.physical_settings == RunPhysicalSettings(
        RunBackend.NUMPY_MMAP_FIRST_SWAP_EXACT,
        131_072,
        4,
        # Pass 384 explicitly so RunPhysicalSettings receives a reviewable numpy mmap
        # first swap exact and run backend input in test run enqueue alias submits the
        # strict canonical command.
        16_384,
        2,
    )


def test_sweep_enqueue_alias_submits_the_strict_canonical_command(tmp_path: Path) -> None:
    # Execute the test sweep enqueue alias submits the strict canonical command workflow
    # in explicit, reviewable steps.
    backend = _EnqueueBackend()
    spec = ResolvedSweepSpec.create(
        (
            SweepEntry(
                _resolved_spec(),
                # Keep the content digest and b ContentDigest step visible while building
                # spec.
                ContentDigest("b" * 64),
                backend.default_run_physical_settings(),
            ),
        ),
        comparison_metrics=("fill_count",),
        # Complete create only after its b and fill count inputs are visible in test sweep
        # enqueue alias submits the strict canonical command.
    )
    spec_file = tmp_path / "sweep.json"
    spec_file.write_bytes(resolved_sweep_spec_bytes(spec))

    result = CliRunner().invoke(
        create_cli(_Factory(backend)),
        # Open the sweep and --enqueue payload explicitly for invoke within test sweep
        # enqueue alias submits the strict canonical command.
        [
            "sweep",
            str(spec_file),
            "--enqueue",
            "--idempotency-key",
            # Pass sweep-key explicitly so invoke receives a reviewable sweep and
            # --enqueue input in test sweep enqueue alias submits the strict canonical
            # command.
            "sweep-key",
            "--reader-readahead",
            "4",
        ],
    )

    # Verify result.exit_code == 0 before this scenario is accepted.
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["state"] == "QUEUED"
    request = backend.requests[0]
    assert request.job_type is JobType.RUN_SWEEP
    assert request.idempotency_key == "sweep-key"
    # Assemble command once so the test sweep enqueue alias submits the strict canonical
    # command workflow shares one value.
    command = resolved_sweep_job_from_bytes(request.payload_json)
    assert isinstance(command, ResolvedSweepJob)
    assert command.resolved_sweep_spec.entries[0].resolved_spec == spec.entries[0].resolved_spec
    assert command.resolved_sweep_spec.entries[0].physical_settings.reader_readahead == 4


def test_enqueue_requires_idempotency_key_without_running_heavy_work(tmp_path: Path) -> None:
    # Execute the test enqueue requires idempotency key without running heavy work
    # workflow in explicit, reviewable steps.
    backend = _EnqueueBackend()
    spec_file = tmp_path / "run.json"
    spec_file.write_bytes(canonical_json_bytes(_resolved_spec().document()))

    result = CliRunner().invoke(
        create_cli(_Factory(backend)),
        # Keep the spec file str step visible while building result.
        ["run-backtest", str(spec_file), "--attempt-nonce", "c" * 64, "--enqueue"],
    )

    assert result.exit_code == 2
    assert json.loads(result.stderr) == {
        "code": "IDEMPOTENCY_KEY_REQUIRED",
        # Keep the message expectation tied to loads, stderr and code in this scenario.
        "message": "Queued runs require an explicit idempotency key.",
    }
    assert backend.requests == []
