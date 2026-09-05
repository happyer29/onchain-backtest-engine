"""Strict executable payloads for the durable single-host job queue.

The queue never stores an unresolved alias or an opaque executable mapping.
Every accepted payload is decoded into an immutable application DTO, checked
against its exact artifact closure and encoded again as canonical JSON.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast

from backtest.application.dataset_plans import dataset_plan_bytes, dataset_plan_from_bytes

# Import ml job commands at the visible module dependency boundary.
from backtest.application.ml_job_commands import (
    ML_JOB_TYPES,
    resolve_ml_job_command,
)
from backtest.application.models import DatasetPlan, JobType

# Import run results at the visible module dependency boundary.
from backtest.application.run_results import RunPhysicalSettings
from backtest.application.run_specs import (
    ReplayInputFormat,
    ResolvedRunSpec,
    resolved_run_spec_from_bytes,
    # Close the run specs import after its required symbols are visible.
)
from backtest.application.sweeps import (
    ResolvedSweepSpec,
    resolved_sweep_spec_from_bytes,
)

# Import hashing at the visible module dependency boundary.
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import ArtifactId, ContentDigest, SnapshotId


class ResolvedJobCommandError(ValueError):
    """A queue payload is unresolved, malformed or inconsistent with its inputs."""


@dataclass(frozen=True, slots=True)
class ResolvedJobCommand:
    job_type: JobType
    canonical_payload: bytes
    input_artifact_ids: tuple[ArtifactId, ...]

    # Define resolved job command post init as one focused operation with an explicit
    # boundary.
    def __post_init__(self) -> None:
        # Execute the resolved job command post init workflow in explicit, reviewable
        # steps.
        ordered = tuple(sorted(self.input_artifact_ids, key=lambda item: item.hex))
        if ordered != self.input_artifact_ids or len(ordered) != len(set(ordered)):
            raise ResolvedJobCommandError("job input artifacts must be sorted and unique")


@dataclass(frozen=True, slots=True)
class PrepareDatasetJobDraft:
    """Public v1 request; controller resolution is required before queueing."""

    plan: DatasetPlan

    def document(self) -> dict[str, object]:
        # Execute the prepare dataset job draft document workflow in explicit, reviewable
        # steps.
        return {
            "plan": json.loads(dataset_plan_bytes(self.plan)),
            "schema": "backtest.prepare-dataset-job/v1",
        }

    def canonical_bytes(self) -> bytes:
        # Return the completed prepare dataset job draft canonical bytes result without a
        # hidden fallback.
        return canonical_json_bytes(self.document())


@dataclass(frozen=True, slots=True, order=True)
class ReusableCanonicalDistribution:
    """Exact committed distribution selected for one planned shard."""

    shard_ordinal: int
    artifact_id: ArtifactId

    def __post_init__(self) -> None:
        # Execute the reusable canonical distribution post init workflow in explicit,
        # reviewable steps.
        if isinstance(self.shard_ordinal, bool) or not isinstance(self.shard_ordinal, int):
            raise TypeError("reusable distribution shard ordinal must be an integer")
        if self.shard_ordinal < 0:
            raise ValueError("reusable distribution shard ordinal must be non-negative")


@dataclass(frozen=True, slots=True)
# Keep the resolved prepare dataset job contract and validation rules together.
class ResolvedPrepareDatasetJob:
    """Executable v2 command with an explicit immutable reuse selection."""

    plan: DatasetPlan
    reusable_distributions: tuple[ReusableCanonicalDistribution, ...] = ()

    def __post_init__(self) -> None:
        # Execute the resolved prepare dataset job post init workflow in explicit,
        # reviewable steps.
        ordered = tuple(sorted(self.reusable_distributions, key=lambda item: item.shard_ordinal))
        if ordered != self.reusable_distributions:
            # Handle the resolved prepare dataset job post init ordered !=
            # self.reusable_distributions branch as a distinct logical block.
            raise ResolvedJobCommandError(
                "reusable distributions must be sorted by planned shard ordinal"
            )
        ordinals = tuple(item.shard_ordinal for item in ordered)
        artifact_ids = tuple(item.artifact_id for item in ordered)
        # Evaluate the complete resolved prepare dataset job post init ordinals and
        # artifact ids condition before guarded effects.
        if len(ordinals) != len(set(ordinals)) or len(artifact_ids) != len(set(artifact_ids)):
            raise ResolvedJobCommandError("reusable distributions must be one-to-one")
        if any(ordinal >= len(self.plan.spec.shards) for ordinal in ordinals):
            raise ResolvedJobCommandError("reusable distribution references an unknown shard")

    def document(self) -> dict[str, object]:
        # Execute the resolved prepare dataset job document workflow in explicit,
        # reviewable steps.
        return {
            "plan": json.loads(dataset_plan_bytes(self.plan)),
            "reusable_distributions": [
                {
                    "artifact_id": item.artifact_id.hex,
                    # Include shard ordinal in the completed resolved prepare dataset job
                    # document result.
                    "shard_ordinal": item.shard_ordinal,
                }
                for item in self.reusable_distributions
            ],
            "schema": "backtest.prepare-dataset-job/v2",
            # Return the completed resolved prepare dataset job document result without a
            # hidden fallback.
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.document())


# Keep the resolved backtest job contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ResolvedBacktestJob:
    resolved_spec: ResolvedRunSpec
    attempt_nonce: ContentDigest
    physical_settings: RunPhysicalSettings

    # Define resolved backtest job document as one focused operation with an explicit
    # boundary.
    def document(self) -> dict[str, object]:
        # Execute the resolved backtest job document workflow in explicit, reviewable
        # steps.
        return {
            "attempt_nonce": self.attempt_nonce.hex,
            "physical_settings": self.physical_settings.document(),
            "resolved_run_spec": self.resolved_spec.document(),
            "schema": "backtest.run-job/v2",
            # Return the completed resolved backtest job document result without a hidden
            # fallback.
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.document())


# Keep the resolved sweep job contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ResolvedSweepJob:
    resolved_sweep_spec: ResolvedSweepSpec

    def document(self) -> dict[str, object]:
        # Execute the resolved sweep job document workflow in explicit, reviewable steps.
        return {
            "resolved_sweep_spec": self.resolved_sweep_spec.document(),
            "schema": "backtest.sweep-job/v2",
        }

    def canonical_bytes(self) -> bytes:
        # Return the completed resolved sweep job canonical bytes result without a hidden
        # fallback.
        return canonical_json_bytes(self.document())


# Keep the resolved compile replay job contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ResolvedCompileReplayJob:
    snapshot_id: SnapshotId
    compiler_version: str = "numpy-mmap-v3"

    def __post_init__(self) -> None:
        # Invoke _trimmed for compiler version as a visible resolved compile replay job
        # post init step.
        _trimmed(self.compiler_version, "compiler_version")

    def document(self) -> dict[str, object]:
        # Execute the resolved compile replay job document workflow in explicit,
        # reviewable steps.
        return {
            "compiler_version": self.compiler_version,
            "schema": "backtest.compile-replay-job/v1",
            "snapshot_id": self.snapshot_id.hex,
        }

    # Define resolved compile replay job canonical bytes as one focused operation with an
    # explicit boundary.
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.document())


# Keep the resolved compile delivery schedule job contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ResolvedCompileDeliveryScheduleJob:
    resolved_spec: ResolvedRunSpec
    compiler_version: str = "numpy-delivery-mmap-v1"

    def __post_init__(self) -> None:
        # Execute the resolved compile delivery schedule job post init workflow in
        # explicit, reviewable steps.
        _trimmed(self.compiler_version, "compiler_version")
        replay = self.resolved_spec.replay_input
        if (
            replay.format is not ReplayInputFormat.REPLAY_PACK
            or replay.replay_pack_id is None
            # Keep replay visible while evaluating the format, replay pack and replay pack
            # id guard.
            or replay.replay_layout_schema_id is None
        ):
            raise ResolvedJobCommandError("delivery compilation requires an exact ReplayPack input")

    def document(self) -> dict[str, object]:
        # Execute the resolved compile delivery schedule job document workflow in
        # explicit, reviewable steps.
        return {
            "compiler_version": self.compiler_version,
            "resolved_run_spec": self.resolved_spec.document(),
            "schema": "backtest.compile-delivery-schedule-job/v1",
        }

    # Define resolved compile delivery schedule job canonical bytes as one focused
    # operation with an explicit boundary.
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.document())


def resolve_job_command(job_type: JobType, payload: bytes) -> ResolvedJobCommand:
    """Decode one exact supported command and derive its artifact closure.

    Unsupported job types fail closed.  They become queueable only together
    with their own strict parser and child dispatcher.
    """

    document, canonical = _canonical_object(payload)
    inputs: tuple[ArtifactId, ...]
    try:
        # Perform the protected resolve job command operation before explicit failure
        # handling.
        if job_type in ML_JOB_TYPES:
            # Handle the resolve job command job_type in ML_JOB_TYPES branch as a distinct
            # logical block.
            ml_command = resolve_ml_job_command(job_type, payload)
            normalized = ml_command.canonical_payload
            inputs = ml_command.input_artifact_ids
        # Handle the resolve job command complement of job_type in ML_JOB_TYPES
        # explicitly.
        elif job_type is JobType.PREPARE_DATASET:
            # Handle the resolve job command job_type is JobType.PREPARE_DATASET branch as
            # a distinct logical block.
            prepare_command = _prepare_from_document(document)
            normalized = prepare_command.canonical_bytes()
            inputs = prepare_input_artifact_ids(prepare_command)
        # Handle the resolve job command complement of job_type is JobType.PREPARE_DATASET
        # explicitly.
        elif job_type is JobType.RUN_BACKTEST:
            # Handle the resolve job command job_type is JobType.RUN_BACKTEST branch as a
            # distinct logical block.
            run_command = _backtest_from_document(document)
            normalized = run_command.canonical_bytes()
            inputs = run_input_artifact_ids(run_command.resolved_spec)
        # Handle the resolve job command complement of job_type is JobType.RUN_BACKTEST
        # explicitly.
        elif job_type is JobType.RUN_SWEEP:
            # Handle the resolve job command job_type is JobType.RUN_SWEEP branch as a
            # distinct logical block.
            sweep_command = _sweep_from_document(document)
            normalized = sweep_command.canonical_bytes()
            inputs = _sweep_input_artifact_ids(sweep_command.resolved_sweep_spec)
        # Handle the resolve job command complement of job_type is JobType.RUN_SWEEP
        # explicitly.
        elif job_type is JobType.COMPILE_REPLAY:
            # Handle the resolve job command job_type is JobType.COMPILE_REPLAY branch as
            # a distinct logical block.
            replay_command = _compile_replay_from_document(document)
            normalized = replay_command.canonical_bytes()
            inputs = (ArtifactId(replay_command.snapshot_id.hex),)
        # Handle the resolve job command complement of job_type is JobType.COMPILE_REPLAY
        # explicitly.
        elif job_type is JobType.COMPILE_DELIVERY_SCHEDULE:
            # Handle the resolve job command job type and compile delivery schedule
            # condition as a distinct block.
            delivery_command = _compile_delivery_from_document(document)
            normalized = delivery_command.canonical_bytes()
            replay_pack_id = delivery_command.resolved_spec.replay_input.replay_pack_id
            if replay_pack_id is None:  # __post_init__ proves this branch impossible
                raise AssertionError("resolved delivery command lost its ReplayPack")
            inputs = (ArtifactId(replay_pack_id.hex),)
        else:
            # Handle the resolve job command complement of job type and compile delivery
            # schedule explicitly.
            raise ResolvedJobCommandError(
                f"{job_type.value} has no executable resolved payload contract"
            )
    except (KeyError, TypeError, ValueError) as error:
        # Translate the (KeyError, TypeError, ValueError) failure through the resolve job
        # command boundary.
        if isinstance(error, ResolvedJobCommandError):
            raise
        raise ResolvedJobCommandError("resolved job payload is invalid") from error
    if canonical != normalized:
        raise ResolvedJobCommandError("resolved job payload is not in exact canonical form")
    # Return the completed resolve job command result without a hidden fallback.
    return ResolvedJobCommand(job_type, normalized, inputs)


def resolved_backtest_job_from_bytes(payload: bytes) -> ResolvedBacktestJob:
    # Execute the resolved backtest job from bytes workflow in explicit, reviewable steps.
    document, canonical = _canonical_object(payload)
    result = _backtest_from_document(document)
    if canonical != result.canonical_bytes():
        raise ResolvedJobCommandError("backtest job is not in exact canonical form")
    return result


# Define resolved prepare dataset job from bytes as one focused operation with an explicit
# boundary.
def resolved_prepare_dataset_job_from_bytes(payload: bytes) -> ResolvedPrepareDatasetJob:
    # Execute the resolved prepare dataset job from bytes workflow in explicit, reviewable
    # steps.
    document, canonical = _canonical_object(payload)
    result = _prepare_from_document(document)
    if canonical != result.canonical_bytes():
        raise ResolvedJobCommandError("prepare-dataset job is not in exact canonical form")
    return result


# Define prepare dataset job draft from bytes as one focused operation with an explicit
# boundary.
def prepare_dataset_job_draft_from_bytes(payload: bytes) -> PrepareDatasetJobDraft:
    # Execute the prepare dataset job draft from bytes workflow in explicit, reviewable
    # steps.
    document, canonical = _canonical_object(payload)
    result = _prepare_draft_from_document(document)
    if canonical != result.canonical_bytes():
        raise ResolvedJobCommandError("prepare-dataset draft is not in exact canonical form")
    return result


# Define resolved sweep job from bytes as one focused operation with an explicit boundary.
def resolved_sweep_job_from_bytes(payload: bytes) -> ResolvedSweepJob:
    # Execute the resolved sweep job from bytes workflow in explicit, reviewable steps.
    document, canonical = _canonical_object(payload)
    result = _sweep_from_document(document)
    if canonical != result.canonical_bytes():
        raise ResolvedJobCommandError("sweep job is not in exact canonical form")
    return result


# Define resolved compile replay job from bytes as one focused operation with an explicit
# boundary.
def resolved_compile_replay_job_from_bytes(payload: bytes) -> ResolvedCompileReplayJob:
    # Execute the resolved compile replay job from bytes workflow in explicit, reviewable
    # steps.
    document, canonical = _canonical_object(payload)
    result = _compile_replay_from_document(document)
    if canonical != result.canonical_bytes():
        raise ResolvedJobCommandError("compile-replay job is not in exact canonical form")
    return result


# Define resolved compile delivery job from bytes as one focused operation with an
# explicit boundary.
def resolved_compile_delivery_job_from_bytes(
    payload: bytes,
) -> ResolvedCompileDeliveryScheduleJob:
    # Execute the resolved compile delivery job from bytes workflow in explicit,
    # reviewable steps.
    document, canonical = _canonical_object(payload)
    result = _compile_delivery_from_document(document)
    if canonical != result.canonical_bytes():
        # Handle the resolved compile delivery job from bytes canonical !=
        # result.canonical_bytes() branch as a distinct logical block.
        raise ResolvedJobCommandError(
            "compile-delivery-schedule job is not in exact canonical form"
        )
    return result


def run_input_artifact_ids(spec: ResolvedRunSpec) -> tuple[ArtifactId, ...]:
    # Execute the run input artifact ids workflow in explicit, reviewable steps.
    values = [ArtifactId(spec.snapshot_id.hex)]
    if spec.replay_input.replay_pack_id is not None:
        values.append(ArtifactId(spec.replay_input.replay_pack_id.hex))
    if spec.delivery_schedule_id is not None:
        values.append(ArtifactId(spec.delivery_schedule_id.hex))
    # Guard this path with spec.model_schedule_id is not None before applying effects.
    if spec.model_schedule_id is not None:
        values.append(ArtifactId(spec.model_schedule_id.hex))
    values.extend(ArtifactId(item.hex) for item in spec.feature_set_ids)
    values.extend(ArtifactId(item.hex) for item in spec.prediction_set_ids)
    ordered = tuple(sorted(values, key=lambda item: item.hex))
    # Guard this path with len(ordered) != len(set(ordered)) before applying effects.
    if len(ordered) != len(set(ordered)):
        raise ResolvedJobCommandError("resolved run contains duplicate input artifacts")
    return ordered


def prepare_input_artifact_ids(
    command: ResolvedPrepareDatasetJob,
    # Keep the tuple input explicit in the prepare input artifact ids contract.
) -> tuple[ArtifactId, ...]:
    # Execute the prepare input artifact ids workflow in explicit, reviewable steps.
    values = {
        command.plan.spec.source_inspection_artifact_id,
        *(item.artifact_id for item in command.reusable_distributions),
    }
    return tuple(sorted(values, key=lambda item: item.hex))


# Define sweep input artifact ids as one focused operation with an explicit boundary.
def _sweep_input_artifact_ids(spec: ResolvedSweepSpec) -> tuple[ArtifactId, ...]:
    # Execute the sweep input artifact ids workflow in explicit, reviewable steps.
    values = {
        item for entry in spec.entries for item in run_input_artifact_ids(entry.resolved_spec)
    }
    return tuple(sorted(values, key=lambda item: item.hex))


def _backtest_from_document(document: dict[str, object]) -> ResolvedBacktestJob:
    # Execute the backtest from document workflow in explicit, reviewable steps.
    _exact_keys(
        document,
        {"attempt_nonce", "physical_settings", "resolved_run_spec", "schema"},
    )
    if document["schema"] != "backtest.run-job/v2":
        # Fail the backtest from document path with ResolvedJobCommandError for
        # unsupported backtest job schema when document and schema is true; do not
        # continue ambiguously.
        raise ResolvedJobCommandError("unsupported backtest job schema")
    spec = _nested_run_spec(document["resolved_run_spec"])
    settings = _physical_settings(document["physical_settings"])
    return ResolvedBacktestJob(
        spec,
        # Include content digest in the completed backtest from document result.
        ContentDigest(_string(document["attempt_nonce"], "attempt_nonce")),
        settings,
    )


def _prepare_from_document(document: dict[str, object]) -> ResolvedPrepareDatasetJob:
    # Execute the prepare from document workflow in explicit, reviewable steps.
    _exact_keys(document, {"plan", "reusable_distributions", "schema"})
    if document["schema"] != "backtest.prepare-dataset-job/v2":
        raise ResolvedJobCommandError("unsupported prepare-dataset job schema")
    return ResolvedPrepareDatasetJob(
        dataset_plan_from_bytes(canonical_json_bytes(_object(document["plan"], "plan"))),
        # Include tuple in the completed prepare from document result.
        tuple(
            _reusable_distribution(item)
            for item in _list(document["reusable_distributions"], "reusable_distributions")
        ),
    )


# Define prepare draft from document as one focused operation with an explicit boundary.
def _prepare_draft_from_document(document: dict[str, object]) -> PrepareDatasetJobDraft:
    # Execute the prepare draft from document workflow in explicit, reviewable steps.
    _exact_keys(document, {"plan", "schema"})
    if document["schema"] != "backtest.prepare-dataset-job/v1":
        raise ResolvedJobCommandError("unsupported prepare-dataset draft schema")
    return PrepareDatasetJobDraft(
        dataset_plan_from_bytes(canonical_json_bytes(_object(document["plan"], "plan")))
        # Complete PrepareDatasetJobDraft only after its plan and dataset plan from bytes
        # inputs are visible in prepare draft from document.
    )


def _reusable_distribution(value: object) -> ReusableCanonicalDistribution:
    # Execute the reusable distribution workflow in explicit, reviewable steps.
    document = _object(value, "reusable distribution")
    _exact_keys(document, {"artifact_id", "shard_ordinal"})
    return ReusableCanonicalDistribution(
        shard_ordinal=_non_negative_integer(document["shard_ordinal"], "shard_ordinal"),
        artifact_id=ArtifactId(_string(document["artifact_id"], "artifact_id")),
        # Complete ReusableCanonicalDistribution only after its shard ordinal and artifact id
        # inputs are visible in reusable distribution.
    )


def _sweep_from_document(document: dict[str, object]) -> ResolvedSweepJob:
    # Execute the sweep from document workflow in explicit, reviewable steps.
    _exact_keys(document, {"resolved_sweep_spec", "schema"})
    if document["schema"] != "backtest.sweep-job/v2":
        raise ResolvedJobCommandError("unsupported sweep job schema")
    nested = _object(document["resolved_sweep_spec"], "resolved_sweep_spec")
    return ResolvedSweepJob(resolved_sweep_spec_from_bytes(canonical_json_bytes(nested)))


# Define compile replay from document as one focused operation with an explicit boundary.
def _compile_replay_from_document(document: dict[str, object]) -> ResolvedCompileReplayJob:
    # Execute the compile replay from document workflow in explicit, reviewable steps.
    _exact_keys(document, {"compiler_version", "schema", "snapshot_id"})
    if document["schema"] != "backtest.compile-replay-job/v1":
        raise ResolvedJobCommandError("unsupported compile-replay job schema")
    return ResolvedCompileReplayJob(
        SnapshotId(_string(document["snapshot_id"], "snapshot_id")),
        # Include string in the completed compile replay from document result.
        _string(document["compiler_version"], "compiler_version"),
    )


def _compile_delivery_from_document(
    document: dict[str, object],
) -> ResolvedCompileDeliveryScheduleJob:
    # Execute the compile delivery from document workflow in explicit, reviewable steps.
    _exact_keys(document, {"compiler_version", "resolved_run_spec", "schema"})
    if document["schema"] != "backtest.compile-delivery-schedule-job/v1":
        raise ResolvedJobCommandError("unsupported delivery job schema")
    return ResolvedCompileDeliveryScheduleJob(
        _nested_run_spec(document["resolved_run_spec"]),
        # Include string in the completed compile delivery from document result.
        _string(document["compiler_version"], "compiler_version"),
    )


def _physical_settings(value: object) -> RunPhysicalSettings:
    # Execute the physical settings workflow in explicit, reviewable steps.
    try:
        return RunPhysicalSettings.from_document(value)
    except (TypeError, ValueError) as error:
        raise ResolvedJobCommandError(str(error)) from error


def _nested_run_spec(value: object) -> ResolvedRunSpec:
    # Return the completed nested run spec result without a hidden fallback.
    return resolved_run_spec_from_bytes(canonical_json_bytes(_object(value, "resolved_run_spec")))


def _canonical_object(payload: bytes) -> tuple[dict[str, object], bytes]:
    # Execute the canonical object workflow in explicit, reviewable steps.
    try:
        # Perform the protected canonical object operation before explicit failure
        # handling.
        value = json.loads(payload)
        canonical = canonical_json_bytes(value)
    except (TypeError, ValueError, UnicodeDecodeError) as error:
        raise ResolvedJobCommandError("job payload must be canonical JSON") from error
    return _object(value, "job payload"), canonical


# Define object as one focused operation with an explicit boundary.
def _object(value: object, field: str) -> dict[str, object]:
    # Execute the object workflow in explicit, reviewable steps.
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ResolvedJobCommandError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _list(value: object, field: str) -> list[object]:
    # Execute the list workflow in explicit, reviewable steps.
    if not isinstance(value, list):
        raise ResolvedJobCommandError(f"{field} must be a list")
    return cast(list[object], value)


def _exact_keys(document: dict[str, object], expected: set[str]) -> None:
    # Execute the exact keys workflow in explicit, reviewable steps.
    if set(document) != expected:
        raise ResolvedJobCommandError("resolved job payload schema is invalid")


def _string(value: object, field: str) -> str:
    # Execute the string workflow in explicit, reviewable steps.
    if not isinstance(value, str):
        raise ResolvedJobCommandError(f"{field} must be a string")
    return _trimmed(value, field)


def _trimmed(value: str, field: str) -> str:
    # Execute the trimmed workflow in explicit, reviewable steps.
    if not value or value != value.strip() or "\x00" in value:
        raise ResolvedJobCommandError(f"{field} must be non-empty, trimmed and NUL-free")
    return value


def _positive_integer(value: object, field: str) -> int:
    # Execute the positive integer workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ResolvedJobCommandError(f"{field} must be a positive integer")
    return value


def _non_negative_integer(value: object, field: str) -> int:
    # Execute the non negative integer workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ResolvedJobCommandError(f"{field} must be a non-negative integer")
    return value


__all__ = [
    "PrepareDatasetJobDraft",
    # Keep the resolved backtest job component named inside the all contract.
    "ResolvedBacktestJob",
    "ResolvedCompileDeliveryScheduleJob",
    "ResolvedCompileReplayJob",
    "ResolvedJobCommand",
    "ResolvedJobCommandError",
    # Keep the resolved prepare dataset job component named inside the all contract.
    "ResolvedPrepareDatasetJob",
    "ResolvedSweepJob",
    "ReusableCanonicalDistribution",
    "prepare_dataset_job_draft_from_bytes",
    "prepare_input_artifact_ids",
    # Keep the resolve job command component named inside the all contract.
    "resolve_job_command",
    "resolved_backtest_job_from_bytes",
    "resolved_compile_delivery_job_from_bytes",
    "resolved_compile_replay_job_from_bytes",
    "resolved_prepare_dataset_job_from_bytes",
    # Keep the resolved sweep job from bytes component named inside the all contract.
    "resolved_sweep_job_from_bytes",
    "run_input_artifact_ids",
]
