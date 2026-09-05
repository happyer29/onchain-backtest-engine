"""Replaceable publication seams for immutable ML artifacts."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from backtest.application.ml_artifacts import (
    BuildFeatureSetRequest,
    BuildFrozenPredictionsRequest,
    # Include build label set request so the ml artifacts dependency remains explicit.
    BuildLabelSetRequest,
    BuildPredictionSetRequest,
    BuildUniverseRequest,
    PublishedFeatureSet,
    PublishedLabelSet,
    # Include published model bundle so the ml artifacts dependency remains explicit.
    PublishedModelBundle,
    PublishedModelSchedule,
    PublishedPredictionSet,
    PublishedUniverse,
    PublishModelBundleRequest,
    # Include publish model schedule request so the ml artifacts dependency remains
    # explicit.
    PublishModelScheduleRequest,
    TrainExactLinearModelRequest,
)


@runtime_checkable
class FeatureSetPublisher(Protocol):
    # Define feature set publisher build feature set as one focused operation with an
    # explicit boundary.
    def build_feature_set(self, request: BuildFeatureSetRequest) -> PublishedFeatureSet: ...


@runtime_checkable
class UniversePublisher(Protocol):
    def build_universe(self, request: BuildUniverseRequest) -> PublishedUniverse: ...


@runtime_checkable
# Keep the label set publisher contract and validation rules together.
class LabelSetPublisher(Protocol):
    def build_label_set(self, request: BuildLabelSetRequest) -> PublishedLabelSet: ...


# Keep the model bundle publisher contract and validation rules together.
@runtime_checkable
class ModelBundlePublisher(Protocol):
    def publish_model_bundle(
        self,
        request: PublishModelBundleRequest,
        # Keep the published model bundle step explicit within the model bundle publisher
        # publish model bundle workflow.
    ) -> PublishedModelBundle: ...


# Keep the model schedule publisher contract and validation rules together.
@runtime_checkable
class ModelSchedulePublisher(Protocol):
    def publish_model_schedule(
        self,
        request: PublishModelScheduleRequest,
        # Keep the published model schedule step explicit within the model schedule publisher
        # publish model schedule workflow.
    ) -> PublishedModelSchedule: ...


# Keep the prediction set publisher contract and validation rules together.
@runtime_checkable
class PredictionSetPublisher(Protocol):
    def build_prediction_set(
        self,
        request: BuildPredictionSetRequest,
        # Keep the published prediction set step explicit within the prediction set publisher
        # build prediction set workflow.
    ) -> PublishedPredictionSet: ...


# Keep the exact linear model trainer contract and validation rules together.
@runtime_checkable
class ExactLinearModelTrainer(Protocol):
    def train_exact_linear(
        self,
        request: TrainExactLinearModelRequest,
        # Keep the published model bundle step explicit within the exact linear model trainer
        # train exact linear workflow.
    ) -> PublishedModelBundle: ...


# Keep the frozen prediction builder contract and validation rules together.
@runtime_checkable
class FrozenPredictionBuilder(Protocol):
    def build_frozen_predictions(
        self,
        request: BuildFrozenPredictionsRequest,
        # Keep the published prediction set step explicit within the frozen prediction builder
        # build frozen predictions workflow.
    ) -> PublishedPredictionSet: ...


__all__ = [
    "ExactLinearModelTrainer",
    "FeatureSetPublisher",
    "FrozenPredictionBuilder",
    # Keep the label set publisher component named inside the all contract.
    "LabelSetPublisher",
    "ModelBundlePublisher",
    "ModelSchedulePublisher",
    "PredictionSetPublisher",
    "UniversePublisher",
    # Complete the all group only after its semantic components are visible.
]
