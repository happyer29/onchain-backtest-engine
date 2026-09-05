# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

# Import testing at the visible module dependency boundary.
from typer.testing import CliRunner

from backtest.application.errors import IdempotencyConflictError
from backtest.application.ml_artifacts import (
    BuildFrozenPredictionsRequest,
    FrozenMissingPolicy,
    # Include publish model schedule request so the ml artifacts dependency remains
    # explicit.
    PublishModelScheduleRequest,
    TrainExactLinearModelRequest,
)
from backtest.application.ml_contracts import (
    FeatureSpec,
    # Include model canonicality so the ml contracts dependency remains explicit.
    ModelCanonicality,
    ModelSchedule,
    ModelScheduleEntry,
    NullPolicy,
    TemporalSplit,
    # Include training job spec so the ml contracts dependency remains explicit.
    TrainingJobSpec,
)
from backtest.application.ml_job_commands import (
    MlResolvedJob,
    ResolvedBuildFeaturesJob,
    # Include resolved build labels job so the ml job commands dependency remains
    # explicit.
    ResolvedBuildLabelsJob,
    ResolvedBuildModelScheduleJob,
    ResolvedBuildUniverseJob,
    ResolvedPredictJob,
    ResolvedTrainModelJob,
    # Include resolve ml job command so the ml job commands dependency remains explicit.
    resolve_ml_job_command,
)
from backtest.application.models import (
    ArtifactKind,
    AttemptState,
    # Include committed artifact so the models dependency remains explicit.
    CommittedArtifact,
    JobRecord,
    JobType,
    ResolvedJobSpec,
)

# Import submit job at the visible module dependency boundary.
from backtest.application.use_cases.submit_job import SubmitJob, SubmitJobRequest
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import (
    ArtifactId,
    BundleId,
    # Include content digest so the identifiers dependency remains explicit.
    ContentDigest,
    FeatureSetId,
    JobId,
    LabelSetId,
    ModelBundleId,
    # Include model schedule id so the identifiers dependency remains explicit.
    ModelScheduleId,
    ReplayPackId,
    RuntimeLockId,
    SnapshotId,
    UniverseId,
    # Close the identifiers import after its required symbols are visible.
)
from backtest.interfaces.api.ml_schemas import (
    BuildFeaturesJobForm,
    BuildLabelsJobForm,
    BuildModelScheduleJobForm,
    # Include build universe job form so the ml schemas dependency remains explicit.
    BuildUniverseJobForm,
    PredictJobForm,
    TrainModelJobForm,
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


# Keep the ml backend contract and validation rules together.
class _MlBackend:
    def __init__(self) -> None:
        # Execute the ml backend init workflow in explicit, reviewable steps.
        self.queue = _MemoryQueue()
        self.submitter = SubmitJob(self.queue)
        self.requests: list[SubmitJobRequest] = []
        self.direct_commands: list[MlResolvedJob] = []

    def submit_job(self, request: SubmitJobRequest) -> JobRecord:
        # Execute the ml backend submit job workflow in explicit, reviewable steps.
        self.requests.append(request)
        return self.submitter.execute(request)

    def execute_ml_job(self, command: MlResolvedJob) -> CommittedArtifact:
        # Execute the ml backend execute ml job workflow in explicit, reviewable steps.
        self.direct_commands.append(command)
        digest = domain_digest(
            "test.cli-ml-result",
            {"job_type": command.JOB_TYPE.value},
        )
        # Return the completed ml backend execute ml job result without a hidden fallback.
        return CommittedArtifact(
            ArtifactId(digest.hex),
            _RESULT_KINDS[command.JOB_TYPE],
            digest,
            digest,
            # Pass command explicitly so CommittedArtifact receives a reviewable hex and
            # job type input in ml backend execute ml job.
            command.input_artifact_ids,
        )


# Keep the factory contract and validation rules together.
class _Factory:
    def __init__(self, backend: _MlBackend) -> None:
        self.backend = backend

    def __call__(
        self,
        # Keep the config path input explicit in the call contract.
        config_path: Path,
        capabilities_file: Path | None,
        *,
        require_capabilities: bool = False,
        prefer_running_controller: bool = False,
        # Keep the ml backend input explicit in the call contract.
    ) -> _MlBackend:
        # Execute the factory call workflow in explicit, reviewable steps.
        del config_path, capabilities_file, require_capabilities, prefer_running_controller
        return self.backend


_RESULT_KINDS = {
    JobType.BUILD_FEATURES: ArtifactKind.FEATURE_SET,
    JobType.BUILD_UNIVERSE: ArtifactKind.UNIVERSE,
    # Keep the job type component named inside the result kinds contract.
    JobType.BUILD_LABELS: ArtifactKind.LABEL_SET,
    JobType.TRAIN_MODEL: ArtifactKind.MODEL_BUNDLE,
    JobType.BUILD_MODEL_SCHEDULE: ArtifactKind.MODEL_SCHEDULE,
    JobType.PREDICT: ArtifactKind.PREDICTION_SET,
}

# Bind cli cases once as an explicit module-level contract.
_CLI_CASES: tuple[tuple[str, type[Any], int, JobType], ...] = (
    ("build-features", BuildFeaturesJobForm, 0, JobType.BUILD_FEATURES),
    ("build-universe", BuildUniverseJobForm, 1, JobType.BUILD_UNIVERSE),
    ("build-labels", BuildLabelsJobForm, 2, JobType.BUILD_LABELS),
    ("train", TrainModelJobForm, 3, JobType.TRAIN_MODEL),
    # Keep the build component named inside the cli cases contract.
    ("build-model-schedule", BuildModelScheduleJobForm, 4, JobType.BUILD_MODEL_SCHEDULE),
    ("predict", PredictJobForm, 5, JobType.PREDICT),
)


@pytest.mark.parametrize(("cli_name", "form_type", "index", "job_type"), _CLI_CASES)
def test_each_ml_alias_enqueues_its_exact_typed_command(
    # Keep the tmp path input explicit in the test each ml alias enqueues its exact typed
    # command contract.
    tmp_path: Path,
    cli_name: str,
    form_type: type[Any],
    index: int,
    job_type: JobType,
    # Close the test each ml alias enqueues its exact typed command signature after its
    # explicit inputs.
) -> None:
    # Execute the test each ml alias enqueues its exact typed command workflow in
    # explicit, reviewable steps.
    backend = _MlBackend()
    command = _commands()[index]
    request_file = tmp_path / f"{cli_name}.json"
    request_file.write_text(form_type.from_domain(command).model_dump_json())

    result = CliRunner().invoke(
        # Keep the create cli and factory create_cli step visible while building result.
        create_cli(_Factory(backend)),
        [
            cli_name,
            str(request_file),
            "--enqueue",
            # Pass idempotency-key explicitly so invoke receives a reviewable --enqueue
            # and --idempotency-key input in test each ml alias enqueues its exact typed
            # command.
            "--idempotency-key",
            f"{cli_name}-key",
        ],
    )

    assert result.exit_code == 0, result.output
    # Verify the queued, state and loads relationship before this scenario is accepted.
    assert json.loads(result.stdout)["state"] == "QUEUED"
    assert backend.direct_commands == []
    assert len(backend.requests) == 1
    request = backend.requests[0]
    assert request.job_type is job_type
    # Verify the idempotency key, request and cli name relationship before this scenario
    # is accepted.
    assert request.idempotency_key == f"{cli_name}-key"
    assert request.input_artifact_ids == command.input_artifact_ids
    resolved = resolve_ml_job_command(job_type, request.payload_json)
    assert resolved.canonical_payload == command.canonical_bytes()
    assert resolved.input_artifact_ids == command.input_artifact_ids


# Apply parametrize semantics to the following test each ml alias uses the direct typed
# backend by default contract.
@pytest.mark.parametrize(("cli_name", "form_type", "index", "job_type"), _CLI_CASES)
def test_each_ml_alias_uses_the_direct_typed_backend_by_default(
    tmp_path: Path,
    cli_name: str,
    form_type: type[Any],
    # Keep the index input explicit in the test each ml alias uses the direct typed
    # backend by default contract.
    index: int,
    job_type: JobType,
) -> None:
    # Execute the test each ml alias uses the direct typed backend by default workflow in
    # explicit, reviewable steps.
    backend = _MlBackend()
    command = _commands()[index]
    request_file = tmp_path / f"{cli_name}.json"
    request_file.write_text(form_type.from_domain(command).model_dump_json())

    result = CliRunner().invoke(
        # Keep the create cli and factory create_cli step visible while building result.
        create_cli(_Factory(backend)),
        [cli_name, str(request_file)],
    )

    assert result.exit_code == 0, result.output
    assert backend.requests == []
    # Verify backend.direct_commands == [command] before this scenario is accepted.
    assert backend.direct_commands == [command]
    response = json.loads(result.stdout)
    assert response["artifact_kind"] == _RESULT_KINDS[job_type].value
    assert response["artifact_id"] == response["build_key"] == response["manifest_digest"]


def test_ml_enqueue_requires_a_key_and_direct_rejects_one(tmp_path: Path) -> None:
    # Execute the test ml enqueue requires a key and direct rejects one workflow in
    # explicit, reviewable steps.
    backend = _MlBackend()
    command = _commands()[0]
    request_file = tmp_path / "features.json"
    request_file.write_text(BuildFeaturesJobForm.from_domain(command).model_dump_json())
    cli = create_cli(_Factory(backend))

    # Assemble missing once so the test ml enqueue requires a key and direct rejects one
    # workflow shares one value.
    missing = CliRunner().invoke(cli, ["build-features", str(request_file), "--enqueue"])
    direct_key = CliRunner().invoke(
        cli,
        ["build-features", str(request_file), "--idempotency-key", "unused"],
    )

    # Verify missing.exit_code == 2 before this scenario is accepted.
    assert missing.exit_code == 2
    assert json.loads(missing.stderr)["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert direct_key.exit_code == 2
    assert json.loads(direct_key.stderr)["code"] == "IDEMPOTENCY_KEY_WITHOUT_ENQUEUE"
    assert backend.requests == []
    # Verify backend.direct_commands == [] before this scenario is accepted.
    assert backend.direct_commands == []


def _commands() -> tuple[
    ResolvedBuildFeaturesJob,
    ResolvedBuildUniverseJob,
    ResolvedBuildLabelsJob,
    # Keep the resolved train model job input explicit in the commands contract.
    ResolvedTrainModelJob,
    ResolvedBuildModelScheduleJob,
    ResolvedPredictJob,
]:
    # Execute the commands workflow in explicit, reviewable steps.
    feature_id = FeatureSetId(_digest("features").hex)
    model_id = ModelBundleId(_digest("model").hex)
    universe_id = UniverseId(_digest("universe").hex)
    feature = FeatureSpec(
        name="momentum",
        # Pass version explicitly so FeatureSpec receives a reviewable momentum and replay
        # row id input in commands.
        version=1,
        entity_key="replay_row_id",
        input_ids=(_digest("source-input"),),
        effective_time_semantics="event-boundary-v1",
        available_time_semantics="next-boundary-v1",
        # Pass warmup boundaries explicitly so FeatureSpec receives a reviewable momentum
        # and replay row id input in commands.
        warmup_boundaries=2,
        dtype="<i8",
        null_policy=NullPolicy.EXPLICIT_BITMAP,
        code_bundle_id=BundleId(_digest("feature-bundle").hex),
        runtime_lock_id=RuntimeLockId(_digest("runtime").hex),
        # Complete FeatureSpec only after its momentum and replay row id inputs are visible in
        # commands.
    )
    training_spec = TrainingJobSpec(
        feature_set_ids=(feature_id,),
        label_set_id=LabelSetId(_digest("labels").hex),
        universe_id=universe_id,
        # Keep the temporal split TemporalSplit step visible while building training spec.
        split=TemporalSplit(0, 20, 25, 30, 2, 1),
        hyperparameter_digest=_digest("hyperparameters"),
        root_seeds=(7,),
        training_cutoff=20,
        modeled_available_boundary=22,
        # Keep the hex BundleId step visible while building training spec.
        trainer_bundle_id=BundleId(_digest("trainer").hex),
        runtime_lock_id=RuntimeLockId(_digest("runtime").hex),
    )
    schedule = ModelSchedule(
        (
            # Keep the model schedule entry and model id ModelScheduleEntry step visible
            # while building schedule.
            ModelScheduleEntry(22, 30, model_id, 20, 22, "receipt-v1"),
            ModelScheduleEntry(30, 40, model_id, 28, 29, "modeled-v1"),
        )
    )
    replay_id = ReplayPackId(_digest("replay").hex)
    # Assemble semantics id once so the commands workflow shares one value.
    semantics_id = _digest("semantics")
    layout_id = _digest("layout")
    compiler = "numpy-point-in-time-ml-v1"
    return (
        ResolvedBuildFeaturesJob(
            # Pass replay id explicitly so ResolvedBuildFeaturesJob receives a reviewable
            # replay id and semantics id input in commands.
            replay_id,
            semantics_id,
            layout_id,
            (feature,),
            (feature_id,),
            # Pass compiler explicitly so ResolvedBuildFeaturesJob receives a reviewable
            # replay id and semantics id input in commands.
            compiler,
        ),
        ResolvedBuildUniverseJob(
            SnapshotId(_digest("snapshot").hex),
            _digest("universe-spec"),
            # Open the snapshot and universe-spec payload explicitly for
            # ResolvedBuildUniverseJob within commands.
            (feature_id,),
            BundleId(_digest("universe-builder").hex),
            _digest("universe-config"),
            compiler,
        ),
        # Include resolved build labels job in the completed commands result.
        ResolvedBuildLabelsJob(
            SnapshotId(_digest("snapshot").hex),
            universe_id,
            _digest("label-spec"),
            BundleId(_digest("label-builder").hex),
            # Include digest in the completed commands result.
            _digest("label-config"),
            20,
            compiler,
        ),
        ResolvedTrainModelJob(
            # Include train exact linear model request in the completed commands result.
            TrainExactLinearModelRequest(
                training_spec,
                _digest("feature-schema"),
                _digest("preprocessing"),
                _digest("calibration"),
                # Keep train exact linear model request, training spec and exact-rational-
                # linear-v1 visible while completing TrainExactLinearModelRequest within
                # commands.
                1,
                "exact-rational-linear-v1",
                ModelCanonicality.CANONICAL_EXACT,
                compiler,
            )
            # Complete ResolvedTrainModelJob only after its exact-rational-linear-v1 and
            # feature-schema inputs are visible in commands.
        ),
        ResolvedBuildModelScheduleJob(
            PublishModelScheduleRequest(
                schedule,
                ModelCanonicality.CANONICAL_EXACT,
                # Pass compiler explicitly so PublishModelScheduleRequest receives a
                # reviewable canonical exact and schedule input in commands.
                compiler,
            )
        ),
        ResolvedPredictJob(
            BuildFrozenPredictionsRequest(
                # Pass replay id explicitly so BuildFrozenPredictionsRequest receives a
                # reviewable schedule and expected-return input in commands.
                replay_id,
                semantics_id,
                layout_id,
                (feature_id,),
                ModelScheduleId(_digest("schedule").hex),
                # Open the schedule and expected-return payload explicitly for
                # BuildFrozenPredictionsRequest within commands.
                (model_id,),
                "expected-return",
                2,
                FrozenMissingPolicy.REJECT,
                ModelCanonicality.CANONICAL_EXACT,
                # Pass compiler explicitly so BuildFrozenPredictionsRequest receives a
                # reviewable schedule and expected-return input in commands.
                compiler,
            )
        ),
    )


def _digest(label: str) -> ContentDigest:
    # Return the completed digest result without a hidden fallback.
    return domain_digest("test.cli-ml", {"label": label})
