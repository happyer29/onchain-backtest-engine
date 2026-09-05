# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import io
import json
import shutil
from collections.abc import Callable, Iterator

# Import dataclasses at the visible module dependency boundary.
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest

# Import repository at the visible module dependency boundary.
from backtest.adapters.artifacts.localfs.repository import (
    ArtifactIntegrityError,
    LocalArtifactRepository,
)
from backtest.adapters.artifacts.localfs.scanner import LocalCommittedArtifactScanner
from backtest.adapters.columnar.numpy import (
    # Include local numpy replay pack compiler so the numpy dependency remains explicit.
    LocalNumpyReplayPackCompiler,
    NumpyMmapReplaySource,
    ReplayPackCompileError,
    ReplayPackFormatError,
)

# Import numpy at the visible module dependency boundary.
from backtest.adapters.columnar.numpy import layout as physical
from backtest.adapters.columnar.numpy.compiler import unit_replay_build_tools
from backtest.application.errors import ReprepareRequiredError
from backtest.application.models import ArtifactDraft, ArtifactKind, DatasetSpec
from backtest.application.replay_packs import (
    # Include compiled replay pack so the replay packs dependency remains explicit.
    CompiledReplayPack,
    ReplayPackManifest,
    ReplaySemanticsManifest,
)
from backtest.application.use_cases.compile_replay import (
    # Include compile replay so the compile replay dependency remains explicit.
    CompileReplay,
    CompileReplayRequest,
)
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    # Include solana mainnet network id so the chain dependency remains explicit.
    SOLANA_MAINNET_NETWORK_ID,
)
from backtest.domain.event_hashing import canonical_event_stream_hash
from backtest.domain.fidelity import OrderingFidelity
from backtest.domain.hashing import canonical_json_bytes

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import (
    AccountId,
    AssetId,
    BundleId,
    CapabilityId,
    # Include content digest so the identifiers dependency remains explicit.
    ContentDigest,
    DatasetRevisionId,
    FeeComponentId,
    LogicalContentHash,
    ProtocolPayloadSchemaId,
    # Include replay pack id so the identifiers dependency remains explicit.
    ReplayPackId,
    RuntimeLockId,
    SnapshotId,
    VenueId,
)

# Import market events at the visible module dependency boundary.
from backtest.domain.market_events import (
    REFERENCE_AMM_TRADE_PAYLOAD_SCHEMA_ID,
    BlockEvent,
    CanonicalEvent,
    ChainPosition,
    # Include event envelope so the market events dependency remains explicit.
    EventEnvelope,
    FeeComponent,
    SwapEvent,
    TokenCreationEvent,
    reference_amm_trade_payload,
    # Close the market events import after its required symbols are visible.
)
from backtest.domain.time import BlockRange
from backtest.engine.replay import ReplayBoundary
from tests.support.replay_v3 import (
    FIXTURE_DECISION_RANGE,
    # Include fixture dataset spec so the replay v3 dependency remains explicit.
    fixture_dataset_spec,
    fixture_snapshot_manifest,
    fixture_source_boundary_document,
)


# Keep the canonical source contract and validation rules together.
class _CanonicalSource:
    def __init__(self, events: tuple[CanonicalEvent, ...]) -> None:
        # Execute the canonical source init workflow in explicit, reviewable steps.
        self._events = events
        self._logical_hash = canonical_event_stream_hash(events)
        self._boundaries = _boundaries(events)

    @property
    def dataset_revision_id(self) -> DatasetRevisionId:
        # Return the completed canonical source dataset revision id result without a
        # hidden fallback.
        return DatasetRevisionId("d" * 64)

    @property
    def logical_content_hash(self) -> LogicalContentHash:
        return self._logical_hash

    @property
    # Define canonical source replay semantics id as one focused operation with an
    # explicit boundary.
    def replay_semantics_id(self) -> ContentDigest:
        return ReplaySemanticsManifest.canonical_v3().replay_semantics_id

    @property
    def decision_range(self) -> BlockRange:
        return FIXTURE_DECISION_RANGE

    # Apply property semantics to the following canonical source dataset spec contract.
    @property
    def dataset_spec(self) -> DatasetSpec:
        return fixture_dataset_spec()

    def boundaries(self) -> tuple[ReplayBoundary, ...]:
        return self._boundaries

    # Define canonical source events as one focused operation with an explicit boundary.
    def events(self) -> Iterator[CanonicalEvent]:
        yield from self._events


# Keep the legacy content identity source contract and validation rules together.
class _LegacyContentIdentitySource(_CanonicalSource):
    @property
    def replay_semantics_id(self) -> ContentDigest:
        return ReplaySemanticsManifest.canonical_v1().replay_semantics_id


class _BoundaryMaterializationForbiddenSource(_CanonicalSource):
    def boundaries(self) -> tuple[ReplayBoundary, ...]:
        raise AssertionError("compiler must derive boundaries from the canonical stream")


class _MutatingBetweenPassesSource(_CanonicalSource):
    def __init__(
        self,
        first_pass: tuple[CanonicalEvent, ...],
        second_pass: tuple[CanonicalEvent, ...],
    ) -> None:
        super().__init__(first_pass)
        self._first_pass = first_pass
        self._second_pass = second_pass
        self._pass_count = 0

    def events(self) -> Iterator[CanonicalEvent]:
        self._pass_count += 1
        yield from self._first_pass if self._pass_count == 1 else self._second_pass


def test_compiler_and_mmap_reader_preserve_exact_logical_stream_and_groups(
    # Keep the tmp path input explicit in the test compiler and mmap reader preserve exact
    # logical stream and groups contract.
    tmp_path: Path,
) -> None:
    # Execute the test compiler and mmap reader preserve exact logical stream and groups
    # workflow in explicit, reviewable steps.
    artifacts, expected, compiled = _compile(tmp_path)

    with NumpyMmapReplaySource(artifacts, compiled.replay_pack_id) as replay:
        # Keep numpy mmap replay source, artifacts and replay pack id active only for the
        # bounded test compiler and mmap reader preserve exact logical stream and groups
        # operation.
        assert tuple(replay.events()) == expected
        assert replay.boundaries() == _boundaries(expected)
        assert replay.group_offsets.tolist() == [0, 1, 3, 4]
        assert replay.boundary_offsets.tolist() == [0, 1, 3, 4]
        assert replay.logical_content_hash == canonical_event_stream_hash(expected)
        # Verify the dataset revision id, replay and d relationship before this scenario
        # is accepted.
        assert replay.dataset_revision_id == DatasetRevisionId("d" * 64)
        assert replay.network_id == SOLANA_MAINNET_NETWORK_ID
        assert replay.position_schema_id == BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID
        assert replay.decision_range == FIXTURE_DECISION_RANGE
        assert replay.dataset_spec == fixture_dataset_spec()
        # Verify the block ordinals, transaction clock and replay relationship before this
        # scenario is accepted.
        assert replay.transaction_clock().block_ordinals == (100,)
        assert replay.transaction_clock().transaction_counts == (2,)
        assert replay.source_boundaries == compiled.manifest.source_boundaries
        arrays = replay.arrays()
        assert arrays[physical.dictionary_values_path("assets")].tobytes() == b"SOLTOKEN"
        # Verify the tolist, arrays and dictionary offsets path relationship before this
        # scenario is accepted.
        assert arrays[physical.dictionary_offsets_path("assets")].tolist() == [0, 3, 8]
        assert all(
            isinstance(array, np.memmap) and not array.flags.writeable for array in arrays.values()
        )
        assert not any("slot" in path for path in arrays)

    # Assemble second once so the test compiler and mmap reader preserve exact logical
    # stream and groups workflow shares one value.
    second = CompileReplay(
        LocalNumpyReplayPackCompiler(
            artifacts,
            lambda snapshot_id: _CanonicalSource(expected),
            runtime_lock_id=RuntimeLockId("9" * 64),
            # Complete LocalNumpyReplayPackCompiler only after its 9 and canonical source
            # inputs are visible in test compiler and mmap reader preserve exact logical
            # stream and groups.
        )
    ).execute(CompileReplayRequest(compiled.manifest.snapshot_id, physical.COMPILER_VERSION))
    assert second.replay_pack_id == compiled.replay_pack_id
    assert second.manifest.identity_document() == compiled.manifest.identity_document()


def test_compiler_does_not_materialize_source_boundary_objects(tmp_path: Path) -> None:
    artifacts = LocalArtifactRepository(tmp_path / "var")
    snapshot_id = _publish_snapshot(artifacts)
    events = _events()
    compiled = LocalNumpyReplayPackCompiler(
        artifacts,
        lambda requested: _BoundaryMaterializationForbiddenSource(events),
        runtime_lock_id=RuntimeLockId("9" * 64),
    ).compile(snapshot_id, physical.COMPILER_VERSION)

    with NumpyMmapReplaySource(artifacts, compiled.replay_pack_id) as replay:
        assert replay.boundaries() == _boundaries(events)
        assert tuple(replay.events()) == events


def test_compiler_aborts_when_canonical_stream_changes_between_passes(tmp_path: Path) -> None:
    artifacts = LocalArtifactRepository(tmp_path / "var")
    snapshot_id = _publish_snapshot(artifacts)
    first_pass = _events()
    changed_trade = replace(cast(SwapEvent, first_pass[2]), sold_amount_atomic=101)
    second_pass = (*first_pass[:2], changed_trade, *first_pass[3:])
    source = _MutatingBetweenPassesSource(first_pass, second_pass)

    def source_factory(requested: SnapshotId) -> _MutatingBetweenPassesSource:
        if requested != snapshot_id:
            raise AssertionError("compiler requested another snapshot")
        return source

    compiler = LocalNumpyReplayPackCompiler(
        artifacts,
        source_factory,
        runtime_lock_id=RuntimeLockId("9" * 64),
    )

    with pytest.raises(
        ReplayPackCompileError, match="logical stream changed between compiler passes"
    ):
        compiler.compile(snapshot_id, physical.COMPILER_VERSION)

    assert not any(
        artifact.kind is ArtifactKind.REPLAY_PACK
        for artifact in LocalCommittedArtifactScanner(artifacts).scan()
    )
    assert not tuple(artifacts.staging_root.glob("artifact-*"))
    assert not tuple((artifacts.data_root / "tmp" / "replay").glob("pack-*"))


def test_build_key_is_not_part_of_replay_pack_content_identity(tmp_path: Path) -> None:
    # Execute the test build key is not part of replay pack content identity workflow in
    # explicit, reviewable steps.
    artifacts, expected, first = _compile(tmp_path)
    second = CompileReplay(
        LocalNumpyReplayPackCompiler(
            artifacts,
            lambda snapshot_id: _CanonicalSource(expected),
            # Keep the runtime lock id RuntimeLockId step visible while building second.
            runtime_lock_id=RuntimeLockId("8" * 64),
            compiler_bundle_id=BundleId("7" * 64),
        )
    ).execute(CompileReplayRequest(first.manifest.snapshot_id, physical.COMPILER_VERSION))

    assert first.replay_build_key != second.replay_build_key
    # Verify the replay pack id, first and second relationship before this scenario is
    # accepted.
    assert first.replay_pack_id == second.replay_pack_id
    assert "build" not in first.manifest.identity_document()
    assert "replay_build_key" not in first.manifest.identity_document()


def test_reader_rejects_an_independently_expected_compiler_identity(tmp_path: Path) -> None:
    # Execute the test reader rejects an independently expected compiler identity workflow
    # in explicit, reviewable steps.
    artifacts, _, compiled = _compile(tmp_path)

    with pytest.raises(ReplayPackFormatError, match="compiler bundle"):
        # Keep raises, replay pack format error and pytest active only for the bounded
        # test reader rejects an independently expected compiler identity operation.
        NumpyMmapReplaySource(
            artifacts,
            compiled.replay_pack_id,
            build_tools=unit_replay_build_tools(compiler_bundle_id=BundleId("7" * 64)),
        )


# Define test compiler rejects legacy content hash event identity as one focused operation
# with an explicit boundary.
def test_compiler_rejects_legacy_content_hash_event_identity(tmp_path: Path) -> None:
    # Execute the test compiler rejects legacy content hash event identity workflow in
    # explicit, reviewable steps.
    artifacts = LocalArtifactRepository(tmp_path / "var")
    snapshot_id = _publish_snapshot(artifacts)
    events = _events()
    compiler = LocalNumpyReplayPackCompiler(
        artifacts,
        # Keep the events _LegacyContentIdentitySource step visible while building
        # compiler.
        lambda requested: _LegacyContentIdentitySource(events),
        runtime_lock_id=RuntimeLockId("9" * 64),
    )

    with pytest.raises(ReplayPackCompileError, match="semantics are incompatible"):
        compiler.compile(snapshot_id, physical.COMPILER_VERSION)


# Define test compiler rejects snapshot without v3 fidelity contract as one focused
# operation with an explicit boundary.
def test_compiler_rejects_snapshot_without_v3_fidelity_contract(tmp_path: Path) -> None:
    # Execute the test compiler rejects snapshot without v3 fidelity contract workflow in
    # explicit, reviewable steps.
    artifacts = LocalArtifactRepository(tmp_path / "var")
    writer = artifacts.stage(ArtifactDraft(ArtifactKind.SNAPSHOT, ContentDigest("a" * 64)))
    committed = writer.commit(canonical_json_bytes({"artifact_schema": "canonical-snapshot/v2"}))
    compiler = LocalNumpyReplayPackCompiler(
        artifacts,
        # Keep the canonical source and events _CanonicalSource step visible while
        # building compiler.
        lambda requested: _CanonicalSource(_events()),
        runtime_lock_id=RuntimeLockId("9" * 64),
    )

    with pytest.raises(ReprepareRequiredError):
        compiler.compile(SnapshotId(committed.artifact_id.hex), physical.COMPILER_VERSION)


# Apply parametrize semantics to the following test compiler rejects incomplete effective
# fidelity contract.
@pytest.mark.parametrize(
    "missing_field",
    [
        "chain_finality",
        "completeness",
        # Pass consistency explicitly so parametrize receives a reviewable missing field
        # and chain finality input in test compiler rejects incomplete effective fidelity.
        "consistency",
        "fees",
        "identity",
        "ordering",
        "state",
        # Close the missing field and chain finality payload only after all test compiler
        # rejects incomplete effective fidelity fields are present.
    ],
)
def test_compiler_rejects_incomplete_effective_fidelity(
    tmp_path: Path,
    missing_field: str,
    # Close the test compiler rejects incomplete effective fidelity signature after its
    # explicit inputs.
) -> None:
    # Execute the test compiler rejects incomplete effective fidelity workflow in
    # explicit, reviewable steps.
    artifacts = LocalArtifactRepository(tmp_path / "var")
    document = _snapshot_fidelity_manifest()
    boundary = cast(dict[str, object], cast(list[object], document["source_boundaries"])[0])
    fidelity = cast(dict[str, str], boundary["source_fidelity"])
    del fidelity[missing_field]
    # Assemble writer once so the test compiler rejects incomplete effective fidelity
    # workflow shares one value.
    writer = artifacts.stage(ArtifactDraft(ArtifactKind.SNAPSHOT, ContentDigest("a" * 64)))
    committed = writer.commit(canonical_json_bytes(document))
    compiler = LocalNumpyReplayPackCompiler(
        artifacts,
        lambda requested: _CanonicalSource(_events()),
        # Keep the runtime lock id RuntimeLockId step visible while building compiler.
        runtime_lock_id=RuntimeLockId("9" * 64),
    )

    with pytest.raises(ReplayPackCompileError, match="fidelity contract"):
        compiler.compile(SnapshotId(committed.artifact_id.hex), physical.COMPILER_VERSION)


def test_compiler_rejects_promoted_cut_dependent_fidelity(tmp_path: Path) -> None:
    # Execute the test compiler rejects promoted cut dependent fidelity workflow in
    # explicit, reviewable steps.
    artifacts = LocalArtifactRepository(tmp_path / "var")
    document = _snapshot_fidelity_manifest()
    boundary = cast(dict[str, object], cast(list[object], document["source_boundaries"])[0])
    fidelity = cast(dict[str, str], boundary["source_fidelity"])
    fidelity["completeness"] = "COMPLETE_TO_WATERMARK"
    # Assemble writer once so the test compiler rejects promoted cut dependent fidelity
    # workflow shares one value.
    writer = artifacts.stage(ArtifactDraft(ArtifactKind.SNAPSHOT, ContentDigest("a" * 64)))
    committed = writer.commit(canonical_json_bytes(document))
    compiler = LocalNumpyReplayPackCompiler(
        artifacts,
        lambda requested: _CanonicalSource(_events()),
        # Keep the runtime lock id RuntimeLockId step visible while building compiler.
        runtime_lock_id=RuntimeLockId("9" * 64),
    )

    with pytest.raises(ReplayPackCompileError, match="fidelity contract"):
        compiler.compile(SnapshotId(committed.artifact_id.hex), physical.COMPILER_VERSION)


def test_compiler_rejects_unvalidated_source_boundary(tmp_path: Path) -> None:
    # Execute the test compiler rejects unvalidated source boundary workflow in explicit,
    # reviewable steps.
    artifacts = LocalArtifactRepository(tmp_path / "var")
    document = _snapshot_fidelity_manifest()
    boundary = cast(dict[str, object], cast(list[object], document["source_boundaries"])[0])
    boundary["validation_status"] = "FAIL"
    writer = artifacts.stage(ArtifactDraft(ArtifactKind.SNAPSHOT, ContentDigest("a" * 64)))
    # Assemble committed once so the test compiler rejects unvalidated source boundary
    # workflow shares one value.
    committed = writer.commit(canonical_json_bytes(document))
    compiler = LocalNumpyReplayPackCompiler(
        artifacts,
        lambda requested: _CanonicalSource(_events()),
        runtime_lock_id=RuntimeLockId("9" * 64),
        # Complete LocalNumpyReplayPackCompiler only after its 9 and canonical source inputs
        # are visible in test compiler rejects unvalidated source boundary.
    )

    with pytest.raises(ReplayPackCompileError, match="fidelity contract"):
        compiler.compile(SnapshotId(committed.artifact_id.hex), physical.COMPILER_VERSION)


def test_replay_manifest_rejects_legacy_schema_even_with_current_fields(
    tmp_path: Path,
    # Close the test replay manifest rejects legacy schema even with current fields signature
    # after its explicit inputs.
) -> None:
    # Execute the test replay manifest rejects legacy schema even with current fields
    # workflow in explicit, reviewable steps.
    _, _, compiled = _compile(tmp_path)
    document = compiled.manifest.document()
    document["artifact_schema"] = "replay-pack/v1"
    del document["source_boundaries"]

    with pytest.raises(ReprepareRequiredError):
        # Invoke from_document for document as a visible test replay manifest rejects
        # legacy schema even with current fields step.
        ReplayPackManifest.from_document(document)


def test_mmap_reader_rejects_legacy_content_hash_event_identity(tmp_path: Path) -> None:
    # Execute the test mmap reader rejects legacy content hash event identity workflow in
    # explicit, reviewable steps.
    artifacts, _, compiled = _compile(tmp_path)
    legacy_id = _republish_with_legacy_semantics(artifacts, compiled.replay_pack_id)

    with pytest.raises(ReplayPackFormatError, match="unsupported canonical identity"):
        NumpyMmapReplaySource(artifacts, legacy_id)


def test_physical_corruption_is_rejected_before_mmap(tmp_path: Path) -> None:
    # Execute the test physical corruption is rejected before mmap workflow in explicit,
    # reviewable steps.
    artifacts, _, compiled = _compile(tmp_path)
    path = (
        artifacts.data_root
        / "replay"
        / compiled.manifest.snapshot_id.hex
        / compiled.replay_pack_id.hex
        # Keep the physical component named inside the path contract.
        / physical.ENVELOPE_EVENT_KIND_CODE
    )
    with path.open("r+b") as stream:
        # Keep open and path active only for the bounded test physical corruption is
        # rejected before mmap operation.
        stream.seek(-1, 2)
        original = stream.read(1)
        stream.seek(-1, 2)
        stream.write(bytes([original[0] ^ 0xFF]))

    with pytest.raises(ArtifactIntegrityError):
        # Invoke NumpyMmapReplaySource for replay pack id and artifacts as a visible test
        # physical corruption is rejected before mmap step.
        NumpyMmapReplaySource(artifacts, compiled.replay_pack_id)


def test_declared_dtype_mismatch_is_rejected(tmp_path: Path) -> None:
    # Execute the test declared dtype mismatch is rejected workflow in explicit,
    # reviewable steps.
    artifacts, _, compiled = _compile(tmp_path)
    malformed = _republish_with_array(
        artifacts,
        compiled.replay_pack_id,
        physical.ENVELOPE_EVENT_KIND_CODE,
        # Keep the astype and value astype step visible while building malformed.
        lambda value: value.astype("<u2"),
    )

    with pytest.raises(ReplayPackFormatError, match="dtype/endian mismatch"):
        NumpyMmapReplaySource(artifacts, malformed)


def test_big_endian_numeric_file_is_rejected_by_little_endian_layout(tmp_path: Path) -> None:
    # Execute the test big endian numeric file is rejected by little endian layout
    # workflow in explicit, reviewable steps.
    artifacts, _, compiled = _compile(tmp_path)
    malformed = _republish_with_array(
        artifacts,
        compiled.replay_pack_id,
        physical.ENVELOPE_BOUNDARY_ORDINAL,
        # Keep the astype and value astype step visible while building malformed.
        lambda value: value.astype(">u8"),
    )

    with pytest.raises(ReplayPackFormatError, match="dtype/endian mismatch"):
        NumpyMmapReplaySource(artifacts, malformed)


def test_non_monotone_group_offsets_are_rejected(tmp_path: Path) -> None:
    # Execute the test non monotone group offsets are rejected workflow in explicit,
    # reviewable steps.
    artifacts, _, compiled = _compile(tmp_path)

    def duplicate_first_offset(value: np.ndarray) -> np.ndarray:
        # Execute the duplicate first offset workflow in explicit, reviewable steps.
        result = value.copy()
        result[1] = result[0]
        return result

    malformed = _republish_with_array(
        artifacts,
        # Pass compiled explicitly so _republish_with_array receives a reviewable replay
        # pack id and group offsets input in test non monotone group offsets are rejected.
        compiled.replay_pack_id,
        physical.GROUP_OFFSETS,
        duplicate_first_offset,
    )

    with pytest.raises(ReplayPackFormatError, match="group offsets are not strictly increasing"):
        # Invoke NumpyMmapReplaySource for artifacts and malformed as a visible test non
        # monotone group offsets are rejected step.
        NumpyMmapReplaySource(artifacts, malformed)


def _compile(
    tmp_path: Path,
) -> tuple[LocalArtifactRepository, tuple[CanonicalEvent, ...], CompiledReplayPack]:
    # Execute the compile workflow in explicit, reviewable steps.
    artifacts = LocalArtifactRepository(tmp_path / "var")
    snapshot_id = _publish_snapshot(artifacts)
    events = _events()
    compiler = LocalNumpyReplayPackCompiler(
        artifacts,
        # Keep the requested _checked_source step visible while building compiler.
        lambda requested: _checked_source(requested, snapshot_id, events),
        runtime_lock_id=RuntimeLockId("9" * 64),
    )
    compiled = CompileReplay(compiler).execute(
        CompileReplayRequest(snapshot_id, physical.COMPILER_VERSION)
        # Complete execute only after its compiler version and compile replay request inputs
        # are visible in compile.
    )
    assert isinstance(compiled, CompiledReplayPack)
    return artifacts, events, compiled


def _publish_snapshot(artifacts: LocalArtifactRepository) -> SnapshotId:
    # Execute the publish snapshot workflow in explicit, reviewable steps.
    writer = artifacts.stage(
        ArtifactDraft(
            kind=ArtifactKind.SNAPSHOT,
            build_key=ContentDigest("a" * 64),
        )
        # Complete stage only after its a and snapshot inputs are visible in publish snapshot.
    )
    committed = writer.commit(canonical_json_bytes(_snapshot_fidelity_manifest()))
    return SnapshotId(committed.artifact_id.hex)


def _snapshot_fidelity_manifest() -> dict[str, object]:
    return fixture_snapshot_manifest()


# Define source boundary document as one focused operation with an explicit boundary.
def _source_boundary_document(fidelity: dict[str, str]) -> dict[str, object]:
    return fixture_source_boundary_document(fidelity)


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
    block = BlockEvent(
        envelope=_envelope(slot=100, transaction_index=-1, event_index=0, group=1, event=1),
        block_time_ns=100_000_000_000,
        tx_count=2,
        block_hash=None,
        # Complete BlockEvent only after its envelope inputs are visible in events.
    )
    token = TokenCreationEvent(
        envelope=_envelope(slot=100, transaction_index=0, event_index=0, group=2, event=2),
        asset_id=AssetId("TOKEN"),
        developer_id=AccountId("creator"),
        # Keep the creator AccountId step visible while building token.
        creation_user_id=AccountId("creator"),
        venue_id=VenueId("launch:TOKEN"),
        quote_asset_id=AssetId("SOL"),
        protocol_payload_schema=ProtocolPayloadSchemaId("reference-token-launch-payload-v1"),
        protocol_payload=b"",
        # Pass decimals explicitly so TokenCreationEvent receives a reviewable token and
        # creator input in events.
        decimals=None,
    )
    first_swap = SwapEvent(
        envelope=_envelope(slot=100, transaction_index=0, event_index=1, group=2, event=3),
        venue_id=VenueId("pool"),
        # Keep the sol AssetId step visible while building first swap.
        sold_asset_id=AssetId("SOL"),
        bought_asset_id=AssetId("TOKEN"),
        sold_amount_atomic=100,
        # Exercise the canonical one-zero-leg historical trade contract through mmap.
        bought_amount_atomic=0,
        fee_components=(FeeComponent(FeeComponentId("protocol"), AssetId("SOL"), 1),),
        # Pass protocol payload schema explicitly so SwapEvent receives a reviewable pool
        # and sol input in events.
        protocol_payload_schema=REFERENCE_AMM_TRADE_PAYLOAD_SCHEMA_ID,
        protocol_payload=reference_amm_trade_payload(
            asset_a_id=AssetId("SOL"),
            asset_b_id=AssetId("TOKEN"),
            reserve_a_after_atomic=1_000,
            # Pass reserve b after atomic explicitly so reference_amm_trade_payload
            # receives a reviewable sol and token input in events.
            reserve_b_after_atomic=10_000,
        ),
    )
    second_swap = SwapEvent(
        envelope=_envelope(
            # Pass slot explicitly so _envelope receives a reviewable transaction partial
            # and ordering fidelity input in events.
            slot=100,
            transaction_index=1,
            event_index=None,
            group=3,
            event=4,
            # Pass fidelity explicitly so _envelope receives a reviewable transaction
            # partial and ordering fidelity input in events.
            fidelity=OrderingFidelity.TRANSACTION_PARTIAL,
        ),
        venue_id=VenueId("pool"),
        sold_asset_id=AssetId("TOKEN"),
        bought_asset_id=AssetId("SOL"),
        # Pass sold amount atomic explicitly so SwapEvent receives a reviewable pool and
        # token input in events.
        sold_amount_atomic=(1 << 100) + 1_000,
        bought_amount_atomic=(1 << 96) + 90,
        fee_components=(FeeComponent(FeeComponentId("protocol"), AssetId("TOKEN"), 2),),
        protocol_payload_schema=REFERENCE_AMM_TRADE_PAYLOAD_SCHEMA_ID,
        protocol_payload=reference_amm_trade_payload(
            # Keep the sol AssetId step visible while building second swap.
            asset_a_id=AssetId("SOL"),
            asset_b_id=AssetId("TOKEN"),
            reserve_a_after_atomic=None,
            reserve_b_after_atomic=None,
        ),
        # Complete SwapEvent only after its pool and token inputs are visible in events.
    )
    return (block, token, first_swap, second_swap)


def _envelope(
    *,
    slot: int,
    # Keep the transaction index input explicit in the envelope contract.
    transaction_index: int,
    event_index: int | None,
    group: int,
    event: int,
    fidelity: OrderingFidelity = OrderingFidelity.INSTRUCTION_EXACT,
    # Keep the event envelope input explicit in the envelope contract.
) -> EventEnvelope:
    # Execute the envelope workflow in explicit, reviewable steps.
    return EventEnvelope(
        position=ChainPosition(
            network_id=SOLANA_MAINNET_NETWORK_ID,
            position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            block_ordinal=slot,
            # Pass transaction index explicitly so ChainPosition receives a reviewable
            # solana mainnet network id and block32 transaction32 position schema id input
            # in envelope.
            transaction_index=transaction_index,
            event_index=event_index,
        ),
        transaction_group_id=_digest(group),
        source_record_id=_digest(100 + event),
        # Include canonical event id in the completed envelope result.
        canonical_event_id=_digest(200 + event),
        stable_causal_id=_digest(300 + event),
        capability_id=CapabilityId("fixture.events.v1"),
        protocol="fixture",
        protocol_version="1",
        # Pass ordering fidelity explicitly so EventEnvelope receives a reviewable v1 and
        # fixture input in envelope.
        ordering_fidelity=fidelity,
    )


def _digest(value: int) -> ContentDigest:
    return ContentDigest(f"{value:064x}")


def _boundaries(events: tuple[CanonicalEvent, ...]) -> tuple[ReplayBoundary, ...]:
    # Execute the boundaries workflow in explicit, reviewable steps.
    result: list[ReplayBoundary] = []
    previous: int | None = None
    for event in events:
        # Process events inside the bounded boundaries loop.
        ordinal = event.envelope.boundary_ordinal
        if ordinal != previous:
            # Handle the boundaries ordinal != previous branch as a distinct logical
            # block.
            result.append(ReplayBoundary.from_position(event.envelope.position))
            previous = ordinal
    return tuple(result)


def _republish_with_array(
    artifacts: LocalArtifactRepository,
    # Keep the replay pack id input explicit in the republish with array contract.
    replay_pack_id: ReplayPackId,
    target_path: str,
    mutate: Callable[[np.ndarray], np.ndarray],
) -> ReplayPackId:
    with artifacts.open_committed(replay_pack_id) as handle:  # type: ignore[attr-defined]
        with handle.open_binary("manifest.json") as stream:
            manifest_bytes = stream.read()
        with handle.open_binary("manifest.identity.json") as stream:
            identity_bytes = stream.read()
        manifest = ReplayPackManifest.from_document(json.loads(manifest_bytes))
        # Assemble payloads once so the republish with array workflow shares one value.
        payloads: dict[str, bytes] = {}
        for descriptor in manifest.layout.arrays:
            # Process manifest.layout.arrays inside the bounded republish with array loop.
            with handle.open_binary(descriptor.path) as stream:
                payloads[descriptor.path] = stream.read()

    writer = artifacts.stage(
        ArtifactDraft(
            kind=ArtifactKind.REPLAY_PACK,
            # Pass build key explicitly so ArtifactDraft receives a reviewable replay pack
            # and replay build key input in republish with array.
            build_key=manifest.build.replay_build_key,
            input_artifact_ids=(manifest.snapshot_id,),
        )
    )
    try:
        # Perform the protected republish with array operation before explicit failure
        # handling.
        for descriptor in manifest.layout.arrays:
            # Process manifest.layout.arrays inside the bounded republish with array loop.
            with writer.open_binary(descriptor.path) as destination:
                # Keep open binary, path and writer active only for the bounded republish
                # with array operation.
                if descriptor.path == target_path:
                    # Handle the republish with array descriptor.path == target_path
                    # branch as a distinct logical block.
                    original = np.load(io.BytesIO(payloads[descriptor.path]), allow_pickle=False)
                    np.save(destination, mutate(original), allow_pickle=False)
                else:
                    shutil.copyfileobj(io.BytesIO(payloads[descriptor.path]), destination)
        committed = writer.commit(
            # Pass manifest bytes explicitly so commit receives a reviewable manifest
            # bytes and identity bytes input in republish with array.
            manifest_bytes,
            identity_manifest_bytes=identity_bytes,
        )
    except BaseException:
        # Translate the BaseException failure through the republish with array boundary.
        writer.abort()
        raise
    return ReplayPackId(committed.artifact_id.hex)


def _republish_with_legacy_semantics(
    artifacts: LocalArtifactRepository,
    # Keep the replay pack id input explicit in the republish with legacy semantics
    # contract.
    replay_pack_id: ReplayPackId,
) -> ReplayPackId:
    # Execute the republish with legacy semantics workflow in explicit, reviewable steps.
    raw_handle = artifacts.open_committed(replay_pack_id)
    try:
        # Perform the protected republish with legacy semantics operation before explicit
        # failure handling.
        handle = cast(Any, raw_handle)
        with handle.open_binary("manifest.json") as stream:
            current = ReplayPackManifest.from_document(json.load(stream))
        payloads: dict[str, bytes] = {}
        for descriptor in current.layout.arrays:
            # Process current.layout.arrays inside the bounded republish with legacy
            # semantics loop.
            with handle.open_binary(descriptor.path) as stream:
                payloads[descriptor.path] = stream.read()
    finally:
        raw_handle.close()

    legacy_semantics = ReplaySemanticsManifest.canonical_v1()
    # Assemble legacy build once so the republish with legacy semantics workflow shares
    # one value.
    legacy_build = replace(
        current.build,
        replay_semantics_id=legacy_semantics.replay_semantics_id,
    )
    legacy = replace(
        # Pass current explicitly so replace receives a reviewable current and legacy
        # semantics input in republish with legacy semantics.
        current,
        semantics=legacy_semantics,
        build=legacy_build,
    )
    manifest_bytes = canonical_json_bytes(legacy.document())
    # Assemble identity bytes once so the republish with legacy semantics workflow shares
    # one value.
    identity_bytes = canonical_json_bytes(legacy.identity_document())
    writer = artifacts.stage(
        ArtifactDraft(
            kind=ArtifactKind.REPLAY_PACK,
            build_key=legacy_build.replay_build_key,
            # Pass input artifact ids explicitly so ArtifactDraft receives a reviewable
            # replay pack and replay build key input in republish with legacy semantics.
            input_artifact_ids=(legacy.snapshot_id,),
        )
    )
    try:
        # Perform the protected republish with legacy semantics operation before explicit
        # failure handling.
        for descriptor in legacy.layout.arrays:
            # Process legacy.layout.arrays inside the bounded republish with legacy
            # semantics loop.
            with writer.open_binary(descriptor.path) as destination:
                destination.write(payloads[descriptor.path])
        committed = writer.commit(
            manifest_bytes,
            identity_manifest_bytes=identity_bytes,
            # Complete commit only after its manifest bytes and identity bytes inputs are
            # visible in republish with legacy semantics.
        )
    except BaseException:
        # Translate the BaseException failure through the republish with legacy semantics
        # boundary.
        writer.abort()
        raise
    return ReplayPackId(committed.artifact_id.hex)
