"""Strict Web/API forms for resolved Phase-6 ML jobs.

These DTOs expose only typed semantic fields and exact content IDs.  They do
not accept row payloads, arbitrary paths, aliases, import names or generic JSON
configuration.  Conversion terminates at the application command boundary.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backtest.application.ml_artifacts import (
    BuildFrozenPredictionsRequest,
    # Include frozen missing policy so the ml artifacts dependency remains explicit.
    FrozenMissingPolicy,
    PublishModelScheduleRequest,
    TrainExactLinearModelRequest,
)
from backtest.application.ml_contracts import (
    # Include feature spec so the ml contracts dependency remains explicit.
    FeatureSpec,
    ModelCanonicality,
    ModelSchedule,
    ModelScheduleEntry,
    NullPolicy,
    # Include temporal split so the ml contracts dependency remains explicit.
    TemporalSplit,
    TrainingJobSpec,
)
from backtest.application.ml_job_commands import (
    ResolvedBuildFeaturesJob,
    # Include resolved build labels job so the ml job commands dependency remains
    # explicit.
    ResolvedBuildLabelsJob,
    ResolvedBuildModelScheduleJob,
    ResolvedBuildUniverseJob,
    ResolvedPredictJob,
    ResolvedTrainModelJob,
    # Close the ml job commands import after its required symbols are visible.
)
from backtest.domain.identifiers import (
    BundleId,
    ContentDigest,
    FeatureSetId,
    # Include label set id so the identifiers dependency remains explicit.
    LabelSetId,
    ModelBundleId,
    ModelScheduleId,
    ReplayPackId,
    RuntimeLockId,
    # Include snapshot id so the identifiers dependency remains explicit.
    SnapshotId,
    UniverseId,
)

DigestText = Annotated[
    str,
    # Keep the field Field step visible while building digest text.
    Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
        description="Exact lowercase SHA-256 content ID without an alias or path",
        # Complete Field only after its ^[0-9a-f]{64}$ and exact lowercase sha-256 content id
        # without an alias or path inputs are visible in module.
    ),
]
TokenText = Annotated[str, Field(min_length=1, max_length=256)]


class MlApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


# Keep the feature spec form contract and validation rules together.
class FeatureSpecForm(MlApiModel):
    name: TokenText
    version: int = Field(gt=0)
    entity_key: TokenText
    input_ids: tuple[DigestText, ...] = ()
    # Declare effective time semantics explicitly in the feature spec form contract.
    effective_time_semantics: TokenText
    available_time_semantics: TokenText
    warmup_boundaries: int = Field(ge=0)
    dtype: TokenText
    null_policy: NullPolicy
    # Declare code bundle id explicitly in the feature spec form contract.
    code_bundle_id: DigestText
    runtime_lock_id: DigestText

    @field_validator("input_ids")
    @classmethod
    def validate_input_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        # Return the completed feature spec form validate input ids result without a
        # hidden fallback.
        return _ordered_unique(values, "feature input_ids")

    @model_validator(mode="after")
    def validate_domain_contract(self) -> Self:
        # Execute the feature spec form validate domain contract workflow in explicit,
        # reviewable steps.
        self.to_domain()
        return self

    def to_domain(self) -> FeatureSpec:
        # Execute the feature spec form to domain workflow in explicit, reviewable steps.
        return FeatureSpec(
            name=self.name,
            version=self.version,
            entity_key=self.entity_key,
            input_ids=tuple(ContentDigest(item) for item in self.input_ids),
            # Pass effective time semantics explicitly so FeatureSpec receives a
            # reviewable name and version input in feature spec form to domain.
            effective_time_semantics=self.effective_time_semantics,
            available_time_semantics=self.available_time_semantics,
            warmup_boundaries=self.warmup_boundaries,
            dtype=self.dtype,
            null_policy=self.null_policy,
            # Include code bundle id in the completed feature spec form to domain result.
            code_bundle_id=BundleId(self.code_bundle_id),
            runtime_lock_id=RuntimeLockId(self.runtime_lock_id),
        )

    @classmethod
    def from_domain(cls, value: FeatureSpec) -> Self:
        # Execute the feature spec form from domain workflow in explicit, reviewable
        # steps.
        return cls(
            name=value.name,
            version=value.version,
            entity_key=value.entity_key,
            input_ids=tuple(item.hex for item in value.input_ids),
            # Pass effective time semantics explicitly so cls receives a reviewable name
            # and version input in feature spec form from domain.
            effective_time_semantics=value.effective_time_semantics,
            available_time_semantics=value.available_time_semantics,
            warmup_boundaries=value.warmup_boundaries,
            dtype=value.dtype,
            null_policy=value.null_policy,
            # Pass code bundle id explicitly so cls receives a reviewable name and version
            # input in feature spec form from domain.
            code_bundle_id=value.code_bundle_id.hex,
            runtime_lock_id=value.runtime_lock_id.hex,
        )


# Keep the temporal split form contract and validation rules together.
class TemporalSplitForm(MlApiModel):
    train_from: int = Field(ge=0)
    train_until: int = Field(ge=0)
    validation_from: int = Field(ge=0)
    validation_until: int = Field(ge=0)
    # Declare purge boundaries explicitly in the temporal split form contract.
    purge_boundaries: int = Field(ge=0)
    embargo_boundaries: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_domain_contract(self) -> Self:
        # Execute the temporal split form validate domain contract workflow in explicit,
        # reviewable steps.
        self.to_domain()
        return self

    def to_domain(self) -> TemporalSplit:
        # Execute the temporal split form to domain workflow in explicit, reviewable
        # steps.
        return TemporalSplit(
            train_from=self.train_from,
            train_until=self.train_until,
            validation_from=self.validation_from,
            validation_until=self.validation_until,
            # Pass purge boundaries explicitly so TemporalSplit receives a reviewable
            # train from and train until input in temporal split form to domain.
            purge_boundaries=self.purge_boundaries,
            embargo_boundaries=self.embargo_boundaries,
        )

    @classmethod
    def from_domain(cls, value: TemporalSplit) -> Self:
        # Return the completed temporal split form from domain result without a hidden
        # fallback.
        return cls(**value.document())


# Keep the training job spec form contract and validation rules together.
class TrainingJobSpecForm(MlApiModel):
    feature_set_ids: tuple[DigestText, ...] = Field(min_length=1)
    label_set_id: DigestText
    universe_id: DigestText
    split: TemporalSplitForm
    # Declare hyperparameter digest explicitly in the training job spec form contract.
    hyperparameter_digest: DigestText
    root_seeds: tuple[int, ...] = Field(min_length=1)
    training_cutoff: int = Field(ge=0)
    modeled_available_boundary: int = Field(ge=0)
    trainer_bundle_id: DigestText
    # Declare runtime lock id explicitly in the training job spec form contract.
    runtime_lock_id: DigestText

    @field_validator("feature_set_ids")
    @classmethod
    def validate_feature_set_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _ordered_unique(values, "training feature_set_ids", allow_empty=False)

    # Apply field validator semantics to the following training job spec form validate
    # root seeds contract.
    @field_validator("root_seeds")
    @classmethod
    def validate_root_seeds(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        # Execute the training job spec form validate root seeds workflow in explicit,
        # reviewable steps.
        if len(values) != len(set(values)):
            raise ValueError("training root_seeds must be unique")
        return values

    @model_validator(mode="after")
    def validate_domain_contract(self) -> Self:
        # Execute the training job spec form validate domain contract workflow in
        # explicit, reviewable steps.
        self.to_domain()
        return self

    def to_domain(self) -> TrainingJobSpec:
        # Execute the training job spec form to domain workflow in explicit, reviewable
        # steps.
        return TrainingJobSpec(
            feature_set_ids=tuple(FeatureSetId(item) for item in self.feature_set_ids),
            label_set_id=LabelSetId(self.label_set_id),
            universe_id=UniverseId(self.universe_id),
            split=self.split.to_domain(),
            # Include hyperparameter digest in the completed training job spec form to
            # domain result.
            hyperparameter_digest=ContentDigest(self.hyperparameter_digest),
            root_seeds=self.root_seeds,
            training_cutoff=self.training_cutoff,
            modeled_available_boundary=self.modeled_available_boundary,
            trainer_bundle_id=BundleId(self.trainer_bundle_id),
            # Include runtime lock id in the completed training job spec form to domain
            # result.
            runtime_lock_id=RuntimeLockId(self.runtime_lock_id),
        )

    @classmethod
    def from_domain(cls, value: TrainingJobSpec) -> Self:
        # Execute the training job spec form from domain workflow in explicit, reviewable
        # steps.
        return cls(
            feature_set_ids=tuple(item.hex for item in value.feature_set_ids),
            label_set_id=value.label_set_id.hex,
            universe_id=value.universe_id.hex,
            split=TemporalSplitForm.from_domain(value.split),
            # Pass hyperparameter digest explicitly so cls receives a reviewable hex and
            # feature set ids input in training job spec form from domain.
            hyperparameter_digest=value.hyperparameter_digest.hex,
            root_seeds=value.root_seeds,
            training_cutoff=value.training_cutoff,
            modeled_available_boundary=value.modeled_available_boundary,
            trainer_bundle_id=value.trainer_bundle_id.hex,
            # Pass runtime lock id explicitly so cls receives a reviewable hex and feature
            # set ids input in training job spec form from domain.
            runtime_lock_id=value.runtime_lock_id.hex,
        )


# Keep the model schedule entry form contract and validation rules together.
class ModelScheduleEntryForm(MlApiModel):
    eligible_from: int = Field(ge=0)
    eligible_until: int = Field(gt=0)
    model_bundle_id: DigestText
    training_cutoff: int = Field(ge=0)
    # Declare model available boundary explicitly in the model schedule entry form
    # contract.
    model_available_boundary: int = Field(ge=0)
    availability_basis: TokenText

    @model_validator(mode="after")
    def validate_domain_contract(self) -> Self:
        # Execute the model schedule entry form validate domain contract workflow in
        # explicit, reviewable steps.
        self.to_domain()
        return self

    def to_domain(self) -> ModelScheduleEntry:
        # Execute the model schedule entry form to domain workflow in explicit, reviewable
        # steps.
        return ModelScheduleEntry(
            eligible_from=self.eligible_from,
            eligible_until=self.eligible_until,
            model_bundle_id=ModelBundleId(self.model_bundle_id),
            training_cutoff=self.training_cutoff,
            # Pass model available boundary explicitly so ModelScheduleEntry receives a
            # reviewable eligible from and eligible until input in model schedule entry
            # form to domain.
            model_available_boundary=self.model_available_boundary,
            availability_basis=self.availability_basis,
        )

    @classmethod
    def from_domain(cls, value: ModelScheduleEntry) -> Self:
        # Execute the model schedule entry form from domain workflow in explicit,
        # reviewable steps.
        return cls(
            eligible_from=value.eligible_from,
            eligible_until=value.eligible_until,
            model_bundle_id=value.model_bundle_id.hex,
            training_cutoff=value.training_cutoff,
            # Pass model available boundary explicitly so cls receives a reviewable
            # eligible from and eligible until input in model schedule entry form from
            # domain.
            model_available_boundary=value.model_available_boundary,
            availability_basis=value.availability_basis,
        )


# Keep the model schedule form contract and validation rules together.
class ModelScheduleForm(MlApiModel):
    entries: tuple[ModelScheduleEntryForm, ...]
    fallback_model_bundle_id: DigestText | None = None

    @model_validator(mode="after")
    def validate_domain_contract(self) -> Self:
        # Execute the model schedule form validate domain contract workflow in explicit,
        # reviewable steps.
        self.to_domain()
        return self

    def to_domain(self) -> ModelSchedule:
        # Execute the model schedule form to domain workflow in explicit, reviewable
        # steps.
        return ModelSchedule(
            entries=tuple(item.to_domain() for item in self.entries),
            fallback_model_bundle_id=(
                None
                if self.fallback_model_bundle_id is None
                # Route all remaining cases through the explicit alternative branch.
                else ModelBundleId(self.fallback_model_bundle_id)
            ),
        )

    @classmethod
    def from_domain(cls, value: ModelSchedule) -> Self:
        # Execute the model schedule form from domain workflow in explicit, reviewable
        # steps.
        return cls(
            entries=tuple(ModelScheduleEntryForm.from_domain(item) for item in value.entries),
            fallback_model_bundle_id=(
                None
                if value.fallback_model_bundle_id is None
                # Route all remaining cases through the explicit alternative branch.
                else value.fallback_model_bundle_id.hex
            ),
        )


# Keep the build features job form contract and validation rules together.
class BuildFeaturesJobForm(MlApiModel):
    spec_version: Literal[1] = 1
    replay_pack_id: DigestText
    replay_semantics_id: DigestText
    replay_layout_schema_id: DigestText
    # Declare feature specs explicitly in the build features job form contract.
    feature_specs: tuple[FeatureSpecForm, ...] = Field(min_length=1)
    input_feature_set_ids: tuple[DigestText, ...] = ()
    compiler_version: TokenText

    @field_validator("input_feature_set_ids")
    @classmethod
    # Define build features job form validate feature set ids as one focused operation
    # with an explicit boundary.
    def validate_feature_set_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _ordered_unique(values, "input_feature_set_ids")

    @model_validator(mode="after")
    def validate_domain_contract(self) -> Self:
        # Execute the build features job form validate domain contract workflow in
        # explicit, reviewable steps.
        self.to_domain()
        return self

    def to_domain(self) -> ResolvedBuildFeaturesJob:
        # Execute the build features job form to domain workflow in explicit, reviewable
        # steps.
        return ResolvedBuildFeaturesJob(
            replay_pack_id=ReplayPackId(self.replay_pack_id),
            replay_semantics_id=ContentDigest(self.replay_semantics_id),
            replay_layout_schema_id=ContentDigest(self.replay_layout_schema_id),
            feature_specs=tuple(item.to_domain() for item in self.feature_specs),
            # Include input feature set ids in the completed build features job form to
            # domain result.
            input_feature_set_ids=tuple(FeatureSetId(item) for item in self.input_feature_set_ids),
            compiler_version=self.compiler_version,
        )

    @classmethod
    def from_domain(cls, value: ResolvedBuildFeaturesJob) -> Self:
        # Execute the build features job form from domain workflow in explicit, reviewable
        # steps.
        return cls(
            replay_pack_id=value.replay_pack_id.hex,
            replay_semantics_id=value.replay_semantics_id.hex,
            replay_layout_schema_id=value.replay_layout_schema_id.hex,
            feature_specs=tuple(FeatureSpecForm.from_domain(item) for item in value.feature_specs),
            # Include input feature set ids in the completed build features job form from
            # domain result.
            input_feature_set_ids=tuple(item.hex for item in value.input_feature_set_ids),
            compiler_version=value.compiler_version,
        )


# Keep the build universe job form contract and validation rules together.
class BuildUniverseJobForm(MlApiModel):
    spec_version: Literal[1] = 1
    snapshot_id: DigestText
    universe_spec_id: DigestText
    input_feature_set_ids: tuple[DigestText, ...] = ()
    # Declare builder bundle id explicitly in the build universe job form contract.
    builder_bundle_id: DigestText
    builder_config_digest: DigestText
    compiler_version: TokenText

    @field_validator("input_feature_set_ids")
    @classmethod
    # Define build universe job form validate feature set ids as one focused operation
    # with an explicit boundary.
    def validate_feature_set_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _ordered_unique(values, "input_feature_set_ids")

    @model_validator(mode="after")
    def validate_domain_contract(self) -> Self:
        # Execute the build universe job form validate domain contract workflow in
        # explicit, reviewable steps.
        self.to_domain()
        return self

    def to_domain(self) -> ResolvedBuildUniverseJob:
        # Execute the build universe job form to domain workflow in explicit, reviewable
        # steps.
        return ResolvedBuildUniverseJob(
            snapshot_id=SnapshotId(self.snapshot_id),
            universe_spec_id=ContentDigest(self.universe_spec_id),
            input_feature_set_ids=tuple(FeatureSetId(item) for item in self.input_feature_set_ids),
            builder_bundle_id=BundleId(self.builder_bundle_id),
            # Include builder config digest in the completed build universe job form to
            # domain result.
            builder_config_digest=ContentDigest(self.builder_config_digest),
            compiler_version=self.compiler_version,
        )

    @classmethod
    def from_domain(cls, value: ResolvedBuildUniverseJob) -> Self:
        # Execute the build universe job form from domain workflow in explicit, reviewable
        # steps.
        return cls(
            snapshot_id=value.snapshot_id.hex,
            universe_spec_id=value.universe_spec_id.hex,
            input_feature_set_ids=tuple(item.hex for item in value.input_feature_set_ids),
            builder_bundle_id=value.builder_bundle_id.hex,
            # Pass builder config digest explicitly so cls receives a reviewable hex and
            # snapshot id input in build universe job form from domain.
            builder_config_digest=value.builder_config_digest.hex,
            compiler_version=value.compiler_version,
        )


# Keep the build labels job form contract and validation rules together.
class BuildLabelsJobForm(MlApiModel):
    spec_version: Literal[1] = 1
    snapshot_id: DigestText
    universe_id: DigestText
    label_spec_id: DigestText
    # Declare label builder bundle id explicitly in the build labels job form contract.
    label_builder_bundle_id: DigestText
    label_config_digest: DigestText
    training_cutoff: int = Field(ge=0)
    compiler_version: TokenText

    @model_validator(mode="after")
    # Define build labels job form validate domain contract as one focused operation with
    # an explicit boundary.
    def validate_domain_contract(self) -> Self:
        # Execute the build labels job form validate domain contract workflow in explicit,
        # reviewable steps.
        self.to_domain()
        return self

    def to_domain(self) -> ResolvedBuildLabelsJob:
        # Execute the build labels job form to domain workflow in explicit, reviewable
        # steps.
        return ResolvedBuildLabelsJob(
            snapshot_id=SnapshotId(self.snapshot_id),
            universe_id=UniverseId(self.universe_id),
            label_spec_id=ContentDigest(self.label_spec_id),
            label_builder_bundle_id=BundleId(self.label_builder_bundle_id),
            # Include label config digest in the completed build labels job form to domain
            # result.
            label_config_digest=ContentDigest(self.label_config_digest),
            training_cutoff=self.training_cutoff,
            compiler_version=self.compiler_version,
        )

    @classmethod
    # Define build labels job form from domain as one focused operation with an explicit
    # boundary.
    def from_domain(cls, value: ResolvedBuildLabelsJob) -> Self:
        # Execute the build labels job form from domain workflow in explicit, reviewable
        # steps.
        return cls(
            snapshot_id=value.snapshot_id.hex,
            universe_id=value.universe_id.hex,
            label_spec_id=value.label_spec_id.hex,
            label_builder_bundle_id=value.label_builder_bundle_id.hex,
            # Pass label config digest explicitly so cls receives a reviewable hex and
            # snapshot id input in build labels job form from domain.
            label_config_digest=value.label_config_digest.hex,
            training_cutoff=value.training_cutoff,
            compiler_version=value.compiler_version,
        )


# Keep the train model job form contract and validation rules together.
class TrainModelJobForm(MlApiModel):
    spec_version: Literal[1] = 1
    training_spec: TrainingJobSpecForm
    feature_schema_digest: DigestText
    preprocessing_digest: DigestText
    # Declare calibration digest explicitly in the train model job form contract.
    calibration_digest: DigestText
    ridge_lambda: int = Field(ge=0)
    framework: TokenText
    canonicality: ModelCanonicality
    compiler_version: TokenText

    # Apply model validator semantics to the following train model job form validate
    # domain contract contract.
    @model_validator(mode="after")
    def validate_domain_contract(self) -> Self:
        # Execute the train model job form validate domain contract workflow in explicit,
        # reviewable steps.
        self.to_domain()
        return self

    def to_domain(self) -> ResolvedTrainModelJob:
        # Execute the train model job form to domain workflow in explicit, reviewable
        # steps.
        return ResolvedTrainModelJob(
            TrainExactLinearModelRequest(
                training_spec=self.training_spec.to_domain(),
                feature_schema_digest=ContentDigest(self.feature_schema_digest),
                preprocessing_digest=ContentDigest(self.preprocessing_digest),
                # Include calibration digest in the completed train model job form to
                # domain result.
                calibration_digest=ContentDigest(self.calibration_digest),
                ridge_lambda=self.ridge_lambda,
                framework=self.framework,
                canonicality=self.canonicality,
                compiler_version=self.compiler_version,
                # Complete TrainExactLinearModelRequest only after its to domain and training
                # spec inputs are visible in train model job form to domain.
            )
        )

    @classmethod
    def from_domain(cls, value: ResolvedTrainModelJob) -> Self:
        # Execute the train model job form from domain workflow in explicit, reviewable
        # steps.
        request = value.request
        return cls(
            training_spec=TrainingJobSpecForm.from_domain(request.training_spec),
            feature_schema_digest=request.feature_schema_digest.hex,
            preprocessing_digest=request.preprocessing_digest.hex,
            # Pass calibration digest explicitly so cls receives a reviewable from domain
            # and training spec input in train model job form from domain.
            calibration_digest=request.calibration_digest.hex,
            ridge_lambda=request.ridge_lambda,
            framework=request.framework,
            canonicality=request.canonicality,
            compiler_version=request.compiler_version,
            # Complete cls only after its from domain and training spec inputs are visible in
            # train model job form from domain.
        )


# Keep the build model schedule job form contract and validation rules together.
class BuildModelScheduleJobForm(MlApiModel):
    spec_version: Literal[1] = 1
    schedule: ModelScheduleForm
    canonicality: ModelCanonicality
    compiler_version: TokenText

    # Apply model validator semantics to the following build model schedule job form
    # validate domain contract contract.
    @model_validator(mode="after")
    def validate_domain_contract(self) -> Self:
        # Execute the build model schedule job form validate domain contract workflow in
        # explicit, reviewable steps.
        self.to_domain()
        return self

    def to_domain(self) -> ResolvedBuildModelScheduleJob:
        # Execute the build model schedule job form to domain workflow in explicit,
        # reviewable steps.
        return ResolvedBuildModelScheduleJob(
            PublishModelScheduleRequest(
                schedule=self.schedule.to_domain(),
                canonicality=self.canonicality,
                compiler_version=self.compiler_version,
                # Complete PublishModelScheduleRequest only after its to domain and schedule
                # inputs are visible in build model schedule job form to domain.
            )
        )

    @classmethod
    def from_domain(cls, value: ResolvedBuildModelScheduleJob) -> Self:
        # Execute the build model schedule job form from domain workflow in explicit,
        # reviewable steps.
        return cls(
            schedule=ModelScheduleForm.from_domain(value.request.schedule),
            canonicality=value.request.canonicality,
            compiler_version=value.request.compiler_version,
        )


# Keep the predict job form contract and validation rules together.
class PredictJobForm(MlApiModel):
    spec_version: Literal[1] = 1
    replay_pack_id: DigestText
    replay_semantics_id: DigestText
    replay_layout_schema_id: DigestText
    # Declare feature set ids explicitly in the predict job form contract.
    feature_set_ids: tuple[DigestText, ...] = Field(min_length=1)
    model_schedule_id: DigestText
    model_bundle_ids: tuple[DigestText, ...] = Field(min_length=1)
    prediction_name: TokenText
    inference_delay_boundaries: int = Field(ge=0)
    # Declare missing policy explicitly in the predict job form contract.
    missing_policy: FrozenMissingPolicy
    canonicality: ModelCanonicality
    compiler_version: TokenText

    @field_validator("feature_set_ids", "model_bundle_ids")
    @classmethod
    # Define predict job form validate ordered ids as one focused operation with an
    # explicit boundary.
    def validate_ordered_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _ordered_unique(values, "prediction artifact IDs", allow_empty=False)

    @model_validator(mode="after")
    def validate_domain_contract(self) -> Self:
        # Execute the predict job form validate domain contract workflow in explicit,
        # reviewable steps.
        self.to_domain()
        return self

    def to_domain(self) -> ResolvedPredictJob:
        # Execute the predict job form to domain workflow in explicit, reviewable steps.
        return ResolvedPredictJob(
            BuildFrozenPredictionsRequest(
                replay_pack_id=ReplayPackId(self.replay_pack_id),
                replay_semantics_id=ContentDigest(self.replay_semantics_id),
                replay_layout_schema_id=ContentDigest(self.replay_layout_schema_id),
                # Include feature set ids in the completed predict job form to domain
                # result.
                feature_set_ids=tuple(FeatureSetId(item) for item in self.feature_set_ids),
                model_schedule_id=ModelScheduleId(self.model_schedule_id),
                model_bundle_ids=tuple(ModelBundleId(item) for item in self.model_bundle_ids),
                prediction_name=self.prediction_name,
                inference_delay_boundaries=self.inference_delay_boundaries,
                # Pass missing policy explicitly so BuildFrozenPredictionsRequest receives
                # a reviewable replay pack id and replay semantics id input in predict job
                # form to domain.
                missing_policy=self.missing_policy,
                canonicality=self.canonicality,
                compiler_version=self.compiler_version,
            )
        )

    # Apply classmethod semantics to the following predict job form from domain contract.
    @classmethod
    def from_domain(cls, value: ResolvedPredictJob) -> Self:
        # Execute the predict job form from domain workflow in explicit, reviewable steps.
        request = value.request
        return cls(
            replay_pack_id=request.replay_pack_id.hex,
            replay_semantics_id=request.replay_semantics_id.hex,
            replay_layout_schema_id=request.replay_layout_schema_id.hex,
            # Include feature set ids in the completed predict job form from domain
            # result.
            feature_set_ids=tuple(item.hex for item in request.feature_set_ids),
            model_schedule_id=request.model_schedule_id.hex,
            model_bundle_ids=tuple(item.hex for item in request.model_bundle_ids),
            prediction_name=request.prediction_name,
            inference_delay_boundaries=request.inference_delay_boundaries,
            # Pass missing policy explicitly so cls receives a reviewable hex and replay
            # pack id input in predict job form from domain.
            missing_policy=request.missing_policy,
            canonicality=request.canonicality,
            compiler_version=request.compiler_version,
        )


def _ordered_unique(
    # Keep the values input explicit in the ordered unique contract.
    values: tuple[str, ...],
    field: str,
    *,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    # Execute the ordered unique workflow in explicit, reviewable steps.
    if not allow_empty and not values:
        raise ValueError(f"{field} must not be empty")
    if tuple(sorted(values)) != values:
        raise ValueError(f"{field} must be sorted")
    if len(values) != len(set(values)):
        # Fail the ordered unique path with ValueError for must be unique and field when
        # values is true; do not continue ambiguously.
        raise ValueError(f"{field} must be unique")
    return values


__all__ = [
    "BuildFeaturesJobForm",
    "BuildLabelsJobForm",
    # Keep the build model schedule job form component named inside the all contract.
    "BuildModelScheduleJobForm",
    "BuildUniverseJobForm",
    "FeatureSpecForm",
    "ModelScheduleEntryForm",
    "ModelScheduleForm",
    # Keep the predict job form component named inside the all contract.
    "PredictJobForm",
    "TemporalSplitForm",
    "TrainModelJobForm",
    "TrainingJobSpecForm",
]
