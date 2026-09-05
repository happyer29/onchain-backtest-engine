"""Canonical half-open chain ranges."""

from __future__ import annotations

from dataclasses import dataclass

from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    UINT32_SIZE,
    # Include chain identity mismatch error so the chain dependency remains explicit.
    ChainIdentityMismatchError,
    ChainPosition,
)
from backtest.domain.identifiers import NetworkId, PositionSchemaId


@dataclass(frozen=True, slots=True, order=True)
# Keep the block range contract and validation rules together.
class BlockRange:
    """A non-empty half-open block range on one exact chain identity."""

    network_id: NetworkId
    position_schema_id: PositionSchemaId
    from_block_ordinal: int
    to_block_ordinal: int

    def __post_init__(self) -> None:
        # Execute the block range post init workflow in explicit, reviewable steps.
        if not isinstance(self.network_id, NetworkId):
            raise TypeError("network_id must be a NetworkId")
        if not isinstance(self.position_schema_id, PositionSchemaId):
            raise TypeError("position_schema_id must be a PositionSchemaId")
        if self.position_schema_id != BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID:
            # Fail the block range post init path with ValueError for block range uses an
            # unsupported position schema when position schema id and block32
            # transaction32 position schema id is true; do not continue ambiguously.
            raise ValueError("BlockRange uses an unsupported position schema")
        for field_name in ("from_block_ordinal", "to_block_ordinal"):
            # Process from block ordinal and to block ordinal inside the bounded block
            # range post init loop.
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
        if self.from_block_ordinal < 0:
            raise ValueError("from_block_ordinal must be non-negative")
        # Evaluate the complete block range post init to block ordinal and from block
        # ordinal condition before guarded effects.
        if self.to_block_ordinal <= self.from_block_ordinal:
            raise ValueError("block range must be non-empty")
        if self.to_block_ordinal > UINT32_SIZE:
            raise OverflowError("block range exceeds block32-transaction32-v1 capacity")

    @property
    # Define block range span as one focused operation with an explicit boundary.
    def span(self) -> int:
        return self.to_block_ordinal - self.from_block_ordinal

    def contains_block(self, block_ordinal: int) -> bool:
        # Execute the block range contains block workflow in explicit, reviewable steps.
        if isinstance(block_ordinal, bool) or not isinstance(block_ordinal, int):
            raise TypeError("block_ordinal must be an integer")
        return self.from_block_ordinal <= block_ordinal < self.to_block_ordinal

    def contains_position(self, position: ChainPosition) -> bool:
        # Execute the block range contains position workflow in explicit, reviewable
        # steps.
        if not isinstance(position, ChainPosition):
            raise TypeError("position must be a ChainPosition")
        if (
            position.network_id != self.network_id
            or position.position_schema_id != self.position_schema_id
            # Evaluate the complete block range contains position network id, position schema
            # id and position condition before guarded effects.
        ):
            # Handle the block range contains position network id, position schema id and
            # position condition as a distinct block.
            raise ChainIdentityMismatchError(
                "position does not belong to the block range chain identity"
            )
        return self.contains_block(position.block_ordinal)

    def with_warmup(self, warmup_blocks: int) -> BlockRange:
        # Execute the block range with warmup workflow in explicit, reviewable steps.
        if isinstance(warmup_blocks, bool) or not isinstance(warmup_blocks, int):
            raise TypeError("warmup_blocks must be an integer")
        if warmup_blocks < 0:
            raise ValueError("warmup_blocks must be non-negative")
        return BlockRange(
            # Pass self explicitly so BlockRange receives a reviewable network id and
            # position schema id input in block range with warmup.
            self.network_id,
            self.position_schema_id,
            max(0, self.from_block_ordinal - warmup_blocks),
            self.to_block_ordinal,
        )

    # Define block range split as one focused operation with an explicit boundary.
    def split(self, max_span: int) -> tuple[BlockRange, ...]:
        # Execute the block range split workflow in explicit, reviewable steps.
        if isinstance(max_span, bool) or not isinstance(max_span, int):
            raise TypeError("max_span must be an integer")
        if max_span <= 0:
            raise ValueError("max_span must be positive")
        ranges: list[BlockRange] = []
        # Assemble start once so the block range split workflow shares one value.
        start = self.from_block_ordinal
        while start < self.to_block_ordinal:
            # Keep the start < self.to_block_ordinal loop body bounded within block range
            # split.
            end = min(start + max_span, self.to_block_ordinal)
            ranges.append(
                BlockRange(
                    self.network_id,
                    self.position_schema_id,
                    # Pass start explicitly so BlockRange receives a reviewable network id
                    # and position schema id input in block range split.
                    start,
                    end,
                )
            )
            start = end
        # Return the completed block range split result without a hidden fallback.
        return tuple(ranges)


@dataclass(frozen=True, slots=True, order=True)
class SlotRange:
    """A non-empty, half-open Solana slot range ``[from_slot, to_slot)``."""

    from_slot: int
    to_slot: int

    def __post_init__(self) -> None:
        # Execute the slot range post init workflow in explicit, reviewable steps.
        if isinstance(self.from_slot, bool) or not isinstance(self.from_slot, int):
            raise TypeError("from_slot must be an integer")
        if isinstance(self.to_slot, bool) or not isinstance(self.to_slot, int):
            raise TypeError("to_slot must be an integer")
        if self.from_slot < 0:
            # Fail the slot range post init path with ValueError for from slot must be
            # non-negative when from slot is true; do not continue ambiguously.
            raise ValueError("from_slot must be non-negative")
        if self.to_slot <= self.from_slot:
            raise ValueError("slot range must be non-empty")

    @property
    def span(self) -> int:
        # Return the completed slot range span result without a hidden fallback.
        return self.to_slot - self.from_slot

    def contains(self, slot: int) -> bool:
        return self.from_slot <= slot < self.to_slot

    def with_warmup(self, warmup_slots: int) -> SlotRange:
        # Execute the slot range with warmup workflow in explicit, reviewable steps.
        if isinstance(warmup_slots, bool) or not isinstance(warmup_slots, int):
            raise TypeError("warmup_slots must be an integer")
        if warmup_slots < 0:
            raise ValueError("warmup_slots must be non-negative")
        return SlotRange(max(0, self.from_slot - warmup_slots), self.to_slot)

    # Define slot range split as one focused operation with an explicit boundary.
    def split(self, max_span: int) -> tuple[SlotRange, ...]:
        """Split without gaps or overlaps while preserving half-open semantics."""

        if isinstance(max_span, bool) or not isinstance(max_span, int):
            raise TypeError("max_span must be an integer")
        if max_span <= 0:
            raise ValueError("max_span must be positive")

        ranges: list[SlotRange] = []
        # Assemble start once so the slot range split workflow shares one value.
        start = self.from_slot
        while start < self.to_slot:
            # Keep the start < self.to_slot loop body bounded within slot range split.
            end = min(start + max_span, self.to_slot)
            ranges.append(SlotRange(start, end))
            start = end
        return tuple(ranges)


__all__ = ["BlockRange", "SlotRange"]
