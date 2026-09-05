"""Deterministic training and frozen-inference Phase-6 vertical slices."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack
from fractions import Fraction
from math import gcd, lcm

# Import typing at the visible module dependency boundary.
from typing import Final

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.adapters.columnar.numpy import layout as replay_physical
from backtest.adapters.columnar.numpy.reader import NumpyMmapReplaySource
from backtest.adapters.ml.numpy import layout as physical

# Import publisher at the visible module dependency boundary.
from backtest.adapters.ml.numpy.publisher import LocalNumpyMlArtifactPublisher
from backtest.adapters.ml.numpy.reader import (
    NumpyFeatureSetProvider,
    NumpyModelBundleReader,
    NumpyModelScheduleReader,
    # Include numpy universe reader so the reader dependency remains explicit.
    NumpyUniverseReader,
)
from backtest.adapters.ml.numpy.toolchain import (
    UNIT_EXACT_TRAINER_BUNDLE_ID,
    UNIT_FROZEN_INFERENCE_BUNDLE_ID,
    # Include unit ml build tools so the toolchain dependency remains explicit.
    unit_ml_build_tools,
)
from backtest.adapters.ml.numpy.training import NumpyLabelSetReader
from backtest.application.build_tool_roles import ML_FROZEN_INFERENCE_ROLE, ML_TRAINER_ROLE
from backtest.application.code_bundles import PinnedCodeBundleSet

# Import ml artifacts at the visible module dependency boundary.
from backtest.application.ml_artifacts import (
    BuildFrozenPredictionsRequest,
    BuildPredictionSetRequest,
    ExactLinearModelPayload,
    FrozenMissingPolicy,
    # Include frozen prediction row so the ml artifacts dependency remains explicit.
    FrozenPredictionRow,
    PublishedModelBundle,
    PublishedPredictionSet,
    PublishModelBundleRequest,
    TrainExactLinearModelRequest,
    # Close the ml artifacts import after its required symbols are visible.
)
from backtest.application.ml_contracts import (
    EXACT_LINEAR_MODEL_KIND,
    EXACT_PREDICTION_AVAILABILITY_POLICY,
    ExactInferencePolicy,
    # Include inference missing policy so the ml contracts dependency remains explicit.
    InferenceMissingPolicy,
    InferenceMode,
    ModelCanonicality,
    PredictionAvailability,
)

# Import hashing at the visible module dependency boundary.
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import BundleId, ContentDigest

EXACT_LINEAR_FRAMEWORK: Final = EXACT_LINEAR_MODEL_KIND
_INT64_MIN: Final = -(1 << 63)
_INT64_MAX: Final = (1 << 63) - 1
# Bind uint64 max once as an explicit module-level contract.
_UINT64_MAX: Final = (1 << 64) - 1
EXACT_INTEGER_LINEAR_TRAINER_BUNDLE_ID: Final = BundleId(UNIT_EXACT_TRAINER_BUNDLE_ID.hex)
EXACT_FROZEN_INFERENCE_BUNDLE_ID: Final = BundleId(UNIT_FROZEN_INFERENCE_BUNDLE_ID.hex)


class ExactMlPipelineError(RuntimeError):
    """Exact training/inference cannot preserve its bounded causal contract."""


class LocalExactIntegerLinearTrainer:
    """Fit a small ridge-linear model using bounded exact rational arithmetic."""

    def __init__(
        self,
        artifacts: LocalArtifactRepository,
        publisher: LocalNumpyMlArtifactPublisher,
        *,
        # Keep the maximum training rows input explicit in the init contract.
        maximum_training_rows: int = 100_000,
        maximum_features: int = 64,
        maximum_absolute_input: int = 1 << 48,
        maximum_fraction_bits: int = 4096,
        build_tools: PinnedCodeBundleSet | None = None,
        # Close the init signature after its explicit inputs.
    ) -> None:
        # Execute the local exact integer linear trainer init workflow in explicit,
        # reviewable steps.
        if maximum_training_rows <= 0 or maximum_features <= 0:
            raise ValueError("exact trainer row/feature bounds must be positive")
        if maximum_absolute_input <= 0 or maximum_fraction_bits <= 0:
            raise ValueError("exact trainer numeric bounds must be positive")
        self._artifacts = artifacts
        # Assemble self publisher once so the local exact integer linear trainer init
        # workflow shares one value.
        self._publisher = publisher
        self._build_tools = build_tools or unit_ml_build_tools()
        self._trainer_bundle_id = self._build_tools.require_current(ML_TRAINER_ROLE)
        self._maximum_training_rows = maximum_training_rows
        self._maximum_features = maximum_features
        # Assemble self maximum absolute input once so the local exact integer linear
        # trainer init workflow shares one value.
        self._maximum_absolute_input = maximum_absolute_input
        self._maximum_fraction_bits = maximum_fraction_bits

    def train_exact_linear(
        self,
        request: TrainExactLinearModelRequest,
        # Keep the published model bundle input explicit in the train exact linear contract.
    ) -> PublishedModelBundle:
        # Execute the local exact integer linear trainer train exact linear workflow in
        # explicit, reviewable steps.
        self._require_current()
        if request.compiler_version != physical.COMPILER_VERSION:
            raise ExactMlPipelineError(f"compiler version must be {physical.COMPILER_VERSION!r}")
        if request.framework != EXACT_LINEAR_FRAMEWORK:
            raise ExactMlPipelineError("exact trainer framework is unsupported")
        # Evaluate the complete local exact integer linear trainer train exact linear
        # trainer bundle id, training spec and request condition before guarded effects.
        if request.training_spec.trainer_bundle_id != self._trainer_bundle_id:
            raise ExactMlPipelineError("TrainingJobSpec pins another trainer bundle")
        with ExitStack() as stack:
            # Keep exit stack active only for the bounded local exact integer linear
            # trainer train exact linear operation.
            features = tuple(
                stack.enter_context(
                    NumpyFeatureSetProvider(
                        self._artifacts,
                        feature_id,
                        # Pass build tools explicitly so NumpyFeatureSetProvider receives
                        # a reviewable artifacts and build tools input in local exact
                        # integer linear trainer train exact linear.
                        build_tools=self._build_tools,
                    )
                )
                for feature_id in request.training_spec.feature_set_ids
            )
            # Assemble labels once so the local exact integer linear trainer train exact
            # linear workflow shares one value.
            labels = stack.enter_context(
                NumpyLabelSetReader(
                    self._artifacts,
                    request.training_spec.label_set_id,
                    build_tools=self._build_tools,
                    # Complete NumpyLabelSetReader only after its artifacts and label set id
                    # inputs are visible in local exact integer linear trainer train exact
                    # linear.
                )
            )
            universe = stack.enter_context(
                NumpyUniverseReader(
                    self._artifacts,
                    # Pass request explicitly so NumpyUniverseReader receives a reviewable
                    # artifacts and universe id input in local exact integer linear
                    # trainer train exact linear.
                    request.training_spec.universe_id,
                    build_tools=self._build_tools,
                )
            )
            feature_schema = _feature_schema(features)
            # Evaluate the complete local exact integer linear trainer train exact linear
            # feature schema, feature schema digest and request condition before guarded
            # effects.
            if feature_schema != request.feature_schema_digest:
                raise ExactMlPipelineError("training FeatureSet schema digest changed")
            feature_count = sum(len(feature.feature_specs) for feature in features)
            if not 0 < feature_count <= self._maximum_features:
                raise ExactMlPipelineError("training feature count exceeds exact-trainer bound")
            # Evaluate the complete local exact integer linear trainer train exact linear
            # universe id, labels and universe condition before guarded effects.
            if labels.universe_id != universe.universe_id:
                raise ExactMlPipelineError("training LabelSet references another Universe")
            if labels.training_cutoff != request.training_spec.training_cutoff:
                raise ExactMlPipelineError("training cutoff differs from LabelSet")
            payload, metrics = self._fit(request, features, labels, universe, feature_count)
        # Return the completed local exact integer linear trainer train exact linear
        # result without a hidden fallback.
        return self._publisher.publish_model_bundle(
            PublishModelBundleRequest(
                training_spec=request.training_spec,
                feature_schema_digest=request.feature_schema_digest,
                payload=payload,
                # Pass preprocessing digest explicitly so PublishModelBundleRequest
                # receives a reviewable training spec and feature schema digest input in
                # local exact integer linear trainer train exact linear.
                preprocessing_digest=request.preprocessing_digest,
                calibration_digest=request.calibration_digest,
                metrics_digest=metrics,
                fitted_component_available_boundaries=(request.training_spec.training_cutoff,),
                framework=request.framework,
                # Pass canonicality explicitly so PublishModelBundleRequest receives a
                # reviewable training spec and feature schema digest input in local exact
                # integer linear trainer train exact linear.
                canonicality=request.canonicality,
                compiler_version=request.compiler_version,
            )
        )

    def _fit(
        # Keep the remaining fit inputs visible at the local exact integer linear trainer
        # fit boundary.
        self,
        request: TrainExactLinearModelRequest,
        features: tuple[NumpyFeatureSetProvider, ...],
        labels: NumpyLabelSetReader,
        universe: NumpyUniverseReader,
        # Keep the feature count input explicit in the fit contract.
        feature_count: int,
    ) -> tuple[ExactLinearModelPayload, ContentDigest]:
        # Execute the local exact integer linear trainer fit workflow in explicit,
        # reviewable steps.
        dimension = feature_count + 1
        gram = [[0 for _ in range(dimension)] for _ in range(dimension)]
        target = [0 for _ in range(dimension)]
        target_square = 0
        selected_rows = 0
        # Assemble split once so the local exact integer linear trainer fit workflow
        # shares one value.
        split = request.training_spec.split
        for label in labels.rows_for_training():
            # Process labels.rows_for_training() inside the bounded local exact integer
            # linear trainer fit loop.
            if not split.train_from <= label.effective_boundary_ordinal < split.train_until:
                continue
            if label.future_boundary_used > request.training_spec.training_cutoff:
                raise ExactMlPipelineError("training label uses data after training cutoff")
            if label.value is None:
                # Keep the continue step explicit within the local exact integer linear
                # trainer fit workflow.
                continue
            if not universe.contains(label.replay_row_id, label.effective_boundary_ordinal):
                continue
            values = [1]
            for feature in features:
                # Process features inside the bounded local exact integer linear trainer
                # fit loop.
                for code in range(len(feature.feature_specs)):
                    # Process range(len(feature.feature_specs)) inside the bounded local
                    # exact integer linear trainer fit loop.
                    value = feature.value_at_code(
                        code,
                        label.replay_row_id,
                        label.effective_boundary_ordinal,
                    )
                    # Guard this path with value is None before applying effects.
                    if value is None:
                        # Handle the local exact integer linear trainer fit value is None
                        # branch as a distinct logical block.
                        raise ExactMlPipelineError(
                            "training feature is missing or not yet causally available"
                        )
                    _require_absolute_bound(
                        value,
                        # Pass self explicitly so _require_absolute_bound receives a
                        # reviewable training feature and maximum absolute input input in
                        # local exact integer linear trainer fit.
                        self._maximum_absolute_input,
                        "training feature",
                    )
                    values.append(value)
            _require_absolute_bound(
                # Pass label explicitly so _require_absolute_bound receives a reviewable
                # training label and value input in local exact integer linear trainer
                # fit.
                label.value,
                self._maximum_absolute_input,
                "training label",
            )
            selected_rows += 1
            # Evaluate the complete local exact integer linear trainer fit selected rows
            # and maximum training rows condition before guarded effects.
            if selected_rows > self._maximum_training_rows:
                raise ExactMlPipelineError("training row count exceeds exact-trainer bound")
            for row in range(dimension):
                # Process range(dimension) inside the bounded local exact integer linear
                # trainer fit loop.
                target[row] += values[row] * label.value
                for column in range(row, dimension):
                    # Process range(row, dimension) inside the bounded local exact integer
                    # linear trainer fit loop.
                    product = values[row] * values[column]
                    gram[row][column] += product
                    if row != column:
                        gram[column][row] += product
            target_square += label.value * label.value
        # Guard this path with selected_rows == 0 before applying effects.
        if selected_rows == 0:
            raise ExactMlPipelineError("temporal split has no eligible non-null training rows")
        for index in range(1, dimension):
            gram[index][index] += request.ridge_lambda
        coefficients = _solve_exact(
            # Pass gram explicitly so _solve_exact receives a reviewable maximum fraction
            # bits and gram input in local exact integer linear trainer fit.
            gram,
            target,
            maximum_fraction_bits=self._maximum_fraction_bits,
        )
        payload = _fraction_payload(coefficients)
        # Assemble sse once so the local exact integer linear trainer fit workflow shares
        # one value.
        sse = Fraction(target_square)
        for row in range(dimension):
            # Process range(dimension) inside the bounded local exact integer linear
            # trainer fit loop.
            sse -= 2 * coefficients[row] * target[row]
            for column in range(dimension):
                # Metrics describe unregularized residual error; ridge affects only fit.
                ridge_adjustment = request.ridge_lambda if row == column and row > 0 else 0
                sse += (
                    coefficients[row]
                    * coefficients[column]
                    * (gram[row][column] - ridge_adjustment)
                    # Complete the sse group only after its semantic components are visible.
                )
        metrics = domain_digest(
            "backtest.exact-linear-training-metrics.v1",
            {
                "ridge_lambda": request.ridge_lambda,
                # Keep sample count named so the v1 and ridge lambda payload passed to
                # domain_digest remains self-describing within local exact integer linear
                # trainer fit.
                "sample_count": selected_rows,
                "sse_denominator": sse.denominator,
                "sse_numerator": sse.numerator,
                "trainer_bundle_id": self._trainer_bundle_id.hex,
            },
            # Complete domain_digest only after its v1 and ridge lambda inputs are visible in
            # local exact integer linear trainer fit.
        )
        return payload, metrics

    def _require_current(self) -> None:
        # Execute the local exact integer linear trainer require current workflow in
        # explicit, reviewable steps.
        if self._build_tools.require_current(ML_TRAINER_ROLE) != self._trainer_bundle_id:
            raise ExactMlPipelineError("exact trainer identity changed")


class LocalExactFrozenPredictionBuilder:
    """Compute frozen predictions from exact mmap inputs, then publish them."""

    def __init__(
        self,
        artifacts: LocalArtifactRepository,
        publisher: LocalNumpyMlArtifactPublisher,
        *,
        # Keep the build tools input explicit in the init contract.
        build_tools: PinnedCodeBundleSet | None = None,
    ) -> None:
        # Execute the local exact frozen prediction builder init workflow in explicit,
        # reviewable steps.
        self._artifacts = artifacts
        self._publisher = publisher
        self._build_tools = build_tools or unit_ml_build_tools()
        self._inference_bundle_id = self._build_tools.require_current(ML_FROZEN_INFERENCE_ROLE)

    def build_frozen_predictions(
        # Keep the remaining build frozen predictions inputs visible at the local exact
        # frozen prediction builder build frozen predictions boundary.
        self,
        request: BuildFrozenPredictionsRequest,
    ) -> PublishedPredictionSet:
        # Execute the local exact frozen prediction builder build frozen predictions
        # workflow in explicit, reviewable steps.
        if self._build_tools.require_current(ML_FROZEN_INFERENCE_ROLE) != self._inference_bundle_id:
            raise ExactMlPipelineError("frozen inference compiler identity changed")
        if request.compiler_version != physical.COMPILER_VERSION:
            raise ExactMlPipelineError(f"compiler version must be {physical.COMPILER_VERSION!r}")
        exact_policy = ExactInferencePolicy.frozen_exact_linear(
            # Pass prediction name explicitly so frozen_exact_linear receives a reviewable
            # prediction name and value input in local exact frozen prediction builder
            # build frozen predictions.
            prediction_name=request.prediction_name,
            missing_policy=InferenceMissingPolicy(request.missing_policy.value),
            inference_delay_boundaries=request.inference_delay_boundaries,
        )
        return self._publisher.build_prediction_set(
            # Include build prediction set request in the completed local exact frozen
            # prediction builder build frozen predictions result.
            BuildPredictionSetRequest(
                replay_pack_id=request.replay_pack_id,
                replay_semantics_id=request.replay_semantics_id,
                replay_layout_schema_id=request.replay_layout_schema_id,
                feature_set_ids=request.feature_set_ids,
                # Pass model schedule id explicitly so BuildPredictionSetRequest receives
                # a reviewable replay pack id and replay semantics id input in local exact
                # frozen prediction builder build frozen predictions.
                model_schedule_id=request.model_schedule_id,
                model_bundle_ids=request.model_bundle_ids,
                prediction_name=request.prediction_name,
                inference_mode=InferenceMode.FROZEN,
                inference_policy_digest=exact_policy.inference_policy_digest,
                # Pass causal availability policy explicitly so BuildPredictionSetRequest
                # receives a reviewable replay pack id and replay semantics id input in
                # local exact frozen prediction builder build frozen predictions.
                causal_availability_policy=EXACT_PREDICTION_AVAILABILITY_POLICY,
                canonicality=request.canonicality,
                rows=self._prediction_rows(request),
                compiler_version=request.compiler_version,
            )
            # Complete build_prediction_set only after its replay pack id and replay semantics
            # id inputs are visible in local exact frozen prediction builder build frozen
            # predictions.
        )

    def _prediction_rows(
        self,
        request: BuildFrozenPredictionsRequest,
    ) -> Iterator[FrozenPredictionRow]:
        # Execute the local exact frozen prediction builder prediction rows workflow in
        # explicit, reviewable steps.
        with ExitStack() as stack:
            # Keep exit stack active only for the bounded local exact frozen prediction
            # builder prediction rows operation.
            replay = stack.enter_context(
                NumpyMmapReplaySource(
                    self._artifacts,
                    request.replay_pack_id,
                    build_tools=self._build_tools,
                    # Complete NumpyMmapReplaySource only after its artifacts and replay pack
                    # id inputs are visible in local exact frozen prediction builder
                    # prediction rows.
                )
            )
            features = tuple(
                stack.enter_context(
                    NumpyFeatureSetProvider(
                        # Pass self explicitly so NumpyFeatureSetProvider receives a
                        # reviewable artifacts and build tools input in local exact frozen
                        # prediction builder prediction rows.
                        self._artifacts,
                        feature_id,
                        build_tools=self._build_tools,
                    )
                )
                # Pass feature id explicitly so tuple receives a reviewable enter context
                # and feature set ids input in local exact frozen prediction builder
                # prediction rows.
                for feature_id in request.feature_set_ids
            )
            schedule = stack.enter_context(
                NumpyModelScheduleReader(
                    self._artifacts,
                    # Pass request explicitly so NumpyModelScheduleReader receives a
                    # reviewable artifacts and model schedule id input in local exact
                    # frozen prediction builder prediction rows.
                    request.model_schedule_id,
                    build_tools=self._build_tools,
                )
            )
            models = {
                # Keep the enter context and stack enter_context step visible while
                # building models.
                model_id: stack.enter_context(
                    NumpyModelBundleReader(
                        self._artifacts,
                        model_id,
                        build_tools=self._build_tools,
                        # Complete NumpyModelBundleReader only after its artifacts and build
                        # tools inputs are visible in local exact frozen prediction builder
                        # prediction rows.
                    )
                )
                for model_id in request.model_bundle_ids
            }
            if replay.replay_semantics_id != request.replay_semantics_id:
                # Fail the local exact frozen prediction builder prediction rows path with
                # ExactMlPipelineError for frozen inference replay pack semantics changed
                # when replay semantics id, replay and request is true; do not continue
                # ambiguously.
                raise ExactMlPipelineError("frozen inference ReplayPack semantics changed")
            if replay.replay_layout_schema_id != request.replay_layout_schema_id:
                raise ExactMlPipelineError("frozen inference ReplayPack layout changed")
            feature_count = sum(len(feature.feature_specs) for feature in features)
            if any(model.weights.size != feature_count for model in models.values()):
                # Fail the local exact frozen prediction builder prediction rows path with
                # ExactMlPipelineError for model weight count differs from exact features
                # when size, feature count and model is true; do not continue ambiguously.
                raise ExactMlPipelineError("model weight count differs from exact features")
            feature_schema = _feature_schema(features)
            if any(model.feature_schema_digest != feature_schema for model in models.values()):
                raise ExactMlPipelineError("model feature schema differs from exact features")
            if any(
                # Pass model explicitly so any receives a reviewable framework and
                # canonicality input in local exact frozen prediction builder prediction
                # rows.
                model.framework != EXACT_LINEAR_FRAMEWORK
                or model.canonicality is not ModelCanonicality.CANONICAL_EXACT
                for model in models.values()
            ):
                raise ExactMlPipelineError("frozen exact inference model is unsupported")
            # Assemble effective once so the local exact frozen prediction builder
            # prediction rows workflow shares one value.
            effective = replay.arrays()[replay_physical.ENVELOPE_BOUNDARY_ORDINAL]
            for row_id in range(replay.manifest.event_count):
                # Process range(replay.manifest.event_count) inside the bounded local
                # exact frozen prediction builder prediction rows loop.
                boundary = int(effective[row_id])
                selected_id = schedule.model_for(boundary)
                try:
                    model = models[selected_id]
                except KeyError as error:
                    # Translate the KeyError failure through the local exact frozen
                    # prediction builder prediction rows boundary.
                    raise ExactMlPipelineError(
                        "ModelSchedule selected a model outside frozen exact inputs"
                    ) from error
                selected_model_available = (model.model_available_boundary,)
                selected_fitted = model.fitted_component_available_boundaries
                # Assemble feature available once so the local exact frozen prediction
                # builder prediction rows workflow shares one value.
                feature_available = max(
                    feature.available_boundary_for_row(row_id) for feature in features
                )
                inference_start = max(
                    feature_available,
                    # Pass selected model available explicitly so max receives a
                    # reviewable feature available and selected model available input in
                    # local exact frozen prediction builder prediction rows.
                    *selected_model_available,
                    *selected_fitted,
                )
                inference_completion = inference_start + request.inference_delay_boundaries
                if inference_completion > _UINT64_MAX:
                    # Fail the local exact frozen prediction builder prediction rows path
                    # with ExactMlPipelineError for frozen inference availability exceeds
                    # uint64 when inference completion and uint64 max is true; do not
                    # continue ambiguously.
                    raise ExactMlPipelineError("frozen inference availability exceeds uint64")
                missing = False
                materialized_values: list[int] = []
                for feature in features:
                    # Process features inside the bounded local exact frozen prediction
                    # builder prediction rows loop.
                    for code in range(len(feature.feature_specs)):
                        # Process range(len(feature.feature_specs)) inside the bounded
                        # local exact frozen prediction builder prediction rows loop.
                        value = feature.materialized_value_for_offline_pipeline(code, row_id)
                        if value is None:
                            missing = True
                        else:
                            materialized_values.append(value)
                # Evaluate the complete local exact frozen prediction builder prediction
                # rows missing, missing policy and reject condition before guarded
                # effects.
                if missing and request.missing_policy is FrozenMissingPolicy.REJECT:
                    raise ExactMlPipelineError("frozen inference encountered a missing feature")
                value = None if missing else model.predict_exact(tuple(materialized_values))
                if value is not None and not _INT64_MIN <= value <= _INT64_MAX:
                    raise ExactMlPipelineError("frozen prediction exceeds checked int64 output")
                # Keep the yield step explicit within the local exact frozen prediction
                # builder prediction rows workflow.
                yield FrozenPredictionRow(
                    replay_row_id=row_id,
                    effective_boundary_ordinal=boundary,
                    inference_completion_boundary=inference_completion,
                    availability=PredictionAvailability(
                        # Pass feature available boundary explicitly so
                        # PredictionAvailability receives a reviewable feature available
                        # and selected model available input in local exact frozen
                        # prediction builder prediction rows.
                        feature_available_boundary=feature_available,
                        model_available_boundaries=selected_model_available,
                        fitted_component_available_boundaries=selected_fitted,
                        inference_completion_boundary=inference_completion,
                    ),
                    # Pass value explicitly so FrozenPredictionRow receives a reviewable
                    # prediction availability and row id input in local exact frozen
                    # prediction builder prediction rows.
                    value=value,
                )


def _feature_schema(features: tuple[NumpyFeatureSetProvider, ...]) -> ContentDigest:
    # Execute the feature schema workflow in explicit, reviewable steps.
    return domain_digest(
        "backtest.model-feature-schema.v1",
        [
            {
                "feature_set_id": feature.feature_set_id.hex,
                # Keep feature spec ids named so the v1 and feature set id payload passed
                # to domain_digest remains self-describing within feature schema.
                "feature_spec_ids": [item.feature_spec_id.hex for item in feature.feature_specs],
            }
            for feature in features
        ],
    )


# Define require absolute bound as one focused operation with an explicit boundary.
def _require_absolute_bound(value: int, maximum: int, label: str) -> None:
    # Execute the require absolute bound workflow in explicit, reviewable steps.
    if abs(value) > maximum:
        raise ExactMlPipelineError(f"{label} exceeds exact-trainer numeric bound")


def _solve_exact(
    matrix: list[list[int]],
    target: list[int],
    # Close the solve exact signature after its explicit inputs.
    *,
    maximum_fraction_bits: int,
) -> tuple[Fraction, ...]:
    # Execute the solve exact workflow in explicit, reviewable steps.
    size = len(target)
    augmented = [
        [Fraction(value) for value in matrix[row]] + [Fraction(target[row])] for row in range(size)
    ]
    for column in range(size):
        # Process range(size) inside the bounded solve exact loop.
        pivot = next(
            (row for row in range(column, size) if augmented[row][column]),
            None,
        )
        if pivot is None:
            # Fail the solve exact path with ExactMlPipelineError for exact ridge system
            # is singular when pivot is true; do not continue ambiguously.
            raise ExactMlPipelineError("exact ridge system is singular")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [
            _bounded_fraction(value / divisor, maximum_fraction_bits)
            # Keep the value component named inside the augmented[column] contract.
            for value in augmented[column]
            # Complete the augmented[column] group only after its semantic components are
            # visible.
        ]
        for row in range(size):
            # Process range(size) inside the bounded solve exact loop.
            if row == column:
                continue
            multiplier = augmented[row][column]
            if not multiplier:
                continue
            # Assemble augmented[row] once so the solve exact workflow shares one value.
            augmented[row] = [
                _bounded_fraction(
                    augmented[row][index] - multiplier * augmented[column][index],
                    maximum_fraction_bits,
                )
                # Keep the size range step visible while building augmented[row].
                for index in range(size + 1)
            ]
    return tuple(augmented[index][-1] for index in range(size))


def _bounded_fraction(value: Fraction, maximum_bits: int) -> Fraction:
    # Execute the bounded fraction workflow in explicit, reviewable steps.
    if value.numerator.bit_length() > maximum_bits or value.denominator.bit_length() > maximum_bits:
        raise ExactMlPipelineError("exact trainer fraction-growth bound exceeded")
    return value


def _fraction_payload(coefficients: tuple[Fraction, ...]) -> ExactLinearModelPayload:
    # Execute the fraction payload workflow in explicit, reviewable steps.
    divisor = 1
    for coefficient in coefficients:
        divisor = lcm(divisor, coefficient.denominator)
    numerators = [
        coefficient.numerator * (divisor // coefficient.denominator)
        # Keep the coefficient component named inside the numerators contract.
        for coefficient in coefficients
        # Complete the numerators group only after its semantic components are visible.
    ]
    common = divisor
    for numerator in numerators:
        common = gcd(common, abs(numerator))
    if common > 1:
        # Handle the fraction payload common > 1 branch as a distinct logical block.
        divisor //= common
        numerators = [value // common for value in numerators]
    minimum = -(1 << 63)
    maximum = (1 << 63) - 1
    if not 1 <= divisor <= maximum or any(not minimum <= value <= maximum for value in numerators):
        # Fail the fraction payload path with ExactMlPipelineError for exact trained
        # coefficients exceed int64 payload bounds when divisor, maximum and value is
        # true; do not continue ambiguously.
        raise ExactMlPipelineError("exact trained coefficients exceed int64 payload bounds")
    return ExactLinearModelPayload(
        weights=tuple(numerators[1:]),
        intercept=numerators[0],
        output_divisor=divisor,
        # Complete ExactLinearModelPayload only after its tuple and numerators inputs are
        # visible in fraction payload.
    )


__all__ = [
    "EXACT_FROZEN_INFERENCE_BUNDLE_ID",
    "EXACT_INTEGER_LINEAR_TRAINER_BUNDLE_ID",
    "EXACT_LINEAR_FRAMEWORK",
    # Keep the exact ml pipeline error component named inside the all contract.
    "ExactMlPipelineError",
    "LocalExactFrozenPredictionBuilder",
    "LocalExactIntegerLinearTrainer",
]
