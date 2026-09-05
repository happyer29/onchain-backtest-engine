"""Reference causal scheduler with the normative phase ordering."""

from __future__ import annotations

import heapq
from bisect import bisect_left
from dataclasses import dataclass, field
from enum import IntEnum

# Import itertools at the visible module dependency boundary.
from itertools import pairwise

from backtest.domain.chain import ChainPosition
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import BundleId, ContentDigest

SCHEDULER_BUNDLE_ID = BundleId(
    # Keep the v2 domain_digest step visible while building scheduler bundle id.
    domain_digest(
        "backtest.causal-scheduler-bundle.v2",
        {
            "chain_position": "explicit-network-position-schema-v1",
            "key": "canonical-v1",
            # Keep phase table named so the v2 and chain position payload passed to
            # domain_digest remains self-describing within module.
            "phase_table": "canonical-v1",
        },
    ).hex
)


# Keep the scheduler phase contract and validation rules together.
class SchedulerPhase(IntEnum):
    HISTORICAL_REFERENCE_APPLY = 10
    SIMULATION_STATE_RECONCILE = 20
    OBSERVATION_DELIVERY = 30
    STRATEGY_CALLBACK = 40
    # Declare risk and order acceptance explicitly in the scheduler phase contract.
    RISK_AND_ORDER_ACCEPTANCE = 50
    VENUE_EXECUTION_AND_LEDGER_COMMIT = 60
    STRATEGY_EXECUTION_NOTIFICATION = 70
    CHECKPOINT = 80


# Keep the scheduler instant contract and validation rules together.
@dataclass(frozen=True, slots=True)
class SchedulerInstant:
    boundary_ordinal: int
    chain_position: ChainPosition | None
    monotone_logical_ns: int | None = None

    # Define scheduler instant post init as one focused operation with an explicit
    # boundary.
    def __post_init__(self) -> None:
        # Execute the scheduler instant post init workflow in explicit, reviewable steps.
        if (
            isinstance(self.boundary_ordinal, bool)
            or not isinstance(self.boundary_ordinal, int)
            or self.boundary_ordinal < 0
        ):
            # Fail the scheduler instant post init path with ValueError for boundary
            # ordinal must be a non-negative integer when isinstance and boundary ordinal
            # is true; do not continue ambiguously.
            raise ValueError("boundary_ordinal must be a non-negative integer")
        if self.chain_position is not None:
            # Handle the scheduler instant post init self.chain_position is not None
            # branch as a distinct logical block.
            if not isinstance(self.chain_position, ChainPosition):
                raise TypeError("chain_position must be a ChainPosition or None")
            if self.chain_position.boundary_ordinal != self.boundary_ordinal:
                raise ValueError("scheduler instant position does not match its boundary ordinal")
        if self.monotone_logical_ns is not None and (
            # Keep isinstance visible while evaluating the monotone logical ns and
            # isinstance guard.
            isinstance(self.monotone_logical_ns, bool)
            or not isinstance(self.monotone_logical_ns, int)
        ):
            raise TypeError("monotone_logical_ns must be an integer or None")

    @property
    # Define scheduler instant chain slot as one focused operation with an explicit
    # boundary.
    def chain_slot(self) -> int | None:
        """Deprecated read-only bridge for slot-shaped internal callers."""

        return None if self.chain_position is None else self.chain_position.block_ordinal


# Keep the scheduler key contract and validation rules together.
@dataclass(frozen=True, slots=True, order=True)
class SchedulerKey:
    release_boundary_ordinal: int
    phase_priority: SchedulerPhase
    source_or_creator_boundary_ordinal: int
    # Declare stable causal id hex explicitly in the scheduler key contract.
    stable_causal_id_hex: str

    def __post_init__(self) -> None:
        # Execute the scheduler key post init workflow in explicit, reviewable steps.
        if self.release_boundary_ordinal < 0:
            raise ValueError("release boundary must be non-negative")
        if self.source_or_creator_boundary_ordinal < 0:
            raise ValueError("source/creator boundary must be non-negative")
        ContentDigest(self.stable_causal_id_hex)


# Keep the heap item contract and validation rules together.
@dataclass(order=True, slots=True)
class _HeapItem[T]:
    key: SchedulerKey
    payload: T = field(compare=False)


class CausalScheduler[T]:
    """Small heap reserved for dynamic orders, timers and notifications."""

    def __init__(self) -> None:
        # Execute the causal scheduler init workflow in explicit, reviewable steps.
        self._heap: list[_HeapItem[T]] = []
        self._keys: set[SchedulerKey] = set()

    def enqueue(self, key: SchedulerKey, payload: T) -> None:
        # Execute the causal scheduler enqueue workflow in explicit, reviewable steps.
        if key in self._keys:
            raise ValueError("scheduler key collision")
        heapq.heappush(self._heap, _HeapItem(key, payload))
        self._keys.add(key)

    def pop_ready(
        # Keep the remaining pop ready inputs visible at the causal scheduler pop ready
        # boundary.
        self,
        boundary: int,
        *,
        through_phase: SchedulerPhase = SchedulerPhase.CHECKPOINT,
    ) -> tuple[tuple[SchedulerKey, T], ...]:
        # Execute the causal scheduler pop ready workflow in explicit, reviewable steps.
        ready: list[tuple[SchedulerKey, T]] = []
        limit = (boundary, int(through_phase))
        while self._heap:
            # Keep the self._heap loop body bounded within causal scheduler pop ready.
            item = self._heap[0]
            item_prefix = (item.key.release_boundary_ordinal, int(item.key.phase_priority))
            if item_prefix > limit:
                break
            popped = heapq.heappop(self._heap)
            # Invoke remove for key and popped as a visible causal scheduler pop ready
            # step.
            self._keys.remove(popped.key)
            ready.append((popped.key, popped.payload))
        return tuple(ready)

    def __len__(self) -> int:
        return len(self._heap)


# Define first boundary at or after slot as one focused operation with an explicit
# boundary.
def first_boundary_at_or_after_slot(
    *,
    target_slot: int,
    boundary_slots: tuple[int, ...],
    boundary_ordinals: tuple[int, ...],
    # Keep the int input explicit in the first boundary at or after slot contract.
) -> int:
    # Execute the first boundary at or after slot workflow in explicit, reviewable steps.
    if target_slot < 0:
        raise ValueError("target_slot must be non-negative")
    if len(boundary_slots) != len(boundary_ordinals) or not boundary_slots:
        raise ValueError("boundary slot and ordinal arrays must be non-empty and aligned")
    if any(left > right for left, right in pairwise(boundary_slots)):
        # Fail the first boundary at or after slot path with ValueError for boundary slots
        # must be monotone when left, right and pairwise is true; do not continue
        # ambiguously.
        raise ValueError("boundary slots must be monotone")
    index = bisect_left(boundary_slots, target_slot)
    if index == len(boundary_slots):
        raise LookupError("latency target is outside the replay horizon")
    return boundary_ordinals[index]


# Define first boundary at or after block as one focused operation with an explicit
# boundary.
def first_boundary_at_or_after_block(
    *,
    target_block_ordinal: int,
    boundary_block_ordinals: tuple[int, ...],
    boundary_ordinals: tuple[int, ...],
    # Keep the int input explicit in the first boundary at or after block contract.
) -> int:
    """Generic block-coordinate equivalent of the transitional slot helper."""

    if target_block_ordinal < 0:
        raise ValueError("target_block_ordinal must be non-negative")
    if len(boundary_block_ordinals) != len(boundary_ordinals) or not boundary_block_ordinals:
        raise ValueError("boundary block and ordinal arrays must be non-empty and aligned")
    if any(left > right for left, right in pairwise(boundary_block_ordinals)):
        # Fail the first boundary at or after block path with ValueError for boundary
        # blocks must be monotone when left, right and pairwise is true; do not continue
        # ambiguously.
        raise ValueError("boundary blocks must be monotone")
    index = bisect_left(boundary_block_ordinals, target_block_ordinal)
    if index == len(boundary_block_ordinals):
        raise LookupError("latency target is outside the replay horizon")
    return boundary_ordinals[index]


# Define next order eligible boundary as one focused operation with an explicit boundary.
def next_order_eligible_boundary(*, current_decision_boundary: int, candidate_boundary: int) -> int:
    """Forbid execution in a transaction group already applied to history."""

    if current_decision_boundary < 0 or candidate_boundary < 0:
        raise ValueError("boundary ordinals must be non-negative")
    if candidate_boundary <= current_decision_boundary:
        return current_decision_boundary + 1
    return candidate_boundary


# Bind all once as an explicit module-level contract.
__all__ = [
    "SCHEDULER_BUNDLE_ID",
    "CausalScheduler",
    "SchedulerInstant",
    "SchedulerKey",
    # Keep the scheduler phase component named inside the all contract.
    "SchedulerPhase",
    "first_boundary_at_or_after_block",
    "first_boundary_at_or_after_slot",
    "next_order_eligible_boundary",
]
