"""Strict read-only mmap readers for causal ML artifacts.

Only FeatureSet and PredictionSet implement the engine-facing scalar port.
Training-only labels live in :mod:`backtest.adapters.ml.numpy.training` and are
therefore impossible to inject through this module's public provider surface.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import ExitStack, suppress
from pathlib import Path

# Import types at the visible module dependency boundary.
from types import TracebackType
from typing import Any, Protocol, Self, cast

import numpy as np
import numpy.typing as npt

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository

# Import numpy at the visible module dependency boundary.
from backtest.adapters.columnar.numpy import layout as replay_physical
from backtest.adapters.columnar.numpy.reader import NumpyMmapReplaySource
from backtest.adapters.ml.numpy import layout as physical
from backtest.adapters.ml.numpy.toolchain import unit_ml_build_tools
from backtest.application.build_tool_roles import (
    # Include ml compiler role so the build tool roles dependency remains explicit.
    ML_COMPILER_ROLE,
    ML_FEATURE_BUILDER_ROLE,
    ML_FROZEN_INFERENCE_ROLE,
    ML_TRAINER_ROLE,
    ML_UNIVERSE_BUILDER_ROLE,
    # Include ml writer role so the build tool roles dependency remains explicit.
    ML_WRITER_ROLE,
)
from backtest.application.code_bundles import PinnedCodeBundleSet
from backtest.application.ml_artifacts import (
    MlArtifactContractError,
    # Include ml artifact manifest so the ml artifacts dependency remains explicit.
    MlArtifactManifest,
    MlArtifactSchema,
    MlLayoutManifest,
    MlLogicalStreamHasher,
    UniverseMembershipRow,
    # Include feature spec from document so the ml artifacts dependency remains explicit.
    feature_spec_from_document,
    model_schedule_from_document,
    training_spec_from_document,
)
from backtest.application.ml_contracts import (
    # Include feature spec so the ml contracts dependency remains explicit.
    FeatureSpec,
    InferenceMode,
    ModelCanonicality,
    ModelSchedule,
    ModelUnavailableError,
    # Include null policy so the ml contracts dependency remains explicit.
    NullPolicy,
    TrainingJobSpec,
)
from backtest.application.models import ArtifactKind
from backtest.domain.hashing import canonical_json_bytes, domain_digest

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import (
    ArtifactId,
    BundleId,
    ContentDigest,
    FeatureSetId,
    # Include model bundle id so the identifiers dependency remains explicit.
    ModelBundleId,
    ModelScheduleId,
    PredictionSetId,
    ReplayPackId,
    SnapshotId,
    # Include universe id so the identifiers dependency remains explicit.
    UniverseId,
)


# Keep the local handle contract and validation rules together.
class _LocalHandle(Protocol):
    @property
    def descriptor(self) -> Any: ...

    def local_path(self, relative_name: str) -> Path: ...

    def open_binary(self, relative_name: str) -> Any: ...

    # Define local handle close as one focused operation with an explicit boundary.
    def close(self) -> None: ...


class NumpyMlArtifactFormatError(RuntimeError):
    """A committed ML artifact violates its physical or causal contract."""


class _MappedMlArtifact:
    def __init__(
        self,
        artifacts: LocalArtifactRepository,
        artifact_id: ArtifactId,
        # Close the init signature after its explicit inputs.
        *,
        expected_kind: ArtifactKind,
        expected_schema: MlArtifactSchema,
        build_tools: PinnedCodeBundleSet | None = None,
    ) -> None:
        # Execute the mapped ml artifact init workflow in explicit, reviewable steps.
        self.artifacts = artifacts
        self.build_tools = build_tools or unit_ml_build_tools()
        self._closed = False
        self._handle = cast(_LocalHandle, artifacts.open_committed(artifact_id))
        self._arrays: dict[str, npt.NDArray[np.generic]] = {}
        # Keep expected failures inside the mapped ml artifact init error boundary.
        try:
            # Perform the protected mapped ml artifact init operation before explicit
            # failure handling.
            descriptor = self._handle.descriptor
            if descriptor.kind is not expected_kind:
                raise NumpyMlArtifactFormatError("requested artifact has another ML kind")
            if descriptor.artifact_id.hex != artifact_id.hex:
                raise NumpyMlArtifactFormatError("ML artifact descriptor identity mismatch")
            # Acquire open binary, json and handle at an explicit mapped ml artifact init
            # context boundary so cleanup remains scoped.
            with self._handle.open_binary("manifest.json") as stream:
                manifest_bytes = stream.read()
            document = _json_object(manifest_bytes, "ML manifest")
            if canonical_json_bytes(document) != manifest_bytes:
                raise NumpyMlArtifactFormatError("ML manifest is not canonical JSON")
            # Keep expected failures inside the mapped ml artifact init error boundary.
            try:
                self.manifest = MlArtifactManifest.from_document(document)
            except (MlArtifactContractError, TypeError, ValueError) as error:
                raise NumpyMlArtifactFormatError("ML manifest is invalid") from error
            if self.manifest.artifact_schema is not expected_schema:
                # Fail the mapped ml artifact init path with NumpyMlArtifactFormatError
                # for ml manifest schema differs from artifact kind when artifact schema,
                # expected schema and manifest is true; do not continue ambiguously.
                raise NumpyMlArtifactFormatError("ML manifest schema differs from artifact kind")
            if descriptor.build_key != self.manifest.build.build_key:
                raise NumpyMlArtifactFormatError("ML descriptor/build key mismatch")
            if descriptor.input_artifact_ids != self.manifest.build.input_artifact_ids:
                raise NumpyMlArtifactFormatError("ML exact input lineage is inconsistent")
            # Invoke _validate_known_build for manifest and require current as a visible
            # mapped ml artifact init step.
            _validate_known_build(
                self.manifest,
                compiler_bundle_id=self.build_tools.require_current(ML_COMPILER_ROLE),
                writer_bundle_id=self.build_tools.require_current(ML_WRITER_ROLE),
            )
            # Invoke _map_arrays as a visible step within the mapped ml artifact init
            # workflow.
            self._map_arrays()
        except BaseException:
            # Translate the BaseException failure through the mapped ml artifact init
            # boundary.
            self.close()
            raise

    @property
    def artifact_id(self) -> ArtifactId:
        return ArtifactId(self._handle.descriptor.artifact_id.hex)

    # Apply property semantics to the following mapped ml artifact arrays contract.
    @property
    def arrays(self) -> Mapping[str, npt.NDArray[np.generic]]:
        # Execute the mapped ml artifact arrays workflow in explicit, reviewable steps.
        self._require_open()
        return self._arrays.copy()

    def require_layout(self, expected: MlLayoutManifest) -> None:
        # Execute the mapped ml artifact require layout workflow in explicit, reviewable
        # steps.
        if self.manifest.layout.document() != expected.document():
            raise NumpyMlArtifactFormatError("ML layout is not the supported mmap v1 schema")

    def array(self, path: str) -> npt.NDArray[np.generic]:
        # Execute the mapped ml artifact array workflow in explicit, reviewable steps.
        self._require_open()
        return self._arrays[path]

    def close(self) -> None:
        # Execute the mapped ml artifact close workflow in explicit, reviewable steps.
        if self._closed:
            return
        self._closed = True
        for array in self._arrays.values():
            # Process self._arrays.values() inside the bounded mapped ml artifact close
            # loop.
            mmap = getattr(array, "_mmap", None)
            if mmap is not None:
                # Handle the mapped ml artifact close mmap is not None branch as a
                # distinct logical block.
                with suppress(BufferError):
                    mmap.close()
        self._arrays.clear()
        self._handle.close()

    def _map_arrays(self) -> None:
        # Execute the mapped ml artifact map arrays workflow in explicit, reviewable
        # steps.
        for descriptor in self.manifest.layout.arrays:
            # Process self.manifest.layout.arrays inside the bounded mapped ml artifact
            # map arrays loop.
            try:
                # Perform the protected mapped ml artifact map arrays operation before
                # explicit failure handling.
                array = np.load(
                    self._handle.local_path(descriptor.path),
                    mmap_mode="r",
                    allow_pickle=False,
                    max_header_size=16 * 1024,
                    # Complete load only after its r and local path inputs are visible in
                    # mapped ml artifact map arrays.
                )
            except (OSError, ValueError) as error:
                # Translate the (OSError, ValueError) failure through the mapped ml
                # artifact map arrays boundary.
                raise NumpyMlArtifactFormatError(
                    f"ML array {descriptor.role} cannot be mapped"
                ) from error
            if not isinstance(array, np.memmap):
                raise NumpyMlArtifactFormatError("ML .npy member is not memory mapped")
            # Guard this path with array.dtype.str != descriptor.dtype before applying
            # effects.
            if array.dtype.str != descriptor.dtype:
                # Handle the mapped ml artifact map arrays array.dtype.str !=
                # descriptor.dtype branch as a distinct logical block.
                raise NumpyMlArtifactFormatError(
                    f"ML array {descriptor.role} dtype/endian mismatch"
                )
            if array.shape != descriptor.shape:
                raise NumpyMlArtifactFormatError(f"ML array {descriptor.role} shape mismatch")
            # Evaluate the complete mapped ml artifact map arrays writeable, c contiguous
            # and flags condition before guarded effects.
            if not array.flags.c_contiguous or array.flags.writeable:
                # Handle the mapped ml artifact map arrays writeable, c contiguous and
                # flags condition as a distinct block.
                raise NumpyMlArtifactFormatError(
                    f"ML array {descriptor.role} is not read-only C-order"
                )
            self._arrays[descriptor.path] = array

    def _require_open(self) -> None:
        # Execute the mapped ml artifact require open workflow in explicit, reviewable
        # steps.
        if self._closed:
            raise NumpyMlArtifactFormatError("ML artifact reader is closed")


class NumpyFeatureSetProvider:
    """Dense ReplayPack-row-aligned point-in-time feature provider."""

    def __init__(
        self,
        artifacts: LocalArtifactRepository,
        feature_set_id: FeatureSetId,
        *,
        # Keep the build tools input explicit in the init contract.
        build_tools: PinnedCodeBundleSet | None = None,
    ) -> None:
        # Execute the numpy feature set provider init workflow in explicit, reviewable
        # steps.
        self._mapped = _MappedMlArtifact(
            artifacts,
            feature_set_id,
            expected_kind=ArtifactKind.FEATURE_SET,
            expected_schema=MlArtifactSchema.FEATURE_SET,
            # Pass build tools explicitly so _MappedMlArtifact receives a reviewable
            # feature set and artifacts input in numpy feature set provider init.
            build_tools=build_tools,
        )
        try:
            # Perform the protected numpy feature set provider init operation before
            # explicit failure handling.
            semantic = _semantic(self._mapped.manifest)
            _keys(
                semantic,
                {
                    "alignment_policy",
                    # Pass feature specs explicitly so _keys receives a reviewable
                    # alignment policy and feature specs input in numpy feature set
                    # provider init.
                    "feature_specs",
                    "input_feature_set_ids",
                    "maximum_available_boundary",
                    "replay_layout_schema_id",
                    "replay_pack_id",
                    # Pass replay semantics id explicitly so _keys receives a reviewable
                    # alignment policy and feature specs input in numpy feature set
                    # provider init.
                    "replay_semantics_id",
                },
                "FeatureSet semantic content",
            )
            if semantic["alignment_policy"] != "dense-replay-row-id-v1":
                # Fail the numpy feature set provider init path with
                # NumpyMlArtifactFormatError for feature set alignment policy is
                # unsupported when dense-replay-row-id-v1, semantic and alignment policy
                # is true; do not continue ambiguously.
                raise NumpyMlArtifactFormatError("FeatureSet alignment policy is unsupported")
            self._feature_specs = tuple(
                feature_spec_from_document(item)
                for item in _list(semantic["feature_specs"], "feature_specs")
            )
            # Guard this path with not self._feature_specs before applying effects.
            if not self._feature_specs:
                raise NumpyMlArtifactFormatError("FeatureSet has no features")
            if any(spec.dtype != "<i8" for spec in self._feature_specs):
                raise NumpyMlArtifactFormatError("FeatureSet dtype is unsupported")
            expected_feature_builder = _source_bound_expected_bundle_id(
                # Pass self explicitly so _source_bound_expected_bundle_id receives a
                # reviewable build tools and mapped input in numpy feature set provider
                # init.
                self._mapped.build_tools,
                ML_FEATURE_BUILDER_ROLE,
            )
            if expected_feature_builder is not None and any(
                spec.code_bundle_id != expected_feature_builder
                # Pass spec explicitly so any receives a reviewable code bundle id and
                # feature specs input in numpy feature set provider init.
                for spec in self._feature_specs
                # Complete any only after its code bundle id and feature specs inputs are
                # visible in numpy feature set provider init.
            ):
                raise NumpyMlArtifactFormatError("FeatureSet builder bundle is unsupported")
            feature_ids = tuple(spec.feature_spec_id.hex for spec in self._feature_specs)
            if feature_ids != tuple(sorted(feature_ids)) or len(feature_ids) != len(
                set(feature_ids)
                # Complete len only after its set and feature ids inputs are visible in numpy
                # feature set provider init.
            ):
                raise NumpyMlArtifactFormatError("FeatureSet specs are not canonical")
            self._name_to_code = {
                spec.name: index for index, spec in enumerate(self._feature_specs)
            }
            # Evaluate the complete numpy feature set provider init name to code and
            # feature specs condition before guarded effects.
            if len(self._name_to_code) != len(self._feature_specs):
                raise NumpyMlArtifactFormatError("FeatureSet names are not unique")
            self._replay_pack_id = ReplayPackId(_digest(semantic, "replay_pack_id"))
            self._replay_semantics_id = ContentDigest(_digest(semantic, "replay_semantics_id"))
            self._replay_layout_schema_id = ContentDigest(
                # Keep the semantic _digest step visible while building self. replay
                # layout schema id.
                _digest(semantic, "replay_layout_schema_id")
            )
            self._input_feature_set_ids = tuple(
                FeatureSetId(_token(item, "input FeatureSet ID"))
                for item in _list(semantic["input_feature_set_ids"], "input_feature_set_ids")
                # Complete tuple only after its input feature set id and input feature set ids
                # inputs are visible in numpy feature set provider init.
            )
            _ordered_ids(self._input_feature_set_ids, "input FeatureSet IDs")
            expected_inputs = _sorted_artifact_ids(
                (self._replay_pack_id, *self._input_feature_set_ids)
            )
            # Evaluate the complete numpy feature set provider init input artifact ids,
            # expected inputs and build condition before guarded effects.
            if self._mapped.manifest.build.input_artifact_ids != expected_inputs:
                raise NumpyMlArtifactFormatError("FeatureSet lineage differs from semantic inputs")
            expected_build = dict(semantic)
            expected_build.pop("maximum_available_boundary")
            if _semantic_build(self._mapped.manifest) != expected_build:
                # Fail the numpy feature set provider init path with
                # NumpyMlArtifactFormatError for feature set build/content semantics
                # differ when expected build, semantic build and manifest is true; do not
                # continue ambiguously.
                raise NumpyMlArtifactFormatError("FeatureSet build/content semantics differ")
            row_count = self._mapped.manifest.row_count
            self._mapped.require_layout(
                physical.feature_layout(row_count, len(self._feature_specs))
            )
            # Invoke _validate_arrays for artifacts and semantic as a visible numpy
            # feature set provider init step.
            self._validate_arrays(artifacts, semantic)
        except BaseException:
            # Translate the BaseException failure through the numpy feature set provider
            # init boundary.
            self.close()
            raise

    @property
    def feature_set_id(self) -> FeatureSetId:
        return FeatureSetId(self._mapped.artifact_id.hex)

    # Apply property semantics to the following numpy feature set provider manifest
    # contract.
    @property
    def manifest(self) -> MlArtifactManifest:
        return self._mapped.manifest

    @property
    def feature_specs(self) -> tuple[FeatureSpec, ...]:
        # Return the completed numpy feature set provider feature specs result without a
        # hidden fallback.
        return self._feature_specs

    @property
    def replay_pack_id(self) -> ReplayPackId:
        return self._replay_pack_id

    @property
    # Define numpy feature set provider arrays as one focused operation with an explicit
    # boundary.
    def arrays(self) -> Mapping[str, npt.NDArray[np.generic]]:
        return self._mapped.arrays

    @property
    def snapshot_id(self) -> SnapshotId:
        return SnapshotId(self._snapshot_id.hex)

    # Define numpy feature set provider feature code as one focused operation with an
    # explicit boundary.
    def feature_code(self, name: str) -> int:
        # Execute the numpy feature set provider feature code workflow in explicit,
        # reviewable steps.
        try:
            return self._name_to_code[name]
        except KeyError as error:
            raise KeyError(f"unknown feature {name!r}") from error

    def available_boundary_for_row(self, replay_row_id: int) -> int:
        # Execute the numpy feature set provider available boundary for row workflow in
        # explicit, reviewable steps.
        self._validate_row(replay_row_id)
        return int(self._mapped.array(physical.FEATURE_AVAILABLE)[replay_row_id])

    def value_at(
        self,
        name: str,
        # Keep the entity id input explicit in the value at contract.
        entity_id: int,
        boundary_ordinal: int,
    ) -> int | None:
        # Execute the numpy feature set provider value at workflow in explicit, reviewable
        # steps.
        code = self._name_to_code.get(name)
        if code is None:
            return None
        return self.value_at_code(code, entity_id, boundary_ordinal)

    def value_at_code(
        # Keep the remaining value at code inputs visible at the numpy feature set
        # provider value at code boundary.
        self,
        feature_code: int,
        replay_row_id: int,
        boundary_ordinal: int,
    ) -> int | None:
        # Execute the numpy feature set provider value at code workflow in explicit,
        # reviewable steps.
        if boundary_ordinal < 0:
            raise ValueError("decision boundary must be non-negative")
        if not 0 <= feature_code < len(self._feature_specs):
            raise ValueError("feature code is out of bounds")
        self._validate_row(replay_row_id)
        # Evaluate the complete numpy feature set provider value at code boundary ordinal,
        # available boundary for row and replay row id condition before guarded effects.
        if boundary_ordinal < self.available_boundary_for_row(replay_row_id):
            return None
        validity = self._mapped.array(physical.FEATURE_VALIDITY)
        if not _bitmap_valid(validity[feature_code], replay_row_id):
            return None
        # Return the completed numpy feature set provider value at code result without a
        # hidden fallback.
        return int(self._mapped.array(physical.FEATURE_VALUES)[replay_row_id, feature_code])

    def materialized_value_for_offline_pipeline(
        self,
        feature_code: int,
        replay_row_id: int,
        # Keep the int input explicit in the materialized value for offline pipeline contract.
    ) -> int | None:
        """Return stored bytes for a trusted builder, without claiming causal visibility."""

        if not 0 <= feature_code < len(self._feature_specs):
            raise ValueError("feature code is out of bounds")
        self._validate_row(replay_row_id)
        validity = self._mapped.array(physical.FEATURE_VALIDITY)
        if not _bitmap_valid(validity[feature_code], replay_row_id):
            # Return explicit absence from the numpy feature set provider materialized
            # value for offline pipeline path.
            return None
        return int(self._mapped.array(physical.FEATURE_VALUES)[replay_row_id, feature_code])

    def close(self) -> None:
        self._mapped.close()

    def __enter__(self) -> Self:
        # Return the completed numpy feature set provider enter result without a hidden
        # fallback.
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        # Keep the traceback input explicit in the exit contract.
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _validate_row(self, replay_row_id: int) -> None:
        # Execute the numpy feature set provider validate row workflow in explicit,
        # reviewable steps.
        if isinstance(replay_row_id, bool) or not isinstance(replay_row_id, int):
            raise TypeError("replay row ID must be an integer")
        if not 0 <= replay_row_id < self._mapped.manifest.row_count:
            raise ValueError("replay row ID is out of bounds")

    def _validate_arrays(
        # Keep the remaining validate arrays inputs visible at the numpy feature set
        # provider validate arrays boundary.
        self,
        artifacts: LocalArtifactRepository,
        semantic: dict[str, object],
    ) -> None:
        # Execute the numpy feature set provider validate arrays workflow in explicit,
        # reviewable steps.
        count = self._mapped.manifest.row_count
        rows = self._mapped.array(physical.FEATURE_ROW_ID)
        available = self._mapped.array(physical.FEATURE_AVAILABLE)
        values = self._mapped.array(physical.FEATURE_VALUES)
        validity = self._mapped.array(physical.FEATURE_VALIDITY)
        # Evaluate the complete numpy feature set provider validate arrays array equal,
        # rows and np condition before guarded effects.
        if not np.array_equal(rows, np.arange(count, dtype=np.dtype("<u8"))):
            raise NumpyMlArtifactFormatError("FeatureSet replay row IDs are not dense")
        for code in range(len(self._feature_specs)):
            # Process range(len(self._feature_specs)) inside the bounded numpy feature set
            # provider validate arrays loop.
            _validate_bitmap_padding(validity[code], count, "feature")
            if self._feature_specs[code].null_policy is NullPolicy.FORBID and any(
                not _bitmap_valid(validity[code], row) for row in range(count)
            ):
                raise NumpyMlArtifactFormatError("non-null FeatureSpec contains missing values")
        # Acquire numpy mmap replay source, artifacts and replay pack id at an explicit
        # numpy feature set provider validate arrays context boundary so cleanup remains
        # scoped.
        with NumpyMmapReplaySource(
            artifacts,
            self._replay_pack_id,
            build_tools=self._mapped.build_tools,
        ) as replay:
            # Keep numpy mmap replay source, artifacts and replay pack id active only for
            # the bounded numpy feature set provider validate arrays operation.
            self._snapshot_id = SnapshotId(replay.snapshot_id.hex)
            if replay.replay_semantics_id != self._replay_semantics_id:
                raise NumpyMlArtifactFormatError("FeatureSet ReplayPack semantics changed")
            if replay.replay_layout_schema_id != self._replay_layout_schema_id:
                raise NumpyMlArtifactFormatError("FeatureSet ReplayPack layout changed")
            # Guard this path with replay.manifest.event_count != count before applying
            # effects.
            if replay.manifest.event_count != count:
                raise NumpyMlArtifactFormatError("FeatureSet row count differs from ReplayPack")
            effective = replay.arrays()[replay_physical.ENVELOPE_BOUNDARY_ORDINAL]
            if any(int(available[row]) < int(effective[row]) for row in range(count)):
                raise NumpyMlArtifactFormatError("FeatureSet contains future-poisoned availability")
        # Assemble maximum once so the numpy feature set provider validate arrays workflow
        # shares one value.
        maximum = _optional_integer(semantic["maximum_available_boundary"], "maximum availability")
        actual_maximum = None if count == 0 else int(available.max())
        if maximum != actual_maximum:
            raise NumpyMlArtifactFormatError("FeatureSet maximum availability is inconsistent")
        hasher = MlLogicalStreamHasher(MlArtifactSchema.FEATURE_SET)
        # Traverse range(count) explicitly so each numpy feature set provider validate
        # arrays iteration remains traceable.
        for row in range(count):
            # Process range(count) inside the bounded numpy feature set provider validate
            # arrays loop.
            logical_values: list[int | None] = []
            for code in range(len(self._feature_specs)):
                # Process range(len(self._feature_specs)) inside the bounded numpy feature
                # set provider validate arrays loop.
                logical_values.append(
                    int(values[row, code]) if _bitmap_valid(validity[code], row) else None
                )
            hasher.update(
                {
                    # Pass available boundary ordinal explicitly to update for available
                    # boundary ordinal and replay row id.
                    "available_boundary_ordinal": int(available[row]),
                    "replay_row_id": row,
                    "values": logical_values,
                }
            )
        # Invoke _require_logical_hash for manifest and mapped as a visible numpy feature
        # set provider validate arrays step.
        _require_logical_hash(self._mapped.manifest, hasher)


class NumpyUniverseReader:
    """Read-only point-in-time membership intervals over numeric entity IDs."""

    def __init__(
        self,
        artifacts: LocalArtifactRepository,
        universe_id: ArtifactId,
        *,
        # Keep the build tools input explicit in the init contract.
        build_tools: PinnedCodeBundleSet | None = None,
    ) -> None:
        # Execute the numpy universe reader init workflow in explicit, reviewable steps.
        self._mapped = _MappedMlArtifact(
            artifacts,
            universe_id,
            expected_kind=ArtifactKind.UNIVERSE,
            expected_schema=MlArtifactSchema.UNIVERSE,
            # Pass build tools explicitly so _MappedMlArtifact receives a reviewable
            # universe and artifacts input in numpy universe reader init.
            build_tools=build_tools,
        )
        try:
            # Perform the protected numpy universe reader init operation before explicit
            # failure handling.
            semantic = _semantic(self._mapped.manifest)
            _keys(
                semantic,
                {
                    "builder_bundle_id",
                    # Pass builder config digest explicitly so _keys receives a reviewable
                    # builder bundle id and builder config digest input in numpy universe
                    # reader init.
                    "builder_config_digest",
                    "input_feature_set_ids",
                    "maximum_input_available_boundary",
                    "snapshot_id",
                    "universe_spec_id",
                    # Close the builder bundle id and builder config digest payload only after
                    # all numpy universe reader init fields are present.
                },
                "Universe semantic content",
            )
            feature_ids = tuple(
                FeatureSetId(_token(item, "Universe FeatureSet ID"))
                # Keep the list and input feature set ids _list step visible while
                # building feature ids.
                for item in _list(semantic["input_feature_set_ids"], "input_feature_set_ids")
            )
            _ordered_ids(feature_ids, "Universe FeatureSet IDs")
            expected_universe_builder = _source_bound_expected_bundle_id(
                self._mapped.build_tools,
                # Pass ml universe builder role explicitly so
                # _source_bound_expected_bundle_id receives a reviewable build tools and
                # mapped input in numpy universe reader init.
                ML_UNIVERSE_BUILDER_ROLE,
            )
            if (
                expected_universe_builder is not None
                and semantic["builder_bundle_id"] != expected_universe_builder.hex
                # Evaluate the complete numpy universe reader init expected universe builder,
                # hex and semantic condition before guarded effects.
            ):
                raise NumpyMlArtifactFormatError("Universe builder bundle is unsupported")
            self._snapshot_id = SnapshotId(_digest(semantic, "snapshot_id"))
            expected = _sorted_artifact_ids((self._snapshot_id, *feature_ids))
            if self._mapped.manifest.build.input_artifact_ids != expected:
                # Fail the numpy universe reader init path with NumpyMlArtifactFormatError
                # for universe exact lineage is inconsistent when input artifact ids,
                # expected and build is true; do not continue ambiguously.
                raise NumpyMlArtifactFormatError("Universe exact lineage is inconsistent")
            expected_build = dict(semantic)
            expected_build.pop("maximum_input_available_boundary")
            if _semantic_build(self._mapped.manifest) != expected_build:
                raise NumpyMlArtifactFormatError("Universe build/content semantics differ")
            # Assemble count once so the numpy universe reader init workflow shares one
            # value.
            count = self._mapped.manifest.row_count
            self._mapped.require_layout(physical.universe_layout(count))
            self._validate_arrays(semantic)
        except BaseException:
            # Translate the BaseException failure through the numpy universe reader init
            # boundary.
            self.close()
            raise

    @property
    def manifest(self) -> MlArtifactManifest:
        return self._mapped.manifest

    # Apply property semantics to the following numpy universe reader universe id
    # contract.
    @property
    def universe_id(self) -> UniverseId:
        return UniverseId(self._mapped.artifact_id.hex)

    @property
    def snapshot_id(self) -> SnapshotId:
        # Return the completed numpy universe reader snapshot id result without a hidden
        # fallback.
        return self._snapshot_id

    def contains(self, entity_id: int, boundary_ordinal: int) -> bool:
        # Execute the numpy universe reader contains workflow in explicit, reviewable
        # steps.
        if entity_id < 0 or boundary_ordinal < 0:
            raise ValueError("universe coordinates must be non-negative")
        entities = self._mapped.array(physical.UNIVERSE_ENTITY_ID)
        left = int(np.searchsorted(entities, entity_id, side="left"))
        right = int(np.searchsorted(entities, entity_id, side="right"))
        # Guard this path with left == right before applying effects.
        if left == right:
            return False
        starts = self._mapped.array(physical.UNIVERSE_ELIGIBLE_FROM)
        position = (
            left + int(np.searchsorted(starts[left:right], boundary_ordinal, side="right")) - 1
            # Complete the position group only after its semantic components are visible.
        )
        if position < left:
            return False
        return boundary_ordinal < int(
            self._mapped.array(physical.UNIVERSE_ELIGIBLE_UNTIL)[position]
            # Include boundary ordinal in the completed numpy universe reader contains result.
        ) and boundary_ordinal >= int(
            self._mapped.array(physical.UNIVERSE_INPUT_AVAILABLE)[position]
        )

    def memberships_for_offline_builder(self) -> Iterator[UniverseMembershipRow]:
        """Stream verified intervals to a training-only, allowlisted label builder."""

        entities = self._mapped.array(physical.UNIVERSE_ENTITY_ID)
        starts = self._mapped.array(physical.UNIVERSE_ELIGIBLE_FROM)
        stops = self._mapped.array(physical.UNIVERSE_ELIGIBLE_UNTIL)
        available = self._mapped.array(physical.UNIVERSE_INPUT_AVAILABLE)
        for index in range(self._mapped.manifest.row_count):
            # Process range(self._mapped.manifest.row_count) inside the bounded numpy
            # universe reader memberships for offline builder loop.
            yield UniverseMembershipRow(
                entity_id=int(entities[index]),
                eligible_from=int(starts[index]),
                eligible_until=int(stops[index]),
                input_available_boundary=int(available[index]),
                # Complete UniverseMembershipRow only after its int and entities inputs are
                # visible in numpy universe reader memberships for offline builder.
            )

    def close(self) -> None:
        self._mapped.close()

    def __enter__(self) -> Self:
        return self

    # Define numpy universe reader exit as one focused operation with an explicit
    # boundary.
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
        # Close the exit signature after its explicit inputs.
    ) -> None:
        self.close()

    def _validate_arrays(self, semantic: dict[str, object]) -> None:
        # Execute the numpy universe reader validate arrays workflow in explicit,
        # reviewable steps.
        count = self._mapped.manifest.row_count
        entities = self._mapped.array(physical.UNIVERSE_ENTITY_ID)
        starts = self._mapped.array(physical.UNIVERSE_ELIGIBLE_FROM)
        stops = self._mapped.array(physical.UNIVERSE_ELIGIBLE_UNTIL)
        available = self._mapped.array(physical.UNIVERSE_INPUT_AVAILABLE)
        # Assemble previous entity once so the numpy universe reader validate arrays
        # workflow shares one value.
        previous_entity: int | None = None
        previous_stop = 0
        hasher = MlLogicalStreamHasher(MlArtifactSchema.UNIVERSE)
        for index in range(count):
            # Process range(count) inside the bounded numpy universe reader validate
            # arrays loop.
            entity = int(entities[index])
            start = int(starts[index])
            stop = int(stops[index])
            input_available = int(available[index])
            if stop <= start or input_available > start:
                # Fail the numpy universe reader validate arrays path with
                # NumpyMlArtifactFormatError for universe interval is not point-in-time
                # valid when stop, start and input available is true; do not continue
                # ambiguously.
                raise NumpyMlArtifactFormatError("Universe interval is not point-in-time valid")
            if previous_entity is not None and (
                entity < previous_entity or (entity == previous_entity and start < previous_stop)
            ):
                raise NumpyMlArtifactFormatError("Universe intervals are unordered or overlap")
            # Assemble previous entity once so the numpy universe reader validate arrays
            # workflow shares one value.
            previous_entity = entity
            previous_stop = stop
            hasher.update(
                {
                    "eligible_from": start,
                    # Keep eligible until named so the eligible from and eligible until
                    # payload passed to update remains self-describing within numpy
                    # universe reader validate arrays.
                    "eligible_until": stop,
                    "entity_id": entity,
                    "input_available_boundary": input_available,
                }
            )
        # Assemble maximum once so the numpy universe reader validate arrays workflow
        # shares one value.
        maximum = _integer(semantic["maximum_input_available_boundary"], "maximum availability")
        actual = 0 if count == 0 else int(available.max())
        if maximum != actual:
            raise NumpyMlArtifactFormatError("Universe maximum availability is inconsistent")
        _require_logical_hash(self._mapped.manifest, hasher)


# Keep the numpy model bundle reader contract and validation rules together.
class NumpyModelBundleReader:
    """Safe normalized integer model payload; never deserializes pickle/code."""

    def __init__(
        self,
        artifacts: LocalArtifactRepository,
        model_bundle_id: ModelBundleId,
        *,
        # Keep the build tools input explicit in the init contract.
        build_tools: PinnedCodeBundleSet | None = None,
    ) -> None:
        # Execute the numpy model bundle reader init workflow in explicit, reviewable
        # steps.
        self._mapped = _MappedMlArtifact(
            artifacts,
            model_bundle_id,
            expected_kind=ArtifactKind.MODEL_BUNDLE,
            expected_schema=MlArtifactSchema.MODEL_BUNDLE,
            # Pass build tools explicitly so _MappedMlArtifact receives a reviewable model
            # bundle and artifacts input in numpy model bundle reader init.
            build_tools=build_tools,
        )
        try:
            # Perform the protected numpy model bundle reader init operation before
            # explicit failure handling.
            semantic = _semantic(self._mapped.manifest)
            _keys(
                semantic,
                {
                    "calibration_digest",
                    # Pass canonicality explicitly so _keys receives a reviewable
                    # calibration digest and canonicality input in numpy model bundle
                    # reader init.
                    "canonicality",
                    "feature_schema_digest",
                    "fitted_component_available_boundaries",
                    "framework",
                    "metrics_digest",
                    # Pass model available boundary explicitly so _keys receives a
                    # reviewable calibration digest and canonicality input in numpy model
                    # bundle reader init.
                    "model_available_boundary",
                    "output_divisor",
                    "preprocessing_digest",
                    "training_spec",
                    "weight_count",
                    # Close the calibration digest and canonicality payload only after all
                    # numpy model bundle reader init fields are present.
                },
                "ModelBundle semantic content",
            )
            self._training_spec = training_spec_from_document(semantic["training_spec"])
            expected_trainer = _source_bound_expected_bundle_id(
                # Pass self explicitly so _source_bound_expected_bundle_id receives a
                # reviewable build tools and mapped input in numpy model bundle reader
                # init.
                self._mapped.build_tools,
                ML_TRAINER_ROLE,
            )
            if (
                expected_trainer is not None
                # Keep self visible while evaluating the expected trainer, trainer bundle
                # id and training spec guard.
                and self._training_spec.trainer_bundle_id != expected_trainer
            ):
                raise NumpyMlArtifactFormatError("ModelBundle trainer bundle is unsupported")
            self._canonicality = _canonicality(semantic["canonicality"])
            self._feature_schema_digest = ContentDigest(_digest(semantic, "feature_schema_digest"))
            # Assemble self framework once so the numpy model bundle reader init workflow
            # shares one value.
            self._framework = _token(semantic["framework"], "framework")
            self._model_available_boundary = _integer(
                semantic["model_available_boundary"], "model availability"
            )
            if self._model_available_boundary != self._training_spec.modeled_available_boundary:
                # Fail the numpy model bundle reader init path with
                # NumpyMlArtifactFormatError for model bundle modeled availability changed
                # when model available boundary, modeled available boundary and training
                # spec is true; do not continue ambiguously.
                raise NumpyMlArtifactFormatError("ModelBundle modeled availability changed")
            self._fitted_boundaries = tuple(
                _integer(item, "fitted availability")
                for item in _list(
                    semantic["fitted_component_available_boundaries"],
                    # Pass fitted component available boundaries explicitly so _list
                    # receives a reviewable fitted component available boundaries and
                    # semantic input in numpy model bundle reader init.
                    "fitted_component_available_boundaries",
                )
            )
            if any(item > self._model_available_boundary for item in self._fitted_boundaries):
                raise NumpyMlArtifactFormatError("ModelBundle has future fitted components")
            # Assemble self output divisor once so the numpy model bundle reader init
            # workflow shares one value.
            self._output_divisor = _integer(semantic["output_divisor"], "output divisor", minimum=1)
            weight_count = _integer(semantic["weight_count"], "weight_count", minimum=1)
            if self._mapped.manifest.row_count != 1:
                raise NumpyMlArtifactFormatError("ModelBundle logical row count is invalid")
            self._mapped.require_layout(physical.model_layout(weight_count))
            # Assemble expected inputs once so the numpy model bundle reader init workflow
            # shares one value.
            expected_inputs = _sorted_artifact_ids(
                (
                    *self._training_spec.feature_set_ids,
                    self._training_spec.label_set_id,
                    self._training_spec.universe_id,
                    # Complete _sorted_artifact_ids only after its label set id and universe
                    # id inputs are visible in numpy model bundle reader init.
                )
            )
            if self._mapped.manifest.build.input_artifact_ids != expected_inputs:
                raise NumpyMlArtifactFormatError("ModelBundle training lineage is inconsistent")
            if _semantic_build(self._mapped.manifest) != semantic:
                # Fail the numpy model bundle reader init path with
                # NumpyMlArtifactFormatError for model bundle build/content semantics
                # differ when semantic, semantic build and manifest is true; do not
                # continue ambiguously.
                raise NumpyMlArtifactFormatError("ModelBundle build/content semantics differ")
            self._validate_arrays()
        except BaseException:
            # Translate the BaseException failure through the numpy model bundle reader
            # init boundary.
            self.close()
            raise

    @property
    def model_bundle_id(self) -> ModelBundleId:
        return ModelBundleId(self._mapped.artifact_id.hex)

    # Apply property semantics to the following numpy model bundle reader manifest
    # contract.
    @property
    def manifest(self) -> MlArtifactManifest:
        return self._mapped.manifest

    @property
    def training_spec(self) -> TrainingJobSpec:
        # Return the completed numpy model bundle reader training spec result without a
        # hidden fallback.
        return self._training_spec

    @property
    def canonicality(self) -> ModelCanonicality:
        return self._canonicality

    @property
    # Define numpy model bundle reader feature schema digest as one focused operation with
    # an explicit boundary.
    def feature_schema_digest(self) -> ContentDigest:
        return self._feature_schema_digest

    @property
    def framework(self) -> str:
        return self._framework

    # Apply property semantics to the following numpy model bundle reader model available
    # boundary contract.
    @property
    def model_available_boundary(self) -> int:
        return self._model_available_boundary

    @property
    def fitted_component_available_boundaries(self) -> tuple[int, ...]:
        # Return the completed numpy model bundle reader fitted component available
        # boundaries result without a hidden fallback.
        return self._fitted_boundaries

    @property
    def weights(self) -> npt.NDArray[np.generic]:
        return self._mapped.array(physical.MODEL_WEIGHTS)

    @property
    # Define numpy model bundle reader intercept as one focused operation with an explicit
    # boundary.
    def intercept(self) -> int:
        return int(self._mapped.array(physical.MODEL_INTERCEPT)[0])

    @property
    def output_divisor(self) -> int:
        return self._output_divisor

    # Define numpy model bundle reader predict exact as one focused operation with an
    # explicit boundary.
    def predict_exact(self, values: tuple[int, ...]) -> int:
        """Run the normalized small model with exact integer arithmetic."""

        if len(values) != self.weights.size:
            raise ValueError("embedded feature width differs from model weights")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise TypeError("embedded model values must be integers")
        numerator = self.intercept
        # Traverse enumerate(values) explicitly so each numpy model bundle reader predict
        # exact iteration remains traceable.
        for index, value in enumerate(values):
            numerator += int(self.weights[index]) * value
        return numerator // self._output_divisor

    def close(self) -> None:
        self._mapped.close()

    # Define numpy model bundle reader enter as one focused operation with an explicit
    # boundary.
    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        # Keep the exc input explicit in the exit contract.
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _validate_arrays(self) -> None:
        # Execute the numpy model bundle reader validate arrays workflow in explicit,
        # reviewable steps.
        weights = self._mapped.array(physical.MODEL_WEIGHTS)
        intercept = self.intercept
        hasher = MlLogicalStreamHasher(MlArtifactSchema.MODEL_BUNDLE)
        hasher.update(
            {
                # Keep intercept named so the intercept and output divisor payload passed
                # to update remains self-describing within numpy model bundle reader
                # validate arrays.
                "intercept": intercept,
                "output_divisor": self._output_divisor,
                "weights": [int(item) for item in weights],
            }
        )
        # Invoke _require_logical_hash for manifest and mapped as a visible numpy model
        # bundle reader validate arrays step.
        _require_logical_hash(self._mapped.manifest, hasher)


class NumpyModelScheduleReader:
    """Exact committed walk-forward schedule with typed gap failures."""

    def __init__(
        self,
        artifacts: LocalArtifactRepository,
        model_schedule_id: ModelScheduleId,
        *,
        # Keep the build tools input explicit in the init contract.
        build_tools: PinnedCodeBundleSet | None = None,
    ) -> None:
        # Execute the numpy model schedule reader init workflow in explicit, reviewable
        # steps.
        self._mapped = _MappedMlArtifact(
            artifacts,
            model_schedule_id,
            expected_kind=ArtifactKind.MODEL_SCHEDULE,
            expected_schema=MlArtifactSchema.MODEL_SCHEDULE,
            # Pass build tools explicitly so _MappedMlArtifact receives a reviewable model
            # schedule and artifacts input in numpy model schedule reader init.
            build_tools=build_tools,
        )
        try:
            # Perform the protected numpy model schedule reader init operation before
            # explicit failure handling.
            semantic = _semantic(self._mapped.manifest)
            _keys(semantic, {"canonicality", "schedule"}, "ModelSchedule semantic content")
            self._canonicality = _canonicality(semantic["canonicality"])
            self._schedule = model_schedule_from_document(semantic["schedule"])
            self._model_available_boundaries: dict[ModelBundleId, int] = {}
            # Evaluate the complete numpy model schedule reader init row count, manifest
            # and entries condition before guarded effects.
            if self._mapped.manifest.row_count != len(self._schedule.entries):
                raise NumpyMlArtifactFormatError("ModelSchedule entry count is inconsistent")
            self._mapped.require_layout(physical.schedule_layout(len(self._schedule.entries)))
            model_ids = _schedule_model_ids(self._schedule)
            if self._mapped.manifest.build.input_artifact_ids != _sorted_artifact_ids(
                # Keep cast visible while evaluating the input artifact ids, build and
                # sorted artifact ids guard.
                cast(tuple[ArtifactId, ...], model_ids)
            ):
                raise NumpyMlArtifactFormatError("ModelSchedule exact model lineage changed")
            if _semantic_build(self._mapped.manifest) != semantic:
                raise NumpyMlArtifactFormatError("ModelSchedule build/content semantics differ")
            # Invoke _validate_arrays for artifacts as a visible numpy model schedule
            # reader init step.
            self._validate_arrays(artifacts)
        except BaseException:
            # Translate the BaseException failure through the numpy model schedule reader
            # init boundary.
            self.close()
            raise

    @property
    def model_schedule_id(self) -> ModelScheduleId:
        return ModelScheduleId(self._mapped.artifact_id.hex)

    # Apply property semantics to the following numpy model schedule reader manifest
    # contract.
    @property
    def manifest(self) -> MlArtifactManifest:
        return self._mapped.manifest

    @property
    def schedule(self) -> ModelSchedule:
        # Return the completed numpy model schedule reader schedule result without a
        # hidden fallback.
        return self._schedule

    @property
    def canonicality(self) -> ModelCanonicality:
        return self._canonicality

    @property
    # Define numpy model schedule reader model bundle ids as one focused operation with an
    # explicit boundary.
    def model_bundle_ids(self) -> tuple[ModelBundleId, ...]:
        return _schedule_model_ids(self._schedule)

    def model_for(self, decision_boundary: int) -> ModelBundleId:
        # Execute the numpy model schedule reader model for workflow in explicit,
        # reviewable steps.
        model_id = self._schedule.model_for(decision_boundary)
        try:
            model_available = self._model_available_boundaries[model_id]
        except KeyError as error:  # pragma: no cover - lineage validation covers this
            raise NumpyMlArtifactFormatError(
                "ModelSchedule selected an unverified model"
            ) from error
        if model_available > decision_boundary:
            raise ModelUnavailableError("MODEL_UNAVAILABLE")
        # Return the completed numpy model schedule reader model for result without a
        # hidden fallback.
        return model_id

    def close(self) -> None:
        self._mapped.close()

    def __enter__(self) -> Self:
        return self

    # Define numpy model schedule reader exit as one focused operation with an explicit
    # boundary.
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
        # Close the exit signature after its explicit inputs.
    ) -> None:
        self.close()

    def _validate_arrays(self, artifacts: LocalArtifactRepository) -> None:
        # Execute the numpy model schedule reader validate arrays workflow in explicit,
        # reviewable steps.
        entries = self._schedule.entries
        arrays = self._mapped.arrays
        hasher = MlLogicalStreamHasher(MlArtifactSchema.MODEL_SCHEDULE)
        with ExitStack() as stack:
            # Keep exit stack active only for the bounded numpy model schedule reader
            # validate arrays operation.
            readers = {
                model_id: stack.enter_context(
                    NumpyModelBundleReader(
                        artifacts,
                        model_id,
                        # Pass build tools explicitly so NumpyModelBundleReader receives a
                        # reviewable build tools and mapped input in numpy model schedule
                        # reader validate arrays.
                        build_tools=self._mapped.build_tools,
                    )
                )
                for model_id in _schedule_model_ids(self._schedule)
            }
            # Assemble self model available boundaries once so the numpy model schedule
            # reader validate arrays workflow shares one value.
            self._model_available_boundaries = {
                model_id: reader.model_available_boundary for model_id, reader in readers.items()
            }
            for index, entry in enumerate(entries):
                # Process enumerate(entries) inside the bounded numpy model schedule
                # reader validate arrays loop.
                if (
                    int(arrays[physical.SCHEDULE_ELIGIBLE_FROM][index]) != entry.eligible_from
                    or int(arrays[physical.SCHEDULE_ELIGIBLE_UNTIL][index]) != entry.eligible_until
                    or _array_digest(arrays[physical.SCHEDULE_MODEL_ID], index)
                    != entry.model_bundle_id.hex
                    # Keep int visible while evaluating the eligible from, eligible until
                    # and hex guard.
                    or int(arrays[physical.SCHEDULE_TRAINING_CUTOFF][index])
                    != entry.training_cutoff
                    or int(arrays[physical.SCHEDULE_MODEL_AVAILABLE][index])
                    != entry.model_available_boundary
                    or _array_digest(arrays[physical.SCHEDULE_AVAILABILITY_BASIS], index)
                    # Keep domain digest visible while evaluating the eligible from,
                    # eligible until and hex guard.
                    != domain_digest(
                        "backtest.model-availability-basis.v1", entry.availability_basis
                    ).hex
                ):
                    raise NumpyMlArtifactFormatError("ModelSchedule arrays differ from manifest")
                # Assemble model once so the numpy model schedule reader validate arrays
                # workflow shares one value.
                model = readers[entry.model_bundle_id]
                if (
                    model.training_spec.training_cutoff != entry.training_cutoff
                    or model.model_available_boundary != entry.model_available_boundary
                    or model.canonicality is not self._canonicality
                    # Evaluate the complete numpy model schedule reader validate arrays
                    # training cutoff, model available boundary and canonicality condition
                    # before guarded effects.
                ):
                    raise NumpyMlArtifactFormatError("ModelSchedule model metadata mismatch")
                hasher.update(entry.document())
            if self._schedule.fallback_model_bundle_id is not None:
                # Handle the numpy model schedule reader validate arrays fallback model
                # bundle id and schedule condition as a distinct block.
                fallback = readers[self._schedule.fallback_model_bundle_id]
                if fallback.canonicality is not self._canonicality:
                    raise NumpyMlArtifactFormatError("ModelSchedule fallback canonicality differs")
        _require_logical_hash(self._mapped.manifest, hasher)


class NumpyPredictionSetProvider:
    """Frozen scalar prediction overlay released only at its causal boundary."""

    def __init__(
        self,
        artifacts: LocalArtifactRepository,
        prediction_set_id: PredictionSetId,
        *,
        # Keep the build tools input explicit in the init contract.
        build_tools: PinnedCodeBundleSet | None = None,
    ) -> None:
        # Execute the numpy prediction set provider init workflow in explicit, reviewable
        # steps.
        self._mapped = _MappedMlArtifact(
            artifacts,
            prediction_set_id,
            expected_kind=ArtifactKind.PREDICTION_SET,
            expected_schema=MlArtifactSchema.PREDICTION_SET,
            # Pass build tools explicitly so _MappedMlArtifact receives a reviewable
            # prediction set and artifacts input in numpy prediction set provider init.
            build_tools=build_tools,
        )
        try:
            # Perform the protected numpy prediction set provider init operation before
            # explicit failure handling.
            semantic = _semantic(self._mapped.manifest)
            _keys(
                semantic,
                {
                    "canonicality",
                    # Pass causal availability policy explicitly so _keys receives a
                    # reviewable canonicality and causal availability policy input in
                    # numpy prediction set provider init.
                    "causal_availability_policy",
                    "feature_set_ids",
                    "inference_mode",
                    "inference_compiler_bundle_id",
                    "inference_policy_digest",
                    # Pass maximum available boundary explicitly so _keys receives a
                    # reviewable canonicality and causal availability policy input in
                    # numpy prediction set provider init.
                    "maximum_available_boundary",
                    "model_availability_operands",
                    "model_bundle_ids",
                    "model_schedule_id",
                    "prediction_name",
                    # Pass replay layout schema id explicitly so _keys receives a
                    # reviewable canonicality and causal availability policy input in
                    # numpy prediction set provider init.
                    "replay_layout_schema_id",
                    "replay_pack_id",
                    "replay_semantics_id",
                },
                "PredictionSet semantic content",
                # Complete _keys only after its canonicality and causal availability policy
                # inputs are visible in numpy prediction set provider init.
            )
            self._prediction_name = _token(semantic["prediction_name"], "prediction_name")
            if semantic["inference_mode"] != InferenceMode.FROZEN.value:
                raise NumpyMlArtifactFormatError("PredictionSet inference mode is not frozen")
            expected_inference_compiler = _source_bound_expected_bundle_id(
                # Pass self explicitly so _source_bound_expected_bundle_id receives a
                # reviewable build tools and mapped input in numpy prediction set provider
                # init.
                self._mapped.build_tools,
                ML_FROZEN_INFERENCE_ROLE,
            )
            if (
                expected_inference_compiler is not None
                # Keep semantic visible while evaluating the expected inference compiler,
                # hex and semantic guard.
                and semantic["inference_compiler_bundle_id"] != expected_inference_compiler.hex
            ):
                # Handle the numpy prediction set provider init expected inference
                # compiler, hex and semantic condition as a distinct block.
                raise NumpyMlArtifactFormatError(
                    "PredictionSet inference compiler bundle is unsupported"
                )
            self._canonicality = _canonicality(semantic["canonicality"])
            self._inference_policy_digest = ContentDigest(
                # Keep the semantic _digest step visible while building self. inference
                # policy digest.
                _digest(semantic, "inference_policy_digest")
            )
            self._causal_availability_policy = _token(
                semantic["causal_availability_policy"],
                "causal_availability_policy",
                # Complete _token only after its causal availability policy and semantic
                # inputs are visible in numpy prediction set provider init.
            )
            self._replay_pack_id = ReplayPackId(_digest(semantic, "replay_pack_id"))
            replay_semantics_id = ContentDigest(_digest(semantic, "replay_semantics_id"))
            replay_layout_id = ContentDigest(_digest(semantic, "replay_layout_schema_id"))
            feature_ids = tuple(
                # Keep the feature set id and token FeatureSetId step visible while
                # building feature ids.
                FeatureSetId(_token(item, "prediction FeatureSet ID"))
                for item in _list(semantic["feature_set_ids"], "feature_set_ids")
            )
            model_ids = tuple(
                ModelBundleId(_token(item, "prediction ModelBundle ID"))
                # Keep the list and model bundle ids _list step visible while building
                # model ids.
                for item in _list(semantic["model_bundle_ids"], "model_bundle_ids")
            )
            _ordered_ids(feature_ids, "prediction FeatureSet IDs", allow_empty=False)
            _ordered_ids(model_ids, "prediction ModelBundle IDs", allow_empty=False)
            schedule_id = ModelScheduleId(_digest(semantic, "model_schedule_id"))
            # Assemble self model schedule id once so the numpy prediction set provider
            # init workflow shares one value.
            self._model_schedule_id = schedule_id
            expected_inputs = _sorted_artifact_ids(
                (self._replay_pack_id, *feature_ids, schedule_id, *model_ids)
            )
            if self._mapped.manifest.build.input_artifact_ids != expected_inputs:
                # Fail the numpy prediction set provider init path with
                # NumpyMlArtifactFormatError for prediction set exact lineage is
                # inconsistent when input artifact ids, expected inputs and build is true;
                # do not continue ambiguously.
                raise NumpyMlArtifactFormatError("PredictionSet exact lineage is inconsistent")
            expected_build = dict(semantic)
            expected_build.pop("maximum_available_boundary")
            expected_build.pop("model_availability_operands")
            if _semantic_build(self._mapped.manifest) != expected_build:
                # Fail the numpy prediction set provider init path with
                # NumpyMlArtifactFormatError for prediction set build/content semantics
                # differ when expected build, semantic build and manifest is true; do not
                # continue ambiguously.
                raise NumpyMlArtifactFormatError("PredictionSet build/content semantics differ")
            count = self._mapped.manifest.row_count
            self._mapped.require_layout(physical.prediction_layout(count))
            self._validate_arrays(
                artifacts,
                # Pass semantic explicitly so _validate_arrays receives a reviewable
                # artifacts and semantic input in numpy prediction set provider init.
                semantic,
                replay_semantics_id,
                replay_layout_id,
                feature_ids,
                schedule_id,
                # Pass model ids explicitly so _validate_arrays receives a reviewable
                # artifacts and semantic input in numpy prediction set provider init.
                model_ids,
            )
        except BaseException:
            # Translate the BaseException failure through the numpy prediction set
            # provider init boundary.
            self.close()
            raise

    @property
    def prediction_set_id(self) -> PredictionSetId:
        return PredictionSetId(self._mapped.artifact_id.hex)

    # Apply property semantics to the following numpy prediction set provider manifest
    # contract.
    @property
    def manifest(self) -> MlArtifactManifest:
        return self._mapped.manifest

    @property
    def canonicality(self) -> ModelCanonicality:
        # Return the completed numpy prediction set provider canonicality result without a
        # hidden fallback.
        return self._canonicality

    @property
    def model_schedule_id(self) -> ModelScheduleId:
        return self._model_schedule_id

    @property
    # Define numpy prediction set provider prediction name as one focused operation with
    # an explicit boundary.
    def prediction_name(self) -> str:
        return self._prediction_name

    @property
    def inference_policy_digest(self) -> ContentDigest:
        return self._inference_policy_digest

    # Apply property semantics to the following numpy prediction set provider causal
    # availability policy contract.
    @property
    def causal_availability_policy(self) -> str:
        return self._causal_availability_policy

    def value_at(
        self,
        # Keep the name input explicit in the value at contract.
        name: str,
        entity_id: int,
        boundary_ordinal: int,
    ) -> int | None:
        # Execute the numpy prediction set provider value at workflow in explicit,
        # reviewable steps.
        if name != self._prediction_name:
            return None
        return self.value_at_code(0, entity_id, boundary_ordinal)

    def value_at_code(
        self,
        # Keep the prediction code input explicit in the value at code contract.
        prediction_code: int,
        replay_row_id: int,
        boundary_ordinal: int,
    ) -> int | None:
        # Execute the numpy prediction set provider value at code workflow in explicit,
        # reviewable steps.
        if prediction_code != 0:
            raise ValueError("prediction code is out of bounds")
        if boundary_ordinal < 0:
            raise ValueError("decision boundary must be non-negative")
        if not 0 <= replay_row_id < self._mapped.manifest.row_count:
            # Fail the numpy prediction set provider value at code path with ValueError
            # for replay row id is out of bounds when replay row id, row count and
            # manifest is true; do not continue ambiguously.
            raise ValueError("replay row ID is out of bounds")
        if boundary_ordinal < int(self._mapped.array(physical.PREDICTION_AVAILABLE)[replay_row_id]):
            return None
        if not _bitmap_valid(self._mapped.array(physical.PREDICTION_VALIDITY), replay_row_id):
            return None
        # Return the completed numpy prediction set provider value at code result without
        # a hidden fallback.
        return int(self._mapped.array(physical.PREDICTION_VALUE)[replay_row_id])

    def available_boundary_for_row(self, replay_row_id: int) -> int:
        # Execute the numpy prediction set provider available boundary for row workflow in
        # explicit, reviewable steps.
        if not 0 <= replay_row_id < self._mapped.manifest.row_count:
            raise ValueError("replay row ID is out of bounds")
        return int(self._mapped.array(physical.PREDICTION_AVAILABLE)[replay_row_id])

    def close(self) -> None:
        self._mapped.close()

    # Define numpy prediction set provider enter as one focused operation with an explicit
    # boundary.
    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        # Keep the exc input explicit in the exit contract.
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _validate_arrays(
        # Keep the remaining validate arrays inputs visible at the numpy prediction set
        # provider validate arrays boundary.
        self,
        artifacts: LocalArtifactRepository,
        semantic: dict[str, object],
        replay_semantics_id: ContentDigest,
        replay_layout_id: ContentDigest,
        # Keep the feature ids input explicit in the validate arrays contract.
        feature_ids: tuple[FeatureSetId, ...],
        schedule_id: ModelScheduleId,
        model_ids: tuple[ModelBundleId, ...],
    ) -> None:
        # Execute the numpy prediction set provider validate arrays workflow in explicit,
        # reviewable steps.
        count = self._mapped.manifest.row_count
        arrays = self._mapped.arrays
        if not np.array_equal(
            arrays[physical.PREDICTION_ROW_ID], np.arange(count, dtype=np.dtype("<u8"))
        ):
            # Fail the numpy prediction set provider validate arrays path with
            # NumpyMlArtifactFormatError for prediction set replay row ids are not dense
            # when array equal, np and arrays is true; do not continue ambiguously.
            raise NumpyMlArtifactFormatError("PredictionSet replay row IDs are not dense")
        _validate_bitmap_padding(arrays[physical.PREDICTION_VALIDITY], count, "prediction")
        with ExitStack() as stack:
            # Keep exit stack active only for the bounded numpy prediction set provider
            # validate arrays operation.
            replay = stack.enter_context(
                NumpyMmapReplaySource(
                    artifacts,
                    self._replay_pack_id,
                    build_tools=self._mapped.build_tools,
                    # Complete NumpyMmapReplaySource only after its replay pack id and build
                    # tools inputs are visible in numpy prediction set provider validate
                    # arrays.
                )
            )
            features = tuple(
                stack.enter_context(
                    NumpyFeatureSetProvider(
                        # Pass artifacts explicitly so NumpyFeatureSetProvider receives a
                        # reviewable build tools and mapped input in numpy prediction set
                        # provider validate arrays.
                        artifacts,
                        feature_id,
                        build_tools=self._mapped.build_tools,
                    )
                )
                # Pass feature id explicitly so tuple receives a reviewable enter context
                # and build tools input in numpy prediction set provider validate arrays.
                for feature_id in feature_ids
            )
            schedule = stack.enter_context(
                NumpyModelScheduleReader(
                    artifacts,
                    # Pass schedule id explicitly so NumpyModelScheduleReader receives a
                    # reviewable build tools and mapped input in numpy prediction set
                    # provider validate arrays.
                    schedule_id,
                    build_tools=self._mapped.build_tools,
                )
            )
            models = tuple(
                # Keep the enter context and stack enter_context step visible while
                # building models.
                stack.enter_context(
                    NumpyModelBundleReader(
                        artifacts,
                        model_id,
                        build_tools=self._mapped.build_tools,
                        # Complete NumpyModelBundleReader only after its build tools and
                        # mapped inputs are visible in numpy prediction set provider validate
                        # arrays.
                    )
                )
                for model_id in model_ids
            )
            if replay.replay_semantics_id != replay_semantics_id:
                # Fail the numpy prediction set provider validate arrays path with
                # NumpyMlArtifactFormatError for prediction set replay pack semantics
                # changed when replay semantics id and replay is true; do not continue
                # ambiguously.
                raise NumpyMlArtifactFormatError("PredictionSet ReplayPack semantics changed")
            if replay.replay_layout_schema_id != replay_layout_id:
                raise NumpyMlArtifactFormatError("PredictionSet ReplayPack layout changed")
            if replay.manifest.event_count != count:
                raise NumpyMlArtifactFormatError("PredictionSet row count differs from ReplayPack")
            # Evaluate the complete numpy prediction set provider validate arrays replay
            # pack id, feature and features condition before guarded effects.
            if any(feature.replay_pack_id != self._replay_pack_id for feature in features):
                raise NumpyMlArtifactFormatError("PredictionSet FeatureSet alignment differs")
            if schedule.canonicality is not self._canonicality or any(
                model.canonicality is not self._canonicality for model in models
            ):
                # Fail the numpy prediction set provider validate arrays path with
                # NumpyMlArtifactFormatError for exact and tolerance ml artifacts are
                # mixed when canonicality, schedule and model is true; do not continue
                # ambiguously.
                raise NumpyMlArtifactFormatError("exact and tolerance ML artifacts are mixed")
            operand_document = _model_operands(models)
            if semantic["model_availability_operands"] != operand_document:
                raise NumpyMlArtifactFormatError("PredictionSet model operands changed")
            effective_expected = replay.arrays()[replay_physical.ENVELOPE_BOUNDARY_ORDINAL]
            # Evaluate the complete numpy prediction set provider validate arrays array
            # equal, effective expected and np condition before guarded effects.
            if not np.array_equal(arrays[physical.PREDICTION_EFFECTIVE], effective_expected):
                raise NumpyMlArtifactFormatError("PredictionSet effective boundaries changed")
            hasher = MlLogicalStreamHasher(MlArtifactSchema.PREDICTION_SET)
            models_by_id = {model.model_bundle_id: model for model in models}
            for row in range(count):
                # Process range(count) inside the bounded numpy prediction set provider
                # validate arrays loop.
                feature_available = max(
                    feature.available_boundary_for_row(row) for feature in features
                )
                stored_feature = int(arrays[physical.PREDICTION_FEATURE_AVAILABLE][row])
                inference = int(arrays[physical.PREDICTION_INFERENCE_COMPLETION][row])
                # Assemble available once so the numpy prediction set provider validate
                # arrays workflow shares one value.
                available = int(arrays[physical.PREDICTION_AVAILABLE][row])
                effective = int(arrays[physical.PREDICTION_EFFECTIVE][row])
                if stored_feature != feature_available:
                    raise NumpyMlArtifactFormatError("PredictionSet feature operand changed")
                try:
                    # Assemble selected model once so the numpy prediction set provider
                    # validate arrays workflow shares one value.
                    selected_model = schedule.model_for(effective)
                except ModelUnavailableError:
                    raise
                selected_reader = models_by_id[selected_model]
                required = max(
                    # Pass feature available explicitly so max receives a reviewable model
                    # available boundary and fitted component available boundaries input
                    # in numpy prediction set provider validate arrays.
                    feature_available,
                    inference,
                    selected_reader.model_available_boundary,
                    *selected_reader.fitted_component_available_boundaries,
                )
                # Guard this path with available != required before applying effects.
                if available != required:
                    # Handle the numpy prediction set provider validate arrays available
                    # != required branch as a distinct logical block.
                    raise NumpyMlArtifactFormatError(
                        "PredictionSet availability lower bound failed"
                    )
                model_code = int(arrays[physical.PREDICTION_MODEL_CODE][row])
                if model_code >= len(model_ids) or model_ids[model_code] != selected_model:
                    # Fail the numpy prediction set provider validate arrays path with
                    # NumpyMlArtifactFormatError for prediction set selected model changed
                    # when model code, selected model and model ids is true; do not
                    # continue ambiguously.
                    raise NumpyMlArtifactFormatError("PredictionSet selected model changed")
                value = (
                    int(arrays[physical.PREDICTION_VALUE][row])
                    if _bitmap_valid(arrays[physical.PREDICTION_VALIDITY], row)
                    else None
                    # Complete the value group only after its semantic components are visible.
                )
                hasher.update(
                    {
                        "available_boundary_ordinal": available,
                        "effective_boundary_ordinal": effective,
                        # Keep feature available boundary named so the available boundary
                        # ordinal and effective boundary ordinal payload passed to update
                        # remains self-describing within numpy prediction set provider
                        # validate arrays.
                        "feature_available_boundary": feature_available,
                        "inference_completion_boundary": inference,
                        "model_bundle_id": selected_model.hex,
                        "replay_row_id": row,
                        "value": value,
                        # Close the available boundary ordinal and effective boundary ordinal
                        # payload only after all numpy prediction set provider validate arrays
                        # fields are present.
                    }
                )
        maximum = _optional_integer(semantic["maximum_available_boundary"], "maximum availability")
        actual = None if count == 0 else int(arrays[physical.PREDICTION_AVAILABLE].max())
        if maximum != actual:
            # Fail the numpy prediction set provider validate arrays path with
            # NumpyMlArtifactFormatError for prediction set maximum availability is
            # inconsistent when maximum and actual is true; do not continue ambiguously.
            raise NumpyMlArtifactFormatError("PredictionSet maximum availability is inconsistent")
        _require_logical_hash(self._mapped.manifest, hasher)


def _validate_known_build(
    manifest: MlArtifactManifest,
    *,
    # Keep the compiler bundle id input explicit in the validate known build contract.
    compiler_bundle_id: BundleId,
    writer_bundle_id: BundleId,
) -> None:
    # Execute the validate known build workflow in explicit, reviewable steps.
    build = manifest.build
    if build.compiler_bundle_id != compiler_bundle_id:
        raise NumpyMlArtifactFormatError("ML compiler bundle is unsupported")
    if build.compiler_version != physical.COMPILER_VERSION:
        raise NumpyMlArtifactFormatError("ML compiler version is unsupported")
    # Evaluate the complete validate known build writer bundle id and build condition
    # before guarded effects.
    if build.writer_bundle_id != writer_bundle_id:
        raise NumpyMlArtifactFormatError("ML writer bundle is unsupported")
    if build.writer_settings_digest != physical.WRITER_SETTINGS_DIGEST:
        raise NumpyMlArtifactFormatError("ML writer settings are unsupported")


def _semantic(manifest: MlArtifactManifest) -> dict[str, object]:
    # Return the completed semantic result without a hidden fallback.
    return _json_object(manifest.semantic_content, "ML semantic content")


def _semantic_build(manifest: MlArtifactManifest) -> dict[str, object]:
    return _json_object(manifest.build.semantic_inputs, "ML build semantic inputs")


def _json_object(payload: bytes, label: str) -> dict[str, object]:
    # Execute the json object workflow in explicit, reviewable steps.
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, ValueError) as error:
        raise NumpyMlArtifactFormatError(f"{label} is invalid JSON") from error
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        # Fail the json object path with NumpyMlArtifactFormatError for must be an object
        # and label when isinstance, value and key is true; do not continue ambiguously.
        raise NumpyMlArtifactFormatError(f"{label} must be an object")
    return cast(dict[str, object], value)


def _keys(document: dict[str, object], expected: set[str], label: str) -> None:
    # Execute the keys workflow in explicit, reviewable steps.
    if set(document) != expected:
        raise NumpyMlArtifactFormatError(f"{label} schema is invalid")


def _list(value: object, label: str) -> list[object]:
    # Execute the list workflow in explicit, reviewable steps.
    if not isinstance(value, list):
        raise NumpyMlArtifactFormatError(f"{label} must be a list")
    return cast(list[object], value)


def _token(value: object, label: str) -> str:
    # Execute the token workflow in explicit, reviewable steps.
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise NumpyMlArtifactFormatError(f"{label} must be a canonical token")
    return value


def _digest(document: dict[str, object], field: str) -> str:
    # Execute the digest workflow in explicit, reviewable steps.
    value = _token(document[field], field)
    try:
        return ContentDigest(value).hex
    except ValueError as error:
        raise NumpyMlArtifactFormatError(f"{field} is not a digest") from error


# Define integer as one focused operation with an explicit boundary.
def _integer(value: object, label: str, *, minimum: int = 0) -> int:
    # Execute the integer workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise NumpyMlArtifactFormatError(f"{label} must be an integer >= {minimum}")
    return value


def _optional_integer(value: object, label: str) -> int | None:
    return None if value is None else _integer(value, label)


# Define canonicality as one focused operation with an explicit boundary.
def _canonicality(value: object) -> ModelCanonicality:
    # Execute the canonicality workflow in explicit, reviewable steps.
    try:
        return ModelCanonicality(_token(value, "canonicality"))
    except ValueError as error:
        raise NumpyMlArtifactFormatError("model canonicality is unsupported") from error


def _ordered_ids(
    # Keep the values input explicit in the ordered ids contract.
    values: tuple[ArtifactId, ...],
    label: str,
    *,
    allow_empty: bool = True,
) -> None:
    # Execute the ordered ids workflow in explicit, reviewable steps.
    if not allow_empty and not values:
        raise NumpyMlArtifactFormatError(f"{label} must not be empty")
    if tuple(sorted(values, key=lambda item: item.hex)) != values or len(values) != len(
        {item.hex for item in values}
    ):
        # Fail the ordered ids path with NumpyMlArtifactFormatError for must be sorted and
        # unique and label when values, sorted and hex is true; do not continue
        # ambiguously.
        raise NumpyMlArtifactFormatError(f"{label} must be sorted and unique")


def _source_bound_expected_bundle_id(
    build_tools: PinnedCodeBundleSet,
    role: str,
) -> BundleId | None:
    """Return a production expectation without making unit defaults authoritative."""

    identity = build_tools.identity_for(role)
    if not identity.is_source_bound:
        return None
    identity.require_current()
    return identity.bundle_id


# Define sorted artifact ids as one focused operation with an explicit boundary.
def _sorted_artifact_ids(values: tuple[ArtifactId, ...]) -> tuple[ArtifactId, ...]:
    # Execute the sorted artifact ids workflow in explicit, reviewable steps.
    result = tuple(sorted((ArtifactId(item.hex) for item in values), key=lambda item: item.hex))
    if len(result) != len({item.hex for item in result}):
        raise NumpyMlArtifactFormatError("ML exact inputs contain duplicates")
    return result


def _schedule_model_ids(schedule: ModelSchedule) -> tuple[ModelBundleId, ...]:
    # Execute the schedule model ids workflow in explicit, reviewable steps.
    values = {item.model_bundle_id for item in schedule.entries}
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


# Define array digest as one focused operation with an explicit boundary.
def _array_digest(array: npt.NDArray[np.generic], index: int) -> str:
    # Execute the array digest workflow in explicit, reviewable steps.
    raw = bytes(array[index].tobytes())
    if len(raw) != 32:
        raise NumpyMlArtifactFormatError("fixed digest array has another item size")
    return raw.hex()


def _bitmap_valid(bitmap: npt.NDArray[np.generic], index: int) -> bool:
    # Return the completed bitmap valid result without a hidden fallback.
    return bool(int(bitmap[index // 8]) & (1 << (index % 8)))


def _validate_bitmap_padding(
    bitmap: npt.NDArray[np.generic],
    item_count: int,
    label: str,
    # Close the validate bitmap padding signature after its explicit inputs.
) -> None:
    # Execute the validate bitmap padding workflow in explicit, reviewable steps.
    expected_size = (item_count + 7) // 8
    if bitmap.shape != (expected_size,):
        raise NumpyMlArtifactFormatError(f"{label} validity bitmap shape is invalid")
    remainder = item_count % 8
    if remainder and int(bitmap[-1]) & ~((1 << remainder) - 1):
        # Fail the validate bitmap padding path with NumpyMlArtifactFormatError for
        # validity bitmap padding is non-zero and label when remainder and bitmap is true;
        # do not continue ambiguously.
        raise NumpyMlArtifactFormatError(f"{label} validity bitmap padding is non-zero")


def _require_logical_hash(
    manifest: MlArtifactManifest,
    hasher: MlLogicalStreamHasher,
) -> None:
    # Execute the require logical hash workflow in explicit, reviewable steps.
    if hasher.count != manifest.row_count:
        raise NumpyMlArtifactFormatError("ML logical row count mismatch")
    if hasher.content_digest() != manifest.logical_content_hash:
        raise NumpyMlArtifactFormatError("ML logical stream hash mismatch")


__all__ = [
    # Keep the numpy feature set provider component named inside the all contract.
    "NumpyFeatureSetProvider",
    "NumpyMlArtifactFormatError",
    "NumpyModelBundleReader",
    "NumpyModelScheduleReader",
    "NumpyPredictionSetProvider",
    # Keep the numpy universe reader component named inside the all contract.
    "NumpyUniverseReader",
]
