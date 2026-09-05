"""Typed publication contracts for immutable point-in-time ML artifacts.

The contracts contain no NumPy/framework objects, aliases, paths or executable
payloads.  Concrete builders convert these DTOs to versioned local layouts.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

# Import hashlib at the visible module dependency boundary.
from hashlib import sha256
from pathlib import PurePosixPath
from typing import ClassVar, Self, cast

from backtest.application.ml_contracts import (
    FeatureSpec,
    # Include inference mode so the ml contracts dependency remains explicit.
    InferenceMode,
    ModelCanonicality,
    ModelSchedule,
    ModelScheduleEntry,
    NullPolicy,
    # Include prediction availability so the ml contracts dependency remains explicit.
    PredictionAvailability,
    TemporalSplit,
    TrainingJobSpec,
)
from backtest.application.models import ArtifactKind, CommittedArtifact

# Import hashing at the visible module dependency boundary.
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.domain.identifiers import (
    ArtifactId,
    BundleId,
    ContentDigest,
    # Include feature set id so the identifiers dependency remains explicit.
    FeatureSetId,
    LabelSetId,
    ModelBundleId,
    ModelScheduleId,
    PredictionSetId,
    # Include replay pack id so the identifiers dependency remains explicit.
    ReplayPackId,
    RuntimeLockId,
    SnapshotId,
    UniverseId,
)


# Keep the ml artifact contract error contract and validation rules together.
class MlArtifactContractError(ValueError):
    """An ML artifact request or manifest violates its versioned contract."""


class MlLogicalStreamHasher:
    """Versioned logical-row hash independent of paths and NumPy headers."""

    def __init__(self, artifact_schema: MlArtifactSchema) -> None:
        # Execute the ml logical stream hasher init workflow in explicit, reviewable
        # steps.
        self._hasher = sha256()
        self._hasher.update(b"backtest.ml-logical-stream.v1\x00")
        self._hasher.update(artifact_schema.value.encode("ascii"))
        self._hasher.update(b"\x00")
        self._count = 0

    # Define ml logical stream hasher update as one focused operation with an explicit
    # boundary.
    def update(self, document: dict[str, object]) -> None:
        # Execute the ml logical stream hasher update workflow in explicit, reviewable
        # steps.
        payload = canonical_json_bytes(document)
        self._hasher.update(len(payload).to_bytes(8, "big"))
        self._hasher.update(payload)
        self._count += 1

    @property
    # Define ml logical stream hasher count as one focused operation with an explicit
    # boundary.
    def count(self) -> int:
        return self._count

    def content_digest(self) -> ContentDigest:
        # Execute the ml logical stream hasher content digest workflow in explicit,
        # reviewable steps.
        result = self._hasher.copy()
        result.update(self._count.to_bytes(8, "big"))
        return ContentDigest(result.hexdigest())


# Keep the ml artifact schema contract and validation rules together.
class MlArtifactSchema(StrEnum):
    FEATURE_SET = "feature-set/v1"
    UNIVERSE = "universe/v1"
    LABEL_SET = "label-set/v1"
    MODEL_BUNDLE = "model-bundle/v1"
    # Declare model schedule explicitly in the ml artifact schema contract.
    MODEL_SCHEDULE = "model-schedule/v1"
    PREDICTION_SET = "prediction-set/v1"


# Keep the frozen missing policy contract and validation rules together.
class FrozenMissingPolicy(StrEnum):
    NULL = "NULL"
    REJECT = "REJECT"


def _token(value: object, field: str) -> str:
    # Execute the token workflow in explicit, reviewable steps.
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise MlArtifactContractError(f"{field} must be non-empty, trimmed and NUL-free")
    return value


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    # Execute the integer workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise MlArtifactContractError(f"{field} must be an integer >= {minimum}")
    return value


def _object(value: object, label: str) -> dict[str, object]:
    # Execute the object workflow in explicit, reviewable steps.
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise MlArtifactContractError(f"{label} must be a JSON object")
    return cast(dict[str, object], value)


def _list(value: object, label: str) -> list[object]:
    # Execute the list workflow in explicit, reviewable steps.
    if not isinstance(value, list):
        raise MlArtifactContractError(f"{label} must be a JSON list")
    return cast(list[object], value)


def _keys(document: dict[str, object], expected: set[str], label: str) -> None:
    # Execute the keys workflow in explicit, reviewable steps.
    if set(document) != expected:
        raise MlArtifactContractError(f"{label} schema is invalid")


def _canonical_object(payload: bytes, label: str) -> dict[str, object]:
    # Execute the canonical object workflow in explicit, reviewable steps.
    try:
        # Perform the protected canonical object operation before explicit failure
        # handling.
        canonical = canonical_json_bytes(json.loads(payload))
        value = json.loads(payload)
    except (TypeError, UnicodeDecodeError, ValueError) as error:
        raise MlArtifactContractError(f"{label} must be canonical JSON") from error
    if canonical != payload:
        # Fail the canonical object path with MlArtifactContractError for must be
        # canonical json and label when canonical and payload is true; do not continue
        # ambiguously.
        raise MlArtifactContractError(f"{label} must be canonical JSON")
    return _object(value, label)


def _ordered_ids[T: ArtifactId | ContentDigest](
    values: tuple[T, ...],
    field: str,
    # Close the ordered ids signature after its explicit inputs.
    *,
    allow_empty: bool = True,
) -> None:
    # Execute the ordered ids workflow in explicit, reviewable steps.
    if not allow_empty and not values:
        raise MlArtifactContractError(f"{field} must not be empty")
    if tuple(sorted(values, key=lambda item: item.hex)) != values:
        raise MlArtifactContractError(f"{field} must be sorted")
    if len(values) != len({item.hex for item in values}):
        # Fail the ordered ids path with MlArtifactContractError for must be unique and
        # field when values, hex and item is true; do not continue ambiguously.
        raise MlArtifactContractError(f"{field} must be unique")


def _relative_npy(value: str) -> None:
    # Execute the relative npy workflow in explicit, reviewable steps.
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or "\\" in value
        # Keep any visible while evaluating the is absolute, value and path guard.
        or any(part in {"", ".", ".."} for part in path.parts)
        or not value.endswith(".npy")
    ):
        raise MlArtifactContractError("ML array path must be canonical relative .npy")


# Keep the ml array layout contract and validation rules together.
@dataclass(frozen=True, slots=True)
class MlArrayLayout:
    path: str
    dtype: str
    shape: tuple[int, ...]
    # Declare role explicitly in the ml array layout contract.
    role: str
    byte_order: str
    overflow_policy: str

    def __post_init__(self) -> None:
        # Execute the ml array layout post init workflow in explicit, reviewable steps.
        _relative_npy(self.path)
        for field in ("dtype", "role", "byte_order", "overflow_policy"):
            _token(getattr(self, field), field)
        if not self.shape or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            # Pass value explicitly so any receives a reviewable shape and isinstance
            # input in ml array layout post init.
            for value in self.shape
        ):
            raise MlArtifactContractError("ML array shape must be non-negative")

    def schema_document(self) -> dict[str, object]:
        # Execute the ml array layout schema document workflow in explicit, reviewable
        # steps.
        return {
            "byte_order": self.byte_order,
            "dtype": self.dtype,
            "overflow_policy": self.overflow_policy,
            "path": self.path,
            # Include rank in the completed ml array layout schema document result.
            "rank": len(self.shape),
            "role": self.role,
        }

    def document(self) -> dict[str, object]:
        return {**self.schema_document(), "shape": list(self.shape)}

    # Apply classmethod semantics to the following ml array layout from document contract.
    @classmethod
    def from_document(cls, value: object) -> Self:
        # Execute the ml array layout from document workflow in explicit, reviewable
        # steps.
        document = _object(value, "ML array layout")
        _keys(
            document,
            {"byte_order", "dtype", "overflow_policy", "path", "rank", "role", "shape"},
            "ML array layout",
            # Complete _keys only after its byte order and dtype inputs are visible in ml
            # array layout from document.
        )
        shape = tuple(_integer(item, "array shape") for item in _list(document["shape"], "shape"))
        rank = _integer(document["rank"], "rank", minimum=1)
        if rank != len(shape):
            raise MlArtifactContractError("ML array rank differs from shape")
        # Return the completed ml array layout from document result without a hidden
        # fallback.
        return cls(
            path=_token(document["path"], "path"),
            dtype=_token(document["dtype"], "dtype"),
            shape=shape,
            role=_token(document["role"], "role"),
            # Include byte order in the completed ml array layout from document result.
            byte_order=_token(document["byte_order"], "byte_order"),
            overflow_policy=_token(document["overflow_policy"], "overflow_policy"),
        )


# Keep the ml layout manifest contract and validation rules together.
@dataclass(frozen=True, slots=True)
class MlLayoutManifest:
    arrays: tuple[MlArrayLayout, ...]
    layout_version: int = 1
    container: str = "numpy-npy-v1"
    # Declare physical byte order explicitly in the ml layout manifest contract.
    physical_byte_order: str = "little"

    def __post_init__(self) -> None:
        # Execute the ml layout manifest post init workflow in explicit, reviewable steps.
        if self.layout_version != 1:
            raise MlArtifactContractError("only ML layout version 1 is supported")
        if not self.arrays or tuple(sorted(self.arrays, key=lambda item: item.path)) != self.arrays:
            raise MlArtifactContractError("ML arrays must be non-empty and path-sorted")
        if len({item.path for item in self.arrays}) != len(self.arrays):
            # Fail the ml layout manifest post init path with MlArtifactContractError for
            # ml array paths must be unique when arrays, path and item is true; do not
            # continue ambiguously.
            raise MlArtifactContractError("ML array paths must be unique")
        _token(self.container, "container")
        _token(self.physical_byte_order, "physical_byte_order")

    def schema_document(self) -> dict[str, object]:
        # Execute the ml layout manifest schema document workflow in explicit, reviewable
        # steps.
        return {
            "arrays": [item.schema_document() for item in self.arrays],
            "container": self.container,
            "layout_version": self.layout_version,
            "physical_byte_order": self.physical_byte_order,
            # Return the completed ml layout manifest schema document result without a hidden
            # fallback.
        }

    @property
    def layout_schema_id(self) -> ContentDigest:
        return domain_digest("backtest.ml-layout-schema.v1", self.schema_document())

    def document(self) -> dict[str, object]:
        # Execute the ml layout manifest document workflow in explicit, reviewable steps.
        return {
            "arrays": [item.document() for item in self.arrays],
            "container": self.container,
            "layout_schema_id": self.layout_schema_id.hex,
            "layout_version": self.layout_version,
            # Include physical byte order in the completed ml layout manifest document
            # result.
            "physical_byte_order": self.physical_byte_order,
        }

    @classmethod
    def from_document(cls, value: object) -> Self:
        # Execute the ml layout manifest from document workflow in explicit, reviewable
        # steps.
        document = _object(value, "ML layout")
        _keys(
            document,
            {
                "arrays",
                # Pass container explicitly so _keys receives a reviewable arrays and
                # container input in ml layout manifest from document.
                "container",
                "layout_schema_id",
                "layout_version",
                "physical_byte_order",
            },
            # Pass ml layout explicitly so _keys receives a reviewable arrays and
            # container input in ml layout manifest from document.
            "ML layout",
        )
        result = cls(
            arrays=tuple(
                MlArrayLayout.from_document(item)
                # Keep the list and arrays _list step visible while building result.
                for item in _list(document["arrays"], "arrays")
                # Complete tuple only after its arrays and from document inputs are visible in
                # ml layout manifest from document.
            ),
            layout_version=_integer(document["layout_version"], "layout_version", minimum=1),
            container=_token(document["container"], "container"),
            physical_byte_order=_token(document["physical_byte_order"], "physical_byte_order"),
        )
        # Assemble stored once so the ml layout manifest from document workflow shares one
        # value.
        stored = ContentDigest(_token(document["layout_schema_id"], "layout_schema_id"))
        if stored != result.layout_schema_id:
            raise MlArtifactContractError("ML layout schema ID mismatch")
        return result


# Keep the ml build manifest contract and validation rules together.
@dataclass(frozen=True, slots=True)
class MlBuildManifest:
    artifact_schema: MlArtifactSchema
    input_artifact_ids: tuple[ArtifactId, ...]
    semantic_inputs: bytes
    # Declare compiler bundle id explicitly in the ml build manifest contract.
    compiler_bundle_id: BundleId
    compiler_version: str
    writer_bundle_id: BundleId
    runtime_lock_id: RuntimeLockId
    writer_settings_digest: ContentDigest

    # Declare expected schema explicitly in the ml build manifest contract.
    EXPECTED_SCHEMA: ClassVar[MlArtifactSchema | None] = None

    def __post_init__(self) -> None:
        # Execute the ml build manifest post init workflow in explicit, reviewable steps.
        if self.EXPECTED_SCHEMA is not None and self.artifact_schema is not self.EXPECTED_SCHEMA:
            raise MlArtifactContractError("ML build manifest has another artifact schema")
        _ordered_ids(self.input_artifact_ids, "ML build inputs")
        _canonical_object(self.semantic_inputs, "ML build semantic inputs")
        _token(self.compiler_version, "compiler_version")

    # Define ml build manifest identity document as one focused operation with an explicit
    # boundary.
    def identity_document(self) -> dict[str, object]:
        # Execute the ml build manifest identity document workflow in explicit, reviewable
        # steps.
        return {
            "artifact_schema": self.artifact_schema.value,
            "compiler_bundle_id": self.compiler_bundle_id.hex,
            "compiler_version": self.compiler_version,
            "input_artifact_ids": [item.hex for item in self.input_artifact_ids],
            # Include runtime lock id in the completed ml build manifest identity document
            # result.
            "runtime_lock_id": self.runtime_lock_id.hex,
            "semantic_inputs": _canonical_object(self.semantic_inputs, "ML build semantic inputs"),
            "writer_bundle_id": self.writer_bundle_id.hex,
            "writer_settings_digest": self.writer_settings_digest.hex,
        }

    # Apply property semantics to the following ml build manifest build key contract.
    @property
    def build_key(self) -> ContentDigest:
        return domain_digest("backtest.ml-artifact-build.v1", self.identity_document())

    def document(self) -> dict[str, object]:
        return {**self.identity_document(), "build_key": self.build_key.hex}

    # Apply classmethod semantics to the following ml build manifest from document
    # contract.
    @classmethod
    def from_document(cls, value: object) -> Self:
        # Execute the ml build manifest from document workflow in explicit, reviewable
        # steps.
        document = _object(value, "ML build manifest")
        _keys(
            document,
            {
                "artifact_schema",
                # Pass build key explicitly so _keys receives a reviewable artifact schema
                # and build key input in ml build manifest from document.
                "build_key",
                "compiler_bundle_id",
                "compiler_version",
                "input_artifact_ids",
                "runtime_lock_id",
                # Pass semantic inputs explicitly so _keys receives a reviewable artifact
                # schema and build key input in ml build manifest from document.
                "semantic_inputs",
                "writer_bundle_id",
                "writer_settings_digest",
            },
            "ML build manifest",
            # Complete _keys only after its artifact schema and build key inputs are visible
            # in ml build manifest from document.
        )
        try:
            schema = MlArtifactSchema(_token(document["artifact_schema"], "artifact_schema"))
        except ValueError as error:
            raise MlArtifactContractError("unknown ML artifact schema") from error
        # Assemble result once so the ml build manifest from document workflow shares one
        # value.
        result = cls(
            artifact_schema=schema,
            input_artifact_ids=tuple(
                ArtifactId(_token(item, "input artifact ID"))
                for item in _list(document["input_artifact_ids"], "input_artifact_ids")
                # Complete tuple only after its input artifact id and input artifact ids
                # inputs are visible in ml build manifest from document.
            ),
            semantic_inputs=canonical_json_bytes(
                _object(document["semantic_inputs"], "semantic_inputs")
            ),
            compiler_bundle_id=BundleId(
                # Keep the token and compiler bundle id _token step visible while building
                # result.
                _token(document["compiler_bundle_id"], "compiler_bundle_id")
            ),
            compiler_version=_token(document["compiler_version"], "compiler_version"),
            writer_bundle_id=BundleId(_token(document["writer_bundle_id"], "writer_bundle_id")),
            runtime_lock_id=RuntimeLockId(_token(document["runtime_lock_id"], "runtime_lock_id")),
            # Keep the content digest and token ContentDigest step visible while building
            # result.
            writer_settings_digest=ContentDigest(
                _token(document["writer_settings_digest"], "writer_settings_digest")
            ),
        )
        stored = ContentDigest(_token(document["build_key"], "build_key"))
        # Guard this path with stored != result.build_key before applying effects.
        if stored != result.build_key:
            raise MlArtifactContractError("ML build key mismatch")
        return result


class FeatureSetBuildManifest(MlBuildManifest):
    EXPECTED_SCHEMA = MlArtifactSchema.FEATURE_SET


# Keep the universe build manifest contract and validation rules together.
class UniverseBuildManifest(MlBuildManifest):
    EXPECTED_SCHEMA = MlArtifactSchema.UNIVERSE


class LabelSetBuildManifest(MlBuildManifest):
    EXPECTED_SCHEMA = MlArtifactSchema.LABEL_SET


class ModelBundleBuildManifest(MlBuildManifest):
    # Declare expected schema explicitly in the model bundle build manifest contract.
    EXPECTED_SCHEMA = MlArtifactSchema.MODEL_BUNDLE


class ModelScheduleBuildManifest(MlBuildManifest):
    EXPECTED_SCHEMA = MlArtifactSchema.MODEL_SCHEDULE


class PredictionSetBuildManifest(MlBuildManifest):
    EXPECTED_SCHEMA = MlArtifactSchema.PREDICTION_SET


# Bind build by schema once as an explicit module-level contract.
_BUILD_BY_SCHEMA: dict[MlArtifactSchema, type[MlBuildManifest]] = {
    MlArtifactSchema.FEATURE_SET: FeatureSetBuildManifest,
    MlArtifactSchema.UNIVERSE: UniverseBuildManifest,
    MlArtifactSchema.LABEL_SET: LabelSetBuildManifest,
    MlArtifactSchema.MODEL_BUNDLE: ModelBundleBuildManifest,
    # Keep the ml artifact schema component named inside the build by schema contract.
    MlArtifactSchema.MODEL_SCHEDULE: ModelScheduleBuildManifest,
    MlArtifactSchema.PREDICTION_SET: PredictionSetBuildManifest,
}


# Keep the ml artifact manifest contract and validation rules together.
@dataclass(frozen=True, slots=True)
class MlArtifactManifest:
    artifact_schema: MlArtifactSchema
    build: MlBuildManifest
    row_count: int
    # Declare logical content hash explicitly in the ml artifact manifest contract.
    logical_content_hash: ContentDigest
    layout: MlLayoutManifest
    semantic_content: bytes

    EXPECTED_SCHEMA: ClassVar[MlArtifactSchema | None] = None

    def __post_init__(self) -> None:
        # Execute the ml artifact manifest post init workflow in explicit, reviewable
        # steps.
        if self.EXPECTED_SCHEMA is not None and self.artifact_schema is not self.EXPECTED_SCHEMA:
            raise MlArtifactContractError("ML content manifest has another artifact schema")
        if self.build.artifact_schema is not self.artifact_schema:
            raise MlArtifactContractError("ML build/content schemas differ")
        _integer(self.row_count, "row_count")
        # Invoke _canonical_object for ml semantic content and semantic content as a
        # visible ml artifact manifest post init step.
        _canonical_object(self.semantic_content, "ML semantic content")

    def identity_document(self) -> dict[str, object]:
        # Execute the ml artifact manifest identity document workflow in explicit,
        # reviewable steps.
        return {
            "artifact_schema": self.artifact_schema.value,
            "layout": self.layout.document(),
            "logical_content_hash": self.logical_content_hash.hex,
            "row_count": self.row_count,
            # Include semantic content in the completed ml artifact manifest identity
            # document result.
            "semantic_content": _canonical_object(self.semantic_content, "ML semantic content"),
        }

    def document(self) -> dict[str, object]:
        return {**self.identity_document(), "build": self.build.document()}

    @classmethod
    # Define ml artifact manifest from document as one focused operation with an explicit
    # boundary.
    def from_document(cls, value: object) -> Self:
        # Execute the ml artifact manifest from document workflow in explicit, reviewable
        # steps.
        document = _object(value, "ML artifact manifest")
        _keys(
            document,
            {
                "artifact_schema",
                # Pass build explicitly so _keys receives a reviewable artifact schema and
                # build input in ml artifact manifest from document.
                "build",
                "layout",
                "logical_content_hash",
                "row_count",
                "semantic_content",
                # Close the artifact schema and build payload only after all ml artifact
                # manifest from document fields are present.
            },
            "ML artifact manifest",
        )
        try:
            schema = MlArtifactSchema(_token(document["artifact_schema"], "artifact_schema"))
        # Translate value error through the ml artifact manifest from document boundary
        # without hiding other errors.
        except ValueError as error:
            raise MlArtifactContractError("unknown ML artifact schema") from error
        build_type = _BUILD_BY_SCHEMA[schema]
        return cls(
            artifact_schema=schema,
            # Include build in the completed ml artifact manifest from document result.
            build=build_type.from_document(document["build"]),
            row_count=_integer(document["row_count"], "row_count"),
            logical_content_hash=ContentDigest(
                _token(document["logical_content_hash"], "logical_content_hash")
            ),
            # Include layout in the completed ml artifact manifest from document result.
            layout=MlLayoutManifest.from_document(document["layout"]),
            semantic_content=canonical_json_bytes(
                _object(document["semantic_content"], "semantic_content")
            ),
        )


# Keep the feature set artifact manifest contract and validation rules together.
class FeatureSetArtifactManifest(MlArtifactManifest):
    EXPECTED_SCHEMA = MlArtifactSchema.FEATURE_SET


class UniverseArtifactManifest(MlArtifactManifest):
    EXPECTED_SCHEMA = MlArtifactSchema.UNIVERSE


class LabelSetArtifactManifest(MlArtifactManifest):
    # Declare expected schema explicitly in the label set artifact manifest contract.
    EXPECTED_SCHEMA = MlArtifactSchema.LABEL_SET


class ModelBundleArtifactManifest(MlArtifactManifest):
    EXPECTED_SCHEMA = MlArtifactSchema.MODEL_BUNDLE


class ModelScheduleArtifactManifest(MlArtifactManifest):
    EXPECTED_SCHEMA = MlArtifactSchema.MODEL_SCHEDULE


# Keep the prediction set artifact manifest contract and validation rules together.
class PredictionSetArtifactManifest(MlArtifactManifest):
    EXPECTED_SCHEMA = MlArtifactSchema.PREDICTION_SET


# Keep the feature overlay row contract and validation rules together.
@dataclass(frozen=True, slots=True)
class FeatureOverlayRow:
    replay_row_id: int
    available_boundary_ordinal: int
    values: tuple[int | None, ...]

    # Define feature overlay row post init as one focused operation with an explicit
    # boundary.
    def __post_init__(self) -> None:
        # Execute the feature overlay row post init workflow in explicit, reviewable
        # steps.
        _integer(self.replay_row_id, "replay_row_id")
        _integer(self.available_boundary_ordinal, "available_boundary_ordinal")
        if any(
            value is not None and (isinstance(value, bool) or not isinstance(value, int))
            for value in self.values
            # Complete any only after its values and isinstance inputs are visible in feature
            # overlay row post init.
        ):
            raise MlArtifactContractError("feature values must be integers or None")


# Keep the universe membership row contract and validation rules together.
@dataclass(frozen=True, slots=True, order=True)
class UniverseMembershipRow:
    entity_id: int
    eligible_from: int
    eligible_until: int
    # Declare input available boundary explicitly in the universe membership row contract.
    input_available_boundary: int

    def __post_init__(self) -> None:
        # Execute the universe membership row post init workflow in explicit, reviewable
        # steps.
        for field in ("entity_id", "eligible_from", "input_available_boundary"):
            _integer(getattr(self, field), field)
        _integer(self.eligible_until, "eligible_until", minimum=1)
        if self.eligible_until <= self.eligible_from:
            raise MlArtifactContractError("universe interval must be non-empty")
        # Evaluate the complete universe membership row post init input available boundary
        # and eligible from condition before guarded effects.
        if self.input_available_boundary > self.eligible_from:
            raise MlArtifactContractError("universe membership uses a future input")


# Keep the label overlay row contract and validation rules together.
@dataclass(frozen=True, slots=True)
class LabelOverlayRow:
    replay_row_id: int
    effective_boundary_ordinal: int
    future_boundary_used: int
    # Declare value explicitly in the label overlay row contract.
    value: int | None

    def __post_init__(self) -> None:
        # Execute the label overlay row post init workflow in explicit, reviewable steps.
        for field in (
            "replay_row_id",
            "effective_boundary_ordinal",
            "future_boundary_used",
        ):
            # Invoke _integer for getattr and field as a visible label overlay row post
            # init step.
            _integer(getattr(self, field), field)
        if self.future_boundary_used < self.effective_boundary_ordinal:
            raise MlArtifactContractError("label future boundary precedes effective boundary")
        if self.value is not None and (
            isinstance(self.value, bool) or not isinstance(self.value, int)
            # Evaluate the complete label overlay row post init value and isinstance condition
            # before guarded effects.
        ):
            raise MlArtifactContractError("label value must be an integer or None")


# Keep the exact linear model payload contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ExactLinearModelPayload:
    weights: tuple[int, ...]
    intercept: int
    output_divisor: int = 1

    # Define exact linear model payload post init as one focused operation with an
    # explicit boundary.
    def __post_init__(self) -> None:
        # Execute the exact linear model payload post init workflow in explicit,
        # reviewable steps.
        if not self.weights:
            raise MlArtifactContractError("linear model requires weights")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in self.weights):
            raise MlArtifactContractError("linear model weights must be integers")
        if isinstance(self.intercept, bool) or not isinstance(self.intercept, int):
            # Fail the exact linear model payload post init path with
            # MlArtifactContractError for linear model intercept must be an integer when
            # isinstance and intercept is true; do not continue ambiguously.
            raise MlArtifactContractError("linear model intercept must be an integer")
        _integer(self.output_divisor, "output_divisor", minimum=1)


# Keep the frozen prediction row contract and validation rules together.
@dataclass(frozen=True, slots=True)
class FrozenPredictionRow:
    replay_row_id: int
    effective_boundary_ordinal: int
    inference_completion_boundary: int
    # Declare availability explicitly in the frozen prediction row contract.
    availability: PredictionAvailability
    value: int | None

    def __post_init__(self) -> None:
        # Execute the frozen prediction row post init workflow in explicit, reviewable
        # steps.
        for field in (
            "replay_row_id",
            "effective_boundary_ordinal",
            "inference_completion_boundary",
        ):
            # Invoke _integer for getattr and field as a visible frozen prediction row
            # post init step.
            _integer(getattr(self, field), field)
        if self.value is not None and (
            isinstance(self.value, bool) or not isinstance(self.value, int)
        ):
            raise MlArtifactContractError("prediction value must be an integer or None")
        # Evaluate the complete frozen prediction row post init inference completion
        # boundary and availability condition before guarded effects.
        if self.availability.inference_completion_boundary != self.inference_completion_boundary:
            raise MlArtifactContractError("prediction inference availability operands differ")


# Keep the build feature set request contract and validation rules together.
@dataclass(frozen=True, slots=True)
class BuildFeatureSetRequest:
    replay_pack_id: ReplayPackId
    replay_semantics_id: ContentDigest
    replay_layout_schema_id: ContentDigest
    # Declare feature specs explicitly in the build feature set request contract.
    feature_specs: tuple[FeatureSpec, ...]
    input_feature_set_ids: tuple[FeatureSetId, ...]
    rows: Iterable[FeatureOverlayRow]
    compiler_version: str

    def __post_init__(self) -> None:
        # Execute the build feature set request post init workflow in explicit, reviewable
        # steps.
        if not self.feature_specs:
            raise MlArtifactContractError("FeatureSet requires feature specs")
        ids = tuple(spec.feature_spec_id.hex for spec in self.feature_specs)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise MlArtifactContractError("feature specs must be identity-sorted and unique")
        # Evaluate the complete build feature set request post init entity key, replay row
        # id and spec condition before guarded effects.
        if any(spec.entity_key != "replay_row_id" for spec in self.feature_specs):
            raise MlArtifactContractError("v1 features must align to replay_row_id")
        _ordered_ids(self.input_feature_set_ids, "input_feature_set_ids")
        _token(self.compiler_version, "compiler_version")


# Keep the build universe request contract and validation rules together.
@dataclass(frozen=True, slots=True)
class BuildUniverseRequest:
    snapshot_id: SnapshotId
    universe_spec_id: ContentDigest
    input_feature_set_ids: tuple[FeatureSetId, ...]
    # Declare builder bundle id explicitly in the build universe request contract.
    builder_bundle_id: BundleId
    builder_config_digest: ContentDigest
    rows: Iterable[UniverseMembershipRow]
    compiler_version: str

    def __post_init__(self) -> None:
        # Execute the build universe request post init workflow in explicit, reviewable
        # steps.
        _ordered_ids(self.input_feature_set_ids, "universe feature inputs")
        _token(self.compiler_version, "compiler_version")


# Keep the build label set request contract and validation rules together.
@dataclass(frozen=True, slots=True)
class BuildLabelSetRequest:
    snapshot_id: SnapshotId
    universe_id: UniverseId
    label_spec_id: ContentDigest
    # Declare label builder bundle id explicitly in the build label set request contract.
    label_builder_bundle_id: BundleId
    label_config_digest: ContentDigest
    training_cutoff: int
    rows: Iterable[LabelOverlayRow]
    compiler_version: str

    # Define build label set request post init as one focused operation with an explicit
    # boundary.
    def __post_init__(self) -> None:
        # Execute the build label set request post init workflow in explicit, reviewable
        # steps.
        _integer(self.training_cutoff, "training_cutoff")
        _token(self.compiler_version, "compiler_version")


# Keep the publish model bundle request contract and validation rules together.
@dataclass(frozen=True, slots=True)
class PublishModelBundleRequest:
    training_spec: TrainingJobSpec
    feature_schema_digest: ContentDigest
    payload: ExactLinearModelPayload
    # Declare preprocessing digest explicitly in the publish model bundle request
    # contract.
    preprocessing_digest: ContentDigest
    calibration_digest: ContentDigest
    metrics_digest: ContentDigest
    fitted_component_available_boundaries: tuple[int, ...]
    framework: str
    # Declare canonicality explicitly in the publish model bundle request contract.
    canonicality: ModelCanonicality
    compiler_version: str

    def __post_init__(self) -> None:
        # Execute the publish model bundle request post init workflow in explicit,
        # reviewable steps.
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in self.fitted_component_available_boundaries
        ):
            raise MlArtifactContractError("fitted availability must be non-negative")
        # Invoke _token for framework as a visible publish model bundle request post init
        # step.
        _token(self.framework, "framework")
        _token(self.compiler_version, "compiler_version")


# Keep the publish model schedule request contract and validation rules together.
@dataclass(frozen=True, slots=True)
class PublishModelScheduleRequest:
    schedule: ModelSchedule
    canonicality: ModelCanonicality
    compiler_version: str

    # Define publish model schedule request post init as one focused operation with an
    # explicit boundary.
    def __post_init__(self) -> None:
        _token(self.compiler_version, "compiler_version")


# Keep the build prediction set request contract and validation rules together.
@dataclass(frozen=True, slots=True)
class BuildPredictionSetRequest:
    replay_pack_id: ReplayPackId
    replay_semantics_id: ContentDigest
    replay_layout_schema_id: ContentDigest
    # Declare feature set ids explicitly in the build prediction set request contract.
    feature_set_ids: tuple[FeatureSetId, ...]
    model_schedule_id: ModelScheduleId
    model_bundle_ids: tuple[ModelBundleId, ...]
    prediction_name: str
    inference_mode: InferenceMode
    # Declare inference policy digest explicitly in the build prediction set request
    # contract.
    inference_policy_digest: ContentDigest
    causal_availability_policy: str
    canonicality: ModelCanonicality
    rows: Iterable[FrozenPredictionRow]
    compiler_version: str

    # Define build prediction set request post init as one focused operation with an
    # explicit boundary.
    def __post_init__(self) -> None:
        # Execute the build prediction set request post init workflow in explicit,
        # reviewable steps.
        _ordered_ids(self.feature_set_ids, "prediction feature inputs", allow_empty=False)
        _ordered_ids(self.model_bundle_ids, "prediction model inputs", allow_empty=False)
        _token(self.prediction_name, "prediction_name")
        _token(self.causal_availability_policy, "causal_availability_policy")
        if self.inference_mode is not InferenceMode.FROZEN:
            # Fail the build prediction set request post init path with
            # MlArtifactContractError for prediction set v1 publishes only frozen
            # predictions when inference mode and frozen is true; do not continue
            # ambiguously.
            raise MlArtifactContractError("PredictionSet v1 publishes only frozen predictions")
        _token(self.compiler_version, "compiler_version")


# Keep the train exact linear model request contract and validation rules together.
@dataclass(frozen=True, slots=True)
class TrainExactLinearModelRequest:
    training_spec: TrainingJobSpec
    feature_schema_digest: ContentDigest
    preprocessing_digest: ContentDigest
    # Declare calibration digest explicitly in the train exact linear model request
    # contract.
    calibration_digest: ContentDigest
    ridge_lambda: int
    framework: str
    canonicality: ModelCanonicality
    compiler_version: str

    # Define train exact linear model request post init as one focused operation with an
    # explicit boundary.
    def __post_init__(self) -> None:
        # Execute the train exact linear model request post init workflow in explicit,
        # reviewable steps.
        _integer(self.ridge_lambda, "ridge_lambda")
        _token(self.framework, "framework")
        _token(self.compiler_version, "compiler_version")
        if self.canonicality is not ModelCanonicality.CANONICAL_EXACT:
            raise MlArtifactContractError("exact integer trainer requires CANONICAL_EXACT")


# Keep the build frozen predictions request contract and validation rules together.
@dataclass(frozen=True, slots=True)
class BuildFrozenPredictionsRequest:
    replay_pack_id: ReplayPackId
    replay_semantics_id: ContentDigest
    replay_layout_schema_id: ContentDigest
    # Declare feature set ids explicitly in the build frozen predictions request contract.
    feature_set_ids: tuple[FeatureSetId, ...]
    model_schedule_id: ModelScheduleId
    model_bundle_ids: tuple[ModelBundleId, ...]
    prediction_name: str
    inference_delay_boundaries: int
    # Declare missing policy explicitly in the build frozen predictions request contract.
    missing_policy: FrozenMissingPolicy
    canonicality: ModelCanonicality
    compiler_version: str

    def __post_init__(self) -> None:
        # Execute the build frozen predictions request post init workflow in explicit,
        # reviewable steps.
        _ordered_ids(self.feature_set_ids, "frozen prediction feature inputs", allow_empty=False)
        _ordered_ids(self.model_bundle_ids, "frozen prediction model inputs", allow_empty=False)
        _token(self.prediction_name, "prediction_name")
        _integer(self.inference_delay_boundaries, "inference_delay_boundaries")
        _token(self.compiler_version, "compiler_version")
        # Evaluate the complete build frozen predictions request post init canonicality,
        # canonical exact and model canonicality condition before guarded effects.
        if self.canonicality is not ModelCanonicality.CANONICAL_EXACT:
            raise MlArtifactContractError("exact frozen builder requires CANONICAL_EXACT")


# Keep the published ml artifact contract and validation rules together.
@dataclass(frozen=True, slots=True)
class PublishedMlArtifact:
    artifact: CommittedArtifact
    manifest: MlArtifactManifest
    requested_build: MlBuildManifest

    # Declare expected kind explicitly in the published ml artifact contract.
    EXPECTED_KIND: ClassVar[ArtifactKind | None] = None

    def __post_init__(self) -> None:
        # Execute the published ml artifact post init workflow in explicit, reviewable
        # steps.
        if self.EXPECTED_KIND is not None and self.artifact.kind is not self.EXPECTED_KIND:
            raise MlArtifactContractError("published ML artifact kind mismatch")
        if self.manifest.artifact_schema is not self.requested_build.artifact_schema:
            raise MlArtifactContractError("published ML build/content schema mismatch")
        if self.artifact.build_key != self.manifest.build.build_key:
            # Fail the published ml artifact post init path with MlArtifactContractError
            # for published descriptor/manifest build key mismatch when build key,
            # artifact and build is true; do not continue ambiguously.
            raise MlArtifactContractError("published descriptor/manifest build key mismatch")
        if self.artifact.input_artifact_ids != self.manifest.build.input_artifact_ids:
            raise MlArtifactContractError("published descriptor/manifest inputs mismatch")

    @property
    def build_key(self) -> ContentDigest:
        # Return the completed published ml artifact build key result without a hidden
        # fallback.
        return self.requested_build.build_key


# Keep the published feature set contract and validation rules together.
class PublishedFeatureSet(PublishedMlArtifact):
    EXPECTED_KIND = ArtifactKind.FEATURE_SET

    @property
    def feature_set_id(self) -> FeatureSetId:
        return FeatureSetId(self.artifact.artifact_id.hex)


# Keep the published universe contract and validation rules together.
class PublishedUniverse(PublishedMlArtifact):
    EXPECTED_KIND = ArtifactKind.UNIVERSE

    @property
    def universe_id(self) -> UniverseId:
        return UniverseId(self.artifact.artifact_id.hex)


# Keep the published label set contract and validation rules together.
class PublishedLabelSet(PublishedMlArtifact):
    EXPECTED_KIND = ArtifactKind.LABEL_SET

    @property
    def label_set_id(self) -> LabelSetId:
        return LabelSetId(self.artifact.artifact_id.hex)


# Keep the published model bundle contract and validation rules together.
class PublishedModelBundle(PublishedMlArtifact):
    EXPECTED_KIND = ArtifactKind.MODEL_BUNDLE

    @property
    def model_bundle_id(self) -> ModelBundleId:
        return ModelBundleId(self.artifact.artifact_id.hex)


# Keep the published model schedule contract and validation rules together.
class PublishedModelSchedule(PublishedMlArtifact):
    EXPECTED_KIND = ArtifactKind.MODEL_SCHEDULE

    @property
    def model_schedule_id(self) -> ModelScheduleId:
        return ModelScheduleId(self.artifact.artifact_id.hex)


# Keep the published prediction set contract and validation rules together.
class PublishedPredictionSet(PublishedMlArtifact):
    EXPECTED_KIND = ArtifactKind.PREDICTION_SET

    @property
    def prediction_set_id(self) -> PredictionSetId:
        return PredictionSetId(self.artifact.artifact_id.hex)


# Define feature spec document as one focused operation with an explicit boundary.
def feature_spec_document(spec: FeatureSpec) -> dict[str, object]:
    return {**spec.identity_document(), "feature_spec_id": spec.feature_spec_id.hex}


def feature_spec_from_document(value: object) -> FeatureSpec:
    # Execute the feature spec from document workflow in explicit, reviewable steps.
    document = _object(value, "FeatureSpec")
    _keys(
        document,
        {
            "available_time_semantics",
            # Pass code bundle id explicitly so _keys receives a reviewable available time
            # semantics and code bundle id input in feature spec from document.
            "code_bundle_id",
            "dtype",
            "effective_time_semantics",
            "entity_key",
            "feature_spec_id",
            # Pass input ids explicitly so _keys receives a reviewable available time
            # semantics and code bundle id input in feature spec from document.
            "input_ids",
            "name",
            "null_policy",
            "runtime_lock_id",
            "version",
            # Pass warmup boundaries explicitly so _keys receives a reviewable available
            # time semantics and code bundle id input in feature spec from document.
            "warmup_boundaries",
        },
        "FeatureSpec",
    )
    try:
        # Assemble null policy once so the feature spec from document workflow shares one
        # value.
        null_policy = NullPolicy(_token(document["null_policy"], "null_policy"))
    except ValueError as error:
        raise MlArtifactContractError("FeatureSpec null policy is unsupported") from error
    result = FeatureSpec(
        name=_token(document["name"], "name"),
        # Keep the integer and version _integer step visible while building result.
        version=_integer(document["version"], "version", minimum=1),
        entity_key=_token(document["entity_key"], "entity_key"),
        input_ids=tuple(
            ContentDigest(_token(item, "feature input ID"))
            for item in _list(document["input_ids"], "input_ids")
            # Complete tuple only after its feature input id and input ids inputs are visible
            # in feature spec from document.
        ),
        effective_time_semantics=_token(
            document["effective_time_semantics"], "effective_time_semantics"
        ),
        available_time_semantics=_token(
            # Pass document explicitly so _token receives a reviewable available time
            # semantics and document input in feature spec from document.
            document["available_time_semantics"],
            "available_time_semantics",
        ),
        warmup_boundaries=_integer(document["warmup_boundaries"], "warmup_boundaries"),
        dtype=_token(document["dtype"], "dtype"),
        # Pass null policy explicitly so FeatureSpec receives a reviewable name and
        # version input in feature spec from document.
        null_policy=null_policy,
        # Keep the bundle id and token BundleId step visible while building result.
        code_bundle_id=BundleId(_token(document["code_bundle_id"], "code_bundle_id")),
        runtime_lock_id=RuntimeLockId(_token(document["runtime_lock_id"], "runtime_lock_id")),
    )
    stored = ContentDigest(_token(document["feature_spec_id"], "feature_spec_id"))
    if stored != result.feature_spec_id:
        # Fail the feature spec from document path with MlArtifactContractError for
        # feature spec id mismatch when stored, feature spec id and result is true; do not
        # continue ambiguously.
        raise MlArtifactContractError("FeatureSpec ID mismatch")
    return result


def training_spec_document(spec: TrainingJobSpec) -> dict[str, object]:
    # Execute the training spec document workflow in explicit, reviewable steps.
    return {
        "feature_set_ids": [item.hex for item in spec.feature_set_ids],
        "hyperparameter_digest": spec.hyperparameter_digest.hex,
        "label_set_id": spec.label_set_id.hex,
        "modeled_available_boundary": spec.modeled_available_boundary,
        # Include root seeds in the completed training spec document result.
        "root_seeds": list(spec.root_seeds),
        "runtime_lock_id": spec.runtime_lock_id.hex,
        "split": spec.split.document(),
        "trainer_bundle_id": spec.trainer_bundle_id.hex,
        "training_cutoff": spec.training_cutoff,
        # Include training job spec id in the completed training spec document result.
        "training_job_spec_id": spec.training_job_spec_id.hex,
        "universe_id": spec.universe_id.hex,
    }


def training_spec_from_document(value: object) -> TrainingJobSpec:
    # Execute the training spec from document workflow in explicit, reviewable steps.
    document = _object(value, "TrainingJobSpec")
    _keys(
        document,
        {
            "feature_set_ids",
            # Pass hyperparameter digest explicitly so _keys receives a reviewable feature
            # set ids and hyperparameter digest input in training spec from document.
            "hyperparameter_digest",
            "label_set_id",
            "modeled_available_boundary",
            "root_seeds",
            "runtime_lock_id",
            # Pass split explicitly so _keys receives a reviewable feature set ids and
            # hyperparameter digest input in training spec from document.
            "split",
            "trainer_bundle_id",
            "training_cutoff",
            "training_job_spec_id",
            "universe_id",
            # Close the feature set ids and hyperparameter digest payload only after all
            # training spec from document fields are present.
        },
        "TrainingJobSpec",
    )
    split_document = _object(document["split"], "TemporalSplit")
    _keys(
        # Pass split document explicitly so _keys receives a reviewable embargo boundaries
        # and purge boundaries input in training spec from document.
        split_document,
        {
            "embargo_boundaries",
            "purge_boundaries",
            "train_from",
            # Pass train until explicitly so _keys receives a reviewable embargo
            # boundaries and purge boundaries input in training spec from document.
            "train_until",
            "validation_from",
            "validation_until",
        },
        "TemporalSplit",
        # Complete _keys only after its embargo boundaries and purge boundaries inputs are
        # visible in training spec from document.
    )
    result = TrainingJobSpec(
        feature_set_ids=tuple(
            FeatureSetId(_token(item, "feature_set_id"))
            for item in _list(document["feature_set_ids"], "feature_set_ids")
            # Complete tuple only after its feature set id and feature set ids inputs are
            # visible in training spec from document.
        ),
        label_set_id=LabelSetId(_token(document["label_set_id"], "label_set_id")),
        universe_id=UniverseId(_token(document["universe_id"], "universe_id")),
        split=TemporalSplit(
            train_from=_integer(split_document["train_from"], "train_from"),
            # Keep the integer and train until _integer step visible while building
            # result.
            train_until=_integer(split_document["train_until"], "train_until"),
            validation_from=_integer(split_document["validation_from"], "validation_from"),
            validation_until=_integer(split_document["validation_until"], "validation_until"),
            purge_boundaries=_integer(split_document["purge_boundaries"], "purge_boundaries"),
            embargo_boundaries=_integer(split_document["embargo_boundaries"], "embargo_boundaries"),
            # Complete TemporalSplit only after its train from and train until inputs are
            # visible in training spec from document.
        ),
        hyperparameter_digest=ContentDigest(
            _token(document["hyperparameter_digest"], "hyperparameter_digest")
        ),
        root_seeds=tuple(
            # Keep the item _integer step visible while building result.
            _integer(item, "root_seed")
            for item in _list(document["root_seeds"], "root_seeds")
        ),
        training_cutoff=_integer(document["training_cutoff"], "training_cutoff"),
        modeled_available_boundary=_integer(
            # Pass document explicitly so _integer receives a reviewable modeled available
            # boundary and document input in training spec from document.
            document["modeled_available_boundary"],
            "modeled_available_boundary",
            # Complete _integer only after its modeled available boundary and document inputs
            # are visible in training spec from document.
        ),
        trainer_bundle_id=BundleId(_token(document["trainer_bundle_id"], "trainer_bundle_id")),
        runtime_lock_id=RuntimeLockId(_token(document["runtime_lock_id"], "runtime_lock_id")),
    )
    stored = ContentDigest(_token(document["training_job_spec_id"], "training_job_spec_id"))
    # Guard this path with stored != result.training_job_spec_id before applying effects.
    if stored != result.training_job_spec_id:
        raise MlArtifactContractError("TrainingJobSpec ID mismatch")
    return result


def model_schedule_document(schedule: ModelSchedule) -> dict[str, object]:
    # Execute the model schedule document workflow in explicit, reviewable steps.
    return {
        "entries": [item.document() for item in schedule.entries],
        "fallback_model_bundle_id": (
            None
            if schedule.fallback_model_bundle_id is None
            # Route all remaining cases through the explicit alternative branch.
            else schedule.fallback_model_bundle_id.hex
        ),
        "schedule_digest": schedule.build_key.hex,
    }


def model_schedule_from_document(value: object) -> ModelSchedule:
    # Execute the model schedule from document workflow in explicit, reviewable steps.
    document = _object(value, "ModelSchedule")
    _keys(
        document,
        {"entries", "fallback_model_bundle_id", "schedule_digest"},
        "ModelSchedule",
        # Complete _keys only after its entries and fallback model bundle id inputs are
        # visible in model schedule from document.
    )
    entries: list[ModelScheduleEntry] = []
    for item in _list(document["entries"], "entries"):
        # Process _list(document['entries'], 'entries') inside the bounded model schedule
        # from document loop.
        entry = _object(item, "ModelScheduleEntry")
        _keys(
            entry,
            {
                "availability_basis",
                # Pass eligible from explicitly so _keys receives a reviewable
                # availability basis and eligible from input in model schedule from
                # document.
                "eligible_from",
                "eligible_until",
                "model_available_boundary",
                "model_bundle_id",
                "training_cutoff",
                # Close the availability basis and eligible from payload only after all model
                # schedule from document fields are present.
            },
            "ModelScheduleEntry",
        )
        entries.append(
            ModelScheduleEntry(
                # Pass eligible from explicitly to append for eligible from and eligible
                # until.
                eligible_from=_integer(entry["eligible_from"], "eligible_from"),
                eligible_until=_integer(entry["eligible_until"], "eligible_until", minimum=1),
                model_bundle_id=ModelBundleId(_token(entry["model_bundle_id"], "model_bundle_id")),
                training_cutoff=_integer(entry["training_cutoff"], "training_cutoff"),
                model_available_boundary=_integer(
                    # Pass entry explicitly so _integer receives a reviewable model
                    # available boundary and entry input in model schedule from document.
                    entry["model_available_boundary"],
                    "model_available_boundary",
                ),
                availability_basis=_token(entry["availability_basis"], "availability_basis"),
            )
            # Complete append only after its eligible from and eligible until inputs are
            # visible in model schedule from document.
        )
    # Assemble fallback value once so the model schedule from document workflow shares one
    # value.
    fallback_value = document["fallback_model_bundle_id"]
    if fallback_value is not None and not isinstance(fallback_value, str):
        raise MlArtifactContractError("fallback model ID must be a digest or null")
    result = ModelSchedule(
        tuple(entries),
        # Pass fallback model bundle id explicitly so ModelSchedule receives a reviewable
        # fallback model bundle id and tuple input in model schedule from document.
        fallback_model_bundle_id=(
            None
            if fallback_value is None
            else ModelBundleId(_token(fallback_value, "fallback_model_bundle_id"))
        ),
        # Complete ModelSchedule only after its fallback model bundle id and tuple inputs are
        # visible in model schedule from document.
    )
    stored = ContentDigest(_token(document["schedule_digest"], "schedule_digest"))
    if stored != result.build_key:
        raise MlArtifactContractError("ModelSchedule digest mismatch")
    return result


# Bind all once as an explicit module-level contract.
__all__ = [
    "BuildFeatureSetRequest",
    "BuildFrozenPredictionsRequest",
    "BuildLabelSetRequest",
    "BuildPredictionSetRequest",
    # Keep the build universe request component named inside the all contract.
    "BuildUniverseRequest",
    "ExactLinearModelPayload",
    "FeatureOverlayRow",
    "FeatureSetArtifactManifest",
    "FeatureSetBuildManifest",
    # Keep the frozen missing policy component named inside the all contract.
    "FrozenMissingPolicy",
    "FrozenPredictionRow",
    "LabelOverlayRow",
    "LabelSetArtifactManifest",
    "LabelSetBuildManifest",
    # Keep the ml array layout component named inside the all contract.
    "MlArrayLayout",
    "MlArtifactContractError",
    "MlArtifactManifest",
    "MlArtifactSchema",
    "MlBuildManifest",
    # Keep the ml layout manifest component named inside the all contract.
    "MlLayoutManifest",
    "MlLogicalStreamHasher",
    "ModelBundleArtifactManifest",
    "ModelBundleBuildManifest",
    "ModelScheduleArtifactManifest",
    # Keep the model schedule build manifest component named inside the all contract.
    "ModelScheduleBuildManifest",
    "PredictionSetArtifactManifest",
    "PredictionSetBuildManifest",
    "PublishModelBundleRequest",
    "PublishModelScheduleRequest",
    # Keep the published feature set component named inside the all contract.
    "PublishedFeatureSet",
    "PublishedLabelSet",
    "PublishedMlArtifact",
    "PublishedModelBundle",
    "PublishedModelSchedule",
    # Keep the published prediction set component named inside the all contract.
    "PublishedPredictionSet",
    "PublishedUniverse",
    "TrainExactLinearModelRequest",
    "UniverseArtifactManifest",
    "UniverseBuildManifest",
    # Keep the universe membership row component named inside the all contract.
    "UniverseMembershipRow",
    "feature_spec_document",
    "feature_spec_from_document",
    "model_schedule_document",
    "model_schedule_from_document",
    # Keep the training spec document component named inside the all contract.
    "training_spec_document",
    "training_spec_from_document",
]
