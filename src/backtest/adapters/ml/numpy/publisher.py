"""Bounded deterministic builders for immutable point-in-time ML overlays."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Mapping

# Import contextlib at the visible module dependency boundary.
from contextlib import ExitStack, suppress
from pathlib import Path
from typing import Final, cast

import numpy as np
import numpy.typing as npt

# Import repository at the visible module dependency boundary.
from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.adapters.columnar.numpy import layout as replay_physical
from backtest.adapters.columnar.numpy.reader import NumpyMmapReplaySource
from backtest.adapters.ml.numpy import layout as physical
from backtest.adapters.ml.numpy.reader import (
    # Include numpy feature set provider so the reader dependency remains explicit.
    NumpyFeatureSetProvider,
    NumpyModelBundleReader,
    NumpyModelScheduleReader,
    NumpyUniverseReader,
)

# Import spill at the visible module dependency boundary.
from backtest.adapters.ml.numpy.spill import SpilledRows, spill_sort
from backtest.adapters.ml.numpy.toolchain import unit_ml_build_tools
from backtest.adapters.ml.numpy.training import NumpyLabelSetReader
from backtest.application.build_tool_roles import (
    ML_COMPILER_ROLE,
    # Include ml frozen inference role so the build tool roles dependency remains
    # explicit.
    ML_FROZEN_INFERENCE_ROLE,
    ML_WRITER_ROLE,
)
from backtest.application.code_bundles import PinnedCodeBundleSet
from backtest.application.ml_artifacts import (
    # Include build feature set request so the ml artifacts dependency remains explicit.
    BuildFeatureSetRequest,
    BuildLabelSetRequest,
    BuildPredictionSetRequest,
    BuildUniverseRequest,
    FeatureOverlayRow,
    # Include feature set artifact manifest so the ml artifacts dependency remains
    # explicit.
    FeatureSetArtifactManifest,
    FeatureSetBuildManifest,
    FrozenPredictionRow,
    LabelOverlayRow,
    LabelSetArtifactManifest,
    # Include label set build manifest so the ml artifacts dependency remains explicit.
    LabelSetBuildManifest,
    MlArtifactContractError,
    MlArtifactManifest,
    MlArtifactSchema,
    MlBuildManifest,
    # Include ml layout manifest so the ml artifacts dependency remains explicit.
    MlLayoutManifest,
    MlLogicalStreamHasher,
    ModelBundleArtifactManifest,
    ModelBundleBuildManifest,
    ModelScheduleArtifactManifest,
    # Include model schedule build manifest so the ml artifacts dependency remains
    # explicit.
    ModelScheduleBuildManifest,
    PredictionSetArtifactManifest,
    PredictionSetBuildManifest,
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
    UniverseArtifactManifest,
    UniverseBuildManifest,
    UniverseMembershipRow,
    feature_spec_document,
    # Include model schedule document so the ml artifacts dependency remains explicit.
    model_schedule_document,
    training_spec_document,
)
from backtest.application.ml_contracts import ModelSchedule, NullPolicy
from backtest.application.models import ArtifactDraft, ArtifactKind, CommittedArtifact

# Import artifacts at the visible module dependency boundary.
from backtest.application.ports.artifacts import ArtifactWriter
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.domain.identifiers import (
    ArtifactId,
    BundleId,
    # Include content digest so the identifiers dependency remains explicit.
    ContentDigest,
    ModelBundleId,
    RuntimeLockId,
)

_UINT64_MAX: Final = (1 << 64) - 1
# Bind int64 min once as an explicit module-level contract.
_INT64_MIN: Final = -(1 << 63)
_INT64_MAX: Final = (1 << 63) - 1


class NumpyMlArtifactCompileError(RuntimeError):
    """An ML artifact cannot be materialized without changing its semantics."""


class LocalNumpyMlArtifactPublisher:
    """Publish all Phase-6 overlay kinds through one deterministic local writer."""

    def __init__(
        self,
        artifacts: LocalArtifactRepository,
        *,
        runtime_lock_id: RuntimeLockId,
        # Keep the maximum rows in memory input explicit in the init contract.
        maximum_rows_in_memory: int = 65_536,
        maximum_open_spill_files: int = 16,
        build_tools: PinnedCodeBundleSet | None = None,
    ) -> None:
        # Execute the local numpy ml artifact publisher init workflow in explicit,
        # reviewable steps.
        if maximum_rows_in_memory <= 0:
            raise ValueError("maximum_rows_in_memory must be positive")
        if maximum_open_spill_files < 2:
            raise ValueError("maximum_open_spill_files must be at least two")
        self._artifacts = artifacts
        # Assemble self runtime lock id once so the local numpy ml artifact publisher init
        # workflow shares one value.
        self._runtime_lock_id = runtime_lock_id
        self._build_tools = build_tools or unit_ml_build_tools()
        self._compiler_bundle_id = self._build_tools.require_current(ML_COMPILER_ROLE)
        self._writer_bundle_id = self._build_tools.require_current(ML_WRITER_ROLE)
        self._maximum_rows_in_memory = maximum_rows_in_memory
        # Assemble self maximum open spill files once so the local numpy ml artifact
        # publisher init workflow shares one value.
        self._maximum_open_spill_files = maximum_open_spill_files
        self._tmp_root = artifacts.data_root / "tmp" / "ml"
        self._tmp_root.mkdir(parents=True, exist_ok=True)

    def build_feature_set(self, request: BuildFeatureSetRequest) -> PublishedFeatureSet:
        # Execute the local numpy ml artifact publisher build feature set workflow in
        # explicit, reviewable steps.
        self._require_current_tools()
        _require_compiler_version(request.compiler_version)
        if any(spec.dtype != "<i8" for spec in request.feature_specs):
            raise NumpyMlArtifactCompileError("FeatureSet v1 supports only explicit <i8 values")
        semantic_inputs = {
            # Keep the alignment policy component named inside the semantic inputs
            # contract.
            "alignment_policy": "dense-replay-row-id-v1",
            "feature_specs": [feature_spec_document(spec) for spec in request.feature_specs],
            "input_feature_set_ids": [item.hex for item in request.input_feature_set_ids],
            "replay_layout_schema_id": request.replay_layout_schema_id.hex,
            "replay_pack_id": request.replay_pack_id.hex,
            # Keep the replay semantics id component named inside the semantic inputs
            # contract.
            "replay_semantics_id": request.replay_semantics_id.hex,
        }
        inputs = _sorted_ids((request.replay_pack_id, *request.input_feature_set_ids))
        build = _build_manifest(
            FeatureSetBuildManifest,
            # Pass ml artifact schema explicitly so _build_manifest receives a reviewable
            # feature set and runtime lock id input in local numpy ml artifact publisher
            # build feature set.
            MlArtifactSchema.FEATURE_SET,
            inputs,
            semantic_inputs,
            self._runtime_lock_id,
            self._compiler_bundle_id,
            # Pass self explicitly so _build_manifest receives a reviewable feature set
            # and runtime lock id input in local numpy ml artifact publisher build feature
            # set.
            self._writer_bundle_id,
        )
        writer = self._stage(ArtifactKind.FEATURE_SET, build)
        temporary_root = self._temporary("features-")
        try:
            # Perform the protected local numpy ml artifact publisher build feature set
            # operation before explicit failure handling.
            with ExitStack() as stack:
                # Keep exit stack active only for the bounded local numpy ml artifact
                # publisher build feature set operation.
                replay = stack.enter_context(
                    NumpyMmapReplaySource(
                        self._artifacts,
                        request.replay_pack_id,
                        build_tools=self._build_tools,
                        # Complete NumpyMmapReplaySource only after its artifacts and replay
                        # pack id inputs are visible in local numpy ml artifact publisher
                        # build feature set.
                    )
                )
                dependencies = tuple(
                    stack.enter_context(
                        NumpyFeatureSetProvider(
                            # Pass self explicitly so NumpyFeatureSetProvider receives a
                            # reviewable artifacts and build tools input in local numpy ml
                            # artifact publisher build feature set.
                            self._artifacts,
                            feature_id,
                            build_tools=self._build_tools,
                        )
                    )
                    # Pass feature id explicitly so tuple receives a reviewable enter
                    # context and input feature set ids input in local numpy ml artifact
                    # publisher build feature set.
                    for feature_id in request.input_feature_set_ids
                )
                _require_replay(replay, request)
                if any(item.replay_pack_id != request.replay_pack_id for item in dependencies):
                    # Handle the local numpy ml artifact publisher build feature set
                    # replay pack id, item and dependencies condition as a distinct block.
                    raise NumpyMlArtifactCompileError(
                        "FeatureSet dependencies align to another ReplayPack"
                    )
                spilled = self._spill_features(temporary_root, request)
                count = replay.manifest.event_count
                # Guard this path with spilled.count != count before applying effects.
                if spilled.count != count:
                    # Handle the local numpy ml artifact publisher build feature set
                    # spilled.count != count branch as a distinct logical block.
                    raise NumpyMlArtifactCompileError(
                        "FeatureSet must contain exactly one row per ReplayPack event"
                    )
                layout = physical.feature_layout(count, len(request.feature_specs))
                logical_hash, maximum = _write_features(
                    # Pass temporary root explicitly so _write_features receives a
                    # reviewable temporary root and layout input in local numpy ml
                    # artifact publisher build feature set.
                    temporary_root,
                    layout,
                    spilled,
                    request,
                    replay,
                    # Complete _write_features only after its temporary root and layout inputs
                    # are visible in local numpy ml artifact publisher build feature set.
                )
            content = {**semantic_inputs, "maximum_available_boundary": maximum}
            manifest = FeatureSetArtifactManifest(
                artifact_schema=MlArtifactSchema.FEATURE_SET,
                build=build,
                # Pass row count explicitly so FeatureSetArtifactManifest receives a
                # reviewable feature set and canonical json bytes input in local numpy ml
                # artifact publisher build feature set.
                row_count=count,
                logical_content_hash=logical_hash,
                layout=layout,
                semantic_content=canonical_json_bytes(content),
            )
            # Assemble committed once so the local numpy ml artifact publisher build
            # feature set workflow shares one value.
            committed = _commit(writer, temporary_root, manifest)
        except BaseException:
            # Translate the BaseException failure through the local numpy ml artifact
            # publisher build feature set boundary.
            writer.abort()
            raise
        finally:
            shutil.rmtree(temporary_root, ignore_errors=True)
        return PublishedFeatureSet(
            # Pass committed explicitly so PublishedFeatureSet receives a reviewable
            # artifacts and artifact id input in local numpy ml artifact publisher build
            # feature set.
            committed,
            _read_committed_manifest(self._artifacts, committed.artifact_id),
            build,
        )

    def build_universe(self, request: BuildUniverseRequest) -> PublishedUniverse:
        # Execute the local numpy ml artifact publisher build universe workflow in
        # explicit, reviewable steps.
        self._require_current_tools()
        _require_compiler_version(request.compiler_version)
        semantic_inputs = {
            "builder_bundle_id": request.builder_bundle_id.hex,
            "builder_config_digest": request.builder_config_digest.hex,
            # Keep the input feature set ids component named inside the semantic inputs
            # contract.
            "input_feature_set_ids": [item.hex for item in request.input_feature_set_ids],
            "snapshot_id": request.snapshot_id.hex,
            "universe_spec_id": request.universe_spec_id.hex,
        }
        inputs = _sorted_ids((request.snapshot_id, *request.input_feature_set_ids))
        # Assemble build once so the local numpy ml artifact publisher build universe
        # workflow shares one value.
        build = _build_manifest(
            UniverseBuildManifest,
            MlArtifactSchema.UNIVERSE,
            inputs,
            semantic_inputs,
            # Pass self explicitly so _build_manifest receives a reviewable universe and
            # runtime lock id input in local numpy ml artifact publisher build universe.
            self._runtime_lock_id,
            self._compiler_bundle_id,
            self._writer_bundle_id,
        )
        writer = self._stage(ArtifactKind.UNIVERSE, build)
        # Assemble temporary root once so the local numpy ml artifact publisher build
        # universe workflow shares one value.
        temporary_root = self._temporary("universe-")
        try:
            # Perform the protected local numpy ml artifact publisher build universe
            # operation before explicit failure handling.
            _require_kind(self._artifacts, request.snapshot_id, ArtifactKind.SNAPSHOT)
            with ExitStack() as stack:
                # Keep exit stack active only for the bounded local numpy ml artifact
                # publisher build universe operation.
                features = tuple(
                    stack.enter_context(
                        NumpyFeatureSetProvider(
                            self._artifacts,
                            feature_id,
                            # Pass build tools explicitly so NumpyFeatureSetProvider
                            # receives a reviewable artifacts and build tools input in
                            # local numpy ml artifact publisher build universe.
                            build_tools=self._build_tools,
                        )
                    )
                    for feature_id in request.input_feature_set_ids
                )
                # Evaluate the complete local numpy ml artifact publisher build universe
                # snapshot id, feature and features condition before guarded effects.
                if any(feature.snapshot_id != request.snapshot_id for feature in features):
                    # Handle the local numpy ml artifact publisher build universe snapshot
                    # id, feature and features condition as a distinct block.
                    raise NumpyMlArtifactCompileError(
                        "Universe feature inputs belong to another snapshot"
                    )
            spilled = self._spill_universe(temporary_root, request)
            layout = physical.universe_layout(spilled.count)
            # Assemble (logical hash, maximum) once so the local numpy ml artifact
            # publisher build universe workflow shares one value.
            logical_hash, maximum = _write_universe(temporary_root, layout, spilled)
            content = {**semantic_inputs, "maximum_input_available_boundary": maximum}
            manifest = UniverseArtifactManifest(
                artifact_schema=MlArtifactSchema.UNIVERSE,
                build=build,
                # Pass row count explicitly so UniverseArtifactManifest receives a
                # reviewable universe and count input in local numpy ml artifact publisher
                # build universe.
                row_count=spilled.count,
                logical_content_hash=logical_hash,
                layout=layout,
                semantic_content=canonical_json_bytes(content),
            )
            # Assemble committed once so the local numpy ml artifact publisher build
            # universe workflow shares one value.
            committed = _commit(writer, temporary_root, manifest)
        except BaseException:
            # Translate the BaseException failure through the local numpy ml artifact
            # publisher build universe boundary.
            writer.abort()
            raise
        finally:
            shutil.rmtree(temporary_root, ignore_errors=True)
        return PublishedUniverse(
            # Pass committed explicitly so PublishedUniverse receives a reviewable
            # artifacts and artifact id input in local numpy ml artifact publisher build
            # universe.
            committed,
            _read_committed_manifest(self._artifacts, committed.artifact_id),
            build,
        )

    def build_label_set(self, request: BuildLabelSetRequest) -> PublishedLabelSet:
        # Execute the local numpy ml artifact publisher build label set workflow in
        # explicit, reviewable steps.
        self._require_current_tools()
        _require_compiler_version(request.compiler_version)
        semantic_inputs = {
            "label_builder_bundle_id": request.label_builder_bundle_id.hex,
            "label_config_digest": request.label_config_digest.hex,
            # Keep the label spec id component named inside the semantic inputs contract.
            "label_spec_id": request.label_spec_id.hex,
            "snapshot_id": request.snapshot_id.hex,
            "training_cutoff": request.training_cutoff,
            "universe_id": request.universe_id.hex,
        }
        # Assemble inputs once so the local numpy ml artifact publisher build label set
        # workflow shares one value.
        inputs = _sorted_ids((request.snapshot_id, request.universe_id))
        build = _build_manifest(
            LabelSetBuildManifest,
            MlArtifactSchema.LABEL_SET,
            inputs,
            # Pass semantic inputs explicitly so _build_manifest receives a reviewable
            # label set and runtime lock id input in local numpy ml artifact publisher
            # build label set.
            semantic_inputs,
            self._runtime_lock_id,
            self._compiler_bundle_id,
            self._writer_bundle_id,
        )
        # Assemble writer once so the local numpy ml artifact publisher build label set
        # workflow shares one value.
        writer = self._stage(ArtifactKind.LABEL_SET, build)
        temporary_root = self._temporary("labels-")
        try:
            # Perform the protected local numpy ml artifact publisher build label set
            # operation before explicit failure handling.
            _require_kind(self._artifacts, request.snapshot_id, ArtifactKind.SNAPSHOT)
            with NumpyUniverseReader(
                self._artifacts,
                request.universe_id,
                build_tools=self._build_tools,
                # Complete NumpyUniverseReader only after its artifacts and universe id inputs
                # are visible in local numpy ml artifact publisher build label set.
            ) as universe:
                # Keep numpy universe reader, artifacts and universe id active only for
                # the bounded local numpy ml artifact publisher build label set operation.
                if universe.snapshot_id != request.snapshot_id:
                    # Handle the local numpy ml artifact publisher build label set
                    # snapshot id, universe and request condition as a distinct block.
                    raise NumpyMlArtifactCompileError(
                        "LabelSet universe belongs to another snapshot"
                    )
            spilled = self._spill_labels(temporary_root, request)
            layout = physical.label_layout(spilled.count)
            # Assemble (logical hash, maximum) once so the local numpy ml artifact
            # publisher build label set workflow shares one value.
            logical_hash, maximum = _write_labels(
                temporary_root,
                layout,
                spilled,
                request.training_cutoff,
                # Complete _write_labels only after its training cutoff and temporary root
                # inputs are visible in local numpy ml artifact publisher build label set.
            )
            content = {**semantic_inputs, "maximum_future_boundary_used": maximum}
            manifest = LabelSetArtifactManifest(
                artifact_schema=MlArtifactSchema.LABEL_SET,
                build=build,
                # Pass row count explicitly so LabelSetArtifactManifest receives a
                # reviewable label set and count input in local numpy ml artifact
                # publisher build label set.
                row_count=spilled.count,
                logical_content_hash=logical_hash,
                layout=layout,
                semantic_content=canonical_json_bytes(content),
            )
            # Assemble committed once so the local numpy ml artifact publisher build label
            # set workflow shares one value.
            committed = _commit(writer, temporary_root, manifest)
        except BaseException:
            # Translate the BaseException failure through the local numpy ml artifact
            # publisher build label set boundary.
            writer.abort()
            raise
        finally:
            shutil.rmtree(temporary_root, ignore_errors=True)
        return PublishedLabelSet(
            # Pass committed explicitly so PublishedLabelSet receives a reviewable
            # artifacts and artifact id input in local numpy ml artifact publisher build
            # label set.
            committed,
            _read_committed_manifest(self._artifacts, committed.artifact_id),
            build,
        )

    def publish_model_bundle(
        # Keep the remaining publish model bundle inputs visible at the local numpy ml
        # artifact publisher publish model bundle boundary.
        self,
        request: PublishModelBundleRequest,
    ) -> PublishedModelBundle:
        # Execute the local numpy ml artifact publisher publish model bundle workflow in
        # explicit, reviewable steps.
        self._require_current_tools()
        _require_compiler_version(request.compiler_version)
        inputs = _sorted_ids(
            (
                *request.training_spec.feature_set_ids,
                # Pass request explicitly so _sorted_ids receives a reviewable label set
                # id and universe id input in local numpy ml artifact publisher publish
                # model bundle.
                request.training_spec.label_set_id,
                request.training_spec.universe_id,
            )
        )
        semantic_inputs = {
            # Keep the calibration digest component named inside the semantic inputs
            # contract.
            "calibration_digest": request.calibration_digest.hex,
            "canonicality": request.canonicality.value,
            "feature_schema_digest": request.feature_schema_digest.hex,
            "fitted_component_available_boundaries": list(
                request.fitted_component_available_boundaries
                # Complete list only after its fitted component available boundaries and
                # request inputs are visible in local numpy ml artifact publisher publish
                # model bundle.
            ),
            "framework": request.framework,
            "metrics_digest": request.metrics_digest.hex,
            "model_available_boundary": request.training_spec.modeled_available_boundary,
            "output_divisor": request.payload.output_divisor,
            # Keep the preprocessing digest component named inside the semantic inputs
            # contract.
            "preprocessing_digest": request.preprocessing_digest.hex,
            "training_spec": training_spec_document(request.training_spec),
            "weight_count": len(request.payload.weights),
        }
        build = _build_manifest(
            # Pass model bundle build manifest explicitly so _build_manifest receives a
            # reviewable model bundle and runtime lock id input in local numpy ml artifact
            # publisher publish model bundle.
            ModelBundleBuildManifest,
            MlArtifactSchema.MODEL_BUNDLE,
            inputs,
            semantic_inputs,
            self._runtime_lock_id,
            # Pass self explicitly so _build_manifest receives a reviewable model bundle
            # and runtime lock id input in local numpy ml artifact publisher publish model
            # bundle.
            self._compiler_bundle_id,
            self._writer_bundle_id,
        )
        writer = self._stage(ArtifactKind.MODEL_BUNDLE, build)
        temporary_root = self._temporary("model-")
        # Keep expected failures inside the local numpy ml artifact publisher publish
        # model bundle error boundary.
        try:
            # Perform the protected local numpy ml artifact publisher publish model bundle
            # operation before explicit failure handling.
            with ExitStack() as stack:
                # Keep exit stack active only for the bounded local numpy ml artifact
                # publisher publish model bundle operation.
                features = tuple(
                    stack.enter_context(
                        NumpyFeatureSetProvider(
                            self._artifacts,
                            feature_id,
                            # Pass build tools explicitly so NumpyFeatureSetProvider
                            # receives a reviewable artifacts and build tools input in
                            # local numpy ml artifact publisher publish model bundle.
                            build_tools=self._build_tools,
                        )
                    )
                    for feature_id in request.training_spec.feature_set_ids
                )
                # Assemble label once so the local numpy ml artifact publisher publish
                # model bundle workflow shares one value.
                label = stack.enter_context(
                    NumpyLabelSetReader(
                        self._artifacts,
                        request.training_spec.label_set_id,
                        build_tools=self._build_tools,
                        # Complete NumpyLabelSetReader only after its artifacts and label set
                        # id inputs are visible in local numpy ml artifact publisher publish
                        # model bundle.
                    )
                )
                universe = stack.enter_context(
                    NumpyUniverseReader(
                        self._artifacts,
                        # Pass request explicitly so NumpyUniverseReader receives a
                        # reviewable artifacts and universe id input in local numpy ml
                        # artifact publisher publish model bundle.
                        request.training_spec.universe_id,
                        build_tools=self._build_tools,
                    )
                )
                _validate_training_inputs(request, features, label, universe)
            # Assemble layout once so the local numpy ml artifact publisher publish model
            # bundle workflow shares one value.
            layout = physical.model_layout(len(request.payload.weights))
            logical_hash = _write_model(temporary_root, layout, request)
            manifest = ModelBundleArtifactManifest(
                artifact_schema=MlArtifactSchema.MODEL_BUNDLE,
                build=build,
                # Pass row count explicitly so ModelBundleArtifactManifest receives a
                # reviewable model bundle and canonical json bytes input in local numpy ml
                # artifact publisher publish model bundle.
                row_count=1,
                logical_content_hash=logical_hash,
                layout=layout,
                semantic_content=canonical_json_bytes(semantic_inputs),
            )
            # Assemble committed once so the local numpy ml artifact publisher publish
            # model bundle workflow shares one value.
            committed = _commit(writer, temporary_root, manifest)
        except BaseException:
            # Translate the BaseException failure through the local numpy ml artifact
            # publisher publish model bundle boundary.
            writer.abort()
            raise
        finally:
            shutil.rmtree(temporary_root, ignore_errors=True)
        return PublishedModelBundle(
            # Pass committed explicitly so PublishedModelBundle receives a reviewable
            # artifacts and artifact id input in local numpy ml artifact publisher publish
            # model bundle.
            committed,
            _read_committed_manifest(self._artifacts, committed.artifact_id),
            build,
        )

    def publish_model_schedule(
        # Keep the remaining publish model schedule inputs visible at the local numpy ml
        # artifact publisher publish model schedule boundary.
        self,
        request: PublishModelScheduleRequest,
    ) -> PublishedModelSchedule:
        # Execute the local numpy ml artifact publisher publish model schedule workflow in
        # explicit, reviewable steps.
        self._require_current_tools()
        _require_compiler_version(request.compiler_version)
        model_ids = _schedule_model_ids(request.schedule)
        semantic_inputs = {
            "canonicality": request.canonicality.value,
            # Register schedule through model_schedule_document so the semantic inputs
            # table remains scannable.
            "schedule": model_schedule_document(request.schedule),
        }
        build = _build_manifest(
            ModelScheduleBuildManifest,
            MlArtifactSchema.MODEL_SCHEDULE,
            # Keep the sorted ids and cast _sorted_ids step visible while building build.
            _sorted_ids(cast(tuple[ArtifactId, ...], model_ids)),
            semantic_inputs,
            self._runtime_lock_id,
            self._compiler_bundle_id,
            self._writer_bundle_id,
            # Complete _build_manifest only after its model schedule and runtime lock id
            # inputs are visible in local numpy ml artifact publisher publish model schedule.
        )
        writer = self._stage(ArtifactKind.MODEL_SCHEDULE, build)
        temporary_root = self._temporary("schedule-")
        try:
            # Perform the protected local numpy ml artifact publisher publish model
            # schedule operation before explicit failure handling.
            with ExitStack() as stack:
                # Keep exit stack active only for the bounded local numpy ml artifact
                # publisher publish model schedule operation.
                models = {
                    model_id: stack.enter_context(
                        NumpyModelBundleReader(
                            self._artifacts,
                            model_id,
                            # Pass build tools explicitly so NumpyModelBundleReader
                            # receives a reviewable artifacts and build tools input in
                            # local numpy ml artifact publisher publish model schedule.
                            build_tools=self._build_tools,
                        )
                    )
                    for model_id in model_ids
                }
                # Invoke _validate_schedule_models for request and models as a visible
                # local numpy ml artifact publisher publish model schedule step.
                _validate_schedule_models(request, models)
            layout = physical.schedule_layout(len(request.schedule.entries))
            logical_hash = _write_schedule(temporary_root, layout, request.schedule)
            manifest = ModelScheduleArtifactManifest(
                artifact_schema=MlArtifactSchema.MODEL_SCHEDULE,
                # Pass build explicitly so ModelScheduleArtifactManifest receives a
                # reviewable model schedule and entries input in local numpy ml artifact
                # publisher publish model schedule.
                build=build,
                row_count=len(request.schedule.entries),
                logical_content_hash=logical_hash,
                layout=layout,
                semantic_content=canonical_json_bytes(semantic_inputs),
                # Complete ModelScheduleArtifactManifest only after its model schedule and
                # entries inputs are visible in local numpy ml artifact publisher publish
                # model schedule.
            )
            committed = _commit(writer, temporary_root, manifest)
        except BaseException:
            # Translate the BaseException failure through the local numpy ml artifact
            # publisher publish model schedule boundary.
            writer.abort()
            raise
        finally:
            shutil.rmtree(temporary_root, ignore_errors=True)
        return PublishedModelSchedule(
            # Pass committed explicitly so PublishedModelSchedule receives a reviewable
            # artifacts and artifact id input in local numpy ml artifact publisher publish
            # model schedule.
            committed,
            _read_committed_manifest(self._artifacts, committed.artifact_id),
            build,
        )

    def build_prediction_set(
        # Keep the remaining build prediction set inputs visible at the local numpy ml
        # artifact publisher build prediction set boundary.
        self,
        request: BuildPredictionSetRequest,
    ) -> PublishedPredictionSet:
        # Execute the local numpy ml artifact publisher build prediction set workflow in
        # explicit, reviewable steps.
        self._require_current_tools()
        _require_compiler_version(request.compiler_version)
        inference_compiler_bundle_id = self._build_tools.require_current(ML_FROZEN_INFERENCE_ROLE)
        semantic_inputs = {
            "canonicality": request.canonicality.value,
            # Keep the causal availability policy component named inside the semantic
            # inputs contract.
            "causal_availability_policy": request.causal_availability_policy,
            "feature_set_ids": [item.hex for item in request.feature_set_ids],
            "inference_mode": request.inference_mode.value,
            "inference_compiler_bundle_id": inference_compiler_bundle_id.hex,
            "inference_policy_digest": request.inference_policy_digest.hex,
            # Keep the model bundle ids component named inside the semantic inputs
            # contract.
            "model_bundle_ids": [item.hex for item in request.model_bundle_ids],
            "model_schedule_id": request.model_schedule_id.hex,
            "prediction_name": request.prediction_name,
            "replay_layout_schema_id": request.replay_layout_schema_id.hex,
            "replay_pack_id": request.replay_pack_id.hex,
            # Keep the replay semantics id component named inside the semantic inputs
            # contract.
            "replay_semantics_id": request.replay_semantics_id.hex,
        }
        inputs = _sorted_ids(
            (
                request.replay_pack_id,
                # Pass request explicitly so _sorted_ids receives a reviewable replay pack
                # id and model schedule id input in local numpy ml artifact publisher
                # build prediction set.
                *request.feature_set_ids,
                request.model_schedule_id,
                *request.model_bundle_ids,
            )
        )
        # Assemble build once so the local numpy ml artifact publisher build prediction
        # set workflow shares one value.
        build = _build_manifest(
            PredictionSetBuildManifest,
            MlArtifactSchema.PREDICTION_SET,
            inputs,
            semantic_inputs,
            # Pass self explicitly so _build_manifest receives a reviewable prediction set
            # and runtime lock id input in local numpy ml artifact publisher build
            # prediction set.
            self._runtime_lock_id,
            self._compiler_bundle_id,
            self._writer_bundle_id,
        )
        writer = self._stage(ArtifactKind.PREDICTION_SET, build)
        # Assemble temporary root once so the local numpy ml artifact publisher build
        # prediction set workflow shares one value.
        temporary_root = self._temporary("predictions-")
        try:
            # Perform the protected local numpy ml artifact publisher build prediction set
            # operation before explicit failure handling.
            with ExitStack() as stack:
                # Keep exit stack active only for the bounded local numpy ml artifact
                # publisher build prediction set operation.
                replay = stack.enter_context(
                    NumpyMmapReplaySource(
                        self._artifacts,
                        request.replay_pack_id,
                        build_tools=self._build_tools,
                        # Complete NumpyMmapReplaySource only after its artifacts and replay
                        # pack id inputs are visible in local numpy ml artifact publisher
                        # build prediction set.
                    )
                )
                features = tuple(
                    stack.enter_context(
                        NumpyFeatureSetProvider(
                            # Pass self explicitly so NumpyFeatureSetProvider receives a
                            # reviewable artifacts and build tools input in local numpy ml
                            # artifact publisher build prediction set.
                            self._artifacts,
                            feature_id,
                            build_tools=self._build_tools,
                        )
                    )
                    # Pass feature id explicitly so tuple receives a reviewable enter
                    # context and feature set ids input in local numpy ml artifact
                    # publisher build prediction set.
                    for feature_id in request.feature_set_ids
                )
                schedule = stack.enter_context(
                    NumpyModelScheduleReader(
                        self._artifacts,
                        # Pass request explicitly so NumpyModelScheduleReader receives a
                        # reviewable artifacts and model schedule id input in local numpy
                        # ml artifact publisher build prediction set.
                        request.model_schedule_id,
                        build_tools=self._build_tools,
                    )
                )
                models = tuple(
                    # Keep the enter context and stack enter_context step visible while
                    # building models.
                    stack.enter_context(
                        NumpyModelBundleReader(
                            self._artifacts,
                            model_id,
                            build_tools=self._build_tools,
                            # Complete NumpyModelBundleReader only after its artifacts and
                            # build tools inputs are visible in local numpy ml artifact
                            # publisher build prediction set.
                        )
                    )
                    for model_id in request.model_bundle_ids
                )
                _validate_prediction_inputs(request, replay, features, schedule, models)
                # Assemble spilled once so the local numpy ml artifact publisher build
                # prediction set workflow shares one value.
                spilled = self._spill_predictions(temporary_root, request)
                count = replay.manifest.event_count
                if spilled.count != count:
                    # Handle the local numpy ml artifact publisher build prediction set
                    # spilled.count != count branch as a distinct logical block.
                    raise NumpyMlArtifactCompileError(
                        "PredictionSet must contain exactly one row per ReplayPack event"
                    )
                layout = physical.prediction_layout(count)
                logical_hash, maximum, operands = _write_predictions(
                    # Pass temporary root explicitly so _write_predictions receives a
                    # reviewable temporary root and layout input in local numpy ml
                    # artifact publisher build prediction set.
                    temporary_root,
                    layout,
                    spilled,
                    replay,
                    features,
                    # Pass schedule explicitly so _write_predictions receives a reviewable
                    # temporary root and layout input in local numpy ml artifact publisher
                    # build prediction set.
                    schedule,
                    models,
                    request,
                )
            content = {
                # Keep the semantic inputs component named inside the content contract.
                **semantic_inputs,
                "maximum_available_boundary": maximum,
                "model_availability_operands": operands,
            }
            manifest = PredictionSetArtifactManifest(
                # Pass artifact schema explicitly so PredictionSetArtifactManifest
                # receives a reviewable prediction set and canonical json bytes input in
                # local numpy ml artifact publisher build prediction set.
                artifact_schema=MlArtifactSchema.PREDICTION_SET,
                build=build,
                row_count=count,
                logical_content_hash=logical_hash,
                layout=layout,
                # Keep the content canonical_json_bytes step visible while building
                # manifest.
                semantic_content=canonical_json_bytes(content),
            )
            committed = _commit(writer, temporary_root, manifest)
        except BaseException:
            # Translate the BaseException failure through the local numpy ml artifact
            # publisher build prediction set boundary.
            writer.abort()
            raise
        finally:
            shutil.rmtree(temporary_root, ignore_errors=True)
        return PublishedPredictionSet(
            # Pass committed explicitly so PublishedPredictionSet receives a reviewable
            # artifacts and artifact id input in local numpy ml artifact publisher build
            # prediction set.
            committed,
            _read_committed_manifest(self._artifacts, committed.artifact_id),
            build,
        )

    def _stage(self, kind: ArtifactKind, build: MlBuildManifest) -> ArtifactWriter:
        # Execute the local numpy ml artifact publisher stage workflow in explicit,
        # reviewable steps.
        return self._artifacts.stage(
            ArtifactDraft(
                kind=kind,
                build_key=build.build_key,
                input_artifact_ids=build.input_artifact_ids,
                # Complete ArtifactDraft only after its build key and input artifact ids
                # inputs are visible in local numpy ml artifact publisher stage.
            )
        )

    def _temporary(self, prefix: str) -> Path:
        return Path(tempfile.mkdtemp(prefix=prefix, dir=self._tmp_root))

    def _spill_features(
        # Keep the remaining spill features inputs visible at the local numpy ml artifact
        # publisher spill features boundary.
        self,
        root: Path,
        request: BuildFeatureSetRequest,
    ) -> SpilledRows:
        # Execute the local numpy ml artifact publisher spill features workflow in
        # explicit, reviewable steps.
        return spill_sort(
            request.rows,
            encode=_feature_document,
            key=lambda document: (_document_int(document, "replay_row_id"),),
            root=root / "spill",
            # Pass maximum rows in memory explicitly so spill_sort receives a reviewable
            # replay row id and spill input in local numpy ml artifact publisher spill
            # features.
            maximum_rows_in_memory=self._maximum_rows_in_memory,
            maximum_open_files=self._maximum_open_spill_files,
        )

    def _spill_universe(
        self,
        # Keep the root input explicit in the spill universe contract.
        root: Path,
        request: BuildUniverseRequest,
    ) -> SpilledRows:
        # Execute the local numpy ml artifact publisher spill universe workflow in
        # explicit, reviewable steps.
        return spill_sort(
            request.rows,
            encode=_universe_document,
            key=lambda document: (
                _document_int(document, "entity_id"),
                # Include document int in the completed local numpy ml artifact publisher
                # spill universe result.
                _document_int(document, "eligible_from"),
            ),
            root=root / "spill",
            maximum_rows_in_memory=self._maximum_rows_in_memory,
            maximum_open_files=self._maximum_open_spill_files,
            # Complete spill_sort only after its entity id and eligible from inputs are
            # visible in local numpy ml artifact publisher spill universe.
        )

    def _spill_labels(
        self,
        root: Path,
        request: BuildLabelSetRequest,
        # Keep the spilled rows input explicit in the spill labels contract.
    ) -> SpilledRows:
        # Execute the local numpy ml artifact publisher spill labels workflow in explicit,
        # reviewable steps.
        return spill_sort(
            request.rows,
            encode=_label_document,
            key=lambda document: (_document_int(document, "replay_row_id"),),
            root=root / "spill",
            # Pass maximum rows in memory explicitly so spill_sort receives a reviewable
            # replay row id and spill input in local numpy ml artifact publisher spill
            # labels.
            maximum_rows_in_memory=self._maximum_rows_in_memory,
            maximum_open_files=self._maximum_open_spill_files,
        )

    def _spill_predictions(
        self,
        # Keep the root input explicit in the spill predictions contract.
        root: Path,
        request: BuildPredictionSetRequest,
    ) -> SpilledRows:
        # Execute the local numpy ml artifact publisher spill predictions workflow in
        # explicit, reviewable steps.
        return spill_sort(
            request.rows,
            encode=_prediction_document,
            key=lambda document: (_document_int(document, "replay_row_id"),),
            root=root / "spill",
            # Pass maximum rows in memory explicitly so spill_sort receives a reviewable
            # replay row id and spill input in local numpy ml artifact publisher spill
            # predictions.
            maximum_rows_in_memory=self._maximum_rows_in_memory,
            maximum_open_files=self._maximum_open_spill_files,
        )

    def _require_current_tools(self) -> None:
        # Execute the local numpy ml artifact publisher require current tools workflow in
        # explicit, reviewable steps.
        if (
            self._build_tools.require_current(ML_COMPILER_ROLE) != self._compiler_bundle_id
            or self._build_tools.require_current(ML_WRITER_ROLE) != self._writer_bundle_id
        ):
            raise NumpyMlArtifactCompileError("ML build tool identity changed")


# Define build manifest as one focused operation with an explicit boundary.
def _build_manifest[T: MlBuildManifest](
    manifest_type: type[T],
    schema: MlArtifactSchema,
    inputs: tuple[ArtifactId, ...],
    semantic_inputs: Mapping[str, object],
    # Keep the runtime lock id input explicit in the build manifest contract.
    runtime_lock_id: RuntimeLockId,
    compiler_bundle_id: BundleId,
    writer_bundle_id: BundleId,
) -> T:
    # Execute the build manifest workflow in explicit, reviewable steps.
    return manifest_type(
        artifact_schema=schema,
        input_artifact_ids=inputs,
        semantic_inputs=canonical_json_bytes(dict(semantic_inputs)),
        compiler_bundle_id=compiler_bundle_id,
        # Pass compiler version explicitly so manifest_type receives a reviewable compiler
        # version and writer settings digest input in build manifest.
        compiler_version=physical.COMPILER_VERSION,
        writer_bundle_id=writer_bundle_id,
        runtime_lock_id=runtime_lock_id,
        writer_settings_digest=physical.WRITER_SETTINGS_DIGEST,
    )


# Define commit as one focused operation with an explicit boundary.
def _commit(
    writer: ArtifactWriter,
    root: Path,
    manifest: MlArtifactManifest,
) -> CommittedArtifact:
    # Execute the commit workflow in explicit, reviewable steps.
    for descriptor in manifest.layout.arrays:
        # Process manifest.layout.arrays inside the bounded commit loop.
        with (
            (root / descriptor.path).open("rb") as source,
            writer.open_binary(descriptor.path) as destination,
        ):
            shutil.copyfileobj(source, destination, length=1024 * 1024)
    # Return the completed commit result without a hidden fallback.
    return writer.commit(
        canonical_json_bytes(manifest.document()),
        identity_manifest_bytes=canonical_json_bytes(manifest.identity_document()),
    )


def _read_committed_manifest(
    # Keep the artifacts input explicit in the read committed manifest contract.
    artifacts: LocalArtifactRepository,
    artifact_id: ArtifactId,
) -> MlArtifactManifest:
    # Execute the read committed manifest workflow in explicit, reviewable steps.
    handle = artifacts.open_committed(artifact_id)
    try:
        # Perform the protected read committed manifest operation before explicit failure
        # handling.
        with handle.open_binary("manifest.json") as stream:
            payload = stream.read()
    finally:
        handle.close()
    try:
        # Perform the protected read committed manifest operation before explicit failure
        # handling.
        document = json.loads(payload)
        if canonical_json_bytes(document) != payload:
            raise ValueError("manifest is not canonical")
        return MlArtifactManifest.from_document(document)
    except (MlArtifactContractError, TypeError, ValueError) as error:
        # Fail the read committed manifest path with NumpyMlArtifactCompileError for
        # committed ml manifest is invalid; do not continue ambiguously.
        raise NumpyMlArtifactCompileError("committed ML manifest is invalid") from error


def _require_compiler_version(value: str) -> None:
    # Execute the require compiler version workflow in explicit, reviewable steps.
    if value != physical.COMPILER_VERSION:
        raise NumpyMlArtifactCompileError(f"compiler version must be {physical.COMPILER_VERSION!r}")


def _require_kind(
    artifacts: LocalArtifactRepository,
    artifact_id: ArtifactId,
    # Keep the kind input explicit in the require kind contract.
    kind: ArtifactKind,
) -> None:
    # Execute the require kind workflow in explicit, reviewable steps.
    handle = artifacts.open_committed(artifact_id)
    try:
        # Perform the protected require kind operation before explicit failure handling.
        if handle.descriptor.kind is not kind:
            raise NumpyMlArtifactCompileError(f"input must be a committed {kind.value}")
    finally:
        handle.close()


def _require_replay(
    # Keep the replay input explicit in the require replay contract.
    replay: NumpyMmapReplaySource,
    request: BuildFeatureSetRequest | BuildPredictionSetRequest,
) -> None:
    # Execute the require replay workflow in explicit, reviewable steps.
    if replay.replay_pack_id != request.replay_pack_id:
        raise NumpyMlArtifactCompileError("opened ReplayPack identity changed")
    if replay.replay_semantics_id != request.replay_semantics_id:
        raise NumpyMlArtifactCompileError("ReplayPack semantics differ from request")
    if replay.replay_layout_schema_id != request.replay_layout_schema_id:
        # Fail the require replay path with NumpyMlArtifactCompileError for replay pack
        # layout differs from request when replay layout schema id, replay and request is
        # true; do not continue ambiguously.
        raise NumpyMlArtifactCompileError("ReplayPack layout differs from request")


def _sorted_ids(values: tuple[ArtifactId, ...]) -> tuple[ArtifactId, ...]:
    # Execute the sorted ids workflow in explicit, reviewable steps.
    result = tuple(sorted((ArtifactId(item.hex) for item in values), key=lambda item: item.hex))
    if len(result) != len({item.hex for item in result}):
        raise NumpyMlArtifactCompileError("ML exact input artifact IDs must be unique")
    return result


def _open_arrays(
    # Keep the root input explicit in the open arrays contract.
    root: Path,
    layout: MlLayoutManifest,
) -> dict[str, npt.NDArray[np.generic]]:
    # Execute the open arrays workflow in explicit, reviewable steps.
    arrays: dict[str, npt.NDArray[np.generic]] = {}
    for descriptor in layout.arrays:
        # Process layout.arrays inside the bounded open arrays loop.
        path = root / descriptor.path
        path.parent.mkdir(parents=True, exist_ok=True)
        arrays[descriptor.path] = np.lib.format.open_memmap(
            path,
            mode="w+",
            # Keep the dtype dtype step visible while building arrays[descriptor.path].
            dtype=np.dtype(descriptor.dtype),
            shape=descriptor.shape,
            fortran_order=False,
        )
    return arrays


# Define close arrays as one focused operation with an explicit boundary.
def _close_arrays(arrays: dict[str, npt.NDArray[np.generic]]) -> None:
    # Execute the close arrays workflow in explicit, reviewable steps.
    for array in arrays.values():
        # Process arrays.values() inside the bounded close arrays loop.
        if isinstance(array, np.memmap):
            # Handle the close arrays isinstance(array, np.memmap) branch as a distinct
            # logical block.
            array.flush()
            mmap = getattr(array, "_mmap", None)
            if mmap is not None:
                # Handle the close arrays mmap is not None branch as a distinct logical
                # block.
                with suppress(BufferError):
                    mmap.close()
    arrays.clear()


def _write_features(
    root: Path,
    # Keep the layout input explicit in the write features contract.
    layout: MlLayoutManifest,
    spilled: SpilledRows,
    request: BuildFeatureSetRequest,
    replay: NumpyMmapReplaySource,
) -> tuple[ContentDigest, int | None]:
    # Execute the write features workflow in explicit, reviewable steps.
    arrays = _open_arrays(root, layout)
    validity = arrays[physical.FEATURE_VALIDITY]
    validity[:] = 0
    hasher = MlLogicalStreamHasher(MlArtifactSchema.FEATURE_SET)
    maximum: int | None = None
    # Assemble effective once so the write features workflow shares one value.
    effective = replay.arrays()[replay_physical.ENVELOPE_BOUNDARY_ORDINAL]
    try:
        # Perform the protected write features operation before explicit failure handling.
        for expected_row, document in enumerate(spilled.documents()):
            # Process enumerate(spilled.documents()) inside the bounded write features
            # loop.
            row_id = _document_u64(document, "replay_row_id")
            available = _document_u64(document, "available_boundary_ordinal")
            if row_id != expected_row:
                raise NumpyMlArtifactCompileError("FeatureSet replay row IDs must be dense")
            if available < int(effective[row_id]):
                # Handle the write features available < int(effective[row_id]) branch as a
                # distinct logical block.
                raise NumpyMlArtifactCompileError(
                    "FeatureSet availability precedes the effective ReplayPack row"
                )
            raw_values = document.get("values")
            if not isinstance(raw_values, list) or len(raw_values) != len(request.feature_specs):
                # Fail the write features path with NumpyMlArtifactCompileError for
                # feature set row width is inconsistent when isinstance, raw values and
                # feature specs is true; do not continue ambiguously.
                raise NumpyMlArtifactCompileError("FeatureSet row width is inconsistent")
            logical_values: list[int | None] = []
            for code, raw_value in enumerate(raw_values):
                # Process enumerate(raw_values) inside the bounded write features loop.
                if raw_value is None:
                    # Handle the write features raw_value is None branch as a distinct
                    # logical block.
                    if request.feature_specs[code].null_policy is NullPolicy.FORBID:
                        # Handle the write features null policy, forbid and feature specs
                        # condition as a distinct block.
                        raise NumpyMlArtifactCompileError(
                            "FeatureSet contains null under FORBID policy"
                        )
                    value = 0
                else:
                    # Handle the write features complement of raw_value is None
                    # explicitly.
                    value = _i64(raw_value, "feature value")
                    _set_bitmap(validity[code], row_id)
                arrays[physical.FEATURE_VALUES][row_id, code] = value
                logical_values.append(None if raw_value is None else value)
            arrays[physical.FEATURE_ROW_ID][row_id] = row_id
            # Assemble row id, arrays and feature available once so the write features
            # workflow shares one value.
            arrays[physical.FEATURE_AVAILABLE][row_id] = available
            maximum = available if maximum is None else max(maximum, available)
            hasher.update(
                {
                    "available_boundary_ordinal": available,
                    # Keep replay row id named so the available boundary ordinal and
                    # replay row id payload passed to update remains self-describing
                    # within write features.
                    "replay_row_id": row_id,
                    "values": logical_values,
                }
            )
    finally:
        # Invoke _close_arrays for arrays as a visible write features step.
        _close_arrays(arrays)
    if hasher.count != spilled.count:
        raise NumpyMlArtifactCompileError("FeatureSet spill count changed")
    return hasher.content_digest(), maximum


def _write_universe(
    # Keep the root input explicit in the write universe contract.
    root: Path,
    layout: MlLayoutManifest,
    spilled: SpilledRows,
) -> tuple[ContentDigest, int]:
    # Execute the write universe workflow in explicit, reviewable steps.
    arrays = _open_arrays(root, layout)
    hasher = MlLogicalStreamHasher(MlArtifactSchema.UNIVERSE)
    maximum = 0
    previous_entity: int | None = None
    previous_stop = 0
    # Keep expected failures inside the write universe error boundary.
    try:
        # Perform the protected write universe operation before explicit failure handling.
        for index, document in enumerate(spilled.documents()):
            # Process enumerate(spilled.documents()) inside the bounded write universe
            # loop.
            entity = _document_u64(document, "entity_id")
            start = _document_u64(document, "eligible_from")
            stop = _document_u64(document, "eligible_until")
            available = _document_u64(document, "input_available_boundary")
            if stop <= start or available > start:
                # Fail the write universe path with NumpyMlArtifactCompileError for
                # universe interval uses a future input when stop, start and available is
                # true; do not continue ambiguously.
                raise NumpyMlArtifactCompileError("Universe interval uses a future input")
            if previous_entity is not None and entity == previous_entity and start < previous_stop:
                raise NumpyMlArtifactCompileError("Universe intervals overlap")
            arrays[physical.UNIVERSE_ENTITY_ID][index] = entity
            arrays[physical.UNIVERSE_ELIGIBLE_FROM][index] = start
            # Assemble index, arrays and universe eligible until once so the write
            # universe workflow shares one value.
            arrays[physical.UNIVERSE_ELIGIBLE_UNTIL][index] = stop
            arrays[physical.UNIVERSE_INPUT_AVAILABLE][index] = available
            maximum = max(maximum, available)
            previous_entity = entity
            previous_stop = stop
            # Invoke update for document as a visible write universe step.
            hasher.update(document)
    finally:
        _close_arrays(arrays)
    return hasher.content_digest(), maximum


def _write_labels(
    # Keep the root input explicit in the write labels contract.
    root: Path,
    layout: MlLayoutManifest,
    spilled: SpilledRows,
    training_cutoff: int,
) -> tuple[ContentDigest, int | None]:
    # Execute the write labels workflow in explicit, reviewable steps.
    arrays = _open_arrays(root, layout)
    validity = arrays[physical.LABEL_VALIDITY]
    validity[:] = 0
    hasher = MlLogicalStreamHasher(MlArtifactSchema.LABEL_SET)
    maximum: int | None = None
    # Keep expected failures inside the write labels error boundary.
    try:
        # Perform the protected write labels operation before explicit failure handling.
        for index, document in enumerate(spilled.documents()):
            # Process enumerate(spilled.documents()) inside the bounded write labels loop.
            row_id = _document_u64(document, "replay_row_id")
            effective = _document_u64(document, "effective_boundary_ordinal")
            future = _document_u64(document, "future_boundary_used")
            if effective > training_cutoff:
                raise NumpyMlArtifactCompileError("LabelSet row is after training cutoff")
            # Guard this path with future < effective before applying effects.
            if future < effective:
                raise NumpyMlArtifactCompileError("LabelSet future boundary precedes its row")
            raw_value = document.get("value")
            value = 0 if raw_value is None else _i64(raw_value, "label value")
            if raw_value is not None:
                # Invoke _set_bitmap for validity and index as a visible write labels
                # step.
                _set_bitmap(validity, index)
            arrays[physical.LABEL_ROW_ID][index] = row_id
            arrays[physical.LABEL_EFFECTIVE][index] = effective
            arrays[physical.LABEL_FUTURE_USED][index] = future
            arrays[physical.LABEL_VALUE][index] = value
            # Assemble maximum once so the write labels workflow shares one value.
            maximum = future if maximum is None else max(maximum, future)
            hasher.update(
                {
                    "effective_boundary_ordinal": effective,
                    "future_boundary_used": future,
                    # Keep replay row id named so the effective boundary ordinal and
                    # future boundary used payload passed to update remains self-
                    # describing within write labels.
                    "replay_row_id": row_id,
                    "value": None if raw_value is None else value,
                }
            )
    finally:
        # Invoke _close_arrays for arrays as a visible write labels step.
        _close_arrays(arrays)
    return hasher.content_digest(), maximum


def _write_model(
    root: Path,
    layout: MlLayoutManifest,
    # Keep the request input explicit in the write model contract.
    request: PublishModelBundleRequest,
) -> ContentDigest:
    # Execute the write model workflow in explicit, reviewable steps.
    arrays = _open_arrays(root, layout)
    try:
        # Perform the protected write model operation before explicit failure handling.
        for index, weight in enumerate(request.payload.weights):
            arrays[physical.MODEL_WEIGHTS][index] = _i64(weight, "model weight")
        arrays[physical.MODEL_INTERCEPT][0] = _i64(request.payload.intercept, "model intercept")
    finally:
        _close_arrays(arrays)
    # Assemble hasher once so the write model workflow shares one value.
    hasher = MlLogicalStreamHasher(MlArtifactSchema.MODEL_BUNDLE)
    hasher.update(
        {
            "intercept": request.payload.intercept,
            "output_divisor": request.payload.output_divisor,
            # Pass weights explicitly to update for intercept and output divisor.
            "weights": list(request.payload.weights),
        }
    )
    return hasher.content_digest()


def _write_schedule(
    # Keep the root input explicit in the write schedule contract.
    root: Path,
    layout: MlLayoutManifest,
    schedule: ModelSchedule,
) -> ContentDigest:
    # Execute the write schedule workflow in explicit, reviewable steps.
    arrays = _open_arrays(root, layout)
    hasher = MlLogicalStreamHasher(MlArtifactSchema.MODEL_SCHEDULE)
    try:
        # Perform the protected write schedule operation before explicit failure handling.
        for index, entry in enumerate(schedule.entries):
            # Process enumerate(schedule.entries) inside the bounded write schedule loop.
            arrays[physical.SCHEDULE_ELIGIBLE_FROM][index] = _u64(
                entry.eligible_from, "eligible_from"
            )
            arrays[physical.SCHEDULE_ELIGIBLE_UNTIL][index] = _u64(
                entry.eligible_until,
                # Pass eligible until explicitly so _u64 receives a reviewable eligible
                # until and entry input in write schedule.
                "eligible_until",
                # Complete _u64 only after its eligible until and entry inputs are visible in
                # write schedule.
            )
            arrays[physical.SCHEDULE_MODEL_ID][index] = bytes.fromhex(entry.model_bundle_id.hex)
            arrays[physical.SCHEDULE_TRAINING_CUTOFF][index] = _u64(
                entry.training_cutoff, "training_cutoff"
            )
            # Assemble index, arrays and schedule model available once so the write
            # schedule workflow shares one value.
            arrays[physical.SCHEDULE_MODEL_AVAILABLE][index] = _u64(
                entry.model_available_boundary, "model_available_boundary"
            )
            arrays[physical.SCHEDULE_AVAILABILITY_BASIS][index] = bytes.fromhex(
                domain_digest("backtest.model-availability-basis.v1", entry.availability_basis).hex
                # Complete fromhex only after its v1 and hex inputs are visible in write
                # schedule.
            )
            hasher.update(entry.document())
    finally:
        _close_arrays(arrays)
    return hasher.content_digest()


# Define write predictions as one focused operation with an explicit boundary.
def _write_predictions(
    root: Path,
    layout: MlLayoutManifest,
    spilled: SpilledRows,
    replay: NumpyMmapReplaySource,
    # Keep the features input explicit in the write predictions contract.
    features: tuple[NumpyFeatureSetProvider, ...],
    schedule: NumpyModelScheduleReader,
    models: tuple[NumpyModelBundleReader, ...],
    request: BuildPredictionSetRequest,
) -> tuple[ContentDigest, int | None, list[object]]:
    # Execute the write predictions workflow in explicit, reviewable steps.
    arrays = _open_arrays(root, layout)
    validity = arrays[physical.PREDICTION_VALIDITY]
    validity[:] = 0
    hasher = MlLogicalStreamHasher(MlArtifactSchema.PREDICTION_SET)
    maximum: int | None = None
    # Assemble effective array once so the write predictions workflow shares one value.
    effective_array = replay.arrays()[replay_physical.ENVELOPE_BOUNDARY_ORDINAL]
    model_codes = {model_id: index for index, model_id in enumerate(request.model_bundle_ids)}
    models_by_id = {model.model_bundle_id: model for model in models}
    operands = _model_operands(models)
    try:
        # Perform the protected write predictions operation before explicit failure
        # handling.
        for expected_row, document in enumerate(spilled.documents()):
            # Process enumerate(spilled.documents()) inside the bounded write predictions
            # loop.
            row_id = _document_u64(document, "replay_row_id")
            effective = _document_u64(document, "effective_boundary_ordinal")
            inference = _document_u64(document, "inference_completion_boundary")
            if row_id != expected_row:
                raise NumpyMlArtifactCompileError("PredictionSet replay row IDs must be dense")
            # Evaluate the complete write predictions effective, effective array and row
            # id condition before guarded effects.
            if effective != int(effective_array[row_id]):
                # Handle the write predictions effective, effective array and row id
                # condition as a distinct block.
                raise NumpyMlArtifactCompileError(
                    "PredictionSet effective boundary differs from ReplayPack"
                )
            feature_available = max(
                feature.available_boundary_for_row(row_id)
                # Pass feature explicitly so max receives a reviewable available boundary
                # for row and row id input in write predictions.
                for feature in features
                # Complete max only after its available boundary for row and row id inputs are
                # visible in write predictions.
            )
            selected_model = schedule.model_for(effective)
            try:
                selected_reader = models_by_id[selected_model]
            except KeyError as error:
                # Translate the KeyError failure through the write predictions boundary.
                raise NumpyMlArtifactCompileError(
                    "ModelSchedule selected a model outside exact prediction inputs"
                ) from error
            model_available = (selected_reader.model_available_boundary,)
            fitted_available = selected_reader.fitted_component_available_boundaries
            # Assemble availability once so the write predictions workflow shares one
            # value.
            availability = document.get("availability")
            if not isinstance(availability, dict):
                raise NumpyMlArtifactCompileError("prediction availability operands are invalid")
            if (
                _document_u64(availability, "feature_available_boundary") != feature_available
                # Keep tuple visible while evaluating the feature available, model
                # available and fitted available guard.
                or tuple(
                    _u64(item, "model availability")
                    for item in _document_list(availability, "model_available_boundaries")
                )
                != model_available
                # Keep tuple visible while evaluating the feature available, model
                # available and fitted available guard.
                or tuple(
                    _u64(item, "fitted availability")
                    for item in _document_list(
                        availability, "fitted_component_available_boundaries"
                    )
                    # Complete tuple only after its fitted availability and fitted component
                    # available boundaries inputs are visible in write predictions.
                )
                != fitted_available
                or _document_u64(availability, "inference_completion_boundary") != inference
            ):
                # Handle the write predictions feature available, model available and
                # fitted available condition as a distinct block.
                raise NumpyMlArtifactCompileError(
                    "PredictionSet declared availability operands differ from exact inputs"
                )
            available = max(feature_available, inference, *model_available, *fitted_available)
            try:
                # Assemble model code once so the write predictions workflow shares one
                # value.
                model_code = model_codes[selected_model]
            except KeyError as error:
                # Translate the KeyError failure through the write predictions boundary.
                raise NumpyMlArtifactCompileError(
                    "ModelSchedule selected a model outside exact prediction inputs"
                ) from error
            raw_value = document.get("value")
            value = 0 if raw_value is None else _i64(raw_value, "prediction value")
            # Guard this path with raw_value is not None before applying effects.
            if raw_value is not None:
                _set_bitmap(validity, row_id)
            arrays[physical.PREDICTION_ROW_ID][row_id] = row_id
            arrays[physical.PREDICTION_EFFECTIVE][row_id] = effective
            arrays[physical.PREDICTION_FEATURE_AVAILABLE][row_id] = feature_available
            # Assemble row id, arrays and prediction inference completion once so the
            # write predictions workflow shares one value.
            arrays[physical.PREDICTION_INFERENCE_COMPLETION][row_id] = inference
            arrays[physical.PREDICTION_AVAILABLE][row_id] = available
            arrays[physical.PREDICTION_MODEL_CODE][row_id] = model_code
            arrays[physical.PREDICTION_VALUE][row_id] = value
            maximum = available if maximum is None else max(maximum, available)
            # Invoke update for available boundary ordinal and effective boundary ordinal
            # as a visible write predictions step.
            hasher.update(
                {
                    "available_boundary_ordinal": available,
                    "effective_boundary_ordinal": effective,
                    "feature_available_boundary": feature_available,
                    # Keep inference completion boundary named so the available boundary
                    # ordinal and effective boundary ordinal payload passed to update
                    # remains self-describing within write predictions.
                    "inference_completion_boundary": inference,
                    "model_bundle_id": selected_model.hex,
                    "replay_row_id": row_id,
                    "value": None if raw_value is None else value,
                }
                # Complete update only after its available boundary ordinal and effective
                # boundary ordinal inputs are visible in write predictions.
            )
    finally:
        _close_arrays(arrays)
    return hasher.content_digest(), maximum, operands


def _validate_training_inputs(
    # Keep the request input explicit in the validate training inputs contract.
    request: PublishModelBundleRequest,
    features: tuple[NumpyFeatureSetProvider, ...],
    label: NumpyLabelSetReader,
    universe: NumpyUniverseReader,
) -> None:
    # Execute the validate training inputs workflow in explicit, reviewable steps.
    if label.universe_id != universe.universe_id:
        raise NumpyMlArtifactCompileError("training label/universe identities differ")
    if label.training_cutoff != request.training_spec.training_cutoff:
        raise NumpyMlArtifactCompileError("training cutoff differs from LabelSet")
    if label.snapshot_id != universe.snapshot_id or any(
        # Pass feature explicitly so any receives a reviewable snapshot id and feature
        # input in validate training inputs.
        feature.snapshot_id != label.snapshot_id
        for feature in features
    ):
        raise NumpyMlArtifactCompileError("training artifacts belong to different snapshots")
    feature_schema = domain_digest(
        # Pass version tag explicitly so domain_digest receives a reviewable v1 and
        # feature set id input in validate training inputs.
        "backtest.model-feature-schema.v1",
        # Open the v1 and feature set id payload explicitly for domain_digest within
        # validate training inputs.
        [
            {
                "feature_set_id": feature.feature_set_id.hex,
                "feature_spec_ids": [item.feature_spec_id.hex for item in feature.feature_specs],
            }
            # Pass feature explicitly so domain_digest receives a reviewable v1 and
            # feature set id input in validate training inputs.
            for feature in features
        ],
    )
    if feature_schema != request.feature_schema_digest:
        raise NumpyMlArtifactCompileError("model feature schema digest differs from exact inputs")
    # Assemble feature count once so the validate training inputs workflow shares one
    # value.
    feature_count = sum(len(feature.feature_specs) for feature in features)
    if len(request.payload.weights) != feature_count:
        raise NumpyMlArtifactCompileError("linear model weight count differs from feature schema")
    if any(
        boundary > request.training_spec.modeled_available_boundary
        # Pass boundary explicitly so any receives a reviewable modeled available boundary
        # and fitted component available boundaries input in validate training inputs.
        for boundary in request.fitted_component_available_boundaries
    ):
        raise NumpyMlArtifactCompileError("fitted component is available after the model")


def _validate_schedule_models(
    request: PublishModelScheduleRequest,
    # Keep the models input explicit in the validate schedule models contract.
    models: dict[ModelBundleId, NumpyModelBundleReader],
) -> None:
    # Execute the validate schedule models workflow in explicit, reviewable steps.
    if any(model.canonicality is not request.canonicality for model in models.values()):
        raise NumpyMlArtifactCompileError("exact and tolerance models cannot share a schedule")
    for entry in request.schedule.entries:
        # Process request.schedule.entries inside the bounded validate schedule models
        # loop.
        model = models[entry.model_bundle_id]
        if (
            model.training_spec.training_cutoff != entry.training_cutoff
            or model.model_available_boundary != entry.model_available_boundary
        ):
            # Fail the validate schedule models path with NumpyMlArtifactCompileError for
            # schedule metadata differs from model bundle when training cutoff, model
            # available boundary and training spec is true; do not continue ambiguously.
            raise NumpyMlArtifactCompileError("schedule metadata differs from ModelBundle")


def _validate_prediction_inputs(
    request: BuildPredictionSetRequest,
    replay: NumpyMmapReplaySource,
    features: tuple[NumpyFeatureSetProvider, ...],
    # Keep the schedule input explicit in the validate prediction inputs contract.
    schedule: NumpyModelScheduleReader,
    models: tuple[NumpyModelBundleReader, ...],
) -> None:
    # Execute the validate prediction inputs workflow in explicit, reviewable steps.
    _require_replay(replay, request)
    if any(feature.replay_pack_id != request.replay_pack_id for feature in features):
        raise NumpyMlArtifactCompileError("prediction features align to another ReplayPack")
    if schedule.canonicality is not request.canonicality or any(
        model.canonicality is not request.canonicality
        # Pass model explicitly so any receives a reviewable canonicality and model input
        # in validate prediction inputs.
        for model in models
        # Complete any only after its canonicality and model inputs are visible in validate
        # prediction inputs.
    ):
        raise NumpyMlArtifactCompileError("exact and tolerance artifacts cannot be mixed")
    if set(_schedule_model_ids(schedule.schedule)) != set(request.model_bundle_ids):
        raise NumpyMlArtifactCompileError("PredictionSet model inputs differ from exact schedule")


def _schedule_model_ids(schedule: ModelSchedule) -> tuple[ModelBundleId, ...]:
    # Execute the schedule model ids workflow in explicit, reviewable steps.
    values = {entry.model_bundle_id for entry in schedule.entries}
    if schedule.fallback_model_bundle_id is not None:
        values.add(schedule.fallback_model_bundle_id)
    return tuple(sorted(values, key=lambda item: item.hex))


def _model_operands(models: tuple[NumpyModelBundleReader, ...]) -> list[object]:
    # Execute the model operands workflow in explicit, reviewable steps.
    return [
        {
            "fitted_component_available_boundaries": list(
                model.fitted_component_available_boundaries
            ),
            # Include model available boundary in the completed model operands result.
            "model_available_boundary": model.model_available_boundary,
            "model_bundle_id": model.model_bundle_id.hex,
        }
        for model in models
    ]


# Define feature document as one focused operation with an explicit boundary.
def _feature_document(row: FeatureOverlayRow) -> dict[str, object]:
    # Execute the feature document workflow in explicit, reviewable steps.
    return {
        "available_boundary_ordinal": row.available_boundary_ordinal,
        "replay_row_id": row.replay_row_id,
        "values": list(row.values),
    }


# Define universe document as one focused operation with an explicit boundary.
def _universe_document(row: UniverseMembershipRow) -> dict[str, object]:
    # Execute the universe document workflow in explicit, reviewable steps.
    return {
        "eligible_from": row.eligible_from,
        "eligible_until": row.eligible_until,
        "entity_id": row.entity_id,
        "input_available_boundary": row.input_available_boundary,
        # Return the completed universe document result without a hidden fallback.
    }


def _label_document(row: LabelOverlayRow) -> dict[str, object]:
    # Execute the label document workflow in explicit, reviewable steps.
    return {
        "effective_boundary_ordinal": row.effective_boundary_ordinal,
        "future_boundary_used": row.future_boundary_used,
        "replay_row_id": row.replay_row_id,
        "value": row.value,
        # Return the completed label document result without a hidden fallback.
    }


def _prediction_document(row: FrozenPredictionRow) -> dict[str, object]:
    # Execute the prediction document workflow in explicit, reviewable steps.
    return {
        "availability": {
            "feature_available_boundary": row.availability.feature_available_boundary,
            "fitted_component_available_boundaries": list(
                row.availability.fitted_component_available_boundaries
                # Complete list only after its fitted component available boundaries and
                # availability inputs are visible in prediction document.
            ),
            "inference_completion_boundary": row.availability.inference_completion_boundary,
            "model_available_boundaries": list(row.availability.model_available_boundaries),
        },
        "effective_boundary_ordinal": row.effective_boundary_ordinal,
        # Include inference completion boundary in the completed prediction document
        # result.
        "inference_completion_boundary": row.inference_completion_boundary,
        "replay_row_id": row.replay_row_id,
        "value": row.value,
    }


def _document_list(document: dict[str, object], field: str) -> list[object]:
    # Execute the document list workflow in explicit, reviewable steps.
    value = document.get(field)
    if not isinstance(value, list):
        raise NumpyMlArtifactCompileError(f"{field} must be a list")
    return cast(list[object], value)


def _document_int(document: dict[str, object], field: str) -> int:
    # Execute the document int workflow in explicit, reviewable steps.
    value = document.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise NumpyMlArtifactCompileError(f"{field} must be an integer")
    return value


def _document_u64(document: dict[str, object], field: str) -> int:
    # Return the completed document u64 result without a hidden fallback.
    return _u64(_document_int(document, field), field)


def _u64(value: object, field: str) -> int:
    # Execute the u64 workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= _UINT64_MAX:
        raise NumpyMlArtifactCompileError(f"{field} exceeds unsigned 64-bit bounds")
    return value


def _i64(value: object, field: str) -> int:
    # Execute the i64 workflow in explicit, reviewable steps.
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not _INT64_MIN <= value <= _INT64_MAX
    ):
        # Fail the i64 path with NumpyMlArtifactCompileError for exceeds signed 64-bit
        # bounds and field when isinstance, value and int64 min is true; do not continue
        # ambiguously.
        raise NumpyMlArtifactCompileError(f"{field} exceeds signed 64-bit bounds")
    return value


def _set_bitmap(bitmap: npt.NDArray[np.generic], index: int) -> None:
    # Execute the set bitmap workflow in explicit, reviewable steps.
    byte = index // 8
    bitmap[byte] = int(bitmap[byte]) | (1 << (index % 8))


__all__ = ["LocalNumpyMlArtifactPublisher", "NumpyMlArtifactCompileError"]
