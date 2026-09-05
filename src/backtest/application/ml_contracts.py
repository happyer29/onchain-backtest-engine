"""Causal, immutable contracts for features, training and inference.

These DTOs deliberately contain no NumPy, framework sessions, registry aliases or
mutable paths.  They are the preflight boundary shared by offline builders and the
sequential engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import (
    # Include bundle id so the identifiers dependency remains explicit.
    BundleId,
    ContentDigest,
    FeatureSetId,
    LabelSetId,
    ModelBundleId,
    # Include model schedule id so the identifiers dependency remains explicit.
    ModelScheduleId,
    RuntimeLockId,
    SnapshotId,
    UniverseId,
)


# Define token as one focused operation with an explicit boundary.
def _token(value: str, *, field: str) -> None:
    # Execute the token workflow in explicit, reviewable steps.
    if not value or value != value.strip() or "\x00" in value:
        raise ValueError(f"{field} must be non-empty, trimmed and NUL-free")


def _ordered_unique(values: tuple[ContentDigest, ...], *, field: str) -> None:
    # Execute the ordered unique workflow in explicit, reviewable steps.
    if tuple(sorted(values, key=lambda item: item.hex)) != values:
        raise ValueError(f"{field} must be sorted")
    if len(values) != len(set(values)):
        raise ValueError(f"{field} must not contain duplicates")


# Keep the null policy contract and validation rules together.
class NullPolicy(StrEnum):
    FORBID = "FORBID"
    EXPLICIT_BITMAP = "EXPLICIT_BITMAP"


# Keep the model canonicality contract and validation rules together.
class ModelCanonicality(StrEnum):
    CANONICAL_EXACT = "CANONICAL_EXACT"
    NON_CANONICAL_TOLERANCE = "NON_CANONICAL_TOLERANCE"


# Keep the inference mode contract and validation rules together.
class InferenceMode(StrEnum):
    DISABLED = "DISABLED"
    FROZEN = "FROZEN"
    EMBEDDED_BATCH = "EMBEDDED_BATCH"
    STATEFUL_SEQUENTIAL = "STATEFUL_SEQUENTIAL"


# Keep the inference missing policy contract and validation rules together.
class InferenceMissingPolicy(StrEnum):
    NULL = "NULL"
    REJECT = "REJECT"


EXACT_LINEAR_MODEL_KIND = "exact-rational-linear-v1"
EXACT_PREDICTION_AVAILABILITY_POLICY = "max-feature-selected-model-fitted-inference-completion-v1"
# Bind exact inference completion policy once as an explicit module-level contract.
EXACT_INFERENCE_COMPLETION_POLICY = "max-input-availability-plus-delay-boundaries-v1"
EXACT_LINEAR_ARITHMETIC_POLICY = "checked-python-integer-floor-int64-output-v1"
EXACT_SCHEDULE_GAP_POLICY = "reject-uncovered-or-use-explicit-hashed-fallback-v1"


@dataclass(frozen=True, slots=True)
class ExactInferencePolicy:
    """Resolved semantic policy shared by frozen and embedded exact inference.

    Batch size, mmap location and temporary quota are intentionally absent: they
    are physical execution settings and cannot change a canonical prediction.
    """

    mode: InferenceMode
    prediction_name: str | None
    missing_policy: InferenceMissingPolicy
    inference_delay_boundaries: int

    def __post_init__(self) -> None:
        # Execute the exact inference policy post init workflow in explicit, reviewable
        # steps.
        if self.mode is InferenceMode.STATEFUL_SEQUENTIAL:
            raise ValueError("stateful inference is not implemented by the exact v1 policy")
        if isinstance(self.inference_delay_boundaries, bool) or not isinstance(
            self.inference_delay_boundaries, int
        ):
            # Fail the exact inference policy post init path with TypeError for inference
            # delay must be an integer when isinstance and inference delay boundaries is
            # true; do not continue ambiguously.
            raise TypeError("inference delay must be an integer")
        if self.inference_delay_boundaries < 0:
            raise ValueError("inference delay must be non-negative")
        if self.mode is InferenceMode.DISABLED:
            # Handle the exact inference policy post init self.mode is
            # InferenceMode.DISABLED branch as a distinct logical block.
            if (
                self.prediction_name is not None
                or self.inference_delay_boundaries != 0
                or self.missing_policy is not InferenceMissingPolicy.REJECT
            ):
                # Fail the exact inference policy post init path with ValueError for
                # disabled inference must use the canonical no-prediction policy when
                # prediction name, inference delay boundaries and missing policy is true;
                # do not continue ambiguously.
                raise ValueError("disabled inference must use the canonical no-prediction policy")
            return
        if (
            self.prediction_name is None
            or not self.prediction_name
            # Keep self visible while evaluating the prediction name and strip guard.
            or self.prediction_name != self.prediction_name.strip()
            or "\x00" in self.prediction_name
        ):
            raise ValueError("exact inference prediction_name must be canonical")

    @classmethod
    # Define exact inference policy disabled as one focused operation with an explicit
    # boundary.
    def disabled(cls) -> ExactInferencePolicy:
        # Execute the exact inference policy disabled workflow in explicit, reviewable
        # steps.
        return cls(
            mode=InferenceMode.DISABLED,
            prediction_name=None,
            missing_policy=InferenceMissingPolicy.REJECT,
            inference_delay_boundaries=0,
            # Complete cls only after its disabled and reject inputs are visible in exact
            # inference policy disabled.
        )

    @classmethod
    def frozen_exact_linear(
        cls,
        *,
        # Keep the prediction name input explicit in the frozen exact linear contract.
        prediction_name: str,
        missing_policy: InferenceMissingPolicy,
        inference_delay_boundaries: int,
    ) -> ExactInferencePolicy:
        # Execute the exact inference policy frozen exact linear workflow in explicit,
        # reviewable steps.
        return cls(
            mode=InferenceMode.FROZEN,
            prediction_name=prediction_name,
            missing_policy=missing_policy,
            inference_delay_boundaries=inference_delay_boundaries,
            # Complete cls only after its frozen and inference mode inputs are visible in
            # exact inference policy frozen exact linear.
        )

    @classmethod
    def embedded_exact_linear(
        cls,
        *,
        # Keep the prediction name input explicit in the embedded exact linear contract.
        prediction_name: str,
        missing_policy: InferenceMissingPolicy,
        inference_delay_boundaries: int,
    ) -> ExactInferencePolicy:
        # Execute the exact inference policy embedded exact linear workflow in explicit,
        # reviewable steps.
        return cls(
            mode=InferenceMode.EMBEDDED_BATCH,
            prediction_name=prediction_name,
            missing_policy=missing_policy,
            inference_delay_boundaries=inference_delay_boundaries,
            # Complete cls only after its embedded batch and inference mode inputs are visible
            # in exact inference policy embedded exact linear.
        )

    def document(self) -> dict[str, object]:
        # Execute the exact inference policy document workflow in explicit, reviewable
        # steps.
        enabled = self.mode is not InferenceMode.DISABLED
        return {
            "arithmetic_policy": (EXACT_LINEAR_ARITHMETIC_POLICY if enabled else "none-v1"),
            "availability_policy": (EXACT_PREDICTION_AVAILABILITY_POLICY if enabled else "none-v1"),
            "completion_policy": (EXACT_INFERENCE_COMPLETION_POLICY if enabled else "none-v1"),
            # Include inference delay boundaries in the completed exact inference policy
            # document result.
            "inference_delay_boundaries": self.inference_delay_boundaries,
            "missing_policy": self.missing_policy.value,
            "mode": self.mode.value,
            "model_kind": EXACT_LINEAR_MODEL_KIND if enabled else "none-v1",
            "prediction_name": self.prediction_name,
            # Include schedule gap policy in the completed exact inference policy document
            # result.
            "schedule_gap_policy": EXACT_SCHEDULE_GAP_POLICY,
        }

    @property
    def inference_policy_digest(self) -> ContentDigest:
        return domain_digest("backtest.exact-inference-policy.v1", self.document())

    # Apply classmethod semantics to the following exact inference policy from document
    # contract.
    @classmethod
    def from_document(cls, value: object) -> ExactInferencePolicy:
        # Execute the exact inference policy from document workflow in explicit,
        # reviewable steps.
        if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
            raise ValueError("inference component config must be an object")
        expected = {
            "arithmetic_policy",
            "availability_policy",
            # Keep the completion policy component named inside the expected contract.
            "completion_policy",
            "inference_delay_boundaries",
            "missing_policy",
            "mode",
            "model_kind",
            # Keep the prediction name component named inside the expected contract.
            "prediction_name",
            "schedule_gap_policy",
        }
        if set(value) != expected:
            raise ValueError("inference component config schema is invalid")
        # Assemble prediction name once so the exact inference policy from document
        # workflow shares one value.
        prediction_name = value["prediction_name"]
        if prediction_name is not None and not isinstance(prediction_name, str):
            raise ValueError("inference prediction_name must be a string or null")
        delay = value["inference_delay_boundaries"]
        if isinstance(delay, bool) or not isinstance(delay, int):
            # Fail the exact inference policy from document path with ValueError for
            # inference delay must be an integer when isinstance and delay is true; do not
            # continue ambiguously.
            raise ValueError("inference delay must be an integer")
        try:
            # Perform the protected exact inference policy from document operation before
            # explicit failure handling.
            result = cls(
                mode=InferenceMode(value["mode"]),
                prediction_name=prediction_name,
                missing_policy=InferenceMissingPolicy(value["missing_policy"]),
                inference_delay_boundaries=delay,
                # Complete cls only after its mode and missing policy inputs are visible in
                # exact inference policy from document.
            )
        except (TypeError, ValueError) as error:
            raise ValueError("inference component policy is unsupported") from error
        if result.document() != value:
            raise ValueError("inference component policy constants are unsupported")
        # Return the completed exact inference policy from document result without a
        # hidden fallback.
        return result


# Keep the feature spec contract and validation rules together.
@dataclass(frozen=True, slots=True)
class FeatureSpec:
    name: str
    version: int
    entity_key: str
    # Declare input ids explicitly in the feature spec contract.
    input_ids: tuple[ContentDigest, ...]
    effective_time_semantics: str
    available_time_semantics: str
    warmup_boundaries: int
    dtype: str
    # Declare null policy explicitly in the feature spec contract.
    null_policy: NullPolicy
    code_bundle_id: BundleId
    runtime_lock_id: RuntimeLockId

    def __post_init__(self) -> None:
        # Execute the feature spec post init workflow in explicit, reviewable steps.
        for field in (
            "name",
            "entity_key",
            "effective_time_semantics",
            "available_time_semantics",
            # Traverse name, entity key and effective time semantics explicitly so each
            # feature spec post init iteration remains traceable.
            "dtype",
        ):
            _token(str(getattr(self, field)), field=field)
        if self.version <= 0:
            raise ValueError("feature version must be positive")
        # Guard this path with self.warmup_boundaries < 0 before applying effects.
        if self.warmup_boundaries < 0:
            raise ValueError("feature warmup must be non-negative")
        _ordered_unique(self.input_ids, field="feature input_ids")

    def identity_document(self) -> dict[str, object]:
        # Execute the feature spec identity document workflow in explicit, reviewable
        # steps.
        return {
            "available_time_semantics": self.available_time_semantics,
            "code_bundle_id": self.code_bundle_id.hex,
            "dtype": self.dtype,
            "effective_time_semantics": self.effective_time_semantics,
            # Include entity key in the completed feature spec identity document result.
            "entity_key": self.entity_key,
            "input_ids": [item.hex for item in self.input_ids],
            "name": self.name,
            "null_policy": self.null_policy.value,
            "runtime_lock_id": self.runtime_lock_id.hex,
            # Include version in the completed feature spec identity document result.
            "version": self.version,
            "warmup_boundaries": self.warmup_boundaries,
        }

    @property
    def feature_spec_id(self) -> ContentDigest:
        # Return the completed feature spec feature spec id result without a hidden
        # fallback.
        return domain_digest("backtest.feature-spec.v1", self.identity_document())


# Keep the point in time row contract and validation rules together.
@dataclass(frozen=True, slots=True, order=True)
class PointInTimeRow:
    row_id: int
    entity_id: int
    effective_boundary_ordinal: int
    # Declare available boundary ordinal explicitly in the point in time row contract.
    available_boundary_ordinal: int

    def __post_init__(self) -> None:
        # Execute the point in time row post init workflow in explicit, reviewable steps.
        for field in (
            "row_id",
            "entity_id",
            "effective_boundary_ordinal",
            "available_boundary_ordinal",
            # Traverse row id, entity id and effective boundary ordinal explicitly so each
            # point in time row post init iteration remains traceable.
        ):
            # Process row id, entity id and effective boundary ordinal inside the bounded
            # point in time row post init loop.
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field} must be a non-negative integer")
        if self.available_boundary_ordinal < self.effective_boundary_ordinal:
            raise ValueError("data cannot be available before it is effective")


# Keep the feature set manifest contract and validation rules together.
@dataclass(frozen=True, slots=True)
class FeatureSetManifest:
    snapshot_id: SnapshotId
    replay_semantics_id: ContentDigest
    feature_specs: tuple[FeatureSpec, ...]
    # Declare input feature set ids explicitly in the feature set manifest contract.
    input_feature_set_ids: tuple[FeatureSetId, ...]
    row_count: int
    alignment_policy: str
    schema_digest: ContentDigest
    physical_content_digest: ContentDigest
    # Declare maximum available boundary explicitly in the feature set manifest contract.
    maximum_available_boundary: int | None

    def __post_init__(self) -> None:
        # Execute the feature set manifest post init workflow in explicit, reviewable
        # steps.
        if not self.feature_specs:
            raise ValueError("FeatureSet requires at least one FeatureSpec")
        spec_ids = tuple(item.feature_spec_id.hex for item in self.feature_specs)
        if spec_ids != tuple(sorted(spec_ids)) or len(spec_ids) != len(set(spec_ids)):
            raise ValueError("feature specs must be sorted and unique by identity")
        # Invoke _ordered_unique for input feature set ids as a visible feature set
        # manifest post init step.
        _ordered_unique(self.input_feature_set_ids, field="input_feature_set_ids")
        if self.row_count < 0:
            raise ValueError("row_count must be non-negative")
        _token(self.alignment_policy, field="alignment_policy")
        if self.maximum_available_boundary is not None and self.maximum_available_boundary < 0:
            # Fail the feature set manifest post init path with ValueError for maximum
            # available boundary must be non-negative when maximum available boundary is
            # true; do not continue ambiguously.
            raise ValueError("maximum_available_boundary must be non-negative")

    def identity_document(self) -> dict[str, object]:
        # Execute the feature set manifest identity document workflow in explicit,
        # reviewable steps.
        return {
            "alignment_policy": self.alignment_policy,
            "feature_spec_ids": [item.feature_spec_id.hex for item in self.feature_specs],
            "input_feature_set_ids": [item.hex for item in self.input_feature_set_ids],
            "maximum_available_boundary": self.maximum_available_boundary,
            # Include physical content digest in the completed feature set manifest
            # identity document result.
            "physical_content_digest": self.physical_content_digest.hex,
            "replay_semantics_id": self.replay_semantics_id.hex,
            "row_count": self.row_count,
            "schema_digest": self.schema_digest.hex,
            "snapshot_id": self.snapshot_id.hex,
            # Return the completed feature set manifest identity document result without a
            # hidden fallback.
        }

    @property
    def build_key(self) -> ContentDigest:
        """Derivation key; the repository-assigned content ID remains authoritative."""

        return domain_digest("backtest.feature-set-build.v1", self.identity_document())


# Keep the label set manifest contract and validation rules together.
@dataclass(frozen=True, slots=True)
class LabelSetManifest:
    snapshot_id: SnapshotId
    label_spec_id: ContentDigest
    universe_id: UniverseId
    # Declare training cutoff explicitly in the label set manifest contract.
    training_cutoff: int
    maximum_future_boundary_used: int
    row_count: int
    physical_content_digest: ContentDigest

    def __post_init__(self) -> None:
        # Execute the label set manifest post init workflow in explicit, reviewable steps.
        if self.training_cutoff < 0 or self.maximum_future_boundary_used < 0:
            raise ValueError("label boundaries must be non-negative")
        if self.maximum_future_boundary_used < self.training_cutoff:
            raise ValueError("label horizon cannot end before the training cutoff")
        if self.row_count < 0:
            # Fail the label set manifest post init path with ValueError for label row
            # count must be non-negative when row count is true; do not continue
            # ambiguously.
            raise ValueError("label row_count must be non-negative")

    @property
    def build_key(self) -> ContentDigest:
        # Execute the label set manifest build key workflow in explicit, reviewable steps.
        return domain_digest(
            "backtest.label-set-build.v1",
            {
                "label_spec_id": self.label_spec_id.hex,
                "maximum_future_boundary_used": self.maximum_future_boundary_used,
                # Keep physical content digest named so the v1 and label spec id payload
                # passed to domain_digest remains self-describing within label set
                # manifest build key.
                "physical_content_digest": self.physical_content_digest.hex,
                "row_count": self.row_count,
                "snapshot_id": self.snapshot_id.hex,
                "training_cutoff": self.training_cutoff,
                "universe_id": self.universe_id.hex,
                # Close the v1 and label spec id payload only after all label set manifest
                # build key fields are present.
            },
        )


# Keep the universe manifest contract and validation rules together.
@dataclass(frozen=True, slots=True)
class UniverseManifest:
    snapshot_id: SnapshotId
    universe_spec_id: ContentDigest
    maximum_input_available_boundary: int
    # Declare row count explicitly in the universe manifest contract.
    row_count: int
    physical_content_digest: ContentDigest

    def __post_init__(self) -> None:
        # Execute the universe manifest post init workflow in explicit, reviewable steps.
        if self.maximum_input_available_boundary < 0 or self.row_count < 0:
            raise ValueError("universe boundaries and row count must be non-negative")

    @property
    def build_key(self) -> ContentDigest:
        # Execute the universe manifest build key workflow in explicit, reviewable steps.
        return domain_digest(
            "backtest.universe-build.v1",
            {
                "maximum_input_available_boundary": self.maximum_input_available_boundary,
                "physical_content_digest": self.physical_content_digest.hex,
                # Keep row count named so the v1 and maximum input available boundary
                # payload passed to domain_digest remains self-describing within universe
                # manifest build key.
                "row_count": self.row_count,
                "snapshot_id": self.snapshot_id.hex,
                "universe_spec_id": self.universe_spec_id.hex,
            },
        )


# Keep the temporal split contract and validation rules together.
@dataclass(frozen=True, slots=True)
class TemporalSplit:
    train_from: int
    train_until: int
    validation_from: int
    # Declare validation until explicitly in the temporal split contract.
    validation_until: int
    purge_boundaries: int
    embargo_boundaries: int

    def __post_init__(self) -> None:
        # Execute the temporal split post init workflow in explicit, reviewable steps.
        values = (
            self.train_from,
            self.train_until,
            self.validation_from,
            self.validation_until,
            # Keep the self component named inside the values contract.
            self.purge_boundaries,
            self.embargo_boundaries,
        )
        if any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in values):
            raise ValueError("temporal split values must be non-negative integers")
        # Evaluate the complete temporal split post init train from, train until and
        # validation from condition before guarded effects.
        if not self.train_from < self.train_until <= self.validation_from < self.validation_until:
            raise ValueError("temporal split intervals must be ordered and half-open")
        if self.train_until + self.purge_boundaries > self.validation_from:
            raise ValueError("purge interval crosses validation start")

    def document(self) -> dict[str, int]:
        # Execute the temporal split document workflow in explicit, reviewable steps.
        return {
            "embargo_boundaries": self.embargo_boundaries,
            "purge_boundaries": self.purge_boundaries,
            "train_from": self.train_from,
            "train_until": self.train_until,
            # Include validation from in the completed temporal split document result.
            "validation_from": self.validation_from,
            "validation_until": self.validation_until,
        }


# Keep the training job spec contract and validation rules together.
@dataclass(frozen=True, slots=True)
class TrainingJobSpec:
    feature_set_ids: tuple[FeatureSetId, ...]
    label_set_id: LabelSetId
    universe_id: UniverseId
    # Declare split explicitly in the training job spec contract.
    split: TemporalSplit
    hyperparameter_digest: ContentDigest
    root_seeds: tuple[int, ...]
    training_cutoff: int
    modeled_available_boundary: int
    # Declare trainer bundle id explicitly in the training job spec contract.
    trainer_bundle_id: BundleId
    runtime_lock_id: RuntimeLockId

    def __post_init__(self) -> None:
        # Execute the training job spec post init workflow in explicit, reviewable steps.
        _ordered_unique(self.feature_set_ids, field="training feature_set_ids")
        if not self.feature_set_ids:
            raise ValueError("training requires at least one FeatureSet")
        if not self.root_seeds or len(self.root_seeds) != len(set(self.root_seeds)):
            raise ValueError("training root_seeds must be non-empty and unique")
        # Evaluate the complete training job spec post init seed, root seeds and
        # isinstance condition before guarded effects.
        if any(isinstance(seed, bool) or not isinstance(seed, int) for seed in self.root_seeds):
            raise TypeError("training seeds must be integers")
        if self.training_cutoff < self.split.train_until:
            raise ValueError("training cutoff must cover all training rows")
        if self.modeled_available_boundary < self.training_cutoff:
            # Fail the training job spec post init path with ValueError for model cannot
            # be available before its training cutoff when modeled available boundary and
            # training cutoff is true; do not continue ambiguously.
            raise ValueError("model cannot be available before its training cutoff")

    @property
    def training_job_spec_id(self) -> ContentDigest:
        # Execute the training job spec training job spec id workflow in explicit,
        # reviewable steps.
        return domain_digest(
            "backtest.training-job-spec.v1",
            {
                "feature_set_ids": [item.hex for item in self.feature_set_ids],
                "hyperparameter_digest": self.hyperparameter_digest.hex,
                # Keep label set id named so the v1 and feature set ids payload passed to
                # domain_digest remains self-describing within training job spec training
                # job spec id.
                "label_set_id": self.label_set_id.hex,
                "modeled_available_boundary": self.modeled_available_boundary,
                "root_seeds": list(self.root_seeds),
                "runtime_lock_id": self.runtime_lock_id.hex,
                "split": self.split.document(),
                # Keep trainer bundle id named so the v1 and feature set ids payload
                # passed to domain_digest remains self-describing within training job spec
                # training job spec id.
                "trainer_bundle_id": self.trainer_bundle_id.hex,
                "training_cutoff": self.training_cutoff,
                "universe_id": self.universe_id.hex,
            },
        )


# Keep the model bundle manifest contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ModelBundleManifest:
    training_job_spec_id: ContentDigest
    feature_schema_digest: ContentDigest
    weights_digest: ContentDigest
    # Declare preprocessing digest explicitly in the model bundle manifest contract.
    preprocessing_digest: ContentDigest
    calibration_digest: ContentDigest
    metrics_digest: ContentDigest
    framework: str
    runtime_lock_id: RuntimeLockId
    # Declare training cutoff explicitly in the model bundle manifest contract.
    training_cutoff: int
    model_available_boundary: int
    canonicality: ModelCanonicality

    def __post_init__(self) -> None:
        # Execute the model bundle manifest post init workflow in explicit, reviewable
        # steps.
        _token(self.framework, field="framework")
        if self.training_cutoff < 0:
            raise ValueError("training_cutoff must be non-negative")
        if self.model_available_boundary < self.training_cutoff:
            raise ValueError("model availability precedes training cutoff")

    # Apply property semantics to the following model bundle manifest build key contract.
    @property
    def build_key(self) -> ContentDigest:
        # Execute the model bundle manifest build key workflow in explicit, reviewable
        # steps.
        return domain_digest(
            "backtest.model-bundle-build.v1",
            {
                "calibration_digest": self.calibration_digest.hex,
                "canonicality": self.canonicality.value,
                # Keep feature schema digest named so the v1 and calibration digest
                # payload passed to domain_digest remains self-describing within model
                # bundle manifest build key.
                "feature_schema_digest": self.feature_schema_digest.hex,
                "framework": self.framework,
                "metrics_digest": self.metrics_digest.hex,
                "model_available_boundary": self.model_available_boundary,
                "preprocessing_digest": self.preprocessing_digest.hex,
                # Keep runtime lock id named so the v1 and calibration digest payload
                # passed to domain_digest remains self-describing within model bundle
                # manifest build key.
                "runtime_lock_id": self.runtime_lock_id.hex,
                "training_cutoff": self.training_cutoff,
                "training_job_spec_id": self.training_job_spec_id.hex,
                "weights_digest": self.weights_digest.hex,
            },
            # Complete domain_digest only after its v1 and calibration digest inputs are
            # visible in model bundle manifest build key.
        )


# Keep the model schedule entry contract and validation rules together.
@dataclass(frozen=True, slots=True, order=True)
class ModelScheduleEntry:
    eligible_from: int
    eligible_until: int
    model_bundle_id: ModelBundleId
    # Declare training cutoff explicitly in the model schedule entry contract.
    training_cutoff: int
    model_available_boundary: int
    availability_basis: str

    def __post_init__(self) -> None:
        # Execute the model schedule entry post init workflow in explicit, reviewable
        # steps.
        if self.eligible_from < 0 or self.eligible_until <= self.eligible_from:
            raise ValueError("model eligibility must be a non-empty half-open interval")
        if self.training_cutoff < 0:
            raise ValueError("training_cutoff must be non-negative")
        if self.model_available_boundary > self.eligible_from:
            # Fail the model schedule entry post init path with ValueError for model is
            # not available at the start of its interval when model available boundary and
            # eligible from is true; do not continue ambiguously.
            raise ValueError("model is not available at the start of its interval")
        if self.training_cutoff > self.model_available_boundary:
            raise ValueError("training cutoff is later than model availability")
        _token(self.availability_basis, field="availability_basis")

    def document(self) -> dict[str, object]:
        # Execute the model schedule entry document workflow in explicit, reviewable
        # steps.
        return {
            "availability_basis": self.availability_basis,
            "eligible_from": self.eligible_from,
            "eligible_until": self.eligible_until,
            "model_available_boundary": self.model_available_boundary,
            # Include model bundle id in the completed model schedule entry document
            # result.
            "model_bundle_id": self.model_bundle_id.hex,
            "training_cutoff": self.training_cutoff,
        }


class ModelUnavailableError(LookupError):
    """A decision boundary has no causally eligible exact model."""


@dataclass(frozen=True, slots=True)
class ModelSchedule:
    entries: tuple[ModelScheduleEntry, ...]
    fallback_model_bundle_id: ModelBundleId | None = None

    def __post_init__(self) -> None:
        # Execute the model schedule post init workflow in explicit, reviewable steps.
        if not self.entries and self.fallback_model_bundle_id is None:
            raise ValueError("model schedule requires entries or an explicit fallback")
        if tuple(sorted(self.entries, key=lambda item: item.eligible_from)) != self.entries:
            raise ValueError("model schedule entries must be sorted")
        for previous, current in zip(self.entries, self.entries[1:], strict=False):
            # Process entries inside the bounded model schedule post init loop.
            if previous.eligible_until > current.eligible_from:
                raise ValueError("model schedule intervals overlap")

    @property
    def build_key(self) -> ContentDigest:
        # Execute the model schedule build key workflow in explicit, reviewable steps.
        return domain_digest(
            "backtest.model-schedule-build.v1",
            {
                "entries": [item.document() for item in self.entries],
                "fallback_model_bundle_id": (
                    # Keep domain digest, v1 and entries visible while completing
                    # domain_digest within model schedule build key.
                    None
                    if self.fallback_model_bundle_id is None
                    else self.fallback_model_bundle_id.hex
                ),
            },
            # Complete domain_digest only after its v1 and entries inputs are visible in model
            # schedule build key.
        )

    def model_for(self, decision_boundary: int) -> ModelBundleId:
        # Execute the model schedule model for workflow in explicit, reviewable steps.
        if decision_boundary < 0:
            raise ValueError("decision boundary must be non-negative")
        matches = tuple(
            item
            for item in self.entries
            # Pass item explicitly so tuple receives a reviewable entries and eligible
            # from input in model schedule model for.
            if item.eligible_from <= decision_boundary < item.eligible_until
        )
        if len(matches) == 1:
            return matches[0].model_bundle_id
        if not matches and self.fallback_model_bundle_id is not None:
            # Return the completed model schedule model for result without a hidden
            # fallback.
            return self.fallback_model_bundle_id
        raise ModelUnavailableError("MODEL_UNAVAILABLE")

    def require_covered(self, boundaries: tuple[int, ...]) -> None:
        # Execute the model schedule require covered workflow in explicit, reviewable
        # steps.
        for boundary in boundaries:
            self.model_for(boundary)


# Keep the prediction availability contract and validation rules together.
@dataclass(frozen=True, slots=True)
class PredictionAvailability:
    feature_available_boundary: int
    model_available_boundaries: tuple[int, ...]
    fitted_component_available_boundaries: tuple[int, ...]
    # Declare inference completion boundary explicitly in the prediction availability
    # contract.
    inference_completion_boundary: int

    def __post_init__(self) -> None:
        # Execute the prediction availability post init workflow in explicit, reviewable
        # steps.
        values = (
            self.feature_available_boundary,
            self.inference_completion_boundary,
            *self.model_available_boundaries,
            *self.fitted_component_available_boundaries,
            # Complete the values group only after its semantic components are visible.
        )
        if any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in values):
            raise ValueError("prediction availability operands must be non-negative integers")
        if not self.model_available_boundaries:
            raise ValueError("prediction availability requires at least one model")

    # Apply property semantics to the following prediction availability available boundary
    # ordinal contract.
    @property
    def available_boundary_ordinal(self) -> int:
        # Execute the prediction availability available boundary ordinal workflow in
        # explicit, reviewable steps.
        return max(
            self.feature_available_boundary,
            self.inference_completion_boundary,
            *self.model_available_boundaries,
            *self.fitted_component_available_boundaries,
            # Complete max only after its feature available boundary and inference completion
            # boundary inputs are visible in prediction availability available boundary
            # ordinal.
        )


# Keep the prediction set manifest contract and validation rules together.
@dataclass(frozen=True, slots=True)
class PredictionSetManifest:
    feature_set_ids: tuple[FeatureSetId, ...]
    model_schedule_id: ModelScheduleId
    model_bundle_ids: tuple[ModelBundleId, ...]
    # Declare inference mode explicitly in the prediction set manifest contract.
    inference_mode: InferenceMode
    inference_policy_digest: ContentDigest
    causal_availability_policy: str
    compiler_bundle_id: BundleId
    runtime_lock_id: RuntimeLockId
    # Declare row count explicitly in the prediction set manifest contract.
    row_count: int
    schema_digest: ContentDigest
    physical_content_digest: ContentDigest
    canonicality: ModelCanonicality

    def __post_init__(self) -> None:
        # Execute the prediction set manifest post init workflow in explicit, reviewable
        # steps.
        _ordered_unique(self.feature_set_ids, field="prediction feature_set_ids")
        _ordered_unique(self.model_bundle_ids, field="prediction model_bundle_ids")
        if not self.feature_set_ids or not self.model_bundle_ids:
            raise ValueError("PredictionSet requires features and models")
        _token(self.causal_availability_policy, field="causal_availability_policy")
        # Guard this path with self.row_count < 0 before applying effects.
        if self.row_count < 0:
            raise ValueError("prediction row_count must be non-negative")

    @property
    def build_key(self) -> ContentDigest:
        # Execute the prediction set manifest build key workflow in explicit, reviewable
        # steps.
        return domain_digest(
            "backtest.prediction-set-build.v1",
            {
                "canonicality": self.canonicality.value,
                "causal_availability_policy": self.causal_availability_policy,
                # Keep compiler bundle id named so the v1 and canonicality payload passed
                # to domain_digest remains self-describing within prediction set manifest
                # build key.
                "compiler_bundle_id": self.compiler_bundle_id.hex,
                "feature_set_ids": [item.hex for item in self.feature_set_ids],
                "inference_mode": self.inference_mode.value,
                "inference_policy_digest": self.inference_policy_digest.hex,
                "model_bundle_ids": [item.hex for item in self.model_bundle_ids],
                # Keep model schedule id named so the v1 and canonicality payload passed
                # to domain_digest remains self-describing within prediction set manifest
                # build key.
                "model_schedule_id": self.model_schedule_id.hex,
                "physical_content_digest": self.physical_content_digest.hex,
                "row_count": self.row_count,
                "runtime_lock_id": self.runtime_lock_id.hex,
                "schema_digest": self.schema_digest.hex,
                # Close the v1 and canonicality payload only after all prediction set manifest
                # build key fields are present.
            },
        )


__all__ = [
    "EXACT_INFERENCE_COMPLETION_POLICY",
    "EXACT_LINEAR_ARITHMETIC_POLICY",
    # Keep the exact linear model kind component named inside the all contract.
    "EXACT_LINEAR_MODEL_KIND",
    "EXACT_PREDICTION_AVAILABILITY_POLICY",
    "EXACT_SCHEDULE_GAP_POLICY",
    "ExactInferencePolicy",
    "FeatureSetManifest",
    # Keep the feature spec component named inside the all contract.
    "FeatureSpec",
    "InferenceMissingPolicy",
    "InferenceMode",
    "LabelSetManifest",
    "ModelBundleManifest",
    # Keep the model canonicality component named inside the all contract.
    "ModelCanonicality",
    "ModelSchedule",
    "ModelScheduleEntry",
    "ModelUnavailableError",
    "NullPolicy",
    # Keep the point in time row component named inside the all contract.
    "PointInTimeRow",
    "PredictionAvailability",
    "PredictionSetManifest",
    "TemporalSplit",
    "TrainingJobSpec",
    # Keep the universe manifest component named inside the all contract.
    "UniverseManifest",
]
