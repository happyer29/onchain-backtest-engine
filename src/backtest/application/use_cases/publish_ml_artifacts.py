"""Application orchestration for immutable point-in-time ML artifacts."""

from __future__ import annotations

from typing import NoReturn

from backtest.application.errors import WorkflowNotImplementedError
from backtest.application.ml_artifacts import (
    BuildFeatureSetRequest,
    # Include build frozen predictions request so the ml artifacts dependency remains
    # explicit.
    BuildFrozenPredictionsRequest,
    BuildLabelSetRequest,
    BuildPredictionSetRequest,
    BuildUniverseRequest,
    PublishedFeatureSet,
    # Include published label set so the ml artifacts dependency remains explicit.
    PublishedLabelSet,
    PublishedModelBundle,
    PublishedModelSchedule,
    PublishedPredictionSet,
    PublishedUniverse,
    # Include publish model bundle request so the ml artifacts dependency remains
    # explicit.
    PublishModelBundleRequest,
    PublishModelScheduleRequest,
    TrainExactLinearModelRequest,
)
from backtest.application.ports.ml_artifacts import (
    # Include exact linear model trainer so the ml artifacts dependency remains explicit.
    ExactLinearModelTrainer,
    FeatureSetPublisher,
    FrozenPredictionBuilder,
    LabelSetPublisher,
    ModelBundlePublisher,
    # Include model schedule publisher so the ml artifacts dependency remains explicit.
    ModelSchedulePublisher,
    PredictionSetPublisher,
    UniversePublisher,
)


# Keep the build feature set contract and validation rules together.
class BuildFeatureSet:
    def __init__(self, publisher: FeatureSetPublisher | None = None) -> None:
        self._publisher = publisher

    def execute(self, request: BuildFeatureSetRequest) -> PublishedFeatureSet:
        # Execute the build feature set execute workflow in explicit, reviewable steps.
        if self._publisher is None:
            _unavailable("build-feature-set")
        return self._publisher.build_feature_set(request)


# Keep the build universe contract and validation rules together.
class BuildUniverse:
    def __init__(self, publisher: UniversePublisher | None = None) -> None:
        self._publisher = publisher

    def execute(self, request: BuildUniverseRequest) -> PublishedUniverse:
        # Execute the build universe execute workflow in explicit, reviewable steps.
        if self._publisher is None:
            _unavailable("build-universe")
        return self._publisher.build_universe(request)


# Keep the build label set contract and validation rules together.
class BuildLabelSet:
    def __init__(self, publisher: LabelSetPublisher | None = None) -> None:
        self._publisher = publisher

    def execute(self, request: BuildLabelSetRequest) -> PublishedLabelSet:
        # Execute the build label set execute workflow in explicit, reviewable steps.
        if self._publisher is None:
            _unavailable("build-label-set")
        return self._publisher.build_label_set(request)


# Keep the publish model bundle contract and validation rules together.
class PublishModelBundle:
    def __init__(self, publisher: ModelBundlePublisher | None = None) -> None:
        self._publisher = publisher

    def execute(self, request: PublishModelBundleRequest) -> PublishedModelBundle:
        # Execute the publish model bundle execute workflow in explicit, reviewable steps.
        if self._publisher is None:
            _unavailable("publish-model-bundle")
        return self._publisher.publish_model_bundle(request)


# Keep the publish model schedule contract and validation rules together.
class PublishModelSchedule:
    def __init__(self, publisher: ModelSchedulePublisher | None = None) -> None:
        self._publisher = publisher

    def execute(self, request: PublishModelScheduleRequest) -> PublishedModelSchedule:
        # Execute the publish model schedule execute workflow in explicit, reviewable
        # steps.
        if self._publisher is None:
            _unavailable("publish-model-schedule")
        return self._publisher.publish_model_schedule(request)


# Keep the build prediction set contract and validation rules together.
class BuildPredictionSet:
    def __init__(self, publisher: PredictionSetPublisher | None = None) -> None:
        self._publisher = publisher

    def execute(self, request: BuildPredictionSetRequest) -> PublishedPredictionSet:
        # Execute the build prediction set execute workflow in explicit, reviewable steps.
        if self._publisher is None:
            _unavailable("build-prediction-set")
        return self._publisher.build_prediction_set(request)


# Keep the train exact linear model contract and validation rules together.
class TrainExactLinearModel:
    def __init__(self, trainer: ExactLinearModelTrainer | None = None) -> None:
        self._trainer = trainer

    def execute(self, request: TrainExactLinearModelRequest) -> PublishedModelBundle:
        # Execute the train exact linear model execute workflow in explicit, reviewable
        # steps.
        if self._trainer is None:
            _unavailable("train-exact-linear-model")
        return self._trainer.train_exact_linear(request)


# Keep the build frozen predictions contract and validation rules together.
class BuildFrozenPredictions:
    def __init__(self, builder: FrozenPredictionBuilder | None = None) -> None:
        self._builder = builder

    def execute(self, request: BuildFrozenPredictionsRequest) -> PublishedPredictionSet:
        # Execute the build frozen predictions execute workflow in explicit, reviewable
        # steps.
        if self._builder is None:
            _unavailable("build-frozen-predictions")
        return self._builder.build_frozen_predictions(request)


def _unavailable(workflow: str) -> NoReturn:
    # Execute the unavailable workflow in explicit, reviewable steps.
    raise WorkflowNotImplementedError(
        workflow,
        required_architecture_sections=(14, 15, 24, 25, 33),
    )


__all__ = [
    # Keep the build feature set component named inside the all contract.
    "BuildFeatureSet",
    "BuildFrozenPredictions",
    "BuildLabelSet",
    "BuildPredictionSet",
    "BuildUniverse",
    # Keep the publish model bundle component named inside the all contract.
    "PublishModelBundle",
    "PublishModelSchedule",
    "TrainExactLinearModel",
]
