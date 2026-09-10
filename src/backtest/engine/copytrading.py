"""Sequential reference copy replay: historical/delivery merge plus bounded orders."""

import heapq
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

# No source adapter, plugin implementation, storage client or wall clock enters replay.
from backtest.domain.chain import ChainPosition
from backtest.domain.copytrading import CopyBuySignal
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import ContentDigest, VenueId
from backtest.domain.market_events import (
    # Only canonical market variants can affect historical and observed Pump state.
    CanonicalEvent,
    TokenLaunchEvent,
    VenueLifecycleEvent,
    VenueTradeEvent,
)

# Historical input has already been verified by the application artifact reader.
from backtest.domain.time import BlockRange
from backtest.engine.copytrading_contracts import CopyBuyProtocolRuntime, CopyBuyStrategy
from backtest.engine.copytrading_execution import (
    CopyAttemptStatus,
    CopyExecutionPosition,
    # Execution owns money; the scheduler only requests acceptance and delivers landings.
    CopyOrderExecutor,
)
from backtest.engine.copytrading_state import CopyPositionStatus, maximum_settlement_position
from backtest.engine.replay import HistoricalEventSource, IndexedHistoricalEventSource

# Reuse the canonical transaction grouping and authoritative global transaction clock.
from backtest.engine.sniping import _boundary_position, _event_groups
from backtest.engine.transaction_clock import CompactTransactionClock


@dataclass(frozen=True, slots=True)
class CopyReplayLimits:
    """Operational admission caps never change the strategy's semantic behavior."""

    maximum_events: int
    maximum_positions: int
    maximum_dynamic_items: int

    def __post_init__(self) -> None:
        """Reaching a limit aborts rather than silently dropping data or positions."""
        for value in (self.maximum_events, self.maximum_positions, self.maximum_dynamic_items):
            if type(value) is not int or value < 1:
                raise ValueError("copy replay limits must be positive integers")


@dataclass(order=True, slots=True)
class _Action:
    """The normative scheduler key contains no allocation-order or RNG operand."""

    release: int
    phase: int
    creator: int
    causal_id: bytes
    position_id: ContentDigest = field(compare=False)
    # Payload values never participate in the canonical ordering key.
    kind: str = field(compare=False)


@dataclass(frozen=True, slots=True)
class CopyReplayCounts:
    """Bounded engine output; position rows are delivered separately to the sink."""

    historical_events: int
    historical_groups: int
    observed_groups: int
    positions: int
    observed_events: int


# Stream counts remain scalar even when position rows are externally buffered.


def copy_event_groups(
    events: Iterator[CanonicalEvent],
    *,
    clock: CompactTransactionClock,
    # Reject oversized atomic groups instead of subdividing their causality boundary.
    maximum_group_events: int = 10_000,
) -> Iterator[tuple[CanonicalEvent, ...]]:
    """Cap each historical group before the shared atomic grouper allocates its tuple."""
    if type(maximum_group_events) is not int or maximum_group_events < 1:
        raise ValueError("copy transaction group cap must be positive")

    def bounded_events() -> Iterator[CanonicalEvent]:
        """Admission fails without dropping instructions or splitting a transaction."""
        previous: tuple[int, ContentDigest] | None = None
        count = 0
        for event in events:
            identity = (event.envelope.boundary_ordinal, event.envelope.transaction_group_id)
            count = count + 1 if identity == previous else 1
            # The shared grouper separately rejects bad ordering and mixed group identities.
            if count > maximum_group_events:
                raise ValueError("copy transaction group admission limit exceeded")
            previous = identity
            yield event

    # The shared grouper validates total order after the allocation cap is enforced.
    yield from _event_groups(bounded_events(), clock=clock)


# Preflight reads a disposable protocol view, never the live historical state.
def validate_copy_replay(
    source: HistoricalEventSource,
    *,
    clock: CompactTransactionClock,
    decision_range: BlockRange,
    # Policy timing and hard resource bounds are validated against the same compact clock.
    strategy: CopyBuyStrategy,
    protocol: CopyBuyProtocolRuntime,
    limits: CopyReplayLimits,
) -> tuple[int, int]:
    """Prove shape/order/state and the longest settlement before any wallet mutation."""
    if (decision_range.network_id, decision_range.position_schema_id) != (
        clock.network_id,
        clock.position_schema_id,
    ):
        raise ValueError("copy decision range and transaction clock have different identities")
    # Count the verified stream so later rereads cannot silently truncate execution.
    event_count = group_count = 0
    wallets = frozenset(strategy.signing_wallets)
    for group in copy_event_groups(source.events(), clock=clock):
        # A separate disposable reducer validates the complete transaction-atomic stream.
        event_count += len(group)
        group_count += 1
        if event_count > limits.maximum_events:
            raise ValueError("copy source event admission limit exceeded")
        signals = protocol.apply_group(group, effective_at_unix_s=_group_seconds(clock, group))
        # Prove even later duplicate signals; failure must precede strategy consumption.
        for signal in signals:
            if signal.signing_wallet in wallets and decision_range.contains_block(
                signal.position.block_ordinal
            ):
                maximum_settlement_position(clock, signal.position, strategy.policy)
    # An indexed artifact must yield every event declared by its immutable manifest.
    if isinstance(source, IndexedHistoricalEventSource) and event_count != source.event_count:
        raise ValueError("copy canonical source count mismatch")
    return event_count, group_count


class CopyBuyReferenceEngine:
    """Readable oracle with independent sequential historical and delayed readers."""

    def run(
        self,
        *,
        source: HistoricalEventSource,
        decision_range: BlockRange,
        # Strategy decisions and financial execution use separate core-owned interfaces.
        strategy: CopyBuyStrategy,
        executor: CopyOrderExecutor,
        # A third fresh state instance validates input before financial execution starts.
        validation_protocol: CopyBuyProtocolRuntime,
        limits: CopyReplayLimits,
        append_position: Callable[[CopyExecutionPosition], None],
    ) -> CopyReplayCounts:
        """Consume immutable local input and emit bounded position records in signal order."""
        clock = executor.clock
        if validation_protocol is executor.historical or validation_protocol is executor.observed:
            raise ValueError("copy preflight requires a separate fresh protocol reducer")
        # Validate the complete path before initializing mutable positions or order queues.
        expected = validate_copy_replay(
            source,
            clock=clock,
            decision_range=decision_range,
            strategy=strategy,
            # Resource limits reject the run rather than dropping later signals.
            protocol=validation_protocol,
            limits=limits,
        )
        # No heap item is allocated for a historical market event or delayed observation.
        historical = iter(copy_event_groups(source.events(), clock=clock))
        observed = iter(_deliveries(source, clock, strategy.policy.observation_delay_transactions))
        next_history, next_observation = next(historical, None), next(observed, None)
        states: dict[ContentDigest, CopyExecutionPosition] = {}
        by_venue: dict[VenueId, ContentDigest] = {}
        # Only admitted positions, their at-most-four retries and hold timers are dynamic.
        scheduled: list[_Action] = []
        events = groups = delivered = observed_events = 0
        while next_history is not None or next_observation is not None or scheduled:
            boundary = _next_boundary(next_history, next_observation, scheduled)
            position = ChainPosition.from_boundary_ordinal(
                # Reconstruct only the selected boundary, without expanding the global transaction
                # clock.
                network_id=clock.network_id,
                position_schema_id=clock.position_schema_id,
                boundary_ordinal_value=boundary,
            )
            # Phase 10 commits the complete real transaction before any observation/landing.
            if next_history is not None and next_history[0].envelope.boundary_ordinal == boundary:
                executor.historical.apply_group(
                    next_history, effective_at_unix_s=_group_seconds(clock, next_history)
                )
                events, groups = events + len(next_history), groups + 1
                # Historical advancement occurs once after the whole transaction commits.
                next_history = next(historical, None)
            callbacks: list[
                tuple[
                    int,
                    bytes,
                    # Callbacks retain original causal identity rather than depending on allocation
                    # order.
                    tuple[tuple[CanonicalEvent, ...], tuple[CopyBuySignal, ...]] | _Action,
                ]
            ] = []
            # Phase 30 updates only the observed instance after exact global-transaction delay.
            if next_observation is not None and next_observation[0] == boundary:
                _, group = next_observation
                signals = executor.observed.apply_group(
                    group, effective_at_unix_s=_group_seconds(clock, group)
                )
                # Delivery emits one callback only after all instructions update observed state.
                callbacks.append(
                    (
                        group[0].envelope.boundary_ordinal,
                        bytes.fromhex(group[0].envelope.transaction_group_id.hex),
                        (group, signals),
                        # The callback carries the complete group and its original actor-bearing
                        # signals.
                    )
                )
                delivered += 1
                observed_events += len(group)
                # Fixed transaction delay preserves group order, so this is a sequential merge.
                next_observation = next(observed, None)
            while scheduled and scheduled[0].release == boundary and scheduled[0].phase == 40:
                action = heapq.heappop(scheduled)
                callbacks.append((action.creator, action.causal_id, action))
            # Phase 40 callbacks use the same creator/causal ordering as dynamic timers.
            requests: dict[ContentDigest, tuple[CopyExecutionPosition, bool]] = {}
            for _, _, callback in sorted(callbacks, key=lambda item: (item[0], item[1])):
                if isinstance(callback, _Action):
                    self._exit(states[callback.position_id], position, executor, requests)
                else:
                    # Market callbacks can enqueue intents but cannot reserve funds during phase 40.
                    self._market_callback(
                        callback[0],
                        callback[1],
                        position,
                        decision_range,
                        # Canonical source order decides the winning leader when multiple buys share
                        # a transaction.
                        strategy,
                        executor,
                        states,
                        by_venue,
                        requests,
                        # Position admission applies before any order can enter phase 50.
                        limits,
                    )
            # Phase 50 retains canonical callback order and each group's instruction order.
            for state, is_buy in requests.values():
                attempt = (
                    executor.begin_buy(state) if is_buy else executor.begin_sell(state, position)
                )
                if attempt.status is CopyAttemptStatus.SUBMITTED:
                    # A submitted instruction has a future landing; a free reject can only schedule
                    # its retry.
                    _schedule(scheduled, state, attempt.expected_landing, position, "ORDER", 60)
                elif state.control.status is CopyPositionStatus.RETRY_WAIT:
                    _schedule(scheduled, state, state.control.retry_position, position, "RETRY", 40)
            # Phase 60 is ordered independently from callbacks and always follows history.
            notifications: list[CopyExecutionPosition] = []
            while scheduled and scheduled[0].release == boundary:
                action = heapq.heappop(scheduled)
                if action.phase != 60:
                    raise ValueError("copy scheduler attempted to revisit an earlier phase")
                # Landing observes the fully applied historical state at this exact boundary.
                state = states[action.position_id]
                executor.land(state, position)
                notifications.append(state)
            # Phase 70 can latch a trigger but cannot revisit phase 50 on this boundary.
            for state in notifications:
                if state.control.status is CopyPositionStatus.OPEN:
                    reason = state.control.evaluate_exit(
                        position=position,
                        current_price=executor.observed.current_price(state.intent),
                        # Only the committed buy notification starts holding-time and price
                        # evaluation.
                    )
                    if reason is None:
                        _schedule(scheduled, state, state.control.deadline, position, "HOLD", 40)
                    else:
                        # Notification-triggered exits use the next canonical callback boundary.
                        due = clock.transaction_after(position, 1)
                        _schedule(scheduled, state, due, position, "EXIT", 40)
                elif state.control.status is CopyPositionStatus.RETRY_WAIT:
                    _schedule(scheduled, state, state.control.retry_position, position, "RETRY", 40)
            # Exceeding admission is a failed attempt, never a partially successful backtest.
            if len(scheduled) > limits.maximum_dynamic_items:
                raise ValueError("copy dynamic scheduler admission limit exceeded")
        if (events, groups) != expected:
            raise ValueError("copy source changed between validation and execution")
        # Publication receives rows separately and cannot embed an unbounded manifest list.
        for state in sorted(
            states.values(),
            key=lambda value: (
                value.intent.signal.position.boundary_ordinal,
                value.intent.roundtrip_id.hex,
                # External keyset order uses source boundary and actual copy position identity.
            ),
        ):
            if state.control.status not in (
                CopyPositionStatus.CLOSED,
                CopyPositionStatus.EXHAUSTED,
                # No partial or debug position may be published as a successful canonical run.
                CopyPositionStatus.BUY_FAILED,
            ):
                raise ValueError("copy replay ended with an unfinished settlement path")
            append_position(state)
        return CopyReplayCounts(events, groups, delivered, len(states), observed_events)

    # The returned counters describe execution, while each row was emitted independently.

    def _market_callback(
        self,
        group: tuple[CanonicalEvent, ...],
        signals: tuple[CopyBuySignal, ...],
        # Only the real source group supplies entry signals and changed venues.
        position: ChainPosition,
        decision_range: BlockRange,
        strategy: CopyBuyStrategy,
        executor: CopyOrderExecutor,
        # Lookup is bounded by admitted positions, not the number of market events.
        states: dict[ContentDigest, CopyExecutionPosition],
        by_venue: dict[VenueId, ContentDigest],
        requests: dict[ContentDigest, tuple[CopyExecutionPosition, bool]],
        limits: CopyReplayLimits,
    ) -> None:
        """Evaluate existing holdings and retain canonical instruction order for entries."""
        affected = {
            event.venue_id
            for event in group
            if isinstance(event, (TokenLaunchEvent, VenueTradeEvent, VenueLifecycleEvent))
        }
        # Canonical position ordering makes simultaneous exits independent of set iteration order.
        for identity in sorted(
            (by_venue[venue] for venue in affected if venue in by_venue),
            key=lambda value: value.hex,
        ):
            self._exit(states[identity], position, executor, requests)
        # Signals come from the validated original actor-bearing transaction, in source order.
        for signal in signals:
            if not decision_range.contains_block(signal.position.block_ordinal):
                continue
            intent = strategy.decide(signal, decision_position=position)
            # A duplicate leader buy leaves the previously consumed mint untouched.
            if intent is None:
                continue
            # Mint consumption is permanent even if this first buy is rejected or fails.
            if len(states) >= limits.maximum_positions:
                raise ValueError("copy position admission limit exceeded")
            state = CopyExecutionPosition(intent)
            states[intent.roundtrip_id], by_venue[intent.venue_id] = state, intent.roundtrip_id
            # Consumption occurs in the callback; quotation/funds/reservation wait for phase 50.
            requests[intent.roundtrip_id] = (state, True)

    # Exit evaluation can latch a condition without submitting multiple pending sells.
    def _exit(
        self,
        state: CopyExecutionPosition,
        position: ChainPosition,
        executor: CopyOrderExecutor,
        # The boundary-local request map deduplicates market and timer triggers.
        requests: dict[ContentDigest, tuple[CopyExecutionPosition, bool]],
    ) -> None:
        """One latched condition owns at most one pending full-position sell."""
        control = state.control
        if control.status is CopyPositionStatus.OPEN:
            # Only already-delivered state can trigger an exit from an open position.
            if (
                control.evaluate_exit(
                    position=position,
                    current_price=executor.observed.current_price(state.intent),
                    # Price thresholds use delivered state, including when a timeout shares this
                    # boundary.
                )
                is None
            ):
                return
        elif control.status is CopyPositionStatus.RETRY_WAIT:
            # A market update before the two-second retry boundary cannot restart a sell.
            if (
                control.retry_position is None
                or position.boundary_ordinal < control.retry_position.boundary_ordinal
            ):
                return
        # Closed, failed-entry and pending-sale positions cannot enqueue another sell.
        else:
            return
        # Repeated market/timer callbacks at this boundary create one phase-50 sell decision.
        requests.setdefault(state.intent.roundtrip_id, (state, False))


# Only simulated actions enter the dynamic heap; market delivery remains sequential.
def _schedule(
    queue: list[_Action],
    state: CopyExecutionPosition,
    release: ChainPosition | None,
    creator: ChainPosition,
    # The phase and action kind are versioned scheduler semantics, not runtime priorities.
    kind: str,
    phase: int,
) -> None:
    """Dynamic items bind their own creation instant and immutable position/attempt ID."""
    if release is None or release.boundary_ordinal <= creator.boundary_ordinal:
        raise ValueError("copy action must be eligible strictly after its creator boundary")
    identity = domain_digest(
        "backtest.copy-scheduled-action.v1",
        {
            # Action identity binds the position, retry ordinal and causal creation boundary.
            "position_id": state.intent.roundtrip_id.hex,
            "kind": kind,
            "attempt": state.control.sell_attempt_count,
            "creator": creator.boundary_ordinal,
        },
        # No wall time, random identifier or physical batch setting enters this digest.
    )
    # Heap size depends on open positions and retries, never on delayed event count.
    heapq.heappush(
        queue,
        _Action(
            release.boundary_ordinal,
            phase,
            # Creator and digest break ties without depending on Python object identity.
            creator.boundary_ordinal,
            bytes.fromhex(identity.hex),
            state.intent.roundtrip_id,
            kind,
        ),
        # The remaining action payload is excluded from comparison ordering.
    )


# A constant transaction delay preserves source order and permits a bounded merge.
def _deliveries(
    source: HistoricalEventSource, clock: CompactTransactionClock, delay: int
) -> Iterator[tuple[int, tuple[CanonicalEvent, ...]]]:
    """Constant global-transaction latency preserves order without an event heap."""
    for group in copy_event_groups(source.events(), clock=clock):
        position = _boundary_position(group)
        if position.transaction_index < 0:
            continue
        # Late tail observations outside the clock cannot affect any in-horizon decision.
        if clock.global_transaction_index(position) + delay >= clock.total_transaction_count:
            return
        release = clock.transaction_after(position, delay) if delay else position
        yield release.boundary_ordinal, group


def _group_seconds(clock: CompactTransactionClock, group: tuple[CanonicalEvent, ...]) -> int:
    """Raw block groups may be empty of transactions, but still have an authoritative time."""
    return clock.block_time_for_block(group[0].envelope.position.block_ordinal) // 1_000_000_000


# Clock-only gaps require no synthetic historical events or interpolated prices.
def _next_boundary(
    history: tuple[CanonicalEvent, ...] | None,
    observation: tuple[int, tuple[CanonicalEvent, ...]] | None,
    queue: list[_Action],
) -> int:
    """Merge the three ordered fronts without expanding global transactions into events."""
    values = [queue[0].release] if queue else []
    if history is not None:
        values.append(history[0].envelope.boundary_ordinal)
    if observation is not None:
        values.append(observation[0])
    # The earliest available front advances the single sequential replay process.
    return min(values)
