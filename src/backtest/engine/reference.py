"""Readable, deterministic and causal reference backtest reducer.

This backend is deliberately straightforward. It is the semantic oracle for
future optimized/mmap backends: all of them must produce byte-identical audit
and result hashes for ``CANONICAL_EXACT`` runs.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from itertools import groupby, pairwise

# Import execution at the visible module dependency boundary.
from backtest.domain.execution import (
    ExecutionMode,
    ExecutionNotification,
    ExecutionPlan,
    ExecutionRejected,
    # Include fill so the execution dependency remains explicit.
    Fill,
    OrderStatus,
)
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import (
    # Include asset id so the identifiers dependency remains explicit.
    AssetId,
    BundleId,
    ContentDigest,
    LogicalContentHash,
    OrderId,
    # Close the identifiers import after its required symbols are visible.
)
from backtest.domain.intents import SwapExactInIntent
from backtest.domain.ledger import (
    AccountKind,
    LedgerAccount,
    # Include ledger correlation kind so the ledger dependency remains explicit.
    LedgerCorrelationKind,
    LedgerTransaction,
    Posting,
)
from backtest.domain.market_events import CanonicalEvent, canonical_event_sort_key

# Import audit at the visible module dependency boundary.
from backtest.engine.audit import (
    CanonicalStreamHasher,
    fill_document,
    ledger_document,
    posting_documents,
    # Close the audit import after its required symbols are visible.
)
from backtest.engine.causal_data import (
    CausalScalarProvider,
    CausalScalarView,
    EmptyCausalScalarProvider,
    # Close the causal data import after its required symbols are visible.
)
from backtest.engine.contracts import (
    DEFAULT_ENGINE_PHYSICAL_SETTINGS,
    EnginePhysicalSettings,
    ObservedMarketView,
    # Include portfolio view so the contracts dependency remains explicit.
    PortfolioView,
    RiskPolicy,
    RunEventSink,
    StrategyContext,
    StrategyInstance,
    # Include venue execution model so the contracts dependency remains explicit.
    VenueExecutionModel,
)
from backtest.engine.portfolio import (
    PortfolioState,
    available_account_id,
    # Include reserved account id so the portfolio dependency remains explicit.
    reserved_account_id,
)
from backtest.engine.replay import (
    HistoricalEventSource,
    IndexedHistoricalEventSource,
    # Include observation delivery so the replay dependency remains explicit.
    ObservationDelivery,
    ObservationDeliverySource,
    ReplayBoundary,
)
from backtest.engine.rng import KeyedRng

# Import scheduler at the visible module dependency boundary.
from backtest.engine.scheduler import (
    CausalScheduler,
    SchedulerInstant,
    SchedulerKey,
    SchedulerPhase,
    # Close the scheduler import after its required symbols are visible.
)
from backtest.engine.state import HistoricalReferenceState, ObservedState, SimulationVenueState

ENGINE_BUNDLE_ID = BundleId(
    domain_digest(
        "backtest.reference-engine-bundle.v2",
        # Open the v2 and arithmetic payload explicitly for domain_digest within module.
        {
            "arithmetic": "checked-integer-v1",
            "audit": "canonical-stream-v1",
            "chain_identity": "explicit-network-position-schema-v1",
            "group_policy": "atomic-v1",
            # Keep scheduler named so the v2 and arithmetic payload passed to
            # domain_digest remains self-describing within module.
            "scheduler": "canonical-phases-v1",
        },
    ).hex
)

SLOT_LATENCY_MODEL_BUNDLE_ID = BundleId(
    # Keep the v1 domain_digest step visible while building slot latency model bundle id.
    domain_digest(
        "backtest.slot-latency-model-bundle.v1",
        {"rounding": "ceil-to-first-real-boundary-v1", "unit": "slot"},
    ).hex
)


# Keep the engine invariant error contract and validation rules together.
class EngineInvariantError(RuntimeError):
    """An input or plugin violated a deterministic engine contract."""


@dataclass(frozen=True, slots=True)
class SlotLatencyModel:
    """Explicit slot-based observation and order latency policy."""

    observation_slots: int = 0
    order_slots: int = 0
    bundle_identity: BundleId = SLOT_LATENCY_MODEL_BUNDLE_ID

    def __post_init__(self) -> None:
        # Execute the slot latency model post init workflow in explicit, reviewable steps.
        for field_name in ("observation_slots", "order_slots"):
            # Process ('observation_slots', 'order_slots') inside the bounded slot latency
            # model post init loop.
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")

    @property
    def bundle_id(self) -> BundleId:
        # Return the completed slot latency model bundle id result without a hidden
        # fallback.
        return self.bundle_identity

    @property
    def config_digest(self) -> ContentDigest:
        # Execute the slot latency model config digest workflow in explicit, reviewable
        # steps.
        return domain_digest(
            "backtest.component-config.v1",
            {
                "observation_slots": self.observation_slots,
                "order_slots": self.order_slots,
                # Close the v1 and observation slots payload only after all slot latency model
                # config digest fields are present.
            },
        )


# Keep the reference run config contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ReferenceRunConfig:
    execution_mode: ExecutionMode
    latency: SlotLatencyModel
    root_seed: int
    # Declare initial available explicitly in the reference run config contract.
    initial_available: Mapping[AssetId, int]
    maximum_dynamic_items: int = 1_000_000
    engine_bundle_id: BundleId = ENGINE_BUNDLE_ID

    def __post_init__(self) -> None:
        # Execute the reference run config post init workflow in explicit, reviewable
        # steps.
        KeyedRng(self.root_seed)
        if not isinstance(self.execution_mode, ExecutionMode) or self.execution_mode not in {
            ExecutionMode.EXOGENOUS_REPLAY,
            ExecutionMode.SHADOW_STATE_REPLAY,
        }:
            raise ValueError("reference FirstSwap engine execution mode is unsupported")
        if self.maximum_dynamic_items <= 0:
            raise ValueError("maximum_dynamic_items must be positive")


# Keep the run summary contract and validation rules together.
@dataclass(frozen=True, slots=True)
class RunSummary:
    dataset_logical_content_hash: LogicalContentHash
    replay_semantics_id: ContentDigest
    engine_bundle_id: ContentDigest
    # Declare latency bundle id explicitly in the run summary contract.
    latency_bundle_id: ContentDigest
    historical_group_count: int
    historical_event_count: int
    delivered_event_count: int
    accepted_order_count: int
    # Declare rejected order count explicitly in the run summary contract.
    rejected_order_count: int
    filled_order_count: int
    failed_order_count: int
    ledger_transaction_count: int
    fill_count: int
    # Declare audit hash explicitly in the run summary contract.
    audit_hash: ContentDigest
    ledger_hash: ContentDigest
    fill_hash: ContentDigest
    result_hash: ContentDigest
    final_balances: tuple[tuple[str, str, str, int], ...]


# Keep the null run event sink contract and validation rules together.
class NullRunEventSink:
    """No-op sink useful when only canonical hashes and summary are required."""

    def append_audit(self, record: dict[str, object]) -> None:
        del record

    def append_ledger(self, transaction: LedgerTransaction) -> None:
        del transaction

    def append_fill(self, fill: Fill) -> None:
        # Discard fill after its boundary-only use.
        del fill

    def append_canonical_audit(
        self,
        record_json: bytes,
        *,
        # Keep the boundary ordinal input explicit in the append canonical audit contract.
        boundary_ordinal: int,
        phase: int,
        record_type: str,
    ) -> None:
        del record_json, boundary_ordinal, phase, record_type


# Keep the observation contract and validation rules together.
@dataclass(frozen=True, slots=True)
class _Observation:
    event: CanonicalEvent
    event_row_id: int


@dataclass(frozen=True, slots=True)
# Keep the executable order contract and validation rules together.
class _ExecutableOrder:
    intent: SwapExactInIntent


# Keep the recorder contract and validation rules together.
class _Recorder:
    def __init__(self, sink: RunEventSink) -> None:
        # Execute the recorder init workflow in explicit, reviewable steps.
        self.sink = sink
        self.audit = CanonicalStreamHasher("backtest.canonical-audit-stream.v1")
        self.ledger = CanonicalStreamHasher("backtest.canonical-ledger-stream.v2")
        self.fills = CanonicalStreamHasher("backtest.canonical-fill-stream.v1")

    def append_audit(self, record: dict[str, object]) -> None:
        # Execute the recorder append audit workflow in explicit, reviewable steps.
        self.audit.append(record)
        self.sink.append_audit(record)

    def append_ledger(self, transaction: LedgerTransaction) -> None:
        # Execute the recorder append ledger workflow in explicit, reviewable steps.
        self.ledger.append(ledger_document(transaction))
        self.sink.append_ledger(transaction)

    def append_fill(self, fill: Fill) -> None:
        # Execute the recorder append fill workflow in explicit, reviewable steps.
        self.fills.append(fill_document(fill))
        self.sink.append_fill(fill)


# Keep the boundary timeline contract and validation rules together.
class _BoundaryTimeline:
    def __init__(self, boundaries: tuple[ReplayBoundary, ...]) -> None:
        # Execute the boundary timeline init workflow in explicit, reviewable steps.
        if not boundaries:
            raise EngineInvariantError("replay boundary index must not be empty")
        if any(
            left.boundary_ordinal >= right.boundary_ordinal for left, right in pairwise(boundaries)
        ):
            # Fail the boundary timeline init path with EngineInvariantError for replay
            # boundaries must have strictly increasing ordinals when boundary ordinal,
            # left and right is true; do not continue ambiguously.
            raise EngineInvariantError("replay boundaries must have strictly increasing ordinals")
        chain_identity = (boundaries[0].network_id, boundaries[0].position_schema_id)
        if any((item.network_id, item.position_schema_id) != chain_identity for item in boundaries):
            # Handle the boundary timeline init chain identity, item and boundaries
            # condition as a distinct block.
            raise EngineInvariantError(
                "replay boundaries mix network or position schema identities"
            )
        if any(left.block_ordinal > right.block_ordinal for left, right in pairwise(boundaries)):
            raise EngineInvariantError("replay boundary blocks must be monotone")
        # Assemble self boundaries once so the boundary timeline init workflow shares one
        # value.
        self.boundaries = boundaries
        self.ordinals = tuple(item.boundary_ordinal for item in boundaries)
        self.blocks = tuple(item.block_ordinal for item in boundaries)
        self.index_by_ordinal = {
            item.boundary_ordinal: index
            # Keep the boundaries enumerate step visible while building self.index by
            # ordinal.
            for index, item in enumerate(boundaries)
            # Complete the self index by ordinal group only after its semantic components are
            # visible.
        }

    def observation_release(self, source_boundary: int, delay_slots: int) -> int | None:
        # Execute the boundary timeline observation release workflow in explicit,
        # reviewable steps.
        source_index = self._index(source_boundary)
        target_slot = self.blocks[source_index] + delay_slots
        candidate = max(source_index, bisect_left(self.blocks, target_slot))
        return None if candidate >= len(self.boundaries) else self.ordinals[candidate]

    def order_release(self, decision_boundary: int, delay_slots: int) -> int | None:
        # Execute the boundary timeline order release workflow in explicit, reviewable
        # steps.
        current_index = self._index(decision_boundary)
        target_slot = self.blocks[current_index] + delay_slots
        candidate = max(current_index + 1, bisect_left(self.blocks, target_slot))
        return None if candidate >= len(self.boundaries) else self.ordinals[candidate]

    def instant(self, boundary: int) -> SchedulerInstant:
        # Execute the boundary timeline instant workflow in explicit, reviewable steps.
        index = self._index(boundary)
        return SchedulerInstant(boundary, self.boundaries[index].chain_position)

    def require(self, boundary: int) -> None:
        self._index(boundary)

    def require_event(self, event: CanonicalEvent) -> None:
        # Execute the boundary timeline require event workflow in explicit, reviewable
        # steps.
        index = self._index(event.envelope.boundary_ordinal)
        boundary = self.boundaries[index]
        position = event.envelope.position
        if (
            position.network_id != boundary.network_id
            # Keep position visible while evaluating the network id, position schema id
            # and block ordinal guard.
            or position.position_schema_id != boundary.position_schema_id
            or position.block_ordinal != boundary.block_ordinal
            or position.transaction_index != boundary.transaction_index
        ):
            # Handle the boundary timeline require event network id, position schema id
            # and block ordinal condition as a distinct block.
            raise EngineInvariantError(
                "historical event differs from replay network, schema or boundary position"
            )

    def _index(self, boundary: int) -> int:
        # Execute the boundary timeline index workflow in explicit, reviewable steps.
        try:
            return self.index_by_ordinal[boundary]
        except KeyError as error:
            raise EngineInvariantError("item references a non-existent replay boundary") from error


class _MaterializedObservationMerge:
    """Sequentially merge verified delivery rows with already-seen historical rows."""

    def __init__(
        self,
        source: ObservationDeliverySource,
        events: IndexedHistoricalEventSource,
        timeline: _BoundaryTimeline,
        # Keep the observation slots input explicit in the init contract.
        observation_slots: int,
    ) -> None:
        # Execute the materialized observation merge init workflow in explicit, reviewable
        # steps.
        counts = (
            source.input_event_count,
            source.delivery_count,
            source.outside_horizon_count,
        )
        # Evaluate the complete materialized observation merge init value, counts and
        # isinstance condition before guarded effects.
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts
        ):
            raise EngineInvariantError("materialized delivery counts must be non-negative integers")
        if source.input_event_count <= 0:
            # Fail the materialized observation merge init path with EngineInvariantError
            # for materialized delivery input count must be positive when input event
            # count and source is true; do not continue ambiguously.
            raise EngineInvariantError("materialized delivery input count must be positive")
        if source.delivery_count + source.outside_horizon_count != source.input_event_count:
            raise EngineInvariantError("materialized delivery counts do not cover the replay")
        self._source = source
        self._events = events
        # Assemble self timeline once so the materialized observation merge init workflow
        # shares one value.
        self._timeline = timeline
        self._observation_slots = observation_slots
        self._iterator: Iterator[ObservationDelivery] = source.deliveries()
        self._next: ObservationDelivery | None = None
        self._seen_event_count = 0
        # Assemble self pending count once so the materialized observation merge init
        # workflow shares one value.
        self._pending_count = 0
        self._previous_key: SchedulerKey | None = None
        self._consumed = 0
        self._outside = 0
        self._advance()

    # Apply property semantics to the following materialized observation merge pending
    # count contract.
    @property
    def pending_count(self) -> int:
        return self._pending_count

    def register(
        self,
        # Keep the event row index input explicit in the register contract.
        event_row_index: int,
        expected_release: int | None,
    ) -> None:
        # Execute the materialized observation merge register workflow in explicit,
        # reviewable steps.
        if event_row_index != self._seen_event_count:
            raise EngineInvariantError("historical replay row indexes are not contiguous")
        if event_row_index >= self._source.input_event_count:
            raise EngineInvariantError("historical replay exceeds materialized input count")
        self._seen_event_count += 1
        # Guard this path with expected_release is None before applying effects.
        if expected_release is None:
            # Handle the materialized observation merge register expected_release is None
            # branch as a distinct logical block.
            self._outside += 1
            return
        self._pending_count += 1

    def pop_ready(self, boundary: int) -> tuple[tuple[SchedulerKey, _Observation], ...]:
        # Execute the materialized observation merge pop ready workflow in explicit,
        # reviewable steps.
        ready: list[tuple[SchedulerKey, _Observation]] = []
        while self._next is not None and self._next.release_boundary_ordinal <= boundary:
            # Keep the next, release boundary ordinal and boundary loop body bounded
            # within materialized observation merge pop ready.
            delivery = self._next
            if delivery.release_boundary_ordinal != boundary:
                raise EngineInvariantError("materialized delivery was not released on its boundary")
            self._timeline.require(delivery.release_boundary_ordinal)
            if delivery.event_row_index >= self._seen_event_count:
                # Handle the materialized observation merge pop ready event row index,
                # seen event count and delivery condition as a distinct block.
                raise EngineInvariantError(
                    "materialized delivery references an unseen historical event row"
                )
            event = self._events.event_at(delivery.event_row_index)
            expected_release = self._timeline.observation_release(
                # Pass event explicitly so observation_release receives a reviewable
                # boundary ordinal and envelope input in materialized observation merge
                # pop ready.
                event.envelope.boundary_ordinal,
                self._observation_slots,
            )
            if expected_release is None:
                # Handle the materialized observation merge pop ready expected_release is
                # None branch as a distinct logical block.
                raise EngineInvariantError(
                    "materialized delivery references an outside-horizon event row"
                )
            if delivery.release_boundary_ordinal != expected_release:
                raise EngineInvariantError("materialized delivery differs from resolved latency")
            # Assemble key once so the materialized observation merge pop ready workflow
            # shares one value.
            key = SchedulerKey(
                delivery.release_boundary_ordinal,
                SchedulerPhase.OBSERVATION_DELIVERY,
                event.envelope.boundary_ordinal,
                event.envelope.stable_causal_id.hex,
                # Complete SchedulerKey only after its release boundary ordinal and
                # observation delivery inputs are visible in materialized observation merge
                # pop ready.
            )
            if self._previous_key is not None and key <= self._previous_key:
                raise EngineInvariantError("materialized deliveries violate scheduler ordering")
            self._previous_key = key
            ready.append((key, _Observation(event, delivery.event_row_index)))
            # Assemble self pending count once so the materialized observation merge pop
            # ready workflow shares one value.
            self._pending_count -= 1
            if self._pending_count < 0:
                raise EngineInvariantError("materialized delivery duplicates an event row")
            self._consumed += 1
            self._advance()
        # Return the completed materialized observation merge pop ready result without a
        # hidden fallback.
        return tuple(ready)

    def finish(self, historical_event_count: int) -> None:
        # Execute the materialized observation merge finish workflow in explicit,
        # reviewable steps.
        if historical_event_count != self._source.input_event_count:
            raise EngineInvariantError("materialized delivery input count differs from replay")
        if self._next is not None:
            raise EngineInvariantError("materialized delivery remains beyond the replay horizon")
        if self._consumed != self._source.delivery_count:
            # Fail the materialized observation merge finish path with
            # EngineInvariantError for materialized delivery stream ended at the wrong
            # count when consumed, delivery count and source is true; do not continue
            # ambiguously.
            raise EngineInvariantError("materialized delivery stream ended at the wrong count")
        if self._outside != self._source.outside_horizon_count:
            raise EngineInvariantError("materialized outside-horizon count differs from replay")
        if self._pending_count:
            raise EngineInvariantError("materialized delivery stream omitted replay event rows")

    # Define materialized observation merge advance as one focused operation with an
    # explicit boundary.
    def _advance(self) -> None:
        # Execute the materialized observation merge advance workflow in explicit,
        # reviewable steps.
        try:
            delivery = next(self._iterator)
        except StopIteration:
            # Translate the StopIteration failure through the materialized observation
            # merge advance boundary.
            self._next = None
            return
        if self._consumed >= self._source.delivery_count:
            raise EngineInvariantError("materialized delivery stream exceeds declared count")
        if delivery.event_row_index >= self._source.input_event_count:
            # Fail the materialized observation merge advance path with
            # EngineInvariantError for materialized delivery event row is out of bounds
            # when event row index, input event count and delivery is true; do not
            # continue ambiguously.
            raise EngineInvariantError("materialized delivery event row is out of bounds")
        self._next = delivery


class ReferenceBacktestEngine:
    """One sequential reducer with explicit causal phases and bounded queues."""

    def run(
        self,
        *,
        source: HistoricalEventSource,
        strategy: StrategyInstance,
        # Keep the execution model input explicit in the run contract.
        execution_model: VenueExecutionModel,
        risk_policy: RiskPolicy,
        config: ReferenceRunConfig,
        sink: RunEventSink | None = None,
        features: CausalScalarProvider | None = None,
        # Keep the predictions input explicit in the run contract.
        predictions: CausalScalarProvider | None = None,
        delivery_schedule: ObservationDeliverySource | None = None,
        physical_settings: EnginePhysicalSettings = DEFAULT_ENGINE_PHYSICAL_SETTINGS,
    ) -> RunSummary:
        # Execute the reference backtest engine run workflow in explicit, reviewable
        # steps.
        del physical_settings
        timeline = _BoundaryTimeline(source.boundaries())
        recorder = _Recorder(NullRunEventSink() if sink is None else sink)
        historical = HistoricalReferenceState()
        observed = ObservedState()
        # Assemble venue once so the reference backtest engine run workflow shares one
        # value.
        venue = SimulationVenueState(config.execution_mode)
        portfolio = PortfolioState(config.initial_available)
        portfolio_view = PortfolioView(portfolio)
        observed_view = ObservedMarketView(observed)
        rng = KeyedRng(config.root_seed)
        # Assemble feature provider once so the reference backtest engine run workflow
        # shares one value.
        feature_provider = EmptyCausalScalarProvider() if features is None else features
        prediction_provider = EmptyCausalScalarProvider() if predictions is None else predictions
        observations: CausalScheduler[_Observation] = CausalScheduler()
        materialized_observations: _MaterializedObservationMerge | None = None
        if delivery_schedule is not None:
            # Handle the reference backtest engine run delivery_schedule is not None
            # branch as a distinct logical block.
            if not isinstance(source, IndexedHistoricalEventSource):
                # Handle the reference backtest engine run isinstance, source and indexed
                # historical event source condition as a distinct block.
                raise EngineInvariantError(
                    "materialized deliveries require a stable row-indexed ReplayPack"
                )
            materialized_observations = _MaterializedObservationMerge(
                delivery_schedule,
                # Pass source explicitly so _MaterializedObservationMerge receives a
                # reviewable observation slots and latency input in reference backtest
                # engine run.
                source,
                timeline,
                config.latency.observation_slots,
            )
        executable_orders: CausalScheduler[_ExecutableOrder] = CausalScheduler()
        # Assemble seen orders once so the reference backtest engine run workflow shares
        # one value.
        seen_orders: set[OrderId] = set()
        terminal_orders: set[OrderId] = set()

        group_count = 0
        event_count = 0
        delivered_count = 0
        # Assemble accepted count once so the reference backtest engine run workflow
        # shares one value.
        accepted_count = 0
        rejected_count = 0
        filled_order_count = 0
        failed_order_count = 0

        previous_sort_key: tuple[str, str, int, str, int, str] | None = None
        # Assemble previous group boundary once so the reference backtest engine run
        # workflow shares one value.
        previous_group_boundary: int | None = None
        event_row_index = 0
        grouped = groupby(
            source.events(),
            key=lambda event: (
                # Pass event explicitly so groupby receives a reviewable events and
                # boundary ordinal input in reference backtest engine run.
                event.envelope.boundary_ordinal,
                event.envelope.transaction_group_id.hex,
            ),
        )
        for (boundary, group_id), group_iterator in grouped:
            # Process grouped inside the bounded reference backtest engine run loop.
            events = tuple(group_iterator)
            if not events:  # pragma: no cover - groupby never yields empty groups
                raise EngineInvariantError("replay emitted an empty historical group")
            for event in events:
                # Process events inside the bounded reference backtest engine run loop.
                sort_key = canonical_event_sort_key(event)
                if previous_sort_key is not None and sort_key <= previous_sort_key:
                    # Handle the reference backtest engine run previous sort key and sort
                    # key condition as a distinct block.
                    raise EngineInvariantError(
                        "historical events are not in strict canonical order"
                    )
                previous_sort_key = sort_key
            if previous_group_boundary == boundary:
                # Fail the reference backtest engine run path with EngineInvariantError
                # for one boundary contains more than one transaction group when previous
                # group boundary and boundary is true; do not continue ambiguously.
                raise EngineInvariantError("one boundary contains more than one transaction group")
            previous_group_boundary = boundary
            timeline.require(boundary)
            for event in events:
                timeline.require_event(event)

            # Invoke apply_group for events as a visible reference backtest engine run
            # step.
            historical.apply_group(events)
            group_count += 1
            event_count += len(events)
            recorder.append_audit(
                {
                    # Keep boundary ordinal named so the historical group applied and
                    # boundary ordinal payload passed to append_audit remains self-
                    # describing within reference backtest engine run.
                    "boundary_ordinal": boundary,
                    "event_ids": [event.envelope.canonical_event_id.hex for event in events],
                    "group_id": group_id,
                    "phase": int(SchedulerPhase.HISTORICAL_REFERENCE_APPLY),
                    "record_type": "HISTORICAL_GROUP_APPLIED",
                    # Close the historical group applied and boundary ordinal payload only
                    # after all reference backtest engine run fields are present.
                }
            )

            venue.reconcile_group(events, historical)
            recorder.append_audit(
                {
                    # Keep boundary ordinal named so the simulation reconciled and
                    # boundary ordinal payload passed to append_audit remains self-
                    # describing within reference backtest engine run.
                    "boundary_ordinal": boundary,
                    "execution_mode": config.execution_mode.value,
                    "group_id": group_id,
                    "phase": int(SchedulerPhase.SIMULATION_STATE_RECONCILE),
                    "record_type": "SIMULATION_RECONCILED",
                    # Close the simulation reconciled and boundary ordinal payload only after
                    # all reference backtest engine run fields are present.
                }
            )

            for event in events:
                # Process events inside the bounded reference backtest engine run loop.
                release = timeline.observation_release(
                    event.envelope.boundary_ordinal,
                    config.latency.observation_slots,
                )
                if release is None:
                    # Handle the reference backtest engine run release is None branch as a
                    # distinct logical block.
                    recorder.append_audit(
                        {
                            "boundary_ordinal": boundary,
                            "event_id": event.envelope.canonical_event_id.hex,
                            "phase": int(SchedulerPhase.OBSERVATION_DELIVERY),
                            # Keep record type named so the observation outside horizon
                            # and boundary ordinal payload passed to append_audit remains
                            # self-describing within reference backtest engine run.
                            "record_type": "OBSERVATION_OUTSIDE_HORIZON",
                        }
                    )
                    if materialized_observations is not None:
                        materialized_observations.register(event_row_index, None)
                    # Assemble event row index once so the reference backtest engine run
                    # workflow shares one value.
                    event_row_index += 1
                    continue
                if materialized_observations is None:
                    # Handle the reference backtest engine run materialized_observations
                    # is None branch as a distinct logical block.
                    observations.enqueue(
                        SchedulerKey(
                            release,
                            SchedulerPhase.OBSERVATION_DELIVERY,
                            event.envelope.boundary_ordinal,
                            # Pass event explicitly so SchedulerKey receives a reviewable
                            # observation delivery and boundary ordinal input in reference
                            # backtest engine run.
                            event.envelope.stable_causal_id.hex,
                        ),
                        _Observation(event, event_row_index),
                    )
                else:
                    # Invoke register for event row index and release as a visible
                    # reference backtest engine run step.
                    materialized_observations.register(event_row_index, release)
                event_row_index += 1
            observation_count = (
                len(observations)
                if materialized_observations is None
                # Route all remaining cases through the explicit alternative branch.
                else materialized_observations.pending_count
            )
            _check_queue_budget(
                observation_count,
                executable_orders,
                # Pass config explicitly so _check_queue_budget receives a reviewable
                # maximum dynamic items and observation count input in reference backtest
                # engine run.
                config.maximum_dynamic_items,
            )

            ready_observations = (
                observations.pop_ready(
                    boundary,
                    # Pass through phase explicitly so pop_ready receives a reviewable
                    # observation delivery and boundary input in reference backtest engine
                    # run.
                    through_phase=SchedulerPhase.OBSERVATION_DELIVERY,
                )
                if materialized_observations is None
                else materialized_observations.pop_ready(boundary)
            )
            # Assemble delivered once so the reference backtest engine run workflow shares
            # one value.
            delivered: list[_Observation] = []
            for key, item in ready_observations:
                # Process ready_observations inside the bounded reference backtest engine
                # run loop.
                observed.apply(item.event)
                delivered.append(item)
                delivered_count += 1
                recorder.append_audit(
                    {
                        # Keep boundary ordinal named so the observation delivered and
                        # boundary ordinal payload passed to append_audit remains self-
                        # describing within reference backtest engine run.
                        "boundary_ordinal": boundary,
                        "event_id": item.event.envelope.canonical_event_id.hex,
                        "phase": int(SchedulerPhase.OBSERVATION_DELIVERY),
                        "record_type": "OBSERVATION_DELIVERED",
                        "source_boundary_ordinal": key.source_or_creator_boundary_ordinal,
                        # Close the observation delivered and boundary ordinal payload only
                        # after all reference backtest engine run fields are present.
                    }
                )

            instant = timeline.instant(boundary)
            notification_context = StrategyContext(
                instant,
                # Pass observed view explicitly so StrategyContext receives a reviewable
                # causal scalar view and instant input in reference backtest engine run.
                observed_view,
                portfolio_view,
                rng,
                CausalScalarView(feature_provider, boundary),
                CausalScalarView(prediction_provider, boundary),
                # Complete StrategyContext only after its causal scalar view and instant
                # inputs are visible in reference backtest engine run.
            )
            proposed: list[SwapExactInIntent] = []
            for observation in delivered:
                # Process delivered inside the bounded reference backtest engine run loop.
                context = StrategyContext(
                    instant,
                    observed_view,
                    portfolio_view,
                    rng,
                    # Keep the feature provider CausalScalarView step visible while
                    # building context.
                    CausalScalarView(
                        feature_provider,
                        boundary,
                        bound_entity_id=observation.event_row_id,
                    ),
                    # Keep the prediction provider CausalScalarView step visible while
                    # building context.
                    CausalScalarView(
                        prediction_provider,
                        boundary,
                        bound_entity_id=observation.event_row_id,
                    ),
                    # Pass observation explicitly so StrategyContext receives a reviewable
                    # event row id and causal scalar view input in reference backtest
                    # engine run.
                    observation.event_row_id,
                )
                intents = tuple(strategy.on_event(observation.event, context))
                for intent in intents:
                    # Process intents inside the bounded reference backtest engine run
                    # loop.
                    if not isinstance(intent, SwapExactInIntent):
                        raise EngineInvariantError("strategy emitted an unsupported intent type")
                    if intent.created_boundary_ordinal != boundary:
                        # Handle the reference backtest engine run created boundary
                        # ordinal, boundary and intent condition as a distinct block.
                        raise EngineInvariantError(
                            "strategy intent has a non-current decision boundary"
                        )
                    if intent.order_id in seen_orders:
                        raise EngineInvariantError("strategy emitted a duplicate order ID")
                    # Invoke add for order id and intent as a visible reference backtest
                    # engine run step.
                    seen_orders.add(intent.order_id)
                    proposed.append(intent)
                    recorder.append_audit(
                        {
                            "boundary_ordinal": boundary,
                            # Keep order id named so the intent proposed and boundary
                            # ordinal payload passed to append_audit remains self-
                            # describing within reference backtest engine run.
                            "order_id": intent.order_id.hex,
                            "phase": int(SchedulerPhase.STRATEGY_CALLBACK),
                            "record_type": "INTENT_PROPOSED",
                        }
                    )
            # Invoke sort for hex and order id as a visible reference backtest engine run
            # step.
            proposed.sort(key=lambda intent: intent.order_id.hex)

            notifications: list[ExecutionNotification] = []
            for intent in proposed:
                # Process proposed inside the bounded reference backtest engine run loop.
                release = timeline.order_release(boundary, config.latency.order_slots)
                if release is None or not risk_policy.accept(intent, portfolio_view):
                    # Handle the reference backtest engine run release, accept and intent
                    # condition as a distinct block.
                    rejected_count += 1
                    terminal_orders.add(intent.order_id)
                    reason = "HORIZON_EXHAUSTED" if release is None else "RISK_REJECTED"
                    recorder.append_audit(
                        {
                            # Keep boundary ordinal named so the reason and order rejected
                            # payload passed to append_audit remains self-describing
                            # within reference backtest engine run.
                            "boundary_ordinal": boundary,
                            "order_id": intent.order_id.hex,
                            "phase": int(SchedulerPhase.RISK_AND_ORDER_ACCEPTANCE),
                            "reason": reason,
                            "record_type": "ORDER_REJECTED",
                            # Close the reason and order rejected payload only after all
                            # reference backtest engine run fields are present.
                        }
                    )
                    notifications.append(
                        ExecutionNotification(
                            intent.order_id,
                            # Pass order status explicitly so ExecutionNotification
                            # receives a reviewable order id and rejected input in
                            # reference backtest engine run.
                            OrderStatus.REJECTED,
                            boundary,
                            reports=(reason,),
                        )
                    )
                    # Keep the continue step explicit within the reference backtest engine
                    # run workflow.
                    continue
                reservation = _reservation_transaction(intent, boundary)
                portfolio.apply(reservation)
                recorder.append_ledger(reservation)
                accepted_count += 1
                # Invoke append_audit for order accepted and reserved and boundary ordinal
                # as a visible reference backtest engine run step.
                recorder.append_audit(
                    {
                        "boundary_ordinal": boundary,
                        "eligible_boundary_ordinal": release,
                        "order_id": intent.order_id.hex,
                        # Pass phase explicitly to append_audit for order accepted and
                        # reserved and boundary ordinal.
                        "phase": int(SchedulerPhase.RISK_AND_ORDER_ACCEPTANCE),
                        "record_type": "ORDER_ACCEPTED_AND_RESERVED",
                    }
                )
                executable_orders.enqueue(
                    # Pass scheduler key explicitly to enqueue for venue execution and
                    # ledger commit and hex.
                    SchedulerKey(
                        release,
                        SchedulerPhase.VENUE_EXECUTION_AND_LEDGER_COMMIT,
                        boundary,
                        _order_causal_digest(intent.order_id).hex,
                        # Complete SchedulerKey only after its venue execution and ledger
                        # commit and hex inputs are visible in reference backtest engine run.
                    ),
                    _ExecutableOrder(intent),
                )
                notifications.append(
                    ExecutionNotification(intent.order_id, OrderStatus.ACCEPTED, boundary)
                    # Complete append only after its order id and accepted inputs are visible
                    # in reference backtest engine run.
                )
            observation_count = (
                len(observations)
                if materialized_observations is None
                else materialized_observations.pending_count
                # Complete the observation count group only after its semantic components are
                # visible.
            )
            _check_queue_budget(
                observation_count,
                executable_orders,
                config.maximum_dynamic_items,
                # Complete _check_queue_budget only after its maximum dynamic items and
                # observation count inputs are visible in reference backtest engine run.
            )

            ready_orders = executable_orders.pop_ready(
                boundary,
                through_phase=SchedulerPhase.VENUE_EXECUTION_AND_LEDGER_COMMIT,
            )
            # Traverse ready_orders explicitly so each reference backtest engine run
            # iteration remains traceable.
            for _, order_item in ready_orders:
                # Process ready_orders inside the bounded reference backtest engine run
                # loop.
                intent = order_item.intent
                if intent.order_id in terminal_orders:
                    raise EngineInvariantError("terminal order was scheduled for execution twice")
                try:
                    # Perform the protected reference backtest engine run operation before
                    # explicit failure handling.
                    plan = execution_model.execute(
                        intent,
                        venue,
                        boundary_ordinal=boundary,
                        mode=config.execution_mode,
                        # Complete execute only after its execution mode and intent inputs are
                        # visible in reference backtest engine run.
                    )
                except ExecutionRejected as error:
                    # Translate the ExecutionRejected failure through the reference
                    # backtest engine run boundary.
                    release_transaction = _release_transaction(intent, boundary, error.code)
                    portfolio.apply(release_transaction)
                    recorder.append_ledger(release_transaction)
                    terminal_orders.add(intent.order_id)
                    failed_order_count += 1
                    # Invoke append_audit for code and order execution failed and released
                    # as a visible reference backtest engine run step.
                    recorder.append_audit(
                        {
                            "boundary_ordinal": boundary,
                            "order_id": intent.order_id.hex,
                            "phase": int(SchedulerPhase.VENUE_EXECUTION_AND_LEDGER_COMMIT),
                            # Keep reason named so the code and order execution failed and
                            # released payload passed to append_audit remains self-
                            # describing within reference backtest engine run.
                            "reason": error.code,
                            "record_type": "ORDER_EXECUTION_FAILED_AND_RELEASED",
                        }
                    )
                    notifications.append(
                        # Pass execution notification explicitly to append for order id
                        # and execution failed.
                        ExecutionNotification(
                            intent.order_id,
                            OrderStatus.EXECUTION_FAILED,
                            boundary,
                            reports=(error.code,),
                            # Complete ExecutionNotification only after its order id and
                            # execution failed inputs are visible in reference backtest engine
                            # run.
                        )
                    )
                    continue

                _validate_execution_plan(intent, plan, boundary, config.execution_mode)
                settlement = _settlement_transaction(intent, plan.ledger_postings, boundary)
                # Assemble portfolio candidate once so the reference backtest engine run
                # workflow shares one value.
                portfolio_candidate = portfolio.preview(settlement)
                venue_candidate = (
                    None if plan.transition is None else venue.preview_transition(plan.transition)
                )
                portfolio.commit(portfolio_candidate)
                # Guard this path with venue_candidate is not None before applying
                # effects.
                if venue_candidate is not None:
                    venue.commit(venue_candidate)
                recorder.append_ledger(settlement)
                for fill in sorted(plan.fills, key=lambda value: value.order_id.hex):
                    recorder.append_fill(fill)
                # Invoke add for order id and intent as a visible reference backtest
                # engine run step.
                terminal_orders.add(intent.order_id)
                filled_order_count += 1
                recorder.append_audit(
                    {
                        "boundary_ordinal": boundary,
                        # Pass fill count explicitly to append_audit for order filled
                        # atomically and boundary ordinal.
                        "fill_count": len(plan.fills),
                        "order_id": intent.order_id.hex,
                        "phase": int(SchedulerPhase.VENUE_EXECUTION_AND_LEDGER_COMMIT),
                        "record_type": "ORDER_FILLED_ATOMICALLY",
                    }
                    # Complete append_audit only after its order filled atomically and
                    # boundary ordinal inputs are visible in reference backtest engine run.
                )
                notifications.append(
                    ExecutionNotification(
                        intent.order_id,
                        OrderStatus.FILLED,
                        # Pass boundary explicitly so ExecutionNotification receives a
                        # reviewable order id and filled input in reference backtest
                        # engine run.
                        boundary,
                        fills=plan.fills,
                        reports=plan.reports,
                    )
                )

            # Invoke sort for hex and value as a visible reference backtest engine run
            # step.
            notifications.sort(key=lambda item: (item.order_id.hex, item.status.value))
            for notification in notifications:
                # Process notifications inside the bounded reference backtest engine run
                # loop.
                strategy.on_execution(notification, notification_context)
                recorder.append_audit(
                    {
                        "boundary_ordinal": boundary,
                        "order_id": notification.order_id.hex,
                        # Pass phase explicitly to append_audit for strategy notified and
                        # value.
                        "phase": int(SchedulerPhase.STRATEGY_EXECUTION_NOTIFICATION),
                        "record_type": "STRATEGY_NOTIFIED",
                        "status": notification.status.value,
                    }
                )

            # Invoke append_audit for boundary checkpoint and boundary ordinal as a
            # visible reference backtest engine run step.
            recorder.append_audit(
                {
                    "boundary_ordinal": boundary,
                    "phase": int(SchedulerPhase.CHECKPOINT),
                    "record_type": "BOUNDARY_CHECKPOINT",
                    # Close the boundary checkpoint and boundary ordinal payload only after
                    # all reference backtest engine run fields are present.
                }
            )

        if event_count == 0:
            raise EngineInvariantError("replay source emitted no canonical events")
        if materialized_observations is not None:
            # Invoke finish for event count as a visible reference backtest engine run
            # step.
            materialized_observations.finish(event_count)
        if len(observations) or len(executable_orders):
            raise EngineInvariantError("replay ended with supposedly reachable dynamic items")
        final_balances = portfolio.semantic_balances()
        result_document: dict[str, object] = {
            # Keep the accepted order count component named inside the result document
            # contract.
            "accepted_order_count": accepted_count,
            "failed_order_count": failed_order_count,
            "fill_count": recorder.fills.count,
            "fill_hash": recorder.fills.digest.hex,
            "filled_order_count": filled_order_count,
            # Register row through list so the result document table remains scannable.
            "final_balances": [list(row) for row in final_balances],
            "ledger_hash": recorder.ledger.digest.hex,
            "ledger_transaction_count": recorder.ledger.count,
            "rejected_order_count": rejected_count,
        }
        # Return the completed reference backtest engine run result without a hidden
        # fallback.
        return RunSummary(
            dataset_logical_content_hash=source.logical_content_hash,
            replay_semantics_id=source.replay_semantics_id,
            engine_bundle_id=config.engine_bundle_id,
            latency_bundle_id=config.latency.bundle_id,
            # Pass historical group count explicitly so RunSummary receives a reviewable
            # v1 and logical content hash input in reference backtest engine run.
            historical_group_count=group_count,
            historical_event_count=event_count,
            delivered_event_count=delivered_count,
            accepted_order_count=accepted_count,
            rejected_order_count=rejected_count,
            # Pass filled order count explicitly so RunSummary receives a reviewable v1
            # and logical content hash input in reference backtest engine run.
            filled_order_count=filled_order_count,
            failed_order_count=failed_order_count,
            ledger_transaction_count=recorder.ledger.count,
            fill_count=recorder.fills.count,
            audit_hash=recorder.audit.digest,
            # Pass ledger hash explicitly so RunSummary receives a reviewable v1 and
            # logical content hash input in reference backtest engine run.
            ledger_hash=recorder.ledger.digest,
            fill_hash=recorder.fills.digest,
            result_hash=domain_digest("backtest.canonical-run-result.v1", result_document),
            final_balances=final_balances,
        )


# Define check queue budget as one focused operation with an explicit boundary.
def _check_queue_budget(
    observation_count: int,
    executable_orders: CausalScheduler[_ExecutableOrder],
    maximum: int,
) -> None:
    # Execute the check queue budget workflow in explicit, reviewable steps.
    if observation_count + len(executable_orders) > maximum:
        raise EngineInvariantError("dynamic scheduler item budget exceeded")


def _order_causal_digest(order_id: OrderId) -> ContentDigest:
    return ContentDigest(order_id.hex)


def _reservation_transaction(
    # Keep the intent input explicit in the reservation transaction contract.
    intent: SwapExactInIntent,
    boundary: int,
) -> LedgerTransaction:
    # Execute the reservation transaction workflow in explicit, reviewable steps.
    postings = (
        Posting(
            LedgerAccount(
                available_account_id(intent.sold_asset_id),
                AccountKind.PORTFOLIO_AVAILABLE,
                # Complete LedgerAccount only after its sold asset id and portfolio available
                # inputs are visible in reservation transaction.
            ),
            intent.sold_asset_id,
            -intent.amount_in_atomic,
        ),
        Posting(
            # Register ledger account and portfolio reserved through LedgerAccount so the
            # postings table remains scannable.
            LedgerAccount(
                reserved_account_id(intent.sold_asset_id),
                AccountKind.PORTFOLIO_RESERVED,
            ),
            intent.sold_asset_id,
            # Pass intent explicitly so Posting receives a reviewable portfolio reserved
            # and sold asset id input in reservation transaction.
            intent.amount_in_atomic,
        ),
    )
    digest = domain_digest(
        "backtest.ledger-reservation.v1",
        # Open the v1 and amount atomic payload explicitly for domain_digest within
        # reservation transaction.
        {
            "amount_atomic": intent.amount_in_atomic,
            "asset_id": intent.sold_asset_id.value,
            "boundary_ordinal": boundary,
            "order_id": intent.order_id.hex,
            # Close the v1 and amount atomic payload only after all reservation transaction
            # fields are present.
        },
    )
    return LedgerTransaction(
        transaction_id=digest,
        correlation_kind=LedgerCorrelationKind.ORDER,
        # Include correlation id in the completed reservation transaction result.
        correlation_id=_order_causal_digest(intent.order_id),
        boundary_ordinal=boundary,
        postings=postings,
        reason="ORDER_RESERVATION",
    )


# Define release transaction as one focused operation with an explicit boundary.
def _release_transaction(
    intent: SwapExactInIntent,
    boundary: int,
    reason_code: str,
) -> LedgerTransaction:
    # Execute the release transaction workflow in explicit, reviewable steps.
    postings = (
        Posting(
            LedgerAccount(
                reserved_account_id(intent.sold_asset_id),
                AccountKind.PORTFOLIO_RESERVED,
                # Complete LedgerAccount only after its sold asset id and portfolio reserved
                # inputs are visible in release transaction.
            ),
            intent.sold_asset_id,
            -intent.amount_in_atomic,
        ),
        Posting(
            # Register ledger account and portfolio available through LedgerAccount so the
            # postings table remains scannable.
            LedgerAccount(
                available_account_id(intent.sold_asset_id),
                AccountKind.PORTFOLIO_AVAILABLE,
            ),
            intent.sold_asset_id,
            # Pass intent explicitly so Posting receives a reviewable portfolio available
            # and sold asset id input in release transaction.
            intent.amount_in_atomic,
        ),
    )
    digest = domain_digest(
        "backtest.ledger-release.v1",
        # Open the reason code and v1 payload explicitly for domain_digest within release
        # transaction.
        {
            "amount_atomic": intent.amount_in_atomic,
            "asset_id": intent.sold_asset_id.value,
            "boundary_ordinal": boundary,
            "order_id": intent.order_id.hex,
            # Keep reason named so the reason code and v1 payload passed to domain_digest
            # remains self-describing within release transaction.
            "reason": reason_code,
        },
    )
    return LedgerTransaction(
        transaction_id=digest,
        # Pass correlation kind explicitly so LedgerTransaction receives a reviewable
        # order release and order input in release transaction.
        correlation_kind=LedgerCorrelationKind.ORDER,
        correlation_id=_order_causal_digest(intent.order_id),
        boundary_ordinal=boundary,
        postings=postings,
        reason="ORDER_RELEASE",
        # Complete LedgerTransaction only after its order release and order inputs are visible
        # in release transaction.
    )


def _settlement_transaction(
    intent: SwapExactInIntent,
    postings: Iterable[Posting],
    boundary: int,
    # Keep the ledger transaction input explicit in the settlement transaction contract.
) -> LedgerTransaction:
    # Execute the settlement transaction workflow in explicit, reviewable steps.
    posting_tuple = tuple(postings)
    digest = domain_digest(
        "backtest.ledger-settlement.v1",
        {
            "boundary_ordinal": boundary,
            # Keep order id named so the v1 and boundary ordinal payload passed to
            # domain_digest remains self-describing within settlement transaction.
            "order_id": intent.order_id.hex,
            "postings": posting_documents(posting_tuple),
        },
    )
    return LedgerTransaction(
        # Pass transaction id explicitly so LedgerTransaction receives a reviewable order
        # settlement and order input in settlement transaction.
        transaction_id=digest,
        correlation_kind=LedgerCorrelationKind.ORDER,
        correlation_id=_order_causal_digest(intent.order_id),
        boundary_ordinal=boundary,
        postings=posting_tuple,
        # Pass reason explicitly so LedgerTransaction receives a reviewable order
        # settlement and order input in settlement transaction.
        reason="ORDER_SETTLEMENT",
    )


def _validate_execution_plan(
    intent: SwapExactInIntent,
    plan: object,
    # Keep the boundary input explicit in the validate execution plan contract.
    boundary: int,
    mode: ExecutionMode,
) -> None:
    # Execute the validate execution plan workflow in explicit, reviewable steps.
    if not isinstance(plan, ExecutionPlan):
        raise EngineInvariantError("venue model returned a non-ExecutionPlan value")
    if any(fill.order_id != intent.order_id for fill in plan.fills):
        raise EngineInvariantError("execution plan contains another order ID")
    if any(fill.boundary_ordinal != boundary for fill in plan.fills):
        # Fail the validate execution plan path with EngineInvariantError for execution
        # plan fill has a non-current boundary when boundary ordinal, boundary and fill is
        # true; do not continue ambiguously.
        raise EngineInvariantError("execution plan fill has a non-current boundary")
    if sum(fill.amount_in_atomic for fill in plan.fills) != intent.amount_in_atomic:
        raise EngineInvariantError("execution plan input amount differs from reserved input")
    if mode is ExecutionMode.EXOGENOUS_REPLAY and plan.transition is not None:
        raise EngineInvariantError("exogenous execution must not mutate venue state")
    # Evaluate the complete validate execution plan mode, exogenous replay and transition
    # condition before guarded effects.
    if mode is not ExecutionMode.EXOGENOUS_REPLAY and plan.transition is None:
        raise EngineInvariantError("stateful execution requires a venue transition")


__all__ = [
    "ENGINE_BUNDLE_ID",
    "SLOT_LATENCY_MODEL_BUNDLE_ID",
    # Keep the engine invariant error component named inside the all contract.
    "EngineInvariantError",
    "NullRunEventSink",
    "ReferenceBacktestEngine",
    "ReferenceRunConfig",
    "RunSummary",
    # Keep the slot latency model component named inside the all contract.
    "SlotLatencyModel",
]
