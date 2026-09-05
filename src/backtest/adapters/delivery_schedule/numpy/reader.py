"""Strict read-only mmap reader for observation DeliverySchedule layout v1."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from contextlib import suppress
from pathlib import Path

# Import types at the visible module dependency boundary.
from types import TracebackType
from typing import Any, Protocol, cast

import numpy as np
import numpy.typing as npt

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository

# Import numpy at the visible module dependency boundary.
from backtest.adapters.columnar.numpy import layout as replay_physical
from backtest.adapters.columnar.numpy.reader import NumpyMmapReplaySource
from backtest.adapters.delivery_schedule.numpy import layout as physical
from backtest.adapters.delivery_schedule.numpy.compiler import (
    DELIVERY_WRITER_SETTINGS_DIGEST,
    # Include unit delivery build tools so the compiler dependency remains explicit.
    unit_delivery_build_tools,
)
from backtest.adapters.delivery_schedule.numpy.policy import (
    DeliveryObservationPolicyError,
    resolve_observation_policy,
    # Close the policy import after its required symbols are visible.
)
from backtest.application.build_tool_roles import (
    DELIVERY_COMPILER_ROLE,
    DELIVERY_WRITER_ROLE,
)

# Import code bundles at the visible module dependency boundary.
from backtest.application.code_bundles import PinnedCodeBundleSet
from backtest.application.delivery_schedules import (
    DeliveryBuildManifest,
    DeliveryManifestError,
    DeliveryScheduleManifest,
    # Include delivery stream hasher so the delivery schedules dependency remains
    # explicit.
    DeliveryStreamHasher,
    ScheduledDelivery,
)
from backtest.application.models import ArtifactKind
from backtest.domain.hashing import canonical_json_bytes

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import BundleId, ContentDigest, DeliveryScheduleId, ReplayPackId
from backtest.engine.rng import RNG_ALGORITHM


# Keep the local handle contract and validation rules together.
class _LocalHandle(Protocol):
    @property
    def descriptor(self) -> Any: ...

    def local_path(self, relative_name: str) -> Path: ...

    def open_binary(self, relative_name: str) -> Any: ...

    # Define local handle close as one focused operation with an explicit boundary.
    def close(self) -> None: ...


class DeliveryScheduleFormatError(RuntimeError):
    """A committed DeliverySchedule violates its physical or causal contract."""


class NumpyMmapDeliverySchedule:
    """Verified sequential delivery rows referencing one exact ReplayPack."""

    def __init__(
        self,
        artifacts: LocalArtifactRepository,
        delivery_schedule_id: DeliveryScheduleId,
        *,
        # Keep the build tools input explicit in the init contract.
        build_tools: PinnedCodeBundleSet | None = None,
    ) -> None:
        # Execute the numpy mmap delivery schedule init workflow in explicit, reviewable
        # steps.
        self._closed = False
        self._build_tools = build_tools or unit_delivery_build_tools()
        compiler_bundle_id = self._build_tools.require_current(DELIVERY_COMPILER_ROLE)
        writer_bundle_id = self._build_tools.require_current(DELIVERY_WRITER_ROLE)
        self._handle = cast(_LocalHandle, artifacts.open_committed(delivery_schedule_id))
        # Assemble self arrays once so the numpy mmap delivery schedule init workflow
        # shares one value.
        self._arrays: dict[str, npt.NDArray[np.generic]] = {}
        try:
            # Perform the protected numpy mmap delivery schedule init operation before
            # explicit failure handling.
            if self._handle.descriptor.kind is not ArtifactKind.DELIVERY_SCHEDULE:
                raise DeliveryScheduleFormatError("requested artifact is not a DeliverySchedule")
            if self._handle.descriptor.artifact_id.hex != delivery_schedule_id.hex:
                raise DeliveryScheduleFormatError("DeliverySchedule descriptor identity mismatch")
            with self._handle.open_binary("manifest.json") as stream:
                # Assemble manifest bytes once so the numpy mmap delivery schedule init
                # workflow shares one value.
                manifest_bytes = stream.read()
            document = _json_object(manifest_bytes)
            if canonical_json_bytes(document) != manifest_bytes:
                raise DeliveryScheduleFormatError("DeliverySchedule manifest is not canonical JSON")
            try:
                # Assemble self manifest once so the numpy mmap delivery schedule init
                # workflow shares one value.
                self._manifest = DeliveryScheduleManifest.from_document(document)
            except (DeliveryManifestError, TypeError, ValueError) as error:
                raise DeliveryScheduleFormatError("DeliverySchedule manifest is invalid") from error
            inputs = self._handle.descriptor.input_artifact_ids
            if len(inputs) != 1 or inputs[0].hex != self._manifest.replay_pack_id.hex:
                # Handle the numpy mmap delivery schedule init hex, inputs and replay pack
                # id condition as a distinct block.
                raise DeliveryScheduleFormatError(
                    "DeliverySchedule exact ReplayPack input is inconsistent"
                )
            _validate_known_build(
                self._manifest.build,
                # Pass compiler bundle id explicitly so _validate_known_build receives a
                # reviewable build and manifest input in numpy mmap delivery schedule
                # init.
                compiler_bundle_id=compiler_bundle_id,
                writer_bundle_id=writer_bundle_id,
            )
            _validate_known_layout(self._manifest)
            self._map_arrays()
            # Acquire numpy mmap replay source, artifacts and replay pack id at an
            # explicit numpy mmap delivery schedule init context boundary so cleanup
            # remains scoped.
            with NumpyMmapReplaySource(
                artifacts,
                self._manifest.replay_pack_id,
                build_tools=self._build_tools,
            ) as replay:
                # Invoke _validate_against_replay for replay as a visible numpy mmap
                # delivery schedule init step.
                self._validate_against_replay(replay)
        except BaseException:
            # Translate the BaseException failure through the numpy mmap delivery schedule
            # init boundary.
            self.close()
            raise

    @property
    def delivery_schedule_id(self) -> DeliveryScheduleId:
        return DeliveryScheduleId(self._handle.descriptor.artifact_id.hex)

    # Apply property semantics to the following numpy mmap delivery schedule replay pack
    # id contract.
    @property
    def replay_pack_id(self) -> ReplayPackId:
        return self._manifest.replay_pack_id

    @property
    def manifest(self) -> DeliveryScheduleManifest:
        # Return the completed numpy mmap delivery schedule manifest result without a
        # hidden fallback.
        return self._manifest

    @property
    def delivery_build_key(self) -> ContentDigest:
        return self._manifest.build.delivery_build_key

    @property
    # Define numpy mmap delivery schedule input event count as one focused operation with
    # an explicit boundary.
    def input_event_count(self) -> int:
        return self._manifest.input_event_count

    @property
    def delivery_count(self) -> int:
        return self._manifest.delivery_count

    # Apply property semantics to the following numpy mmap delivery schedule outside
    # horizon count contract.
    @property
    def outside_horizon_count(self) -> int:
        return self._manifest.outside_horizon_count

    def require_build(self, expected: DeliveryBuildManifest) -> None:
        # Execute the numpy mmap delivery schedule require build workflow in explicit,
        # reviewable steps.
        self._require_open()
        if expected.document() != self._manifest.build.document():
            # Handle the numpy mmap delivery schedule require build document, expected and
            # build condition as a distinct block.
            raise DeliveryScheduleFormatError(
                "DeliverySchedule build differs from resolved run inputs"
            )

    def deliveries(self) -> Iterator[ScheduledDelivery]:
        # Execute the numpy mmap delivery schedule deliveries workflow in explicit,
        # reviewable steps.
        self._require_open()
        release = self._arrays[physical.RELEASE_BOUNDARY_ORDINAL]
        rows = self._arrays[physical.EVENT_ROW_INDEX]
        for index in range(self._manifest.delivery_count):
            yield ScheduledDelivery(int(release[index]), int(rows[index]))

    # Define numpy mmap delivery schedule delivery columns as one focused operation with
    # an explicit boundary.
    def delivery_columns(self) -> tuple[Sequence[int], Sequence[int]]:
        """Expose verified read-only mmap columns to specialized engines."""

        self._require_open()
        return (
            cast(Sequence[int], self._arrays[physical.RELEASE_BOUNDARY_ORDINAL]),
            cast(Sequence[int], self._arrays[physical.EVENT_ROW_INDEX]),
        )

    # Define numpy mmap delivery schedule arrays as one focused operation with an explicit
    # boundary.
    def arrays(self) -> Mapping[str, npt.NDArray[np.generic]]:
        # Execute the numpy mmap delivery schedule arrays workflow in explicit, reviewable
        # steps.
        self._require_open()
        return self._arrays.copy()

    def close(self) -> None:
        # Execute the numpy mmap delivery schedule close workflow in explicit, reviewable
        # steps.
        if self._closed:
            return
        self._closed = True
        for array in self._arrays.values():
            # Process self._arrays.values() inside the bounded numpy mmap delivery
            # schedule close loop.
            mmap = getattr(array, "_mmap", None)
            if mmap is not None:
                # Handle the numpy mmap delivery schedule close mmap is not None branch as
                # a distinct logical block.
                with suppress(BufferError):
                    mmap.close()
        self._arrays.clear()
        self._handle.close()

    def __enter__(self) -> NumpyMmapDeliverySchedule:
        # Return the completed numpy mmap delivery schedule enter result without a hidden
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

    def _map_arrays(self) -> None:
        # Execute the numpy mmap delivery schedule map arrays workflow in explicit,
        # reviewable steps.
        for descriptor in self._manifest.layout.arrays:
            # Process self._manifest.layout.arrays inside the bounded numpy mmap delivery
            # schedule map arrays loop.
            try:
                # Perform the protected numpy mmap delivery schedule map arrays operation
                # before explicit failure handling.
                array = np.load(
                    self._handle.local_path(descriptor.path),
                    mmap_mode="r",
                    allow_pickle=False,
                    max_header_size=16 * 1024,
                    # Complete load only after its r and local path inputs are visible in
                    # numpy mmap delivery schedule map arrays.
                )
            except (OSError, ValueError) as error:
                # Translate the (OSError, ValueError) failure through the numpy mmap
                # delivery schedule map arrays boundary.
                raise DeliveryScheduleFormatError(
                    f"DeliverySchedule array {descriptor.role} cannot be mapped"
                ) from error
            if not isinstance(array, np.memmap):
                # Handle the numpy mmap delivery schedule map arrays not isinstance(array,
                # np.memmap) branch as a distinct logical block.
                raise DeliveryScheduleFormatError(
                    "DeliverySchedule .npy member is not memory mapped"
                )
            if array.dtype.str != descriptor.dtype:
                # Handle the numpy mmap delivery schedule map arrays array.dtype.str !=
                # descriptor.dtype branch as a distinct logical block.
                raise DeliveryScheduleFormatError(
                    f"DeliverySchedule array {descriptor.role} dtype/endian mismatch"
                )
            if array.shape != descriptor.shape:
                # Handle the numpy mmap delivery schedule map arrays array.shape !=
                # descriptor.shape branch as a distinct logical block.
                raise DeliveryScheduleFormatError(
                    f"DeliverySchedule array {descriptor.role} shape mismatch"
                )
            if not array.flags.c_contiguous or array.flags.writeable:
                # Handle the numpy mmap delivery schedule map arrays writeable, c
                # contiguous and flags condition as a distinct block.
                raise DeliveryScheduleFormatError(
                    f"DeliverySchedule array {descriptor.role} is not read-only C-order"
                )
            self._arrays[descriptor.path] = array

    def _validate_against_replay(self, replay: NumpyMmapReplaySource) -> None:
        # Execute the numpy mmap delivery schedule validate against replay workflow in
        # explicit, reviewable steps.
        manifest = self._manifest
        if replay.replay_pack_id != manifest.replay_pack_id:
            raise DeliveryScheduleFormatError("DeliverySchedule references another ReplayPack")
        if replay.replay_semantics_id != manifest.replay_semantics_id:
            raise DeliveryScheduleFormatError("ReplayPack semantics changed")
        # Evaluate the complete numpy mmap delivery schedule validate against replay
        # replay layout schema id, replay and manifest condition before guarded effects.
        if replay.replay_layout_schema_id != manifest.replay_layout_schema_id:
            raise DeliveryScheduleFormatError("ReplayPack layout schema changed")
        if (
            replay.network_id != manifest.network_id
            or replay.position_schema_id != manifest.position_schema_id
            # Keep replay visible while evaluating the network id, position schema id and
            # decision range guard.
            or replay.decision_range != manifest.decision_range
        ):
            # Handle the numpy mmap delivery schedule validate against replay network id,
            # position schema id and decision range condition as a distinct block.
            raise DeliveryScheduleFormatError(
                "DeliverySchedule chain identity or decision range changed"
            )
        if replay.manifest.event_count != manifest.input_event_count:
            raise DeliveryScheduleFormatError("ReplayPack event count changed")
        # Assemble replay arrays once so the numpy mmap delivery schedule validate against
        # replay workflow shares one value.
        replay_arrays = replay.arrays()
        observation_block_delay = _observation_block_delay(manifest.build)
        expected_deliveries, expected_outside = _expected_counts(
            replay_arrays,
            observation_block_delay,
            # Complete _expected_counts only after its replay arrays and observation block
            # delay inputs are visible in numpy mmap delivery schedule validate against
            # replay.
        )
        if (
            expected_deliveries != manifest.delivery_count
            or expected_outside != manifest.outside_horizon_count
        ):
            # Handle the numpy mmap delivery schedule validate against replay expected
            # deliveries, delivery count and expected outside condition as a distinct
            # block.
            raise DeliveryScheduleFormatError(
                "DeliverySchedule counts differ from resolved latency"
            )
        _validate_delivery_rows(
            manifest,
            # Pass self explicitly so _validate_delivery_rows receives a reviewable arrays
            # and manifest input in numpy mmap delivery schedule validate against replay.
            self._arrays,
            replay_arrays,
            observation_block_delay,
        )

    def _require_open(self) -> None:
        # Execute the numpy mmap delivery schedule require open workflow in explicit,
        # reviewable steps.
        if self._closed:
            raise DeliveryScheduleFormatError("DeliverySchedule reader is closed")


def _validate_known_layout(manifest: DeliveryScheduleManifest) -> None:
    # Execute the validate known layout workflow in explicit, reviewable steps.
    expected = physical.build_layout(manifest.delivery_count)
    if manifest.layout.document() != expected.document():
        # Handle the validate known layout document, layout and expected condition as a
        # distinct block.
        raise DeliveryScheduleFormatError(
            "DeliverySchedule layout is not the supported mmap v1 schema"
        )


def _validate_known_build(
    build: DeliveryBuildManifest,
    # Close the validate known build signature after its explicit inputs.
    *,
    compiler_bundle_id: BundleId,
    writer_bundle_id: BundleId,
) -> None:
    # Execute the validate known build workflow in explicit, reviewable steps.
    if build.compiler_bundle_id != compiler_bundle_id:
        raise DeliveryScheduleFormatError("delivery compiler bundle is unsupported")
    if build.compiler_version != physical.COMPILER_VERSION:
        raise DeliveryScheduleFormatError("delivery compiler version is unsupported")
    if build.writer_bundle_id != writer_bundle_id:
        # Fail the validate known build path with DeliveryScheduleFormatError for delivery
        # writer bundle is unsupported when writer bundle id and build is true; do not
        # continue ambiguously.
        raise DeliveryScheduleFormatError("delivery writer bundle is unsupported")
    if build.writer_settings_digest != DELIVERY_WRITER_SETTINGS_DIGEST:
        raise DeliveryScheduleFormatError("delivery writer settings are unsupported")
    if build.rng_algorithm != RNG_ALGORITHM:
        raise DeliveryScheduleFormatError("delivery RNG algorithm is unsupported")
    # Evaluate the complete validate known build api version, component and components
    # condition before guarded effects.
    if any(component.api_version != 1 for component in build.components):
        raise DeliveryScheduleFormatError("delivery component API version is unsupported")
    _observation_block_delay(build)


def _observation_block_delay(build: DeliveryBuildManifest) -> int:
    # Execute the observation block delay workflow in explicit, reviewable steps.
    try:
        return resolve_observation_policy(build.components).block_delay
    except DeliveryObservationPolicyError as error:
        raise DeliveryScheduleFormatError(str(error)) from error


def _expected_counts(
    # Keep the replay arrays input explicit in the expected counts contract.
    replay_arrays: Mapping[str, npt.NDArray[np.generic]],
    observation_blocks: int,
) -> tuple[int, int]:
    # Execute the expected counts workflow in explicit, reviewable steps.
    group_offsets = replay_arrays[replay_physical.GROUP_OFFSETS]
    boundary_ordinals = replay_arrays[replay_physical.BOUNDARY_ORDINAL]
    boundary_blocks = replay_arrays[replay_physical.BOUNDARY_BLOCK_ORDINAL]
    sources = replay_arrays[replay_physical.ENVELOPE_BOUNDARY_ORDINAL]
    if any(
        # Keep int visible while evaluating the index, boundary blocks and size guard.
        int(boundary_blocks[index]) > int(boundary_blocks[index + 1])
        for index in range(boundary_blocks.size - 1)
    ):
        raise DeliveryScheduleFormatError("ReplayPack boundary slots are not monotone")
    if group_offsets.size != boundary_ordinals.size + 1:
        # Fail the expected counts path with DeliveryScheduleFormatError for replay pack
        # does not have one atomic group per boundary when size, group offsets and
        # boundary ordinals is true; do not continue ambiguously.
        raise DeliveryScheduleFormatError("ReplayPack does not have one atomic group per boundary")
    delivered = 0
    outside = 0
    release_index = 0
    for source_index in range(boundary_ordinals.size):
        # Process range(boundary_ordinals.size) inside the bounded expected counts loop.
        start = int(group_offsets[source_index])
        stop = int(group_offsets[source_index + 1])
        source = int(boundary_ordinals[source_index])
        if np.any(sources[start:stop] != source):
            raise DeliveryScheduleFormatError("ReplayPack group differs from source boundary")
        # Assemble release index once so the expected counts workflow shares one value.
        release_index = _next_release_index(
            boundary_blocks,
            source_index,
            observation_blocks,
            release_index,
            # Complete _next_release_index only after its boundary blocks and source index
            # inputs are visible in expected counts.
        )
        if release_index >= boundary_ordinals.size:
            outside += stop - start
        else:
            delivered += stop - start
    # Return the completed expected counts result without a hidden fallback.
    return delivered, outside


def _validate_delivery_rows(
    manifest: DeliveryScheduleManifest,
    delivery_arrays: Mapping[str, npt.NDArray[np.generic]],
    replay_arrays: Mapping[str, npt.NDArray[np.generic]],
    # Keep the observation blocks input explicit in the validate delivery rows contract.
    observation_blocks: int,
) -> None:
    # Execute the validate delivery rows workflow in explicit, reviewable steps.
    releases = delivery_arrays[physical.RELEASE_BOUNDARY_ORDINAL]
    event_rows = delivery_arrays[physical.EVENT_ROW_INDEX]
    boundary_ordinals = replay_arrays[replay_physical.BOUNDARY_ORDINAL]
    boundary_blocks = replay_arrays[replay_physical.BOUNDARY_BLOCK_ORDINAL]
    sources = replay_arrays[replay_physical.ENVELOPE_BOUNDARY_ORDINAL]
    # Assemble stable ids once so the validate delivery rows workflow shares one value.
    stable_ids = replay_arrays[replay_physical.ENVELOPE_STABLE_CAUSAL_ID]
    stream_hasher = DeliveryStreamHasher()
    previous_key: tuple[int, int, bytes] | None = None
    source_index = 0
    release_index = 0
    # Assemble current source once so the validate delivery rows workflow shares one
    # value.
    current_source: int | None = None
    expected_release: int | None = None
    for schedule_row in range(manifest.delivery_count):
        # Process range(manifest.delivery_count) inside the bounded validate delivery rows
        # loop.
        event_row = int(event_rows[schedule_row])
        if event_row >= manifest.input_event_count:
            raise DeliveryScheduleFormatError("delivery event row index is out of bounds")
        source = int(sources[event_row])
        if source != current_source:
            # Handle the validate delivery rows source != current_source branch as a
            # distinct logical block.
            while (
                source_index < boundary_ordinals.size
                and int(boundary_ordinals[source_index]) < source
            ):
                source_index += 1
            # Evaluate the complete validate delivery rows source index, size and source
            # condition before guarded effects.
            if (
                source_index >= boundary_ordinals.size
                or int(boundary_ordinals[source_index]) != source
            ):
                # Handle the validate delivery rows source index, size and source
                # condition as a distinct block.
                raise DeliveryScheduleFormatError(
                    "delivery event references an unknown or non-monotone source boundary"
                )
            release_index = _next_release_index(
                boundary_blocks,
                # Pass source index explicitly so _next_release_index receives a
                # reviewable boundary blocks and source index input in validate delivery
                # rows.
                source_index,
                observation_blocks,
                release_index,
            )
            if release_index >= boundary_ordinals.size:
                # Handle the validate delivery rows release index, size and boundary
                # ordinals condition as a distinct block.
                raise DeliveryScheduleFormatError(
                    "delivery includes an observation outside the replay horizon"
                )
            current_source = source
            expected_release = int(boundary_ordinals[release_index])
        # Assemble release once so the validate delivery rows workflow shares one value.
        release = int(releases[schedule_row])
        if release != expected_release:
            raise DeliveryScheduleFormatError("delivery release differs from resolved latency")
        stable_raw = stable_ids[event_row].tobytes()
        key = (release, source, stable_raw)
        # Evaluate the complete validate delivery rows previous key and key condition
        # before guarded effects.
        if previous_key is not None and key <= previous_key:
            raise DeliveryScheduleFormatError("delivery rows collide or violate scheduler ordering")
        previous_key = key
        stream_hasher.update(
            ScheduledDelivery(release, event_row),
            # Pass source boundary ordinal explicitly so update receives a reviewable hex
            # and scheduled delivery input in validate delivery rows.
            source_boundary_ordinal=source,
            stable_causal_id=ContentDigest(stable_raw.hex()),
        )
    if stream_hasher.digest() != manifest.logical_delivery_stream_hash:
        raise DeliveryScheduleFormatError("logical delivery stream hash mismatch")


# Define next release index as one focused operation with an explicit boundary.
def _next_release_index(
    boundary_blocks: npt.NDArray[np.generic],
    source_index: int,
    observation_blocks: int,
    previous_release_index: int,
    # Keep the int input explicit in the next release index contract.
) -> int:
    # Execute the next release index workflow in explicit, reviewable steps.
    target_block = int(boundary_blocks[source_index]) + observation_blocks
    candidate = max(source_index, previous_release_index)
    while candidate < boundary_blocks.size and int(boundary_blocks[candidate]) < target_block:
        candidate += 1
    return candidate


# Define json object as one focused operation with an explicit boundary.
def _json_object(payload: bytes) -> dict[str, object]:
    # Execute the json object workflow in explicit, reviewable steps.
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, ValueError) as error:
        raise DeliveryScheduleFormatError("DeliverySchedule manifest is invalid JSON") from error
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        # Fail the json object path with DeliveryScheduleFormatError for delivery schedule
        # manifest must be a json object when isinstance, value and key is true; do not
        # continue ambiguously.
        raise DeliveryScheduleFormatError("DeliverySchedule manifest must be a JSON object")
    return cast(dict[str, object], value)


__all__ = ["DeliveryScheduleFormatError", "NumpyMmapDeliverySchedule"]
