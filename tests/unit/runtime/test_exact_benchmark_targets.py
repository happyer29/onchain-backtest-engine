# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

# Import pytest at the visible module dependency boundary.
import pytest

from backtest.adapters.artifacts.localfs.repository import (
    ArtifactIntegrityError,
    ArtifactNotCommittedError,
    LocalArtifactRepository,
    # Close the repository import after its required symbols are visible.
)
from backtest.adapters.performance import targets as targets_module
from backtest.adapters.performance.targets import (
    CONTROL_DIRECT_BENCHMARK_BUNDLE_ID,
    EMBEDDED_INFERENCE_BENCHMARK_BUNDLE_ID,
    # Include frozen inference benchmark bundle id so the targets dependency remains
    # explicit.
    FROZEN_INFERENCE_BENCHMARK_BUNDLE_ID,
    FULL_BACKTEST_BENCHMARK_BUNDLE_ID,
    LocalExactBenchmarkSpecResolver,
    LocalExactBenchmarkTargetFactory,
)

# Import benchmarks at the visible module dependency boundary.
from backtest.application.benchmarks import (
    BenchmarkExecutionPhase,
    BenchmarkLaunchRoute,
    BenchmarkWorkload,
    CacheCondition,
    # Include control plane benchmark invocation so the benchmarks dependency remains
    # explicit.
    ControlPlaneBenchmarkInvocation,
    ExactBenchmarkCommand,
)
from backtest.application.job_commands import run_input_artifact_ids
from backtest.application.ml_contracts import (
    # Include exact inference policy so the ml contracts dependency remains explicit.
    ExactInferencePolicy,
    InferenceMissingPolicy,
    InferenceMode,
)
from backtest.application.models import ArtifactDraft, ArtifactKind, CommittedArtifact

# Import run results at the visible module dependency boundary.
from backtest.application.run_results import (
    RunBackend,
    RunComparisonProjection,
    RunPhysicalSettings,
    SuccessfulRunManifest,
    # Include successful run summary so the run results dependency remains explicit.
    SuccessfulRunSummary,
)
from backtest.application.run_specs import (
    AssetBalance,
    ReplayInputFormat,
    # Include resolved component so the run specs dependency remains explicit.
    ResolvedComponent,
    ResolvedReplayInput,
    ResolvedRunSpec,
)
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
    # Include feature set id so the identifiers dependency remains explicit.
    FeatureSetId,
    LogicalContentHash,
    ModelScheduleId,
    PredictionSetId,
    ReplayPackId,
    # Include runtime lock id so the identifiers dependency remains explicit.
    RuntimeLockId,
    SnapshotId,
)
from backtest.engine.reference import RunSummary


class _LocalHandle(Protocol):
    # Define local handle local path as one focused operation with an explicit boundary.
    def local_path(self, relative_name: str) -> Path: ...


# Keep the fake parquet source contract and validation rules together.
class _FakeParquetSource:
    dataset_revision_id = DatasetRevisionId("1" * 64)
    logical_content_hash = LogicalContentHash("2" * 64)
    replay_semantics_id = ContentDigest("4" * 64)

    def __init__(self, *args: object, **kwargs: object) -> None:
        # Discard args after its boundary-only use.
        del args, kwargs

    def events(self) -> object:
        return iter((object(), object(), object()))


# Keep the run executor contract and validation rules together.
@dataclass
class _RunExecutor:
    summary: RunSummary | SuccessfulRunSummary
    calls: int = 0

    def execute_summary(
        # Keep the remaining execute summary inputs visible at the run executor execute
        # summary boundary.
        self,
        spec: ResolvedRunSpec,
        physical_settings: RunPhysicalSettings,
    ) -> RunSummary | SuccessfulRunSummary:
        # Execute the run executor execute summary workflow in explicit, reviewable steps.
        del spec, physical_settings
        self.calls += 1
        return self.summary


# Keep the control executor contract and validation rules together.
@dataclass
class _ControlExecutor:
    comparison: RunComparisonProjection
    route: BenchmarkLaunchRoute | None = None
    invocation_ids: list[ContentDigest] | None = None

    # Define control executor execute as one focused operation with an explicit boundary.
    def execute(
        self,
        run_artifact_id: ArtifactId,
        route: BenchmarkLaunchRoute,
        physical_settings: RunPhysicalSettings,
        # Keep the invocation input explicit in the execute contract.
        invocation: ControlPlaneBenchmarkInvocation,
    ) -> RunComparisonProjection:
        # Execute the control executor execute workflow in explicit, reviewable steps.
        del run_artifact_id, physical_settings
        self.route = route
        if self.invocation_ids is not None:
            self.invocation_ids.append(invocation.invocation_id)
        return self.comparison

    # Define control executor close as one focused operation with an explicit boundary.
    def close(self) -> None:
        return None


def test_full_run_target_is_exactly_resolved_and_rejects_changed_bundle(tmp_path: Path) -> None:
    # Execute the test full run target is exactly resolved and rejects changed bundle
    # workflow in explicit, reviewable steps.
    artifacts, run, manifest = _run_artifact(tmp_path, InferenceMode.DISABLED)
    resolver = _resolver(artifacts, manifest.resolved_spec.runtime_lock_id)
    command = _command(run.artifact_id, BenchmarkWorkload.FULL_BACKTEST)
    spec = resolver.resolve(command)
    executor = _RunExecutor(manifest.bounded_summary)
    # Assemble factory once so the test full run target is exactly resolved and rejects
    # changed bundle workflow shares one value.
    factory = LocalExactBenchmarkTargetFactory(resolver, run_executor=executor)

    result = factory.create(spec, artifacts.data_root).execute_once()

    assert spec.workload_bundle_id == FULL_BACKTEST_BENCHMARK_BUNDLE_ID
    assert spec.input_artifact_ids == (run.artifact_id,)
    assert result.canonical_result_hash == manifest.summary.result_hash
    # Verify the items processed, historical event count and result relationship before
    # this scenario is accepted.
    assert result.items_processed == manifest.comparison.historical_event_count
    assert executor.calls == 1
    with pytest.raises(ValueError, match="independently resolved"):
        # Keep raises, value error and pytest active only for the bounded test full run
        # target is exactly resolved and rejects changed bundle operation.
        factory.validate(
            replace(spec, workload_bundle_id=BundleId("f" * 64)),
            artifacts.data_root,
        )


def test_embedded_target_requires_embedded_seed_and_exact_summary(tmp_path: Path) -> None:
    # Execute the test embedded target requires embedded seed and exact summary workflow
    # in explicit, reviewable steps.
    artifacts, run, manifest = _run_artifact(tmp_path, InferenceMode.EMBEDDED_BATCH)
    resolver = _resolver(artifacts, manifest.resolved_spec.runtime_lock_id)
    spec = resolver.resolve(_command(run.artifact_id, BenchmarkWorkload.EMBEDDED_INFERENCE))
    changed = replace(
        manifest.bounded_summary,
        # Keep the comparison replace step visible while building changed.
        comparison=replace(
            manifest.comparison,
            canonical_result_hash=domain_digest("test.changed-run-result", {}),
        ),
    )
    # Assemble factory once so the test embedded target requires embedded seed and exact
    # summary workflow shares one value.
    factory = LocalExactBenchmarkTargetFactory(
        resolver,
        run_executor=_RunExecutor(changed),
    )

    assert spec.workload_bundle_id == EMBEDDED_INFERENCE_BENCHMARK_BUNDLE_ID
    # Acquire raises, runtime error and pytest at an explicit test embedded target
    # requires embedded seed and exact summary context boundary so cleanup remains scoped.
    with pytest.raises(RuntimeError, match="committed Run seed"):
        factory.create(spec, artifacts.data_root).execute_once()

    disabled_artifacts, disabled_run, disabled_manifest = _run_artifact(
        tmp_path / "disabled",
        InferenceMode.DISABLED,
        # Complete _run_artifact only after its disabled and tmp path inputs are visible in
        # test embedded target requires embedded seed and exact summary.
    )
    with pytest.raises(ValueError, match="embedded Run"):
        # Keep raises, value error and pytest active only for the bounded test embedded
        # target requires embedded seed and exact summary operation.
        _resolver(disabled_artifacts, disabled_manifest.resolved_spec.runtime_lock_id).resolve(
            _command(disabled_run.artifact_id, BenchmarkWorkload.EMBEDDED_INFERENCE)
        )


def test_frozen_and_embedded_resolve_to_the_same_seeded_semantic_result(
    tmp_path: Path,
    # Close the test frozen and embedded resolve to the same seeded semantic result signature
    # after its explicit inputs.
) -> None:
    # Execute the test frozen and embedded resolve to the same seeded semantic result
    # workflow in explicit, reviewable steps.
    embedded_artifacts, embedded_run, embedded_manifest = _run_artifact(
        tmp_path / "embedded",
        InferenceMode.EMBEDDED_BATCH,
    )
    frozen_artifacts, frozen_run, frozen_manifest = _run_artifact(
        # Pass tmp path explicitly so _run_artifact receives a reviewable frozen and tmp
        # path input in test frozen and embedded resolve to the same seeded semantic
        # result.
        tmp_path / "frozen",
        InferenceMode.FROZEN,
    )
    embedded = _resolver(
        embedded_artifacts,
        # Pass embedded manifest explicitly so resolve receives a reviewable artifact id
        # and embedded inference input in test frozen and embedded resolve to the same
        # seeded semantic result.
        embedded_manifest.resolved_spec.runtime_lock_id,
    ).resolve(_command(embedded_run.artifact_id, BenchmarkWorkload.EMBEDDED_INFERENCE))
    frozen_resolver = _resolver(
        frozen_artifacts,
        frozen_manifest.resolved_spec.runtime_lock_id,
        # Complete _resolver only after its runtime lock id and resolved spec inputs are
        # visible in test frozen and embedded resolve to the same seeded semantic result.
    )
    frozen = frozen_resolver.resolve(
        _command(frozen_run.artifact_id, BenchmarkWorkload.FROZEN_INFERENCE)
    )

    assert frozen.workload_bundle_id == FROZEN_INFERENCE_BENCHMARK_BUNDLE_ID
    # Verify the semantic equivalence id, frozen and embedded relationship before this
    # scenario is accepted.
    assert frozen.semantic_equivalence_id == embedded.semantic_equivalence_id
    result = (
        LocalExactBenchmarkTargetFactory(
            frozen_resolver,
            run_executor=_RunExecutor(frozen_manifest.bounded_summary),
            # Complete LocalExactBenchmarkTargetFactory only after its bounded summary and run
            # executor inputs are visible in test frozen and embedded resolve to the same
            # seeded semantic result.
        )
        .create(frozen, frozen_artifacts.data_root)
        .execute_once()
    )
    assert result.canonical_result_hash == frozen_manifest.summary.result_hash


# Define test parquet scan dispatch returns verified logical stream hash as one focused
# operation with an explicit boundary.
def test_parquet_scan_dispatch_returns_verified_logical_stream_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test parquet scan dispatch returns verified logical stream hash workflow
    # in explicit, reviewable steps.
    artifacts = LocalArtifactRepository(tmp_path / "var")
    snapshot = _placeholder(artifacts, ArtifactKind.SNAPSHOT, "snapshot")
    monkeypatch.setattr(targets_module, "CanonicalParquetReplaySource", _FakeParquetSource)
    resolver = _resolver(artifacts, RuntimeLockId("9" * 64))
    spec = resolver.resolve(_command(snapshot.artifact_id, BenchmarkWorkload.PARQUET_SCAN))

    # Assemble result once so the test parquet scan dispatch returns verified logical
    # stream hash workflow shares one value.
    result = (
        LocalExactBenchmarkTargetFactory(resolver)
        .create(
            spec,
            artifacts.data_root,
            # Complete create only after its data root and spec inputs are visible in test
            # parquet scan dispatch returns verified logical stream hash.
        )
        .execute_once()
    )

    assert result.items_processed == 3
    assert result.canonical_result_hash == ContentDigest("2" * 64)


# Define test control target fails closed without real route executor as one focused
# operation with an explicit boundary.
def test_control_target_fails_closed_without_real_route_executor(tmp_path: Path) -> None:
    # Execute the test control target fails closed without real route executor workflow in
    # explicit, reviewable steps.
    artifacts, run, manifest = _run_artifact(tmp_path, InferenceMode.DISABLED)
    resolver = _resolver(artifacts, manifest.resolved_spec.runtime_lock_id)
    spec = resolver.resolve(
        _command(
            run.artifact_id,
            # Pass benchmark workload explicitly so _command receives a reviewable
            # artifact id and control plane round trip input in test control target fails
            # closed without real route executor.
            BenchmarkWorkload.CONTROL_PLANE_ROUND_TRIP,
            route=BenchmarkLaunchRoute.DIRECT,
        )
    )

    assert spec.workload_bundle_id == CONTROL_DIRECT_BENCHMARK_BUNDLE_ID
    # Acquire raises, value error and pytest at an explicit test control target fails
    # closed without real route executor context boundary so cleanup remains scoped.
    with pytest.raises(ValueError, match="real control-plane"):
        LocalExactBenchmarkTargetFactory(resolver).validate(spec, artifacts.data_root)

    invocation_ids: list[ContentDigest] = []
    executor = _ControlExecutor(manifest.comparison, invocation_ids=invocation_ids)
    factory = LocalExactBenchmarkTargetFactory(
        # Pass resolver explicitly so LocalExactBenchmarkTargetFactory receives a
        # reviewable resolver and executor input in test control target fails closed
        # without real route executor.
        resolver,
        control_executor=executor,
    )
    measured = factory.create(
        spec,
        # Pass artifacts explicitly so create receives a reviewable 6 and data root input
        # in test control target fails closed without real route executor.
        artifacts.data_root,
        ContentDigest("6" * 64),
        BenchmarkExecutionPhase.MEASURED,
    )
    result = measured.execute_once()
    # Invoke execute_once as a visible step within the test control target fails closed
    # without real route executor workflow.
    measured.execute_once()
    profile = factory.create(
        spec,
        artifacts.data_root,
        ContentDigest("6" * 64),
        # Pass benchmark execution phase explicitly so create receives a reviewable 6 and
        # data root input in test control target fails closed without real route executor.
        BenchmarkExecutionPhase.PROFILE,
    )
    profile.execute_once()
    assert executor.route is BenchmarkLaunchRoute.DIRECT
    assert result.canonical_result_hash == manifest.summary.result_hash
    # Verify the invocation ids relationship before this scenario is accepted.
    assert len(invocation_ids) == len(set(invocation_ids)) == 3


def test_resolver_reopens_committed_bytes_and_rejects_missing_or_tampered_seed(
    tmp_path: Path,
) -> None:
    # Execute the test resolver reopens committed bytes and rejects missing or tampered
    # seed workflow in explicit, reviewable steps.
    artifacts, run, manifest = _run_artifact(tmp_path, InferenceMode.DISABLED)
    resolver = _resolver(artifacts, manifest.resolved_spec.runtime_lock_id)
    missing = _command(ArtifactId("e" * 64), BenchmarkWorkload.FULL_BACKTEST)
    with pytest.raises(ArtifactNotCommittedError):
        resolver.resolve(missing)

    # Assemble handle once so the test resolver reopens committed bytes and rejects
    # missing or tampered seed workflow shares one value.
    handle = artifacts.open_committed(run.artifact_id)
    try:
        manifest_path = cast(_LocalHandle, handle).local_path("manifest.json")
    finally:
        handle.close()
    # Invoke write_bytes for manifest bytes and manifest as a visible test resolver
    # reopens committed bytes and rejects missing or tampered seed step.
    manifest_path.write_bytes(manifest.manifest_bytes() + b"\n")
    with pytest.raises(ArtifactIntegrityError):
        resolver.resolve(_command(run.artifact_id, BenchmarkWorkload.FULL_BACKTEST))


def test_resolver_rejects_runtime_lock_and_input_closure_mismatch(tmp_path: Path) -> None:
    # Execute the test resolver rejects runtime lock and input closure mismatch workflow
    # in explicit, reviewable steps.
    artifacts, run, manifest = _run_artifact(tmp_path, InferenceMode.DISABLED)
    with pytest.raises(ValueError, match="runtime lock"):
        # Keep raises, value error and pytest active only for the bounded test resolver
        # rejects runtime lock and input closure mismatch operation.
        _resolver(artifacts, RuntimeLockId("e" * 64)).resolve(
            _command(run.artifact_id, BenchmarkWorkload.FULL_BACKTEST)
        )

    malformed_nonce = ContentDigest("7" * 64)
    malformed = replace(
        manifest,
        attempt_nonce=malformed_nonce,
        execution_attempt_id=manifest.resolved_spec.execution_attempt_id(
            malformed_nonce,
            manifest.physical_settings.identity_digest,
        ),
        input_artifact_ids=(),
    )
    writer = artifacts.stage(
        # Keep the run ArtifactDraft step visible while building writer.
        ArtifactDraft(
            ArtifactKind.RUN,
            domain_digest("test.malformed-run", {}),
        )
    )
    # Assemble malformed run once so the test resolver rejects runtime lock and input
    # closure mismatch workflow shares one value.
    malformed_run = writer.commit(
        malformed.manifest_bytes(),
        identity_manifest_bytes=malformed.identity_bytes(),
    )
    with pytest.raises(ValueError, match="exact input closure"):
        # Keep raises, value error and pytest active only for the bounded test resolver
        # rejects runtime lock and input closure mismatch operation.
        _resolver(artifacts, manifest.resolved_spec.runtime_lock_id).resolve(
            _command(malformed_run.artifact_id, BenchmarkWorkload.FULL_BACKTEST)
        )


def _resolver(
    artifacts: LocalArtifactRepository,
    # Keep the runtime lock id input explicit in the resolver contract.
    runtime_lock_id: RuntimeLockId,
) -> LocalExactBenchmarkSpecResolver:
    # Execute the resolver workflow in explicit, reviewable steps.
    return LocalExactBenchmarkSpecResolver(
        artifacts.data_root,
        runtime_lock_id,
        duckdb_memory_limit_mb=256,
    )


# Define command as one focused operation with an explicit boundary.
def _command(
    artifact_id: ArtifactId,
    workload: BenchmarkWorkload,
    *,
    route: BenchmarkLaunchRoute = BenchmarkLaunchRoute.LOCAL_ARTIFACT,
    # Keep the exact benchmark command input explicit in the command contract.
) -> ExactBenchmarkCommand:
    # Execute the command workflow in explicit, reviewable steps.
    return ExactBenchmarkCommand(
        target_artifact_id=artifact_id,
        workload=workload,
        launch_route=route,
        cache_condition=CacheCondition.WARM,
        # Pass batch rows explicitly so ExactBenchmarkCommand receives a reviewable
        # benchmark-attempt and warm input in command.
        batch_rows=65_536,
        readahead=2,
        process_count=1,
        native_threads_per_process=1,
        warmup_iterations=0,
        # Pass measured iterations explicitly so ExactBenchmarkCommand receives a
        # reviewable benchmark-attempt and warm input in command.
        measured_iterations=1,
        capacity_days=1,
        attempt_nonce=domain_digest("test.benchmark-attempt", {}),
    )


def _run_artifact(
    # Keep the tmp path input explicit in the run artifact contract.
    tmp_path: Path,
    mode: InferenceMode,
) -> tuple[LocalArtifactRepository, CommittedArtifact, SuccessfulRunManifest]:
    # Execute the run artifact workflow in explicit, reviewable steps.
    artifacts = LocalArtifactRepository(tmp_path / "var")
    snapshot = _placeholder(artifacts, ArtifactKind.SNAPSHOT, "snapshot")
    replay = _placeholder(
        artifacts,
        ArtifactKind.REPLAY_PACK,
        "replay",
        identity={"snapshot_id": snapshot.artifact_id.hex},
    )
    feature = _placeholder(artifacts, ArtifactKind.FEATURE_SET, "feature")
    schedule = _placeholder(artifacts, ArtifactKind.MODEL_SCHEDULE, "schedule")
    # Assemble prediction once so the run artifact workflow shares one value.
    prediction = _placeholder(artifacts, ArtifactKind.PREDICTION_SET, "prediction")
    runtime_lock_id = RuntimeLockId("9" * 64)
    spec = _resolved_spec(
        mode,
        SnapshotId(snapshot.artifact_id.hex),
        # Keep the hex ReplayPackId step visible while building spec.
        ReplayPackId(replay.artifact_id.hex),
        FeatureSetId(feature.artifact_id.hex),
        ModelScheduleId(schedule.artifact_id.hex),
        PredictionSetId(prediction.artifact_id.hex),
        runtime_lock_id,
        # Complete _resolved_spec only after its hex and artifact id inputs are visible in run
        # artifact.
    )
    physical = RunPhysicalSettings(RunBackend.REFERENCE_PYTHON, 65_536, 1, 8_192, 1)
    attempt_nonce = ContentDigest("8" * 64)
    summary = _summary(spec)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    # Assemble manifest once so the run artifact workflow shares one value.
    manifest = SuccessfulRunManifest(
        spec,
        attempt_nonce,
        spec.execution_attempt_id(attempt_nonce, physical.identity_digest),
        run_input_artifact_ids(spec),
        # Pass summary explicitly so SuccessfulRunManifest receives a reviewable execution
        # attempt id and identity digest input in run artifact.
        summary,
        physical,
        now,
        now,
    )
    # Assemble writer once so the run artifact workflow shares one value.
    writer = artifacts.stage(
        ArtifactDraft(
            ArtifactKind.RUN,
            domain_digest("test.run-build", {"mode": mode.value}),
            manifest.input_artifact_ids,
            # Complete ArtifactDraft only after its run-build and mode inputs are visible in
            # run artifact.
        )
    )
    run = writer.commit(
        manifest.manifest_bytes(),
        identity_manifest_bytes=manifest.identity_bytes(),
        # Complete commit only after its manifest bytes and identity bytes inputs are visible
        # in run artifact.
    )
    return artifacts, run, manifest


def _resolved_spec(
    mode: InferenceMode,
    snapshot_id: SnapshotId,
    # Keep the replay pack id input explicit in the resolved spec contract.
    replay_pack_id: ReplayPackId,
    feature_set_id: FeatureSetId,
    model_schedule_id: ModelScheduleId,
    prediction_artifact_id: PredictionSetId,
    runtime_lock_id: RuntimeLockId,
    # Keep the resolved run spec input explicit in the resolved spec contract.
) -> ResolvedRunSpec:
    # Execute the resolved spec workflow in explicit, reviewable steps.
    features: tuple[FeatureSetId, ...]
    schedule: ModelScheduleId | None
    predictions: tuple[PredictionSetId, ...]
    if mode is InferenceMode.DISABLED:
        # Handle the resolved spec mode is InferenceMode.DISABLED branch as a distinct
        # logical block.
        policy = ExactInferencePolicy.disabled()
        features = ()
        schedule = None
        predictions = ()
    # Handle the resolved spec complement of mode is InferenceMode.DISABLED explicitly.
    elif mode is InferenceMode.EMBEDDED_BATCH:
        # Handle the resolved spec mode is InferenceMode.EMBEDDED_BATCH branch as a
        # distinct logical block.
        policy = ExactInferencePolicy.embedded_exact_linear(
            prediction_name="score",
            missing_policy=InferenceMissingPolicy.REJECT,
            inference_delay_boundaries=0,
        )
        # Assemble features once so the resolved spec workflow shares one value.
        features = (feature_set_id,)
        schedule = model_schedule_id
        predictions = ()
    # Handle the resolved spec complement of mode is InferenceMode.EMBEDDED_BATCH
    # explicitly.
    elif mode is InferenceMode.FROZEN:
        # Handle the resolved spec mode is InferenceMode.FROZEN branch as a distinct
        # logical block.
        policy = ExactInferencePolicy.frozen_exact_linear(
            prediction_name="score",
            missing_policy=InferenceMissingPolicy.REJECT,
            inference_delay_boundaries=0,
        )
        # Assemble features once so the resolved spec workflow shares one value.
        features = (feature_set_id,)
        schedule = model_schedule_id
        predictions = (prediction_artifact_id,)
    else:
        raise AssertionError("test helper supports disabled and exact linear modes")
    # Assemble roles once so the resolved spec workflow shares one value.
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
            # Pass role explicitly so create receives a reviewable component and role
            # input in resolved spec.
            role=role,
            bundle_id=BundleId(domain_digest("test.component", {"role": role}).hex),
            config=(
                policy.document()
                if role == "inference"
                # Route all remaining cases through the explicit alternative branch.
                else {"mode": "SHADOW_STATE_REPLAY"}
                if role == "execution"
                else {"maximum_dynamic_items": 1_024}
                if role == "engine"
                else {"version": 1}
                # Complete create only after its component and role inputs are visible in
                # resolved spec.
            ),
        )
        for role in roles
    )
    return ResolvedRunSpec.create(
        # Pass network id explicitly so create receives a reviewable 1 and 2 input in
        # resolved spec.
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        dataset_revision_id=DatasetRevisionId("1" * 64),
        logical_content_hash=LogicalContentHash("2" * 64),
        snapshot_id=snapshot_id,
        # Include replay semantics id in the completed resolved spec result.
        replay_semantics_id=ContentDigest("4" * 64),
        replay_input=ResolvedReplayInput(
            ReplayInputFormat.REPLAY_PACK,
            replay_layout_schema_id=ContentDigest("7" * 64),
            replay_pack_id=replay_pack_id,
            # Complete ResolvedReplayInput only after its 7 and replay pack inputs are visible
            # in resolved spec.
        ),
        components=components,
        runtime_lock_id=runtime_lock_id,
        initial_portfolio=(AssetBalance(AssetId("SOL"), 1_000),),
        root_seed=42,
        # Pass feature set ids explicitly so create receives a reviewable 1 and 2 input in
        # resolved spec.
        feature_set_ids=features,
        model_schedule_id=schedule,
        prediction_set_ids=predictions,
    )


def _summary(spec: ResolvedRunSpec) -> RunSummary:
    # Execute the summary workflow in explicit, reviewable steps.
    components = {item.role: item for item in spec.components}
    return RunSummary(
        dataset_logical_content_hash=spec.logical_content_hash,
        replay_semantics_id=spec.replay_semantics_id,
        engine_bundle_id=ContentDigest(components["engine"].bundle_id.hex),
        # Include latency bundle id in the completed summary result.
        latency_bundle_id=ContentDigest(components["latency"].bundle_id.hex),
        historical_group_count=2,
        historical_event_count=3,
        delivered_event_count=0,
        accepted_order_count=0,
        # Pass rejected order count explicitly so RunSummary receives a reviewable engine
        # and latency input in summary.
        rejected_order_count=0,
        filled_order_count=0,
        failed_order_count=0,
        ledger_transaction_count=0,
        fill_count=0,
        # Include audit hash in the completed summary result.
        audit_hash=ContentDigest("a" * 64),
        ledger_hash=ContentDigest("b" * 64),
        fill_hash=ContentDigest("c" * 64),
        result_hash=ContentDigest("d" * 64),
        final_balances=(),
        # Complete RunSummary only after its engine and latency inputs are visible in summary.
    )


def _placeholder(
    artifacts: LocalArtifactRepository,
    kind: ArtifactKind,
    label: str,
    *,
    identity: dict[str, object] | None = None,
    # Keep the committed artifact input explicit in the placeholder contract.
) -> CommittedArtifact:
    # Execute the placeholder workflow in explicit, reviewable steps.
    writer = artifacts.stage(
        ArtifactDraft(kind, domain_digest("test.placeholder-build", {"label": label}))
    )
    manifest = canonical_json_bytes({**({} if identity is None else identity), "label": label})
    return writer.commit(manifest, identity_manifest_bytes=manifest)
