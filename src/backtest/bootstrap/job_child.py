"""Strict isolated child dispatcher for already-resolved local job commands."""

from __future__ import annotations

import argparse
import json
import os
import stat

# Import sys at the visible module dependency boundary.
import sys
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Final, cast

# Import localfs at the visible module dependency boundary.
from backtest.adapters.artifacts.localfs import (
    DataRootLayout,
    LocalArtifactRepository,
    LocalCompletionReceiptStore,
)

# Import progress pipe at the visible module dependency boundary.
from backtest.adapters.process.progress_pipe import progress_sink_from_environment
from backtest.application.attempt_identity import queued_execution_attempt_nonce
from backtest.application.completion import AttemptCompletionReceipt, CompletionOutput
from backtest.application.delivery_schedules import CompileDeliveryScheduleRequest
from backtest.application.job_commands import (
    # Include resolved job command error so the job commands dependency remains explicit.
    ResolvedJobCommandError,
    resolve_job_command,
    resolved_backtest_job_from_bytes,
    resolved_compile_delivery_job_from_bytes,
    resolved_compile_replay_job_from_bytes,
    # Include resolved prepare dataset job from bytes so the job commands dependency
    # remains explicit.
    resolved_prepare_dataset_job_from_bytes,
    resolved_sweep_job_from_bytes,
)
from backtest.application.ml_job_commands import (
    resolved_build_features_job_from_bytes,
    # Include resolved build labels job from bytes so the ml job commands dependency
    # remains explicit.
    resolved_build_labels_job_from_bytes,
    resolved_build_model_schedule_job_from_bytes,
    resolved_build_universe_job_from_bytes,
    resolved_predict_job_from_bytes,
    resolved_train_model_job_from_bytes,
    # Close the ml job commands import after its required symbols are visible.
)
from backtest.application.models import (
    BudgetStatus,
    CommittedArtifact,
    JobType,
    # Include progress event so the models dependency remains explicit.
    ProgressEvent,
    ProgressLevel,
    ProgressStage,
    ResolvedJobSpec,
)

# Import progress at the visible module dependency boundary.
from backtest.application.ports.progress import ProgressSink
from backtest.application.use_cases.compile_replay import CompileReplayRequest
from backtest.application.use_cases.prepare_dataset import PrepareDatasetRequest
from backtest.application.use_cases.run_backtest import RunBacktestRequest
from backtest.bootstrap.config import ConfigError, load_settings

# Import execution container at the visible module dependency boundary.
from backtest.bootstrap.execution_container import ExecutionContainer, build_execution_container
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import ArtifactId, AttemptId, ContentDigest, JobId
from backtest.engine.rng import RNG_ALGORITHM

_ENVELOPE_SCHEMA: Final = "backtest.local-job-envelope.v1"
# Bind max envelope bytes once as an explicit module-level contract.
_MAX_ENVELOPE_BYTES: Final = 3 * 1024 * 1024
_USER_ERROR_EXIT: Final = 78
_INTERNAL_ERROR_EXIT: Final = 70
_EXECUTION_STAGES: Final = {
    JobType.PREPARE_DATASET: ProgressStage.PREPARING_DATASET,
    # Keep the job type component named inside the execution stages contract.
    JobType.COMPILE_REPLAY: ProgressStage.COMPILING_REPLAY,
    JobType.COMPILE_DELIVERY_SCHEDULE: ProgressStage.COMPILING_DELIVERY_SCHEDULE,
    JobType.BUILD_FEATURES: ProgressStage.BUILDING_FEATURES,
    JobType.BUILD_UNIVERSE: ProgressStage.BUILDING_UNIVERSE,
    JobType.BUILD_LABELS: ProgressStage.BUILDING_LABELS,
    # Keep the job type component named inside the execution stages contract.
    JobType.TRAIN_MODEL: ProgressStage.TRAINING_MODEL,
    JobType.BUILD_MODEL_SCHEDULE: ProgressStage.BUILDING_MODEL_SCHEDULE,
    JobType.PREDICT: ProgressStage.BUILDING_PREDICTIONS,
    JobType.RUN_BACKTEST: ProgressStage.RUNNING_BACKTEST,
    JobType.RUN_SWEEP: ProgressStage.RUNNING_SWEEP,
    # Complete the execution stages group only after its semantic components are visible.
}


class ChildEnvelopeError(ValueError):
    """The trusted launch file is malformed or differs from its resolved spec."""


class ChildExecutionError(RuntimeError):
    """The resolved child command could not produce a verified completion receipt."""


@dataclass(frozen=True, slots=True)
class LaunchEnvelope:
    attempt_id: AttemptId
    job_id: JobId
    spec: ResolvedJobSpec


# Keep the child execution result contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ChildExecutionResult:
    receipt: AttemptCompletionReceipt
    receipt_digest: ContentDigest


# Keep the child progress reporter contract and validation rules together.
@dataclass(slots=True)
class _ChildProgressReporter:
    attempt_id: AttemptId
    sink: ProgressSink
    sequence: int = 0

    # Define child progress reporter publish as one focused operation with an explicit
    # boundary.
    def publish(
        self,
        stage: ProgressStage,
        *,
        completed_units: int | None = None,
        # Keep the total units input explicit in the publish contract.
        total_units: int | None = None,
    ) -> None:
        # Execute the child progress reporter publish workflow in explicit, reviewable
        # steps.
        self.sequence += 1
        self.sink.publish(
            ProgressEvent(
                attempt_id=self.attempt_id,
                sequence=self.sequence,
                # Pass level explicitly so ProgressEvent receives a reviewable attempt id
                # and sequence input in child progress reporter publish.
                level=ProgressLevel.INFO,
                stage=stage,
                completed_units=completed_units,
                total_units=total_units,
            )
            # Complete publish only after its attempt id and sequence inputs are visible in
            # child progress reporter publish.
        )


def execute_envelope(
    envelope_path: Path,
    *,
    config_path: Path,
    # Keep the capabilities file input explicit in the execute envelope contract.
    capabilities_file: Path | None = None,
    progress_sink: ProgressSink | None = None,
) -> ChildExecutionResult:
    """Execute one exact launch without ever constructing a SQLite adapter."""

    settings = load_settings(config_path)
    data_root = settings.paths.data_root.resolve()
    trusted_directory = data_root / "tmp" / "job-launch"
    envelope = load_launch_envelope(envelope_path, trusted_directory=trusted_directory)
    reporter = _ChildProgressReporter(
        # Pass envelope explicitly so _ChildProgressReporter receives a reviewable attempt
        # id and progress sink from environment input in execute envelope.
        envelope.attempt_id,
        progress_sink if progress_sink is not None else progress_sink_from_environment(),
    )
    reporter.publish(ProgressStage.VALIDATING_INPUTS)
    if envelope.spec.job_type is JobType.PREPARE_DATASET:
        # Handle the execute envelope job type, prepare dataset and spec condition as a
        # distinct block.
        from backtest.bootstrap.preparation_container import build_preparation_container

        preparation = build_preparation_container(
            settings,
            capabilities_file=capabilities_file,
        )
        # Assemble artifacts once so the execute envelope workflow shares one value.
        artifacts = preparation.artifacts
        _verify_exact_inputs(artifacts, envelope.spec.input_artifact_ids)
        command = resolved_prepare_dataset_job_from_bytes(envelope.spec.canonical_payload)
        if command.plan.budget.status is BudgetStatus.REJECTED:
            raise ChildExecutionError("a rejected dataset plan cannot be executed")
        # Invoke validate_execution for plan and reusable distributions as a visible
        # execute envelope step.
        preparation.validate_execution(command.plan, command.reusable_distributions)
        reporter.publish(_EXECUTION_STAGES[envelope.spec.job_type])
        prepared = preparation.prepare_dataset.execute(
            PrepareDatasetRequest(command.plan, command.reusable_distributions)
        )
        # Assemble result artifact once so the execute envelope workflow shares one value.
        result_artifact = prepared.artifact
        reused_ids = {item.artifact_id for item in command.reusable_distributions}
        outputs = (
            prepared.artifact,
            *(
                # Keep the item component named inside the outputs contract.
                item.artifact
                for item in prepared.distributions
                if item.artifact.artifact_id not in reused_ids
            ),
        )
    # Route all remaining cases through the explicit alternative branch.
    else:
        # Handle the execute envelope complement of job type, prepare dataset and spec
        # explicitly.
        execution = build_execution_container(
            settings,
            verify_isolated_child_environment=True,
        )
        artifacts = execution.artifacts
        # Invoke _verify_exact_inputs for input artifact ids and spec as a visible execute
        # envelope step.
        _verify_exact_inputs(artifacts, envelope.spec.input_artifact_ids)
        reporter.publish(_EXECUTION_STAGES[envelope.spec.job_type])
        result_artifact, outputs = _dispatch(
            execution,
            envelope.spec,
            # Pass attempt id explicitly so _dispatch receives a reviewable spec and
            # attempt id input in execute envelope.
            attempt_id=envelope.attempt_id,
        )
    reporter.publish(ProgressStage.VERIFYING_OUTPUTS)
    verified_outputs = _verify_outputs(artifacts, outputs)
    receipt = AttemptCompletionReceipt(
        # Pass version explicitly so AttemptCompletionReceipt receives a reviewable
        # attempt id and spec id input in execute envelope.
        version=1,
        attempt_id=envelope.attempt_id,
        resolved_spec_id=envelope.spec.spec_id,
        result_artifact_id=result_artifact.artifact_id,
        outputs=tuple(
            # Keep the artifact id CompletionOutput step visible while building receipt.
            CompletionOutput(item.artifact_id, item.manifest_digest)
            for item in verified_outputs
        ),
    )
    reporter.publish(ProgressStage.PUBLISHING_RECEIPT)
    # Assemble receipt digest once so the execute envelope workflow shares one value.
    receipt_digest = LocalCompletionReceiptStore(DataRootLayout(artifacts.data_root)).publish(
        # Pass receipt explicitly so publish receives a reviewable receipt input in
        # execute envelope.
        receipt
    )
    reporter.publish(ProgressStage.COMPLETED, completed_units=1, total_units=1)
    return ChildExecutionResult(receipt, receipt_digest)


def load_launch_envelope(path: Path, *, trusted_directory: Path) -> LaunchEnvelope:
    """Read one canonical direct-child file without following a symlink."""

    trusted = trusted_directory.resolve()
    candidate = path.absolute()
    try:
        # Perform the protected load launch envelope operation before explicit failure
        # handling.
        if candidate.parent.resolve(strict=True) != trusted:
            raise ChildEnvelopeError("launch envelope is outside its trusted directory")
        descriptor = os.open(
            candidate,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            # Complete open only after its o nofollow and o cloexec inputs are visible in load
            # launch envelope.
        )
    except ChildEnvelopeError:
        raise
    except OSError as error:
        raise ChildEnvelopeError("launch envelope is unavailable") from error
    # Keep expected failures inside the load launch envelope error boundary.
    try:
        # Perform the protected load launch envelope operation before explicit failure
        # handling.
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size > _MAX_ENVELOPE_BYTES
            # Evaluate the complete load launch envelope st nlink, st size and max envelope
            # bytes condition before guarded effects.
        ):
            raise ChildEnvelopeError("launch envelope is not a bounded private file")
        with os.fdopen(descriptor, "rb") as stream:
            # Keep fdopen, descriptor and rb active only for the bounded load launch
            # envelope operation.
            descriptor = -1
            payload = stream.read(_MAX_ENVELOPE_BYTES + 1)
    finally:
        # Handle the cleanup path after the protected load launch envelope operation.
        if descriptor >= 0:
            os.close(descriptor)
    if len(payload) > _MAX_ENVELOPE_BYTES:
        raise ChildEnvelopeError("launch envelope exceeds its size limit")
    try:
        # Perform the protected load launch envelope operation before explicit failure
        # handling.
        value = json.loads(payload)
        canonical = canonical_json_bytes(value)
    except (TypeError, ValueError, UnicodeDecodeError) as error:
        raise ChildEnvelopeError("launch envelope is not valid canonical JSON") from error
    if canonical != payload:
        # Fail the load launch envelope path with ChildEnvelopeError for launch envelope
        # is not exact canonical json when canonical and payload is true; do not continue
        # ambiguously.
        raise ChildEnvelopeError("launch envelope is not exact canonical JSON")
    document = _object(value, "launch envelope")
    expected = {
        "attempt_id",
        "input_artifact_ids",
        # Keep the job id component named inside the expected contract.
        "job_id",
        "job_type",
        "payload",
        "payload_digest",
        "schema",
        # Keep the spec id component named inside the expected contract.
        "spec_id",
        "spec_version",
    }
    if set(document) != expected or document["schema"] != _ENVELOPE_SCHEMA:
        raise ChildEnvelopeError("launch envelope schema is invalid")
    # Keep expected failures inside the load launch envelope error boundary.
    try:
        # Perform the protected load launch envelope operation before explicit failure
        # handling.
        attempt_id = AttemptId(_string(document["attempt_id"], "attempt_id"))
        job_id = JobId(_string(document["job_id"], "job_id"))
        job_type = JobType(_string(document["job_type"], "job_type"))
        spec_version = _positive_integer(document["spec_version"], "spec_version")
        raw_inputs = document["input_artifact_ids"]
        # Guard this path with not isinstance(raw_inputs, list) before applying effects.
        if not isinstance(raw_inputs, list):
            raise ChildEnvelopeError("input_artifact_ids must be a list")
        inputs = tuple(ArtifactId(_string(item, "input artifact ID")) for item in raw_inputs)
        if inputs != tuple(sorted(inputs, key=lambda item: item.hex)) or len(inputs) != len(
            set(inputs)
            # Complete len only after its set and inputs inputs are visible in load launch
            # envelope.
        ):
            raise ChildEnvelopeError("input artifact IDs must be sorted and unique")
        command_payload = canonical_json_bytes(_object(document["payload"], "job payload"))
        spec = ResolvedJobSpec(
            spec_version=spec_version,
            # Keep the content digest and string ContentDigest step visible while building
            # spec.
            spec_id=ContentDigest(_string(document["spec_id"], "spec_id")),
            job_type=job_type,
            canonical_payload=command_payload,
            payload_digest=ContentDigest(_string(document["payload_digest"], "payload_digest")),
            input_artifact_ids=inputs,
            # Complete ResolvedJobSpec only after its spec id and payload digest inputs are
            # visible in load launch envelope.
        )
        resolved = resolve_job_command(job_type, command_payload)
    except (KeyError, TypeError, ValueError, ResolvedJobCommandError) as error:
        # Translate the key error, type error and value error failure through the load
        # launch envelope boundary.
        if isinstance(error, ChildEnvelopeError):
            raise
        raise ChildEnvelopeError("launch envelope fields are invalid") from error
    if spec.spec_version != 1:
        raise ChildEnvelopeError("unsupported resolved job spec version")
    # Evaluate the complete load launch envelope input artifact ids, resolved and spec
    # condition before guarded effects.
    if resolved.input_artifact_ids != spec.input_artifact_ids:
        raise ChildEnvelopeError("launch inputs differ from the resolved command closure")
    expected_name = f"{sha256(attempt_id.value.encode('utf-8')).hexdigest()}.json"
    if candidate.name != expected_name:
        raise ChildEnvelopeError("launch envelope filename differs from its attempt identity")
    # Return the completed load launch envelope result without a hidden fallback.
    return LaunchEnvelope(attempt_id, job_id, spec)


def _dispatch(
    execution: ExecutionContainer,
    spec: ResolvedJobSpec,
    *,
    # Keep the attempt id input explicit in the dispatch contract.
    attempt_id: AttemptId,
) -> tuple[CommittedArtifact, tuple[CommittedArtifact, ...]]:
    # Execute the dispatch workflow in explicit, reviewable steps.
    payload = spec.canonical_payload
    if spec.job_type is JobType.COMPILE_REPLAY:
        # Handle the dispatch job type, compile replay and spec condition as a distinct
        # block.
        replay_command = resolved_compile_replay_job_from_bytes(payload)
        replay_result = execution.compile_replay.execute(
            CompileReplayRequest(
                replay_command.snapshot_id,
                replay_command.compiler_version,
                # Complete CompileReplayRequest only after its snapshot id and compiler
                # version inputs are visible in dispatch.
            )
        )
        return replay_result.artifact, (replay_result.artifact,)
    if spec.job_type is JobType.BUILD_FEATURES:
        # Handle the dispatch job type, build features and spec condition as a distinct
        # block.
        feature_command = resolved_build_features_job_from_bytes(payload)
        feature_result = execution.build_feature_set.execute(
            feature_command.publication_request(execution.ml_rows.feature_rows(feature_command))
        )
        return feature_result.artifact, (feature_result.artifact,)
    # Evaluate the complete dispatch job type, build universe and spec condition before
    # guarded effects.
    if spec.job_type is JobType.BUILD_UNIVERSE:
        # Handle the dispatch job type, build universe and spec condition as a distinct
        # block.
        universe_command = resolved_build_universe_job_from_bytes(payload)
        universe_result = execution.build_universe.execute(
            universe_command.publication_request(execution.ml_rows.universe_rows(universe_command))
        )
        return universe_result.artifact, (universe_result.artifact,)
    # Guard this path with spec.job_type is JobType.BUILD_LABELS before applying effects.
    if spec.job_type is JobType.BUILD_LABELS:
        # Handle the dispatch spec.job_type is JobType.BUILD_LABELS branch as a distinct
        # logical block.
        label_command = resolved_build_labels_job_from_bytes(payload)
        label_result = execution.build_label_set.execute(
            label_command.publication_request(execution.ml_rows.label_rows(label_command))
        )
        return label_result.artifact, (label_result.artifact,)
    # Guard this path with spec.job_type is JobType.TRAIN_MODEL before applying effects.
    if spec.job_type is JobType.TRAIN_MODEL:
        # Handle the dispatch spec.job_type is JobType.TRAIN_MODEL branch as a distinct
        # logical block.
        train_command = resolved_train_model_job_from_bytes(payload)
        model_result = execution.train_model.execute(train_command.request)
        return model_result.artifact, (model_result.artifact,)
    if spec.job_type is JobType.BUILD_MODEL_SCHEDULE:
        # Handle the dispatch job type, build model schedule and spec condition as a
        # distinct block.
        schedule_command = resolved_build_model_schedule_job_from_bytes(payload)
        schedule_result = execution.publish_model_schedule.execute(schedule_command.request)
        return schedule_result.artifact, (schedule_result.artifact,)
    if spec.job_type is JobType.PREDICT:
        # Handle the dispatch spec.job_type is JobType.PREDICT branch as a distinct
        # logical block.
        predict_command = resolved_predict_job_from_bytes(payload)
        prediction_result = execution.build_frozen_predictions.execute(predict_command.request)
        return prediction_result.artifact, (prediction_result.artifact,)
    if spec.job_type is JobType.COMPILE_DELIVERY_SCHEDULE:
        # Handle the dispatch job type, compile delivery schedule and spec condition as a
        # distinct block.
        delivery_command = resolved_compile_delivery_job_from_bytes(payload)
        run_spec = delivery_command.resolved_spec
        replay_pack_id = run_spec.replay_input.replay_pack_id
        layout_id = run_spec.replay_input.replay_layout_schema_id
        if replay_pack_id is None or layout_id is None:
            # Fail the dispatch path with ChildExecutionError for resolved delivery job
            # lost its replay pack contract when replay pack id and layout id is true; do
            # not continue ambiguously.
            raise ChildExecutionError("resolved delivery job lost its ReplayPack contract")
        roles = {"clock", "engine", "latency", "scheduler"}
        delivery_result = execution.compile_delivery_schedule.execute(
            CompileDeliveryScheduleRequest(
                replay_pack_id=replay_pack_id,
                # Pass replay semantics id explicitly so CompileDeliveryScheduleRequest
                # receives a reviewable replay semantics id and components input in
                # dispatch.
                replay_semantics_id=run_spec.replay_semantics_id,
                replay_layout_schema_id=layout_id,
                components=tuple(item for item in run_spec.components if item.role in roles),
                rng_algorithm=RNG_ALGORITHM,
                root_seed=run_spec.root_seed,
                # Pass compiler version explicitly so CompileDeliveryScheduleRequest
                # receives a reviewable replay semantics id and components input in
                # dispatch.
                compiler_version=delivery_command.compiler_version,
            )
        )
        return delivery_result.artifact, (delivery_result.artifact,)
    if spec.job_type is JobType.RUN_BACKTEST:
        # Handle the dispatch spec.job_type is JobType.RUN_BACKTEST branch as a distinct
        # logical block.
        run_command = resolved_backtest_job_from_bytes(payload)
        run_result = execution.run_backtest.execute(
            RunBacktestRequest(
                run_command.resolved_spec,
                queued_execution_attempt_nonce(
                    # Pass run command explicitly so queued_execution_attempt_nonce
                    # receives a reviewable attempt nonce and spec id input in dispatch.
                    run_command.attempt_nonce,
                    attempt_id,
                    spec.spec_id,
                ),
                run_command.physical_settings,
                # Complete RunBacktestRequest only after its resolved spec and attempt nonce
                # inputs are visible in dispatch.
            )
        )
        return run_result.artifact, (run_result.artifact,)
    if spec.job_type is JobType.RUN_SWEEP:
        # Handle the dispatch spec.job_type is JobType.RUN_SWEEP branch as a distinct
        # logical block.
        sweep_command = resolved_sweep_job_from_bytes(payload)
        sweep_result = execution.run_sweep.execute(
            sweep_command.resolved_sweep_spec,
            attempt_namespace=queued_execution_attempt_nonce(
                ContentDigest(sweep_command.resolved_sweep_spec.sweep_spec_id.hex),
                # Pass attempt id explicitly so queued_execution_attempt_nonce receives a
                # reviewable hex and sweep spec id input in dispatch.
                attempt_id,
                spec.spec_id,
            ),
        )
        outputs = (
            # Keep the sweep result component named inside the outputs contract.
            sweep_result.artifact,
            *(item.run_artifact for item in sweep_result.entries),
        )
        return sweep_result.artifact, outputs
    raise ChildEnvelopeError(f"{spec.job_type.value} has no installed child dispatcher")


# Define verify exact inputs as one focused operation with an explicit boundary.
def _verify_exact_inputs(
    artifacts: LocalArtifactRepository,
    artifact_ids: tuple[ArtifactId, ...],
) -> None:
    # Execute the verify exact inputs workflow in explicit, reviewable steps.
    for artifact_id in artifact_ids:
        # Process artifact_ids inside the bounded verify exact inputs loop.
        try:
            handle = artifacts.open_committed(artifact_id)
        except (FileNotFoundError, RuntimeError) as error:
            raise ChildExecutionError("a resolved input artifact is unavailable") from error
        handle.close()


# Define verify outputs as one focused operation with an explicit boundary.
def _verify_outputs(
    artifacts: LocalArtifactRepository,
    outputs: tuple[CommittedArtifact, ...],
) -> tuple[CommittedArtifact, ...]:
    # Execute the verify outputs workflow in explicit, reviewable steps.
    by_id: dict[str, CommittedArtifact] = {}
    for expected in outputs:
        # Process outputs inside the bounded verify outputs loop.
        previous = by_id.setdefault(expected.artifact_id.hex, expected)
        if previous != expected:
            raise ChildExecutionError("one output ID resolved to different descriptors")
    verified: list[CommittedArtifact] = []
    for artifact_id in sorted(by_id):
        # Process sorted(by_id) inside the bounded verify outputs loop.
        expected = by_id[artifact_id]
        try:
            # Perform the protected verify outputs operation before explicit failure
            # handling.
            handle = artifacts.open_committed(expected.artifact_id)
            try:
                actual = handle.descriptor
            finally:
                handle.close()
        # Translate file not found error through the verify outputs boundary without
        # hiding other errors.
        except (FileNotFoundError, RuntimeError) as error:
            raise ChildExecutionError("a child output failed committed verification") from error
        if actual != expected:
            raise ChildExecutionError("a child output descriptor changed after publication")
        verified.append(actual)
    # Guard this path with not verified before applying effects.
    if not verified:
        raise ChildExecutionError("a successful child job must publish an output artifact")
    return tuple(verified)


def _object(value: object, field: str) -> dict[str, object]:
    # Execute the object workflow in explicit, reviewable steps.
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ChildEnvelopeError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    # Execute the string workflow in explicit, reviewable steps.
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise ChildEnvelopeError(f"{field} must be a non-empty trimmed string")
    return value


def _positive_integer(value: object, field: str) -> int:
    # Execute the positive integer workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ChildEnvelopeError(f"{field} must be a positive integer")
    return value


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    # Execute the arguments workflow in explicit, reviewable steps.
    parser = argparse.ArgumentParser(prog="backtest-job-child", add_help=False)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--capabilities", type=Path)
    parser.add_argument("envelope", type=Path)
    try:
        # Return the completed arguments result without a hidden fallback.
        return parser.parse_args(argv)
    except SystemExit as error:
        raise ChildEnvelopeError("child invocation arguments are invalid") from error


def main(argv: list[str] | None = None) -> int:
    # Execute the main workflow in explicit, reviewable steps.
    try:
        # Perform the protected main operation before explicit failure handling.
        arguments = _arguments(argv)
        execute_envelope(
            arguments.envelope,
            config_path=arguments.config,
            capabilities_file=arguments.capabilities,
            # Complete execute_envelope only after its envelope and config inputs are visible
            # in main.
        )
    except (ChildEnvelopeError, ChildExecutionError, ConfigError, FileNotFoundError, ValueError):
        # Translate the child envelope error, child execution error and config error
        # failure through the main boundary.
        sys.stderr.write("backtest job child rejected the resolved launch\n")
        return _USER_ERROR_EXIT
    except Exception:
        # Translate the Exception failure through the main boundary.
        sys.stderr.write("backtest job child failed before verified completion\n")
        return _INTERNAL_ERROR_EXIT
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# Bind all once as an explicit module-level contract.
__all__ = [
    "ChildEnvelopeError",
    "ChildExecutionError",
    "ChildExecutionResult",
    "LaunchEnvelope",
    # Keep the execute envelope component named inside the all contract.
    "execute_envelope",
    "load_launch_envelope",
    "main",
]
