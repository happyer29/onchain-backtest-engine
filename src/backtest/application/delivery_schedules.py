"""Typed identities and manifests for materialized observation delivery streams."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import cast

from backtest.application.errors import ReprepareRequiredError

# Import models at the visible module dependency boundary.
from backtest.application.models import ArtifactKind, CommittedArtifact
from backtest.application.replay_packs import ReplayArrayLayout
from backtest.application.run_specs import ResolvedComponent
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import (
    # Include bundle id so the identifiers dependency remains explicit.
    BundleId,
    ContentDigest,
    DeliveryScheduleId,
    NetworkId,
    PositionSchemaId,
    # Include replay pack id so the identifiers dependency remains explicit.
    ReplayPackId,
    RuntimeLockId,
)
from backtest.domain.time import BlockRange
from backtest.engine.replay import ObservationDelivery

# Bind required component roles once as an explicit module-level contract.
_REQUIRED_COMPONENT_ROLES = ("clock", "engine", "latency", "scheduler")
_DELIVERY_STREAM_DOMAIN = b"backtest.logical-delivery-stream.v1\x00"


class DeliveryManifestError(ValueError):
    """A delivery manifest is malformed or internally inconsistent."""


def _object(value: object, label: str) -> dict[str, object]:
    # Execute the object workflow in explicit, reviewable steps.
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise DeliveryManifestError(f"{label} must be a JSON object")
    return cast(dict[str, object], value)


def _keys(value: dict[str, object], expected: set[str], label: str) -> None:
    # Execute the keys workflow in explicit, reviewable steps.
    if set(value) != expected:
        raise DeliveryManifestError(f"{label} schema is invalid")


def _string(value: object, field: str) -> str:
    # Execute the string workflow in explicit, reviewable steps.
    if not isinstance(value, str) or not value or value != value.strip():
        raise DeliveryManifestError(f"{field} must be a non-empty trimmed string")
    return value


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    # Execute the integer workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise DeliveryManifestError(f"{field} must be an integer >= {minimum}")
    return value


def _list(value: object, field: str) -> list[object]:
    # Execute the list workflow in explicit, reviewable steps.
    if not isinstance(value, list):
        raise DeliveryManifestError(f"{field} must be a list")
    return cast(list[object], value)


def _range_document(value: BlockRange) -> dict[str, object]:
    # Execute the range document workflow in explicit, reviewable steps.
    return {
        "from_block_ordinal": value.from_block_ordinal,
        "network_id": value.network_id.value,
        "position_schema_id": value.position_schema_id.value,
        "to_block_ordinal": value.to_block_ordinal,
        # Return the completed range document result without a hidden fallback.
    }


def _range_from_document(value: object) -> BlockRange:
    # Execute the range from document workflow in explicit, reviewable steps.
    document = _object(value, "delivery decision range")
    _keys(
        document,
        {
            "from_block_ordinal",
            # Pass network id explicitly so _keys receives a reviewable from block ordinal
            # and network id input in range from document.
            "network_id",
            "position_schema_id",
            "to_block_ordinal",
        },
        "delivery decision range",
        # Complete _keys only after its from block ordinal and network id inputs are visible
        # in range from document.
    )
    return BlockRange(
        network_id=NetworkId(_string(document["network_id"], "network_id")),
        position_schema_id=PositionSchemaId(
            _string(document["position_schema_id"], "position_schema_id")
            # Complete PositionSchemaId only after its position schema id and string inputs
            # are visible in range from document.
        ),
        from_block_ordinal=_integer(document["from_block_ordinal"], "from_block_ordinal"),
        to_block_ordinal=_integer(document["to_block_ordinal"], "to_block_ordinal"),
    )


def _component_from_document(value: object) -> ResolvedComponent:
    # Execute the component from document workflow in explicit, reviewable steps.
    document = _object(value, "resolved delivery component")
    _keys(
        document,
        {"api_version", "bundle_id", "config", "config_digest", "role"},
        "resolved delivery component",
        # Complete _keys only after its api version and bundle id inputs are visible in
        # component from document.
    )
    config = _object(document["config"], "resolved delivery component config")
    component = ResolvedComponent.create(
        role=_string(document["role"], "component role"),
        bundle_id=BundleId(_string(document["bundle_id"], "component bundle_id")),
        # Pass config explicitly so create receives a reviewable component role and role
        # input in component from document.
        config=config,
        api_version=_integer(document["api_version"], "component api_version", minimum=1),
    )
    stored_digest = ContentDigest(_string(document["config_digest"], "component config_digest"))
    if stored_digest.hex != component.config_digest.hex:
        # Fail the component from document path with DeliveryManifestError for component
        # config digest does not match its config when hex, stored digest and config
        # digest is true; do not continue ambiguously.
        raise DeliveryManifestError("component config digest does not match its config")
    return component


def _validate_components(components: tuple[ResolvedComponent, ...]) -> None:
    # Execute the validate components workflow in explicit, reviewable steps.
    if tuple(sorted(components, key=lambda item: item.role)) != components:
        raise DeliveryManifestError("delivery components must be sorted by role")
    roles = tuple(item.role for item in components)
    if roles != _REQUIRED_COMPONENT_ROLES:
        raise DeliveryManifestError("delivery components must be clock/engine/latency/scheduler")


# Keep the compile delivery schedule request contract and validation rules together.
@dataclass(frozen=True, slots=True)
class CompileDeliveryScheduleRequest:
    replay_pack_id: ReplayPackId
    replay_semantics_id: ContentDigest
    replay_layout_schema_id: ContentDigest
    # Declare components explicitly in the compile delivery schedule request contract.
    components: tuple[ResolvedComponent, ...]
    rng_algorithm: str
    root_seed: int
    compiler_version: str

    def __post_init__(self) -> None:
        # Execute the compile delivery schedule request post init workflow in explicit,
        # reviewable steps.
        _validate_components(self.components)
        _string(self.rng_algorithm, "rng_algorithm")
        _string(self.compiler_version, "compiler_version")
        if (
            isinstance(self.root_seed, bool)
            # Keep isinstance visible while evaluating the isinstance and root seed guard.
            or not isinstance(self.root_seed, int)
            or not 0 <= self.root_seed < 1 << 256
        ):
            raise DeliveryManifestError("root_seed must be an unsigned 256-bit integer")

    def component(self, role: str) -> ResolvedComponent:
        # Execute the compile delivery schedule request component workflow in explicit,
        # reviewable steps.
        try:
            return next(item for item in self.components if item.role == role)
        except StopIteration as error:  # pragma: no cover - __post_init__ proves closure
            raise AssertionError(f"missing resolved delivery component {role}") from error


# Keep the delivery layout manifest contract and validation rules together.
@dataclass(frozen=True, slots=True)
class DeliveryLayoutManifest:
    arrays: tuple[ReplayArrayLayout, ...]
    container: str = "numpy-npy-v1"
    layout_version: int = 1
    # Declare ordering explicitly in the delivery layout manifest contract.
    ordering: str = "release-source-stable-v1"
    physical_byte_order: str = "little"

    def __post_init__(self) -> None:
        # Execute the delivery layout manifest post init workflow in explicit, reviewable
        # steps.
        if self.layout_version != 1:
            raise DeliveryManifestError("only delivery layout version 1 is supported")
        if tuple(sorted(self.arrays, key=lambda item: item.path)) != self.arrays:
            raise DeliveryManifestError("delivery arrays must be sorted by path")
        if not self.arrays or len({item.path for item in self.arrays}) != len(self.arrays):
            # Fail the delivery layout manifest post init path with DeliveryManifestError
            # for delivery arrays must be non-empty and unique when arrays, path and item
            # is true; do not continue ambiguously.
            raise DeliveryManifestError("delivery arrays must be non-empty and unique")
        for field, value in (
            ("container", self.container),
            ("ordering", self.ordering),
            ("physical_byte_order", self.physical_byte_order),
            # Traverse container, ordering and physical byte order explicitly so each delivery
            # layout manifest post init iteration remains traceable.
        ):
            _string(value, field)

    def schema_document(self) -> dict[str, object]:
        # Execute the delivery layout manifest schema document workflow in explicit,
        # reviewable steps.
        return {
            "arrays": [item.schema_document() for item in self.arrays],
            "container": self.container,
            "layout_version": self.layout_version,
            "ordering": self.ordering,
            # Include physical byte order in the completed delivery layout manifest schema
            # document result.
            "physical_byte_order": self.physical_byte_order,
        }

    @property
    def delivery_layout_schema_id(self) -> ContentDigest:
        return domain_digest("backtest.delivery-layout-schema.v1", self.schema_document())

    # Define delivery layout manifest document as one focused operation with an explicit
    # boundary.
    def document(self) -> dict[str, object]:
        # Execute the delivery layout manifest document workflow in explicit, reviewable
        # steps.
        return {
            "arrays": [item.document() for item in self.arrays],
            "container": self.container,
            "delivery_layout_schema_id": self.delivery_layout_schema_id.hex,
            "layout_version": self.layout_version,
            # Include ordering in the completed delivery layout manifest document result.
            "ordering": self.ordering,
            "physical_byte_order": self.physical_byte_order,
        }

    @classmethod
    def from_document(cls, value: object) -> DeliveryLayoutManifest:
        # Execute the delivery layout manifest from document workflow in explicit,
        # reviewable steps.
        document = _object(value, "delivery layout")
        _keys(
            document,
            {
                "arrays",
                # Pass container explicitly so _keys receives a reviewable arrays and
                # container input in delivery layout manifest from document.
                "container",
                "delivery_layout_schema_id",
                "layout_version",
                "ordering",
                "physical_byte_order",
                # Close the arrays and container payload only after all delivery layout
                # manifest from document fields are present.
            },
            "delivery layout",
        )
        result = cls(
            arrays=tuple(
                # Keep the item from_document step visible while building result.
                ReplayArrayLayout.from_document(item)
                for item in _list(document["arrays"], "delivery arrays")
            ),
            container=_string(document["container"], "container"),
            layout_version=_integer(document["layout_version"], "layout_version", minimum=1),
            # Keep the string and ordering _string step visible while building result.
            ordering=_string(document["ordering"], "ordering"),
            physical_byte_order=_string(document["physical_byte_order"], "physical_byte_order"),
        )
        stored_id = ContentDigest(
            _string(document["delivery_layout_schema_id"], "delivery_layout_schema_id")
            # Complete ContentDigest only after its delivery layout schema id and string
            # inputs are visible in delivery layout manifest from document.
        )
        if stored_id.hex != result.delivery_layout_schema_id.hex:
            raise DeliveryManifestError("delivery layout schema ID mismatch")
        return result


# Keep the delivery build manifest contract and validation rules together.
@dataclass(frozen=True, slots=True)
class DeliveryBuildManifest:
    replay_pack_id: ReplayPackId
    replay_semantics_id: ContentDigest
    replay_layout_schema_id: ContentDigest
    # Declare components explicitly in the delivery build manifest contract.
    components: tuple[ResolvedComponent, ...]
    rng_algorithm: str
    root_seed: int
    compiler_bundle_id: BundleId
    compiler_version: str
    # Declare writer bundle id explicitly in the delivery build manifest contract.
    writer_bundle_id: BundleId
    runtime_lock_id: RuntimeLockId
    writer_settings_digest: ContentDigest

    def __post_init__(self) -> None:
        # Execute the delivery build manifest post init workflow in explicit, reviewable
        # steps.
        _validate_components(self.components)
        _string(self.rng_algorithm, "rng_algorithm")
        _string(self.compiler_version, "compiler_version")
        if (
            isinstance(self.root_seed, bool)
            # Keep isinstance visible while evaluating the isinstance and root seed guard.
            or not isinstance(self.root_seed, int)
            or not 0 <= self.root_seed < 1 << 256
        ):
            raise DeliveryManifestError("root_seed must be an unsigned 256-bit integer")

    def identity_document(self) -> dict[str, object]:
        # Execute the delivery build manifest identity document workflow in explicit,
        # reviewable steps.
        return {
            "compiler_bundle_id": self.compiler_bundle_id.hex,
            "compiler_version": self.compiler_version,
            "components": [item.identity_document() for item in self.components],
            "replay_layout_schema_id": self.replay_layout_schema_id.hex,
            # Include replay pack id in the completed delivery build manifest identity
            # document result.
            "replay_pack_id": self.replay_pack_id.hex,
            "replay_semantics_id": self.replay_semantics_id.hex,
            "rng_algorithm": self.rng_algorithm,
            "root_seed": self.root_seed,
            "runtime_lock_id": self.runtime_lock_id.hex,
            # Include writer bundle id in the completed delivery build manifest identity
            # document result.
            "writer_bundle_id": self.writer_bundle_id.hex,
            "writer_settings_digest": self.writer_settings_digest.hex,
        }

    @property
    def delivery_build_key(self) -> ContentDigest:
        # Return the completed delivery build manifest delivery build key result without a
        # hidden fallback.
        return domain_digest("backtest.delivery-build.v1", self.identity_document())

    def document(self) -> dict[str, object]:
        return {**self.identity_document(), "delivery_build_key": self.delivery_build_key.hex}

    @classmethod
    def from_document(cls, value: object) -> DeliveryBuildManifest:
        # Execute the delivery build manifest from document workflow in explicit,
        # reviewable steps.
        document = _object(value, "delivery build")
        _keys(
            document,
            {
                "compiler_bundle_id",
                # Pass compiler version explicitly so _keys receives a reviewable compiler
                # bundle id and compiler version input in delivery build manifest from
                # document.
                "compiler_version",
                "components",
                "delivery_build_key",
                "replay_layout_schema_id",
                "replay_pack_id",
                # Pass replay semantics id explicitly so _keys receives a reviewable
                # compiler bundle id and compiler version input in delivery build manifest
                # from document.
                "replay_semantics_id",
                "rng_algorithm",
                "root_seed",
                "runtime_lock_id",
                "writer_bundle_id",
                # Pass writer settings digest explicitly so _keys receives a reviewable
                # compiler bundle id and compiler version input in delivery build manifest
                # from document.
                "writer_settings_digest",
            },
            "delivery build",
        )
        result = cls(
            # Keep the replay pack id and string ReplayPackId step visible while building
            # result.
            replay_pack_id=ReplayPackId(_string(document["replay_pack_id"], "replay_pack_id")),
            replay_semantics_id=ContentDigest(
                _string(document["replay_semantics_id"], "replay_semantics_id")
            ),
            replay_layout_schema_id=ContentDigest(
                # Keep the string and replay layout schema id _string step visible while
                # building result.
                _string(document["replay_layout_schema_id"], "replay_layout_schema_id")
            ),
            components=tuple(
                _component_from_document(item)
                for item in _list(document["components"], "delivery components")
                # Complete tuple only after its delivery components and components inputs are
                # visible in delivery build manifest from document.
            ),
            rng_algorithm=_string(document["rng_algorithm"], "rng_algorithm"),
            root_seed=_integer(document["root_seed"], "root_seed"),
            compiler_bundle_id=BundleId(
                _string(document["compiler_bundle_id"], "compiler_bundle_id")
                # Complete BundleId only after its compiler bundle id and string inputs are
                # visible in delivery build manifest from document.
            ),
            compiler_version=_string(document["compiler_version"], "compiler_version"),
            writer_bundle_id=BundleId(_string(document["writer_bundle_id"], "writer_bundle_id")),
            runtime_lock_id=RuntimeLockId(_string(document["runtime_lock_id"], "runtime_lock_id")),
            writer_settings_digest=ContentDigest(
                # Keep the string and writer settings digest _string step visible while
                # building result.
                _string(document["writer_settings_digest"], "writer_settings_digest")
            ),
        )
        stored_key = ContentDigest(_string(document["delivery_build_key"], "delivery_build_key"))
        if stored_key.hex != result.delivery_build_key.hex:
            # Fail the delivery build manifest from document path with
            # DeliveryManifestError for delivery build key mismatch when hex, stored key
            # and delivery build key is true; do not continue ambiguously.
            raise DeliveryManifestError("delivery build key mismatch")
        return result


ScheduledDelivery = ObservationDelivery


# Keep the delivery stream hasher contract and validation rules together.
class DeliveryStreamHasher:
    def __init__(self) -> None:
        self._digest = hashlib.sha256(_DELIVERY_STREAM_DOMAIN)

    def update(
        self,
        # Keep the delivery input explicit in the update contract.
        delivery: ScheduledDelivery,
        *,
        source_boundary_ordinal: int,
        stable_causal_id: ContentDigest,
    ) -> None:
        # Execute the delivery stream hasher update workflow in explicit, reviewable
        # steps.
        row = domain_digest(
            "backtest.logical-delivery-row.v1",
            {
                "event_row_index": delivery.event_row_index,
                "release_boundary_ordinal": delivery.release_boundary_ordinal,
                # Keep source boundary ordinal named so the v1 and event row index payload
                # passed to domain_digest remains self-describing within delivery stream
                # hasher update.
                "source_boundary_ordinal": source_boundary_ordinal,
                "stable_causal_id": stable_causal_id.hex,
            },
        )
        self._digest.update(bytes.fromhex(row.hex))

    # Define delivery stream hasher digest as one focused operation with an explicit
    # boundary.
    def digest(self) -> ContentDigest:
        return ContentDigest(self._digest.hexdigest())


# Keep the delivery schedule manifest contract and validation rules together.
@dataclass(frozen=True, slots=True)
class DeliveryScheduleManifest:
    replay_pack_id: ReplayPackId
    replay_semantics_id: ContentDigest
    replay_layout_schema_id: ContentDigest
    # Declare network id explicitly in the delivery schedule manifest contract.
    network_id: NetworkId
    position_schema_id: PositionSchemaId
    decision_range: BlockRange
    logical_delivery_stream_hash: ContentDigest
    input_event_count: int
    # Declare delivery count explicitly in the delivery schedule manifest contract.
    delivery_count: int
    outside_horizon_count: int
    layout: DeliveryLayoutManifest
    build: DeliveryBuildManifest
    artifact_schema: str = "delivery-schedule/v2"
    # Declare observation phase explicitly in the delivery schedule manifest contract.
    observation_phase: int = 30
    rebuildability: str = "REBUILDABLE"

    def __post_init__(self) -> None:
        # Execute the delivery schedule manifest post init workflow in explicit,
        # reviewable steps.
        if self.artifact_schema != "delivery-schedule/v2":
            raise DeliveryManifestError("unsupported delivery schedule schema")
        if (
            self.decision_range.network_id != self.network_id
            or self.decision_range.position_schema_id != self.position_schema_id
            # Evaluate the complete delivery schedule manifest post init network id, position
            # schema id and decision range condition before guarded effects.
        ):
            raise DeliveryManifestError("delivery decision range uses another chain identity")
        if self.observation_phase != 30:
            raise DeliveryManifestError("delivery schedule must target observation phase 30")
        if self.rebuildability != "REBUILDABLE":
            # Fail the delivery schedule manifest post init path with
            # DeliveryManifestError for delivery schedule must be rebuildable when
            # rebuildability and rebuildable is true; do not continue ambiguously.
            raise DeliveryManifestError("delivery schedule must be rebuildable")
        if self.input_event_count <= 0 or self.delivery_count < 0:
            raise DeliveryManifestError("delivery schedule counts are invalid")
        if self.outside_horizon_count < 0 or (
            self.delivery_count + self.outside_horizon_count != self.input_event_count
            # Evaluate the complete delivery schedule manifest post init outside horizon
            # count, input event count and delivery count condition before guarded effects.
        ):
            raise DeliveryManifestError("delivery schedule does not cover every input event")
        if (
            self.build.replay_pack_id != self.replay_pack_id
            or self.build.replay_semantics_id != self.replay_semantics_id
            # Keep self visible while evaluating the replay pack id, replay semantics id
            # and replay layout schema id guard.
            or self.build.replay_layout_schema_id != self.replay_layout_schema_id
        ):
            raise DeliveryManifestError("delivery build references another ReplayPack contract")

    def identity_document(self) -> dict[str, object]:
        # Execute the delivery schedule manifest identity document workflow in explicit,
        # reviewable steps.
        return {
            "artifact_schema": self.artifact_schema,
            "delivery_count": self.delivery_count,
            "decision_range": _range_document(self.decision_range),
            "input_event_count": self.input_event_count,
            # Include layout in the completed delivery schedule manifest identity document
            # result.
            "layout": self.layout.document(),
            "logical_delivery_stream_hash": self.logical_delivery_stream_hash.hex,
            "network_id": self.network_id.value,
            "observation_phase": self.observation_phase,
            "outside_horizon_count": self.outside_horizon_count,
            # Include position schema id in the completed delivery schedule manifest
            # identity document result.
            "position_schema_id": self.position_schema_id.value,
            "rebuildability": self.rebuildability,
            "replay_layout_schema_id": self.replay_layout_schema_id.hex,
            "replay_pack_id": self.replay_pack_id.hex,
            "replay_semantics_id": self.replay_semantics_id.hex,
            # Return the completed delivery schedule manifest identity document result without
            # a hidden fallback.
        }

    def document(self) -> dict[str, object]:
        return {**self.identity_document(), "build": self.build.document()}

    @classmethod
    def from_document(cls, value: object) -> DeliveryScheduleManifest:
        # Execute the delivery schedule manifest from document workflow in explicit,
        # reviewable steps.
        document = _object(value, "delivery schedule")
        artifact_schema = document.get("artifact_schema")
        if artifact_schema == "delivery-schedule/v1":
            raise ReprepareRequiredError(artifact_schema)
        _keys(
            # Pass document explicitly so _keys receives a reviewable artifact schema and
            # build input in delivery schedule manifest from document.
            document,
            {
                "artifact_schema",
                "build",
                "delivery_count",
                # Pass decision range explicitly so _keys receives a reviewable artifact
                # schema and build input in delivery schedule manifest from document.
                "decision_range",
                "input_event_count",
                "layout",
                "logical_delivery_stream_hash",
                "network_id",
                # Pass observation phase explicitly so _keys receives a reviewable
                # artifact schema and build input in delivery schedule manifest from
                # document.
                "observation_phase",
                "outside_horizon_count",
                "position_schema_id",
                "rebuildability",
                "replay_layout_schema_id",
                # Pass replay pack id explicitly so _keys receives a reviewable artifact
                # schema and build input in delivery schedule manifest from document.
                "replay_pack_id",
                "replay_semantics_id",
            },
            "delivery schedule",
        )
        # Return the completed delivery schedule manifest from document result without a
        # hidden fallback.
        return cls(
            replay_pack_id=ReplayPackId(_string(document["replay_pack_id"], "replay_pack_id")),
            replay_semantics_id=ContentDigest(
                _string(document["replay_semantics_id"], "replay_semantics_id")
            ),
            # Include replay layout schema id in the completed delivery schedule manifest
            # from document result.
            replay_layout_schema_id=ContentDigest(
                _string(document["replay_layout_schema_id"], "replay_layout_schema_id")
            ),
            network_id=NetworkId(_string(document["network_id"], "network_id")),
            position_schema_id=PositionSchemaId(
                # Include string in the completed delivery schedule manifest from document
                # result.
                _string(document["position_schema_id"], "position_schema_id")
            ),
            decision_range=_range_from_document(document["decision_range"]),
            logical_delivery_stream_hash=ContentDigest(
                _string(
                    # Pass document explicitly so _string receives a reviewable logical
                    # delivery stream hash and document input in delivery schedule
                    # manifest from document.
                    document["logical_delivery_stream_hash"],
                    "logical_delivery_stream_hash",
                )
            ),
            input_event_count=_integer(
                # Pass minimum explicitly so _integer receives a reviewable input event
                # count and document input in delivery schedule manifest from document.
                document["input_event_count"],
                "input_event_count",
                minimum=1,
            ),
            delivery_count=_integer(document["delivery_count"], "delivery_count"),
            # Include outside horizon count in the completed delivery schedule manifest
            # from document result.
            outside_horizon_count=_integer(
                document["outside_horizon_count"],
                "outside_horizon_count",
                # Complete _integer only after its outside horizon count and document inputs
                # are visible in delivery schedule manifest from document.
            ),
            layout=DeliveryLayoutManifest.from_document(document["layout"]),
            build=DeliveryBuildManifest.from_document(document["build"]),
            artifact_schema=_string(document["artifact_schema"], "artifact_schema"),
            observation_phase=_integer(
                # Pass minimum explicitly so _integer receives a reviewable observation
                # phase and document input in delivery schedule manifest from document.
                document["observation_phase"],
                "observation_phase",
                minimum=1,
            ),
            rebuildability=_string(document["rebuildability"], "rebuildability"),
            # Complete cls only after its replay pack id and replay semantics id inputs are
            # visible in delivery schedule manifest from document.
        )


# Keep the compiled delivery schedule contract and validation rules together.
@dataclass(frozen=True, slots=True)
class CompiledDeliverySchedule:
    artifact: CommittedArtifact
    delivery_schedule_id: DeliveryScheduleId
    manifest: DeliveryScheduleManifest
    # Declare requested build explicitly in the compiled delivery schedule contract.
    requested_build: DeliveryBuildManifest

    def __post_init__(self) -> None:
        # Execute the compiled delivery schedule post init workflow in explicit,
        # reviewable steps.
        if self.artifact.kind is not ArtifactKind.DELIVERY_SCHEDULE:
            raise DeliveryManifestError("compiled artifact is not a delivery schedule")
        if self.delivery_schedule_id.hex != self.artifact.artifact_id.hex:
            raise DeliveryManifestError("delivery schedule ID differs from artifact ID")
        if (
            # Keep self visible while evaluating the replay pack id, replay semantics id
            # and replay layout schema id guard.
            self.requested_build.replay_pack_id != self.manifest.replay_pack_id
            or self.requested_build.replay_semantics_id != self.manifest.replay_semantics_id
            or self.requested_build.replay_layout_schema_id != self.manifest.replay_layout_schema_id
        ):
            raise DeliveryManifestError("requested build does not derive committed content")

    # Apply property semantics to the following compiled delivery schedule delivery build
    # key contract.
    @property
    def delivery_build_key(self) -> ContentDigest:
        return self.requested_build.delivery_build_key


__all__ = [
    "CompileDeliveryScheduleRequest",
    # Keep the compiled delivery schedule component named inside the all contract.
    "CompiledDeliverySchedule",
    "DeliveryBuildManifest",
    "DeliveryLayoutManifest",
    "DeliveryManifestError",
    "DeliveryScheduleManifest",
    # Keep the delivery stream hasher component named inside the all contract.
    "DeliveryStreamHasher",
    "ScheduledDelivery",
]
