# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from backtest.domain.chain import (
    # Include block32 transaction32 position schema id so the chain dependency remains
    # explicit.
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
    ChainPosition,
)
from backtest.engine.transaction_clock import (
    # Include compact transaction clock so the transaction clock dependency remains
    # explicit.
    CompactTransactionClock,
    TransactionClockError,
    TransactionClockErrorCode,
)


def _clock(
    # Keep the counts input explicit in the clock contract.
    counts: tuple[int, ...] = (2, 0, 3, 1),
    times: tuple[int, ...] = (10, 11, 12, 13),
) -> CompactTransactionClock:
    # Execute the clock workflow in explicit, reviewable steps.
    prefix: list[int] = []
    total = 0
    for count in counts:
        # Process counts inside the bounded clock loop.
        prefix.append(total)
        total += count
    return CompactTransactionClock(
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        # Include block ordinals in the completed clock result.
        block_ordinals=tuple(100 + index for index in range(len(counts))),
        transaction_counts=counts,
        cumulative_transaction_prefix=tuple(prefix),
        block_time_ns=tuple(value * 1_000_000_000 for value in times),
    )


# Define position as one focused operation with an explicit boundary.
def _position(block: int, transaction: int) -> ChainPosition:
    # Execute the position workflow in explicit, reviewable steps.
    return ChainPosition(
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        block_ordinal=block,
        transaction_index=transaction,
        # Pass event index explicitly so ChainPosition receives a reviewable solana
        # mainnet network id and block32 transaction32 position schema id input in
        # position.
        event_index=None,
    )


def test_transaction_offset_crosses_zero_transaction_blocks_exactly() -> None:
    # Execute the test transaction offset crosses zero transaction blocks exactly workflow
    # in explicit, reviewable steps.
    clock = _clock()

    assert clock.transaction_after(_position(100, 0), 1) == _position(100, 1)
    assert clock.transaction_after(_position(100, 0), 2) == _position(102, 0)
    assert clock.transaction_after(_position(100, 1), 3) == _position(102, 2)
    assert clock.transaction_after(_position(102, 2), 1) == _position(103, 0)


# Define test duration ceil skips empty blocks and then transaction delay is separate as
# one focused operation with an explicit boundary.
def test_duration_ceil_skips_empty_blocks_and_then_transaction_delay_is_separate() -> None:
    # Execute the test duration ceil skips empty blocks and then transaction delay is
    # separate workflow in explicit, reviewable steps.
    clock = _clock(
        counts=(1, 0, 2, 1, 1),
        times=(10, 12, 12, 12, 13),
    )

    decision = clock.first_nonempty_transaction_at_or_after(
        # Keep the position _position step visible while building decision.
        after_position=_position(100, 0),
        target_time_ns=12_000_000_000,
    )

    assert decision == _position(102, 0)
    assert clock.transaction_after(decision, 1) == _position(102, 1)


# Define test insufficient tail and invalid clock fail with typed codes as one focused
# operation with an explicit boundary.
def test_insufficient_tail_and_invalid_clock_fail_with_typed_codes() -> None:
    # Execute the test insufficient tail and invalid clock fail with typed codes workflow
    # in explicit, reviewable steps.
    clock = _clock()
    with pytest.raises(TransactionClockError) as tail:
        clock.transaction_after(_position(103, 0), 1)
    assert tail.value.code is TransactionClockErrorCode.SETTLEMENT_TAIL_EXHAUSTED

    with pytest.raises(TransactionClockError) as regression:
        # Invoke _clock as a visible step within the test insufficient tail and invalid
        # clock fail with typed codes workflow.
        _clock(times=(10, 12, 11, 13))
    assert regression.value.code is TransactionClockErrorCode.BLOCK_TIME_REGRESSION

    with pytest.raises(TransactionClockError) as prefix:
        # Keep raises, transaction clock error and pytest active only for the bounded test
        # insufficient tail and invalid clock fail with typed codes operation.
        CompactTransactionClock(
            network_id=SOLANA_MAINNET_NETWORK_ID,
            position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            block_ordinals=(1,),
            transaction_counts=(1,),
            # Pass cumulative transaction prefix explicitly so CompactTransactionClock
            # receives a reviewable solana mainnet network id and block32 transaction32
            # position schema id input in test insufficient tail and invalid clock fail
            # with typed codes.
            cumulative_transaction_prefix=(1,),
            block_time_ns=(1_000_000_000,),
        )
    assert prefix.value.code is TransactionClockErrorCode.PREFIX_INVALID


@given(
    # Define test prefix lookup matches naive transaction expansion as one focused
    # operation with an explicit boundary.
    counts=st.lists(st.integers(min_value=0, max_value=8), min_size=1, max_size=20).filter(
        lambda values: sum(values) >= 2
    ),
    source_global=st.integers(min_value=0, max_value=200),
    delay=st.integers(min_value=1, max_value=200),
    # Complete given only after its filter and lists inputs are visible in test prefix lookup
    # matches naive transaction expansion.
)
def test_prefix_lookup_matches_naive_transaction_expansion(
    counts: list[int], source_global: int, delay: int
) -> None:
    # Execute the test prefix lookup matches naive transaction expansion workflow in
    # explicit, reviewable steps.
    naive = [
        (100 + block_index, transaction_index)
        for block_index, count in enumerate(counts)
        for transaction_index in range(count)
    ]
    # Assemble source index once so the test prefix lookup matches naive transaction
    # expansion workflow shares one value.
    source_index = source_global % (len(naive) - 1)
    maximum_delay = len(naive) - source_index - 1
    chosen_delay = 1 + (delay - 1) % maximum_delay
    clock = _clock(
        tuple(counts),
        # Keep the index and counts tuple step visible while building clock.
        tuple(1_000 + index for index in range(len(counts))),
    )
    source = _position(*naive[source_index])

    actual = clock.transaction_after(source, chosen_delay)

    assert (actual.block_ordinal, actual.transaction_index) == naive[source_index + chosen_delay]
