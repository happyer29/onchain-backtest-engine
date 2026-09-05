"""Compact all-transaction chain clock for causal execution scheduling.

The clock stores one row per produced block.  It never expands ordinary
network transactions into Python objects.  Lookups use a cumulative prefix to
map a global transaction offset back to an exact ``ChainPosition``.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import pairwise

# Import chain at the visible module dependency boundary.
from backtest.domain.chain import (
    UINT32_MAX,
    UINT64_MAX,
    ChainIdentityMismatchError,
    ChainPosition,
    # Close the chain import after its required symbols are visible.
)
from backtest.domain.identifiers import NetworkId, PositionSchemaId

_NANOSECONDS_PER_SECOND = 1_000_000_000


# Keep the transaction clock error code contract and validation rules together.
class TransactionClockErrorCode(StrEnum):
    EMPTY_CLOCK = "EMPTY_CLOCK"
    ARRAY_LENGTH_MISMATCH = "ARRAY_LENGTH_MISMATCH"
    BLOCK_ORDER_INVALID = "BLOCK_ORDER_INVALID"
    TRANSACTION_COUNT_INVALID = "TRANSACTION_COUNT_INVALID"
    # Declare prefix invalid explicitly in the transaction clock error code contract.
    PREFIX_INVALID = "PREFIX_INVALID"
    PREFIX_OVERFLOW = "PREFIX_OVERFLOW"
    MISSING_BLOCK_TIME = "MISSING_BLOCK_TIME"
    BLOCK_TIME_RESOLUTION_INVALID = "BLOCK_TIME_RESOLUTION_INVALID"
    BLOCK_TIME_REGRESSION = "BLOCK_TIME_REGRESSION"
    # Declare position outside clock explicitly in the transaction clock error code
    # contract.
    POSITION_OUTSIDE_CLOCK = "POSITION_OUTSIDE_CLOCK"
    TRANSACTION_INDEX_OUT_OF_RANGE = "TRANSACTION_INDEX_OUT_OF_RANGE"
    NON_POSITIVE_TRANSACTION_DELAY = "NON_POSITIVE_TRANSACTION_DELAY"
    SETTLEMENT_TAIL_EXHAUSTED = "SETTLEMENT_TAIL_EXHAUSTED"
    DURATION_TARGET_OUTSIDE_CLOCK = "DURATION_TARGET_OUTSIDE_CLOCK"


# Keep the transaction clock error contract and validation rules together.
class TransactionClockError(ValueError):
    """Typed fail-closed transaction-clock error."""

    def __init__(self, code: TransactionClockErrorCode) -> None:
        # Execute the transaction clock error init workflow in explicit, reviewable steps.
        if not isinstance(code, TransactionClockErrorCode):
            raise TypeError("code must be a TransactionClockErrorCode")
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
# Keep the compact transaction clock contract and validation rules together.
class CompactTransactionClock:
    """One-network block clock with exact cumulative transaction prefixes.

    ``cumulative_transaction_prefix[i]`` is the number of transactions in all
    preceding produced blocks.  Zero-transaction blocks are retained, so the
    prefix may repeat while block ordinals remain strictly increasing.
    """

    network_id: NetworkId
    position_schema_id: PositionSchemaId
    block_ordinals: tuple[int, ...]
    transaction_counts: tuple[int, ...]
    cumulative_transaction_prefix: tuple[int, ...]
    # Declare block time ns explicitly in the compact transaction clock contract.
    block_time_ns: tuple[int, ...]
    _cumulative_transaction_end: tuple[int, ...] = field(
        init=False,
        repr=False,
        compare=False,
        # Complete field only after its declared inputs are visible in compact transaction
        # clock.
    )

    def __post_init__(self) -> None:
        # Execute the compact transaction clock post init workflow in explicit, reviewable
        # steps.
        if not isinstance(self.network_id, NetworkId):
            raise TypeError("network_id must be a NetworkId")
        if not isinstance(self.position_schema_id, PositionSchemaId):
            raise TypeError("position_schema_id must be a PositionSchemaId")
        arrays = (
            # Keep the self component named inside the arrays contract.
            self.block_ordinals,
            self.transaction_counts,
            self.cumulative_transaction_prefix,
            self.block_time_ns,
        )
        # Evaluate the complete compact transaction clock post init value, arrays and
        # isinstance condition before guarded effects.
        if any(not isinstance(value, tuple) for value in arrays):
            raise TypeError("transaction clock arrays must be immutable tuples")
        if not self.block_ordinals:
            raise TransactionClockError(TransactionClockErrorCode.EMPTY_CLOCK)
        if any(len(value) != len(self.block_ordinals) for value in arrays[1:]):
            # Fail the compact transaction clock post init path with TransactionClockError
            # for array length mismatch and transaction clock error code when value, block
            # ordinals and arrays is true; do not continue ambiguously.
            raise TransactionClockError(TransactionClockErrorCode.ARRAY_LENGTH_MISMATCH)
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in self.block_ordinals
        ) or any(left >= right for left, right in pairwise(self.block_ordinals)):
            # Fail the compact transaction clock post init path with TransactionClockError
            # for block order invalid and transaction clock error code when value, block
            # ordinals and left is true; do not continue ambiguously.
            raise TransactionClockError(TransactionClockErrorCode.BLOCK_ORDER_INVALID)
        if any(
            isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= UINT32_MAX
            for value in self.transaction_counts
        ):
            # Fail the compact transaction clock post init path with TransactionClockError
            # for transaction count invalid and transaction clock error code when value,
            # transaction counts and isinstance is true; do not continue ambiguously.
            raise TransactionClockError(TransactionClockErrorCode.TRANSACTION_COUNT_INVALID)
        expected_prefix = 0
        transaction_ends: list[int] = []
        for prefix, count in zip(
            self.cumulative_transaction_prefix,
            # Pass self explicitly so zip receives a reviewable cumulative transaction
            # prefix and transaction counts input in compact transaction clock post init.
            self.transaction_counts,
            strict=True,
        ):
            # Process cumulative transaction prefix and transaction counts inside the
            # bounded compact transaction clock post init loop.
            if isinstance(prefix, bool) or not isinstance(prefix, int) or prefix != expected_prefix:
                raise TransactionClockError(TransactionClockErrorCode.PREFIX_INVALID)
            expected_prefix += count
            if expected_prefix > UINT64_MAX:
                raise TransactionClockError(TransactionClockErrorCode.PREFIX_OVERFLOW)
            # Invoke append for expected prefix as a visible compact transaction clock
            # post init step.
            transaction_ends.append(expected_prefix)
        for value in self.block_time_ns:
            # Process self.block_time_ns inside the bounded compact transaction clock post
            # init loop.
            if isinstance(value, bool) or not isinstance(value, int):
                raise TransactionClockError(TransactionClockErrorCode.MISSING_BLOCK_TIME)
            if value < 0 or value % _NANOSECONDS_PER_SECOND:
                raise TransactionClockError(TransactionClockErrorCode.BLOCK_TIME_RESOLUTION_INVALID)
        if any(left > right for left, right in pairwise(self.block_time_ns)):
            # Fail the compact transaction clock post init path with TransactionClockError
            # for block time regression and transaction clock error code when left, right
            # and pairwise is true; do not continue ambiguously.
            raise TransactionClockError(TransactionClockErrorCode.BLOCK_TIME_REGRESSION)
        object.__setattr__(self, "_cumulative_transaction_end", tuple(transaction_ends))

    @property
    def total_transaction_count(self) -> int:
        return self.cumulative_transaction_prefix[-1] + self.transaction_counts[-1]

    # Define compact transaction clock require position as one focused operation with an
    # explicit boundary.
    def require_position(self, position: ChainPosition) -> int:
        """Validate a real transaction position and return its clock row."""

        if not isinstance(position, ChainPosition):
            raise TypeError("position must be a ChainPosition")
        if (
            position.network_id != self.network_id
            or position.position_schema_id != self.position_schema_id
            # Evaluate the complete compact transaction clock require position network id,
            # position schema id and position condition before guarded effects.
        ):
            # Handle the compact transaction clock require position network id, position
            # schema id and position condition as a distinct block.
            raise ChainIdentityMismatchError(
                "position and transaction clock use different chain identities"
            )
        block_index = bisect_left(self.block_ordinals, position.block_ordinal)
        if (
            # Keep block index visible while evaluating the block index, block ordinal and
            # block ordinals guard.
            block_index == len(self.block_ordinals)
            or self.block_ordinals[block_index] != position.block_ordinal
        ):
            raise TransactionClockError(TransactionClockErrorCode.POSITION_OUTSIDE_CLOCK)
        transaction_count = self.transaction_counts[block_index]
        # Evaluate the complete compact transaction clock require position transaction
        # index, transaction count and position condition before guarded effects.
        if not 0 <= position.transaction_index < transaction_count:
            raise TransactionClockError(TransactionClockErrorCode.TRANSACTION_INDEX_OUT_OF_RANGE)
        return block_index

    def block_time_for_position(self, position: ChainPosition) -> int:
        return self.block_time_ns[self.require_position(position)]

    # Define compact transaction clock block time for block as one focused operation with
    # an explicit boundary.
    def block_time_for_block(self, block_ordinal: int) -> int:
        """Return the modeled time for a produced block, including empty blocks."""

        if isinstance(block_ordinal, bool) or not isinstance(block_ordinal, int):
            raise TypeError("block ordinal must be an integer")
        block_index = bisect_left(self.block_ordinals, block_ordinal)
        if (
            block_index == len(self.block_ordinals)
            # Keep self visible while evaluating the block index, block ordinal and block
            # ordinals guard.
            or self.block_ordinals[block_index] != block_ordinal
        ):
            raise TransactionClockError(TransactionClockErrorCode.POSITION_OUTSIDE_CLOCK)
        return self.block_time_ns[block_index]

    def global_transaction_index(self, position: ChainPosition) -> int:
        # Execute the compact transaction clock global transaction index workflow in
        # explicit, reviewable steps.
        block_index = self.require_position(position)
        return self.cumulative_transaction_prefix[block_index] + position.transaction_index

    def transaction_after(
        self,
        position: ChainPosition,
        # Keep the transaction delay input explicit in the transaction after contract.
        transaction_delay: int,
    ) -> ChainPosition:
        """Return the boundary after exactly ``transaction_delay`` next txs.

        The next transaction after ``position`` is numbered one.  A returned
        position therefore represents the historical transaction after which
        an execution phase runs and before the following transaction.
        """

        if (
            isinstance(transaction_delay, bool)
            or not isinstance(transaction_delay, int)
            or transaction_delay < 1
        ):
            # Fail the compact transaction clock transaction after path with
            # TransactionClockError for non positive transaction delay and transaction
            # clock error code when isinstance and transaction delay is true; do not
            # continue ambiguously.
            raise TransactionClockError(TransactionClockErrorCode.NON_POSITIVE_TRANSACTION_DELAY)
        target_global_index = self.global_transaction_index(position) + transaction_delay
        if target_global_index >= self.total_transaction_count:
            raise TransactionClockError(TransactionClockErrorCode.SETTLEMENT_TAIL_EXHAUSTED)
        block_index = bisect_right(self._cumulative_transaction_end, target_global_index)
        # ``target < total`` guarantees a non-empty containing block even when
        # one or more zero-transaction blocks repeat the prefix.
        return ChainPosition(
            network_id=self.network_id,
            position_schema_id=self.position_schema_id,
            block_ordinal=self.block_ordinals[block_index],
            transaction_index=(
                # Pass target global index explicitly so ChainPosition receives a
                # reviewable network id and position schema id input in compact
                # transaction clock transaction after.
                target_global_index - self.cumulative_transaction_prefix[block_index]
            ),
            event_index=None,
        )

    def first_nonempty_transaction_at_or_after(
        # Keep the remaining first nonempty transaction at or after inputs visible at the
        # compact transaction clock first nonempty transaction at or after boundary.
        self,
        *,
        after_position: ChainPosition,
        target_time_ns: int,
    ) -> ChainPosition:
        """Ceil duration time to the first later non-empty block boundary."""

        start_index = self.require_position(after_position) + 1
        if (
            isinstance(target_time_ns, bool)
            or not isinstance(target_time_ns, int)
            or target_time_ns < 0
            # Evaluate the complete compact transaction clock first nonempty transaction at or
            # after isinstance and target time ns condition before guarded effects.
        ):
            raise ValueError("target_time_ns must be a non-negative integer")
        index = bisect_left(self.block_time_ns, target_time_ns, lo=start_index)
        while index < len(self.block_ordinals) and self.transaction_counts[index] == 0:
            # Keep the index, block ordinals and transaction counts loop body bounded
            # within compact transaction clock first nonempty transaction at or after.
            index += 1
            if index < len(self.block_ordinals) and self.block_time_ns[index] < target_time_ns:
                index = bisect_left(self.block_time_ns, target_time_ns, lo=index)
        if index == len(self.block_ordinals):
            raise TransactionClockError(TransactionClockErrorCode.DURATION_TARGET_OUTSIDE_CLOCK)
        # Return the completed compact transaction clock first nonempty transaction at or
        # after result without a hidden fallback.
        return ChainPosition(
            network_id=self.network_id,
            position_schema_id=self.position_schema_id,
            block_ordinal=self.block_ordinals[index],
            transaction_index=0,
            # Pass event index explicitly so ChainPosition receives a reviewable network
            # id and position schema id input in compact transaction clock first nonempty
            # transaction at or after.
            event_index=None,
        )


__all__ = [
    "CompactTransactionClock",
    "TransactionClockError",
    # Keep the transaction clock error code component named inside the all contract.
    "TransactionClockErrorCode",
]
