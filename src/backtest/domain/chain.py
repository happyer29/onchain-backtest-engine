"""Generic, versioned chain-position contracts.

The core keeps network identity separate from ordinal arithmetic.  The first
supported physical position schema deliberately fits one boundary in UInt64 so
the replay hot path can remain compact.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from backtest.domain.identifiers import NetworkId, PositionSchemaId

UINT32_SIZE: Final = 1 << 32
# Bind uint32 max once as an explicit module-level contract.
UINT32_MAX: Final = UINT32_SIZE - 1
UINT64_MAX: Final = (1 << 64) - 1

BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID: Final = PositionSchemaId("block32-transaction32-v1")
SOLANA_MAINNET_NETWORK_ID: Final = NetworkId("solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d")


class UnsupportedPositionSchemaError(ValueError):
    """The runtime cannot interpret the requested position schema."""


class ChainIdentityMismatchError(ValueError):
    """Values from different networks or position schemas were combined."""


def boundary_ordinal(
    block_ordinal: int,
    transaction_index: int,
    *,
    position_schema_id: PositionSchemaId,
    # Keep the int input explicit in the boundary ordinal contract.
) -> int:
    """Encode one historical boundary using an explicit position schema.

    For ``block32-transaction32-v1`` the synthetic block boundary uses
    ``transaction_index=-1`` and maps to the low-word value zero.  Real
    transaction zero follows at ``+1``.  The greatest real transaction index
    is ``UInt32.max - 1`` so the encoded low word still fits UInt32.
    """

    _require_supported_schema(position_schema_id)
    block = _checked_uint32(block_ordinal, "block_ordinal")
    transaction = _checked_transaction_index(transaction_index)
    value = (block << 32) + transaction + 1
    if value > UINT64_MAX:  # pragma: no cover - protected by coordinate bounds
        raise OverflowError("canonical boundary ordinal exceeds UInt64")
    return value


def boundary_coordinates(
    value: int,
    *,
    # Keep the position schema id input explicit in the boundary coordinates contract.
    position_schema_id: PositionSchemaId,
) -> tuple[int, int]:
    """Decode a UInt64 boundary into ``(block_ordinal, transaction_index)``."""

    _require_supported_schema(position_schema_id)
    ordinal = _checked_uint64(value, "boundary_ordinal")
    block_ordinal = ordinal >> 32
    transaction_index = (ordinal & UINT32_MAX) - 1
    return block_ordinal, transaction_index


# Apply dataclass semantics to the following chain position contract.
@dataclass(frozen=True, slots=True, order=True)
class ChainPosition:
    """Exact event position on one immutable network and position schema."""

    network_id: NetworkId
    position_schema_id: PositionSchemaId
    block_ordinal: int
    transaction_index: int
    event_index: int | None

    # Define chain position post init as one focused operation with an explicit boundary.
    def __post_init__(self) -> None:
        # Execute the chain position post init workflow in explicit, reviewable steps.
        if not isinstance(self.network_id, NetworkId):
            raise TypeError("network_id must be a NetworkId")
        _require_supported_schema(self.position_schema_id)
        boundary_ordinal(
            self.block_ordinal,
            # Pass self explicitly so boundary_ordinal receives a reviewable block ordinal
            # and transaction index input in chain position post init.
            self.transaction_index,
            position_schema_id=self.position_schema_id,
        )
        if self.event_index is not None:
            _checked_uint32(self.event_index, "event_index")

    # Apply classmethod semantics to the following chain position from boundary ordinal
    # contract.
    @classmethod
    def from_boundary_ordinal(
        cls,
        *,
        network_id: NetworkId,
        # Keep the position schema id input explicit in the from boundary ordinal
        # contract.
        position_schema_id: PositionSchemaId,
        boundary_ordinal_value: int,
        event_index: int | None = None,
    ) -> ChainPosition:
        # Execute the chain position from boundary ordinal workflow in explicit,
        # reviewable steps.
        block_ordinal, transaction_index = boundary_coordinates(
            boundary_ordinal_value,
            position_schema_id=position_schema_id,
        )
        return cls(
            # Pass network id explicitly so cls receives a reviewable network id and
            # position schema id input in chain position from boundary ordinal.
            network_id=network_id,
            position_schema_id=position_schema_id,
            block_ordinal=block_ordinal,
            transaction_index=transaction_index,
            event_index=event_index,
            # Complete cls only after its network id and position schema id inputs are visible
            # in chain position from boundary ordinal.
        )

    @property
    def boundary_ordinal(self) -> int:
        # Execute the chain position boundary ordinal workflow in explicit, reviewable
        # steps.
        return boundary_ordinal(
            self.block_ordinal,
            self.transaction_index,
            position_schema_id=self.position_schema_id,
        )

    # Apply property semantics to the following chain position slot contract.
    @property
    def slot(self) -> int:
        """Deprecated read-only bridge for the current Solana adapters."""

        return self.block_ordinal

    @property
    def chain_identity(self) -> tuple[NetworkId, PositionSchemaId]:
        return self.network_id, self.position_schema_id

    def require_same_chain(self, other: ChainPosition) -> None:
        # Execute the chain position require same chain workflow in explicit, reviewable
        # steps.
        if self.chain_identity != other.chain_identity:
            # Handle the chain position require same chain chain identity and other
            # condition as a distinct block.
            raise ChainIdentityMismatchError(
                "chain positions use different network or position schema identities"
            )


def _require_supported_schema(position_schema_id: PositionSchemaId) -> None:
    # Execute the require supported schema workflow in explicit, reviewable steps.
    if not isinstance(position_schema_id, PositionSchemaId):
        raise TypeError("position_schema_id must be a PositionSchemaId")
    if position_schema_id != BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID:
        # Handle the require supported schema position schema id and block32 transaction32
        # position schema id condition as a distinct block.
        raise UnsupportedPositionSchemaError(
            f"unsupported position schema: {position_schema_id.value}"
        )


def _checked_transaction_index(value: int) -> int:
    # Execute the checked transaction index workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("transaction_index must be an integer")
    if value < -1:
        raise ValueError("transaction_index must be -1 or non-negative")
    if value >= UINT32_MAX:
        # Fail the checked transaction index path with OverflowError for transaction index
        # exceeds block32-transaction32-v1 capacity when value and uint32 max is true; do
        # not continue ambiguously.
        raise OverflowError("transaction_index exceeds block32-transaction32-v1 capacity")
    return value


def _checked_uint32(value: int, name: str) -> int:
    # Execute the checked uint32 workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    if value > UINT32_MAX:
        # Fail the checked uint32 path with OverflowError for exceeds uint32 and name when
        # value and uint32 max is true; do not continue ambiguously.
        raise OverflowError(f"{name} exceeds UInt32")
    return value


def _checked_uint64(value: int, name: str) -> int:
    # Execute the checked uint64 workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    if value > UINT64_MAX:
        # Fail the checked uint64 path with OverflowError for exceeds uint64 and name when
        # value and uint64 max is true; do not continue ambiguously.
        raise OverflowError(f"{name} exceeds UInt64")
    return value


__all__ = [
    "BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID",
    "SOLANA_MAINNET_NETWORK_ID",
    # Keep the chain identity mismatch error component named inside the all contract.
    "ChainIdentityMismatchError",
    "ChainPosition",
    "UnsupportedPositionSchemaError",
    "boundary_coordinates",
    "boundary_ordinal",
    # Complete the all group only after its semantic components are visible.
]
