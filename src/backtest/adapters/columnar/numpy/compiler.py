"""Two-pass deterministic compiler from canonical v3 events to mmap ReplayPack v3."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable

# Import dataclasses at the visible module dependency boundary.
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository

# Import numpy at the visible module dependency boundary.
from backtest.adapters.columnar.numpy import layout as physical
from backtest.application.build_tool_roles import REPLAY_COMPILER_ROLE, REPLAY_WRITER_ROLE
from backtest.application.canonical_data import (
    EffectiveSourceBoundary,
    ValidationStatus,
    # Include dataset spec from snapshot document so the canonical data dependency remains
    # explicit.
    dataset_spec_from_snapshot_document,
    decision_range_from_snapshot_document,
    effective_source_boundaries_from_snapshot_document,
)
from backtest.application.code_bundles import PinnedCodeBundleIdentity, PinnedCodeBundleSet

# Import models at the visible module dependency boundary.
from backtest.application.models import ArtifactDraft, ArtifactKind, DatasetSpec
from backtest.application.replay_packs import (
    CompiledReplayPack,
    ReplayBuildManifest,
    ReplayPackManifest,
    # Include replay payload counts so the replay packs dependency remains explicit.
    ReplayPayloadCounts,
    ReplaySemanticsManifest,
)
from backtest.domain.event_hashing import CanonicalEventStreamHasher
from backtest.domain.fidelity import OrderingFidelity

# Import hashing at the visible module dependency boundary.
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.domain.identifiers import (
    BundleId,
    ContentDigest,
    LogicalContentHash,
    # Include network id so the identifiers dependency remains explicit.
    NetworkId,
    PositionSchemaId,
    ReplayPackId,
    RuntimeLockId,
    SnapshotId,
    # Close the identifiers import after its required symbols are visible.
)
from backtest.domain.market_events import (
    REFERENCE_AMM_TRADE_PAYLOAD_SCHEMA_ID,
    BlockEvent,
    CanonicalEvent,
    # Include event kind so the market events dependency remains explicit.
    EventKind,
    TokenLaunchEvent,
    VenueLifecycleEvent,
    VenueLifecycleKind,
    VenueTradeEvent,
    # Include canonical event sort key so the market events dependency remains explicit.
    canonical_event_sort_key,
)
from backtest.domain.time import BlockRange
from backtest.engine.replay import HistoricalEventSource
from backtest.engine.transaction_clock import CompactTransactionClock

# Bind compiler bundle id once as an explicit module-level contract.
_COMPILER_BUNDLE_ID: Final = BundleId(
    domain_digest(
        "backtest.numpy-replay-compiler-bundle.v5",
        {
            "canonical_identity_contract": "network-generic-event-v3",
            "boundary_materialization": "stream-derived-v1",
            # Keep clock named so the v4 and canonical identity contract payload passed to
            # domain_digest remains self-describing within module.
            "clock": "compact-block-transaction-prefix-v1",
            "compiler_version": physical.COMPILER_VERSION,
            "passes": 2,
            "preserves_input_order": True,
            "supported_event_kinds": [
                # Pass block explicitly so domain_digest receives a reviewable v4 and
                # canonical identity contract input in module.
                "BLOCK",
                "TOKEN_LAUNCH",
                "VENUE_LIFECYCLE",
                "VENUE_TRADE",
            ],
            # Close the v4 and canonical identity contract payload only after all module
            # fields are present.
        },
    ).hex
)
_WRITER_BUNDLE_ID: Final = BundleId(
    domain_digest(
        # Pass version tag explicitly so domain_digest receives a reviewable v2 and
        # container input in module.
        "backtest.numpy-replay-writer-bundle.v2",
        {
            "container": "numpy-npy-v1",
            "dictionary_order": "utf8-byte-lexicographic-v1",
            "indexes": "sentinel-offsets-v1",
            # Keep nullable named so the v2 and container payload passed to domain_digest
            # remains self-describing within module.
            "nullable": "packed-lsb0-one-is-valid-v1",
            "protocol_payload": "exact-bytes-offsets-v1",
        },
    ).hex
)
# Bind writer settings digest once as an explicit module-level contract.
_WRITER_SETTINGS_DIGEST: Final = domain_digest(
    "backtest.numpy-replay-writer-settings.v2",
    {
        "allow_pickle": False,
        "array_order": "C",
        # Keep dictionary code dtype named so the v2 and allow pickle payload passed to
        # domain_digest remains self-describing within module.
        "dictionary_code_dtype": "<u4",
        "numeric_byte_order": "little",
        "protocol_payload": "exact-bytes-offsets-v1",
        "wide_integer_encoding": "signed-int128-big-endian-fixed16",
    },
    # Complete domain_digest only after its v2 and allow pickle inputs are visible in module.
)

_FIDELITY_CODES: Final = {
    OrderingFidelity.UNKNOWN: 0,
    OrderingFidelity.TRANSACTION_PARTIAL: 1,
    OrderingFidelity.TRANSACTION_EXACT: 2,
    # Keep the ordering fidelity component named inside the fidelity codes contract.
    OrderingFidelity.INSTRUCTION_EXACT: 3,
}
_LIFECYCLE_CODES: Final = {
    VenueLifecycleKind.COMPLETED: 1,
    VenueLifecycleKind.MIGRATED: 2,
    # Keep the venue lifecycle kind component named inside the lifecycle codes contract.
    VenueLifecycleKind.CLOSED: 3,
}


class ReplayPackCompileError(RuntimeError):
    """Canonical input cannot be compiled without changing its semantics."""


@dataclass(frozen=True, slots=True)
class _DictionaryMaterial:
    values: tuple[str, ...]
    blob: bytes
    offsets: tuple[int, ...]

    # Apply property semantics to the following dictionary material codes contract.
    @property
    def codes(self) -> dict[str, int]:
        return {value: index for index, value in enumerate(self.values)}


# Keep the clock row contract and validation rules together.
@dataclass(frozen=True, slots=True)
class _ClockRow:
    block_ordinal: int
    transaction_count: int
    cumulative_transaction_prefix: int
    # Declare block time ns explicitly in the clock row contract.
    block_time_ns: int
    block_hash: str | None


# Keep the scan summary contract and validation rules together.
@dataclass(frozen=True, slots=True)
class _ScanSummary:
    network_id: NetworkId
    position_schema_id: PositionSchemaId
    event_count: int
    # Declare boundary count explicitly in the scan summary contract.
    boundary_count: int
    group_count: int
    payload_counts: ReplayPayloadCounts
    protocol_payload_bytes: int
    logical_hash: LogicalContentHash
    # Declare dictionaries explicitly in the scan summary contract.
    dictionaries: dict[str, _DictionaryMaterial]
    clock_rows: tuple[_ClockRow, ...]


# Keep the snapshot input contract and validation rules together.
@dataclass(frozen=True, slots=True)
class _SnapshotInput:
    source_boundaries: tuple[EffectiveSourceBoundary, ...]
    decision_range: BlockRange
    dataset_spec: DatasetSpec


# Keep the local numpy replay pack compiler contract and validation rules together.
class LocalNumpyReplayPackCompiler:
    """Compile snapshot v4/canonical schema v3 into deterministic NumPy arrays."""

    def __init__(
        self,
        artifacts: LocalArtifactRepository,
        source_factory: Callable[[SnapshotId], HistoricalEventSource],
        *,
        # Keep the runtime lock id input explicit in the init contract.
        runtime_lock_id: RuntimeLockId,
        compiler_bundle_id: BundleId | None = None,
        writer_bundle_id: BundleId | None = None,
        build_tools: PinnedCodeBundleSet | None = None,
    ) -> None:
        # Execute the local numpy replay pack compiler init workflow in explicit,
        # reviewable steps.
        self._artifacts = artifacts
        self._source_factory = source_factory
        self._runtime_lock_id = runtime_lock_id
        self._build_tools = build_tools or unit_replay_build_tools(
            compiler_bundle_id=compiler_bundle_id,
            # Pass writer bundle id explicitly so unit_replay_build_tools receives a
            # reviewable compiler bundle id and writer bundle id input in local numpy
            # replay pack compiler init.
            writer_bundle_id=writer_bundle_id,
        )
        self._compiler_bundle_id = self._build_tools.require_current(REPLAY_COMPILER_ROLE)
        self._writer_bundle_id = self._build_tools.require_current(REPLAY_WRITER_ROLE)
        self._tmp_root = artifacts.data_root / "tmp" / "replay"
        # Invoke mkdir as a visible step within the local numpy replay pack compiler init
        # workflow.
        self._tmp_root.mkdir(parents=True, exist_ok=True)

    def compile(self, snapshot_id: SnapshotId, compiler_version: str) -> CompiledReplayPack:
        # Execute the local numpy replay pack compiler compile workflow in explicit,
        # reviewable steps.
        if compiler_version != physical.COMPILER_VERSION:
            raise ReplayPackCompileError(f"compiler version must be {physical.COMPILER_VERSION!r}")
        self._require_current_tools()
        snapshot_input = self._verify_snapshot_input(snapshot_id)
        source_boundaries = snapshot_input.source_boundaries
        # Assemble source once so the local numpy replay pack compiler compile workflow
        # shares one value.
        source = self._source_factory(snapshot_id)
        source_claim = getattr(source, "source_boundaries", None)
        if source_claim is not None and source_claim != source_boundaries:
            # Handle the local numpy replay pack compiler compile source claim and source
            # boundaries condition as a distinct block.
            raise ReplayPackCompileError(
                "canonical source fidelity differs from the exact snapshot manifest"
            )
        source_decision_range = getattr(source, "decision_range", None)
        if (
            # Keep source decision range visible while evaluating the source decision
            # range, decision range and snapshot input guard.
            source_decision_range is not None
            and source_decision_range != snapshot_input.decision_range
        ):
            # Handle the local numpy replay pack compiler compile source decision range,
            # decision range and snapshot input condition as a distinct block.
            raise ReplayPackCompileError(
                "canonical source decision range differs from the exact snapshot manifest"
            )
        source_dataset_spec = getattr(source, "dataset_spec", None)
        if source_dataset_spec is not None and source_dataset_spec != snapshot_input.dataset_spec:
            # Handle the local numpy replay pack compiler compile source dataset spec,
            # dataset spec and snapshot input condition as a distinct block.
            raise ReplayPackCompileError(
                "canonical source DatasetSpec differs from the exact snapshot manifest"
            )
        semantics = ReplaySemanticsManifest.canonical_v3()
        if source.replay_semantics_id != semantics.replay_semantics_id:
            # Fail the local numpy replay pack compiler compile path with
            # ReplayPackCompileError for canonical source replay semantics are
            # incompatible when replay semantics id, source and semantics is true; do not
            # continue ambiguously.
            raise ReplayPackCompileError("canonical source replay semantics are incompatible")
        # Boundary rows are a deterministic projection of the canonical event stream.
        # Derive them during the two existing passes instead of materializing millions
        # of Python ReplayBoundary objects before compilation.
        summary = _scan_source(source)
        if summary.logical_hash != source.logical_content_hash:
            raise ReplayPackCompileError("canonical source logical stream hash changed")
        # Evaluate the complete local numpy replay pack compiler compile boundary, source
        # boundaries and network id condition before guarded effects.
        if any(
            boundary.source_boundary.block_range.network_id != summary.network_id
            or boundary.source_boundary.block_range.position_schema_id != summary.position_schema_id
            for boundary in source_boundaries
        ):
            # Fail the local numpy replay pack compiler compile path with
            # ReplayPackCompileError for snapshot and canonical stream chain identities
            # differ when boundary, source boundaries and network id is true; do not
            # continue ambiguously.
            raise ReplayPackCompileError("snapshot and canonical stream chain identities differ")

        counts = physical.ReplayLayoutCounts(
            events=summary.event_count,
            boundaries=summary.boundary_count,
            groups=summary.group_count,
            # Pass blocks explicitly so ReplayLayoutCounts receives a reviewable event
            # count and boundary count input in local numpy replay pack compiler compile.
            blocks=summary.payload_counts.blocks,
            token_launches=summary.payload_counts.token_launches,
            venue_trades=summary.payload_counts.venue_trades,
            venue_lifecycles=summary.payload_counts.venue_lifecycles,
            fee_components=summary.payload_counts.fee_components,
            # Pass protocol payload bytes explicitly so ReplayLayoutCounts receives a
            # reviewable event count and boundary count input in local numpy replay pack
            # compiler compile.
            protocol_payload_bytes=summary.protocol_payload_bytes,
        )
        layout = physical.build_layout(
            counts,
            {
                # Keep the values len step visible while building layout.
                name: (len(material.values), len(material.blob))
                for name, material in summary.dictionaries.items()
            },
        )
        build = ReplayBuildManifest(
            # Pass snapshot id explicitly so ReplayBuildManifest receives a reviewable
            # replay semantics id and replay layout schema id input in local numpy replay
            # pack compiler compile.
            snapshot_id=snapshot_id,
            replay_semantics_id=semantics.replay_semantics_id,
            replay_layout_schema_id=layout.replay_layout_schema_id,
            compiler_bundle_id=self._compiler_bundle_id,
            writer_bundle_id=self._writer_bundle_id,
            # Pass runtime lock id explicitly so ReplayBuildManifest receives a reviewable
            # replay semantics id and replay layout schema id input in local numpy replay
            # pack compiler compile.
            runtime_lock_id=self._runtime_lock_id,
            writer_settings_digest=_WRITER_SETTINGS_DIGEST,
            compiler_version=physical.COMPILER_VERSION,
        )
        manifest = ReplayPackManifest(
            # Pass snapshot id explicitly so ReplayPackManifest receives a reviewable
            # dataset revision id and network id input in local numpy replay pack compiler
            # compile.
            snapshot_id=snapshot_id,
            dataset_revision_id=source.dataset_revision_id,
            network_id=summary.network_id,
            position_schema_id=summary.position_schema_id,
            decision_range=snapshot_input.decision_range,
            # Pass dataset spec explicitly so ReplayPackManifest receives a reviewable
            # dataset revision id and network id input in local numpy replay pack compiler
            # compile.
            dataset_spec=snapshot_input.dataset_spec,
            logical_content_hash=source.logical_content_hash,
            logical_output_stream_hash=summary.logical_hash,
            source_boundaries=source_boundaries,
            semantics=semantics,
            # Pass layout explicitly so ReplayPackManifest receives a reviewable dataset
            # revision id and network id input in local numpy replay pack compiler
            # compile.
            layout=layout,
            build=build,
            event_count=summary.event_count,
            boundary_count=summary.boundary_count,
            group_count=summary.group_count,
            # Pass payload counts explicitly so ReplayPackManifest receives a reviewable
            # dataset revision id and network id input in local numpy replay pack compiler
            # compile.
            payload_counts=summary.payload_counts,
        )

        writer = self._artifacts.stage(
            ArtifactDraft(
                kind=ArtifactKind.REPLAY_PACK,
                # Pass build key explicitly so ArtifactDraft receives a reviewable replay
                # pack and replay build key input in local numpy replay pack compiler
                # compile.
                build_key=build.replay_build_key,
                input_artifact_ids=(snapshot_id,),
            )
        )
        temporary_root = Path(tempfile.mkdtemp(prefix="pack-", dir=self._tmp_root))
        # Keep expected failures inside the local numpy replay pack compiler compile error
        # boundary.
        try:
            # Perform the protected local numpy replay pack compiler compile operation
            # before explicit failure handling.
            _materialize_arrays(temporary_root, source, summary, manifest)
            for array in manifest.layout.arrays:
                # Process manifest.layout.arrays inside the bounded local numpy replay
                # pack compiler compile loop.
                with (
                    (temporary_root / array.path).open("rb") as source_stream,
                    writer.open_binary(array.path) as destination,
                ):
                    shutil.copyfileobj(source_stream, destination, length=1024 * 1024)
            # Assemble committed once so the local numpy replay pack compiler compile
            # workflow shares one value.
            committed = writer.commit(
                canonical_json_bytes(manifest.document()),
                identity_manifest_bytes=canonical_json_bytes(manifest.identity_document()),
            )
        except BaseException:
            # Translate the BaseException failure through the local numpy replay pack
            # compiler compile boundary.
            writer.abort()
            raise
        finally:
            shutil.rmtree(temporary_root, ignore_errors=True)
        replay_pack_id = ReplayPackId(committed.artifact_id.hex)
        # Return the completed local numpy replay pack compiler compile result without a
        # hidden fallback.
        return CompiledReplayPack(
            artifact=committed,
            replay_pack_id=replay_pack_id,
            manifest=self._read_committed_manifest(replay_pack_id),
            requested_build=build,
            # Complete CompiledReplayPack only after its read committed manifest and committed
            # inputs are visible in local numpy replay pack compiler compile.
        )

    def _verify_snapshot_input(self, snapshot_id: SnapshotId) -> _SnapshotInput:
        with self._artifacts.open_committed(snapshot_id) as handle:  # type: ignore[attr-defined]
            if handle.descriptor.kind is not ArtifactKind.SNAPSHOT:
                raise ReplayPackCompileError("ReplayPack input must be a committed snapshot")
            with handle.open_binary("manifest.json") as stream:
                manifest_bytes = stream.read()
        try:
            # Perform the protected local numpy replay pack compiler verify snapshot input
            # operation before explicit failure handling.
            manifest = json.loads(manifest_bytes)
            if canonical_json_bytes(manifest) != manifest_bytes:
                raise ValueError("snapshot manifest is not canonical JSON")
            boundaries = effective_source_boundaries_from_snapshot_document(manifest)
            decision_range = decision_range_from_snapshot_document(manifest)
            # Assemble dataset spec once so the local numpy replay pack compiler verify
            # snapshot input workflow shares one value.
            dataset_spec = dataset_spec_from_snapshot_document(manifest)
            if any(
                item.source_boundary.validation_status is not ValidationStatus.PASS
                for item in boundaries
            ):
                # Fail the local numpy replay pack compiler verify snapshot input path
                # with ValueError for snapshot contains an unvalidated source boundary
                # when validation status, pass and item is true; do not continue
                # ambiguously.
                raise ValueError("snapshot contains an unvalidated source boundary")
            return _SnapshotInput(boundaries, decision_range, dataset_spec)
        except (TypeError, ValueError) as error:
            # Translate the (TypeError, ValueError) failure through the local numpy replay
            # pack compiler verify snapshot input boundary.
            raise ReplayPackCompileError(
                "snapshot does not implement the snapshot v4/canonical schema v3 fidelity contract"
            ) from error

    def _read_committed_manifest(self, replay_pack_id: ReplayPackId) -> ReplayPackManifest:
        # Execute the local numpy replay pack compiler read committed manifest workflow in
        # explicit, reviewable steps.
        with (
            self._artifacts.open_committed(replay_pack_id) as handle,  # type: ignore[attr-defined]
            handle.open_binary("manifest.json") as stream,
        ):
            value = json.loads(stream.read())
        try:
            return ReplayPackManifest.from_document(value)
        except (TypeError, ValueError) as error:  # pragma: no cover - compiler authored it
            raise ReplayPackCompileError("committed ReplayPack manifest is invalid") from error

    def _require_current_tools(self) -> None:
        # Execute the local numpy replay pack compiler require current tools workflow in
        # explicit, reviewable steps.
        if (
            self._build_tools.require_current(REPLAY_COMPILER_ROLE) != self._compiler_bundle_id
            or self._build_tools.require_current(REPLAY_WRITER_ROLE) != self._writer_bundle_id
        ):
            raise ReplayPackCompileError("ReplayPack build tool identity changed")


# Define unit replay build tools as one focused operation with an explicit boundary.
def unit_replay_build_tools(
    *,
    compiler_bundle_id: BundleId | None = None,
    writer_bundle_id: BundleId | None = None,
) -> PinnedCodeBundleSet:
    # Execute the unit replay build tools workflow in explicit, reviewable steps.
    return PinnedCodeBundleSet(
        tuple(
            sorted(
                (
                    PinnedCodeBundleIdentity.for_unit_tests(
                        # Pass replay compiler role explicitly so for_unit_tests receives
                        # a reviewable replay compiler role and compiler bundle id input
                        # in unit replay build tools.
                        REPLAY_COMPILER_ROLE,
                        _COMPILER_BUNDLE_ID if compiler_bundle_id is None else compiler_bundle_id,
                    ),
                    PinnedCodeBundleIdentity.for_unit_tests(
                        REPLAY_WRITER_ROLE,
                        # Pass writer bundle id explicitly so for_unit_tests receives a
                        # reviewable replay writer role and writer bundle id input in unit
                        # replay build tools.
                        _WRITER_BUNDLE_ID if writer_bundle_id is None else writer_bundle_id,
                    ),
                ),
                key=lambda item: item.role,
            )
            # Complete tuple only after its for unit tests and role inputs are visible in unit
            # replay build tools.
        )
    )


def replay_writer_settings_digest() -> ContentDigest:
    return ContentDigest(_WRITER_SETTINGS_DIGEST.hex)


def _scan_source(
    # Keep the source input explicit in the scan source contract.
    source: HistoricalEventSource,
) -> _ScanSummary:
    # Execute the scan source workflow in explicit, reviewable steps.
    values: dict[str, set[str]] = {name: set() for name in physical.DICTIONARY_NAMES}
    network_id: NetworkId | None = None
    position_schema_id: PositionSchemaId | None = None
    event_count = boundary_count = group_count = 0
    blocks = token_launches = venue_trades = venue_lifecycles = fee_components = 0
    protocol_payload_bytes = 0
    # Assemble previous sort key once so the scan source workflow shares one value.
    previous_sort_key: tuple[str, str, int, str, int, str] | None = None
    previous_group: tuple[int, str] | None = None
    previous_boundary: int | None = None
    current_clock: _ClockRow | None = None
    cumulative_prefix = 0
    # Assemble clock rows once so the scan source workflow shares one value.
    clock_rows: list[_ClockRow] = []
    stream_hasher = CanonicalEventStreamHasher()

    for event in source.events():
        # Process source.events() inside the bounded scan source loop.
        sort_key = canonical_event_sort_key(event)
        if previous_sort_key is not None and sort_key < previous_sort_key:
            raise ReplayPackCompileError("canonical source event order is not monotone")
        previous_sort_key = sort_key
        envelope = event.envelope
        # Assemble position once so the scan source workflow shares one value.
        position = envelope.position
        if network_id is None:
            network_id = position.network_id
            position_schema_id = position.position_schema_id
        if position.network_id != network_id or position.position_schema_id != position_schema_id:
            # Fail the scan source path with ReplayPackCompileError for canonical source
            # mixes chain identities when network id, position schema id and position is
            # true; do not continue ambiguously.
            raise ReplayPackCompileError("canonical source mixes chain identities")
        if envelope.boundary_ordinal != previous_boundary:
            # Handle the scan source boundary ordinal, previous boundary and envelope
            # condition as a distinct block.
            if previous_boundary is not None and envelope.boundary_ordinal <= previous_boundary:
                raise ReplayPackCompileError("replay boundaries must be strictly monotone")
            # Assemble previous boundary once so the scan source workflow shares one
            # value.
            previous_boundary = envelope.boundary_ordinal
            boundary_count += 1
        group = (envelope.boundary_ordinal, envelope.transaction_group_id.hex)
        if group != previous_group:
            # Handle the scan source group != previous_group branch as a distinct logical
            # block.
            group_count += 1
            previous_group = group
        _add(values["capabilities"], envelope.capability_id.value, "capability")
        _add(values["protocols"], envelope.protocol, "protocol")
        _add(values["protocol_versions"], envelope.protocol_version, "protocol version")

        # Guard this path with isinstance(event, BlockEvent) before applying effects.
        if isinstance(event, BlockEvent):
            # Handle the scan source isinstance(event, BlockEvent) branch as a distinct
            # logical block.
            if event.block_time_ns is None or event.tx_count is None:
                # Handle the scan source block time ns, tx count and event condition as a
                # distinct block.
                raise ReplayPackCompileError(
                    "ReplayPack v3 requires exact block_time_ns and transaction_count"
                )
            if current_clock is not None and position.block_ordinal <= current_clock.block_ordinal:
                raise ReplayPackCompileError("block clock rows must be strictly monotone")
            # Assemble current clock once so the scan source workflow shares one value.
            current_clock = _ClockRow(
                block_ordinal=position.block_ordinal,
                transaction_count=event.tx_count,
                cumulative_transaction_prefix=cumulative_prefix,
                block_time_ns=event.block_time_ns,
                # Pass block hash explicitly so _ClockRow receives a reviewable block
                # ordinal and tx count input in scan source.
                block_hash=event.block_hash,
            )
            cumulative_prefix += event.tx_count
            clock_rows.append(current_clock)
            blocks += 1
            # Guard this path with event.block_hash is not None before applying effects.
            if event.block_hash is not None:
                _add(values["block_hashes"], event.block_hash, "block hash")
        else:
            # Handle the scan source complement of isinstance(event, BlockEvent)
            # explicitly.
            if current_clock is None or current_clock.block_ordinal != position.block_ordinal:
                raise ReplayPackCompileError("event has no preceding exact block-clock row")
            if not 0 <= position.transaction_index < current_clock.transaction_count:
                raise ReplayPackCompileError("event transaction index exceeds block tx_count")
            schema, payload = _protocol_payload(event)
            # Invoke _add for protocol payload schemas and protocol payload schema as a
            # visible scan source step.
            _add(values["protocol_payload_schemas"], schema, "protocol payload schema")
            protocol_payload_bytes += len(payload)
            if isinstance(event, TokenLaunchEvent):
                # Handle the scan source isinstance(event, TokenLaunchEvent) branch as a
                # distinct logical block.
                token_launches += 1
                for account in (event.developer_id.value, event.creation_user_id.value):
                    _add(values["accounts"], account, "account")
                for asset in (event.asset_id.value, event.quote_asset_id.value):
                    _add(values["assets"], asset, "asset")
                # Invoke _add for venues and venue as a visible scan source step.
                _add(values["venues"], event.venue_id.value, "venue")
            # Handle the scan source complement of isinstance(event, TokenLaunchEvent)
            # explicitly.
            elif isinstance(event, VenueTradeEvent):
                # Handle the scan source isinstance(event, VenueTradeEvent) branch as a
                # distinct logical block.
                venue_trades += 1
                _add(values["venues"], event.venue_id.value, "venue")
                for asset in (event.sold_asset_id.value, event.bought_asset_id.value):
                    _add(values["assets"], asset, "asset")
                fee_components += len(event.fee_components)
                # Traverse event.fee_components explicitly so each scan source iteration
                # remains traceable.
                for component in event.fee_components:
                    # Process event.fee_components inside the bounded scan source loop.
                    _add(
                        values["fee_component_ids"],
                        component.component_id.value,
                        "fee component",
                    )
                    # Invoke _add for assets and fee asset as a visible scan source step.
                    _add(values["assets"], component.asset_id.value, "fee asset")
                if event.protocol_payload_schema == REFERENCE_AMM_TRADE_PAYLOAD_SCHEMA_ID:
                    # Handle the scan source protocol payload schema, reference amm trade
                    # payload schema id and event condition as a distinct block.
                    _add(values["assets"], event.pool_asset_a_id.value, "asset")
                    _add(values["assets"], event.pool_asset_b_id.value, "asset")
                    _ = event.fee_amount_atomic
            # Handle the scan source complement of isinstance(event, VenueTradeEvent)
            # explicitly.
            elif isinstance(event, VenueLifecycleEvent):
                # Handle the scan source isinstance(event, VenueLifecycleEvent) branch as
                # a distinct logical block.
                venue_lifecycles += 1
                _add(values["venues"], event.venue_id.value, "venue")
            else:  # pragma: no cover - CanonicalEvent is exhaustive
                raise ReplayPackCompileError(f"unsupported event type {type(event).__name__}")
        stream_hasher.update(event)
        event_count += 1

    if event_count == 0 or not clock_rows or network_id is None or position_schema_id is None:
        raise ReplayPackCompileError("canonical source has no events or exact block clock")
    _validate_clock(network_id, position_schema_id, clock_rows)
    dictionaries = {name: _dictionary_material(items) for name, items in sorted(values.items())}
    if any(len(item.values) > physical.UINT32_MAX for item in dictionaries.values()):
        # Fail the scan source path with ReplayPackCompileError for replay pack dictionary
        # exceeds uint32 codes when uint32 max, item and values is true; do not continue
        # ambiguously.
        raise ReplayPackCompileError("ReplayPack dictionary exceeds UInt32 codes")
    return _ScanSummary(
        network_id=network_id,
        position_schema_id=position_schema_id,
        event_count=event_count,
        # Pass boundary count explicitly so _ScanSummary receives a reviewable network id
        # and position schema id input in scan source.
        boundary_count=boundary_count,
        group_count=group_count,
        payload_counts=ReplayPayloadCounts(
            blocks=blocks,
            token_launches=token_launches,
            # Pass venue trades explicitly so ReplayPayloadCounts receives a reviewable
            # blocks and token launches input in scan source.
            venue_trades=venue_trades,
            venue_lifecycles=venue_lifecycles,
            fee_components=fee_components,
        ),
        protocol_payload_bytes=protocol_payload_bytes,
        # Include logical hash in the completed scan source result.
        logical_hash=stream_hasher.logical_content_hash(),
        dictionaries=dictionaries,
        clock_rows=tuple(clock_rows),
    )


def _validate_clock(
    network_id: NetworkId,
    position_schema_id: PositionSchemaId,
    rows: list[_ClockRow],
) -> None:
    # Execute the validate clock workflow in explicit, reviewable steps.
    try:
        # Perform the protected validate clock operation before explicit failure handling.
        CompactTransactionClock(
            network_id=network_id,
            position_schema_id=position_schema_id,
            block_ordinals=tuple(row.block_ordinal for row in rows),
            transaction_counts=tuple(row.transaction_count for row in rows),
            # Pass cumulative transaction prefix explicitly to CompactTransactionClock for
            # network id and position schema id.
            cumulative_transaction_prefix=tuple(row.cumulative_transaction_prefix for row in rows),
            block_time_ns=tuple(row.block_time_ns for row in rows),
        )
    except (TypeError, ValueError) as error:
        raise ReplayPackCompileError("canonical block clock is invalid") from error


# Define dictionary material as one focused operation with an explicit boundary.
def _dictionary_material(values: set[str]) -> _DictionaryMaterial:
    # Execute the dictionary material workflow in explicit, reviewable steps.
    ordered = tuple(sorted(values, key=lambda item: item.encode("utf-8")))
    chunks = [item.encode("utf-8") for item in ordered]
    offsets = [0]
    for chunk in chunks:
        offsets.append(offsets[-1] + len(chunk))
    # Return the completed dictionary material result without a hidden fallback.
    return _DictionaryMaterial(ordered, b"".join(chunks), tuple(offsets))


def _add(destination: set[str], value: str, label: str) -> None:
    # Execute the add workflow in explicit, reviewable steps.
    if not value or value != value.strip():
        raise ReplayPackCompileError(f"{label} dictionary value is empty or untrimmed")
    destination.add(value)


def _protocol_payload(
    event: TokenLaunchEvent | VenueTradeEvent | VenueLifecycleEvent,
    # Keep the tuple input explicit in the protocol payload contract.
) -> tuple[str, bytes]:
    return event.protocol_payload_schema.value, event.protocol_payload


def _materialize_arrays(
    root: Path,
    source: HistoricalEventSource,
    summary: _ScanSummary,
    manifest: ReplayPackManifest,
) -> None:
    # Execute the materialize arrays workflow in explicit, reviewable steps.
    arrays: dict[str, Any] = {}
    try:
        # Perform the protected materialize arrays operation before explicit failure
        # handling.
        for descriptor in manifest.layout.arrays:
            # Process manifest.layout.arrays inside the bounded materialize arrays loop.
            destination = root / descriptor.path
            destination.parent.mkdir(parents=True, exist_ok=True)
            array = np.lib.format.open_memmap(
                destination,
                mode="w+",
                # Keep the dtype dtype step visible while building array.
                dtype=np.dtype(descriptor.dtype),
                shape=descriptor.shape,
                fortran_order=False,
            )
            array[...] = bytes(array.dtype.itemsize) if array.dtype.kind == "V" else 0
            # Assemble arrays[descriptor path] once so the materialize arrays workflow
            # shares one value.
            arrays[descriptor.path] = array

        _write_dictionaries(arrays, summary.dictionaries)
        _write_clock(arrays, summary)
        dictionary_codes = {name: material.codes for name, material in summary.dictionaries.items()}
        payload_index = {
            EventKind.BLOCK: 0,
            # Keep the event kind component named inside the payload index contract.
            EventKind.TOKEN_LAUNCH: 0,
            EventKind.VENUE_TRADE: 0,
            EventKind.VENUE_LIFECYCLE: 0,
        }
        boundary_index = group_index = -1
        # Assemble fee index once so the materialize arrays workflow shares one value.
        fee_index = protocol_payload_offset = 0
        previous_boundary: int | None = None
        previous_group: tuple[int, str] | None = None
        previous_sort_key: tuple[str, str, int, str, int, str] | None = None
        stream_hasher = CanonicalEventStreamHasher()
        # Assemble arrays, envelope protocol payload offsets and physical once so the
        # materialize arrays workflow shares one value.
        arrays[physical.ENVELOPE_PROTOCOL_PAYLOAD_OFFSETS][0] = 0
        arrays[physical.TRADE_FEE_OFFSETS][0] = 0

        for row_index, event in enumerate(source.events()):
            # Process enumerate(source.events()) inside the bounded materialize arrays
            # loop.
            if row_index >= summary.event_count:
                raise ReplayPackCompileError("canonical source grew between compiler passes")
            sort_key = canonical_event_sort_key(event)
            if previous_sort_key is not None and sort_key < previous_sort_key:
                raise ReplayPackCompileError("canonical source reordered between compiler passes")
            # Assemble previous sort key once so the materialize arrays workflow shares
            # one value.
            previous_sort_key = sort_key
            envelope = event.envelope
            if envelope.boundary_ordinal != previous_boundary:
                # Handle the materialize arrays boundary ordinal, previous boundary and
                # envelope condition as a distinct block.
                if boundary_index >= 0:
                    arrays[physical.BOUNDARY_OFFSETS][boundary_index + 1] = row_index
                boundary_index += 1
                if boundary_index >= summary.boundary_count:
                    raise ReplayPackCompileError("boundary count changed between compiler passes")
                if previous_boundary is not None and envelope.boundary_ordinal <= previous_boundary:
                    raise ReplayPackCompileError("boundary order changed between compiler passes")
                if (
                    envelope.position.network_id != summary.network_id
                    or envelope.position.position_schema_id != summary.position_schema_id
                ):
                    raise ReplayPackCompileError("chain identity changed between compiler passes")
                arrays[physical.BOUNDARY_ORDINAL][boundary_index] = envelope.boundary_ordinal
                arrays[physical.BOUNDARY_BLOCK_ORDINAL][boundary_index] = (
                    envelope.position.block_ordinal
                )
                if boundary_index == 0:
                    arrays[physical.BOUNDARY_OFFSETS][0] = 0
                # Assemble previous boundary once so the materialize arrays workflow
                # shares one value.
                previous_boundary = envelope.boundary_ordinal
            group = (envelope.boundary_ordinal, envelope.transaction_group_id.hex)
            if group != previous_group:
                # Handle the materialize arrays group != previous_group branch as a
                # distinct logical block.
                if group_index >= 0:
                    arrays[physical.GROUP_OFFSETS][group_index + 1] = row_index
                group_index += 1
                if group_index == 0:
                    arrays[physical.GROUP_OFFSETS][0] = 0
                # Assemble previous group once so the materialize arrays workflow shares
                # one value.
                previous_group = group
            protocol_payload_offset = _write_envelope(
                arrays,
                dictionary_codes,
                row_index,
                # Pass event explicitly so _write_envelope receives a reviewable kind and
                # arrays input in materialize arrays.
                event,
                payload_index[event.kind],
                protocol_payload_offset,
            )
            fee_index = _write_payload(
                # Pass arrays explicitly so _write_payload receives a reviewable kind and
                # arrays input in materialize arrays.
                arrays,
                dictionary_codes,
                payload_index[event.kind],
                event,
                fee_index,
                # Complete _write_payload only after its kind and arrays inputs are visible in
                # materialize arrays.
            )
            payload_index[event.kind] += 1
            stream_hasher.update(event)

        arrays[physical.BOUNDARY_OFFSETS][boundary_index + 1] = summary.event_count
        arrays[physical.GROUP_OFFSETS][group_index + 1] = summary.event_count
        # Evaluate the complete materialize arrays boundary count, group count and
        # boundary index condition before guarded effects.
        if boundary_index + 1 != summary.boundary_count or group_index + 1 != summary.group_count:
            raise ReplayPackCompileError("group or boundary count changed between passes")
        expected_payload_counts = {
            EventKind.BLOCK: summary.payload_counts.blocks,
            EventKind.TOKEN_LAUNCH: summary.payload_counts.token_launches,
            # Keep the event kind component named inside the expected payload counts
            # contract.
            EventKind.VENUE_TRADE: summary.payload_counts.venue_trades,
            EventKind.VENUE_LIFECYCLE: summary.payload_counts.venue_lifecycles,
        }
        if payload_index != expected_payload_counts:
            raise ReplayPackCompileError("payload counts changed between compiler passes")
        # Evaluate the complete materialize arrays fee index, fee components and payload
        # counts condition before guarded effects.
        if fee_index != summary.payload_counts.fee_components:
            raise ReplayPackCompileError("fee component count changed between compiler passes")
        if protocol_payload_offset != summary.protocol_payload_bytes:
            raise ReplayPackCompileError("protocol payload size changed between compiler passes")
        if stream_hasher.logical_content_hash() != summary.logical_hash:
            # Fail the materialize arrays path with ReplayPackCompileError for logical
            # stream changed between compiler passes when logical hash, logical content
            # hash and summary is true; do not continue ambiguously.
            raise ReplayPackCompileError("logical stream changed between compiler passes")
        for array in arrays.values():
            array.flush()
    finally:
        # Handle the cleanup path after the protected materialize arrays operation.
        for array in arrays.values():
            # Process arrays.values() inside the bounded materialize arrays loop.
            mmap = getattr(array, "_mmap", None)
            if mmap is not None:
                mmap.close()
        arrays.clear()


def _write_dictionaries(
    # Keep the arrays input explicit in the write dictionaries contract.
    arrays: dict[str, Any],
    dictionaries: dict[str, _DictionaryMaterial],
) -> None:
    # Execute the write dictionaries workflow in explicit, reviewable steps.
    for name, material in dictionaries.items():
        # Process dictionaries.items() inside the bounded write dictionaries loop.
        values = arrays[physical.dictionary_values_path(name)]
        if material.blob:
            values[:] = np.frombuffer(material.blob, dtype=np.dtype("|u1"))
        arrays[physical.dictionary_offsets_path(name)][:] = material.offsets


def _write_clock(arrays: dict[str, Any], summary: _ScanSummary) -> None:
    # Execute the write clock workflow in explicit, reviewable steps.
    block_hash_codes = summary.dictionaries["block_hashes"].codes
    for index, row in enumerate(summary.clock_rows):
        # Process enumerate(summary.clock_rows) inside the bounded write clock loop.
        arrays[physical.CLOCK_BLOCK_ORDINAL][index] = row.block_ordinal
        arrays[physical.CLOCK_TRANSACTION_COUNT][index] = row.transaction_count
        arrays[physical.CLOCK_CUMULATIVE_TRANSACTION_PREFIX][index] = (
            row.cumulative_transaction_prefix
        )
        # Invoke _assign_int64 for clock block time ns and block time ns as a visible
        # write clock step.
        _assign_int64(arrays[physical.CLOCK_BLOCK_TIME_NS], index, row.block_time_ns)
        if row.block_hash is not None:
            # Handle the write clock row.block_hash is not None branch as a distinct
            # logical block.
            arrays[physical.CLOCK_BLOCK_HASH_CODE][index] = block_hash_codes[row.block_hash]
            _set_valid(arrays[physical.CLOCK_BLOCK_HASH_VALID], index)


def _write_envelope(
    arrays: dict[str, Any],
    dictionaries: dict[str, dict[str, int]],
    # Keep the index input explicit in the write envelope contract.
    index: int,
    event: CanonicalEvent,
    payload_index: int,
    payload_offset: int,
) -> int:
    # Execute the write envelope workflow in explicit, reviewable steps.
    envelope = event.envelope
    _assign_uint64(arrays[physical.ENVELOPE_BOUNDARY_ORDINAL], index, envelope.boundary_ordinal)
    arrays[physical.ENVELOPE_BLOCK_ORDINAL][index] = envelope.position.block_ordinal
    _assign_int64(
        arrays[physical.ENVELOPE_TRANSACTION_INDEX],
        # Pass index explicitly so _assign_int64 receives a reviewable envelope
        # transaction index and transaction index input in write envelope.
        index,
        envelope.position.transaction_index,
    )
    if envelope.position.event_index is not None:
        # Handle the write envelope event index, position and envelope condition as a
        # distinct block.
        arrays[physical.ENVELOPE_EVENT_INDEX][index] = envelope.position.event_index
        _set_valid(arrays[physical.ENVELOPE_EVENT_INDEX_VALID], index)
    arrays[physical.ENVELOPE_TRANSACTION_GROUP_ID][index] = bytes.fromhex(
        envelope.transaction_group_id.hex
    )
    # Assemble index, arrays and envelope source record id once so the write envelope
    # workflow shares one value.
    arrays[physical.ENVELOPE_SOURCE_RECORD_ID][index] = bytes.fromhex(envelope.source_record_id.hex)
    arrays[physical.ENVELOPE_CANONICAL_EVENT_ID][index] = bytes.fromhex(
        envelope.canonical_event_id.hex
    )
    arrays[physical.ENVELOPE_STABLE_CAUSAL_ID][index] = bytes.fromhex(envelope.stable_causal_id.hex)
    # Assemble index, arrays and envelope capability code once so the write envelope
    # workflow shares one value.
    arrays[physical.ENVELOPE_CAPABILITY_CODE][index] = dictionaries["capabilities"][
        envelope.capability_id.value
    ]
    arrays[physical.ENVELOPE_PROTOCOL_CODE][index] = dictionaries["protocols"][envelope.protocol]
    arrays[physical.ENVELOPE_PROTOCOL_VERSION_CODE][index] = dictionaries["protocol_versions"][
        # Keep the envelope component named inside the index, arrays and envelope protocol
        # version code contract.
        envelope.protocol_version
    ]
    arrays[physical.ENVELOPE_ORDERING_FIDELITY_CODE][index] = _FIDELITY_CODES[
        envelope.ordering_fidelity
    ]
    # Assemble index, arrays and envelope event kind code once so the write envelope
    # workflow shares one value.
    arrays[physical.ENVELOPE_EVENT_KIND_CODE][index] = int(event.kind)
    _assign_uint64(arrays[physical.ENVELOPE_PAYLOAD_INDEX], index, payload_index)

    payload = b""
    if not isinstance(event, BlockEvent):
        # Handle the write envelope not isinstance(event, BlockEvent) branch as a distinct
        # logical block.
        schema, payload = _protocol_payload(event)
        arrays[physical.ENVELOPE_PROTOCOL_PAYLOAD_SCHEMA_CODE][index] = dictionaries[
            "protocol_payload_schemas"
        ][schema]
        _set_valid(arrays[physical.ENVELOPE_PROTOCOL_PAYLOAD_SCHEMA_VALID], index)
    # Guard this path with payload before applying effects.
    if payload:
        # Handle the write envelope payload branch as a distinct logical block.
        stop = payload_offset + len(payload)
        arrays[physical.ENVELOPE_PROTOCOL_PAYLOAD_BYTES][payload_offset:stop] = np.frombuffer(
            payload, dtype=np.dtype("|u1")
        )
        payload_offset = stop
    # Assemble arrays, envelope protocol payload offsets and index once so the write
    # envelope workflow shares one value.
    arrays[physical.ENVELOPE_PROTOCOL_PAYLOAD_OFFSETS][index + 1] = payload_offset
    return payload_offset


def _write_payload(
    arrays: dict[str, Any],
    dictionaries: dict[str, dict[str, int]],
    # Keep the index input explicit in the write payload contract.
    index: int,
    event: CanonicalEvent,
    fee_index: int,
) -> int:
    # Execute the write payload workflow in explicit, reviewable steps.
    if isinstance(event, BlockEvent):
        return fee_index
    if isinstance(event, TokenLaunchEvent):
        # Handle the write payload isinstance(event, TokenLaunchEvent) branch as a
        # distinct logical block.
        arrays[physical.TOKEN_ASSET_CODE][index] = dictionaries["assets"][event.asset_id.value]
        arrays[physical.TOKEN_DEVELOPER_CODE][index] = dictionaries["accounts"][
            event.developer_id.value
        ]
        arrays[physical.TOKEN_CREATION_USER_CODE][index] = dictionaries["accounts"][
            # Keep the event component named inside the index, arrays and token creation
            # user code contract.
            event.creation_user_id.value
        ]
        arrays[physical.TOKEN_VENUE_CODE][index] = dictionaries["venues"][event.venue_id.value]
        arrays[physical.TOKEN_QUOTE_ASSET_CODE][index] = dictionaries["assets"][
            event.quote_asset_id.value
            # Complete the index, arrays and token quote asset code group only after its
            # semantic components are visible.
        ]
        if event.decimals is not None:
            # Handle the write payload event.decimals is not None branch as a distinct
            # logical block.
            arrays[physical.TOKEN_DECIMALS][index] = event.decimals
            _set_valid(arrays[physical.TOKEN_DECIMALS_VALID], index)
        return fee_index
    if isinstance(event, VenueTradeEvent):
        # Handle the write payload isinstance(event, VenueTradeEvent) branch as a distinct
        # logical block.
        arrays[physical.TRADE_VENUE_CODE][index] = dictionaries["venues"][event.venue_id.value]
        arrays[physical.TRADE_SOLD_ASSET_CODE][index] = dictionaries["assets"][
            event.sold_asset_id.value
        ]
        arrays[physical.TRADE_BOUGHT_ASSET_CODE][index] = dictionaries["assets"][
            # Keep the event component named inside the index, arrays and trade bought
            # asset code contract.
            event.bought_asset_id.value
        ]
        arrays[physical.TRADE_SOLD_AMOUNT][index] = _int128_bytes(event.sold_amount_atomic)
        arrays[physical.TRADE_BOUGHT_AMOUNT][index] = _int128_bytes(event.bought_amount_atomic)
        arrays[physical.TRADE_FEE_OFFSETS][index] = fee_index
        # Traverse event.fee_components explicitly so each write payload iteration remains
        # traceable.
        for component in event.fee_components:
            # Process event.fee_components inside the bounded write payload loop.
            arrays[physical.TRADE_FEE_COMPONENT_CODE][fee_index] = dictionaries[
                "fee_component_ids"
            ][component.component_id.value]
            arrays[physical.TRADE_FEE_ASSET_CODE][fee_index] = dictionaries["assets"][
                component.asset_id.value
                # Complete the fee index, arrays and trade fee asset code group only after its
                # semantic components are visible.
            ]
            arrays[physical.TRADE_FEE_AMOUNT][fee_index] = _int128_bytes(component.amount_atomic)
            fee_index += 1
        arrays[physical.TRADE_FEE_OFFSETS][index + 1] = fee_index
        if event.protocol_payload_schema == REFERENCE_AMM_TRADE_PAYLOAD_SCHEMA_ID:
            # Handle the write payload protocol payload schema, reference amm trade
            # payload schema id and event condition as a distinct block.
            _set_valid(arrays[physical.REFERENCE_AMM_VALID], index)
            arrays[physical.REFERENCE_AMM_ASSET_A_CODE][index] = dictionaries["assets"][
                event.pool_asset_a_id.value
            ]
            arrays[physical.REFERENCE_AMM_ASSET_B_CODE][index] = dictionaries["assets"][
                # Keep the event component named inside the index, arrays and reference
                # amm asset b code contract.
                event.pool_asset_b_id.value
            ]
            arrays[physical.REFERENCE_AMM_TOTAL_FEE][index] = _int128_bytes(event.fee_amount_atomic)
            if event.reserve_a_after_atomic is not None:
                # Handle the write payload reserve a after atomic and event condition as a
                # distinct block.
                arrays[physical.REFERENCE_AMM_RESERVE_A][index] = _int128_bytes(
                    event.reserve_a_after_atomic
                )
                _set_valid(arrays[physical.REFERENCE_AMM_RESERVE_A_VALID], index)
            if event.reserve_b_after_atomic is not None:
                # Handle the write payload reserve b after atomic and event condition as a
                # distinct block.
                arrays[physical.REFERENCE_AMM_RESERVE_B][index] = _int128_bytes(
                    event.reserve_b_after_atomic
                )
                _set_valid(arrays[physical.REFERENCE_AMM_RESERVE_B_VALID], index)
        return fee_index
    # Guard this path with isinstance(event, VenueLifecycleEvent) before applying effects.
    if isinstance(event, VenueLifecycleEvent):
        # Handle the write payload isinstance(event, VenueLifecycleEvent) branch as a
        # distinct logical block.
        arrays[physical.LIFECYCLE_VENUE_CODE][index] = dictionaries["venues"][event.venue_id.value]
        arrays[physical.LIFECYCLE_KIND_CODE][index] = _LIFECYCLE_CODES[event.lifecycle_kind]
        return fee_index
    raise ReplayPackCompileError(f"unsupported event type {type(event).__name__}")


def _assign_uint64(array: Any, index: int, value: int) -> None:
    # Execute the assign uint64 workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 1 << 64:
        raise ReplayPackCompileError("value does not fit ReplayPack UInt64")
    array[index] = value


def _assign_int64(array: Any, index: int, value: int) -> None:
    # Execute the assign int64 workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int) or not -(1 << 63) <= value < 1 << 63:
        raise ReplayPackCompileError("value does not fit ReplayPack Int64")
    array[index] = value


def _int128_bytes(value: int) -> bytes:
    # Execute the int128 bytes workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int) or not -(1 << 127) <= value < 1 << 127:
        raise ReplayPackCompileError("value does not fit ReplayPack signed Int128")
    return value.to_bytes(16, "big", signed=True)


def _set_valid(bitmap: Any, index: int) -> None:
    # Execute the set valid workflow in explicit, reviewable steps.
    byte_index, bit_index = divmod(index, 8)
    bitmap[byte_index] = int(bitmap[byte_index]) | (1 << bit_index)


__all__ = [
    "LocalNumpyReplayPackCompiler",
    "ReplayPackCompileError",
    # Keep the replay writer settings digest component named inside the all contract.
    "replay_writer_settings_digest",
    "unit_replay_build_tools",
]
