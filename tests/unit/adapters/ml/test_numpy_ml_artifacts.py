# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import io
import json
import shutil
from collections.abc import Callable, Iterable, Iterator

# Import dataclasses at the visible module dependency boundary.
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

import numpy as np
import pytest

# Import repository at the visible module dependency boundary.
from backtest.adapters.artifacts.localfs.repository import (
    ArtifactIntegrityError,
    LocalArtifactRepository,
)
from backtest.adapters.columnar.numpy import layout as replay_physical

# Import compiler at the visible module dependency boundary.
from backtest.adapters.columnar.numpy.compiler import LocalNumpyReplayPackCompiler
from backtest.adapters.columnar.numpy.reader import NumpyMmapReplaySource
from backtest.adapters.ml.numpy import layout as ml_physical
from backtest.adapters.ml.numpy.builders import (
    REFERENCE_ALL_ROWS_UNIVERSE_BUNDLE_ID,
    # Include reference all rows universe config digest so the builders dependency remains
    # explicit.
    REFERENCE_ALL_ROWS_UNIVERSE_CONFIG_DIGEST,
    REFERENCE_ALL_ROWS_UNIVERSE_SPEC_ID,
    REFERENCE_FEATURE_BUILDER_BUNDLE_ID,
    REFERENCE_HORIZON_LABEL_BUILDER_BUNDLE_ID,
    REFERENCE_HORIZON_LABEL_CONFIG_DIGEST,
    # Include reference horizon label spec id so the builders dependency remains explicit.
    REFERENCE_HORIZON_LABEL_SPEC_ID,
    LocalReferenceMlRowBuilders,
)
from backtest.adapters.ml.numpy.embedded import EmbeddedExactInferenceError
from backtest.adapters.ml.numpy.overlays import LocalNumpyCausalOverlayFactory

# Import pipelines at the visible module dependency boundary.
from backtest.adapters.ml.numpy.pipelines import (
    EXACT_INTEGER_LINEAR_TRAINER_BUNDLE_ID,
    EXACT_LINEAR_FRAMEWORK,
    LocalExactFrozenPredictionBuilder,
    LocalExactIntegerLinearTrainer,
    # Close the pipelines import after its required symbols are visible.
)
from backtest.adapters.ml.numpy.publisher import (
    LocalNumpyMlArtifactPublisher,
    NumpyMlArtifactCompileError,
)

# Import reader at the visible module dependency boundary.
from backtest.adapters.ml.numpy.reader import (
    NumpyFeatureSetProvider,
    NumpyMlArtifactFormatError,
    NumpyModelBundleReader,
    NumpyModelScheduleReader,
    # Include numpy prediction set provider so the reader dependency remains explicit.
    NumpyPredictionSetProvider,
    NumpyUniverseReader,
)
from backtest.adapters.ml.numpy.toolchain import unit_ml_build_tools
from backtest.adapters.ml.numpy.training import NumpyLabelSetReader

# Import build tool roles at the visible module dependency boundary.
from backtest.application.build_tool_roles import (
    ML_COMPILER_ROLE,
    ML_FEATURE_BUILDER_ROLE,
    ML_FROZEN_INFERENCE_ROLE,
    ML_LABEL_BUILDER_ROLE,
    # Include ml trainer role so the build tool roles dependency remains explicit.
    ML_TRAINER_ROLE,
    ML_UNIVERSE_BUILDER_ROLE,
    ML_WRITER_ROLE,
)
from backtest.application.code_bundles import (
    # Include pinned code bundle identity so the code bundles dependency remains explicit.
    PinnedCodeBundleIdentity,
    PinnedCodeBundleSet,
)
from backtest.application.ml_artifacts import (
    BuildFeatureSetRequest,
    # Include build frozen predictions request so the ml artifacts dependency remains
    # explicit.
    BuildFrozenPredictionsRequest,
    BuildLabelSetRequest,
    BuildPredictionSetRequest,
    BuildUniverseRequest,
    ExactLinearModelPayload,
    # Include feature overlay row so the ml artifacts dependency remains explicit.
    FeatureOverlayRow,
    FrozenMissingPolicy,
    FrozenPredictionRow,
    LabelOverlayRow,
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
    UniverseMembershipRow,
)

# Import ml contracts at the visible module dependency boundary.
from backtest.application.ml_contracts import (
    EXACT_PREDICTION_AVAILABILITY_POLICY,
    ExactInferencePolicy,
    FeatureSpec,
    InferenceMissingPolicy,
    # Include inference mode so the ml contracts dependency remains explicit.
    InferenceMode,
    ModelCanonicality,
    ModelSchedule,
    ModelScheduleEntry,
    ModelUnavailableError,
    # Include null policy so the ml contracts dependency remains explicit.
    NullPolicy,
    PredictionAvailability,
    TemporalSplit,
    TrainingJobSpec,
)

# Import ml job commands at the visible module dependency boundary.
from backtest.application.ml_job_commands import (
    ResolvedBuildFeaturesJob,
    ResolvedBuildLabelsJob,
    ResolvedBuildUniverseJob,
)

# Import models at the visible module dependency boundary.
from backtest.application.models import ArtifactDraft, ArtifactKind
from backtest.application.run_drafts import ReferenceRunDraft
from backtest.application.run_specs import AssetBalance, ResolvedRunSpec
from backtest.application.use_cases.publish_ml_artifacts import (
    BuildFeatureSet,
    # Include build frozen predictions so the publish ml artifacts dependency remains
    # explicit.
    BuildFrozenPredictions,
    BuildLabelSet,
    BuildPredictionSet,
    BuildUniverse,
    PublishModelBundle,
    # Include publish model schedule so the publish ml artifacts dependency remains
    # explicit.
    PublishModelSchedule,
    TrainExactLinearModel,
)
from backtest.bootstrap.reference_run_resolver import (
    ReferenceRunResolutionError,
    # Include reference run spec resolver so the reference run resolver dependency remains
    # explicit.
    ReferenceRunSpecResolver,
)
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
    # Close the chain import after its required symbols are visible.
)
from backtest.domain.event_hashing import canonical_event_stream_hash
from backtest.domain.execution import ExecutionMode, ExecutionNotification
from backtest.domain.fidelity import OrderingFidelity
from backtest.domain.hashing import canonical_json_bytes, domain_digest

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import (
    AccountId,
    AssetId,
    BundleId,
    CapabilityId,
    # Include content digest so the identifiers dependency remains explicit.
    ContentDigest,
    DatasetRevisionId,
    FeatureSetId,
    LogicalContentHash,
    ModelBundleId,
    # Include model schedule id so the identifiers dependency remains explicit.
    ModelScheduleId,
    OrderId,
    PoolId,
    PredictionSetId,
    ProtocolPayloadSchemaId,
    # Include replay pack id so the identifiers dependency remains explicit.
    ReplayPackId,
    RuntimeLockId,
    SnapshotId,
    VenueId,
)

# Import intents at the visible module dependency boundary.
from backtest.domain.intents import SwapExactInIntent
from backtest.domain.market_events import (
    BlockEvent,
    CanonicalEvent,
    ChainPosition,
    # Include event envelope so the market events dependency remains explicit.
    EventEnvelope,
    TokenCreationEvent,
)
from backtest.engine.causal_data import CausalScalarProvider
from backtest.engine.contracts import EnginePhysicalSettings, StrategyContext

# Import reference at the visible module dependency boundary.
from backtest.engine.reference import (
    ReferenceBacktestEngine,
    ReferenceRunConfig,
    RunSummary,
    SlotLatencyModel,
    # Close the reference import after its required symbols are visible.
)
from backtest.engine.replay import ReplayBoundary
from backtest.plugins.execution import ConstantProductExecutionModel
from backtest.plugins.risk import StaticRiskPolicy
from tests.support.replay_v3 import fixture_snapshot_manifest


# Keep the canonical source contract and validation rules together.
class _CanonicalSource:
    def __init__(self, events: tuple[CanonicalEvent, ...]) -> None:
        self._events = events

    @property
    def dataset_revision_id(self) -> DatasetRevisionId:
        # Return the completed canonical source dataset revision id result without a
        # hidden fallback.
        return DatasetRevisionId("d" * 64)

    @property
    def logical_content_hash(self) -> LogicalContentHash:
        return canonical_event_stream_hash(self._events)

    @property
    # Define canonical source replay semantics id as one focused operation with an
    # explicit boundary.
    def replay_semantics_id(self) -> ContentDigest:
        # Execute the canonical source replay semantics id workflow in explicit,
        # reviewable steps.
        from backtest.application.replay_packs import ReplaySemanticsManifest

        return ReplaySemanticsManifest.canonical_v3().replay_semantics_id

    def boundaries(self) -> tuple[ReplayBoundary, ...]:
        # Execute the canonical source boundaries workflow in explicit, reviewable steps.
        result: list[ReplayBoundary] = []
        previous: int | None = None
        for event in self._events:
            # Process self._events inside the bounded canonical source boundaries loop.
            ordinal = event.envelope.boundary_ordinal
            if ordinal != previous:
                # Handle the canonical source boundaries ordinal != previous branch as a
                # distinct logical block.
                result.append(ReplayBoundary.from_position(event.envelope.position))
                previous = ordinal
        return tuple(result)

    def events(self) -> Iterator[CanonicalEvent]:
        yield from self._events


# Keep the prediction driven strategy contract and validation rules together.
@dataclass(frozen=True, slots=True)
class _PredictionDrivenStrategy:
    prediction_name: str

    @property
    def bundle_id(self) -> BundleId:
        # Return the completed prediction driven strategy bundle id result without a
        # hidden fallback.
        return _bundle("prediction-driven-strategy")

    @property
    def component_id(self) -> ContentDigest:
        return _digest("prediction-driven-strategy-config")

    def on_event(
        # Keep the remaining on event inputs visible at the prediction driven strategy on
        # event boundary.
        self,
        event: CanonicalEvent,
        context: StrategyContext,
    ) -> Iterable[SwapExactInIntent]:
        # Execute the prediction driven strategy on event workflow in explicit, reviewable
        # steps.
        if isinstance(event, BlockEvent):
            return ()
        prediction = context.predictions.current(self.prediction_name)
        if prediction is None or prediction <= 0:
            return ()
        # Assemble order id once so the prediction driven strategy on event workflow
        # shares one value.
        order_id = OrderId(
            domain_digest(
                "test.prediction-driven-order.v1",
                {
                    "event_id": event.envelope.canonical_event_id.hex,
                    # Keep prediction named so the v1 and event id payload passed to
                    # domain_digest remains self-describing within prediction driven
                    # strategy on event.
                    "prediction": prediction,
                },
            ).hex
        )
        return (
            # Include swap exact in intent in the completed prediction driven strategy on
            # event result.
            SwapExactInIntent(
                order_id=order_id,
                pool_id=PoolId("unmodeled-pool"),
                sold_asset_id=AssetId("SOL"),
                bought_asset_id=AssetId("TOKEN"),
                # Pass amount in atomic explicitly so SwapExactInIntent receives a
                # reviewable unmodeled-pool and sol input in prediction driven strategy on
                # event.
                amount_in_atomic=1,
                minimum_amount_out_atomic=0,
                created_boundary_ordinal=context.instant.boundary_ordinal,
            ),
        )

    # Define prediction driven strategy on execution as one focused operation with an
    # explicit boundary.
    def on_execution(
        self,
        notification: ExecutionNotification,
        context: StrategyContext,
    ) -> None:
        # Discard notification after its boundary-only use.
        del notification, context


# Keep the ml stack contract and validation rules together.
@dataclass(frozen=True, slots=True)
class _MlStack:
    artifacts: LocalArtifactRepository
    replay_pack_id: ReplayPackId
    feature: PublishedFeatureSet
    # Declare universe explicitly in the ml stack contract.
    universe: PublishedUniverse
    labels: PublishedLabelSet
    models: tuple[PublishedModelBundle, PublishedModelBundle]
    schedule: PublishedModelSchedule
    predictions: PublishedPredictionSet
    # Declare effective explicitly in the ml stack contract.
    effective: tuple[int, ...]
    feature_rows: tuple[FeatureOverlayRow, ...]


def test_phase6_artifacts_are_committed_mmap_causal_and_training_separated(
    tmp_path: Path,
) -> None:
    # Execute the test phase6 artifacts are committed mmap causal and training separated
    # workflow in explicit, reviewable steps.
    stack = _publish_stack(tmp_path, maximum_rows_in_memory=1)
    assert stack.feature.artifact.kind is ArtifactKind.FEATURE_SET
    assert stack.universe.artifact.kind is ArtifactKind.UNIVERSE
    assert stack.labels.artifact.kind is ArtifactKind.LABEL_SET
    assert stack.schedule.artifact.kind is ArtifactKind.MODEL_SCHEDULE
    # Verify the kind, prediction set and artifact relationship before this scenario is
    # accepted.
    assert stack.predictions.artifact.kind is ArtifactKind.PREDICTION_SET

    with NumpyFeatureSetProvider(stack.artifacts, stack.feature.feature_set_id) as features:
        # Keep numpy feature set provider, artifacts and feature set id active only for
        # the bounded test phase6 artifacts are committed mmap causal and training
        # separated operation.
        assert isinstance(features, CausalScalarProvider)
        code = features.feature_code(features.feature_specs[0].name)
        row = stack.feature_rows[0]
        assert (
            features.value_at_code(code, row.replay_row_id, row.available_boundary_ordinal - 1)
            # Verify the value at code, code and replay row id relationship before this
            # scenario is accepted.
            is None
        )
        expected = row.values[code]
        assert (
            features.value_at_code(code, row.replay_row_id, row.available_boundary_ordinal)
            # Keep the expected expectation tied to expected, value at code and code in
            # this scenario.
            == expected
        )
        assert all(
            isinstance(array, np.memmap) and not array.flags.writeable
            for array in features.arrays.values()
            # Complete all only after its memmap and writeable inputs are visible in test
            # phase6 artifacts are committed mmap causal and training separated.
        )

    with NumpyUniverseReader(stack.artifacts, stack.universe.universe_id) as universe:
        # Keep numpy universe reader, artifacts and universe id active only for the
        # bounded test phase6 artifacts are committed mmap causal and training separated
        # operation.
        assert universe.contains(42, 0)
        assert universe.contains(42, stack.effective[-1])
        assert not universe.contains(42, stack.effective[-1] + 100)

    with NumpyLabelSetReader(stack.artifacts, stack.labels.label_set_id) as labels:
        # Keep numpy label set reader, artifacts and label set id active only for the
        # bounded test phase6 artifacts are committed mmap causal and training separated
        # operation.
        assert not isinstance(labels, CausalScalarProvider)
        assert not hasattr(labels, "value_at")
        training_row = labels.row_for_training(0)
        assert training_row is not None
        assert training_row.future_boundary_used == 15

    # Acquire numpy model bundle reader, artifacts and model bundle id at an explicit test
    # phase6 artifacts are committed mmap causal and training separated context boundary
    # so cleanup remains scoped.
    with NumpyModelBundleReader(stack.artifacts, stack.models[0].model_bundle_id) as model:
        # Keep numpy model bundle reader, artifacts and model bundle id active only for
        # the bounded test phase6 artifacts are committed mmap causal and training
        # separated operation.
        assert not model.weights.flags.writeable
        assert model.weights.tolist() in ([1, 2], [3, 4])
        assert model.output_divisor == 10
        assert model.predict_exact((0, 0)) == 0

    with NumpyModelScheduleReader(stack.artifacts, stack.schedule.model_schedule_id) as schedule:
        # Keep numpy model schedule reader, artifacts and model schedule id active only
        # for the bounded test phase6 artifacts are committed mmap causal and training
        # separated operation.
        assert schedule.model_for(stack.effective[0]) in {
            item.model_bundle_id for item in stack.models
        }
        with pytest.raises(ModelUnavailableError, match="MODEL_UNAVAILABLE"):
            schedule.model_for(stack.effective[-1] + 100)

    # Acquire numpy prediction set provider, artifacts and prediction set id at an
    # explicit test phase6 artifacts are committed mmap causal and training separated
    # context boundary so cleanup remains scoped.
    with NumpyPredictionSetProvider(
        stack.artifacts, stack.predictions.prediction_set_id
    ) as predictions:
        # Keep numpy prediction set provider, artifacts and prediction set id active only
        # for the bounded test phase6 artifacts are committed mmap causal and training
        # separated operation.
        assert isinstance(predictions, CausalScalarProvider)
        assert predictions.model_schedule_id == stack.schedule.model_schedule_id
        early_release = predictions.available_boundary_for_row(0)
        assert early_release == stack.effective[0] + 2
        assert predictions.value_at(predictions.prediction_name, 0, early_release - 1) is None
        # Verify the value at, prediction name and early release relationship before this
        # scenario is accepted.
        assert predictions.value_at(predictions.prediction_name, 0, early_release) == 100
        assert predictions.value_at("unknown", 0, early_release) is None


def test_reference_resolver_rejects_prediction_from_another_model_schedule(
    tmp_path: Path,
) -> None:
    # Execute the test reference resolver rejects prediction from another model schedule
    # workflow in explicit, reviewable steps.
    stack = _publish_stack(tmp_path)
    with NumpyModelScheduleReader(
        stack.artifacts,
        stack.schedule.model_schedule_id,
    ) as committed:
        # Keep numpy model schedule reader, artifacts and model schedule id active only
        # for the bounded test reference resolver rejects prediction from another model
        # schedule operation.
        alternate = PublishModelSchedule(_publisher(stack.artifacts)).execute(
            PublishModelScheduleRequest(
                schedule=ModelSchedule(
                    entries=committed.schedule.entries,
                    fallback_model_bundle_id=stack.models[0].model_bundle_id,
                    # Complete ModelSchedule only after its entries and schedule inputs are
                    # visible in test reference resolver rejects prediction from another model
                    # schedule.
                ),
                canonicality=ModelCanonicality.CANONICAL_EXACT,
                compiler_version=ml_physical.COMPILER_VERSION,
            )
        )

    # Acquire raises, reference run resolution error and pytest at an explicit test
    # reference resolver rejects prediction from another model schedule context boundary
    # so cleanup remains scoped.
    with pytest.raises(
        ReferenceRunResolutionError,
        match="PredictionSet references another ModelSchedule",
    ):
        # Keep raises, reference run resolution error and pytest active only for the
        # bounded test reference resolver rejects prediction from another model schedule
        # operation.
        ReferenceRunSpecResolver(
            stack.artifacts,
            _runtime("ml"),
            parquet_memory_limit_mb=256,
            threads=1,
            # Complete ReferenceRunSpecResolver only after its ml and artifacts inputs are
            # visible in test reference resolver rejects prediction from another model
            # schedule.
        ).resolve(
            ReferenceRunDraft(
                snapshot_id=_snapshot_id(stack),
                replay_pack_id=stack.replay_pack_id,
                delivery_schedule_id=None,
                # Pass pool id explicitly to resolve for pool and sol.
                pool_id=PoolId("pool"),
                sold_asset_id=AssetId("SOL"),
                bought_asset_id=AssetId("TOKEN"),
                amount_in_atomic=100,
                minimum_amount_out_atomic=0,
                # Pass fee bps explicitly so ReferenceRunDraft receives a reviewable pool
                # and sol input in test reference resolver rejects prediction from another
                # model schedule.
                fee_bps=30,
                execution_mode=ExecutionMode.SHADOW_STATE_REPLAY,
                maximum_order_input_atomic=1_000,
                observation_slots=0,
                order_slots=0,
                # Pass initial portfolio explicitly to resolve for pool and sol.
                initial_portfolio=(AssetBalance(AssetId("SOL"), 1_000),),
                root_seed=42,
                maximum_dynamic_items=10_000,
                feature_set_ids=(stack.feature.feature_set_id,),
                model_schedule_id=alternate.model_schedule_id,
                # Pass prediction set ids explicitly so ReferenceRunDraft receives a
                # reviewable pool and sol input in test reference resolver rejects
                # prediction from another model schedule.
                prediction_set_ids=(stack.predictions.prediction_set_id,),
                inference_policy=_frozen_policy(),
            )
        )


def test_allowlisted_reference_builders_execute_feature_universe_label_slice(
    # Keep the tmp path input explicit in the test allowlisted reference builders execute
    # feature universe label slice contract.
    tmp_path: Path,
) -> None:
    # Execute the test allowlisted reference builders execute feature universe label slice
    # workflow in explicit, reviewable steps.
    stack = _publish_stack(tmp_path, maximum_rows_in_memory=1)
    replay_semantics, replay_layout = _replay_ids(stack)
    runtime_lock = _runtime("ml")
    builders = LocalReferenceMlRowBuilders(
        stack.artifacts,
        # Pass runtime lock id explicitly so LocalReferenceMlRowBuilders receives a
        # reviewable artifacts and stack input in test allowlisted reference builders
        # execute feature universe label slice.
        runtime_lock_id=runtime_lock,
    )
    publisher = _publisher(stack.artifacts)
    feature_spec = FeatureSpec(
        name="event_boundary_ordinal",
        # Pass version explicitly so FeatureSpec receives a reviewable event boundary
        # ordinal and replay row id input in test allowlisted reference builders execute
        # feature universe label slice.
        version=1,
        entity_key="replay_row_id",
        input_ids=(),
        effective_time_semantics="replay-event-boundary-v1",
        available_time_semantics="event-boundary-plus-warmup-v1",
        # Pass warmup boundaries explicitly so FeatureSpec receives a reviewable event
        # boundary ordinal and replay row id input in test allowlisted reference builders
        # execute feature universe label slice.
        warmup_boundaries=0,
        dtype="<i8",
        null_policy=NullPolicy.FORBID,
        code_bundle_id=REFERENCE_FEATURE_BUILDER_BUNDLE_ID,
        runtime_lock_id=runtime_lock,
        # Complete FeatureSpec only after its event boundary ordinal and replay row id inputs
        # are visible in test allowlisted reference builders execute feature universe label
        # slice.
    )
    feature_command = ResolvedBuildFeaturesJob(
        replay_pack_id=stack.replay_pack_id,
        replay_semantics_id=replay_semantics,
        replay_layout_schema_id=replay_layout,
        # Pass feature specs explicitly so ResolvedBuildFeaturesJob receives a reviewable
        # replay pack id and compiler version input in test allowlisted reference builders
        # execute feature universe label slice.
        feature_specs=(feature_spec,),
        input_feature_set_ids=(),
        compiler_version=ml_physical.COMPILER_VERSION,
    )
    feature = BuildFeatureSet(publisher).execute(
        # Keep the publication request and feature command publication_request step
        # visible while building feature.
        feature_command.publication_request(builders.feature_rows(feature_command))
    )
    universe_command = ResolvedBuildUniverseJob(
        snapshot_id=_snapshot_id(stack),
        universe_spec_id=REFERENCE_ALL_ROWS_UNIVERSE_SPEC_ID,
        # Pass input feature set ids explicitly so ResolvedBuildUniverseJob receives a
        # reviewable feature set id and compiler version input in test allowlisted
        # reference builders execute feature universe label slice.
        input_feature_set_ids=(feature.feature_set_id,),
        builder_bundle_id=REFERENCE_ALL_ROWS_UNIVERSE_BUNDLE_ID,
        builder_config_digest=REFERENCE_ALL_ROWS_UNIVERSE_CONFIG_DIGEST,
        compiler_version=ml_physical.COMPILER_VERSION,
    )
    # Assemble universe once so the test allowlisted reference builders execute feature
    # universe label slice workflow shares one value.
    universe = BuildUniverse(publisher).execute(
        universe_command.publication_request(builders.universe_rows(universe_command))
    )
    label_command = ResolvedBuildLabelsJob(
        snapshot_id=_snapshot_id(stack),
        # Pass universe id explicitly so ResolvedBuildLabelsJob receives a reviewable
        # universe id and effective input in test allowlisted reference builders execute
        # feature universe label slice.
        universe_id=universe.universe_id,
        label_spec_id=REFERENCE_HORIZON_LABEL_SPEC_ID,
        label_builder_bundle_id=REFERENCE_HORIZON_LABEL_BUILDER_BUNDLE_ID,
        label_config_digest=REFERENCE_HORIZON_LABEL_CONFIG_DIGEST,
        training_cutoff=max(stack.effective) + 1,
        # Pass compiler version explicitly so ResolvedBuildLabelsJob receives a reviewable
        # universe id and effective input in test allowlisted reference builders execute
        # feature universe label slice.
        compiler_version=ml_physical.COMPILER_VERSION,
    )
    labels = BuildLabelSet(publisher).execute(
        label_command.publication_request(builders.label_rows(label_command))
    )

    # Acquire numpy feature set provider, artifacts and feature set id at an explicit test
    # allowlisted reference builders execute feature universe label slice context boundary
    # so cleanup remains scoped.
    with NumpyFeatureSetProvider(stack.artifacts, feature.feature_set_id) as provider:
        # Keep numpy feature set provider, artifacts and feature set id active only for
        # the bounded test allowlisted reference builders execute feature universe label
        # slice operation.
        assert (
            tuple(
                provider.materialized_value_for_offline_pipeline(0, row)
                for row in range(provider.manifest.row_count)
            )
            # Keep the stack expectation tied to effective, stack and materialized value
            # for offline pipeline in this scenario.
            == stack.effective
        )
    with NumpyUniverseReader(stack.artifacts, universe.universe_id) as reader:
        assert all(reader.contains(row, boundary) for row, boundary in enumerate(stack.effective))
    with NumpyLabelSetReader(stack.artifacts, labels.label_set_id) as reader:
        # Verify the value, effective and row relationship before this scenario is
        # accepted.
        assert tuple(row.value for row in reader.rows_for_training()) == (1,) * len(stack.effective)


def test_build_key_is_separate_from_committed_ml_content_identity(tmp_path: Path) -> None:
    # Execute the test build key is separate from committed ml content identity workflow
    # in explicit, reviewable steps.
    stack = _publish_stack(tmp_path, maximum_rows_in_memory=1)
    publisher = LocalNumpyMlArtifactPublisher(
        stack.artifacts,
        runtime_lock_id=_runtime("another-runtime"),
        maximum_rows_in_memory=3,
        # Pass maximum open spill files explicitly so LocalNumpyMlArtifactPublisher
        # receives a reviewable another-runtime and artifacts input in test build key is
        # separate from committed ml content identity.
        maximum_open_spill_files=2,
    )
    first = stack.feature
    rebuilt = BuildFeatureSet(publisher).execute(
        BuildFeatureSetRequest(
            # Pass replay pack id explicitly so BuildFeatureSetRequest receives a
            # reviewable replay pack id and feature rows input in test build key is
            # separate from committed ml content identity.
            replay_pack_id=stack.replay_pack_id,
            replay_semantics_id=_replay_ids(stack)[0],
            replay_layout_schema_id=_replay_ids(stack)[1],
            feature_specs=_feature_specs(),
            input_feature_set_ids=(),
            # Keep the reversed and feature rows tuple step visible while building
            # rebuilt.
            rows=tuple(reversed(stack.feature_rows)),
            compiler_version=ml_physical.COMPILER_VERSION,
        )
    )

    assert rebuilt.requested_build.build_key != first.requested_build.build_key
    # Verify the feature set id, rebuilt and first relationship before this scenario is
    # accepted.
    assert rebuilt.feature_set_id == first.feature_set_id
    assert rebuilt.manifest.build.build_key == first.manifest.build.build_key
    assert rebuilt.artifact.build_key == rebuilt.manifest.build.build_key
    assert rebuilt.build_key != ContentDigest(rebuilt.feature_set_id.hex)
    assert "build" not in rebuilt.manifest.identity_document()


# Define test exact trainer reads training only ports and fits without row materialization
# as one focused operation with an explicit boundary.
def test_exact_trainer_reads_training_only_ports_and_fits_without_row_materialization(
    tmp_path: Path,
) -> None:
    # Execute the test exact trainer reads training only ports and fits without row
    # materialization workflow in explicit, reviewable steps.
    stack = _publish_stack(tmp_path)
    publisher = _publisher(stack.artifacts)
    training_universe = BuildUniverse(publisher).execute(
        BuildUniverseRequest(
            snapshot_id=_snapshot_id(stack),
            # Keep the trainer-universe _digest step visible while building training
            # universe.
            universe_spec_id=_digest("trainer-universe"),
            input_feature_set_ids=(stack.feature.feature_set_id,),
            builder_bundle_id=_bundle("trainer-universe-builder"),
            builder_config_digest=_digest("trainer-universe-config"),
            rows=(
                # Keep the universe membership row and effective UniverseMembershipRow
                # step visible while building training universe.
                UniverseMembershipRow(
                    entity_id=0,
                    eligible_from=stack.effective[0] + 1,
                    eligible_until=stack.effective[2],
                    input_available_boundary=stack.effective[0] + 1,
                    # Complete UniverseMembershipRow only after its effective and stack inputs
                    # are visible in test exact trainer reads training only ports and fits
                    # without row materialization.
                ),
            ),
            compiler_version=ml_physical.COMPILER_VERSION,
        )
    )
    # Assemble training labels once so the test exact trainer reads training only ports
    # and fits without row materialization workflow shares one value.
    training_labels = BuildLabelSet(publisher).execute(
        BuildLabelSetRequest(
            snapshot_id=_snapshot_id(stack),
            universe_id=training_universe.universe_id,
            label_spec_id=_digest("trainer-label"),
            # Keep the trainer-label-builder _bundle step visible while building training
            # labels.
            label_builder_bundle_id=_bundle("trainer-label-builder"),
            label_config_digest=_digest("trainer-label-config"),
            training_cutoff=stack.effective[2],
            rows=(
                LabelOverlayRow(
                    # Pass replay row id explicitly so LabelOverlayRow receives a
                    # reviewable effective and stack input in test exact trainer reads
                    # training only ports and fits without row materialization.
                    replay_row_id=0,
                    effective_boundary_ordinal=stack.effective[0] + 1,
                    future_boundary_used=stack.effective[0] + 1,
                    value=10,
                ),
                # Complete BuildLabelSetRequest only after its trainer-label and trainer-
                # label-builder inputs are visible in test exact trainer reads training only
                # ports and fits without row materialization.
            ),
            compiler_version=ml_physical.COMPILER_VERSION,
        )
    )
    training_spec = TrainingJobSpec(
        # Pass feature set ids explicitly so TrainingJobSpec receives a reviewable exact-
        # ridge-hyperparameters and exact-trainer input in test exact trainer reads
        # training only ports and fits without row materialization.
        feature_set_ids=(stack.feature.feature_set_id,),
        label_set_id=training_labels.label_set_id,
        universe_id=training_universe.universe_id,
        split=TemporalSplit(
            stack.effective[0],
            # Pass stack explicitly so TemporalSplit receives a reviewable effective and
            # stack input in test exact trainer reads training only ports and fits without
            # row materialization.
            stack.effective[2],
            stack.effective[2],
            stack.effective[2] + 10,
            purge_boundaries=0,
            embargo_boundaries=0,
            # Complete TemporalSplit only after its effective and stack inputs are visible in
            # test exact trainer reads training only ports and fits without row
            # materialization.
        ),
        hyperparameter_digest=_digest("exact-ridge-hyperparameters"),
        root_seeds=(7,),
        training_cutoff=stack.effective[2],
        modeled_available_boundary=stack.effective[2] + 1,
        # Pass trainer bundle id explicitly so TrainingJobSpec receives a reviewable
        # exact-ridge-hyperparameters and exact-trainer input in test exact trainer reads
        # training only ports and fits without row materialization.
        trainer_bundle_id=EXACT_INTEGER_LINEAR_TRAINER_BUNDLE_ID,
        runtime_lock_id=_runtime("exact-trainer"),
    )
    trainer = LocalExactIntegerLinearTrainer(
        stack.artifacts,
        # Pass publisher explicitly so LocalExactIntegerLinearTrainer receives a
        # reviewable artifacts and stack input in test exact trainer reads training only
        # ports and fits without row materialization.
        publisher,
        maximum_training_rows=2,
        maximum_features=2,
    )
    trained = TrainExactLinearModel(trainer).execute(
        # Keep the train exact linear model request and training spec
        # TrainExactLinearModelRequest step visible while building trained.
        TrainExactLinearModelRequest(
            training_spec=training_spec,
            feature_schema_digest=_feature_schema(stack.feature, _feature_specs()),
            preprocessing_digest=_digest("no-preprocessing"),
            calibration_digest=_digest("no-calibration"),
            # Pass ridge lambda explicitly so TrainExactLinearModelRequest receives a
            # reviewable no-preprocessing and no-calibration input in test exact trainer
            # reads training only ports and fits without row materialization.
            ridge_lambda=1,
            framework=EXACT_LINEAR_FRAMEWORK,
            canonicality=ModelCanonicality.CANONICAL_EXACT,
            compiler_version=ml_physical.COMPILER_VERSION,
        )
        # Complete execute only after its no-preprocessing and no-calibration inputs are
        # visible in test exact trainer reads training only ports and fits without row
        # materialization.
    )

    with NumpyModelBundleReader(stack.artifacts, trained.model_bundle_id) as model:
        # Keep numpy model bundle reader, artifacts and model bundle id active only for
        # the bounded test exact trainer reads training only ports and fits without row
        # materialization operation.
        assert model.training_spec == training_spec
        assert model.weights.size == 2
        assert model.output_divisor > 0
        assert model.fitted_component_available_boundaries == (training_spec.training_cutoff,)


def test_frozen_builder_computes_values_and_causal_rows_from_exact_inputs(
    # Keep the tmp path input explicit in the test frozen builder computes values and
    # causal rows from exact inputs contract.
    tmp_path: Path,
) -> None:
    # Execute the test frozen builder computes values and causal rows from exact inputs
    # workflow in explicit, reviewable steps.
    stack = _publish_stack(tmp_path)
    replay_semantics, replay_layout = _replay_ids(stack)
    model_ids = tuple(item.model_bundle_id for item in stack.models)
    built = BuildFrozenPredictions(
        LocalExactFrozenPredictionBuilder(stack.artifacts, _publisher(stack.artifacts))
        # Complete BuildFrozenPredictions only after its artifacts and local exact frozen
        # prediction builder inputs are visible in test frozen builder computes values and
        # causal rows from exact inputs.
    ).execute(
        BuildFrozenPredictionsRequest(
            replay_pack_id=stack.replay_pack_id,
            replay_semantics_id=replay_semantics,
            replay_layout_schema_id=replay_layout,
            # Pass feature set ids explicitly so BuildFrozenPredictionsRequest receives a
            # reviewable computed-score and replay pack id input in test frozen builder
            # computes values and causal rows from exact inputs.
            feature_set_ids=(stack.feature.feature_set_id,),
            model_schedule_id=stack.schedule.model_schedule_id,
            model_bundle_ids=model_ids,
            prediction_name="computed-score",
            inference_delay_boundaries=3,
            # Pass missing policy explicitly so BuildFrozenPredictionsRequest receives a
            # reviewable computed-score and replay pack id input in test frozen builder
            # computes values and causal rows from exact inputs.
            missing_policy=FrozenMissingPolicy.NULL,
            canonicality=ModelCanonicality.CANONICAL_EXACT,
            compiler_version=ml_physical.COMPILER_VERSION,
        )
    )

    # Acquire numpy prediction set provider, artifacts and prediction set id at an
    # explicit test frozen builder computes values and causal rows from exact inputs
    # context boundary so cleanup remains scoped.
    with NumpyPredictionSetProvider(stack.artifacts, built.prediction_set_id) as predictions:
        # Keep numpy prediction set provider, artifacts and prediction set id active only
        # for the bounded test frozen builder computes values and causal rows from exact
        # inputs operation.
        release = predictions.available_boundary_for_row(0)
        assert release == stack.effective[0] + 4
        assert predictions.value_at("computed-score", 0, release - 1) is None
        assert predictions.value_at("computed-score", 0, release) == 1
        assert (
            # Keep the predictions expectation tied to value at, computed-score and
            # predictions in this scenario.
            predictions.value_at(
                "computed-score",
                1,
                predictions.available_boundary_for_row(1),
            )
            # Verify the value at, computed-score and predictions relationship before this
            # scenario is accepted.
            is None
        )


def test_embedded_exact_is_byte_identical_to_frozen_and_batch_independent(
    tmp_path: Path,
) -> None:
    # Execute the test embedded exact is byte identical to frozen and batch independent
    # workflow in explicit, reviewable steps.
    stack = _publish_stack(tmp_path)
    prediction_name = "computed-score"
    delay = 3
    frozen = _build_frozen_predictions(
        stack,
        # Pass prediction name explicitly so _build_frozen_predictions receives a
        # reviewable null and stack input in test embedded exact is byte identical to
        # frozen and batch independent.
        prediction_name=prediction_name,
        delay=delay,
        missing_policy=FrozenMissingPolicy.NULL,
    )
    frozen_policy = ExactInferencePolicy.frozen_exact_linear(
        # Pass prediction name explicitly so frozen_exact_linear receives a reviewable
        # null and prediction name input in test embedded exact is byte identical to
        # frozen and batch independent.
        prediction_name=prediction_name,
        missing_policy=InferenceMissingPolicy.NULL,
        inference_delay_boundaries=delay,
    )
    embedded_policy = ExactInferencePolicy.embedded_exact_linear(
        # Pass prediction name explicitly so embedded_exact_linear receives a reviewable
        # null and prediction name input in test embedded exact is byte identical to
        # frozen and batch independent.
        prediction_name=prediction_name,
        missing_policy=InferenceMissingPolicy.NULL,
        inference_delay_boundaries=delay,
    )
    frozen_spec = _resolve_inference_spec(
        # Pass stack explicitly so _resolve_inference_spec receives a reviewable
        # prediction set id and stack input in test embedded exact is byte identical to
        # frozen and batch independent.
        stack,
        frozen_policy,
        prediction_set_ids=(frozen.prediction_set_id,),
    )
    embedded_spec = _resolve_inference_spec(stack, embedded_policy)
    # Assemble temporary parent once so the test embedded exact is byte identical to
    # frozen and batch independent workflow shares one value.
    temporary_parent = tmp_path / "embedded-temporary"

    frozen_summary: RunSummary
    with LocalNumpyCausalOverlayFactory(stack.artifacts).open_resolved(frozen_spec) as overlays:
        # Keep open resolved, frozen spec and local numpy causal overlay factory active
        # only for the bounded test embedded exact is byte identical to frozen and batch
        # independent operation.
        assert overlays.predictions is not None
        frozen_summary = _run_with_predictions(stack, overlays.predictions, prediction_name)

    embedded_summaries: list[RunSummary] = []
    with NumpyPredictionSetProvider(stack.artifacts, frozen.prediction_set_id) as expected:
        # Keep numpy prediction set provider, artifacts and prediction set id active only
        # for the bounded test embedded exact is byte identical to frozen and batch
        # independent operation.
        first_release = expected.available_boundary_for_row(0)
        assert first_release == stack.effective[0] + 4
        assert first_release < stack.effective[3]
        for batch_rows, readahead in ((1, 1), (3, 4)):
            # Process ((1, 1), (3, 4)) inside the bounded test embedded exact is byte
            # identical to frozen and batch independent loop.
            factory = LocalNumpyCausalOverlayFactory(
                stack.artifacts,
                embedded_temporary_parent=temporary_parent,
                embedded_maximum_temporary_bytes=1 << 20,
                embedded_batch_rows=batch_rows,
                # Complete LocalNumpyCausalOverlayFactory only after its artifacts and stack
                # inputs are visible in test embedded exact is byte identical to frozen and
                # batch independent.
            )
            with factory.open_resolved(embedded_spec) as overlays:
                # Keep open resolved, embedded spec and factory active only for the
                # bounded test embedded exact is byte identical to frozen and batch
                # independent operation.
                assert overlays.predictions is not None
                for row_id in range(len(stack.effective)):
                    # Process range(len(stack.effective)) inside the bounded test embedded
                    # exact is byte identical to frozen and batch independent loop.
                    release = expected.available_boundary_for_row(row_id)
                    assert (
                        overlays.predictions.value_at(prediction_name, row_id, release - 1) is None
                    )
                    assert overlays.predictions.value_at(
                        # Pass prediction name explicitly so value_at receives a
                        # reviewable prediction name and row id input in test embedded
                        # exact is byte identical to frozen and batch independent.
                        prediction_name,
                        row_id,
                        release,
                    ) == expected.value_at(prediction_name, row_id, release)
                embedded_summaries.append(
                    # Pass run with predictions explicitly to append for predictions and
                    # run with predictions.
                    _run_with_predictions(
                        stack,
                        # Pass overlays explicitly so _run_with_predictions receives a
                        # reviewable predictions and stack input in test embedded exact is
                        # byte identical to frozen and batch independent.
                        overlays.predictions,
                        prediction_name,
                        reader_batch_rows=batch_rows,
                        reader_readahead=readahead,
                    )
                    # Complete append only after its predictions and run with predictions
                    # inputs are visible in test embedded exact is byte identical to frozen
                    # and batch independent.
                )
            assert temporary_parent.is_dir()
            assert not tuple(temporary_parent.iterdir())

    assert frozen_summary.accepted_order_count == 2
    assert frozen_summary.rejected_order_count == 0
    # Verify frozen_summary.failed_order_count == 2 before this scenario is accepted.
    assert frozen_summary.failed_order_count == 2
    assert [summary.audit_hash for summary in embedded_summaries] == [
        frozen_summary.audit_hash,
        frozen_summary.audit_hash,
    ]
    # Verify the result hash, summary and embedded summaries relationship before this
    # scenario is accepted.
    assert [summary.result_hash for summary in embedded_summaries] == [
        frozen_summary.result_hash,
        frozen_summary.result_hash,
    ]


def test_embedded_exact_rejects_missing_features_and_hard_quota(tmp_path: Path) -> None:
    # Execute the test embedded exact rejects missing features and hard quota workflow in
    # explicit, reviewable steps.
    stack = _publish_stack(tmp_path)
    policy = ExactInferencePolicy.embedded_exact_linear(
        prediction_name="computed-score",
        missing_policy=InferenceMissingPolicy.REJECT,
        inference_delay_boundaries=3,
        # Complete embedded_exact_linear only after its computed-score and reject inputs are
        # visible in test embedded exact rejects missing features and hard quota.
    )
    spec = _resolve_inference_spec(stack, policy)

    with (
        pytest.raises(EmbeddedExactInferenceError, match="hard temporary quota"),
        LocalNumpyCausalOverlayFactory(
            # Pass stack explicitly so open_resolved receives a reviewable spec input in
            # test embedded exact rejects missing features and hard quota.
            stack.artifacts,
            embedded_temporary_parent=tmp_path / "quota",
            embedded_maximum_temporary_bytes=1,
            embedded_batch_rows=1,
        ).open_resolved(spec),
        # Acquire raises, embedded exact inference error and pytest at an explicit test
        # embedded exact rejects missing features and hard quota context boundary so cleanup
        # remains scoped.
    ):
        pass

    with (
        pytest.raises(EmbeddedExactInferenceError, match="missing feature"),
        LocalNumpyCausalOverlayFactory(
            # Pass stack explicitly so open_resolved receives a reviewable spec input in
            # test embedded exact rejects missing features and hard quota.
            stack.artifacts,
            embedded_temporary_parent=tmp_path / "missing",
            embedded_maximum_temporary_bytes=1 << 20,
            embedded_batch_rows=2,
        ).open_resolved(spec),
        # Acquire raises, embedded exact inference error and pytest at an explicit test
        # embedded exact rejects missing features and hard quota context boundary so cleanup
        # remains scoped.
    ):
        pass
    assert not tuple((tmp_path / "missing").iterdir())


def test_selected_model_and_fitted_operands_are_required(tmp_path: Path) -> None:
    # Execute the test selected model and fitted operands are required workflow in
    # explicit, reviewable steps.
    stack = _publish_stack(tmp_path)
    replay_semantics, replay_layout = _replay_ids(stack)
    model_pairs = sorted(
        (
            (
                # Pass item explicitly so sorted receives a reviewable model bundle id and
                # models input in test selected model and fitted operands are required.
                item.model_bundle_id,
                _model_availability(stack.artifacts, item.model_bundle_id),
            )
            for item in stack.models
        ),
        # Pass key explicitly so sorted receives a reviewable model bundle id and models
        # input in test selected model and fitted operands are required.
        key=lambda item: item[0].hex,
    )
    availability_by_model = dict(model_pairs)
    wrong_rows = []
    with NumpyModelScheduleReader(stack.artifacts, stack.schedule.model_schedule_id) as schedule:
        # Keep numpy model schedule reader, artifacts and model schedule id active only
        # for the bounded test selected model and fitted operands are required operation.
        for index, effective in enumerate(stack.effective):
            # Process enumerate(stack.effective) inside the bounded test selected model
            # and fitted operands are required loop.
            selected = schedule.model_for(effective)
            wrong = next(model_id for model_id, _ in model_pairs if model_id != selected)
            wrong_model_available, wrong_fitted = availability_by_model[wrong]
            wrong_rows.append(
                FrozenPredictionRow(
                    # Pass replay row id explicitly so FrozenPredictionRow receives a
                    # reviewable prediction availability and index input in test selected
                    # model and fitted operands are required.
                    replay_row_id=index,
                    effective_boundary_ordinal=effective,
                    inference_completion_boundary=effective + 2,
                    availability=PredictionAvailability(
                        feature_available_boundary=effective + 1,
                        # Pass model available boundaries explicitly so
                        # PredictionAvailability receives a reviewable effective and wrong
                        # model available input in test selected model and fitted operands
                        # are required.
                        model_available_boundaries=(wrong_model_available,),
                        fitted_component_available_boundaries=wrong_fitted,
                        inference_completion_boundary=effective + 2,
                    ),
                    value=index,
                    # Complete FrozenPredictionRow only after its prediction availability and
                    # index inputs are visible in test selected model and fitted operands are
                    # required.
                )
            )
    publisher = _publisher(stack.artifacts)
    with pytest.raises(NumpyMlArtifactCompileError, match="availability operands"):
        # Keep raises, numpy ml artifact compile error and pytest active only for the
        # bounded test selected model and fitted operands are required operation.
        BuildPredictionSet(publisher).execute(
            BuildPredictionSetRequest(
                replay_pack_id=stack.replay_pack_id,
                replay_semantics_id=replay_semantics,
                replay_layout_schema_id=replay_layout,
                # Pass feature set ids explicitly so BuildPredictionSetRequest receives a
                # reviewable score and replay pack id input in test selected model and
                # fitted operands are required.
                feature_set_ids=(stack.feature.feature_set_id,),
                model_schedule_id=stack.schedule.model_schedule_id,
                model_bundle_ids=tuple(item[0] for item in model_pairs),
                prediction_name="score",
                inference_mode=InferenceMode.FROZEN,
                # Pass inference policy digest explicitly to execute for score and replay
                # pack id.
                inference_policy_digest=_frozen_policy().inference_policy_digest,
                causal_availability_policy=EXACT_PREDICTION_AVAILABILITY_POLICY,
                canonicality=ModelCanonicality.CANONICAL_EXACT,
                rows=tuple(wrong_rows),
                compiler_version=ml_physical.COMPILER_VERSION,
                # Complete BuildPredictionSetRequest only after its score and replay pack id
                # inputs are visible in test selected model and fitted operands are required.
            )
        )


def test_exact_and_tolerance_models_cannot_be_mixed(tmp_path: Path) -> None:
    # Execute the test exact and tolerance models cannot be mixed workflow in explicit,
    # reviewable steps.
    stack = _publish_stack(tmp_path)
    with NumpyModelScheduleReader(stack.artifacts, stack.schedule.model_schedule_id) as committed:
        schedule = committed.schedule
    with pytest.raises(NumpyMlArtifactCompileError, match="exact and tolerance"):
        # Keep raises, numpy ml artifact compile error and pytest active only for the
        # bounded test exact and tolerance models cannot be mixed operation.
        PublishModelSchedule(_publisher(stack.artifacts)).execute(
            PublishModelScheduleRequest(
                schedule=schedule,
                canonicality=ModelCanonicality.NON_CANONICAL_TOLERANCE,
                compiler_version=ml_physical.COMPILER_VERSION,
                # Complete PublishModelScheduleRequest only after its non canonical tolerance
                # and compiler version inputs are visible in test exact and tolerance models
                # cannot be mixed.
            )
        )


def test_embedded_preflight_rejects_future_explicit_fallback_model(tmp_path: Path) -> None:
    # Execute the test embedded preflight rejects future explicit fallback model workflow
    # in explicit, reviewable steps.
    stack = _publish_stack(tmp_path)
    modeled_available = stack.effective[-1] + 100
    future_model = PublishModelBundle(_publisher(stack.artifacts)).execute(
        _model_request(
            _training_spec(
                # Pass stack explicitly so _training_spec receives a reviewable feature
                # and labels input in test embedded preflight rejects future explicit
                # fallback model.
                stack.feature,
                stack.labels,
                stack.universe,
                modeled_available_boundary=modeled_available,
            ),
            # Keep the feature _feature_schema step visible while building future model.
            _feature_schema(stack.feature, _feature_specs()),
            weights=(1, 2),
            fitted=(modeled_available - 1,),
        )
    )
    # Assemble future schedule once so the test embedded preflight rejects future explicit
    # fallback model workflow shares one value.
    future_schedule = PublishModelSchedule(_publisher(stack.artifacts)).execute(
        PublishModelScheduleRequest(
            schedule=ModelSchedule(
                entries=(),
                fallback_model_bundle_id=future_model.model_bundle_id,
                # Complete ModelSchedule only after its model bundle id and future model
                # inputs are visible in test embedded preflight rejects future explicit
                # fallback model.
            ),
            canonicality=ModelCanonicality.CANONICAL_EXACT,
            compiler_version=ml_physical.COMPILER_VERSION,
        )
    )
    # Assemble policy once so the test embedded preflight rejects future explicit fallback
    # model workflow shares one value.
    policy = ExactInferencePolicy.embedded_exact_linear(
        prediction_name="score",
        missing_policy=InferenceMissingPolicy.NULL,
        inference_delay_boundaries=0,
    )

    # Acquire raises, reference run resolution error and pytest at an explicit test
    # embedded preflight rejects future explicit fallback model context boundary so
    # cleanup remains scoped.
    with pytest.raises(
        ReferenceRunResolutionError,
        match="no eligible model",
    ):
        # Keep raises, reference run resolution error and pytest active only for the
        # bounded test embedded preflight rejects future explicit fallback model
        # operation.
        _resolve_inference_spec(
            stack,
            policy,
            model_schedule_id=future_schedule.model_schedule_id,
        )


# Define test embedded preflight rejects unsupported exact model runtime as one focused
# operation with an explicit boundary.
def test_embedded_preflight_rejects_unsupported_exact_model_runtime(tmp_path: Path) -> None:
    # Execute the test embedded preflight rejects unsupported exact model runtime workflow
    # in explicit, reviewable steps.
    stack = _publish_stack(tmp_path)
    request = _model_request(
        _training_spec(
            stack.feature,
            stack.labels,
            # Pass stack explicitly so _training_spec receives a reviewable feature and
            # labels input in test embedded preflight rejects unsupported exact model
            # runtime.
            stack.universe,
            modeled_available_boundary=25,
        ),
        _feature_schema(stack.feature, _feature_specs()),
        weights=(1, 2),
        # Pass fitted explicitly so _model_request receives a reviewable feature and
        # labels input in test embedded preflight rejects unsupported exact model runtime.
        fitted=(22, 24),
    )
    unsupported = PublishModelBundle(_publisher(stack.artifacts)).execute(
        replace(request, framework="unsupported-exact-runtime-v1")
    )
    # Assemble schedule once so the test embedded preflight rejects unsupported exact
    # model runtime workflow shares one value.
    schedule = _single_model_schedule(stack, unsupported)
    policy = ExactInferencePolicy.embedded_exact_linear(
        prediction_name="score",
        missing_policy=InferenceMissingPolicy.NULL,
        inference_delay_boundaries=0,
        # Complete embedded_exact_linear only after its score and null inputs are visible in
        # test embedded preflight rejects unsupported exact model runtime.
    )

    with pytest.raises(
        ReferenceRunResolutionError,
        match="causal overlays",
    ):
        # Keep raises, reference run resolution error and pytest active only for the
        # bounded test embedded preflight rejects unsupported exact model runtime
        # operation.
        _resolve_inference_spec(
            stack,
            policy,
            model_schedule_id=schedule.model_schedule_id,
        )


# Define test embedded preflight rejects checked output overflow as one focused operation
# with an explicit boundary.
def test_embedded_preflight_rejects_checked_output_overflow(tmp_path: Path) -> None:
    # Execute the test embedded preflight rejects checked output overflow workflow in
    # explicit, reviewable steps.
    stack = _publish_stack(tmp_path)
    training = _training_spec(
        stack.feature,
        stack.labels,
        stack.universe,
        # Pass modeled available boundary explicitly so _training_spec receives a
        # reviewable feature and labels input in test embedded preflight rejects checked
        # output overflow.
        modeled_available_boundary=25,
    )
    overflow_model = PublishModelBundle(_publisher(stack.artifacts)).execute(
        PublishModelBundleRequest(
            training_spec=training,
            # Keep the feature _feature_schema step visible while building overflow model.
            feature_schema_digest=_feature_schema(stack.feature, _feature_specs()),
            payload=ExactLinearModelPayload(
                weights=((1 << 63) - 1, (1 << 63) - 1),
                intercept=(1 << 63) - 1,
                output_divisor=1,
                # Complete ExactLinearModelPayload only after its declared inputs are visible
                # in test embedded preflight rejects checked output overflow.
            ),
            preprocessing_digest=_digest("overflow-preprocessing"),
            calibration_digest=_digest("overflow-calibration"),
            metrics_digest=_digest("overflow-metrics"),
            fitted_component_available_boundaries=(22, 24),
            # Pass framework explicitly so PublishModelBundleRequest receives a reviewable
            # overflow-preprocessing and overflow-calibration input in test embedded
            # preflight rejects checked output overflow.
            framework=EXACT_LINEAR_FRAMEWORK,
            canonicality=ModelCanonicality.CANONICAL_EXACT,
            compiler_version=ml_physical.COMPILER_VERSION,
        )
    )
    # Assemble schedule once so the test embedded preflight rejects checked output
    # overflow workflow shares one value.
    schedule = _single_model_schedule(stack, overflow_model)
    spec = _resolve_inference_spec(
        stack,
        ExactInferencePolicy.embedded_exact_linear(
            prediction_name="score",
            # Pass missing policy explicitly so embedded_exact_linear receives a
            # reviewable score and null input in test embedded preflight rejects checked
            # output overflow.
            missing_policy=InferenceMissingPolicy.NULL,
            inference_delay_boundaries=0,
        ),
        model_schedule_id=schedule.model_schedule_id,
    )

    # Acquire raises, embedded exact inference error and pytest at an explicit test
    # embedded preflight rejects checked output overflow context boundary so cleanup
    # remains scoped.
    with (
        pytest.raises(EmbeddedExactInferenceError, match="checked int64 output"),
        LocalNumpyCausalOverlayFactory(
            stack.artifacts,
            embedded_temporary_parent=tmp_path / "overflow",
            # Pass embedded maximum temporary bytes explicitly so open_resolved receives a
            # reviewable spec input in test embedded preflight rejects checked output
            # overflow.
            embedded_maximum_temporary_bytes=1 << 20,
            embedded_batch_rows=2,
        ).open_resolved(spec),
    ):
        pass


# Apply parametrize semantics to the following test reader rejects dtype endian order and
# future poisoning contract.
@pytest.mark.parametrize(
    ("target", "mutate", "message"),
    [
        (
            ml_physical.FEATURE_VALUES,
            # Define test reader rejects dtype endian order and future poisoning as one
            # focused operation with an explicit boundary.
            lambda value: value.astype("<i4"),
            "dtype/endian mismatch",
        ),
        (
            ml_physical.FEATURE_AVAILABLE,
            # Define test reader rejects dtype endian order and future poisoning as one
            # focused operation with an explicit boundary.
            lambda value: value.astype(">u8"),
            "dtype/endian mismatch",
        ),
        (
            ml_physical.FEATURE_ROW_ID,
            # Define test reader rejects dtype endian order and future poisoning as one
            # focused operation with an explicit boundary.
            lambda value: value[::-1].copy(),
            "row IDs are not dense",
        ),
        (
            ml_physical.FEATURE_VALUES,
            # Define test reader rejects dtype endian order and future poisoning as one
            # focused operation with an explicit boundary.
            lambda value: np.asfortranarray(value),
            "not read-only C-order",
        ),
        (
            ml_physical.FEATURE_AVAILABLE,
            # Define test reader rejects dtype endian order and future poisoning as one
            # focused operation with an explicit boundary.
            lambda value: np.zeros_like(value),
            "future-poisoned availability",
        ),
    ],
)
# Define test reader rejects dtype endian order and future poisoning as one focused
# operation with an explicit boundary.
def test_reader_rejects_dtype_endian_order_and_future_poisoning(
    tmp_path: Path,
    target: str,
    mutate: Callable[[np.ndarray], np.ndarray],
    message: str,
    # Close the test reader rejects dtype endian order and future poisoning signature after
    # its explicit inputs.
) -> None:
    # Execute the test reader rejects dtype endian order and future poisoning workflow in
    # explicit, reviewable steps.
    stack = _publish_stack(tmp_path)
    malformed = _republish_feature_array(
        stack.artifacts,
        stack.feature.feature_set_id,
        target,
        # Pass mutate explicitly so _republish_feature_array receives a reviewable
        # artifacts and feature set id input in test reader rejects dtype endian order and
        # future poisoning.
        mutate,
    )

    with pytest.raises(NumpyMlArtifactFormatError, match=message):
        NumpyFeatureSetProvider(stack.artifacts, malformed)


def test_physical_corruption_is_rejected_before_ml_mmap(tmp_path: Path) -> None:
    # Execute the test physical corruption is rejected before ml mmap workflow in
    # explicit, reviewable steps.
    stack = _publish_stack(tmp_path)
    path = (
        stack.artifacts.data_root
        / "features"
        / stack.feature.feature_set_id.hex
        # Keep the ml physical component named inside the path contract.
        / ml_physical.FEATURE_VALUES
    )
    with path.open("r+b") as stream:
        # Keep open and path active only for the bounded test physical corruption is
        # rejected before ml mmap operation.
        stream.seek(-1, 2)
        original = stream.read(1)
        stream.seek(-1, 2)
        stream.write(bytes([original[0] ^ 0xFF]))

    with pytest.raises(ArtifactIntegrityError):
        # Invoke NumpyFeatureSetProvider for artifacts and feature set id as a visible
        # test physical corruption is rejected before ml mmap step.
        NumpyFeatureSetProvider(stack.artifacts, stack.feature.feature_set_id)


@pytest.mark.parametrize(
    ("role", "artifact_kind"),
    (
        (ML_COMPILER_ROLE, "feature"),
        # Open the role and artifact kind payload explicitly for parametrize within test
        # source bound ml reader rejects mismatched tool identity.
        (ML_WRITER_ROLE, "feature"),
        (ML_FEATURE_BUILDER_ROLE, "feature"),
        (ML_UNIVERSE_BUILDER_ROLE, "universe"),
        (ML_LABEL_BUILDER_ROLE, "label"),
        (ML_TRAINER_ROLE, "model"),
        # Open the role and artifact kind payload explicitly for parametrize within test
        # source bound ml reader rejects mismatched tool identity.
        (ML_FROZEN_INFERENCE_ROLE, "prediction"),
    ),
)
def test_source_bound_ml_reader_rejects_mismatched_tool_identity(
    tmp_path: Path,
    # Keep the role input explicit in the test source bound ml reader rejects mismatched
    # tool identity contract.
    role: str,
    artifact_kind: str,
) -> None:
    # Execute the test source bound ml reader rejects mismatched tool identity workflow in
    # explicit, reviewable steps.
    stack = _publish_stack(tmp_path)
    base = unit_ml_build_tools()
    expected = base.identity_for(role).bundle_id
    if role in {ML_COMPILER_ROLE, ML_WRITER_ROLE, ML_FROZEN_INFERENCE_ROLE}:
        expected = BundleId("7" * 64)
    # Assemble tools once so the test source bound ml reader rejects mismatched tool
    # identity workflow shares one value.
    tools = _source_bound_role(base, role, expected)

    with pytest.raises(NumpyMlArtifactFormatError, match=r"bundle|compiler"):
        # Keep raises, numpy ml artifact format error and pytest active only for the
        # bounded test source bound ml reader rejects mismatched tool identity operation.
        if artifact_kind == "feature":
            # Handle the test source bound ml reader rejects mismatched tool identity
            # artifact_kind == 'feature' branch as a distinct logical block.
            NumpyFeatureSetProvider(
                stack.artifacts,
                stack.feature.feature_set_id,
                build_tools=tools,
            )
        # Handle the test source bound ml reader rejects mismatched tool identity
        # complement of artifact_kind == 'feature' explicitly.
        elif artifact_kind == "universe":
            # Handle the test source bound ml reader rejects mismatched tool identity
            # artifact_kind == 'universe' branch as a distinct logical block.
            NumpyUniverseReader(
                stack.artifacts,
                stack.universe.universe_id,
                build_tools=tools,
            )
        # Handle the test source bound ml reader rejects mismatched tool identity
        # complement of artifact_kind == 'universe' explicitly.
        elif artifact_kind == "label":
            # Handle the test source bound ml reader rejects mismatched tool identity
            # artifact_kind == 'label' branch as a distinct logical block.
            NumpyLabelSetReader(
                stack.artifacts,
                stack.labels.label_set_id,
                build_tools=tools,
            )
        # Handle the test source bound ml reader rejects mismatched tool identity
        # complement of artifact_kind == 'label' explicitly.
        elif artifact_kind == "model":
            # Handle the test source bound ml reader rejects mismatched tool identity
            # artifact_kind == 'model' branch as a distinct logical block.
            NumpyModelBundleReader(
                stack.artifacts,
                stack.models[0].model_bundle_id,
                build_tools=tools,
            )
        # Route all remaining cases through the explicit alternative branch.
        else:
            # Handle the test source bound ml reader rejects mismatched tool identity
            # complement of artifact_kind == 'model' explicitly.
            NumpyPredictionSetProvider(
                stack.artifacts,
                stack.predictions.prediction_set_id,
                build_tools=tools,
            )


# Define publish stack as one focused operation with an explicit boundary.
def _publish_stack(
    tmp_path: Path,
    *,
    maximum_rows_in_memory: int = 2,
) -> _MlStack:
    # Execute the publish stack workflow in explicit, reviewable steps.
    artifacts = LocalArtifactRepository(tmp_path / "var")
    snapshot_id = _publish_snapshot(artifacts)
    events = _events()
    replay = LocalNumpyReplayPackCompiler(
        artifacts,
        # Keep the requested _checked_source step visible while building replay.
        lambda requested: _checked_source(requested, snapshot_id, events),
        runtime_lock_id=_runtime("replay"),
    ).compile(snapshot_id, replay_physical.COMPILER_VERSION)
    effective = tuple(event.envelope.boundary_ordinal for event in events)
    publisher = LocalNumpyMlArtifactPublisher(
        # Pass artifacts explicitly so LocalNumpyMlArtifactPublisher receives a reviewable
        # ml and runtime input in publish stack.
        artifacts,
        runtime_lock_id=_runtime("ml"),
        maximum_rows_in_memory=maximum_rows_in_memory,
        maximum_open_spill_files=2,
    )
    # Assemble specs once so the publish stack workflow shares one value.
    specs = _feature_specs()
    feature_rows = tuple(
        FeatureOverlayRow(
            replay_row_id=index,
            available_boundary_ordinal=boundary + 1,
            # Keep the code and index tuple step visible while building feature rows.
            values=tuple(
                (
                    None
                    if index == 1 and specs[code].null_policy is NullPolicy.EXPLICIT_BITMAP
                    else (index + 1) * (code + 2)
                    # Complete tuple only after its null policy and explicit bitmap inputs are
                    # visible in publish stack.
                )
                for code in range(len(specs))
            ),
        )
        for index, boundary in enumerate(effective)
        # Complete tuple only after its null policy and explicit bitmap inputs are visible in
        # publish stack.
    )
    feature = BuildFeatureSet(publisher).execute(
        BuildFeatureSetRequest(
            replay_pack_id=replay.replay_pack_id,
            replay_semantics_id=replay.manifest.semantics.replay_semantics_id,
            # Pass replay layout schema id explicitly so BuildFeatureSetRequest receives a
            # reviewable replay pack id and replay semantics id input in publish stack.
            replay_layout_schema_id=replay.manifest.layout.replay_layout_schema_id,
            feature_specs=specs,
            input_feature_set_ids=(),
            rows=tuple(reversed(feature_rows)),
            compiler_version=ml_physical.COMPILER_VERSION,
            # Complete BuildFeatureSetRequest only after its replay pack id and replay
            # semantics id inputs are visible in publish stack.
        )
    )
    universe = BuildUniverse(publisher).execute(
        BuildUniverseRequest(
            snapshot_id=snapshot_id,
            # Keep the universe-spec _digest step visible while building universe.
            universe_spec_id=_digest("universe-spec"),
            input_feature_set_ids=(feature.feature_set_id,),
            builder_bundle_id=_bundle("universe-builder"),
            builder_config_digest=_digest("universe-config"),
            rows=(
                # Keep the universe membership row and effective UniverseMembershipRow
                # step visible while building universe.
                UniverseMembershipRow(
                    entity_id=42,
                    eligible_from=0,
                    eligible_until=effective[-1] + 100,
                    input_available_boundary=0,
                    # Complete UniverseMembershipRow only after its effective inputs are
                    # visible in publish stack.
                ),
            ),
            compiler_version=ml_physical.COMPILER_VERSION,
        )
    )
    # Assemble labels once so the publish stack workflow shares one value.
    labels = BuildLabelSet(publisher).execute(
        BuildLabelSetRequest(
            snapshot_id=snapshot_id,
            universe_id=universe.universe_id,
            label_spec_id=_digest("label-spec"),
            # Keep the label-builder _bundle step visible while building labels.
            label_builder_bundle_id=_bundle("label-builder"),
            label_config_digest=_digest("label-config"),
            training_cutoff=20,
            rows=(
                LabelOverlayRow(1, 10, 20, None),
                # Keep the label overlay row LabelOverlayRow step visible while building
                # labels.
                LabelOverlayRow(0, 5, 15, 1),
            ),
            compiler_version=ml_physical.COMPILER_VERSION,
        )
    )
    # Assemble feature schema once so the publish stack workflow shares one value.
    feature_schema = _feature_schema(feature, specs)
    first_spec = _training_spec(feature, labels, universe, modeled_available_boundary=25)
    second_spec = _training_spec(
        feature,
        labels,
        # Pass universe explicitly so _training_spec receives a reviewable feature and
        # labels input in publish stack.
        universe,
        modeled_available_boundary=effective[2],
    )
    first_model = PublishModelBundle(publisher).execute(
        _model_request(first_spec, feature_schema, weights=(1, 2), fitted=(22, 24))
        # Complete execute only after its model request and first spec inputs are visible in
        # publish stack.
    )
    second_model = PublishModelBundle(publisher).execute(
        _model_request(
            second_spec,
            feature_schema,
            # Pass weights explicitly so _model_request receives a reviewable second spec
            # and feature schema input in publish stack.
            weights=(3, 4),
            fitted=(effective[2] - 1,),
        )
    )
    schedule_value = ModelSchedule(
        # Open the modeled-training-completion-v1 and model bundle id payload explicitly
        # for ModelSchedule within publish stack.
        (
            ModelScheduleEntry(
                eligible_from=effective[0],
                eligible_until=effective[2],
                model_bundle_id=first_model.model_bundle_id,
                # Pass training cutoff explicitly so ModelScheduleEntry receives a
                # reviewable modeled-training-completion-v1 and model bundle id input in
                # publish stack.
                training_cutoff=20,
                model_available_boundary=25,
                availability_basis="modeled-training-completion-v1",
            ),
            ModelScheduleEntry(
                # Pass eligible from explicitly so ModelScheduleEntry receives a
                # reviewable modeled-training-completion-v1 and model bundle id input in
                # publish stack.
                eligible_from=effective[2],
                eligible_until=effective[-1] + 100,
                model_bundle_id=second_model.model_bundle_id,
                training_cutoff=20,
                model_available_boundary=effective[2],
                # Pass availability basis explicitly so ModelScheduleEntry receives a
                # reviewable modeled-training-completion-v1 and model bundle id input in
                # publish stack.
                availability_basis="modeled-training-completion-v1",
            ),
        )
    )
    schedule = PublishModelSchedule(publisher).execute(
        # Keep the publish model schedule request and schedule value
        # PublishModelScheduleRequest step visible while building schedule.
        PublishModelScheduleRequest(
            schedule=schedule_value,
            canonicality=ModelCanonicality.CANONICAL_EXACT,
            compiler_version=ml_physical.COMPILER_VERSION,
        )
        # Complete execute only after its canonical exact and compiler version inputs are
        # visible in publish stack.
    )
    models = tuple(sorted((first_model, second_model), key=lambda item: item.model_bundle_id.hex))
    availability_by_model = {
        item.model_bundle_id: _model_availability(artifacts, item.model_bundle_id)
        for item in models
        # Complete the availability by model group only after its semantic components are
        # visible.
    }
    prediction_rows = []
    for index, boundary in enumerate(effective):
        # Process enumerate(effective) inside the bounded publish stack loop.
        selected_model = schedule_value.model_for(boundary)
        selected_available, selected_fitted = availability_by_model[selected_model]
        inference_start = max(boundary + 1, selected_available, *selected_fitted)
        inference_completion = inference_start + 1
        prediction_rows.append(
            # Pass frozen prediction row explicitly to append for frozen prediction row
            # and prediction availability.
            FrozenPredictionRow(
                replay_row_id=index,
                effective_boundary_ordinal=boundary,
                inference_completion_boundary=inference_completion,
                availability=PredictionAvailability(
                    # Pass feature available boundary explicitly so PredictionAvailability
                    # receives a reviewable boundary and selected available input in
                    # publish stack.
                    feature_available_boundary=boundary + 1,
                    model_available_boundaries=(selected_available,),
                    fitted_component_available_boundaries=selected_fitted,
                    inference_completion_boundary=inference_completion,
                ),
                # Pass value explicitly so FrozenPredictionRow receives a reviewable
                # prediction availability and index input in publish stack.
                value=None if index == 2 else 100 + index,
            )
        )
    predictions = BuildPredictionSet(publisher).execute(
        BuildPredictionSetRequest(
            # Pass replay pack id explicitly so BuildPredictionSetRequest receives a
            # reviewable score and replay pack id input in publish stack.
            replay_pack_id=replay.replay_pack_id,
            replay_semantics_id=replay.manifest.semantics.replay_semantics_id,
            replay_layout_schema_id=replay.manifest.layout.replay_layout_schema_id,
            feature_set_ids=(feature.feature_set_id,),
            model_schedule_id=schedule.model_schedule_id,
            # Keep the model bundle id and item tuple step visible while building
            # predictions.
            model_bundle_ids=tuple(item.model_bundle_id for item in models),
            prediction_name="score",
            inference_mode=InferenceMode.FROZEN,
            inference_policy_digest=_frozen_policy().inference_policy_digest,
            causal_availability_policy=EXACT_PREDICTION_AVAILABILITY_POLICY,
            # Pass canonicality explicitly so BuildPredictionSetRequest receives a
            # reviewable score and replay pack id input in publish stack.
            canonicality=ModelCanonicality.CANONICAL_EXACT,
            rows=tuple(reversed(prediction_rows)),
            compiler_version=ml_physical.COMPILER_VERSION,
        )
    )
    # Return the completed publish stack result without a hidden fallback.
    return _MlStack(
        artifacts,
        replay.replay_pack_id,
        feature,
        universe,
        # Pass labels explicitly so _MlStack receives a reviewable replay pack id and cast
        # input in publish stack.
        labels,
        cast(tuple[PublishedModelBundle, PublishedModelBundle], models),
        schedule,
        predictions,
        effective,
        # Pass feature rows explicitly so _MlStack receives a reviewable replay pack id
        # and cast input in publish stack.
        feature_rows,
    )


def _source_bound_role(
    base: PinnedCodeBundleSet,
    role: str,
    # Keep the bundle id input explicit in the source bound role contract.
    bundle_id: BundleId,
) -> PinnedCodeBundleSet:
    # Execute the source bound role workflow in explicit, reviewable steps.
    identities = []
    for identity in base.identities:
        # Process base.identities inside the bounded source bound role loop.
        if identity.role == role:
            # Handle the source bound role identity.role == role branch as a distinct
            # logical block.
            identities.append(
                PinnedCodeBundleIdentity(
                    role,
                    bundle_id,
                    lambda current=bundle_id: current,
                    # Complete PinnedCodeBundleIdentity only after its role and bundle id
                    # inputs are visible in source bound role.
                )
            )
        else:
            identities.append(identity)
    return PinnedCodeBundleSet(tuple(identities))


# Define training spec as one focused operation with an explicit boundary.
def _training_spec(
    feature: PublishedFeatureSet,
    labels: PublishedLabelSet,
    universe: PublishedUniverse,
    *,
    # Keep the modeled available boundary input explicit in the training spec contract.
    modeled_available_boundary: int,
) -> TrainingJobSpec:
    # Execute the training spec workflow in explicit, reviewable steps.
    return TrainingJobSpec(
        feature_set_ids=(feature.feature_set_id,),
        label_set_id=labels.label_set_id,
        universe_id=universe.universe_id,
        split=TemporalSplit(0, 8, 10, 15, purge_boundaries=2, embargo_boundaries=1),
        # Include hyperparameter digest in the completed training spec result.
        hyperparameter_digest=_digest("hyperparameters"),
        root_seeds=(7, 11),
        training_cutoff=20,
        modeled_available_boundary=modeled_available_boundary,
        trainer_bundle_id=_bundle("trainer"),
        # Include runtime lock id in the completed training spec result.
        runtime_lock_id=_runtime("trainer"),
    )


def _model_request(
    training_spec: TrainingJobSpec,
    feature_schema: ContentDigest,
    # Close the model request signature after its explicit inputs.
    *,
    weights: tuple[int, int],
    fitted: tuple[int, ...],
) -> PublishModelBundleRequest:
    # Execute the model request workflow in explicit, reviewable steps.
    return PublishModelBundleRequest(
        training_spec=training_spec,
        feature_schema_digest=feature_schema,
        payload=ExactLinearModelPayload(weights, intercept=5, output_divisor=10),
        preprocessing_digest=_digest("preprocessing"),
        # Include calibration digest in the completed model request result.
        calibration_digest=_digest("calibration"),
        metrics_digest=_digest("metrics"),
        fitted_component_available_boundaries=fitted,
        framework=EXACT_LINEAR_FRAMEWORK,
        canonicality=ModelCanonicality.CANONICAL_EXACT,
        # Pass compiler version explicitly so PublishModelBundleRequest receives a
        # reviewable preprocessing and calibration input in model request.
        compiler_version=ml_physical.COMPILER_VERSION,
    )


def _feature_specs() -> tuple[FeatureSpec, ...]:
    # Execute the feature specs workflow in explicit, reviewable steps.
    values = (
        FeatureSpec(
            name="momentum",
            version=1,
            entity_key="replay_row_id",
            # Register price-input through _digest so the values table remains scannable.
            input_ids=(_digest("price-input"),),
            effective_time_semantics="event-boundary-v1",
            available_time_semantics="declared-row-availability-v1",
            warmup_boundaries=1,
            dtype="<i8",
            # Pass null policy explicitly so FeatureSpec receives a reviewable momentum
            # and replay row id input in feature specs.
            null_policy=NullPolicy.EXPLICIT_BITMAP,
            code_bundle_id=_bundle("feature-momentum"),
            runtime_lock_id=_runtime("feature"),
        ),
        FeatureSpec(
            # Pass name explicitly so FeatureSpec receives a reviewable volume and replay
            # row id input in feature specs.
            name="volume",
            version=1,
            entity_key="replay_row_id",
            input_ids=(_digest("volume-input"),),
            effective_time_semantics="event-boundary-v1",
            # Pass available time semantics explicitly so FeatureSpec receives a
            # reviewable volume and replay row id input in feature specs.
            available_time_semantics="declared-row-availability-v1",
            warmup_boundaries=0,
            dtype="<i8",
            null_policy=NullPolicy.FORBID,
            code_bundle_id=_bundle("feature-volume"),
            # Register feature through _runtime so the values table remains scannable.
            runtime_lock_id=_runtime("feature"),
        ),
    )
    return tuple(sorted(values, key=lambda item: item.feature_spec_id.hex))


def _feature_schema(feature: PublishedFeatureSet, specs: tuple[FeatureSpec, ...]) -> ContentDigest:
    # Execute the feature schema workflow in explicit, reviewable steps.
    return domain_digest(
        "backtest.model-feature-schema.v1",
        [
            {
                "feature_set_id": feature.feature_set_id.hex,
                # Keep feature spec ids named so the v1 and feature set id payload passed
                # to domain_digest remains self-describing within feature schema.
                "feature_spec_ids": [item.feature_spec_id.hex for item in specs],
            }
        ],
    )


def _model_availability(
    # Keep the artifacts input explicit in the model availability contract.
    artifacts: LocalArtifactRepository,
    model_bundle_id: ModelBundleId,
) -> tuple[int, tuple[int, ...]]:
    # Execute the model availability workflow in explicit, reviewable steps.
    with NumpyModelBundleReader(artifacts, model_bundle_id) as model:
        # Keep numpy model bundle reader, artifacts and model bundle id active only for
        # the bounded model availability operation.
        return (
            model.model_available_boundary,
            model.fitted_component_available_boundaries,
        )


def _single_model_schedule(
    # Keep the stack input explicit in the single model schedule contract.
    stack: _MlStack,
    model: PublishedModelBundle,
) -> PublishedModelSchedule:
    # Execute the single model schedule workflow in explicit, reviewable steps.
    with NumpyModelBundleReader(stack.artifacts, model.model_bundle_id) as reader:
        # Keep numpy model bundle reader, artifacts and model bundle id active only for
        # the bounded single model schedule operation.
        entry = ModelScheduleEntry(
            eligible_from=stack.effective[0],
            eligible_until=stack.effective[-1] + 100,
            model_bundle_id=model.model_bundle_id,
            training_cutoff=reader.training_spec.training_cutoff,
            # Pass model available boundary explicitly so ModelScheduleEntry receives a
            # reviewable modeled-training-completion-v1 and effective input in single
            # model schedule.
            model_available_boundary=reader.model_available_boundary,
            availability_basis="modeled-training-completion-v1",
        )
    return PublishModelSchedule(_publisher(stack.artifacts)).execute(
        PublishModelScheduleRequest(
            # Include schedule in the completed single model schedule result.
            schedule=ModelSchedule((entry,)),
            canonicality=ModelCanonicality.CANONICAL_EXACT,
            compiler_version=ml_physical.COMPILER_VERSION,
        )
    )


# Define build frozen predictions as one focused operation with an explicit boundary.
def _build_frozen_predictions(
    stack: _MlStack,
    *,
    prediction_name: str,
    delay: int,
    # Keep the missing policy input explicit in the build frozen predictions contract.
    missing_policy: FrozenMissingPolicy,
) -> PublishedPredictionSet:
    # Execute the build frozen predictions workflow in explicit, reviewable steps.
    replay_semantics, replay_layout = _replay_ids(stack)
    return BuildFrozenPredictions(
        LocalExactFrozenPredictionBuilder(stack.artifacts, _publisher(stack.artifacts))
    ).execute(
        BuildFrozenPredictionsRequest(
            # Pass replay pack id explicitly so BuildFrozenPredictionsRequest receives a
            # reviewable replay pack id and feature set id input in build frozen
            # predictions.
            replay_pack_id=stack.replay_pack_id,
            replay_semantics_id=replay_semantics,
            replay_layout_schema_id=replay_layout,
            feature_set_ids=(stack.feature.feature_set_id,),
            model_schedule_id=stack.schedule.model_schedule_id,
            # Include model bundle ids in the completed build frozen predictions result.
            model_bundle_ids=tuple(item.model_bundle_id for item in stack.models),
            prediction_name=prediction_name,
            inference_delay_boundaries=delay,
            missing_policy=missing_policy,
            canonicality=ModelCanonicality.CANONICAL_EXACT,
            # Pass compiler version explicitly so BuildFrozenPredictionsRequest receives a
            # reviewable replay pack id and feature set id input in build frozen
            # predictions.
            compiler_version=ml_physical.COMPILER_VERSION,
        )
    )


def _resolve_inference_spec(
    stack: _MlStack,
    # Keep the policy input explicit in the resolve inference spec contract.
    policy: ExactInferencePolicy,
    *,
    prediction_set_ids: tuple[PredictionSetId, ...] = (),
    model_schedule_id: ModelScheduleId | None = None,
) -> ResolvedRunSpec:
    # Execute the resolve inference spec workflow in explicit, reviewable steps.
    return ReferenceRunSpecResolver(
        stack.artifacts,
        _runtime("ml"),
        parquet_memory_limit_mb=256,
        threads=1,
        # Complete ReferenceRunSpecResolver only after its ml and artifacts inputs are visible
        # in resolve inference spec.
    ).resolve(
        ReferenceRunDraft(
            snapshot_id=_snapshot_id(stack),
            replay_pack_id=stack.replay_pack_id,
            delivery_schedule_id=None,
            # Include pool id in the completed resolve inference spec result.
            pool_id=PoolId("pool"),
            sold_asset_id=AssetId("SOL"),
            bought_asset_id=AssetId("TOKEN"),
            amount_in_atomic=100,
            minimum_amount_out_atomic=0,
            # Pass fee bps explicitly so ReferenceRunDraft receives a reviewable pool and
            # sol input in resolve inference spec.
            fee_bps=30,
            execution_mode=ExecutionMode.SHADOW_STATE_REPLAY,
            maximum_order_input_atomic=1_000,
            observation_slots=0,
            order_slots=0,
            # Include initial portfolio in the completed resolve inference spec result.
            initial_portfolio=(AssetBalance(AssetId("SOL"), 1_000),),
            root_seed=42,
            maximum_dynamic_items=10_000,
            feature_set_ids=(stack.feature.feature_set_id,),
            model_schedule_id=(
                # Pass stack explicitly so ReferenceRunDraft receives a reviewable pool
                # and sol input in resolve inference spec.
                stack.schedule.model_schedule_id if model_schedule_id is None else model_schedule_id
            ),
            prediction_set_ids=prediction_set_ids,
            inference_policy=policy,
        )
        # Complete resolve only after its pool and sol inputs are visible in resolve inference
        # spec.
    )


def _run_with_predictions(
    stack: _MlStack,
    predictions: CausalScalarProvider,
    prediction_name: str,
    # Close the run with predictions signature after its explicit inputs.
    *,
    reader_batch_rows: int = 65_536,
    reader_readahead: int = 1,
) -> RunSummary:
    # Execute the run with predictions workflow in explicit, reviewable steps.
    with NumpyMmapReplaySource(stack.artifacts, stack.replay_pack_id) as replay:
        # Keep numpy mmap replay source, artifacts and replay pack id active only for the
        # bounded run with predictions operation.
        return ReferenceBacktestEngine().run(
            source=replay,
            strategy=_PredictionDrivenStrategy(prediction_name),
            execution_model=ConstantProductExecutionModel(fee_bps=30),
            risk_policy=StaticRiskPolicy(maximum_order_input_atomic=1_000),
            # Include config in the completed run with predictions result.
            config=ReferenceRunConfig(
                execution_mode=ExecutionMode.SHADOW_STATE_REPLAY,
                latency=SlotLatencyModel(observation_slots=2),
                root_seed=42,
                initial_available={AssetId("SOL"): 1_000},
                # Pass maximum dynamic items explicitly so ReferenceRunConfig receives a
                # reviewable sol and shadow state replay input in run with predictions.
                maximum_dynamic_items=10_000,
            ),
            predictions=predictions,
            physical_settings=EnginePhysicalSettings(
                reader_batch_rows=reader_batch_rows,
                # Pass reader readahead explicitly so EnginePhysicalSettings receives a
                # reviewable reader batch rows and reader readahead input in run with
                # predictions.
                reader_readahead=reader_readahead,
                threads=1,
            ),
        )


def _frozen_policy() -> ExactInferencePolicy:
    # Execute the frozen policy workflow in explicit, reviewable steps.
    return ExactInferencePolicy.frozen_exact_linear(
        prediction_name="score",
        missing_policy=InferenceMissingPolicy.NULL,
        inference_delay_boundaries=1,
    )


# Define replay ids as one focused operation with an explicit boundary.
def _replay_ids(stack: _MlStack) -> tuple[ContentDigest, ContentDigest]:
    # Execute the replay ids workflow in explicit, reviewable steps.
    from backtest.adapters.columnar.numpy.reader import NumpyMmapReplaySource

    with NumpyMmapReplaySource(stack.artifacts, stack.replay_pack_id) as replay:
        return replay.replay_semantics_id, replay.replay_layout_schema_id


def _snapshot_id(stack: _MlStack) -> SnapshotId:
    # Execute the snapshot id workflow in explicit, reviewable steps.
    with NumpyFeatureSetProvider(stack.artifacts, stack.feature.feature_set_id) as feature:
        return feature.snapshot_id


def _publisher(artifacts: LocalArtifactRepository) -> LocalNumpyMlArtifactPublisher:
    # Execute the publisher workflow in explicit, reviewable steps.
    return LocalNumpyMlArtifactPublisher(
        artifacts,
        runtime_lock_id=_runtime("ml"),
        maximum_rows_in_memory=2,
        maximum_open_spill_files=2,
        # Complete LocalNumpyMlArtifactPublisher only after its ml and runtime inputs are
        # visible in publisher.
    )


def _publish_snapshot(artifacts: LocalArtifactRepository) -> SnapshotId:
    # Execute the publish snapshot workflow in explicit, reviewable steps.
    writer = artifacts.stage(
        ArtifactDraft(kind=ArtifactKind.SNAPSHOT, build_key=ContentDigest("a" * 64))
    )
    committed = writer.commit(canonical_json_bytes(_snapshot_fidelity_manifest()))
    return SnapshotId(committed.artifact_id.hex)


# Define snapshot fidelity manifest as one focused operation with an explicit boundary.
def _snapshot_fidelity_manifest() -> dict[str, object]:
    return fixture_snapshot_manifest()


def _checked_source(
    requested: SnapshotId,
    expected: SnapshotId,
    # Keep the events input explicit in the checked source contract.
    events: tuple[CanonicalEvent, ...],
) -> _CanonicalSource:
    # Execute the checked source workflow in explicit, reviewable steps.
    if requested != expected:
        raise AssertionError("compiler requested another snapshot")
    return _CanonicalSource(events)


def _events() -> tuple[CanonicalEvent, ...]:
    # Execute the events workflow in explicit, reviewable steps.
    launches = ((100, 0), (100, 1), (102, 0), (105, 0))
    transaction_counts = {100: 2, 102: 1, 105: 1}
    result: list[CanonicalEvent] = []
    event_number = 1
    current_block: int | None = None
    # Traverse enumerate(launches) explicitly so each events iteration remains traceable.
    for launch_index, (block, transaction) in enumerate(launches):
        # Process enumerate(launches) inside the bounded events loop.
        if block != current_block:
            # Handle the events block != current_block branch as a distinct logical block.
            result.append(
                BlockEvent(
                    envelope=_fixture_envelope(
                        block=block,
                        transaction=-1,
                        # Pass event number explicitly so _fixture_envelope receives a
                        # reviewable v1 and block input in events.
                        event_number=event_number,
                        capability="fixture.events.v1",
                    ),
                    block_time_ns=block * 1_000_000_000,
                    tx_count=transaction_counts[block],
                    # Pass block hash explicitly so BlockEvent receives a reviewable v1
                    # and fixture envelope input in events.
                    block_hash=None,
                )
            )
            event_number += 1
            current_block = block
        # Invoke append for sol and reference-token-launch-payload-v1 as a visible events
        # step.
        result.append(
            TokenCreationEvent(
                envelope=_fixture_envelope(
                    block=block,
                    transaction=transaction,
                    # Pass event number explicitly so _fixture_envelope receives a
                    # reviewable v1 and block input in events.
                    event_number=event_number,
                    capability="fixture.tokens.v1",
                ),
                asset_id=AssetId(f"TOKEN-{launch_index}"),
                developer_id=AccountId(f"creator-{launch_index}"),
                # Pass creation user id explicitly to append for sol and reference-token-
                # launch-payload-v1.
                creation_user_id=AccountId(f"creator-{launch_index}"),
                venue_id=VenueId(f"launch:TOKEN-{launch_index}"),
                quote_asset_id=AssetId("SOL"),
                protocol_payload_schema=ProtocolPayloadSchemaId(
                    "reference-token-launch-payload-v1"
                    # Complete ProtocolPayloadSchemaId only after its reference-token-launch-
                    # payload-v1 inputs are visible in events.
                ),
                protocol_payload=b"",
                decimals=9,
            )
        )
        # Assemble event number once so the events workflow shares one value.
        event_number += 1
    return tuple(result)


def _fixture_envelope(
    *,
    block: int,
    # Keep the transaction input explicit in the fixture envelope contract.
    transaction: int,
    event_number: int,
    capability: str,
) -> EventEnvelope:
    # Execute the fixture envelope workflow in explicit, reviewable steps.
    return EventEnvelope(
        position=ChainPosition(
            network_id=SOLANA_MAINNET_NETWORK_ID,
            position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            block_ordinal=block,
            # Pass transaction index explicitly so ChainPosition receives a reviewable
            # solana mainnet network id and block32 transaction32 position schema id input
            # in fixture envelope.
            transaction_index=transaction,
            event_index=0,
        ),
        transaction_group_id=_numeric_digest(event_number),
        source_record_id=_numeric_digest(event_number + 100),
        # Include canonical event id in the completed fixture envelope result.
        canonical_event_id=_numeric_digest(event_number + 200),
        stable_causal_id=_numeric_digest(event_number + 300),
        capability_id=CapabilityId(capability),
        protocol="fixture",
        protocol_version="1",
        # Pass ordering fidelity explicitly so EventEnvelope receives a reviewable fixture
        # and 1 input in fixture envelope.
        ordering_fidelity=OrderingFidelity.INSTRUCTION_EXACT,
    )


def _republish_feature_array(
    artifacts: LocalArtifactRepository,
    feature_set_id: FeatureSetId,
    # Keep the target path input explicit in the republish feature array contract.
    target_path: str,
    mutate: Callable[[np.ndarray], np.ndarray],
) -> FeatureSetId:
    with artifacts.open_committed(feature_set_id) as handle:  # type: ignore[attr-defined]
        with handle.open_binary("manifest.json") as stream:
            manifest_bytes = stream.read()
        with handle.open_binary("manifest.identity.json") as stream:
            identity_bytes = stream.read()
        from backtest.application.ml_artifacts import MlArtifactManifest

        # Assemble manifest once so the republish feature array workflow shares one value.
        manifest = MlArtifactManifest.from_document(json.loads(manifest_bytes))
        payloads: dict[str, bytes] = {}
        for descriptor in manifest.layout.arrays:
            # Process manifest.layout.arrays inside the bounded republish feature array
            # loop.
            with handle.open_binary(descriptor.path) as stream:
                payloads[descriptor.path] = stream.read()
    writer = artifacts.stage(
        ArtifactDraft(
            kind=ArtifactKind.FEATURE_SET,
            # Pass build key explicitly so ArtifactDraft receives a reviewable feature set
            # and build key input in republish feature array.
            build_key=manifest.build.build_key,
            input_artifact_ids=manifest.build.input_artifact_ids,
        )
    )
    try:
        # Perform the protected republish feature array operation before explicit failure
        # handling.
        for descriptor in manifest.layout.arrays:
            # Process manifest.layout.arrays inside the bounded republish feature array
            # loop.
            with writer.open_binary(descriptor.path) as destination:
                # Keep open binary, path and writer active only for the bounded republish
                # feature array operation.
                if descriptor.path == target_path:
                    # Handle the republish feature array descriptor.path == target_path
                    # branch as a distinct logical block.
                    original = np.load(io.BytesIO(payloads[descriptor.path]), allow_pickle=False)
                    np.save(destination, mutate(original), allow_pickle=False)
                else:
                    shutil.copyfileobj(io.BytesIO(payloads[descriptor.path]), destination)
        committed = writer.commit(manifest_bytes, identity_manifest_bytes=identity_bytes)
    # Translate base exception through the republish feature array boundary without hiding
    # other errors.
    except BaseException:
        # Translate the BaseException failure through the republish feature array
        # boundary.
        writer.abort()
        raise
    return FeatureSetId(committed.artifact_id.hex)


def _digest(label: str) -> ContentDigest:
    return domain_digest("test.numpy-ml", {"label": label})


# Define bundle as one focused operation with an explicit boundary.
def _bundle(label: str) -> BundleId:
    return BundleId(_digest(label).hex)


def _runtime(label: str) -> RuntimeLockId:
    return RuntimeLockId(_digest(label).hex)


def _numeric_digest(value: int) -> ContentDigest:
    # Return the completed numeric digest result without a hidden fallback.
    return ContentDigest(f"{value:064x}")
