# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository

# Import numpy at the visible module dependency boundary.
from backtest.adapters.columnar.numpy import (
    LocalNumpyReplayPackCompiler,
    NumpyMmapFirstSwapEngine,
    NumpyMmapReplaySource,
    OptimizedBackendUnsupported,
    # Close the numpy import after its required symbols are visible.
)
from backtest.adapters.columnar.numpy.layout import COMPILER_VERSION
from backtest.application.models import ArtifactDraft, ArtifactKind, DatasetSpec
from backtest.application.replay_packs import ReplaySemanticsManifest
from backtest.domain.chain import (
    # Include block32 transaction32 position schema id so the chain dependency remains
    # explicit.
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
)
from backtest.domain.event_hashing import canonical_event_stream_hash
from backtest.domain.execution import ExecutionMode, Fill

# Import fidelity at the visible module dependency boundary.
from backtest.domain.fidelity import OrderingFidelity
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import (
    AccountId,
    AssetId,
    # Include capability id so the identifiers dependency remains explicit.
    CapabilityId,
    ContentDigest,
    DatasetRevisionId,
    FeeComponentId,
    LogicalContentHash,
    # Include pool id so the identifiers dependency remains explicit.
    PoolId,
    ProtocolPayloadSchemaId,
    ReplayPackId,
    RuntimeLockId,
    SnapshotId,
    # Include venue id so the identifiers dependency remains explicit.
    VenueId,
)
from backtest.domain.ledger import LedgerTransaction
from backtest.domain.market_events import (
    REFERENCE_AMM_TRADE_PAYLOAD_SCHEMA_ID,
    # Include block event so the market events dependency remains explicit.
    BlockEvent,
    CanonicalEvent,
    ChainPosition,
    EventEnvelope,
    FeeComponent,
    # Include swap event so the market events dependency remains explicit.
    SwapEvent,
    TokenCreationEvent,
    reference_amm_trade_payload,
)
from backtest.domain.time import BlockRange

# Import contracts at the visible module dependency boundary.
from backtest.engine.contracts import DEFAULT_ENGINE_PHYSICAL_SETTINGS, EnginePhysicalSettings
from backtest.engine.reference import (
    ReferenceBacktestEngine,
    ReferenceRunConfig,
    SlotLatencyModel,
    # Close the reference import after its required symbols are visible.
)
from backtest.engine.replay import ReplayBoundary
from backtest.plugins.execution import ConstantProductExecutionModel
from backtest.plugins.risk import StaticRiskPolicy
from backtest.plugins.strategies import FirstSwapStrategy

# Import replay v3 at the visible module dependency boundary.
from tests.support.replay_v3 import (
    FIXTURE_DECISION_RANGE,
    fixture_dataset_spec,
    fixture_snapshot_manifest,
)

# Bind sol once as an explicit module-level contract.
SOL = AssetId("SOL")
TOKEN = AssetId("TOKEN")
POOL = PoolId("pool")


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
        return ReplaySemanticsManifest.canonical_v3().replay_semantics_id

    @property
    def decision_range(self) -> BlockRange:
        return FIXTURE_DECISION_RANGE

    # Apply property semantics to the following canonical source dataset spec contract.
    @property
    def dataset_spec(self) -> DatasetSpec:
        return fixture_dataset_spec()

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


# Keep the memory sink contract and validation rules together.
class _MemorySink:
    def __init__(self) -> None:
        # Execute the memory sink init workflow in explicit, reviewable steps.
        self.audit: list[dict[str, object]] = []
        self.ledger: list[LedgerTransaction] = []
        self.fills: list[Fill] = []

    def append_audit(self, record: dict[str, object]) -> None:
        self.audit.append(record)

    # Define memory sink append ledger as one focused operation with an explicit boundary.
    def append_ledger(self, transaction: LedgerTransaction) -> None:
        self.ledger.append(transaction)

    def append_fill(self, fill: Fill) -> None:
        self.fills.append(fill)


def test_optimized_replay_is_byte_identical_without_decoding_event_objects(
    # Keep the tmp path input explicit in the test optimized replay is byte identical
    # without decoding event objects contract.
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test optimized replay is byte identical without decoding event objects
    # workflow in explicit, reviewable steps.
    artifacts, replay_id = _compile(tmp_path, _events())
    with NumpyMmapReplaySource(artifacts, replay_id) as replay:
        # Keep numpy mmap replay source, artifacts and replay id active only for the
        # bounded test optimized replay is byte identical without decoding event objects
        # operation.
        reference_sink = _MemorySink()
        optimized_sink = _MemorySink()
        reference = _run_reference(replay, reference_sink)

        def forbidden_event_decode(index: int) -> CanonicalEvent:
            # Execute the forbidden event decode workflow in explicit, reviewable steps.
            del index
            raise AssertionError("optimized hot loop called ReplayPack._event")

        def forbidden_event_allocation(*args: object, **kwargs: object) -> None:
            # Execute the forbidden event allocation workflow in explicit, reviewable
            # steps.
            del args, kwargs
            raise AssertionError("optimized hot loop allocated a CanonicalEvent variant")

        monkeypatch.setattr(replay, "_event", forbidden_event_decode)
        for event_type in (BlockEvent, TokenCreationEvent, SwapEvent):
            monkeypatch.setattr(event_type, "__init__", forbidden_event_allocation)
        # Assemble optimized once so the test optimized replay is byte identical without
        # decoding event objects workflow shares one value.
        optimized = _run_optimized(replay, optimized_sink)

    assert optimized == reference
    assert optimized_sink.audit == reference_sink.audit
    assert optimized_sink.ledger == reference_sink.ledger
    assert optimized_sink.fills == reference_sink.fills


# Apply parametrize semantics to the following test optimized hash is independent of batch
# and bounded readahead contract.
@pytest.mark.parametrize("batch_rows", (2, 3, 65_536, 262_144))
@pytest.mark.parametrize("readahead", (1, 2, 4))
def test_optimized_hash_is_independent_of_batch_and_bounded_readahead(
    tmp_path: Path,
    batch_rows: int,
    # Keep the readahead input explicit in the test optimized hash is independent of batch
    # and bounded readahead contract.
    readahead: int,
) -> None:
    # Execute the test optimized hash is independent of batch and bounded readahead
    # workflow in explicit, reviewable steps.
    artifacts, replay_id = _compile(tmp_path, _events())
    with NumpyMmapReplaySource(artifacts, replay_id) as replay:
        # Keep numpy mmap replay source, artifacts and replay id active only for the
        # bounded test optimized hash is independent of batch and bounded readahead
        # operation.
        expected = _run_reference(replay, _MemorySink())
        actual = _run_optimized(
            replay,
            _MemorySink(),
            physical=EnginePhysicalSettings(batch_rows, readahead, 1),
            # Complete _run_optimized only after its memory sink and engine physical settings
            # inputs are visible in test optimized hash is independent of batch and bounded
            # readahead.
        )

    assert actual == expected


@pytest.mark.parametrize(
    ("mode", "observation_slots", "order_slots"),
    (
        # Open the mode and observation slots payload explicitly for parametrize within
        # test optimized dynamic latency and horizon semantics match reference.
        (ExecutionMode.EXOGENOUS_REPLAY, 0, 0),
        (ExecutionMode.SHADOW_STATE_REPLAY, 0, 1),
        (ExecutionMode.SHADOW_STATE_REPLAY, 1, 0),
        (ExecutionMode.SHADOW_STATE_REPLAY, 2, 0),
    ),
    # Complete parametrize only after its mode and observation slots inputs are visible in
    # test optimized dynamic latency and horizon semantics match reference.
)
def test_optimized_dynamic_latency_and_horizon_semantics_match_reference(
    tmp_path: Path,
    mode: ExecutionMode,
    observation_slots: int,
    # Keep the order slots input explicit in the test optimized dynamic latency and
    # horizon semantics match reference contract.
    order_slots: int,
) -> None:
    # Execute the test optimized dynamic latency and horizon semantics match reference
    # workflow in explicit, reviewable steps.
    artifacts, replay_id = _compile(tmp_path, _events())
    latency = SlotLatencyModel(observation_slots, order_slots)
    with NumpyMmapReplaySource(artifacts, replay_id) as replay:
        # Keep numpy mmap replay source, artifacts and replay id active only for the
        # bounded test optimized dynamic latency and horizon semantics match reference
        # operation.
        reference_sink = _MemorySink()
        optimized_sink = _MemorySink()
        reference = _run_reference(
            replay,
            reference_sink,
            # Keep the config and mode _config step visible while building reference.
            config=_config(mode=mode, latency=latency),
        )
        optimized = _run_optimized(
            replay,
            optimized_sink,
            # Keep the config and mode _config step visible while building optimized.
            config=_config(mode=mode, latency=latency),
        )

    assert optimized == reference
    assert optimized_sink.audit == reference_sink.audit
    assert optimized_sink.ledger == reference_sink.ledger
    # Verify the fills, optimized sink and reference sink relationship before this
    # scenario is accepted.
    assert optimized_sink.fills == reference_sink.fills


def test_optimized_backend_rejects_unsupported_surface_before_sink_mutation(
    tmp_path: Path,
) -> None:
    # Execute the test optimized backend rejects unsupported surface before sink mutation
    # workflow in explicit, reviewable steps.
    artifacts, replay_id = _compile(tmp_path, _events())
    engine = _engine()
    sink = _MemorySink()
    with (
        NumpyMmapReplaySource(artifacts, replay_id) as replay,
        # Acquire numpy mmap replay source, artifacts and replay id at an explicit test
        # optimized backend rejects unsupported surface before sink mutation context
        # boundary so cleanup remains scoped.
        pytest.raises(OptimizedBackendUnsupported, match="causal overlays"),
    ):
        # Keep numpy mmap replay source, artifacts and replay id active only for the
        # bounded test optimized backend rejects unsupported surface before sink mutation
        # operation.
        engine.run(
            source=replay,
            strategy=_strategy(),
            execution_model=ConstantProductExecutionModel(fee_bps=30),
            risk_policy=StaticRiskPolicy(maximum_order_input_atomic=1_000),
            # Pass config explicitly to run for strategy and constant product execution
            # model.
            config=_config(),
            sink=sink,
            features=_ScalarProvider(),
        )

    assert sink.audit == []
    # Verify sink.ledger == [] before this scenario is accepted.
    assert sink.ledger == []
    assert sink.fills == []


def test_optimized_backend_rejects_component_substitution_before_sink_mutation(
    tmp_path: Path,
) -> None:
    # Execute the test optimized backend rejects component substitution before sink
    # mutation workflow in explicit, reviewable steps.
    artifacts, replay_id = _compile(tmp_path, _events())
    sink = _MemorySink()
    with (
        NumpyMmapReplaySource(artifacts, replay_id) as replay,
        pytest.raises(OptimizedBackendUnsupported, match="exact FirstSwap"),
        # Acquire numpy mmap replay source, artifacts and replay id at an explicit test
        # optimized backend rejects component substitution before sink mutation context
        # boundary so cleanup remains scoped.
    ):
        # Keep numpy mmap replay source, artifacts and replay id active only for the
        # bounded test optimized backend rejects component substitution before sink
        # mutation operation.
        _engine().run(
            source=replay,
            strategy=_FirstSwapSubclass(
                pool_id=POOL,
                sold_asset_id=SOL,
                # Pass bought asset id explicitly so _FirstSwapSubclass receives a
                # reviewable pool and sol input in test optimized backend rejects
                # component substitution before sink mutation.
                bought_asset_id=TOKEN,
                amount_in_atomic=100,
            ),
            execution_model=ConstantProductExecutionModel(fee_bps=30),
            risk_policy=StaticRiskPolicy(maximum_order_input_atomic=1_000),
            # Pass config explicitly to run for first swap subclass and constant product
            # execution model.
            config=_config(),
            sink=sink,
        )

    assert sink.audit == []
    assert sink.ledger == []
    # Verify sink.fills == [] before this scenario is accepted.
    assert sink.fills == []


def test_optimized_backend_rejects_non_exact_ordering_before_sink_mutation(
    tmp_path: Path,
) -> None:
    # Execute the test optimized backend rejects non exact ordering before sink mutation
    # workflow in explicit, reviewable steps.
    events = list(_events())
    final = events[-1]
    assert isinstance(final, BlockEvent)
    events[-1] = BlockEvent(
        EventEnvelope(
            # Pass position explicitly so EventEnvelope receives a reviewable position and
            # envelope input in test optimized backend rejects non exact ordering before
            # sink mutation.
            position=final.envelope.position,
            transaction_group_id=final.envelope.transaction_group_id,
            source_record_id=final.envelope.source_record_id,
            canonical_event_id=final.envelope.canonical_event_id,
            stable_causal_id=final.envelope.stable_causal_id,
            # Pass capability id explicitly so EventEnvelope receives a reviewable
            # position and envelope input in test optimized backend rejects non exact
            # ordering before sink mutation.
            capability_id=final.envelope.capability_id,
            protocol=final.envelope.protocol,
            protocol_version=final.envelope.protocol_version,
            ordering_fidelity=OrderingFidelity.TRANSACTION_PARTIAL,
        ),
        # Pass block time ns explicitly so BlockEvent receives a reviewable position and
        # transaction group id input in test optimized backend rejects non exact ordering
        # before sink mutation.
        block_time_ns=final.block_time_ns,
        tx_count=final.tx_count,
        block_hash=final.block_hash,
    )
    artifacts, replay_id = _compile(tmp_path, tuple(events))
    # Assemble sink once so the test optimized backend rejects non exact ordering before
    # sink mutation workflow shares one value.
    sink = _MemorySink()
    with (
        NumpyMmapReplaySource(artifacts, replay_id) as replay,
        pytest.raises(OptimizedBackendUnsupported, match="exact transaction"),
    ):
        # Invoke _run_optimized for replay and sink as a visible test optimized backend
        # rejects non exact ordering before sink mutation step.
        _run_optimized(replay, sink)
    assert sink.audit == []


# Keep the scalar provider contract and validation rules together.
class _ScalarProvider:
    def value_at(self, name: str, entity_id: int, boundary_ordinal: int) -> None:
        # Execute the scalar provider value at workflow in explicit, reviewable steps.
        del name, entity_id, boundary_ordinal
        return None


class _FirstSwapSubclass(FirstSwapStrategy):
    pass


def _run_reference(
    # Keep the replay input explicit in the run reference contract.
    replay: NumpyMmapReplaySource,
    sink: _MemorySink,
    *,
    config: ReferenceRunConfig | None = None,
):
    # Execute the run reference workflow in explicit, reviewable steps.
    return ReferenceBacktestEngine().run(
        source=replay,
        strategy=_strategy(),
        execution_model=ConstantProductExecutionModel(fee_bps=30),
        risk_policy=StaticRiskPolicy(maximum_order_input_atomic=1_000),
        # Include config in the completed run reference result.
        config=_config() if config is None else config,
        sink=sink,
    )


def _run_optimized(
    replay: NumpyMmapReplaySource,
    # Keep the sink input explicit in the run optimized contract.
    sink: _MemorySink,
    *,
    physical: EnginePhysicalSettings = DEFAULT_ENGINE_PHYSICAL_SETTINGS,
    config: ReferenceRunConfig | None = None,
):
    # Execute the run optimized workflow in explicit, reviewable steps.
    return _engine().run(
        source=replay,
        strategy=_strategy(),
        execution_model=ConstantProductExecutionModel(fee_bps=30),
        risk_policy=StaticRiskPolicy(maximum_order_input_atomic=1_000),
        # Include config in the completed run optimized result.
        config=_config() if config is None else config,
        sink=sink,
        physical_settings=physical,
    )


def _engine() -> NumpyMmapFirstSwapEngine:
    # Execute the engine workflow in explicit, reviewable steps.
    return NumpyMmapFirstSwapEngine(
        strategy_type=FirstSwapStrategy,
        execution_model_type=ConstantProductExecutionModel,
        risk_policy_type=StaticRiskPolicy,
    )


# Define strategy as one focused operation with an explicit boundary.
def _strategy() -> FirstSwapStrategy:
    # Execute the strategy workflow in explicit, reviewable steps.
    return FirstSwapStrategy(
        pool_id=POOL,
        sold_asset_id=SOL,
        bought_asset_id=TOKEN,
        amount_in_atomic=100,
        # Complete FirstSwapStrategy only after its pool and sol inputs are visible in
        # strategy.
    )


def _config(
    *,
    mode: ExecutionMode = ExecutionMode.SHADOW_STATE_REPLAY,
    latency: SlotLatencyModel | None = None,
    # Keep the reference run config input explicit in the config contract.
) -> ReferenceRunConfig:
    # Execute the config workflow in explicit, reviewable steps.
    return ReferenceRunConfig(
        execution_mode=mode,
        latency=SlotLatencyModel() if latency is None else latency,
        root_seed=42,
        initial_available={SOL: 1_000},
        # Complete ReferenceRunConfig only after its slot latency model and mode inputs are
        # visible in config.
    )


def _compile(
    tmp_path: Path,
    events: tuple[CanonicalEvent, ...],
) -> tuple[LocalArtifactRepository, ReplayPackId]:
    # Execute the compile workflow in explicit, reviewable steps.
    artifacts = LocalArtifactRepository(tmp_path / "var")
    writer = artifacts.stage(ArtifactDraft(ArtifactKind.SNAPSHOT, ContentDigest("a" * 64)))
    snapshot = writer.commit(canonical_json_bytes(_snapshot_manifest()))
    snapshot_id = SnapshotId(snapshot.artifact_id.hex)
    result = LocalNumpyReplayPackCompiler(
        # Pass artifacts explicitly so compile receives a reviewable snapshot id and
        # compiler version input in compile.
        artifacts,
        lambda requested: _CanonicalSource(events),
        runtime_lock_id=RuntimeLockId("9" * 64),
    ).compile(snapshot_id, COMPILER_VERSION)
    return artifacts, result.replay_pack_id


# Define snapshot manifest as one focused operation with an explicit boundary.
def _snapshot_manifest() -> dict[str, object]:
    return fixture_snapshot_manifest()


def _events() -> tuple[CanonicalEvent, ...]:
    # Execute the events workflow in explicit, reviewable steps.
    return (
        BlockEvent(_envelope(100, -1, 0, 1), 100_000_000_000, 1),
        TokenCreationEvent(
            envelope=_envelope(100, 0, 0, 2, group_identity=2),
            asset_id=TOKEN,
            # Include developer id in the completed events result.
            developer_id=AccountId("creator"),
            creation_user_id=AccountId("creator"),
            venue_id=VenueId("launch:TOKEN"),
            quote_asset_id=SOL,
            protocol_payload_schema=ProtocolPayloadSchemaId("reference-token-launch-payload-v1"),
            # Pass protocol payload explicitly so TokenCreationEvent receives a reviewable
            # creator and launch:token input in events.
            protocol_payload=b"",
            decimals=6,
        ),
        SwapEvent(
            envelope=_envelope(100, 0, 1, 3, group_identity=2),
            # Include venue id in the completed events result.
            venue_id=VenueId(POOL.value),
            sold_asset_id=SOL,
            bought_asset_id=TOKEN,
            sold_amount_atomic=100,
            bought_amount_atomic=900,
            # Include fee components in the completed events result.
            fee_components=(FeeComponent(FeeComponentId("protocol"), SOL, 1),),
            protocol_payload_schema=REFERENCE_AMM_TRADE_PAYLOAD_SCHEMA_ID,
            protocol_payload=reference_amm_trade_payload(
                asset_a_id=SOL,
                asset_b_id=TOKEN,
                # Pass reserve a after atomic explicitly so reference_amm_trade_payload
                # receives a reviewable sol and token input in events.
                reserve_a_after_atomic=1_000,
                reserve_b_after_atomic=10_000,
            ),
        ),
        BlockEvent(_envelope(101, -1, 0, 4), 101_000_000_000, 0),
        # Return the completed events result without a hidden fallback.
    )


def _envelope(
    slot: int,
    transaction_index: int,
    event_index: int,
    # Keep the identity input explicit in the envelope contract.
    identity: int,
    *,
    group_identity: int | None = None,
) -> EventEnvelope:
    # Execute the envelope workflow in explicit, reviewable steps.
    position = ChainPosition(
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        block_ordinal=slot,
        transaction_index=transaction_index,
        # Pass event index explicitly so ChainPosition receives a reviewable solana
        # mainnet network id and block32 transaction32 position schema id input in
        # envelope.
        event_index=event_index,
    )
    return EventEnvelope(
        position,
        ContentDigest(f"{identity if group_identity is None else group_identity:064x}"),
        # Include content digest in the completed envelope result.
        ContentDigest(f"{identity + 100:064x}"),
        ContentDigest(f"{identity + 200:064x}"),
        ContentDigest(f"{identity + 300:064x}"),
        CapabilityId("fixture.events.v1"),
        "reference_amm",
        # Pass declared text explicitly so EventEnvelope receives a reviewable 064x and v1
        # input in envelope.
        "1",
        OrderingFidelity.INSTRUCTION_EXACT,
    )
