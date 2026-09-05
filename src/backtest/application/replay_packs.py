"""Typed ReplayPack semantics, layout, derivation and committed-content manifests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import cast

from backtest.application.canonical_data import EffectiveSourceBoundary, ValidationStatus

# Import dataset plans at the visible module dependency boundary.
from backtest.application.dataset_plans import (
    dataset_spec_document,
    dataset_spec_from_document,
)
from backtest.application.errors import ReprepareRequiredError

# Import models at the visible module dependency boundary.
from backtest.application.models import ArtifactKind, CommittedArtifact, DatasetSpec
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import (
    BundleId,
    ContentDigest,
    # Include dataset revision id so the identifiers dependency remains explicit.
    DatasetRevisionId,
    LogicalContentHash,
    NetworkId,
    PositionSchemaId,
    ReplayPackId,
    # Include runtime lock id so the identifiers dependency remains explicit.
    RuntimeLockId,
    SnapshotId,
)
from backtest.domain.time import BlockRange


class ReplayManifestError(ValueError):
    """A ReplayPack manifest is malformed or internally inconsistent."""


def _require_token(value: str, *, field: str) -> None:
    # Execute the require token workflow in explicit, reviewable steps.
    if not value or value != value.strip():
        raise ReplayManifestError(f"{field} must be non-empty and trimmed")


def _require_relative_file(value: str, *, field: str) -> None:
    # Execute the require relative file workflow in explicit, reviewable steps.
    _require_token(value, field=field)
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ReplayManifestError(f"{field} must be a canonical relative path")
    if path.as_posix() != value or "\\" in value:
        # Fail the require relative file path with ReplayManifestError for must use
        # canonical posix separators and field when value, as posix and path is true; do
        # not continue ambiguously.
        raise ReplayManifestError(f"{field} must use canonical POSIX separators")


def _object(value: object, *, label: str) -> dict[str, object]:
    # Execute the object workflow in explicit, reviewable steps.
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ReplayManifestError(f"{label} must be a JSON object")
    return cast(dict[str, object], value)


def _exact_keys(value: dict[str, object], expected: set[str], *, label: str) -> None:
    # Execute the exact keys workflow in explicit, reviewable steps.
    if set(value) != expected:
        raise ReplayManifestError(f"{label} schema is invalid")


def _string(value: object, *, field: str) -> str:
    # Execute the string workflow in explicit, reviewable steps.
    if not isinstance(value, str):
        raise ReplayManifestError(f"{field} must be a string")
    _require_token(value, field=field)
    return value


def _integer(value: object, *, field: str, minimum: int = 0) -> int:
    # Execute the integer workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ReplayManifestError(f"{field} must be an integer >= {minimum}")
    return value


def _sequence(value: object, *, field: str) -> list[object]:
    # Execute the sequence workflow in explicit, reviewable steps.
    if not isinstance(value, list):
        raise ReplayManifestError(f"{field} must be a list")
    return cast(list[object], value)


def _block_range_document(value: BlockRange) -> dict[str, object]:
    # Execute the block range document workflow in explicit, reviewable steps.
    return {
        "from_block_ordinal": value.from_block_ordinal,
        "network_id": value.network_id.value,
        "position_schema_id": value.position_schema_id.value,
        "to_block_ordinal": value.to_block_ordinal,
        # Return the completed block range document result without a hidden fallback.
    }


def _block_range_from_document(value: object) -> BlockRange:
    # Execute the block range from document workflow in explicit, reviewable steps.
    document = _object(value, label="decision range")
    _exact_keys(
        document,
        {
            "from_block_ordinal",
            # Pass network id explicitly so _exact_keys receives a reviewable from block
            # ordinal and network id input in block range from document.
            "network_id",
            "position_schema_id",
            "to_block_ordinal",
        },
        label="decision range",
        # Complete _exact_keys only after its from block ordinal and network id inputs are
        # visible in block range from document.
    )
    return BlockRange(
        network_id=NetworkId(_string(document["network_id"], field="network_id")),
        position_schema_id=PositionSchemaId(
            _string(document["position_schema_id"], field="position_schema_id")
            # Complete PositionSchemaId only after its position schema id and string inputs
            # are visible in block range from document.
        ),
        from_block_ordinal=_integer(document["from_block_ordinal"], field="from_block_ordinal"),
        to_block_ordinal=_integer(document["to_block_ordinal"], field="to_block_ordinal"),
    )


@dataclass(frozen=True, slots=True)
# Keep the replay semantics manifest contract and validation rules together.
class ReplaySemanticsManifest:
    """Result-affecting semantics shared by Parquet and every fast layout."""

    canonical_schema_version: int
    canonical_projection: str
    event_kind_semantics: str
    group_policy: str
    ordering_policy: str
    # Declare integer policy explicitly in the replay semantics manifest contract.
    integer_policy: str
    missingness_policy: str
    causal_availability_policy: str

    def __post_init__(self) -> None:
        # Execute the replay semantics manifest post init workflow in explicit, reviewable
        # steps.
        if self.canonical_schema_version <= 0:
            raise ReplayManifestError("canonical_schema_version must be positive")
        for field in (
            "canonical_projection",
            "event_kind_semantics",
            # Traverse canonical projection, event kind semantics and group policy
            # explicitly so each replay semantics manifest post init iteration remains
            # traceable.
            "group_policy",
            "ordering_policy",
            "integer_policy",
            "missingness_policy",
            "causal_availability_policy",
            # Traverse canonical projection, event kind semantics and group policy explicitly
            # so each replay semantics manifest post init iteration remains traceable.
        ):
            _require_token(cast(str, getattr(self, field)), field=field)

    @classmethod
    def canonical_v1(cls, canonical_schema_version: int = 1) -> ReplaySemanticsManifest:
        """Legacy content-identity contract; never used for new compilation."""

        return cls(
            canonical_schema_version=canonical_schema_version,
            canonical_projection="canonical-event-v1",
            event_kind_semantics="block-token-creation-swap-v1",
            group_policy="atomic-v1",
            # Pass ordering policy explicitly so cls receives a reviewable canonical-
            # event-v1 and block-token-creation-swap-v1 input in replay semantics manifest
            # canonical v1.
            ordering_policy="canonical-position-v1",
            integer_policy="signed-int128-checked-v1",
            missingness_policy="explicit-none-v1",
            causal_availability_policy="effective-boundary-v1",
        )

    # Apply classmethod semantics to the following replay semantics manifest canonical v2
    # contract.
    @classmethod
    def canonical_v2(cls) -> ReplaySemanticsManifest:
        """Legacy networkless contract; never used for new compilation."""

        return cls(
            canonical_schema_version=2,
            canonical_projection="canonical-event-occurrence-v2",
            event_kind_semantics="block-token-creation-swap-v1",
            group_policy="atomic-v1",
            # Pass ordering policy explicitly so cls receives a reviewable canonical-
            # event-occurrence-v2 and block-token-creation-swap-v1 input in replay
            # semantics manifest canonical v2.
            ordering_policy="canonical-position-stable-occurrence-v2",
            integer_policy="signed-int128-checked-v1",
            missingness_policy="explicit-none-v1",
            causal_availability_policy="effective-boundary-v1",
        )

    # Apply classmethod semantics to the following replay semantics manifest canonical v3
    # contract.
    @classmethod
    def canonical_v3(cls) -> ReplaySemanticsManifest:
        """Network-aware generic canonical event contract."""

        return cls(
            canonical_schema_version=3,
            canonical_projection="canonical-generic-event-v3",
            event_kind_semantics="block-token-launch-venue-trade-lifecycle-v1",
            group_policy="atomic-v1",
            # Pass ordering policy explicitly so cls receives a reviewable canonical-
            # generic-event-v3 and block-token-launch-venue-trade-lifecycle-v1 input in
            # replay semantics manifest canonical v3.
            ordering_policy="network-position-stable-occurrence-v3",
            integer_policy="atomic-signed-int128-position-uint32-checked-v2",
            missingness_policy="explicit-none-exact-payload-bytes-v2",
            causal_availability_policy="effective-boundary-v1",
        )

    # Define replay semantics manifest identity document as one focused operation with an
    # explicit boundary.
    def identity_document(self) -> dict[str, object]:
        # Execute the replay semantics manifest identity document workflow in explicit,
        # reviewable steps.
        return {
            "canonical_schema_version": self.canonical_schema_version,
            "canonical_projection": self.canonical_projection,
            "causal_availability_policy": self.causal_availability_policy,
            "event_kind_semantics": self.event_kind_semantics,
            # Include group policy in the completed replay semantics manifest identity
            # document result.
            "group_policy": self.group_policy,
            "integer_policy": self.integer_policy,
            "missingness_policy": self.missingness_policy,
            "ordering_policy": self.ordering_policy,
        }

    # Apply property semantics to the following replay semantics manifest replay semantics
    # id contract.
    @property
    def replay_semantics_id(self) -> ContentDigest:
        return domain_digest("backtest.replay-semantics.v2", self.identity_document())

    def document(self) -> dict[str, object]:
        # Execute the replay semantics manifest document workflow in explicit, reviewable
        # steps.
        return {
            **self.identity_document(),
            "replay_semantics_id": self.replay_semantics_id.hex,
        }

    @classmethod
    # Define replay semantics manifest from document as one focused operation with an
    # explicit boundary.
    def from_document(cls, value: object) -> ReplaySemanticsManifest:
        # Execute the replay semantics manifest from document workflow in explicit,
        # reviewable steps.
        document = _object(value, label="replay semantics")
        _exact_keys(
            document,
            {
                "canonical_schema_version",
                # Pass canonical projection explicitly so _exact_keys receives a
                # reviewable canonical schema version and canonical projection input in
                # replay semantics manifest from document.
                "canonical_projection",
                "causal_availability_policy",
                "event_kind_semantics",
                "group_policy",
                "integer_policy",
                # Pass missingness policy explicitly so _exact_keys receives a reviewable
                # canonical schema version and canonical projection input in replay
                # semantics manifest from document.
                "missingness_policy",
                "ordering_policy",
                "replay_semantics_id",
            },
            label="replay semantics",
            # Complete _exact_keys only after its canonical schema version and canonical
            # projection inputs are visible in replay semantics manifest from document.
        )
        result = cls(
            canonical_schema_version=_integer(
                document["canonical_schema_version"],
                field="canonical_schema_version",
                # Pass minimum explicitly so _integer receives a reviewable canonical
                # schema version and document input in replay semantics manifest from
                # document.
                minimum=1,
            ),
            canonical_projection=_string(
                document["canonical_projection"], field="canonical_projection"
            ),
            # Keep the string and document _string step visible while building result.
            causal_availability_policy=_string(
                document["causal_availability_policy"],
                field="causal_availability_policy",
            ),
            event_kind_semantics=_string(
                # Pass field explicitly so _string receives a reviewable event kind
                # semantics and document input in replay semantics manifest from document.
                document["event_kind_semantics"],
                field="event_kind_semantics",
            ),
            group_policy=_string(document["group_policy"], field="group_policy"),
            integer_policy=_string(document["integer_policy"], field="integer_policy"),
            # Keep the string and document _string step visible while building result.
            missingness_policy=_string(document["missingness_policy"], field="missingness_policy"),
            # Keep the string and document _string step visible while building result.
            ordering_policy=_string(document["ordering_policy"], field="ordering_policy"),
        )
        stored_id = ContentDigest(_string(document["replay_semantics_id"], field="id"))
        if stored_id.hex != result.replay_semantics_id.hex:
            raise ReplayManifestError("replay semantics ID does not match its document")
        # Return the completed replay semantics manifest from document result without a
        # hidden fallback.
        return result


@dataclass(frozen=True, slots=True)
class ReplayArrayLayout:
    """One physical NumPy array and its exact logical role."""

    path: str
    dtype: str
    byte_order: str
    shape: tuple[int, ...]
    role: str
    # Declare overflow policy explicitly in the replay array layout contract.
    overflow_policy: str
    validity_path: str | None = None

    def __post_init__(self) -> None:
        # Execute the replay array layout post init workflow in explicit, reviewable
        # steps.
        _require_relative_file(self.path, field="array path")
        if not self.path.endswith(".npy"):
            raise ReplayManifestError("ReplayPack arrays must use the .npy container")
        for field, value in (
            ("dtype", self.dtype),
            # Traverse dtype, byte order and role explicitly so each replay array layout
            # post init iteration remains traceable.
            ("byte_order", self.byte_order),
            ("role", self.role),
        ):
            _require_token(value, field=field)
        _require_token(self.overflow_policy, field="overflow_policy")
        # Evaluate the complete replay array layout post init shape, size and isinstance
        # condition before guarded effects.
        if not self.shape or any(
            isinstance(size, bool) or not isinstance(size, int) or size < 0 for size in self.shape
        ):
            raise ReplayManifestError("array shape must contain non-negative dimensions")
        if self.validity_path is not None:
            # Handle the replay array layout post init self.validity_path is not None
            # branch as a distinct logical block.
            _require_relative_file(self.validity_path, field="validity_path")
            if self.validity_path == self.path:
                raise ReplayManifestError("an array cannot be its own validity bitmap")

    def schema_document(self) -> dict[str, object]:
        # Execute the replay array layout schema document workflow in explicit, reviewable
        # steps.
        return {
            "byte_order": self.byte_order,
            "dtype": self.dtype,
            "overflow_policy": self.overflow_policy,
            "path": self.path,
            # Include rank in the completed replay array layout schema document result.
            "rank": len(self.shape),
            "role": self.role,
            "validity_path": self.validity_path,
        }

    def document(self) -> dict[str, object]:
        # Return the completed replay array layout document result without a hidden
        # fallback.
        return {**self.schema_document(), "shape": list(self.shape)}

    @classmethod
    def from_document(cls, value: object) -> ReplayArrayLayout:
        # Execute the replay array layout from document workflow in explicit, reviewable
        # steps.
        document = _object(value, label="array layout")
        _exact_keys(
            document,
            {
                "dtype",
                # Pass byte order explicitly so _exact_keys receives a reviewable dtype
                # and byte order input in replay array layout from document.
                "byte_order",
                "overflow_policy",
                "path",
                "rank",
                "role",
                # Pass shape explicitly so _exact_keys receives a reviewable dtype and
                # byte order input in replay array layout from document.
                "shape",
                "validity_path",
            },
            label="array layout",
        )
        # Assemble shape once so the replay array layout from document workflow shares one
        # value.
        shape = tuple(
            _integer(item, field="array shape")
            for item in _sequence(document["shape"], field="shape")
        )
        rank = _integer(document["rank"], field="rank", minimum=1)
        # Guard this path with rank != len(shape) before applying effects.
        if rank != len(shape):
            raise ReplayManifestError("array rank does not match its shape")
        validity_value = document["validity_path"]
        if validity_value is not None and not isinstance(validity_value, str):
            raise ReplayManifestError("validity_path must be a string or null")
        # Return the completed replay array layout from document result without a hidden
        # fallback.
        return cls(
            path=_string(document["path"], field="array path"),
            dtype=_string(document["dtype"], field="dtype"),
            byte_order=_string(document["byte_order"], field="byte_order"),
            shape=shape,
            # Include role in the completed replay array layout from document result.
            role=_string(document["role"], field="role"),
            overflow_policy=_string(document["overflow_policy"], field="overflow_policy"),
            validity_path=validity_value,
        )


@dataclass(frozen=True, slots=True)
# Keep the replay dictionary layout contract and validation rules together.
class ReplayDictionaryLayout:
    """Deterministic UTF-8 dictionary represented by mmap byte/offset arrays."""

    name: str
    values_path: str
    offsets_path: str
    code_dtype: str
    count: int
    # Declare encoding explicitly in the replay dictionary layout contract.
    encoding: str = "utf-8"
    ordering: str = "utf8-byte-lexicographic-v1"

    def __post_init__(self) -> None:
        # Execute the replay dictionary layout post init workflow in explicit, reviewable
        # steps.
        _require_token(self.name, field="dictionary name")
        _require_relative_file(self.values_path, field="dictionary values_path")
        _require_relative_file(self.offsets_path, field="dictionary offsets_path")
        if self.values_path == self.offsets_path:
            raise ReplayManifestError("dictionary values and offsets must be separate")
        # Invoke _require_token for dictionary code dtype and code dtype as a visible
        # replay dictionary layout post init step.
        _require_token(self.code_dtype, field="dictionary code_dtype")
        _require_token(self.encoding, field="dictionary encoding")
        _require_token(self.ordering, field="dictionary ordering")
        if isinstance(self.count, bool) or not isinstance(self.count, int) or self.count < 0:
            raise ReplayManifestError("dictionary count must be non-negative")

    # Define replay dictionary layout schema document as one focused operation with an
    # explicit boundary.
    def schema_document(self) -> dict[str, object]:
        # Execute the replay dictionary layout schema document workflow in explicit,
        # reviewable steps.
        return {
            "code_dtype": self.code_dtype,
            "encoding": self.encoding,
            "name": self.name,
            "offsets_path": self.offsets_path,
            # Include ordering in the completed replay dictionary layout schema document
            # result.
            "ordering": self.ordering,
            "values_path": self.values_path,
        }

    def document(self) -> dict[str, object]:
        return {**self.schema_document(), "count": self.count}

    # Apply classmethod semantics to the following replay dictionary layout from document
    # contract.
    @classmethod
    def from_document(cls, value: object) -> ReplayDictionaryLayout:
        # Execute the replay dictionary layout from document workflow in explicit,
        # reviewable steps.
        document = _object(value, label="dictionary layout")
        _exact_keys(
            document,
            {
                "code_dtype",
                # Pass count explicitly so _exact_keys receives a reviewable code dtype
                # and count input in replay dictionary layout from document.
                "count",
                "encoding",
                "name",
                "offsets_path",
                "ordering",
                # Pass values path explicitly so _exact_keys receives a reviewable code
                # dtype and count input in replay dictionary layout from document.
                "values_path",
            },
            label="dictionary layout",
        )
        return cls(
            # Include name in the completed replay dictionary layout from document result.
            name=_string(document["name"], field="dictionary name"),
            values_path=_string(document["values_path"], field="values_path"),
            offsets_path=_string(document["offsets_path"], field="offsets_path"),
            code_dtype=_string(document["code_dtype"], field="code_dtype"),
            count=_integer(document["count"], field="dictionary count"),
            # Include encoding in the completed replay dictionary layout from document
            # result.
            encoding=_string(document["encoding"], field="dictionary encoding"),
            ordering=_string(document["ordering"], field="dictionary ordering"),
        )


@dataclass(frozen=True, slots=True)
class ReplayLayoutManifest:
    """Content-specific file shapes plus a content-independent physical schema ID."""

    arrays: tuple[ReplayArrayLayout, ...]
    dictionaries: tuple[ReplayDictionaryLayout, ...]
    container: str = "numpy-npy-v1"
    physical_byte_order: str = "little"
    nullable_encoding: str = "packed-lsb0-one-is-valid-v1"
    # Declare group index policy explicitly in the replay layout manifest contract.
    group_index_policy: str = "sentinel-offsets-contiguous-group-v1"
    boundary_index_policy: str = "sentinel-offsets-monotone-boundary-v1"
    layout_version: int = 3

    def __post_init__(self) -> None:
        # Execute the replay layout manifest post init workflow in explicit, reviewable
        # steps.
        if self.layout_version != 3:
            raise ReplayManifestError("only ReplayPack layout version 3 is supported")
        for field in (
            "container",
            "physical_byte_order",
            # Traverse container, physical byte order and nullable encoding explicitly so
            # each replay layout manifest post init iteration remains traceable.
            "nullable_encoding",
            "group_index_policy",
            "boundary_index_policy",
        ):
            _require_token(cast(str, getattr(self, field)), field=field)
        # Guard this path with not self.arrays before applying effects.
        if not self.arrays:
            raise ReplayManifestError("ReplayPack layout requires physical arrays")
        if tuple(sorted(self.arrays, key=lambda item: item.path)) != self.arrays:
            raise ReplayManifestError("array layouts must be sorted by path")
        paths = [item.path for item in self.arrays]
        # Guard this path with len(paths) != len(set(paths)) before applying effects.
        if len(paths) != len(set(paths)):
            raise ReplayManifestError("array paths must be unique")
        path_set = set(paths)
        for item in self.arrays:
            # Process self.arrays inside the bounded replay layout manifest post init
            # loop.
            if item.validity_path is not None and item.validity_path not in path_set:
                raise ReplayManifestError("array validity path is not declared")
        if tuple(sorted(self.dictionaries, key=lambda item: item.name)) != self.dictionaries:
            raise ReplayManifestError("dictionary layouts must be sorted by name")
        names = [item.name for item in self.dictionaries]
        # Guard this path with len(names) != len(set(names)) before applying effects.
        if len(names) != len(set(names)):
            raise ReplayManifestError("dictionary names must be unique")
        for dictionary in self.dictionaries:
            # Process self.dictionaries inside the bounded replay layout manifest post
            # init loop.
            if {dictionary.values_path, dictionary.offsets_path} - path_set:
                raise ReplayManifestError("dictionary array path is not declared")

    def schema_document(self) -> dict[str, object]:
        # Execute the replay layout manifest schema document workflow in explicit,
        # reviewable steps.
        return {
            "arrays": [item.schema_document() for item in self.arrays],
            "boundary_index_policy": self.boundary_index_policy,
            "container": self.container,
            "dictionaries": [item.schema_document() for item in self.dictionaries],
            # Include group index policy in the completed replay layout manifest schema
            # document result.
            "group_index_policy": self.group_index_policy,
            "layout_version": self.layout_version,
            "nullable_encoding": self.nullable_encoding,
            "physical_byte_order": self.physical_byte_order,
        }

    # Apply property semantics to the following replay layout manifest replay layout
    # schema id contract.
    @property
    def replay_layout_schema_id(self) -> ContentDigest:
        return domain_digest("backtest.replay-layout-schema.v3", self.schema_document())

    def document(self) -> dict[str, object]:
        # Execute the replay layout manifest document workflow in explicit, reviewable
        # steps.
        return {
            "arrays": [item.document() for item in self.arrays],
            "boundary_index_policy": self.boundary_index_policy,
            "container": self.container,
            "dictionaries": [item.document() for item in self.dictionaries],
            # Include group index policy in the completed replay layout manifest document
            # result.
            "group_index_policy": self.group_index_policy,
            "layout_version": self.layout_version,
            "nullable_encoding": self.nullable_encoding,
            "physical_byte_order": self.physical_byte_order,
            "replay_layout_schema_id": self.replay_layout_schema_id.hex,
            # Return the completed replay layout manifest document result without a hidden
            # fallback.
        }

    @classmethod
    def from_document(cls, value: object) -> ReplayLayoutManifest:
        # Execute the replay layout manifest from document workflow in explicit,
        # reviewable steps.
        document = _object(value, label="replay layout")
        _exact_keys(
            document,
            {
                "arrays",
                # Pass boundary index policy explicitly so _exact_keys receives a
                # reviewable arrays and boundary index policy input in replay layout
                # manifest from document.
                "boundary_index_policy",
                "container",
                "dictionaries",
                "group_index_policy",
                "layout_version",
                # Pass nullable encoding explicitly so _exact_keys receives a reviewable
                # arrays and boundary index policy input in replay layout manifest from
                # document.
                "nullable_encoding",
                "physical_byte_order",
                "replay_layout_schema_id",
            },
            label="replay layout",
            # Complete _exact_keys only after its arrays and boundary index policy inputs are
            # visible in replay layout manifest from document.
        )
        result = cls(
            arrays=tuple(
                ReplayArrayLayout.from_document(item)
                for item in _sequence(document["arrays"], field="arrays")
                # Complete tuple only after its arrays and from document inputs are visible in
                # replay layout manifest from document.
            ),
            dictionaries=tuple(
                ReplayDictionaryLayout.from_document(item)
                for item in _sequence(document["dictionaries"], field="dictionaries")
            ),
            # Keep the string and document _string step visible while building result.
            container=_string(document["container"], field="container"),
            physical_byte_order=_string(
                document["physical_byte_order"], field="physical_byte_order"
            ),
            nullable_encoding=_string(document["nullable_encoding"], field="nullable_encoding"),
            # Keep the string and document _string step visible while building result.
            group_index_policy=_string(document["group_index_policy"], field="group_index_policy"),
            boundary_index_policy=_string(
                document["boundary_index_policy"], field="boundary_index_policy"
            ),
            layout_version=_integer(document["layout_version"], field="layout_version", minimum=1),
            # Complete cls only after its arrays and dictionaries inputs are visible in replay
            # layout manifest from document.
        )
        stored_id = ContentDigest(_string(document["replay_layout_schema_id"], field="id"))
        if stored_id.hex != result.replay_layout_schema_id.hex:
            raise ReplayManifestError("replay layout schema ID does not match its document")
        return result


# Apply dataclass semantics to the following replay build manifest contract.
@dataclass(frozen=True, slots=True)
class ReplayBuildManifest:
    """Derivation lookup identity; deliberately excluded from content identity."""

    snapshot_id: SnapshotId
    replay_semantics_id: ContentDigest
    replay_layout_schema_id: ContentDigest
    compiler_bundle_id: BundleId
    writer_bundle_id: BundleId
    # Declare runtime lock id explicitly in the replay build manifest contract.
    runtime_lock_id: RuntimeLockId
    writer_settings_digest: ContentDigest
    compiler_version: str

    def __post_init__(self) -> None:
        _require_token(self.compiler_version, field="compiler_version")

    # Define replay build manifest identity document as one focused operation with an
    # explicit boundary.
    def identity_document(self) -> dict[str, object]:
        # Execute the replay build manifest identity document workflow in explicit,
        # reviewable steps.
        return {
            "compiler_bundle_id": self.compiler_bundle_id.hex,
            "compiler_version": self.compiler_version,
            "replay_layout_schema_id": self.replay_layout_schema_id.hex,
            "replay_semantics_id": self.replay_semantics_id.hex,
            # Include runtime lock id in the completed replay build manifest identity
            # document result.
            "runtime_lock_id": self.runtime_lock_id.hex,
            "snapshot_id": self.snapshot_id.hex,
            "writer_bundle_id": self.writer_bundle_id.hex,
            "writer_settings_digest": self.writer_settings_digest.hex,
        }

    # Apply property semantics to the following replay build manifest replay build key
    # contract.
    @property
    def replay_build_key(self) -> ContentDigest:
        return domain_digest("backtest.replay-build.v1", self.identity_document())

    def document(self) -> dict[str, object]:
        return {**self.identity_document(), "replay_build_key": self.replay_build_key.hex}

    # Apply classmethod semantics to the following replay build manifest from document
    # contract.
    @classmethod
    def from_document(cls, value: object) -> ReplayBuildManifest:
        # Execute the replay build manifest from document workflow in explicit, reviewable
        # steps.
        document = _object(value, label="replay build")
        _exact_keys(
            document,
            {
                "compiler_bundle_id",
                # Pass compiler version explicitly so _exact_keys receives a reviewable
                # compiler bundle id and compiler version input in replay build manifest
                # from document.
                "compiler_version",
                "replay_build_key",
                "replay_layout_schema_id",
                "replay_semantics_id",
                "runtime_lock_id",
                # Pass snapshot id explicitly so _exact_keys receives a reviewable
                # compiler bundle id and compiler version input in replay build manifest
                # from document.
                "snapshot_id",
                "writer_bundle_id",
                "writer_settings_digest",
            },
            label="replay build",
            # Complete _exact_keys only after its compiler bundle id and compiler version
            # inputs are visible in replay build manifest from document.
        )
        result = cls(
            snapshot_id=SnapshotId(_string(document["snapshot_id"], field="snapshot_id")),
            replay_semantics_id=ContentDigest(
                _string(document["replay_semantics_id"], field="replay_semantics_id")
                # Complete ContentDigest only after its replay semantics id and string inputs
                # are visible in replay build manifest from document.
            ),
            replay_layout_schema_id=ContentDigest(
                _string(document["replay_layout_schema_id"], field="replay_layout_schema_id")
            ),
            compiler_bundle_id=BundleId(
                # Keep the string and document _string step visible while building result.
                _string(document["compiler_bundle_id"], field="compiler_bundle_id")
            ),
            writer_bundle_id=BundleId(
                _string(document["writer_bundle_id"], field="writer_bundle_id")
            ),
            # Keep the runtime lock id and string RuntimeLockId step visible while
            # building result.
            runtime_lock_id=RuntimeLockId(
                _string(document["runtime_lock_id"], field="runtime_lock_id")
            ),
            writer_settings_digest=ContentDigest(
                _string(document["writer_settings_digest"], field="writer_settings_digest")
                # Complete ContentDigest only after its writer settings digest and string
                # inputs are visible in replay build manifest from document.
            ),
            compiler_version=_string(document["compiler_version"], field="compiler_version"),
        )
        stored_key = ContentDigest(_string(document["replay_build_key"], field="build key"))
        if stored_key.hex != result.replay_build_key.hex:
            # Fail the replay build manifest from document path with ReplayManifestError
            # for replay build key does not match its document when hex, stored key and
            # replay build key is true; do not continue ambiguously.
            raise ReplayManifestError("replay build key does not match its document")
        return result


# Keep the replay payload counts contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ReplayPayloadCounts:
    blocks: int
    token_launches: int
    venue_trades: int
    # Declare venue lifecycles explicitly in the replay payload counts contract.
    venue_lifecycles: int
    fee_components: int

    def __post_init__(self) -> None:
        # Execute the replay payload counts post init workflow in explicit, reviewable
        # steps.
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in (
                self.blocks,
                self.token_launches,
                # Pass self explicitly so any receives a reviewable blocks and token
                # launches input in replay payload counts post init.
                self.venue_trades,
                self.venue_lifecycles,
                self.fee_components,
            )
        ):
            # Fail the replay payload counts post init path with ReplayManifestError for
            # payload counts must be non-negative integers when value, isinstance and
            # blocks is true; do not continue ambiguously.
            raise ReplayManifestError("payload counts must be non-negative integers")

    @property
    def total(self) -> int:
        return self.blocks + self.token_launches + self.venue_trades + self.venue_lifecycles

    def document(self) -> dict[str, object]:
        # Execute the replay payload counts document workflow in explicit, reviewable
        # steps.
        return {
            "blocks": self.blocks,
            "fee_components": self.fee_components,
            "token_launches": self.token_launches,
            "venue_lifecycles": self.venue_lifecycles,
            # Include venue trades in the completed replay payload counts document result.
            "venue_trades": self.venue_trades,
        }

    @classmethod
    def from_document(cls, value: object) -> ReplayPayloadCounts:
        # Execute the replay payload counts from document workflow in explicit, reviewable
        # steps.
        document = _object(value, label="payload counts")
        _exact_keys(
            document,
            {
                "blocks",
                # Pass fee components explicitly so _exact_keys receives a reviewable
                # blocks and fee components input in replay payload counts from document.
                "fee_components",
                "token_launches",
                "venue_lifecycles",
                "venue_trades",
            },
            # Pass label explicitly so _exact_keys receives a reviewable blocks and fee
            # components input in replay payload counts from document.
            label="payload counts",
        )
        return cls(
            blocks=_integer(document["blocks"], field="blocks"),
            token_launches=_integer(document["token_launches"], field="token_launches"),
            # Include venue trades in the completed replay payload counts from document
            # result.
            venue_trades=_integer(document["venue_trades"], field="venue_trades"),
            venue_lifecycles=_integer(document["venue_lifecycles"], field="venue_lifecycles"),
            fee_components=_integer(document["fee_components"], field="fee_components"),
        )


@dataclass(frozen=True, slots=True)
# Keep the replay pack manifest contract and validation rules together.
class ReplayPackManifest:
    """Root manifest split into content identity and operational build provenance."""

    snapshot_id: SnapshotId
    dataset_revision_id: DatasetRevisionId
    network_id: NetworkId
    position_schema_id: PositionSchemaId
    decision_range: BlockRange
    # Declare dataset spec explicitly in the replay pack manifest contract.
    dataset_spec: DatasetSpec
    logical_content_hash: LogicalContentHash
    logical_output_stream_hash: LogicalContentHash
    source_boundaries: tuple[EffectiveSourceBoundary, ...]
    semantics: ReplaySemanticsManifest
    # Declare layout explicitly in the replay pack manifest contract.
    layout: ReplayLayoutManifest
    build: ReplayBuildManifest
    event_count: int
    boundary_count: int
    group_count: int
    # Declare payload counts explicitly in the replay pack manifest contract.
    payload_counts: ReplayPayloadCounts
    artifact_schema: str = "replay-pack/v3"
    rebuildability: str = "REBUILDABLE"

    def __post_init__(self) -> None:
        # Execute the replay pack manifest post init workflow in explicit, reviewable
        # steps.
        if self.artifact_schema != "replay-pack/v3":
            raise ReplayManifestError("unsupported ReplayPack artifact schema")
        if self.rebuildability != "REBUILDABLE":
            raise ReplayManifestError("ReplayPack v3 must be rebuildable")
        if not isinstance(self.network_id, NetworkId):
            # Fail the replay pack manifest post init path with TypeError for network id
            # must be a network id when isinstance and network id is true; do not continue
            # ambiguously.
            raise TypeError("network_id must be a NetworkId")
        if not isinstance(self.position_schema_id, PositionSchemaId):
            raise TypeError("position_schema_id must be a PositionSchemaId")
        if not isinstance(self.decision_range, BlockRange):
            raise TypeError("decision_range must be a BlockRange")
        # Evaluate the complete replay pack manifest post init isinstance and dataset spec
        # condition before guarded effects.
        if not isinstance(self.dataset_spec, DatasetSpec):
            raise TypeError("dataset_spec must be a DatasetSpec")
        if (
            self.decision_range.network_id != self.network_id
            or self.decision_range.position_schema_id != self.position_schema_id
            # Evaluate the complete replay pack manifest post init network id, position schema
            # id and decision range condition before guarded effects.
        ):
            raise ReplayManifestError("ReplayPack decision range uses another chain identity")
        if (
            self.dataset_spec.network_id != self.network_id
            or self.dataset_spec.position_schema_id != self.position_schema_id
            # Keep self visible while evaluating the network id, position schema id and
            # decision range guard.
            or self.dataset_spec.decision_range != self.decision_range
        ):
            # Handle the replay pack manifest post init network id, position schema id and
            # decision range condition as a distinct block.
            raise ReplayManifestError(
                "ReplayPack DatasetSpec differs from its chain identity or decision range"
            )
        if not self.source_boundaries:
            raise ReplayManifestError("ReplayPack must preserve source fidelity boundaries")
        # Evaluate the complete replay pack manifest post init validation status, pass and
        # item condition before guarded effects.
        if any(
            item.source_boundary.validation_status is not ValidationStatus.PASS
            for item in self.source_boundaries
        ):
            raise ReplayManifestError("ReplayPack source boundaries must be validated")
        # Assemble boundary identities once so the replay pack manifest post init workflow
        # shares one value.
        boundary_identities = tuple(
            (
                item.source_boundary.source_id,
                item.source_boundary.capability_id,
                item.source_boundary.capability_schema_version,
                # Pass item explicitly so tuple receives a reviewable source id and
                # capability id input in replay pack manifest post init.
                item.source_boundary.block_range,
            )
            for item in self.source_boundaries
        )
        if len(boundary_identities) != len(set(boundary_identities)):
            # Fail the replay pack manifest post init path with ReplayManifestError for
            # replay pack source boundary identities must be unique when boundary
            # identities is true; do not continue ambiguously.
            raise ReplayManifestError("ReplayPack source boundary identities must be unique")
        if self.event_count <= 0 or self.boundary_count <= 0 or self.group_count <= 0:
            raise ReplayManifestError("ReplayPack counts must be positive")
        if self.payload_counts.total != self.event_count:
            raise ReplayManifestError("payload counts do not cover the envelope stream")
        # Evaluate the complete replay pack manifest post init logical output stream hash
        # and logical content hash condition before guarded effects.
        if self.logical_output_stream_hash != self.logical_content_hash:
            raise ReplayManifestError("ReplayPack logical stream must equal snapshot content")
        if self.build.snapshot_id != self.snapshot_id:
            raise ReplayManifestError("build manifest references another snapshot")
        if self.build.replay_semantics_id != self.semantics.replay_semantics_id:
            # Fail the replay pack manifest post init path with ReplayManifestError for
            # build and content replay semantics differ when replay semantics id, build
            # and semantics is true; do not continue ambiguously.
            raise ReplayManifestError("build and content replay semantics differ")
        if self.build.replay_layout_schema_id != self.layout.replay_layout_schema_id:
            raise ReplayManifestError("build and content layout schema differ")
        if any(
            item.source_boundary.block_range.network_id != self.network_id
            # Pass item explicitly so any receives a reviewable source boundaries and
            # network id input in replay pack manifest post init.
            or item.source_boundary.block_range.position_schema_id != self.position_schema_id
            for item in self.source_boundaries
        ):
            raise ReplayManifestError("ReplayPack source boundaries use another chain identity")

    def identity_document(self) -> dict[str, object]:
        # Execute the replay pack manifest identity document workflow in explicit,
        # reviewable steps.
        return {
            "artifact_schema": self.artifact_schema,
            "boundary_count": self.boundary_count,
            "dataset_revision_id": self.dataset_revision_id.hex,
            "dataset_spec": dataset_spec_document(self.dataset_spec),
            # Include decision range in the completed replay pack manifest identity
            # document result.
            "decision_range": _block_range_document(self.decision_range),
            "event_count": self.event_count,
            "group_count": self.group_count,
            "layout": self.layout.document(),
            "logical_content_hash": self.logical_content_hash.hex,
            # Include logical output stream hash in the completed replay pack manifest
            # identity document result.
            "logical_output_stream_hash": self.logical_output_stream_hash.hex,
            "network_id": self.network_id.value,
            "payload_counts": self.payload_counts.document(),
            "position_schema_id": self.position_schema_id.value,
            "rebuildability": self.rebuildability,
            # Include semantics in the completed replay pack manifest identity document
            # result.
            "semantics": self.semantics.document(),
            "source_boundaries": [item.identity_document() for item in self.source_boundaries],
            "snapshot_id": self.snapshot_id.hex,
        }

    def document(self) -> dict[str, object]:
        # Return the completed replay pack manifest document result without a hidden
        # fallback.
        return {**self.identity_document(), "build": self.build.document()}

    @classmethod
    def from_document(cls, value: object) -> ReplayPackManifest:
        # Execute the replay pack manifest from document workflow in explicit, reviewable
        # steps.
        document = _object(value, label="ReplayPack manifest")
        artifact_schema = document.get("artifact_schema")
        if artifact_schema in {"replay-pack/v1", "replay-pack/v2"}:
            raise ReprepareRequiredError(artifact_schema)
        if artifact_schema != "replay-pack/v3":
            # Fail the replay pack manifest from document path with ReplayManifestError
            # for unsupported replay pack artifact schema when artifact schema is true; do
            # not continue ambiguously.
            raise ReplayManifestError("unsupported ReplayPack artifact schema")
        _exact_keys(
            document,
            {
                "artifact_schema",
                # Pass boundary count explicitly so _exact_keys receives a reviewable
                # artifact schema and boundary count input in replay pack manifest from
                # document.
                "boundary_count",
                "build",
                "dataset_revision_id",
                "dataset_spec",
                "decision_range",
                # Pass event count explicitly so _exact_keys receives a reviewable
                # artifact schema and boundary count input in replay pack manifest from
                # document.
                "event_count",
                "group_count",
                "layout",
                "logical_content_hash",
                "logical_output_stream_hash",
                # Pass network id explicitly so _exact_keys receives a reviewable artifact
                # schema and boundary count input in replay pack manifest from document.
                "network_id",
                "payload_counts",
                "position_schema_id",
                "rebuildability",
                "semantics",
                # Pass source boundaries explicitly so _exact_keys receives a reviewable
                # artifact schema and boundary count input in replay pack manifest from
                # document.
                "source_boundaries",
                "snapshot_id",
            },
            label="ReplayPack manifest",
        )
        # Return the completed replay pack manifest from document result without a hidden
        # fallback.
        return cls(
            snapshot_id=SnapshotId(_string(document["snapshot_id"], field="snapshot_id")),
            dataset_revision_id=DatasetRevisionId(
                _string(document["dataset_revision_id"], field="dataset_revision_id")
            ),
            # Include network id in the completed replay pack manifest from document
            # result.
            network_id=NetworkId(_string(document["network_id"], field="network_id")),
            position_schema_id=PositionSchemaId(
                _string(document["position_schema_id"], field="position_schema_id")
            ),
            decision_range=_block_range_from_document(document["decision_range"]),
            # Include dataset spec in the completed replay pack manifest from document
            # result.
            dataset_spec=dataset_spec_from_document(document["dataset_spec"]),
            logical_content_hash=LogicalContentHash(
                _string(document["logical_content_hash"], field="logical_content_hash")
            ),
            logical_output_stream_hash=LogicalContentHash(
                # Include string in the completed replay pack manifest from document
                # result.
                _string(
                    document["logical_output_stream_hash"],
                    field="logical_output_stream_hash",
                )
            ),
            # Include source boundaries in the completed replay pack manifest from
            # document result.
            source_boundaries=tuple(
                EffectiveSourceBoundary.from_document(item)
                for item in _sequence(document["source_boundaries"], field="source_boundaries")
            ),
            semantics=ReplaySemanticsManifest.from_document(document["semantics"]),
            # Include layout in the completed replay pack manifest from document result.
            layout=ReplayLayoutManifest.from_document(document["layout"]),
            build=ReplayBuildManifest.from_document(document["build"]),
            event_count=_integer(document["event_count"], field="event_count", minimum=1),
            boundary_count=_integer(document["boundary_count"], field="boundary_count", minimum=1),
            group_count=_integer(document["group_count"], field="group_count", minimum=1),
            # Include payload counts in the completed replay pack manifest from document
            # result.
            payload_counts=ReplayPayloadCounts.from_document(document["payload_counts"]),
            artifact_schema=_string(document["artifact_schema"], field="artifact_schema"),
            rebuildability=_string(document["rebuildability"], field="rebuildability"),
        )


# Keep the compiled replay pack contract and validation rules together.
@dataclass(frozen=True, slots=True)
class CompiledReplayPack:
    artifact: CommittedArtifact
    replay_pack_id: ReplayPackId
    manifest: ReplayPackManifest
    # Declare requested build explicitly in the compiled replay pack contract.
    requested_build: ReplayBuildManifest

    def __post_init__(self) -> None:
        # Execute the compiled replay pack post init workflow in explicit, reviewable
        # steps.
        if self.artifact.kind is not ArtifactKind.REPLAY_PACK:
            raise ReplayManifestError("compiled artifact is not a ReplayPack")
        if self.replay_pack_id.hex != self.artifact.artifact_id.hex:
            raise ReplayManifestError("ReplayPack ID must equal committed artifact ID")
        if (
            # Keep self visible while evaluating the snapshot id, replay semantics id and
            # replay layout schema id guard.
            self.requested_build.snapshot_id != self.manifest.snapshot_id
            or self.requested_build.replay_semantics_id
            != self.manifest.semantics.replay_semantics_id
            or self.requested_build.replay_layout_schema_id
            != self.manifest.layout.replay_layout_schema_id
            # Evaluate the complete compiled replay pack post init snapshot id, replay
            # semantics id and replay layout schema id condition before guarded effects.
        ):
            raise ReplayManifestError("requested build does not derive this ReplayPack content")

    @property
    def replay_build_key(self) -> ContentDigest:
        return self.requested_build.replay_build_key


# Bind all once as an explicit module-level contract.
__all__ = [
    "CompiledReplayPack",
    "ReplayArrayLayout",
    "ReplayBuildManifest",
    "ReplayDictionaryLayout",
    # Keep the replay layout manifest component named inside the all contract.
    "ReplayLayoutManifest",
    "ReplayManifestError",
    "ReplayPackManifest",
    "ReplayPayloadCounts",
    "ReplaySemanticsManifest",
    # Complete the all group only after its semantic components are visible.
]
