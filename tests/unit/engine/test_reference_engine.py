# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest

from backtest.domain.chain import (
    # Include block32 transaction32 position schema id so the chain dependency remains
    # explicit.
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
)
from backtest.domain.execution import ExecutionMode, Fill
from backtest.domain.fidelity import OrderingFidelity

# Import hashing at the visible module dependency boundary.
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import (
    AssetId,
    CapabilityId,
    ContentDigest,
    # Include dataset revision id so the identifiers dependency remains explicit.
    DatasetRevisionId,
    LogicalContentHash,
    NetworkId,
    PoolId,
    VenueId,
    # Close the identifiers import after its required symbols are visible.
)
from backtest.domain.ledger import LedgerCorrelationKind, LedgerTransaction
from backtest.domain.market_events import (
    REFERENCE_AMM_TRADE_PAYLOAD_SCHEMA_ID,
    BlockEvent,
    # Include canonical event so the market events dependency remains explicit.
    CanonicalEvent,
    ChainPosition,
    EventEnvelope,
    SwapEvent,
    reference_amm_trade_payload,
    # Close the market events import after its required symbols are visible.
)
from backtest.engine.reference import (
    EngineInvariantError,
    ReferenceBacktestEngine,
    ReferenceRunConfig,
    # Include run summary so the reference dependency remains explicit.
    RunSummary,
    SlotLatencyModel,
)
from backtest.engine.replay import ObservationDelivery, ObservationDeliverySource, ReplayBoundary
from backtest.plugins.execution import ConstantProductExecutionModel

# Import risk at the visible module dependency boundary.
from backtest.plugins.risk import StaticRiskPolicy
from backtest.plugins.strategies import FirstSwapStrategy

SOL = AssetId("SOL")
TOKEN = AssetId("TOKEN")
POOL = PoolId("pool")


def test_first_swap_config_rejects_sniping_only_virtual_settlement_mode() -> None:
    with pytest.raises(ValueError, match="execution mode is unsupported"):
        ReferenceRunConfig(
            execution_mode=ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT,
            latency=SlotLatencyModel(),
            root_seed=42,
            initial_available={SOL: 1_000},
        )


# Keep the memory sink contract and validation rules together.
@dataclass
class _MemorySink:
    audits: list[dict[str, object]] = field(default_factory=list)
    ledger: list[LedgerTransaction] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)

    # Define memory sink append audit as one focused operation with an explicit boundary.
    def append_audit(self, record: dict[str, object]) -> None:
        self.audits.append(record)

    def append_ledger(self, transaction: LedgerTransaction) -> None:
        self.ledger.append(transaction)

    def append_fill(self, fill: Fill) -> None:
        # Invoke append for fill as a visible memory sink append fill step.
        self.fills.append(fill)


# Keep the source contract and validation rules together.
@dataclass(frozen=True)
class _Source:
    values: tuple[CanonicalEvent, ...]

    @property
    def dataset_revision_id(self) -> DatasetRevisionId:
        # Return the completed source dataset revision id result without a hidden
        # fallback.
        return DatasetRevisionId("1" * 64)

    @property
    def logical_content_hash(self) -> LogicalContentHash:
        return LogicalContentHash("2" * 64)

    @property
    # Define source replay semantics id as one focused operation with an explicit
    # boundary.
    def replay_semantics_id(self) -> ContentDigest:
        return ContentDigest("3" * 64)

    def boundaries(self) -> tuple[ReplayBoundary, ...]:
        # Execute the source boundaries workflow in explicit, reviewable steps.
        seen: dict[int, ChainPosition] = {}
        for event in self.values:
            seen[event.envelope.boundary_ordinal] = event.envelope.position
        return tuple(ReplayBoundary.from_position(seen[key]) for key in sorted(seen))

    def events(self) -> Iterator[CanonicalEvent]:
        # Keep the yield step explicit within the source events workflow.
        yield from self.values

    @property
    def event_count(self) -> int:
        return len(self.values)

    def event_at(self, event_row_index: int) -> CanonicalEvent:
        # Return the completed source event at result without a hidden fallback.
        return self.values[event_row_index]


# Keep the schedule contract and validation rules together.
@dataclass(frozen=True)
class _Schedule:
    values: tuple[ObservationDelivery, ...]
    input_event_count: int
    outside_horizon_count: int
    # Declare declared delivery count explicitly in the schedule contract.
    declared_delivery_count: int | None = None

    @property
    def delivery_count(self) -> int:
        # Execute the schedule delivery count workflow in explicit, reviewable steps.
        if self.declared_delivery_count is None:
            return len(self.values)
        return self.declared_delivery_count

    def deliveries(self) -> Iterator[ObservationDelivery]:
        yield from self.values


# Define test reference engine is repeatable causal and conserves every transaction as one
# focused operation with an explicit boundary.
def test_reference_engine_is_repeatable_causal_and_conserves_every_transaction() -> None:
    # Execute the test reference engine is repeatable causal and conserves every
    # transaction workflow in explicit, reviewable steps.
    source = _Source(
        (
            _block(100),
            _swap(100, 0, "first", 1_000, 10_000),
            _block(101),
            # Keep the block _block step visible while building source.
            _block(102),
        )
    )
    first_sink = _MemorySink()
    second_sink = _MemorySink()

    # Assemble first once so the test reference engine is repeatable causal and conserves
    # every transaction workflow shares one value.
    first = _run(source, first_sink)
    second = _run(source, second_sink)

    assert first.audit_hash == second.audit_hash
    assert first.result_hash == second.result_hash
    assert first.ledger_hash == second.ledger_hash
    # Verify first.fill_hash == second.fill_hash before this scenario is accepted.
    assert first.fill_hash == second.fill_hash
    assert (
        first.audit_hash.hex == "21f8d426d2e8fcec3b725914abdbd1e3f91a043aaec0626d7d33e247595ae0ab"
    )
    assert (
        # Keep the hex expectation tied to hex, result hash and first in this scenario.
        first.result_hash.hex == "953ad06748dbcb6617d95b958aa4d52382d267e55637d2253c81c51c1c9d73e7"
    )
    assert first.accepted_order_count == first.filled_order_count == 1
    assert first.failed_order_count == first.rejected_order_count == 0
    assert len(first_sink.fills) == 1
    # Assemble decision once so the test reference engine is repeatable causal and
    # conserves every transaction workflow shares one value.
    decision = next(
        int(record["boundary_ordinal"])
        for record in first_sink.audits
        if record["record_type"] == "INTENT_PROPOSED"
    )
    # Verify the boundary ordinal, decision and fills relationship before this scenario is
    # accepted.
    assert first_sink.fills[0].boundary_ordinal > decision
    assert all(
        sum(posting.amount_atomic for posting in transaction.postings if posting.asset_id == asset)
        == 0
        for transaction in first_sink.ledger
        # Pass asset explicitly so all receives a reviewable ledger and asset id input in
        # test reference engine is repeatable causal and conserves every transaction.
        for asset in {posting.asset_id for posting in transaction.postings}
    )
    assert {transaction.correlation_kind for transaction in first_sink.ledger} == {
        LedgerCorrelationKind.ORDER
    }
    # Verify the correlation id, transaction and ledger relationship before this scenario
    # is accepted.
    assert {transaction.correlation_id for transaction in first_sink.ledger} == {
        ContentDigest(first_sink.fills[0].order_id.hex)
    }
    assert _balance(first.final_balances, "portfolio:reserved:SOL", "SOL") == 0
    assert _balance(first.final_balances, "portfolio:available:SOL", "SOL") == 900
    # Verify the balance, final balances and portfolio:available:token relationship before
    # this scenario is accepted.
    assert _balance(first.final_balances, "portfolio:available:TOKEN", "TOKEN") == 909


def test_slot_latency_rounds_to_real_boundary_and_order_remains_strictly_future() -> None:
    # Execute the test slot latency rounds to real boundary and order remains strictly
    # future workflow in explicit, reviewable steps.
    source = _Source(
        (
            _block(100),
            _swap(100, 0, "first", 1_000, 10_000),
            _block(101),
            # Keep the block _block step visible while building source.
            _block(102),
            _block(103),
        )
    )
    sink = _MemorySink()
    # Assemble summary once so the test slot latency rounds to real boundary and order
    # remains strictly future workflow shares one value.
    summary = _run(
        source,
        sink,
        latency=SlotLatencyModel(observation_slots=1, order_slots=1),
    )

    # Verify summary.filled_order_count == 1 before this scenario is accepted.
    assert summary.filled_order_count == 1
    decision = next(
        int(record["boundary_ordinal"])
        for record in sink.audits
        if record["record_type"] == "INTENT_PROPOSED"
        # Complete next only after its boundary ordinal and intent proposed inputs are visible
        # in test slot latency rounds to real boundary and order remains strictly future.
    )
    assert decision == _block(101).envelope.boundary_ordinal
    assert sink.fills[0].boundary_ordinal == _block(102).envelope.boundary_ordinal
    assert sink.fills[0].boundary_ordinal > decision


def test_materialized_observation_merge_is_byte_identical_to_dynamic_scheduler() -> None:
    # Execute the test materialized observation merge is byte identical to dynamic
    # scheduler workflow in explicit, reviewable steps.
    source = _Source(
        (
            _block(100),
            _swap(100, 0, "first", 1_000, 10_000),
            _block(101),
            # Keep the block _block step visible while building source.
            _block(102),
        )
    )
    boundaries = source.boundaries()
    schedule = _Schedule(
        # Pass values explicitly so _Schedule receives a reviewable boundary ordinal and
        # observation delivery input in test materialized observation merge is byte
        # identical to dynamic scheduler.
        values=(
            ObservationDelivery(boundaries[2].boundary_ordinal, 0),
            ObservationDelivery(boundaries[2].boundary_ordinal, 1),
            ObservationDelivery(boundaries[3].boundary_ordinal, 2),
        ),
        # Pass input event count explicitly so _Schedule receives a reviewable boundary
        # ordinal and observation delivery input in test materialized observation merge is
        # byte identical to dynamic scheduler.
        input_event_count=4,
        outside_horizon_count=1,
    )
    dynamic_sink = _MemorySink()
    materialized_sink = _MemorySink()

    # Assemble dynamic once so the test materialized observation merge is byte identical
    # to dynamic scheduler workflow shares one value.
    dynamic = _run(
        source,
        dynamic_sink,
        latency=SlotLatencyModel(observation_slots=1, order_slots=1),
    )
    # Assemble materialized once so the test materialized observation merge is byte
    # identical to dynamic scheduler workflow shares one value.
    materialized = _run(
        source,
        materialized_sink,
        latency=SlotLatencyModel(observation_slots=1, order_slots=1),
        delivery_schedule=schedule,
        # Complete _run only after its slot latency model and source inputs are visible in
        # test materialized observation merge is byte identical to dynamic scheduler.
    )

    assert materialized == dynamic
    assert materialized_sink.audits == dynamic_sink.audits
    assert materialized_sink.ledger == dynamic_sink.ledger
    assert materialized_sink.fills == dynamic_sink.fills


# Define test materialized observation merge rejects wrong release and truncation as one
# focused operation with an explicit boundary.
def test_materialized_observation_merge_rejects_wrong_release_and_truncation() -> None:
    # Execute the test materialized observation merge rejects wrong release and truncation
    # workflow in explicit, reviewable steps.
    source = _Source((_block(100), _block(101)))
    boundaries = source.boundaries()
    wrong_release = _Schedule(
        values=(ObservationDelivery(boundaries[0].boundary_ordinal, 0),),
        input_event_count=2,
        # Pass outside horizon count explicitly so _Schedule receives a reviewable
        # boundary ordinal and observation delivery input in test materialized observation
        # merge rejects wrong release and truncation.
        outside_horizon_count=1,
    )
    truncated = _Schedule(
        values=(),
        input_event_count=2,
        # Pass outside horizon count explicitly into _Schedule within test materialized
        # observation merge rejects wrong release and truncation.
        outside_horizon_count=1,
        declared_delivery_count=1,
    )

    with pytest.raises(EngineInvariantError, match="differs from resolved latency"):
        # Keep raises, engine invariant error and pytest active only for the bounded test
        # materialized observation merge rejects wrong release and truncation operation.
        _run(
            source,
            _MemorySink(),
            latency=SlotLatencyModel(observation_slots=1),
            delivery_schedule=wrong_release,
            # Complete _run only after its memory sink and slot latency model inputs are
            # visible in test materialized observation merge rejects wrong release and
            # truncation.
        )
    with pytest.raises(EngineInvariantError, match=r"wrong count|omitted"):
        # Keep raises, engine invariant error and pytest active only for the bounded test
        # materialized observation merge rejects wrong release and truncation operation.
        _run(
            source,
            _MemorySink(),
            latency=SlotLatencyModel(observation_slots=1),
            delivery_schedule=truncated,
            # Complete _run only after its memory sink and slot latency model inputs are
            # visible in test materialized observation merge rejects wrong release and
            # truncation.
        )


def test_future_poison_cannot_change_an_earlier_decision_or_fill() -> None:
    # Execute the test future poison cannot change an earlier decision or fill workflow in
    # explicit, reviewable steps.
    prefix = (
        _block(100),
        _swap(100, 0, "first", 1_000, 10_000),
        _block(101),
    )
    # Assemble plain sink once so the test future poison cannot change an earlier decision
    # or fill workflow shares one value.
    plain_sink = _MemorySink()
    poison_sink = _MemorySink()
    _run(_Source(prefix), plain_sink)
    _run(
        _Source((*prefix, _swap(102, 0, "future-poison", 50_000, 7), _block(103))),
        # Pass poison sink explicitly so _run receives a reviewable future-poison and
        # source input in test future poison cannot change an earlier decision or fill.
        poison_sink,
    )

    plain_intent = next(
        record for record in plain_sink.audits if record["record_type"] == "INTENT_PROPOSED"
    )
    # Assemble poison intent once so the test future poison cannot change an earlier
    # decision or fill workflow shares one value.
    poison_intent = next(
        record for record in poison_sink.audits if record["record_type"] == "INTENT_PROPOSED"
    )
    assert plain_intent == poison_intent
    assert plain_sink.fills[0] == poison_sink.fills[0]


# Define test expected execution rejection releases the entire reservation as one focused
# operation with an explicit boundary.
def test_expected_execution_rejection_releases_the_entire_reservation() -> None:
    # Execute the test expected execution rejection releases the entire reservation
    # workflow in explicit, reviewable steps.
    source = _Source(
        (
            _block(100),
            _swap(100, 0, "first", 1_000, 10_000),
            _block(101),
            # Complete _Source only after its first and block inputs are visible in test
            # expected execution rejection releases the entire reservation.
        )
    )
    sink = _MemorySink()
    summary = _run(source, sink, minimum_amount_out_atomic=9_999)

    assert summary.failed_order_count == 1
    # Verify summary.fill_count == 0 before this scenario is accepted.
    assert summary.fill_count == 0
    assert summary.ledger_transaction_count == 2
    assert _balance(summary.final_balances, "portfolio:reserved:SOL", "SOL") == 0
    assert _balance(summary.final_balances, "portfolio:available:SOL", "SOL") == 1_000
    assert any(
        # Pass record explicitly so any receives a reviewable order execution failed and
        # released and minimum output not met input in test expected execution rejection
        # releases the entire reservation.
        record["record_type"] == "ORDER_EXECUTION_FAILED_AND_RELEASED"
        and record["reason"] == "MINIMUM_OUTPUT_NOT_MET"
        for record in sink.audits
    )


def test_non_canonical_source_order_fails_closed() -> None:
    # Execute the test non canonical source order fails closed workflow in explicit,
    # reviewable steps.
    source = _Source((_swap(100, 0, "first", 1_000, 10_000), _block(100)))

    with pytest.raises(EngineInvariantError, match="strict canonical order"):
        _run(source, _MemorySink())


def test_reference_engine_rejects_mixed_network_boundaries() -> None:
    # Both networks are well-formed, so rejection must occur at the mixed-stream guard.
    source = _Source(
        (
            _block(100),
            _block(101, network_id=NetworkId("solana:11111111111111111111111111111112")),
        )
        # The next engine boundary must not silently replace the first network identity.
    )

    with pytest.raises(EngineInvariantError, match="mix network or position schema"):
        _run(source, _MemorySink())


@pytest.mark.parametrize(
    "ordering_fidelity",
    # Open the ordering fidelity and unknown payload explicitly for parametrize within
    # test ambiguous transaction order fails before historical state is applied.
    (OrderingFidelity.UNKNOWN, OrderingFidelity.TRANSACTION_PARTIAL),
)
def test_ambiguous_transaction_order_fails_before_historical_state_is_applied(
    ordering_fidelity: OrderingFidelity,
) -> None:
    # Execute the test ambiguous transaction order fails before historical state is
    # applied workflow in explicit, reviewable steps.
    event = _swap(100, 0, "ambiguous", 1_000, 10_000)
    ambiguous = SwapEvent(
        envelope=EventEnvelope(
            position=ChainPosition(
                network_id=SOLANA_MAINNET_NETWORK_ID,
                # Pass position schema id explicitly so ChainPosition receives a
                # reviewable solana mainnet network id and block32 transaction32 position
                # schema id input in test ambiguous transaction order fails before
                # historical state is applied.
                position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
                block_ordinal=100,
                transaction_index=0,
                event_index=None,
            ),
            # Pass transaction group id explicitly so EventEnvelope receives a reviewable
            # transaction group id and envelope input in test ambiguous transaction order
            # fails before historical state is applied.
            transaction_group_id=event.envelope.transaction_group_id,
            source_record_id=event.envelope.source_record_id,
            canonical_event_id=event.envelope.canonical_event_id,
            stable_causal_id=event.envelope.stable_causal_id,
            capability_id=event.envelope.capability_id,
            # Pass protocol explicitly so EventEnvelope receives a reviewable transaction
            # group id and envelope input in test ambiguous transaction order fails before
            # historical state is applied.
            protocol=event.envelope.protocol,
            protocol_version=event.envelope.protocol_version,
            ordering_fidelity=ordering_fidelity,
        ),
        venue_id=event.venue_id,
        # Pass sold asset id explicitly so SwapEvent receives a reviewable transaction
        # group id and source record id input in test ambiguous transaction order fails
        # before historical state is applied.
        sold_asset_id=event.sold_asset_id,
        bought_asset_id=event.bought_asset_id,
        sold_amount_atomic=event.sold_amount_atomic,
        bought_amount_atomic=event.bought_amount_atomic,
        fee_components=event.fee_components,
        # Pass protocol payload schema explicitly so SwapEvent receives a reviewable
        # transaction group id and source record id input in test ambiguous transaction
        # order fails before historical state is applied.
        protocol_payload_schema=event.protocol_payload_schema,
        protocol_payload=event.protocol_payload,
    )
    sink = _MemorySink()

    with pytest.raises(RuntimeError, match="ordering is ambiguous"):
        # Invoke _run for source and ambiguous as a visible test ambiguous transaction
        # order fails before historical state is applied step.
        _run(_Source((ambiguous,)), sink)

    assert sink.audits == []
    assert sink.ledger == []
    assert sink.fills == []


def _run(
    # Keep the source input explicit in the run contract.
    source: _Source,
    sink: _MemorySink,
    *,
    latency: SlotLatencyModel | None = None,
    minimum_amount_out_atomic: int = 0,
    # Keep the delivery schedule input explicit in the run contract.
    delivery_schedule: ObservationDeliverySource | None = None,
) -> RunSummary:
    # Execute the run workflow in explicit, reviewable steps.
    strategy = FirstSwapStrategy(
        pool_id=POOL,
        sold_asset_id=SOL,
        bought_asset_id=TOKEN,
        amount_in_atomic=100,
        # Pass minimum amount out atomic explicitly so FirstSwapStrategy receives a
        # reviewable pool and sol input in run.
        minimum_amount_out_atomic=minimum_amount_out_atomic,
    )
    return ReferenceBacktestEngine().run(
        source=source,
        strategy=strategy,
        # Include execution model in the completed run result.
        execution_model=ConstantProductExecutionModel(fee_bps=30),
        risk_policy=StaticRiskPolicy(maximum_order_input_atomic=1_000),
        config=ReferenceRunConfig(
            execution_mode=ExecutionMode.SHADOW_STATE_REPLAY,
            latency=SlotLatencyModel() if latency is None else latency,
            # Pass root seed explicitly so ReferenceRunConfig receives a reviewable shadow
            # state replay and slot latency model input in run.
            root_seed=42,
            initial_available={SOL: 1_000},
        ),
        sink=sink,
        delivery_schedule=delivery_schedule,
        # Complete run only after its shadow state replay and constant product execution model
        # inputs are visible in run.
    )


def _block(
    slot: int,
    *,
    network_id: NetworkId = SOLANA_MAINNET_NETWORK_ID,
    # Keep the block event input explicit in the block contract.
) -> BlockEvent:
    # Execute the block workflow in explicit, reviewable steps.
    position = _position(slot, -1, 0, network_id=network_id)
    return BlockEvent(_envelope(position, f"block-{slot}"), slot * 1_000_000, 1)


def _swap(
    slot: int,
    transaction_index: int,
    # Keep the identity input explicit in the swap contract.
    identity: str,
    reserve_a_after_atomic: int,
    reserve_b_after_atomic: int,
) -> SwapEvent:
    # Execute the swap workflow in explicit, reviewable steps.
    position = _position(slot, transaction_index, 0)
    return SwapEvent(
        envelope=_envelope(position, identity),
        venue_id=VenueId(POOL.value),
        sold_asset_id=SOL,
        # Pass bought asset id explicitly so SwapEvent receives a reviewable value and
        # envelope input in swap.
        bought_asset_id=TOKEN,
        sold_amount_atomic=100,
        bought_amount_atomic=900,
        fee_components=(),
        protocol_payload_schema=REFERENCE_AMM_TRADE_PAYLOAD_SCHEMA_ID,
        # Include protocol payload in the completed swap result.
        protocol_payload=reference_amm_trade_payload(
            asset_a_id=SOL,
            asset_b_id=TOKEN,
            reserve_a_after_atomic=reserve_a_after_atomic,
            reserve_b_after_atomic=reserve_b_after_atomic,
            # Complete reference_amm_trade_payload only after its sol and token inputs are
            # visible in swap.
        ),
    )


def _position(
    block_ordinal: int,
    transaction_index: int,
    # Keep the event index input explicit in the position contract.
    event_index: int | None,
    *,
    network_id: NetworkId = SOLANA_MAINNET_NETWORK_ID,
) -> ChainPosition:
    # Execute the position workflow in explicit, reviewable steps.
    return ChainPosition(
        network_id=network_id,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        block_ordinal=block_ordinal,
        transaction_index=transaction_index,
        # Pass event index explicitly so ChainPosition receives a reviewable network id
        # and block32 transaction32 position schema id input in position.
        event_index=event_index,
    )


def _envelope(position: ChainPosition, identity: str) -> EventEnvelope:
    # Execute the envelope workflow in explicit, reviewable steps.
    group = domain_digest(
        "test.transaction-group.v1",
        {
            "network_id": position.network_id.value,
            "identity": identity,
            # Keep block ordinal named so the v1 and network id payload passed to
            # domain_digest remains self-describing within envelope.
            "block_ordinal": position.block_ordinal,
            "position_schema_id": position.position_schema_id.value,
            "transaction_index": position.transaction_index,
        },
    )
    # Assemble source once so the envelope workflow shares one value.
    source = domain_digest("test.source-record.v1", {"identity": identity})
    event = domain_digest("test.canonical-event.v1", {"identity": identity})
    causal = domain_digest("test.stable-causal.v1", {"identity": identity})
    return EventEnvelope(
        position=position,
        # Pass transaction group id explicitly so EventEnvelope receives a reviewable v1
        # and reference amm input in envelope.
        transaction_group_id=group,
        source_record_id=source,
        canonical_event_id=event,
        stable_causal_id=causal,
        capability_id=CapabilityId("test.events.v1"),
        # Pass protocol explicitly so EventEnvelope receives a reviewable v1 and reference
        # amm input in envelope.
        protocol="reference_amm",
        protocol_version="1",
        ordering_fidelity=OrderingFidelity.INSTRUCTION_EXACT,
    )


def _balance(
    # Keep the balances input explicit in the balance contract.
    balances: tuple[tuple[str, str, str, int], ...],
    account_id: str,
    asset_id: str,
) -> int:
    # Execute the balance workflow in explicit, reviewable steps.
    return next(
        (
            amount
            for account, _, asset, amount in balances
            if account == account_id and asset == asset_id
            # Complete next only after its amount and balances inputs are visible in balance.
        ),
        0,
    )
