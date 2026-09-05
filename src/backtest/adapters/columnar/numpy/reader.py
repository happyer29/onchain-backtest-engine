"""Strict read-only mmap reader for deterministic ReplayPack NumPy layout v3."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import suppress
from pathlib import Path

# Import types at the visible module dependency boundary.
from types import TracebackType
from typing import Any, Protocol, cast

import numpy as np
import numpy.typing as npt

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository

# Import numpy at the visible module dependency boundary.
from backtest.adapters.columnar.numpy import layout as physical
from backtest.adapters.columnar.numpy.compiler import (
    replay_writer_settings_digest,
    unit_replay_build_tools,
)

# Import build tool roles at the visible module dependency boundary.
from backtest.application.build_tool_roles import REPLAY_COMPILER_ROLE, REPLAY_WRITER_ROLE
from backtest.application.canonical_data import EffectiveSourceBoundary
from backtest.application.code_bundles import PinnedCodeBundleSet
from backtest.application.models import ArtifactKind, DatasetSpec
from backtest.application.replay_packs import (
    # Include replay manifest error so the replay packs dependency remains explicit.
    ReplayManifestError,
    ReplayPackManifest,
    ReplaySemanticsManifest,
)
from backtest.domain.event_hashing import CanonicalEventStreamHasher

# Import fidelity at the visible module dependency boundary.
from backtest.domain.fidelity import OrderingFidelity
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import (
    AccountId,
    AssetId,
    # Include bundle id so the identifiers dependency remains explicit.
    BundleId,
    CapabilityId,
    ContentDigest,
    DatasetRevisionId,
    FeeComponentId,
    # Include logical content hash so the identifiers dependency remains explicit.
    LogicalContentHash,
    NetworkId,
    PositionSchemaId,
    ProtocolPayloadSchemaId,
    ReplayPackId,
    # Include snapshot id so the identifiers dependency remains explicit.
    SnapshotId,
    VenueId,
)
from backtest.domain.market_events import (
    BlockEvent,
    # Include canonical event so the market events dependency remains explicit.
    CanonicalEvent,
    ChainPosition,
    EventEnvelope,
    EventKind,
    FeeComponent,
    # Include token launch event so the market events dependency remains explicit.
    TokenLaunchEvent,
    VenueLifecycleEvent,
    VenueLifecycleKind,
    VenueTradeEvent,
)

# Import time at the visible module dependency boundary.
from backtest.domain.time import BlockRange
from backtest.engine.replay import ReplayBoundary
from backtest.engine.transaction_clock import CompactTransactionClock

_CODE_TO_FIDELITY = {
    0: OrderingFidelity.UNKNOWN,
    # Keep the ordering fidelity component named inside the code to fidelity contract.
    1: OrderingFidelity.TRANSACTION_PARTIAL,
    2: OrderingFidelity.TRANSACTION_EXACT,
    3: OrderingFidelity.INSTRUCTION_EXACT,
}
_CODE_TO_LIFECYCLE = {
    # Keep the venue lifecycle kind component named inside the code to lifecycle contract.
    1: VenueLifecycleKind.COMPLETED,
    2: VenueLifecycleKind.MIGRATED,
    3: VenueLifecycleKind.CLOSED,
}


# Keep the local handle contract and validation rules together.
class _LocalHandle(Protocol):
    @property
    def descriptor(self) -> Any: ...

    def local_path(self, relative_name: str) -> Path: ...

    def open_binary(self, relative_name: str) -> Any: ...

    # Define local handle close as one focused operation with an explicit boundary.
    def close(self) -> None: ...


class ReplayPackFormatError(RuntimeError):
    """A committed ReplayPack violates its versioned physical contract."""


class _DictionaryView:
    def __init__(
        self,
        *,
        name: str,
        # Keep the values input explicit in the init contract.
        values: npt.NDArray[np.generic],
        offsets: npt.NDArray[np.generic],
        count: int,
    ) -> None:
        # Execute the dictionary view init workflow in explicit, reviewable steps.
        self.name = name
        self.values = values
        self.offsets = offsets
        self.count = count
        self._validate()

    # Define dictionary view value as one focused operation with an explicit boundary.
    def value(self, code: int) -> str:
        # Execute the dictionary view value workflow in explicit, reviewable steps.
        if not 0 <= code < self.count:
            raise ReplayPackFormatError(f"{self.name} dictionary code is out of bounds")
        start = int(self.offsets[code])
        stop = int(self.offsets[code + 1])
        try:
            # Return the completed dictionary view value result without a hidden fallback.
            return self.values[start:stop].tobytes().decode("utf-8")
        except UnicodeDecodeError as error:  # pragma: no cover - checked at open
            raise ReplayPackFormatError(f"{self.name} dictionary contains invalid UTF-8") from error

    def code_for(self, value: str) -> int | None:
        # Execute the dictionary view code for workflow in explicit, reviewable steps.
        target = value.encode("utf-8")
        lower = 0
        upper = self.count
        while lower < upper:
            # Keep the lower < upper loop body bounded within dictionary view code for.
            middle = (lower + upper) // 2
            start = int(self.offsets[middle])
            stop = int(self.offsets[middle + 1])
            candidate = self.values[start:stop].tobytes()
            if candidate < target:
                # Assemble lower once so the dictionary view code for workflow shares one
                # value.
                lower = middle + 1
            else:
                upper = middle
        if lower >= self.count:
            return None
        # Assemble start once so the dictionary view code for workflow shares one value.
        start = int(self.offsets[lower])
        stop = int(self.offsets[lower + 1])
        return lower if self.values[start:stop].tobytes() == target else None

    def _validate(self) -> None:
        # Execute the dictionary view validate workflow in explicit, reviewable steps.
        if self.offsets.shape != (self.count + 1,):
            raise ReplayPackFormatError(f"{self.name} dictionary offset count is invalid")
        if int(self.offsets[0]) != 0 or int(self.offsets[-1]) != self.values.size:
            raise ReplayPackFormatError(f"{self.name} dictionary sentinels are invalid")
        previous: bytes | None = None
        # Traverse range(self.count) explicitly so each dictionary view validate iteration
        # remains traceable.
        for index in range(self.count):
            # Process range(self.count) inside the bounded dictionary view validate loop.
            start = int(self.offsets[index])
            stop = int(self.offsets[index + 1])
            if stop <= start:
                raise ReplayPackFormatError(f"{self.name} dictionary values must be non-empty")
            raw = self.values[start:stop].tobytes()
            # Keep expected failures inside the dictionary view validate error boundary.
            try:
                decoded = raw.decode("utf-8")
            except UnicodeDecodeError as error:
                # Translate the UnicodeDecodeError failure through the dictionary view
                # validate boundary.
                raise ReplayPackFormatError(
                    f"{self.name} dictionary contains invalid UTF-8"
                ) from error
            if not decoded or decoded != decoded.strip():
                raise ReplayPackFormatError(f"{self.name} dictionary contains an invalid value")
            # Evaluate the complete dictionary view validate previous and raw condition
            # before guarded effects.
            if previous is not None and raw <= previous:
                raise ReplayPackFormatError(f"{self.name} dictionary order is not deterministic")
            previous = raw


class NumpyMmapReplaySource:
    """Verified mmap source and exact compact transaction-clock provider."""

    def __init__(
        self,
        artifacts: LocalArtifactRepository,
        replay_pack_id: ReplayPackId,
        *,
        # Keep the build tools input explicit in the init contract.
        build_tools: PinnedCodeBundleSet | None = None,
    ) -> None:
        # Execute the numpy mmap replay source init workflow in explicit, reviewable
        # steps.
        self._closed = False
        self._build_tools = build_tools or unit_replay_build_tools()
        compiler_bundle_id = self._build_tools.require_current(REPLAY_COMPILER_ROLE)
        writer_bundle_id = self._build_tools.require_current(REPLAY_WRITER_ROLE)
        self._handle = cast(_LocalHandle, artifacts.open_committed(replay_pack_id))
        # Assemble self arrays once so the numpy mmap replay source init workflow shares
        # one value.
        self._arrays: dict[str, npt.NDArray[np.generic]] = {}
        self._dictionaries: dict[str, _DictionaryView] = {}
        try:
            # Perform the protected numpy mmap replay source init operation before
            # explicit failure handling.
            if self._handle.descriptor.kind is not ArtifactKind.REPLAY_PACK:
                raise ReplayPackFormatError("requested artifact is not a ReplayPack")
            if self._handle.descriptor.artifact_id.hex != replay_pack_id.hex:
                raise ReplayPackFormatError("ReplayPack descriptor identity mismatch")
            with self._handle.open_binary("manifest.json") as stream:
                # Assemble manifest bytes once so the numpy mmap replay source init
                # workflow shares one value.
                manifest_bytes = stream.read()
            document = _json_object(manifest_bytes)
            if canonical_json_bytes(document) != manifest_bytes:
                raise ReplayPackFormatError("ReplayPack manifest is not canonical JSON")
            try:
                # Assemble self manifest once so the numpy mmap replay source init
                # workflow shares one value.
                self._manifest = ReplayPackManifest.from_document(document)
            except (ReplayManifestError, TypeError, ValueError) as error:
                raise ReplayPackFormatError("ReplayPack manifest is invalid") from error
            if self._manifest.semantics != ReplaySemanticsManifest.canonical_v3():
                # Handle the numpy mmap replay source init semantics, manifest and
                # canonical v3 condition as a distinct block.
                raise ReplayPackFormatError(
                    "ReplayPack uses an unsupported canonical identity contract"
                )
            _validate_known_build(
                self._manifest,
                # Pass compiler bundle id explicitly so _validate_known_build receives a
                # reviewable manifest and compiler bundle id input in numpy mmap replay
                # source init.
                compiler_bundle_id=compiler_bundle_id,
                writer_bundle_id=writer_bundle_id,
            )
            input_ids = self._handle.descriptor.input_artifact_ids
            if len(input_ids) != 1 or input_ids[0].hex != self._manifest.snapshot_id.hex:
                # Fail the numpy mmap replay source init path with ReplayPackFormatError
                # for replay pack exact snapshot input is inconsistent when hex, input ids
                # and snapshot id is true; do not continue ambiguously.
                raise ReplayPackFormatError("ReplayPack exact snapshot input is inconsistent")
            _validate_known_layout(self._manifest)
            self._map_arrays()
            self._open_dictionaries()
            self._transaction_clock = self._validate_structure()
        # Translate base exception through the numpy mmap replay source init boundary
        # without hiding other errors.
        except BaseException:
            # Translate the BaseException failure through the numpy mmap replay source
            # init boundary.
            self.close()
            raise

    @property
    def replay_pack_id(self) -> ReplayPackId:
        return ReplayPackId(self._handle.descriptor.artifact_id.hex)

    # Apply property semantics to the following numpy mmap replay source snapshot id
    # contract.
    @property
    def snapshot_id(self) -> SnapshotId:
        return self._manifest.snapshot_id

    @property
    def dataset_revision_id(self) -> DatasetRevisionId:
        # Return the completed numpy mmap replay source dataset revision id result without
        # a hidden fallback.
        return self._manifest.dataset_revision_id

    @property
    def network_id(self) -> NetworkId:
        return self._manifest.network_id

    @property
    # Define numpy mmap replay source position schema id as one focused operation with an
    # explicit boundary.
    def position_schema_id(self) -> PositionSchemaId:
        return self._manifest.position_schema_id

    @property
    def decision_range(self) -> BlockRange:
        return self._manifest.decision_range

    # Apply property semantics to the following numpy mmap replay source dataset spec
    # contract.
    @property
    def dataset_spec(self) -> DatasetSpec:
        return self._manifest.dataset_spec

    @property
    def logical_content_hash(self) -> LogicalContentHash:
        # Return the completed numpy mmap replay source logical content hash result
        # without a hidden fallback.
        return self._manifest.logical_content_hash

    @property
    def replay_semantics_id(self) -> ContentDigest:
        return self._manifest.semantics.replay_semantics_id

    @property
    # Define numpy mmap replay source replay layout schema id as one focused operation
    # with an explicit boundary.
    def replay_layout_schema_id(self) -> ContentDigest:
        return self._manifest.layout.replay_layout_schema_id

    @property
    def source_boundaries(self) -> tuple[EffectiveSourceBoundary, ...]:
        return self._manifest.source_boundaries

    # Apply property semantics to the following numpy mmap replay source manifest
    # contract.
    @property
    def manifest(self) -> ReplayPackManifest:
        return self._manifest

    @property
    def group_offsets(self) -> npt.NDArray[np.generic]:
        # Execute the numpy mmap replay source group offsets workflow in explicit,
        # reviewable steps.
        self._require_open()
        return self._arrays[physical.GROUP_OFFSETS]

    @property
    def boundary_offsets(self) -> npt.NDArray[np.generic]:
        # Execute the numpy mmap replay source boundary offsets workflow in explicit,
        # reviewable steps.
        self._require_open()
        return self._arrays[physical.BOUNDARY_OFFSETS]

    @property
    def event_count(self) -> int:
        return self._manifest.event_count

    # Define numpy mmap replay source transaction clock as one focused operation with an
    # explicit boundary.
    def transaction_clock(self) -> CompactTransactionClock:
        # Execute the numpy mmap replay source transaction clock workflow in explicit,
        # reviewable steps.
        self._require_open()
        return self._transaction_clock

    def boundaries(self) -> tuple[ReplayBoundary, ...]:
        # Execute the numpy mmap replay source boundaries workflow in explicit, reviewable
        # steps.
        self._require_open()
        ordinals = self._arrays[physical.BOUNDARY_ORDINAL]
        blocks = self._arrays[physical.BOUNDARY_BLOCK_ORDINAL]
        return tuple(
            ReplayBoundary(
                # Pass network id explicitly so ReplayBoundary receives a reviewable
                # network id and position schema id input in numpy mmap replay source
                # boundaries.
                network_id=self.network_id,
                position_schema_id=self.position_schema_id,
                boundary_ordinal=int(ordinals[index]),
                block_ordinal=int(blocks[index]),
            )
            # Include index in the completed numpy mmap replay source boundaries result.
            for index in range(self._manifest.boundary_count)
        )

    def events(self) -> Iterator[CanonicalEvent]:
        # Execute the numpy mmap replay source events workflow in explicit, reviewable
        # steps.
        self._require_open()
        stream_hasher = CanonicalEventStreamHasher()
        for index in range(self._manifest.event_count):
            # Process range(self._manifest.event_count) inside the bounded numpy mmap
            # replay source events loop.
            event = self._event(index)
            stream_hasher.update(event)
            yield event
        if stream_hasher.logical_content_hash() != self._manifest.logical_output_stream_hash:
            raise ReplayPackFormatError("ReplayPack logical event stream hash mismatch")

    # Define numpy mmap replay source event at as one focused operation with an explicit
    # boundary.
    def event_at(self, event_row_index: int) -> CanonicalEvent:
        # Execute the numpy mmap replay source event at workflow in explicit, reviewable
        # steps.
        self._require_open()
        if (
            isinstance(event_row_index, bool)
            or not isinstance(event_row_index, int)
            or not 0 <= event_row_index < self._manifest.event_count
            # Evaluate the complete numpy mmap replay source event at isinstance, event row
            # index and event count condition before guarded effects.
        ):
            raise ReplayPackFormatError("ReplayPack event row index is out of bounds")
        return self._event(event_row_index)

    def arrays(self) -> Mapping[str, npt.NDArray[np.generic]]:
        # Execute the numpy mmap replay source arrays workflow in explicit, reviewable
        # steps.
        self._require_open()
        return self._arrays.copy()

    def dictionary_code(self, name: str, value: str) -> int | None:
        # Execute the numpy mmap replay source dictionary code workflow in explicit,
        # reviewable steps.
        self._require_open()
        if not value or value != value.strip():
            raise ReplayPackFormatError("ReplayPack dictionary lookup value is invalid")
        try:
            return self._dictionaries[name].code_for(value)
        # Translate key error through the numpy mmap replay source dictionary code
        # boundary without hiding other errors.
        except KeyError as error:
            raise ReplayPackFormatError("ReplayPack dictionary name is unsupported") from error

    def dictionary_value(self, name: str, code: int) -> str:
        # Execute the numpy mmap replay source dictionary value workflow in explicit,
        # reviewable steps.
        self._require_open()
        try:
            return self._dictionaries[name].value(code)
        except KeyError as error:
            raise ReplayPackFormatError("ReplayPack dictionary name is unsupported") from error

    # Define numpy mmap replay source close as one focused operation with an explicit
    # boundary.
    def close(self) -> None:
        # Execute the numpy mmap replay source close workflow in explicit, reviewable
        # steps.
        if self._closed:
            return
        self._closed = True
        for array in self._arrays.values():
            # Process self._arrays.values() inside the bounded numpy mmap replay source
            # close loop.
            mmap = getattr(array, "_mmap", None)
            if mmap is not None:
                # Handle the numpy mmap replay source close mmap is not None branch as a
                # distinct logical block.
                with suppress(BufferError):
                    mmap.close()
        self._arrays.clear()
        self._dictionaries.clear()
        self._handle.close()

    # Define numpy mmap replay source enter as one focused operation with an explicit
    # boundary.
    def __enter__(self) -> NumpyMmapReplaySource:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        # Keep the exc input explicit in the exit contract.
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _map_arrays(self) -> None:
        # Execute the numpy mmap replay source map arrays workflow in explicit, reviewable
        # steps.
        for descriptor in self._manifest.layout.arrays:
            # Process self._manifest.layout.arrays inside the bounded numpy mmap replay
            # source map arrays loop.
            path = self._handle.local_path(descriptor.path)
            try:
                array = np.load(path, mmap_mode="r", allow_pickle=False, max_header_size=16 * 1024)
            except (OSError, ValueError) as error:
                # Translate the (OSError, ValueError) failure through the numpy mmap
                # replay source map arrays boundary.
                raise ReplayPackFormatError(
                    f"ReplayPack array {descriptor.role} cannot be mapped"
                ) from error
            if not isinstance(array, np.memmap):
                raise ReplayPackFormatError("ReplayPack .npy member is not memory mapped")
            # Guard this path with array.dtype.str != descriptor.dtype before applying
            # effects.
            if array.dtype.str != descriptor.dtype:
                # Handle the numpy mmap replay source map arrays array.dtype.str !=
                # descriptor.dtype branch as a distinct logical block.
                raise ReplayPackFormatError(
                    f"ReplayPack array {descriptor.role} dtype/endian mismatch"
                )
            if array.shape != descriptor.shape:
                raise ReplayPackFormatError(f"ReplayPack array {descriptor.role} shape mismatch")
            # Evaluate the complete numpy mmap replay source map arrays writeable, c
            # contiguous and flags condition before guarded effects.
            if not array.flags.c_contiguous or array.flags.writeable:
                # Handle the numpy mmap replay source map arrays writeable, c contiguous
                # and flags condition as a distinct block.
                raise ReplayPackFormatError(
                    f"ReplayPack array {descriptor.role} is not read-only C-order"
                )
            self._arrays[descriptor.path] = array

    def _open_dictionaries(self) -> None:
        # Execute the numpy mmap replay source open dictionaries workflow in explicit,
        # reviewable steps.
        for descriptor in self._manifest.layout.dictionaries:
            # Process self._manifest.layout.dictionaries inside the bounded numpy mmap
            # replay source open dictionaries loop.
            self._dictionaries[descriptor.name] = _DictionaryView(
                name=descriptor.name,
                values=self._arrays[descriptor.values_path],
                offsets=self._arrays[descriptor.offsets_path],
                count=descriptor.count,
                # Complete _DictionaryView only after its name and arrays inputs are visible
                # in numpy mmap replay source open dictionaries.
            )

    def _validate_structure(self) -> CompactTransactionClock:
        # Execute the numpy mmap replay source validate structure workflow in explicit,
        # reviewable steps.
        event_count = self._manifest.event_count
        boundary_offsets = self._arrays[physical.BOUNDARY_OFFSETS]
        group_offsets = self._arrays[physical.GROUP_OFFSETS]
        _validate_strict_offsets(boundary_offsets, event_count, "boundary")
        _validate_strict_offsets(group_offsets, event_count, "group")
        # Invoke _validate_variable_offsets for protocol payload and arrays as a visible
        # numpy mmap replay source validate structure step.
        _validate_variable_offsets(
            self._arrays[physical.ENVELOPE_PROTOCOL_PAYLOAD_OFFSETS],
            self._arrays[physical.ENVELOPE_PROTOCOL_PAYLOAD_BYTES].size,
            "protocol payload",
        )
        # Invoke _validate_variable_offsets for fee component and arrays as a visible
        # numpy mmap replay source validate structure step.
        _validate_variable_offsets(
            self._arrays[physical.TRADE_FEE_OFFSETS],
            self._manifest.payload_counts.fee_components,
            "fee component",
        )
        # Assemble boundary ordinals once so the numpy mmap replay source validate
        # structure workflow shares one value.
        boundary_ordinals = self._arrays[physical.BOUNDARY_ORDINAL]
        boundary_blocks = self._arrays[physical.BOUNDARY_BLOCK_ORDINAL]
        envelope_ordinals = self._arrays[physical.ENVELOPE_BOUNDARY_ORDINAL]
        envelope_blocks = self._arrays[physical.ENVELOPE_BLOCK_ORDINAL]
        source_boundaries = self._arrays[physical.ENVELOPE_BOUNDARY_ORDINAL]
        # Evaluate the complete numpy mmap replay source validate structure any, np and
        # source boundaries condition before guarded effects.
        if np.any(source_boundaries != envelope_ordinals):
            raise ReplayPackFormatError("source boundary differs from effective boundary")
        previous_ordinal: int | None = None
        for index in range(self._manifest.boundary_count):
            # Process range(self._manifest.boundary_count) inside the bounded numpy mmap
            # replay source validate structure loop.
            ordinal = int(boundary_ordinals[index])
            if previous_ordinal is not None and ordinal <= previous_ordinal:
                raise ReplayPackFormatError("boundary ordinals are not strictly monotone")
            boundary = ReplayBoundary(
                self.network_id,
                # Pass self explicitly so ReplayBoundary receives a reviewable network id
                # and position schema id input in numpy mmap replay source validate
                # structure.
                self.position_schema_id,
                ordinal,
                int(boundary_blocks[index]),
            )
            start = int(boundary_offsets[index])
            # Assemble stop once so the numpy mmap replay source validate structure
            # workflow shares one value.
            stop = int(boundary_offsets[index + 1])
            if np.any(envelope_ordinals[start:stop] != ordinal) or np.any(
                envelope_blocks[start:stop] != boundary.block_ordinal
            ):
                raise ReplayPackFormatError("boundary offsets do not span one boundary")
            # Assemble previous ordinal once so the numpy mmap replay source validate
            # structure workflow shares one value.
            previous_ordinal = ordinal
        group_ids = self._arrays[physical.ENVELOPE_TRANSACTION_GROUP_ID]
        previous_group: tuple[int, bytes] | None = None
        for index in range(self._manifest.group_count):
            # Process range(self._manifest.group_count) inside the bounded numpy mmap
            # replay source validate structure loop.
            start = int(group_offsets[index])
            stop = int(group_offsets[index + 1])
            key = (int(envelope_ordinals[start]), group_ids[start].tobytes())
            if previous_group == key:
                raise ReplayPackFormatError("adjacent group offsets split one group")
            # Evaluate the complete numpy mmap replay source validate structure any, np
            # and envelope ordinals condition before guarded effects.
            if np.any(envelope_ordinals[start:stop] != key[0]) or any(
                group_ids[row].tobytes() != key[1] for row in range(start, stop)
            ):
                raise ReplayPackFormatError("group offsets cross canonical groups")
            previous_group = key
        # Invoke _validate_codes_and_payload_indexes as a visible step within the numpy
        # mmap replay source validate structure workflow.
        self._validate_codes_and_payload_indexes()
        for path, count, label in (
            (physical.ENVELOPE_EVENT_INDEX_VALID, event_count, "event_index"),
            (
                physical.ENVELOPE_PROTOCOL_PAYLOAD_SCHEMA_VALID,
                # Traverse envelope event index valid, event count and event index
                # explicitly so each numpy mmap replay source validate structure iteration
                # remains traceable.
                event_count,
                "protocol payload schema",
            ),
            (
                physical.CLOCK_BLOCK_HASH_VALID,
                # Traverse envelope event index valid, event count and event index
                # explicitly so each numpy mmap replay source validate structure iteration
                # remains traceable.
                self._manifest.payload_counts.blocks,
                "block_hash",
            ),
            (
                physical.TOKEN_DECIMALS_VALID,
                # Traverse envelope event index valid, event count and event index
                # explicitly so each numpy mmap replay source validate structure iteration
                # remains traceable.
                self._manifest.payload_counts.token_launches,
                "token decimals",
            ),
            (
                physical.REFERENCE_AMM_VALID,
                # Traverse envelope event index valid, event count and event index
                # explicitly so each numpy mmap replay source validate structure iteration
                # remains traceable.
                self._manifest.payload_counts.venue_trades,
                "reference AMM",
            ),
            (
                physical.REFERENCE_AMM_RESERVE_A_VALID,
                # Traverse envelope event index valid, event count and event index
                # explicitly so each numpy mmap replay source validate structure iteration
                # remains traceable.
                self._manifest.payload_counts.venue_trades,
                "reference reserve A",
            ),
            (
                physical.REFERENCE_AMM_RESERVE_B_VALID,
                # Traverse envelope event index valid, event count and event index
                # explicitly so each numpy mmap replay source validate structure iteration
                # remains traceable.
                self._manifest.payload_counts.venue_trades,
                "reference reserve B",
            ),
        ):
            _validate_bitmap_padding(self._arrays[path], count, label)
        # Keep expected failures inside the numpy mmap replay source validate structure
        # error boundary.
        try:
            # Perform the protected numpy mmap replay source validate structure operation
            # before explicit failure handling.
            clock = CompactTransactionClock(
                network_id=self.network_id,
                position_schema_id=self.position_schema_id,
                block_ordinals=tuple(
                    int(value)
                    # Pass value explicitly so tuple receives a reviewable arrays and
                    # clock block ordinal input in numpy mmap replay source validate
                    # structure.
                    for value in self._arrays[physical.CLOCK_BLOCK_ORDINAL]
                    # Complete tuple only after its arrays and clock block ordinal inputs are
                    # visible in numpy mmap replay source validate structure.
                ),
                transaction_counts=tuple(
                    int(value) for value in self._arrays[physical.CLOCK_TRANSACTION_COUNT]
                ),
                cumulative_transaction_prefix=tuple(
                    # Keep the value int step visible while building clock.
                    int(value)
                    for value in self._arrays[physical.CLOCK_CUMULATIVE_TRANSACTION_PREFIX]
                ),
                block_time_ns=tuple(
                    int(value)
                    # Pass value explicitly so tuple receives a reviewable arrays and
                    # clock block time ns input in numpy mmap replay source validate
                    # structure.
                    for value in self._arrays[physical.CLOCK_BLOCK_TIME_NS]
                    # Complete tuple only after its arrays and clock block time ns inputs are
                    # visible in numpy mmap replay source validate structure.
                ),
            )
        except (TypeError, ValueError) as error:
            # Translate the (TypeError, ValueError) failure through the numpy mmap replay
            # source validate structure boundary.
            raise ReplayPackFormatError(
                "ReplayPack compact transaction clock is invalid"
            ) from error
        self._validate_event_positions(clock)
        return clock

    # Define numpy mmap replay source validate codes and payload indexes as one focused
    # operation with an explicit boundary.
    def _validate_codes_and_payload_indexes(self) -> None:
        # Execute the numpy mmap replay source validate codes and payload indexes workflow
        # in explicit, reviewable steps.
        dictionary_fields = (
            (physical.ENVELOPE_CAPABILITY_CODE, "capabilities"),
            (physical.ENVELOPE_PROTOCOL_CODE, "protocols"),
            (physical.ENVELOPE_PROTOCOL_VERSION_CODE, "protocol_versions"),
            (physical.TOKEN_ASSET_CODE, "assets"),
            # Keep the physical component named inside the dictionary fields contract.
            (physical.TOKEN_DEVELOPER_CODE, "accounts"),
            (physical.TOKEN_CREATION_USER_CODE, "accounts"),
            (physical.TOKEN_VENUE_CODE, "venues"),
            (physical.TOKEN_QUOTE_ASSET_CODE, "assets"),
            (physical.TRADE_VENUE_CODE, "venues"),
            # Keep the physical component named inside the dictionary fields contract.
            (physical.TRADE_SOLD_ASSET_CODE, "assets"),
            (physical.TRADE_BOUGHT_ASSET_CODE, "assets"),
            (physical.TRADE_FEE_COMPONENT_CODE, "fee_component_ids"),
            (physical.TRADE_FEE_ASSET_CODE, "assets"),
            (physical.LIFECYCLE_VENUE_CODE, "venues"),
            # Complete the dictionary fields group only after its semantic components are
            # visible.
        )
        for path, dictionary_name in dictionary_fields:
            # Process dictionary_fields inside the bounded numpy mmap replay source
            # validate codes and payload indexes loop.
            _validate_dictionary_codes(
                self._arrays[path], self._dictionaries[dictionary_name], dictionary_name
            )
        _validate_optional_dictionary_codes(
            self._arrays[physical.CLOCK_BLOCK_HASH_CODE],
            # Pass self explicitly so _validate_optional_dictionary_codes receives a
            # reviewable block hashes and arrays input in numpy mmap replay source
            # validate codes and payload indexes.
            self._arrays[physical.CLOCK_BLOCK_HASH_VALID],
            self._dictionaries["block_hashes"],
            "block_hashes",
        )
        _validate_optional_dictionary_codes(
            # Pass self explicitly so _validate_optional_dictionary_codes receives a
            # reviewable protocol payload schemas and arrays input in numpy mmap replay
            # source validate codes and payload indexes.
            self._arrays[physical.ENVELOPE_PROTOCOL_PAYLOAD_SCHEMA_CODE],
            self._arrays[physical.ENVELOPE_PROTOCOL_PAYLOAD_SCHEMA_VALID],
            self._dictionaries["protocol_payload_schemas"],
            "protocol_payload_schemas",
        )
        # Assemble reference valid once so the numpy mmap replay source validate codes and
        # payload indexes workflow shares one value.
        reference_valid = self._arrays[physical.REFERENCE_AMM_VALID]
        for path in (
            physical.REFERENCE_AMM_ASSET_A_CODE,
            physical.REFERENCE_AMM_ASSET_B_CODE,
        ):
            # Process reference amm asset a code, reference amm asset b code and physical
            # inside the bounded numpy mmap replay source validate codes and payload
            # indexes loop.
            _validate_optional_dictionary_codes(
                self._arrays[path], reference_valid, self._dictionaries["assets"], "assets"
            )
        kinds = self._arrays[physical.ENVELOPE_EVENT_KIND_CODE]
        payloads = self._arrays[physical.ENVELOPE_PAYLOAD_INDEX]
        # Assemble schema valid once so the numpy mmap replay source validate codes and
        # payload indexes workflow shares one value.
        schema_valid = self._arrays[physical.ENVELOPE_PROTOCOL_PAYLOAD_SCHEMA_VALID]
        expected = {
            EventKind.BLOCK: 0,
            EventKind.TOKEN_LAUNCH: 0,
            EventKind.VENUE_TRADE: 0,
            # Keep the event kind component named inside the expected contract.
            EventKind.VENUE_LIFECYCLE: 0,
        }
        for index in range(self._manifest.event_count):
            # Process range(self._manifest.event_count) inside the bounded numpy mmap
            # replay source validate codes and payload indexes loop.
            try:
                kind = EventKind(int(kinds[index]))
            except ValueError as error:
                raise ReplayPackFormatError("ReplayPack has an unsupported event kind") from error
            if kind not in expected:
                # Fail the numpy mmap replay source validate codes and payload indexes
                # path with ReplayPackFormatError for replay pack has an unsupported event
                # kind when kind and expected is true; do not continue ambiguously.
                raise ReplayPackFormatError("ReplayPack has an unsupported event kind")
            if int(payloads[index]) != expected[kind]:
                raise ReplayPackFormatError("payload indexes are not dense and monotone")
            if _is_valid(schema_valid, index) == (kind is EventKind.BLOCK):
                raise ReplayPackFormatError("protocol payload schema presence differs from kind")
            # Assemble expected[kind] once so the numpy mmap replay source validate codes
            # and payload indexes workflow shares one value.
            expected[kind] += 1
        actual = {
            EventKind.BLOCK: self._manifest.payload_counts.blocks,
            EventKind.TOKEN_LAUNCH: self._manifest.payload_counts.token_launches,
            EventKind.VENUE_TRADE: self._manifest.payload_counts.venue_trades,
            # Keep the event kind component named inside the actual contract.
            EventKind.VENUE_LIFECYCLE: self._manifest.payload_counts.venue_lifecycles,
        }
        if expected != actual:
            raise ReplayPackFormatError("payload indexes do not cover typed payload arrays")
        fidelity = self._arrays[physical.ENVELOPE_ORDERING_FIDELITY_CODE]
        # Evaluate the complete numpy mmap replay source validate codes and payload
        # indexes size, fidelity and code to fidelity condition before guarded effects.
        if fidelity.size and any(int(value) not in _CODE_TO_FIDELITY for value in fidelity):
            raise ReplayPackFormatError("ordering fidelity code is unsupported")
        lifecycle = self._arrays[physical.LIFECYCLE_KIND_CODE]
        if lifecycle.size and any(int(value) not in _CODE_TO_LIFECYCLE for value in lifecycle):
            raise ReplayPackFormatError("venue lifecycle code is unsupported")

    # Define numpy mmap replay source validate event positions as one focused operation
    # with an explicit boundary.
    def _validate_event_positions(self, clock: CompactTransactionClock) -> None:
        # Execute the numpy mmap replay source validate event positions workflow in
        # explicit, reviewable steps.
        blocks = clock.block_ordinals
        counts = clock.transaction_counts
        clock_index = {block: index for index, block in enumerate(blocks)}
        event_blocks = self._arrays[physical.ENVELOPE_BLOCK_ORDINAL]
        transaction_indexes = self._arrays[physical.ENVELOPE_TRANSACTION_INDEX]
        # Assemble event kinds once so the numpy mmap replay source validate event
        # positions workflow shares one value.
        event_kinds = self._arrays[physical.ENVELOPE_EVENT_KIND_CODE]
        payload_indexes = self._arrays[physical.ENVELOPE_PAYLOAD_INDEX]
        for index in range(self._manifest.event_count):
            # Process range(self._manifest.event_count) inside the bounded numpy mmap
            # replay source validate event positions loop.
            block = int(event_blocks[index])
            try:
                block_index = clock_index[block]
            except KeyError as error:
                raise ReplayPackFormatError("event block is absent from compact clock") from error
            # Assemble transaction index once so the numpy mmap replay source validate
            # event positions workflow shares one value.
            transaction_index = int(transaction_indexes[index])
            kind = EventKind(int(event_kinds[index]))
            if kind is EventKind.BLOCK:
                # Handle the numpy mmap replay source validate event positions kind is
                # EventKind.BLOCK branch as a distinct logical block.
                if transaction_index != -1 or int(payload_indexes[index]) != block_index:
                    raise ReplayPackFormatError("block event differs from compact clock order")
            # Handle the numpy mmap replay source validate event positions complement of
            # kind is EventKind.BLOCK explicitly.
            elif not 0 <= transaction_index < counts[block_index]:
                raise ReplayPackFormatError("event transaction index exceeds clock tx_count")

    def _event(self, index: int) -> CanonicalEvent:
        # Execute the numpy mmap replay source event workflow in explicit, reviewable
        # steps.
        event_index = (
            int(self._arrays[physical.ENVELOPE_EVENT_INDEX][index])
            if _is_valid(self._arrays[physical.ENVELOPE_EVENT_INDEX_VALID], index)
            else None
        )
        # Assemble fidelity code once so the numpy mmap replay source event workflow
        # shares one value.
        fidelity_code = int(self._arrays[physical.ENVELOPE_ORDERING_FIDELITY_CODE][index])
        try:
            # Perform the protected numpy mmap replay source event operation before
            # explicit failure handling.
            fidelity = _CODE_TO_FIDELITY[fidelity_code]
            kind = EventKind(int(self._arrays[physical.ENVELOPE_EVENT_KIND_CODE][index]))
        except (KeyError, ValueError) as error:  # pragma: no cover - checked at open
            raise ReplayPackFormatError("unsupported envelope enum code") from error
        envelope = EventEnvelope(
            position=ChainPosition(
                network_id=self.network_id,
                position_schema_id=self.position_schema_id,
                # Keep the index and arrays int step visible while building envelope.
                block_ordinal=int(self._arrays[physical.ENVELOPE_BLOCK_ORDINAL][index]),
                transaction_index=int(self._arrays[physical.ENVELOPE_TRANSACTION_INDEX][index]),
                event_index=event_index,
            ),
            transaction_group_id=_digest(
                # Pass self explicitly so _digest receives a reviewable arrays and
                # envelope transaction group id input in numpy mmap replay source event.
                self._arrays[physical.ENVELOPE_TRANSACTION_GROUP_ID],
                index,
            ),
            source_record_id=_digest(self._arrays[physical.ENVELOPE_SOURCE_RECORD_ID], index),
            canonical_event_id=_digest(self._arrays[physical.ENVELOPE_CANONICAL_EVENT_ID], index),
            # Keep the digest and index _digest step visible while building envelope.
            stable_causal_id=_digest(self._arrays[physical.ENVELOPE_STABLE_CAUSAL_ID], index),
            # Keep the capability id and dictionary CapabilityId step visible while
            # building envelope.
            capability_id=CapabilityId(
                self._dictionary("capabilities", physical.ENVELOPE_CAPABILITY_CODE, index)
            ),
            protocol=self._dictionary("protocols", physical.ENVELOPE_PROTOCOL_CODE, index),
            protocol_version=self._dictionary(
                # Pass protocol versions explicitly so _dictionary receives a reviewable
                # protocol versions and envelope protocol version code input in numpy mmap
                # replay source event.
                "protocol_versions",
                physical.ENVELOPE_PROTOCOL_VERSION_CODE,
                index,
            ),
            ordering_fidelity=fidelity,
            # Complete EventEnvelope only after its capabilities and protocols inputs are
            # visible in numpy mmap replay source event.
        )
        stored_boundary = int(self._arrays[physical.ENVELOPE_BOUNDARY_ORDINAL][index])
        # Evaluate the complete numpy mmap replay source event boundary ordinal, stored
        # boundary and envelope condition before guarded effects.
        if envelope.boundary_ordinal != stored_boundary:
            raise ReplayPackFormatError("chain position does not match boundary ordinal")
        payload_index = int(self._arrays[physical.ENVELOPE_PAYLOAD_INDEX][index])
        if kind is EventKind.BLOCK:
            # Handle the numpy mmap replay source event kind is EventKind.BLOCK branch as
            # a distinct logical block.
            return BlockEvent(
                envelope=envelope,
                block_time_ns=int(self._arrays[physical.CLOCK_BLOCK_TIME_NS][payload_index]),
                tx_count=int(self._arrays[physical.CLOCK_TRANSACTION_COUNT][payload_index]),
                block_hash=(
                    # Include self in the completed numpy mmap replay source event result.
                    self._dictionary("block_hashes", physical.CLOCK_BLOCK_HASH_CODE, payload_index)
                    if _is_valid(self._arrays[physical.CLOCK_BLOCK_HASH_VALID], payload_index)
                    else None
                ),
            )
        # Assemble schema once so the numpy mmap replay source event workflow shares one
        # value.
        schema = ProtocolPayloadSchemaId(
            self._dictionary(
                "protocol_payload_schemas",
                physical.ENVELOPE_PROTOCOL_PAYLOAD_SCHEMA_CODE,
                index,
                # Complete _dictionary only after its protocol payload schemas and envelope
                # protocol payload schema code inputs are visible in numpy mmap replay source
                # event.
            )
        )
        protocol_payload = _byte_slice(
            self._arrays[physical.ENVELOPE_PROTOCOL_PAYLOAD_BYTES],
            self._arrays[physical.ENVELOPE_PROTOCOL_PAYLOAD_OFFSETS],
            # Pass index explicitly so _byte_slice receives a reviewable arrays and
            # envelope protocol payload bytes input in numpy mmap replay source event.
            index,
        )
        if kind is EventKind.TOKEN_LAUNCH:
            # Handle the numpy mmap replay source event kind is EventKind.TOKEN_LAUNCH
            # branch as a distinct logical block.
            return TokenLaunchEvent(
                envelope=envelope,
                asset_id=AssetId(
                    self._dictionary("assets", physical.TOKEN_ASSET_CODE, payload_index)
                ),
                # Include developer id in the completed numpy mmap replay source event
                # result.
                developer_id=AccountId(
                    self._dictionary("accounts", physical.TOKEN_DEVELOPER_CODE, payload_index)
                ),
                creation_user_id=AccountId(
                    self._dictionary("accounts", physical.TOKEN_CREATION_USER_CODE, payload_index)
                    # Complete AccountId only after its accounts and dictionary inputs are
                    # visible in numpy mmap replay source event.
                ),
                venue_id=VenueId(
                    self._dictionary("venues", physical.TOKEN_VENUE_CODE, payload_index)
                ),
                quote_asset_id=AssetId(
                    # Include self in the completed numpy mmap replay source event result.
                    self._dictionary("assets", physical.TOKEN_QUOTE_ASSET_CODE, payload_index)
                ),
                protocol_payload_schema=schema,
                protocol_payload=protocol_payload,
                decimals=(
                    # Include int in the completed numpy mmap replay source event result.
                    int(self._arrays[physical.TOKEN_DECIMALS][payload_index])
                    if _is_valid(self._arrays[physical.TOKEN_DECIMALS_VALID], payload_index)
                    else None
                ),
            )
        # Guard this path with kind is EventKind.VENUE_TRADE before applying effects.
        if kind is EventKind.VENUE_TRADE:
            # Handle the numpy mmap replay source event kind is EventKind.VENUE_TRADE
            # branch as a distinct logical block.
            start = int(self._arrays[physical.TRADE_FEE_OFFSETS][payload_index])
            stop = int(self._arrays[physical.TRADE_FEE_OFFSETS][payload_index + 1])
            fees = tuple(
                FeeComponent(
                    FeeComponentId(
                        # Keep the fee component ids _dictionary step visible while
                        # building fees.
                        self._dictionary(
                            "fee_component_ids", physical.TRADE_FEE_COMPONENT_CODE, fee_index
                        )
                    ),
                    AssetId(self._dictionary("assets", physical.TRADE_FEE_ASSET_CODE, fee_index)),
                    # Keep the int128 and fee index _int128 step visible while building
                    # fees.
                    _int128(self._arrays[physical.TRADE_FEE_AMOUNT], fee_index),
                )
                for fee_index in range(start, stop)
            )
            return VenueTradeEvent(
                # Pass envelope explicitly so VenueTradeEvent receives a reviewable venues
                # and assets input in numpy mmap replay source event.
                envelope=envelope,
                venue_id=VenueId(
                    self._dictionary("venues", physical.TRADE_VENUE_CODE, payload_index)
                ),
                sold_asset_id=AssetId(
                    # Include self in the completed numpy mmap replay source event result.
                    self._dictionary("assets", physical.TRADE_SOLD_ASSET_CODE, payload_index)
                ),
                bought_asset_id=AssetId(
                    self._dictionary("assets", physical.TRADE_BOUGHT_ASSET_CODE, payload_index)
                ),
                # Include sold amount atomic in the completed numpy mmap replay source
                # event result.
                sold_amount_atomic=_int128(self._arrays[physical.TRADE_SOLD_AMOUNT], payload_index),
                bought_amount_atomic=_int128(
                    self._arrays[physical.TRADE_BOUGHT_AMOUNT], payload_index
                ),
                fee_components=fees,
                # Pass protocol payload schema explicitly so VenueTradeEvent receives a
                # reviewable venues and assets input in numpy mmap replay source event.
                protocol_payload_schema=schema,
                protocol_payload=protocol_payload,
            )
        if kind is EventKind.VENUE_LIFECYCLE:
            # Handle the numpy mmap replay source event kind is EventKind.VENUE_LIFECYCLE
            # branch as a distinct logical block.
            return VenueLifecycleEvent(
                envelope=envelope,
                venue_id=VenueId(
                    self._dictionary("venues", physical.LIFECYCLE_VENUE_CODE, payload_index)
                ),
                # Pass lifecycle kind explicitly so VenueLifecycleEvent receives a
                # reviewable venues and dictionary input in numpy mmap replay source
                # event.
                lifecycle_kind=_CODE_TO_LIFECYCLE[
                    int(self._arrays[physical.LIFECYCLE_KIND_CODE][payload_index])
                ],
                protocol_payload_schema=schema,
                protocol_payload=protocol_payload,
                # Complete VenueLifecycleEvent only after its venues and dictionary inputs are
                # visible in numpy mmap replay source event.
            )
        raise ReplayPackFormatError("unsupported ReplayPack event kind")

    def _dictionary(self, name: str, path: str, index: int) -> str:
        return self._dictionaries[name].value(int(self._arrays[path][index]))

    def _require_open(self) -> None:
        # Execute the numpy mmap replay source require open workflow in explicit,
        # reviewable steps.
        if self._closed:
            raise ReplayPackFormatError("ReplayPack reader is closed")


def _validate_known_layout(manifest: ReplayPackManifest) -> None:
    # Execute the validate known layout workflow in explicit, reviewable steps.
    by_path = {item.path: item for item in manifest.layout.arrays}
    try:
        # Perform the protected validate known layout operation before explicit failure
        # handling.
        dictionary_sizes = {
            item.name: (item.count, by_path[item.values_path].shape[0])
            for item in manifest.layout.dictionaries
        }
        payload_byte_count = by_path[physical.ENVELOPE_PROTOCOL_PAYLOAD_BYTES].shape[0]
    # Translate key error through the validate known layout boundary without hiding other
    # errors.
    except (KeyError, IndexError) as error:
        raise ReplayPackFormatError("ReplayPack dictionary/layout is incomplete") from error
    expected = physical.build_layout(
        physical.ReplayLayoutCounts(
            events=manifest.event_count,
            # Pass boundaries explicitly so ReplayLayoutCounts receives a reviewable event
            # count and boundary count input in validate known layout.
            boundaries=manifest.boundary_count,
            groups=manifest.group_count,
            blocks=manifest.payload_counts.blocks,
            token_launches=manifest.payload_counts.token_launches,
            venue_trades=manifest.payload_counts.venue_trades,
            # Pass venue lifecycles explicitly so ReplayLayoutCounts receives a reviewable
            # event count and boundary count input in validate known layout.
            venue_lifecycles=manifest.payload_counts.venue_lifecycles,
            fee_components=manifest.payload_counts.fee_components,
            protocol_payload_bytes=payload_byte_count,
        ),
        dictionary_sizes,
        # Complete build_layout only after its replay layout counts and event count inputs are
        # visible in validate known layout.
    )
    if manifest.layout.document() != expected.document():
        raise ReplayPackFormatError("ReplayPack layout is not the supported mmap v3 schema")


def _validate_known_build(
    manifest: ReplayPackManifest,
    # Close the validate known build signature after its explicit inputs.
    *,
    compiler_bundle_id: BundleId,
    writer_bundle_id: BundleId,
) -> None:
    # Execute the validate known build workflow in explicit, reviewable steps.
    build = manifest.build
    if build.compiler_bundle_id != compiler_bundle_id:
        raise ReplayPackFormatError("ReplayPack compiler bundle is unsupported")
    if build.compiler_version != physical.COMPILER_VERSION:
        raise ReplayPackFormatError("ReplayPack compiler version is unsupported")
    # Evaluate the complete validate known build writer bundle id and build condition
    # before guarded effects.
    if build.writer_bundle_id != writer_bundle_id:
        raise ReplayPackFormatError("ReplayPack writer bundle is unsupported")
    if build.writer_settings_digest != replay_writer_settings_digest():
        raise ReplayPackFormatError("ReplayPack writer settings are unsupported")


def _validate_strict_offsets(
    # Keep the offsets input explicit in the validate strict offsets contract.
    offsets: npt.NDArray[np.generic],
    value_count: int,
    label: str,
) -> None:
    # Execute the validate strict offsets workflow in explicit, reviewable steps.
    if int(offsets[0]) != 0 or int(offsets[-1]) != value_count:
        raise ReplayPackFormatError(f"{label} offsets have invalid sentinels")
    previous = -1
    for value in offsets:
        # Process offsets inside the bounded validate strict offsets loop.
        current = int(value)
        if current <= previous:
            raise ReplayPackFormatError(f"{label} offsets are not strictly increasing")
        previous = current


def _validate_variable_offsets(
    # Keep the offsets input explicit in the validate variable offsets contract.
    offsets: npt.NDArray[np.generic],
    value_count: int,
    label: str,
) -> None:
    # Execute the validate variable offsets workflow in explicit, reviewable steps.
    if int(offsets[0]) != 0 or int(offsets[-1]) != value_count:
        raise ReplayPackFormatError(f"{label} offsets have invalid sentinels")
    previous = -1
    for value in offsets:
        # Process offsets inside the bounded validate variable offsets loop.
        current = int(value)
        if current < previous:
            raise ReplayPackFormatError(f"{label} offsets are not monotone")
        previous = current


def _validate_dictionary_codes(
    # Keep the array input explicit in the validate dictionary codes contract.
    array: npt.NDArray[np.generic],
    dictionary: _DictionaryView,
    label: str,
) -> None:
    # Execute the validate dictionary codes workflow in explicit, reviewable steps.
    if array.size and int(array.max()) >= dictionary.count:
        raise ReplayPackFormatError(f"{label} dictionary code is out of bounds")


def _validate_optional_dictionary_codes(
    array: npt.NDArray[np.generic],
    validity: npt.NDArray[np.generic],
    # Keep the dictionary input explicit in the validate optional dictionary codes
    # contract.
    dictionary: _DictionaryView,
    label: str,
) -> None:
    # Execute the validate optional dictionary codes workflow in explicit, reviewable
    # steps.
    for index in range(array.size):
        # Process range(array.size) inside the bounded validate optional dictionary codes
        # loop.
        if _is_valid(validity, index) and int(array[index]) >= dictionary.count:
            raise ReplayPackFormatError(f"{label} dictionary code is out of bounds")


def _validate_bitmap_padding(bitmap: npt.NDArray[np.generic], value_count: int, label: str) -> None:
    # Execute the validate bitmap padding workflow in explicit, reviewable steps.
    expected_size = (value_count + 7) // 8
    if bitmap.shape != (expected_size,):
        raise ReplayPackFormatError(f"{label} validity bitmap length is invalid")
    remainder = value_count % 8
    if remainder and expected_size:
        # Handle the validate bitmap padding remainder and expected_size branch as a
        # distinct logical block.
        padding_mask = (~((1 << remainder) - 1)) & 0xFF
        if int(bitmap[-1]) & padding_mask:
            raise ReplayPackFormatError(f"{label} validity bitmap padding is non-zero")


def _is_valid(bitmap: npt.NDArray[np.generic], index: int) -> bool:
    # Execute the is valid workflow in explicit, reviewable steps.
    byte_index, bit_index = divmod(index, 8)
    return bool(int(bitmap[byte_index]) & (1 << bit_index))


def _digest(array: npt.NDArray[np.generic], index: int) -> ContentDigest:
    # Execute the digest workflow in explicit, reviewable steps.
    raw = array[index].tobytes()
    if len(raw) != 32:  # pragma: no cover - dtype checked at open
        raise ReplayPackFormatError("fixed digest width is invalid")
    return ContentDigest(raw.hex())


def _int128(array: npt.NDArray[np.generic], index: int) -> int:
    # Execute the int128 workflow in explicit, reviewable steps.
    raw = array[index].tobytes()
    if len(raw) != 16:  # pragma: no cover - dtype checked at open
        raise ReplayPackFormatError("fixed Int128 width is invalid")
    return int.from_bytes(raw, "big", signed=True)


def _byte_slice(
    values: npt.NDArray[np.generic], offsets: npt.NDArray[np.generic], index: int
) -> bytes:
    # Return the completed byte slice result without a hidden fallback.
    return values[int(offsets[index]) : int(offsets[index + 1])].tobytes()


def _json_object(payload: bytes) -> dict[str, object]:
    # Execute the json object workflow in explicit, reviewable steps.
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, ValueError) as error:
        raise ReplayPackFormatError("ReplayPack manifest is invalid JSON") from error
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        # Fail the json object path with ReplayPackFormatError for replay pack manifest
        # must be a json object when isinstance, value and key is true; do not continue
        # ambiguously.
        raise ReplayPackFormatError("ReplayPack manifest must be a JSON object")
    return cast(dict[str, object], value)


__all__ = ["NumpyMmapReplaySource", "ReplayPackFormatError"]
