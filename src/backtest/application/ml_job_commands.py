"""Canonical executable commands for immutable Phase-6 ML jobs.

The durable queue stores only these small resolved documents.  Builders obtain
large row streams from implementations pinned by the exact bundle/config IDs;
rows, filesystem paths, aliases and opaque executable mappings are deliberately
absent from the transport contract.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import ClassVar, cast

# Import ml artifacts at the visible module dependency boundary.
from backtest.application.ml_artifacts import (
    BuildFeatureSetRequest,
    BuildFrozenPredictionsRequest,
    BuildLabelSetRequest,
    BuildUniverseRequest,
    # Include feature overlay row so the ml artifacts dependency remains explicit.
    FeatureOverlayRow,
    FrozenMissingPolicy,
    LabelOverlayRow,
    PublishModelScheduleRequest,
    TrainExactLinearModelRequest,
    # Include universe membership row so the ml artifacts dependency remains explicit.
    UniverseMembershipRow,
    feature_spec_document,
    feature_spec_from_document,
    model_schedule_document,
    model_schedule_from_document,
    # Include training spec document so the ml artifacts dependency remains explicit.
    training_spec_document,
    training_spec_from_document,
)
from backtest.application.ml_contracts import FeatureSpec, ModelCanonicality
from backtest.application.models import JobType

# Import hashing at the visible module dependency boundary.
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import (
    ArtifactId,
    BundleId,
    ContentDigest,
    # Include feature set id so the identifiers dependency remains explicit.
    FeatureSetId,
    ModelBundleId,
    ModelScheduleId,
    ReplayPackId,
    SnapshotId,
    # Include universe id so the identifiers dependency remains explicit.
    UniverseId,
)

BUILD_FEATURES_JOB_SCHEMA = "backtest.build-features-job/v1"
BUILD_UNIVERSE_JOB_SCHEMA = "backtest.build-universe-job/v1"
BUILD_LABELS_JOB_SCHEMA = "backtest.build-labels-job/v1"
# Bind train model job schema once as an explicit module-level contract.
TRAIN_MODEL_JOB_SCHEMA = "backtest.train-model-job/v1"
BUILD_MODEL_SCHEDULE_JOB_SCHEMA = "backtest.build-model-schedule-job/v1"
PREDICT_JOB_SCHEMA = "backtest.predict-job/v1"


class MlJobCommandError(ValueError):
    """An ML job payload is unresolved, malformed or not canonical v1."""


@dataclass(frozen=True, slots=True)
class ResolvedMlJobCommand:
    """Canonical queue material plus its exact committed-artifact closure."""

    job_type: JobType
    canonical_payload: bytes
    input_artifact_ids: tuple[ArtifactId, ...]

    def __post_init__(self) -> None:
        # Execute the resolved ml job command post init workflow in explicit, reviewable
        # steps.
        if self.job_type not in ML_JOB_TYPES:
            raise MlJobCommandError("job type is not a Phase-6 ML job")
        if not isinstance(self.canonical_payload, bytes):
            raise MlJobCommandError("canonical ML job payload must be bytes")
        _require_sorted_unique(self.input_artifact_ids, "ML job input artifacts")


# Keep the resolved build features job contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ResolvedBuildFeaturesJob:
    replay_pack_id: ReplayPackId
    replay_semantics_id: ContentDigest
    replay_layout_schema_id: ContentDigest
    # Declare feature specs explicitly in the resolved build features job contract.
    feature_specs: tuple[FeatureSpec, ...]
    input_feature_set_ids: tuple[FeatureSetId, ...]
    compiler_version: str

    SCHEMA: ClassVar[str] = BUILD_FEATURES_JOB_SCHEMA
    JOB_TYPE: ClassVar[JobType] = JobType.BUILD_FEATURES

    # Define resolved build features job post init as one focused operation with an
    # explicit boundary.
    def __post_init__(self) -> None:
        # Execute the resolved build features job post init workflow in explicit,
        # reviewable steps.
        self.publication_request(())
        _strict_artifact_inputs((self.replay_pack_id, *self.input_feature_set_ids))

    @property
    def input_artifact_ids(self) -> tuple[ArtifactId, ...]:
        return _strict_artifact_inputs((self.replay_pack_id, *self.input_feature_set_ids))

    # Define resolved build features job publication request as one focused operation with
    # an explicit boundary.
    def publication_request(
        self,
        rows: Iterable[FeatureOverlayRow],
    ) -> BuildFeatureSetRequest:
        """Bind the bounded row stream produced by the pinned feature bundles."""

        return BuildFeatureSetRequest(
            replay_pack_id=self.replay_pack_id,
            replay_semantics_id=self.replay_semantics_id,
            replay_layout_schema_id=self.replay_layout_schema_id,
            feature_specs=self.feature_specs,
            # Pass input feature set ids explicitly so BuildFeatureSetRequest receives a
            # reviewable replay pack id and replay semantics id input in resolved build
            # features job publication request.
            input_feature_set_ids=self.input_feature_set_ids,
            rows=rows,
            compiler_version=self.compiler_version,
        )

    def document(self) -> dict[str, object]:
        # Execute the resolved build features job document workflow in explicit,
        # reviewable steps.
        return {
            "compiler_version": self.compiler_version,
            "feature_specs": [feature_spec_document(item) for item in self.feature_specs],
            "input_feature_set_ids": [item.hex for item in self.input_feature_set_ids],
            "replay_layout_schema_id": self.replay_layout_schema_id.hex,
            # Include replay pack id in the completed resolved build features job document
            # result.
            "replay_pack_id": self.replay_pack_id.hex,
            "replay_semantics_id": self.replay_semantics_id.hex,
            "schema": self.SCHEMA,
        }

    def canonical_bytes(self) -> bytes:
        # Return the completed resolved build features job canonical bytes result without
        # a hidden fallback.
        return canonical_json_bytes(self.document())


# Keep the resolved build universe job contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ResolvedBuildUniverseJob:
    snapshot_id: SnapshotId
    universe_spec_id: ContentDigest
    input_feature_set_ids: tuple[FeatureSetId, ...]
    # Declare builder bundle id explicitly in the resolved build universe job contract.
    builder_bundle_id: BundleId
    builder_config_digest: ContentDigest
    compiler_version: str

    SCHEMA: ClassVar[str] = BUILD_UNIVERSE_JOB_SCHEMA
    JOB_TYPE: ClassVar[JobType] = JobType.BUILD_UNIVERSE

    # Define resolved build universe job post init as one focused operation with an
    # explicit boundary.
    def __post_init__(self) -> None:
        # Execute the resolved build universe job post init workflow in explicit,
        # reviewable steps.
        self.publication_request(())
        _strict_artifact_inputs((self.snapshot_id, *self.input_feature_set_ids))

    @property
    def input_artifact_ids(self) -> tuple[ArtifactId, ...]:
        return _strict_artifact_inputs((self.snapshot_id, *self.input_feature_set_ids))

    # Define resolved build universe job publication request as one focused operation with
    # an explicit boundary.
    def publication_request(
        self,
        rows: Iterable[UniverseMembershipRow],
    ) -> BuildUniverseRequest:
        """Bind memberships emitted by the exact universe builder bundle."""

        return BuildUniverseRequest(
            snapshot_id=self.snapshot_id,
            universe_spec_id=self.universe_spec_id,
            input_feature_set_ids=self.input_feature_set_ids,
            builder_bundle_id=self.builder_bundle_id,
            # Pass builder config digest explicitly so BuildUniverseRequest receives a
            # reviewable snapshot id and universe spec id input in resolved build universe
            # job publication request.
            builder_config_digest=self.builder_config_digest,
            rows=rows,
            compiler_version=self.compiler_version,
        )

    def document(self) -> dict[str, object]:
        # Execute the resolved build universe job document workflow in explicit,
        # reviewable steps.
        return {
            "builder_bundle_id": self.builder_bundle_id.hex,
            "builder_config_digest": self.builder_config_digest.hex,
            "compiler_version": self.compiler_version,
            "input_feature_set_ids": [item.hex for item in self.input_feature_set_ids],
            # Include schema in the completed resolved build universe job document result.
            "schema": self.SCHEMA,
            "snapshot_id": self.snapshot_id.hex,
            "universe_spec_id": self.universe_spec_id.hex,
        }

    def canonical_bytes(self) -> bytes:
        # Return the completed resolved build universe job canonical bytes result without
        # a hidden fallback.
        return canonical_json_bytes(self.document())


# Keep the resolved build labels job contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ResolvedBuildLabelsJob:
    snapshot_id: SnapshotId
    universe_id: UniverseId
    label_spec_id: ContentDigest
    # Declare label builder bundle id explicitly in the resolved build labels job
    # contract.
    label_builder_bundle_id: BundleId
    label_config_digest: ContentDigest
    training_cutoff: int
    compiler_version: str

    SCHEMA: ClassVar[str] = BUILD_LABELS_JOB_SCHEMA
    # Declare job type explicitly in the resolved build labels job contract.
    JOB_TYPE: ClassVar[JobType] = JobType.BUILD_LABELS

    def __post_init__(self) -> None:
        # Execute the resolved build labels job post init workflow in explicit, reviewable
        # steps.
        self.publication_request(())
        _strict_artifact_inputs((self.snapshot_id, self.universe_id))

    @property
    def input_artifact_ids(self) -> tuple[ArtifactId, ...]:
        return _strict_artifact_inputs((self.snapshot_id, self.universe_id))

    # Define resolved build labels job publication request as one focused operation with
    # an explicit boundary.
    def publication_request(self, rows: Iterable[LabelOverlayRow]) -> BuildLabelSetRequest:
        """Bind labels emitted only inside the training-side builder boundary."""

        return BuildLabelSetRequest(
            snapshot_id=self.snapshot_id,
            universe_id=self.universe_id,
            label_spec_id=self.label_spec_id,
            label_builder_bundle_id=self.label_builder_bundle_id,
            # Pass label config digest explicitly so BuildLabelSetRequest receives a
            # reviewable snapshot id and universe id input in resolved build labels job
            # publication request.
            label_config_digest=self.label_config_digest,
            training_cutoff=self.training_cutoff,
            rows=rows,
            compiler_version=self.compiler_version,
        )

    # Define resolved build labels job document as one focused operation with an explicit
    # boundary.
    def document(self) -> dict[str, object]:
        # Execute the resolved build labels job document workflow in explicit, reviewable
        # steps.
        return {
            "compiler_version": self.compiler_version,
            "label_builder_bundle_id": self.label_builder_bundle_id.hex,
            "label_config_digest": self.label_config_digest.hex,
            "label_spec_id": self.label_spec_id.hex,
            # Include schema in the completed resolved build labels job document result.
            "schema": self.SCHEMA,
            "snapshot_id": self.snapshot_id.hex,
            "training_cutoff": self.training_cutoff,
            "universe_id": self.universe_id.hex,
        }

    # Define resolved build labels job canonical bytes as one focused operation with an
    # explicit boundary.
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.document())


# Keep the resolved train model job contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ResolvedTrainModelJob:
    request: TrainExactLinearModelRequest

    SCHEMA: ClassVar[str] = TRAIN_MODEL_JOB_SCHEMA
    JOB_TYPE: ClassVar[JobType] = JobType.TRAIN_MODEL

    # Define resolved train model job post init as one focused operation with an explicit
    # boundary.
    def __post_init__(self) -> None:
        _ = self.input_artifact_ids

    @property
    def input_artifact_ids(self) -> tuple[ArtifactId, ...]:
        # Execute the resolved train model job input artifact ids workflow in explicit,
        # reviewable steps.
        spec = self.request.training_spec
        return _strict_artifact_inputs((*spec.feature_set_ids, spec.label_set_id, spec.universe_id))

    def document(self) -> dict[str, object]:
        # Execute the resolved train model job document workflow in explicit, reviewable
        # steps.
        return {
            "calibration_digest": self.request.calibration_digest.hex,
            "canonicality": self.request.canonicality.value,
            "compiler_version": self.request.compiler_version,
            "feature_schema_digest": self.request.feature_schema_digest.hex,
            # Include framework in the completed resolved train model job document result.
            "framework": self.request.framework,
            "preprocessing_digest": self.request.preprocessing_digest.hex,
            "ridge_lambda": self.request.ridge_lambda,
            "schema": self.SCHEMA,
            "training_spec": training_spec_document(self.request.training_spec),
            # Return the completed resolved train model job document result without a hidden
            # fallback.
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.document())


# Keep the resolved build model schedule job contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ResolvedBuildModelScheduleJob:
    request: PublishModelScheduleRequest

    SCHEMA: ClassVar[str] = BUILD_MODEL_SCHEDULE_JOB_SCHEMA
    JOB_TYPE: ClassVar[JobType] = JobType.BUILD_MODEL_SCHEDULE

    # Apply property semantics to the following resolved build model schedule job input
    # artifact ids contract.
    @property
    def input_artifact_ids(self) -> tuple[ArtifactId, ...]:
        # Execute the resolved build model schedule job input artifact ids workflow in
        # explicit, reviewable steps.
        values = {entry.model_bundle_id for entry in self.request.schedule.entries}
        fallback = self.request.schedule.fallback_model_bundle_id
        if fallback is not None:
            values.add(fallback)
        return tuple(ArtifactId(item.hex) for item in sorted(values, key=lambda item: item.hex))

    # Define resolved build model schedule job document as one focused operation with an
    # explicit boundary.
    def document(self) -> dict[str, object]:
        # Execute the resolved build model schedule job document workflow in explicit,
        # reviewable steps.
        return {
            "canonicality": self.request.canonicality.value,
            "compiler_version": self.request.compiler_version,
            "schedule": model_schedule_document(self.request.schedule),
            "schema": self.SCHEMA,
            # Return the completed resolved build model schedule job document result without a
            # hidden fallback.
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.document())


# Keep the resolved predict job contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ResolvedPredictJob:
    request: BuildFrozenPredictionsRequest

    SCHEMA: ClassVar[str] = PREDICT_JOB_SCHEMA
    JOB_TYPE: ClassVar[JobType] = JobType.PREDICT

    # Define resolved predict job post init as one focused operation with an explicit
    # boundary.
    def __post_init__(self) -> None:
        _ = self.input_artifact_ids

    @property
    def input_artifact_ids(self) -> tuple[ArtifactId, ...]:
        # Execute the resolved predict job input artifact ids workflow in explicit,
        # reviewable steps.
        return _strict_artifact_inputs(
            (
                self.request.replay_pack_id,
                *self.request.feature_set_ids,
                self.request.model_schedule_id,
                # Pass self explicitly so _strict_artifact_inputs receives a reviewable
                # replay pack id and model schedule id input in resolved predict job input
                # artifact ids.
                *self.request.model_bundle_ids,
            )
        )

    def document(self) -> dict[str, object]:
        # Execute the resolved predict job document workflow in explicit, reviewable
        # steps.
        return {
            "canonicality": self.request.canonicality.value,
            "compiler_version": self.request.compiler_version,
            "feature_set_ids": [item.hex for item in self.request.feature_set_ids],
            "inference_delay_boundaries": self.request.inference_delay_boundaries,
            # Include missing policy in the completed resolved predict job document
            # result.
            "missing_policy": self.request.missing_policy.value,
            "model_bundle_ids": [item.hex for item in self.request.model_bundle_ids],
            "model_schedule_id": self.request.model_schedule_id.hex,
            "prediction_name": self.request.prediction_name,
            "replay_layout_schema_id": self.request.replay_layout_schema_id.hex,
            # Include replay pack id in the completed resolved predict job document
            # result.
            "replay_pack_id": self.request.replay_pack_id.hex,
            "replay_semantics_id": self.request.replay_semantics_id.hex,
            "schema": self.SCHEMA,
        }

    def canonical_bytes(self) -> bytes:
        # Return the completed resolved predict job canonical bytes result without a
        # hidden fallback.
        return canonical_json_bytes(self.document())


MlResolvedJob = (
    ResolvedBuildFeaturesJob
    | ResolvedBuildUniverseJob
    | ResolvedBuildLabelsJob
    # Keep the resolved train model job component named inside the ml resolved job
    # contract.
    | ResolvedTrainModelJob
    | ResolvedBuildModelScheduleJob
    | ResolvedPredictJob
)

ML_JOB_TYPES = frozenset(
    # Open the build features and build universe payload explicitly for frozenset within
    # module.
    {
        JobType.BUILD_FEATURES,
        JobType.BUILD_UNIVERSE,
        JobType.BUILD_LABELS,
        JobType.TRAIN_MODEL,
        # Pass job type explicitly so frozenset receives a reviewable build features and
        # build universe input in module.
        JobType.BUILD_MODEL_SCHEDULE,
        JobType.PREDICT,
    }
)


def resolve_ml_job_command(job_type: JobType, payload: bytes) -> ResolvedMlJobCommand:
    """Decode one ML command and derive its artifact closure from typed fields."""

    decoder = _DECODERS.get(job_type)
    if decoder is None:
        raise MlJobCommandError(f"{job_type.value} has no Phase-6 ML payload contract")
    document = _canonical_object(payload)
    try:
        # Assemble command once so the resolve ml job command workflow shares one value.
        command = decoder(document)
    except (KeyError, TypeError, ValueError) as error:
        # Translate the (KeyError, TypeError, ValueError) failure through the resolve ml
        # job command boundary.
        if isinstance(error, MlJobCommandError):
            raise
        raise MlJobCommandError("resolved ML job payload is invalid") from error
    normalized = command.canonical_bytes()
    if payload != normalized:
        # Fail the resolve ml job command path with MlJobCommandError for resolved ml job
        # payload is not in exact canonical form when payload and normalized is true; do
        # not continue ambiguously.
        raise MlJobCommandError("resolved ML job payload is not in exact canonical form")
    return ResolvedMlJobCommand(job_type, normalized, command.input_artifact_ids)


def resolved_build_features_job_from_bytes(payload: bytes) -> ResolvedBuildFeaturesJob:
    return _typed_from_bytes(payload, _build_features_from_document)


def resolved_build_universe_job_from_bytes(payload: bytes) -> ResolvedBuildUniverseJob:
    # Return the completed resolved build universe job from bytes result without a hidden
    # fallback.
    return _typed_from_bytes(payload, _build_universe_from_document)


def resolved_build_labels_job_from_bytes(payload: bytes) -> ResolvedBuildLabelsJob:
    return _typed_from_bytes(payload, _build_labels_from_document)


def resolved_train_model_job_from_bytes(payload: bytes) -> ResolvedTrainModelJob:
    return _typed_from_bytes(payload, _train_model_from_document)


# Define resolved build model schedule job from bytes as one focused operation with an
# explicit boundary.
def resolved_build_model_schedule_job_from_bytes(
    payload: bytes,
) -> ResolvedBuildModelScheduleJob:
    return _typed_from_bytes(payload, _build_model_schedule_from_document)


def resolved_predict_job_from_bytes(payload: bytes) -> ResolvedPredictJob:
    # Return the completed resolved predict job from bytes result without a hidden
    # fallback.
    return _typed_from_bytes(payload, _predict_from_document)


def _typed_from_bytes[T: MlResolvedJob](
    payload: bytes,
    decoder: Callable[[dict[str, object]], T],
) -> T:
    # Execute the typed from bytes workflow in explicit, reviewable steps.
    document = _canonical_object(payload)
    try:
        result = decoder(document)
    except (KeyError, TypeError, ValueError) as error:
        # Translate the (KeyError, TypeError, ValueError) failure through the typed from
        # bytes boundary.
        if isinstance(error, MlJobCommandError):
            raise
        raise MlJobCommandError("resolved ML job payload is invalid") from error
    if payload != result.canonical_bytes():
        raise MlJobCommandError("resolved ML job payload is not in exact canonical form")
    # Return the completed typed from bytes result without a hidden fallback.
    return result


def _build_features_from_document(document: dict[str, object]) -> ResolvedBuildFeaturesJob:
    # Execute the build features from document workflow in explicit, reviewable steps.
    _exact_keys(
        document,
        {
            "compiler_version",
            "feature_specs",
            # Pass input feature set ids explicitly so _exact_keys receives a reviewable
            # compiler version and feature specs input in build features from document.
            "input_feature_set_ids",
            "replay_layout_schema_id",
            "replay_pack_id",
            "replay_semantics_id",
            "schema",
            # Close the compiler version and feature specs payload only after all build
            # features from document fields are present.
        },
    )
    _schema(document, BUILD_FEATURES_JOB_SCHEMA)
    return ResolvedBuildFeaturesJob(
        replay_pack_id=ReplayPackId(_string(document["replay_pack_id"], "replay_pack_id")),
        # Include replay semantics id in the completed build features from document
        # result.
        replay_semantics_id=ContentDigest(
            _string(document["replay_semantics_id"], "replay_semantics_id")
        ),
        replay_layout_schema_id=ContentDigest(
            _string(document["replay_layout_schema_id"], "replay_layout_schema_id")
            # Complete ContentDigest only after its replay layout schema id and string inputs
            # are visible in build features from document.
        ),
        feature_specs=tuple(
            feature_spec_from_document(item)
            for item in _array(document["feature_specs"], "feature_specs")
        ),
        # Include input feature set ids in the completed build features from document
        # result.
        input_feature_set_ids=tuple(
            FeatureSetId(_string(item, "input_feature_set_id"))
            for item in _array(document["input_feature_set_ids"], "input_feature_set_ids")
        ),
        compiler_version=_string(document["compiler_version"], "compiler_version"),
        # Complete ResolvedBuildFeaturesJob only after its replay pack id and replay semantics
        # id inputs are visible in build features from document.
    )


def _build_universe_from_document(document: dict[str, object]) -> ResolvedBuildUniverseJob:
    # Execute the build universe from document workflow in explicit, reviewable steps.
    _exact_keys(
        document,
        {
            "builder_bundle_id",
            "builder_config_digest",
            # Pass compiler version explicitly so _exact_keys receives a reviewable
            # builder bundle id and builder config digest input in build universe from
            # document.
            "compiler_version",
            "input_feature_set_ids",
            "schema",
            "snapshot_id",
            "universe_spec_id",
            # Close the builder bundle id and builder config digest payload only after all
            # build universe from document fields are present.
        },
    )
    _schema(document, BUILD_UNIVERSE_JOB_SCHEMA)
    return ResolvedBuildUniverseJob(
        snapshot_id=SnapshotId(_string(document["snapshot_id"], "snapshot_id")),
        # Include universe spec id in the completed build universe from document result.
        universe_spec_id=ContentDigest(_string(document["universe_spec_id"], "universe_spec_id")),
        input_feature_set_ids=tuple(
            FeatureSetId(_string(item, "input_feature_set_id"))
            for item in _array(document["input_feature_set_ids"], "input_feature_set_ids")
        ),
        # Include builder bundle id in the completed build universe from document result.
        builder_bundle_id=BundleId(_string(document["builder_bundle_id"], "builder_bundle_id")),
        builder_config_digest=ContentDigest(
            _string(document["builder_config_digest"], "builder_config_digest")
        ),
        compiler_version=_string(document["compiler_version"], "compiler_version"),
        # Complete ResolvedBuildUniverseJob only after its snapshot id and universe spec id
        # inputs are visible in build universe from document.
    )


def _build_labels_from_document(document: dict[str, object]) -> ResolvedBuildLabelsJob:
    # Execute the build labels from document workflow in explicit, reviewable steps.
    _exact_keys(
        document,
        {
            "compiler_version",
            "label_builder_bundle_id",
            # Pass label config digest explicitly so _exact_keys receives a reviewable
            # compiler version and label builder bundle id input in build labels from
            # document.
            "label_config_digest",
            "label_spec_id",
            "schema",
            "snapshot_id",
            "training_cutoff",
            # Pass universe id explicitly so _exact_keys receives a reviewable compiler
            # version and label builder bundle id input in build labels from document.
            "universe_id",
        },
    )
    _schema(document, BUILD_LABELS_JOB_SCHEMA)
    return ResolvedBuildLabelsJob(
        # Include snapshot id in the completed build labels from document result.
        snapshot_id=SnapshotId(_string(document["snapshot_id"], "snapshot_id")),
        universe_id=UniverseId(_string(document["universe_id"], "universe_id")),
        label_spec_id=ContentDigest(_string(document["label_spec_id"], "label_spec_id")),
        label_builder_bundle_id=BundleId(
            _string(document["label_builder_bundle_id"], "label_builder_bundle_id")
            # Complete BundleId only after its label builder bundle id and string inputs are
            # visible in build labels from document.
        ),
        label_config_digest=ContentDigest(
            _string(document["label_config_digest"], "label_config_digest")
        ),
        training_cutoff=_integer(document["training_cutoff"], "training_cutoff"),
        # Include compiler version in the completed build labels from document result.
        compiler_version=_string(document["compiler_version"], "compiler_version"),
    )


def _train_model_from_document(document: dict[str, object]) -> ResolvedTrainModelJob:
    # Execute the train model from document workflow in explicit, reviewable steps.
    _exact_keys(
        document,
        {
            "calibration_digest",
            "canonicality",
            # Pass compiler version explicitly so _exact_keys receives a reviewable
            # calibration digest and canonicality input in train model from document.
            "compiler_version",
            "feature_schema_digest",
            "framework",
            "preprocessing_digest",
            "ridge_lambda",
            # Pass schema explicitly so _exact_keys receives a reviewable calibration
            # digest and canonicality input in train model from document.
            "schema",
            "training_spec",
        },
    )
    _schema(document, TRAIN_MODEL_JOB_SCHEMA)
    # Return the completed train model from document result without a hidden fallback.
    return ResolvedTrainModelJob(
        TrainExactLinearModelRequest(
            training_spec=training_spec_from_document(document["training_spec"]),
            feature_schema_digest=ContentDigest(
                _string(document["feature_schema_digest"], "feature_schema_digest")
                # Complete ContentDigest only after its feature schema digest and string
                # inputs are visible in train model from document.
            ),
            preprocessing_digest=ContentDigest(
                _string(document["preprocessing_digest"], "preprocessing_digest")
            ),
            calibration_digest=ContentDigest(
                # Include string in the completed train model from document result.
                _string(document["calibration_digest"], "calibration_digest")
            ),
            ridge_lambda=_integer(document["ridge_lambda"], "ridge_lambda"),
            framework=_string(document["framework"], "framework"),
            canonicality=_canonicality(document["canonicality"]),
            # Include compiler version in the completed train model from document result.
            compiler_version=_string(document["compiler_version"], "compiler_version"),
        )
    )


def _build_model_schedule_from_document(
    document: dict[str, object],
    # Keep the resolved build model schedule job input explicit in the build model schedule
    # from document contract.
) -> ResolvedBuildModelScheduleJob:
    # Execute the build model schedule from document workflow in explicit, reviewable
    # steps.
    _exact_keys(document, {"canonicality", "compiler_version", "schedule", "schema"})
    _schema(document, BUILD_MODEL_SCHEDULE_JOB_SCHEMA)
    return ResolvedBuildModelScheduleJob(
        PublishModelScheduleRequest(
            schedule=model_schedule_from_document(document["schedule"]),
            # Include canonicality in the completed build model schedule from document
            # result.
            canonicality=_canonicality(document["canonicality"]),
            compiler_version=_string(document["compiler_version"], "compiler_version"),
        )
    )


def _predict_from_document(document: dict[str, object]) -> ResolvedPredictJob:
    # Execute the predict from document workflow in explicit, reviewable steps.
    _exact_keys(
        document,
        {
            "canonicality",
            "compiler_version",
            # Pass feature set ids explicitly so _exact_keys receives a reviewable
            # canonicality and compiler version input in predict from document.
            "feature_set_ids",
            "inference_delay_boundaries",
            "missing_policy",
            "model_bundle_ids",
            "model_schedule_id",
            # Pass prediction name explicitly so _exact_keys receives a reviewable
            # canonicality and compiler version input in predict from document.
            "prediction_name",
            "replay_layout_schema_id",
            "replay_pack_id",
            "replay_semantics_id",
            "schema",
            # Close the canonicality and compiler version payload only after all predict from
            # document fields are present.
        },
    )
    _schema(document, PREDICT_JOB_SCHEMA)
    try:
        missing_policy = FrozenMissingPolicy(_string(document["missing_policy"], "missing_policy"))
    # Translate value error through the predict from document boundary without hiding
    # other errors.
    except ValueError as error:
        raise MlJobCommandError("unsupported frozen missing policy") from error
    return ResolvedPredictJob(
        BuildFrozenPredictionsRequest(
            replay_pack_id=ReplayPackId(_string(document["replay_pack_id"], "replay_pack_id")),
            # Include replay semantics id in the completed predict from document result.
            replay_semantics_id=ContentDigest(
                _string(document["replay_semantics_id"], "replay_semantics_id")
            ),
            replay_layout_schema_id=ContentDigest(
                _string(document["replay_layout_schema_id"], "replay_layout_schema_id")
                # Complete ContentDigest only after its replay layout schema id and string
                # inputs are visible in predict from document.
            ),
            feature_set_ids=tuple(
                FeatureSetId(_string(item, "feature_set_id"))
                for item in _array(document["feature_set_ids"], "feature_set_ids")
            ),
            # Include model schedule id in the completed predict from document result.
            model_schedule_id=ModelScheduleId(
                _string(document["model_schedule_id"], "model_schedule_id")
            ),
            model_bundle_ids=tuple(
                ModelBundleId(_string(item, "model_bundle_id"))
                # Include item in the completed predict from document result.
                for item in _array(document["model_bundle_ids"], "model_bundle_ids")
            ),
            prediction_name=_string(document["prediction_name"], "prediction_name"),
            inference_delay_boundaries=_integer(
                document["inference_delay_boundaries"],
                # Pass inference delay boundaries explicitly so _integer receives a
                # reviewable inference delay boundaries and document input in predict from
                # document.
                "inference_delay_boundaries",
                # Complete _integer only after its inference delay boundaries and document
                # inputs are visible in predict from document.
            ),
            missing_policy=missing_policy,
            canonicality=_canonicality(document["canonicality"]),
            compiler_version=_string(document["compiler_version"], "compiler_version"),
        )
        # Complete ResolvedPredictJob only after its prediction name and inference delay
        # boundaries inputs are visible in predict from document.
    )


def _canonical_object(payload: bytes) -> dict[str, object]:
    # Execute the canonical object workflow in explicit, reviewable steps.
    if not isinstance(payload, bytes):
        raise MlJobCommandError("ML job payload must be bytes")
    try:
        # Perform the protected canonical object operation before explicit failure
        # handling.
        value = json.loads(payload)
        canonical = canonical_json_bytes(value)
    except (TypeError, UnicodeDecodeError, ValueError) as error:
        raise MlJobCommandError("ML job payload must be canonical JSON") from error
    if canonical != payload:
        # Fail the canonical object path with MlJobCommandError for ml job payload must
        # use exact canonical json bytes when canonical and payload is true; do not
        # continue ambiguously.
        raise MlJobCommandError("ML job payload must use exact canonical JSON bytes")
    return _object(value, "ML job payload")


def _object(value: object, field: str) -> dict[str, object]:
    # Execute the object workflow in explicit, reviewable steps.
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise MlJobCommandError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _array(value: object, field: str) -> list[object]:
    # Execute the array workflow in explicit, reviewable steps.
    if not isinstance(value, list):
        raise MlJobCommandError(f"{field} must be an array")
    return cast(list[object], value)


def _exact_keys(document: dict[str, object], expected: set[str]) -> None:
    # Execute the exact keys workflow in explicit, reviewable steps.
    if set(document) != expected:
        raise MlJobCommandError("resolved ML job payload schema is invalid")


def _schema(document: dict[str, object], expected: str) -> None:
    # Execute the schema workflow in explicit, reviewable steps.
    if document["schema"] != expected:
        raise MlJobCommandError("unsupported ML job schema")


def _string(value: object, field: str) -> str:
    # Execute the string workflow in explicit, reviewable steps.
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise MlJobCommandError(f"{field} must be non-empty, trimmed and NUL-free")
    return value


def _integer(value: object, field: str) -> int:
    # Execute the integer workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MlJobCommandError(f"{field} must be a non-negative integer")
    return value


def _canonicality(value: object) -> ModelCanonicality:
    # Execute the canonicality workflow in explicit, reviewable steps.
    try:
        return ModelCanonicality(_string(value, "canonicality"))
    except ValueError as error:
        raise MlJobCommandError("unsupported model canonicality") from error


def _strict_artifact_inputs(values: tuple[ArtifactId, ...]) -> tuple[ArtifactId, ...]:
    # Execute the strict artifact inputs workflow in explicit, reviewable steps.
    result = tuple(sorted((ArtifactId(item.hex) for item in values), key=lambda item: item.hex))
    if len(result) != len({item.hex for item in result}):
        raise MlJobCommandError("ML exact input artifact IDs must be unique")
    return result


def _require_sorted_unique(values: tuple[ArtifactId, ...], field: str) -> None:
    # Execute the require sorted unique workflow in explicit, reviewable steps.
    if tuple(sorted(values, key=lambda item: item.hex)) != values:
        raise MlJobCommandError(f"{field} must be sorted")
    if len(values) != len({item.hex for item in values}):
        raise MlJobCommandError(f"{field} must be unique")


_DECODERS: dict[JobType, Callable[[dict[str, object]], MlResolvedJob]] = {
    # Keep the job type component named inside the decoders contract.
    JobType.BUILD_FEATURES: _build_features_from_document,
    JobType.BUILD_UNIVERSE: _build_universe_from_document,
    JobType.BUILD_LABELS: _build_labels_from_document,
    JobType.TRAIN_MODEL: _train_model_from_document,
    JobType.BUILD_MODEL_SCHEDULE: _build_model_schedule_from_document,
    # Keep the job type component named inside the decoders contract.
    JobType.PREDICT: _predict_from_document,
}


__all__ = [
    "BUILD_FEATURES_JOB_SCHEMA",
    "BUILD_LABELS_JOB_SCHEMA",
    # Keep the build model schedule job schema component named inside the all contract.
    "BUILD_MODEL_SCHEDULE_JOB_SCHEMA",
    "BUILD_UNIVERSE_JOB_SCHEMA",
    "ML_JOB_TYPES",
    "PREDICT_JOB_SCHEMA",
    "TRAIN_MODEL_JOB_SCHEMA",
    # Keep the ml job command error component named inside the all contract.
    "MlJobCommandError",
    "ResolvedBuildFeaturesJob",
    "ResolvedBuildLabelsJob",
    "ResolvedBuildModelScheduleJob",
    "ResolvedBuildUniverseJob",
    # Keep the resolved ml job command component named inside the all contract.
    "ResolvedMlJobCommand",
    "ResolvedPredictJob",
    "ResolvedTrainModelJob",
    "resolve_ml_job_command",
    "resolved_build_features_job_from_bytes",
    # Keep the resolved build labels job from bytes component named inside the all
    # contract.
    "resolved_build_labels_job_from_bytes",
    "resolved_build_model_schedule_job_from_bytes",
    "resolved_build_universe_job_from_bytes",
    "resolved_predict_job_from_bytes",
    "resolved_train_model_job_from_bytes",
    # Complete the all group only after its semantic components are visible.
]
