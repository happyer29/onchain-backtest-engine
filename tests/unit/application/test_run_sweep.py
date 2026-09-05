# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import json
import os

import pytest

from backtest.adapters.process.parallel import SpawnProcessIndependentRunExecutor

# Import ml contracts at the visible module dependency boundary.
from backtest.application.ml_contracts import ExactInferencePolicy
from backtest.application.models import ArtifactKind, CommittedArtifact
from backtest.application.run_results import (
    RunBackend,
    RunComparisonMetric,
    # Include run comparison projection so the run results dependency remains explicit.
    RunComparisonProjection,
    RunPhysicalSettings,
)
from backtest.application.run_specs import (
    AssetBalance,
    # Include replay contract so the run specs dependency remains explicit.
    ReplayContract,
    ReplayInputFormat,
    ResolvedComponent,
    ResolvedReplayInput,
    ResolvedRunSpec,
    # Close the run specs import after its required symbols are visible.
)
from backtest.application.sweeps import (
    ResolvedSweepSpec,
    SweepEntry,
    SweepEntryResult,
    # Include resolved sweep spec bytes so the sweeps dependency remains explicit.
    resolved_sweep_spec_bytes,
    resolved_sweep_spec_from_bytes,
    sweep_result_digest,
)
from backtest.application.use_cases.run_backtest import (
    # Include run backtest request so the run backtest dependency remains explicit.
    RunBacktestRequest,
    RunBacktestResult,
)
from backtest.application.use_cases.run_sweep import RunSweep, SweepExecutionError
from backtest.domain.chain import (
    # Include block32 transaction32 position schema id so the chain dependency remains
    # explicit.
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
)
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.domain.identifiers import (
    # Include artifact id so the identifiers dependency remains explicit.
    ArtifactId,
    AssetId,
    BundleId,
    ContentDigest,
    DatasetRevisionId,
    # Include logical content hash so the identifiers dependency remains explicit.
    LogicalContentHash,
    RuntimeLockId,
    SnapshotId,
)


def _spec(seed: int) -> ResolvedRunSpec:
    # Execute the spec workflow in explicit, reviewable steps.
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
            # Pass role explicitly so create receives a reviewable bundle and role input
            # in spec.
            role=role,
            bundle_id=BundleId(domain_digest("test.sweep.bundle", {"role": role}).hex),
            config=(
                ExactInferencePolicy.disabled().document()
                if role == "inference"
                # Route all remaining cases through the explicit alternative branch.
                else {"mode": "SHADOW_STATE_REPLAY"}
                if role == "execution"
                else {"version": 1}
            ),
        )
        # Pass role explicitly so tuple receives a reviewable inference and bundle input
        # in spec.
        for role in roles
    )
    return ResolvedRunSpec.create(
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        # Include dataset revision id in the completed spec result.
        dataset_revision_id=DatasetRevisionId("1" * 64),
        logical_content_hash=LogicalContentHash("2" * 64),
        snapshot_id=SnapshotId("3" * 64),
        replay_semantics_id=ContentDigest("4" * 64),
        replay_input=ResolvedReplayInput(ReplayInputFormat.CANONICAL_PARQUET),
        # Pass components explicitly so create receives a reviewable 1 and 2 input in
        # spec.
        components=components,
        runtime_lock_id=RuntimeLockId("5" * 64),
        initial_portfolio=(AssetBalance(AssetId("SOL"), 1_000),),
        root_seed=seed,
    )


# Define physical as one focused operation with an explicit boundary.
def _physical(readahead: int = 1) -> RunPhysicalSettings:
    # Execute the physical workflow in explicit, reviewable steps.
    return RunPhysicalSettings(
        RunBackend.REFERENCE_PYTHON,
        65_536,
        readahead,
        8_192,
        # Keep run physical settings, reference python and readahead visible while
        # completing RunPhysicalSettings within physical.
        1,
    )


def _result(request: RunBacktestRequest) -> RunBacktestResult:
    # Execute the result workflow in explicit, reviewable steps.
    attempt = request.resolved_spec.execution_attempt_id(
        request.attempt_nonce,
        request.physical_settings.identity_digest,
    )
    digest = domain_digest("test.sweep.result", {"seed": request.resolved_spec.root_seed})
    # Assemble comparison once so the result workflow shares one value.
    comparison = RunComparisonProjection(
        canonical_result_hash=digest,
        audit_hash=domain_digest("test.sweep.audit", {"seed": request.resolved_spec.root_seed}),
        ledger_hash=domain_digest("test.sweep.ledger", {"seed": request.resolved_spec.root_seed}),
        fill_hash=domain_digest("test.sweep.fills", {"seed": request.resolved_spec.root_seed}),
        # Pass historical group count explicitly so RunComparisonProjection receives a
        # reviewable audit and seed input in result.
        historical_group_count=request.resolved_spec.root_seed,
        historical_event_count=request.resolved_spec.root_seed + 1,
        delivered_event_count=request.resolved_spec.root_seed + 2,
        accepted_order_count=1,
        rejected_order_count=0,
        # Pass filled order count explicitly so RunComparisonProjection receives a
        # reviewable audit and seed input in result.
        filled_order_count=1,
        failed_order_count=0,
        ledger_transaction_count=1,
        fill_count=1,
        final_balances_count=1,
        # Keep the final-balances domain_digest step visible while building comparison.
        final_balances_digest=domain_digest(
            "test.sweep.final-balances",
            {"seed": request.resolved_spec.root_seed},
        ),
    )
    # Assemble artifact id once so the result workflow shares one value.
    artifact_id = ArtifactId(domain_digest("test.sweep.artifact", {"attempt": attempt.hex}).hex)
    return RunBacktestResult(
        request.resolved_spec.logical_run_id,
        attempt,
        digest,
        # Include committed artifact in the completed result result.
        CommittedArtifact(
            artifact_id=artifact_id,
            kind=ArtifactKind.RUN,
            manifest_digest=digest,
            build_key=domain_digest("test.sweep.build", {"attempt": attempt.hex}),
            # Pass input artifact ids explicitly so CommittedArtifact receives a
            # reviewable build and attempt input in result.
            input_artifact_ids=(),
        ),
        comparison,
        request.physical_settings,
        ReplayContract.CANONICAL_EXACT,
        # Open the build and attempt payload explicitly for RunBacktestResult within
        # result.
        (),
    )


def _isolated_process_result(request: RunBacktestRequest) -> RunBacktestResult:
    # Execute the isolated process result workflow in explicit, reviewable steps.
    result = _result(request)
    process_digest = domain_digest("test.sweep.worker-process", {"pid": os.getpid()})
    return RunBacktestResult(
        result.logical_run_id,
        result.execution_attempt_id,
        # Pass result explicitly so RunBacktestResult receives a reviewable logical run id
        # and execution attempt id input in isolated process result.
        result.canonical_result_hash,
        CommittedArtifact(
            artifact_id=result.artifact.artifact_id,
            kind=result.artifact.kind,
            manifest_digest=result.artifact.manifest_digest,
            # Pass build key explicitly so CommittedArtifact receives a reviewable
            # artifact id and artifact input in isolated process result.
            build_key=process_digest,
            input_artifact_ids=result.artifact.input_artifact_ids,
        ),
        result.comparison,
        result.physical_settings,
        # Pass result explicitly so RunBacktestResult receives a reviewable logical run id
        # and execution attempt id input in isolated process result.
        result.canonicality,
        result.warnings,
    )


# Keep the reverse executor contract and validation rules together.
class _ReverseExecutor:
    def execute_all(
        self,
        requests: tuple[RunBacktestRequest, ...],
    ) -> tuple[RunBacktestResult, ...]:
        # Return the completed reverse executor execute all result without a hidden
        # fallback.
        return tuple(_result(request) for request in reversed(requests))


# Keep the output store contract and validation rules together.
class _OutputStore:
    def publish(
        self,
        spec: ResolvedSweepSpec,
        entries: tuple[SweepEntryResult, ...],
        # Keep the committed artifact input explicit in the publish contract.
    ) -> CommittedArtifact:
        # Execute the output store publish workflow in explicit, reviewable steps.
        digest = sweep_result_digest(spec.sweep_spec_id, spec.comparison_metrics, entries)
        return CommittedArtifact(
            artifact_id=ArtifactId(
                domain_digest("test.sweep.aggregate", {"result": digest.hex}).hex
            ),
            # Pass kind explicitly so CommittedArtifact receives a reviewable aggregate
            # and result input in output store publish.
            kind=ArtifactKind.SWEEP,
            manifest_digest=digest,
            build_key=spec.sweep_spec_id,
            input_artifact_ids=tuple(
                sorted(
                    # Open the artifact id and run artifact payload explicitly for sorted
                    # within output store publish.
                    (item.run_artifact.artifact_id for item in entries),
                    key=lambda item: item.hex,
                )
            ),
        )


# Define sweep as one focused operation with an explicit boundary.
def _sweep() -> ResolvedSweepSpec:
    # Execute the sweep workflow in explicit, reviewable steps.
    return ResolvedSweepSpec.create(
        (
            SweepEntry(_spec(1), domain_digest("test.nonce", {"n": 1}), _physical(1)),
            SweepEntry(_spec(2), domain_digest("test.nonce", {"n": 2}), _physical(2)),
        ),
        # Pass comparison metrics explicitly so create receives a reviewable nonce and n
        # input in sweep.
        comparison_metrics=(
            RunComparisonMetric.FINAL_BALANCES_DIGEST,
            RunComparisonMetric.FILL_COUNT,
        ),
    )


# Define test sweep result is independent of executor completion order as one focused
# operation with an explicit boundary.
def test_sweep_result_is_independent_of_executor_completion_order() -> None:
    # Execute the test sweep result is independent of executor completion order workflow
    # in explicit, reviewable steps.
    sweep = _sweep()
    reverse = RunSweep(_ReverseExecutor(), _OutputStore()).execute(sweep)

    # Keep the forward executor contract and validation rules together.
    class _ForwardExecutor:
        def execute_all(
            self,
            requests: tuple[RunBacktestRequest, ...],
        ) -> tuple[RunBacktestResult, ...]:
            # Return the completed forward executor execute all result without a hidden
            # fallback.
            return tuple(_result(request) for request in requests)

    forward = RunSweep(_ForwardExecutor(), _OutputStore()).execute(sweep)
    assert reverse == forward
    assert reverse.result_digest == forward.result_digest
    assert tuple(item.entry_id.hex for item in reverse.entries) == tuple(
        # Keep the sorted expectation tied to hex, sorted and entry id in this scenario.
        sorted(item.entry_id.hex for item in reverse.entries)
    )


def test_resolved_sweep_v2_round_trip_pins_per_entry_physical_settings() -> None:
    # Execute the test resolved sweep v2 round trip pins per entry physical settings
    # workflow in explicit, reviewable steps.
    sweep = _sweep()
    payload = resolved_sweep_spec_bytes(sweep)

    assert resolved_sweep_spec_from_bytes(payload) == sweep
    assert json.loads(payload)["spec_version"] == 2
    assert sorted(item.physical_settings.reader_readahead for item in sweep.entries) == [1, 2]

    # Assemble original once so the test resolved sweep v2 round trip pins per entry
    # physical settings workflow shares one value.
    original = next(item for item in sweep.entries if item.resolved_spec.root_seed == 1)
    changed = ResolvedSweepSpec.create(
        (
            SweepEntry(
                original.resolved_spec,
                # Pass original explicitly so SweepEntry receives a reviewable resolved
                # spec and attempt nonce input in test resolved sweep v2 round trip pins
                # per entry physical settings.
                original.attempt_nonce,
                _physical(4),
            ),
            next(item for item in sweep.entries if item.resolved_spec.root_seed == 2),
        ),
        # Pass comparison metrics explicitly so create receives a reviewable resolved spec
        # and attempt nonce input in test resolved sweep v2 round trip pins per entry
        # physical settings.
        comparison_metrics=sweep.comparison_metrics,
    )
    changed_entry = next(item for item in changed.entries if item.resolved_spec.root_seed == 1)
    assert changed_entry.resolved_spec.logical_run_id == original.resolved_spec.logical_run_id
    assert changed.sweep_spec_id != sweep.sweep_spec_id

    # Assemble invalid once so the test resolved sweep v2 round trip pins per entry
    # physical settings workflow shares one value.
    invalid = json.loads(payload)
    invalid["entries"][0]["physical_settings"]["reader_readahead"] = 3
    with pytest.raises(ValueError, match="1, 2 or 4"):
        resolved_sweep_spec_from_bytes(canonical_json_bytes(invalid))


def test_spawn_executor_isolates_every_independent_entry_in_its_own_process() -> None:
    # Execute the test spawn executor isolates every independent entry in its own process
    # workflow in explicit, reviewable steps.
    sweep = _sweep()
    requests = tuple(
        RunBacktestRequest(
            entry.resolved_spec,
            entry.attempt_nonce,
            # Pass entry explicitly so RunBacktestRequest receives a reviewable resolved
            # spec and attempt nonce input in test spawn executor isolates every
            # independent entry in its own process.
            entry.physical_settings,
        )
        for entry in sweep.entries
    )

    results = SpawnProcessIndependentRunExecutor(
        # Pass isolated process result explicitly so execute_all receives a reviewable
        # requests input in test spawn executor isolates every independent entry in its
        # own process.
        _isolated_process_result,
        max_workers=2,
    ).execute_all(requests)

    assert {item.execution_attempt_id for item in results} == {
        request.resolved_spec.execution_attempt_id(
            # Pass request explicitly so execution_attempt_id receives a reviewable
            # attempt nonce and identity digest input in test spawn executor isolates
            # every independent entry in its own process.
            request.attempt_nonce,
            request.physical_settings.identity_digest,
        )
        for request in requests
    }
    # Verify the requests, build key and artifact relationship before this scenario is
    # accepted.
    assert len({item.artifact.build_key for item in results}) == len(requests)


def test_sweep_rejects_duplicate_or_missing_executor_results() -> None:
    # Execute the test sweep rejects duplicate or missing executor results workflow in
    # explicit, reviewable steps.
    sweep = _sweep()

    # Keep the duplicate contract and validation rules together.
    class _Duplicate:
        def execute_all(
            self,
            requests: tuple[RunBacktestRequest, ...],
        ) -> tuple[RunBacktestResult, ...]:
            # Execute the duplicate execute all workflow in explicit, reviewable steps.
            result = _result(requests[0])
            return result, result

    with pytest.raises(SweepExecutionError, match="duplicate"):
        RunSweep(_Duplicate(), _OutputStore()).execute(sweep)

    # Keep the missing contract and validation rules together.
    class _Missing:
        def execute_all(
            self,
            requests: tuple[RunBacktestRequest, ...],
        ) -> tuple[RunBacktestResult, ...]:
            # Return the completed missing execute all result without a hidden fallback.
            return (_result(requests[0]),)

    with pytest.raises(SweepExecutionError, match="wrong result count"):
        RunSweep(_Missing(), _OutputStore()).execute(sweep)


def test_sweep_spec_rejects_duplicate_entries() -> None:
    # Execute the test sweep spec rejects duplicate entries workflow in explicit,
    # reviewable steps.
    entry = SweepEntry(_spec(1), domain_digest("test.nonce", {"n": 1}), _physical())
    with pytest.raises(ValueError, match="unique"):
        ResolvedSweepSpec.create((entry, entry))


def test_sweep_spec_rejects_unknown_comparison_metric() -> None:
    # Execute the test sweep spec rejects unknown comparison metric workflow in explicit,
    # reviewable steps.
    entry = SweepEntry(_spec(1), domain_digest("test.nonce", {"n": 1}), _physical())
    with pytest.raises(ValueError, match="unsupported run comparison metric"):
        ResolvedSweepSpec.create((entry,), comparison_metrics=("pnl",))


def test_sweep_retry_namespace_changes_only_physical_attempts() -> None:
    # Execute the test sweep retry namespace changes only physical attempts workflow in
    # explicit, reviewable steps.
    sweep = _sweep()
    use_case = RunSweep(_ReverseExecutor(), _OutputStore())

    first = use_case.execute(sweep, attempt_namespace=ContentDigest("a" * 64))
    second = use_case.execute(sweep, attempt_namespace=ContentDigest("b" * 64))

    assert tuple(item.logical_run_id for item in first.entries) == tuple(
        # Pass item explicitly so tuple receives a reviewable logical run id and entries
        # input in test sweep retry namespace changes only physical attempts.
        item.logical_run_id
        for item in second.entries
    )
    assert tuple(item.execution_attempt_id for item in first.entries) != tuple(
        item.execution_attempt_id
        # Pass item explicitly so tuple receives a reviewable execution attempt id and
        # entries input in test sweep retry namespace changes only physical attempts.
        for item in second.entries
        # Complete tuple only after its execution attempt id and entries inputs are visible in
        # test sweep retry namespace changes only physical attempts.
    )
