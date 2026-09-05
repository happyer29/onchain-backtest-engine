"""Canonical semantic hashes shared by every historical-event representation."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import ContentDigest, LogicalContentHash

# Import market events at the visible module dependency boundary.
from backtest.domain.market_events import (
    BlockEvent,
    CanonicalEvent,
    TokenLaunchEvent,
    VenueLifecycleEvent,
    # Include venue trade event so the market events dependency remains explicit.
    VenueTradeEvent,
)

_LOGICAL_STREAM_DOMAIN = b"backtest.canonical-logical-stream.v3\x00"


def canonical_event_document(event: CanonicalEvent) -> dict[str, object]:
    """Return the versioned, representation-independent event projection."""

    envelope = event.envelope
    value: dict[str, object] = {
        "boundary_ordinal": envelope.boundary_ordinal,
        "block_ordinal": envelope.position.block_ordinal,
        "canonical_event_id": envelope.canonical_event_id.hex,
        # Keep the capability id component named inside the value contract.
        "capability_id": envelope.capability_id.value,
        "event_index": envelope.position.event_index,
        "event_kind": event.kind.name,
        "network_id": envelope.position.network_id.value,
        "ordering_fidelity": envelope.ordering_fidelity.value,
        # Keep the position schema id component named inside the value contract.
        "position_schema_id": envelope.position.position_schema_id.value,
        "protocol": envelope.protocol,
        "protocol_version": envelope.protocol_version,
        "source_record_id": envelope.source_record_id.hex,
        "stable_causal_id": envelope.stable_causal_id.hex,
        # Keep the transaction group id component named inside the value contract.
        "transaction_group_id": envelope.transaction_group_id.hex,
        "transaction_index": envelope.position.transaction_index,
    }
    if isinstance(event, BlockEvent):
        # Handle the canonical event document isinstance(event, BlockEvent) branch as a
        # distinct logical block.
        value["payload"] = {
            "block_hash": event.block_hash,
            "block_time_ns": event.block_time_ns,
            "tx_count": event.tx_count,
        }
    # Handle the canonical event document complement of isinstance(event, BlockEvent)
    # explicitly.
    elif isinstance(event, TokenLaunchEvent):
        # Handle the canonical event document isinstance(event, TokenLaunchEvent) branch
        # as a distinct logical block.
        value["payload"] = {
            "asset_id": event.asset_id.value,
            "creation_user_id": event.creation_user_id.value,
            "decimals": event.decimals,
            "developer_id": event.developer_id.value,
            # Register hex and protocol payload through hex so the value['payload'] table
            # remains scannable.
            "protocol_payload": event.protocol_payload.hex(),
            "protocol_payload_schema": event.protocol_payload_schema.value,
            "quote_asset_id": event.quote_asset_id.value,
            "venue_id": event.venue_id.value,
        }
    # Handle the canonical event document complement of isinstance(event,
    # TokenLaunchEvent) explicitly.
    elif isinstance(event, VenueTradeEvent):
        # Handle the canonical event document isinstance(event, VenueTradeEvent) branch as
        # a distinct logical block.
        value["payload"] = {
            "bought_amount_atomic": event.bought_amount_atomic,
            "bought_asset_id": event.bought_asset_id.value,
            "fee_components": [
                {
                    # Keep the amount atomic component named inside the value['payload']
                    # contract.
                    "amount_atomic": component.amount_atomic,
                    "asset_id": component.asset_id.value,
                    "component_id": component.component_id.value,
                }
                for component in event.fee_components
                # Complete the value['payload'] group only after its semantic components are
                # visible.
            ],
            "protocol_payload": event.protocol_payload.hex(),
            "protocol_payload_schema": event.protocol_payload_schema.value,
            "sold_amount_atomic": event.sold_amount_atomic,
            "sold_asset_id": event.sold_asset_id.value,
            # Keep the venue id component named inside the value['payload'] contract.
            "venue_id": event.venue_id.value,
        }
    # Handle the canonical event document complement of isinstance(event, VenueTradeEvent)
    # explicitly.
    elif isinstance(event, VenueLifecycleEvent):
        # Handle the canonical event document isinstance(event, VenueLifecycleEvent)
        # branch as a distinct logical block.
        value["payload"] = {
            "lifecycle_kind": event.lifecycle_kind.value,
            "protocol_payload": event.protocol_payload.hex(),
            "protocol_payload_schema": event.protocol_payload_schema.value,
            "venue_id": event.venue_id.value,
            # Complete the value['payload'] group only after its semantic components are
            # visible.
        }
    else:  # pragma: no cover - CanonicalEvent is an exhaustive closed union
        raise TypeError(f"unsupported canonical event: {type(event).__name__}")
    return value


def canonical_event_digest(event: CanonicalEvent) -> ContentDigest:
    """Hash one logical event independently of Parquet or ReplayPack bytes."""

    return domain_digest("backtest.canonical-logical-row.v3", canonical_event_document(event))


class CanonicalEventStreamHasher:
    """Incremental hash for the exact ordered canonical logical stream."""

    def __init__(self) -> None:
        self._digest = hashlib.sha256(_LOGICAL_STREAM_DOMAIN)

    def update(self, event: CanonicalEvent) -> None:
        self._digest.update(bytes.fromhex(canonical_event_digest(event).hex))

    def logical_content_hash(self) -> LogicalContentHash:
        # Return the completed canonical event stream hasher logical content hash result
        # without a hidden fallback.
        return LogicalContentHash(self._digest.hexdigest())


def canonical_event_stream_hash(events: Iterable[CanonicalEvent]) -> LogicalContentHash:
    # Execute the canonical event stream hash workflow in explicit, reviewable steps.
    hasher = CanonicalEventStreamHasher()
    for event in events:
        hasher.update(event)
    return hasher.logical_content_hash()


__all__ = [
    # Keep the canonical event stream hasher component named inside the all contract.
    "CanonicalEventStreamHasher",
    "canonical_event_digest",
    "canonical_event_document",
    "canonical_event_stream_hash",
]
