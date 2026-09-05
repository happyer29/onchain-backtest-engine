# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import itertools

import pytest

from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    # Include solana mainnet network id so the chain dependency remains explicit.
    SOLANA_MAINNET_NETWORK_ID,
    ChainPosition,
)
from backtest.domain.identifiers import ContentDigest
from backtest.engine.rng import KeyedRng

# Import scheduler at the visible module dependency boundary.
from backtest.engine.scheduler import (
    CausalScheduler,
    SchedulerInstant,
    SchedulerKey,
    SchedulerPhase,
    # Include first boundary at or after slot so the scheduler dependency remains
    # explicit.
    first_boundary_at_or_after_slot,
    next_order_eligible_boundary,
)


def test_scheduler_instant_requires_a_matching_explicit_chain_position() -> None:
    # Execute the test scheduler instant requires a matching explicit chain position
    # workflow in explicit, reviewable steps.
    position = ChainPosition(
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        block_ordinal=10,
        transaction_index=2,
        # Pass event index explicitly so ChainPosition receives a reviewable solana
        # mainnet network id and block32 transaction32 position schema id input in test
        # scheduler instant requires a matching explicit chain position.
        event_index=None,
    )

    assert SchedulerInstant(position.boundary_ordinal, position).chain_slot == 10
    with pytest.raises(ValueError, match="does not match"):
        SchedulerInstant(position.boundary_ordinal + 1, position)


# Define test scheduler order is independent of enqueue permutation as one focused
# operation with an explicit boundary.
def test_scheduler_order_is_independent_of_enqueue_permutation() -> None:
    # Execute the test scheduler order is independent of enqueue permutation workflow in
    # explicit, reviewable steps.
    items = (
        (_key(12, SchedulerPhase.OBSERVATION_DELIVERY, 10, "1"), "late"),
        (_key(11, SchedulerPhase.VENUE_EXECUTION_AND_LEDGER_COMMIT, 9, "2"), "execute"),
        (_key(11, SchedulerPhase.OBSERVATION_DELIVERY, 10, "3"), "observe"),
        (_key(11, SchedulerPhase.OBSERVATION_DELIVERY, 9, "4"), "older"),
        # Complete the items group only after its semantic components are visible.
    )
    expected = ("older", "observe", "execute", "late")

    for permutation in itertools.permutations(items):
        # Process itertools.permutations(items) inside the bounded test scheduler order is
        # independent of enqueue permutation loop.
        scheduler: CausalScheduler[str] = CausalScheduler()
        for key, value in permutation:
            scheduler.enqueue(key, value)
        assert tuple(value for _, value in scheduler.pop_ready(12)) == expected


def test_scheduler_rejects_an_ambiguous_key_collision() -> None:
    # Execute the test scheduler rejects an ambiguous key collision workflow in explicit,
    # reviewable steps.
    scheduler: CausalScheduler[str] = CausalScheduler()
    key = _key(1, SchedulerPhase.OBSERVATION_DELIVERY, 1, "a")
    scheduler.enqueue(key, "first")

    with pytest.raises(ValueError, match="collision"):
        scheduler.enqueue(key, "second")


# Define test slot rounding and current group order rule as one focused operation with an
# explicit boundary.
def test_slot_rounding_and_current_group_order_rule() -> None:
    # Execute the test slot rounding and current group order rule workflow in explicit,
    # reviewable steps.
    assert (
        first_boundary_at_or_after_slot(
            target_slot=101,
            boundary_slots=(100, 100, 102),
            boundary_ordinals=(10, 11, 20),
            # Complete first_boundary_at_or_after_slot only after its declared inputs are
            # visible in test slot rounding and current group order rule.
        )
        == 20
    )
    assert (
        next_order_eligible_boundary(
            # Pass current decision boundary explicitly into next_order_eligible_boundary
            # within test slot rounding and current group order rule.
            current_decision_boundary=10,
            candidate_boundary=10,
        )
        == 11
    )
    # Verify the next order eligible boundary relationship before this scenario is
    # accepted.
    assert (
        next_order_eligible_boundary(
            current_decision_boundary=10,
            candidate_boundary=20,
        )
        # Verify the next order eligible boundary relationship before this scenario is
        # accepted.
        == 20
    )


def test_keyed_rng_has_a_golden_vector_and_is_call_order_independent() -> None:
    # Execute the test keyed rng has a golden vector and is call order independent
    # workflow in explicit, reviewable steps.
    rng = KeyedRng(42)
    component = ContentDigest("1" * 64)
    causal = ContentDigest("2" * 64)
    other = ContentDigest("3" * 64)

    expected = rng.draw_bytes(component_id=component, causal_id=causal, draw_index=7)
    # Invoke draw_bytes for component and other as a visible test keyed rng has a golden
    # vector and is call order independent step.
    rng.draw_bytes(component_id=component, causal_id=other, draw_index=0)
    repeated = rng.draw_bytes(component_id=component, causal_id=causal, draw_index=7)

    assert expected == repeated
    assert expected.hex() == "0d372dd0ef756071db80212e910dc599bc2d3e263dc1ea67c0f0acdb2b4cef62"


def _key(
    # Keep the release input explicit in the key contract.
    release: int,
    phase: SchedulerPhase,
    source: int,
    digest_digit: str,
) -> SchedulerKey:
    # Return the completed key result without a hidden fallback.
    return SchedulerKey(release, phase, source, digest_digit * 64)
