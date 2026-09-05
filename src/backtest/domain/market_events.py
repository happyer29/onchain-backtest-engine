"""Canonical, infrastructure-independent historical event contracts.

The dataclasses are used at preparation, tests and the readable reference
backend. Fast backends represent the same fields as typed arrays and do not
allocate one instance per event in their hot loop.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Any, Final, Literal

# Import chain at the visible module dependency boundary.
from backtest.domain.chain import UINT32_MAX, ChainPosition, boundary_ordinal
from backtest.domain.fidelity import OrderingFidelity
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import (
    AccountId,
    # Include asset id so the identifiers dependency remains explicit.
    AssetId,
    CapabilityId,
    ContentDigest,
    FeeComponentId,
    PoolId,
    # Include protocol payload schema id so the identifiers dependency remains explicit.
    ProtocolPayloadSchemaId,
    VenueId,
)

REFERENCE_AMM_TRADE_PAYLOAD_SCHEMA_ID: Final = ProtocolPayloadSchemaId(
    "reference-amm-trade-payload-v1"
    # Complete ProtocolPayloadSchemaId only after its reference-amm-trade-payload-v1 inputs
    # are visible in module.
)


class EventKind(IntEnum):
    """Stable physical codes shared by canonical snapshots and ReplayPacks."""

    BLOCK = 1
    TOKEN_LAUNCH = 2
    VENUE_TRADE = 3
    LIQUIDITY = 4
    TRANSFER = 5
    # Declare venue lifecycle explicitly in the event kind contract.
    VENUE_LIFECYCLE = 6

    # Read-only source compatibility. New manifests serialize canonical names.
    TOKEN_CREATION = TOKEN_LAUNCH
    SWAP = VENUE_TRADE


# Keep the event kind name contract and validation rules together.
class EventKindName(StrEnum):
    BLOCK = "BLOCK"
    TOKEN_LAUNCH = "TOKEN_LAUNCH"
    VENUE_TRADE = "VENUE_TRADE"
    LIQUIDITY = "LIQUIDITY"
    # Declare transfer explicitly in the event kind name contract.
    TRANSFER = "TRANSFER"
    VENUE_LIFECYCLE = "VENUE_LIFECYCLE"

    TOKEN_CREATION = TOKEN_LAUNCH
    SWAP = VENUE_TRADE


class VenueLifecycleKind(StrEnum):
    """Versioned generic venue lifecycle transition names."""

    COMPLETED = "COMPLETED"
    MIGRATED = "MIGRATED"
    CLOSED = "CLOSED"


def event_kind_name(kind: EventKind) -> EventKindName:
    return EventKindName(kind.name)


# Keep the event envelope contract and validation rules together.
@dataclass(frozen=True, slots=True)
class EventEnvelope:
    position: ChainPosition
    transaction_group_id: ContentDigest
    source_record_id: ContentDigest
    # Declare canonical event id explicitly in the event envelope contract.
    canonical_event_id: ContentDigest
    stable_causal_id: ContentDigest
    capability_id: CapabilityId
    protocol: str
    protocol_version: str
    # Declare ordering fidelity explicitly in the event envelope contract.
    ordering_fidelity: OrderingFidelity

    def __post_init__(self) -> None:
        # Execute the event envelope post init workflow in explicit, reviewable steps.
        if not isinstance(self.position, ChainPosition):
            raise TypeError("position must be a ChainPosition")
        for field_name in ("protocol", "protocol_version"):
            # Process ('protocol', 'protocol_version') inside the bounded event envelope
            # post init loop.
            value = getattr(self, field_name)
            if not value or value != value.strip():
                raise ValueError(f"{field_name} must be non-empty and trimmed")
        if (
            self.ordering_fidelity
            # Evaluate the complete event envelope post init ordering fidelity, event
            # index and transaction exact condition before guarded effects.
            in {
                OrderingFidelity.TRANSACTION_EXACT,
                OrderingFidelity.INSTRUCTION_EXACT,
            }
            and self.position.event_index is None
            # Evaluate the complete event envelope post init ordering fidelity, event index
            # and transaction exact condition before guarded effects.
        ):
            raise ValueError("exact event ordering requires an event_index")

    @property
    def boundary_ordinal(self) -> int:
        return self.position.boundary_ordinal


# Keep the block event contract and validation rules together.
@dataclass(frozen=True, slots=True)
class BlockEvent:
    envelope: EventEnvelope
    block_time_ns: int | None
    tx_count: int | None
    # Declare block hash explicitly in the block event contract.
    block_hash: str | None = None

    def __post_init__(self) -> None:
        # Execute the block event post init workflow in explicit, reviewable steps.
        if not isinstance(self.envelope, EventEnvelope):
            raise TypeError("envelope must be an EventEnvelope")
        if self.envelope.position.transaction_index != -1:
            raise ValueError("block events must use the synthetic block boundary")
        if self.block_time_ns is not None and (
            # Keep isinstance visible while evaluating the block time ns and isinstance
            # guard.
            isinstance(self.block_time_ns, bool) or not isinstance(self.block_time_ns, int)
        ):
            raise TypeError("block_time_ns must be an integer or None")
        if self.tx_count is not None:
            # Handle the block event post init self.tx_count is not None branch as a
            # distinct logical block.
            if isinstance(self.tx_count, bool) or not isinstance(self.tx_count, int):
                raise TypeError("tx_count must be an integer or None")
            if not 0 <= self.tx_count <= UINT32_MAX:
                raise ValueError("tx_count must fit the position schema transaction capacity")

    @property
    # Define block event kind as one focused operation with an explicit boundary.
    def kind(self) -> EventKind:
        return EventKind.BLOCK


# Keep the fee component contract and validation rules together.
@dataclass(frozen=True, slots=True, order=True)
class FeeComponent:
    component_id: FeeComponentId
    asset_id: AssetId
    amount_atomic: int

    # Define fee component post init as one focused operation with an explicit boundary.
    def __post_init__(self) -> None:
        # Execute the fee component post init workflow in explicit, reviewable steps.
        if not isinstance(self.component_id, FeeComponentId):
            raise TypeError("component_id must be a FeeComponentId")
        if not isinstance(self.asset_id, AssetId):
            raise TypeError("asset_id must be an AssetId")
        if (
            # Keep isinstance visible while evaluating the isinstance and amount atomic
            # guard.
            isinstance(self.amount_atomic, bool)
            or not isinstance(self.amount_atomic, int)
            or self.amount_atomic <= 0
        ):
            raise ValueError("fee component amount must be a positive integer")


# Apply dataclass semantics to the following token launch event contract.
@dataclass(frozen=True, slots=True)
class TokenLaunchEvent:
    """A launch whose containing chain transaction succeeded.

    Failed or unknown-status creation instructions are source evidence, not
    canonical launch events. Source/projector boundaries must reject them
    instead of silently changing the strategy target universe.
    """

    envelope: EventEnvelope
    asset_id: AssetId
    developer_id: AccountId
    creation_user_id: AccountId
    venue_id: VenueId
    # Declare quote asset id explicitly in the token launch event contract.
    quote_asset_id: AssetId
    protocol_payload_schema: ProtocolPayloadSchemaId
    protocol_payload: bytes
    decimals: int | None = None

    def __post_init__(self) -> None:
        # Execute the token launch event post init workflow in explicit, reviewable steps.
        if not isinstance(self.envelope, EventEnvelope):
            raise TypeError("envelope must be an EventEnvelope")
        for field_name, expected_type in (
            ("asset_id", AssetId),
            ("developer_id", AccountId),
            # Traverse asset id, developer id and account id explicitly so each token
            # launch event post init iteration remains traceable.
            ("creation_user_id", AccountId),
            ("venue_id", VenueId),
            ("quote_asset_id", AssetId),
        ):
            # Process asset id, developer id and account id inside the bounded token
            # launch event post init loop.
            if not isinstance(getattr(self, field_name), expected_type):
                raise TypeError(f"{field_name} must be a {expected_type.__name__}")
        _validate_protocol_payload(self.protocol_payload_schema, self.protocol_payload)
        if self.asset_id == self.quote_asset_id:
            raise ValueError("launched and quote assets must be different")
        # Evaluate the complete token launch event post init decimals and isinstance
        # condition before guarded effects.
        if self.decimals is not None and (
            isinstance(self.decimals, bool)
            or not isinstance(self.decimals, int)
            or not 0 <= self.decimals <= 38
        ):
            # Fail the token launch event post init path with ValueError for decimals must
            # be between 0 and 38 or none when decimals and isinstance is true; do not
            # continue ambiguously.
            raise ValueError("decimals must be between 0 and 38 or None")

    @property
    def kind(self) -> EventKind:
        return EventKind.TOKEN_LAUNCH

    @property
    # Define token launch event transaction succeeded as one focused operation with an
    # explicit boundary.
    def transaction_succeeded(self) -> Literal[True]:
        """Expose the type-level invariant without another stored column."""

        return True

    @property
    def creator_id(self) -> AccountId:
        """Deprecated FirstSwap bridge; new code uses ``developer_id``."""

        return self.developer_id


# Keep the venue trade event contract and validation rules together.
@dataclass(frozen=True, slots=True)
class VenueTradeEvent:
    envelope: EventEnvelope
    venue_id: VenueId
    sold_asset_id: AssetId
    # Declare bought asset id explicitly in the venue trade event contract.
    bought_asset_id: AssetId
    sold_amount_atomic: int
    bought_amount_atomic: int
    fee_components: tuple[FeeComponent, ...]
    protocol_payload_schema: ProtocolPayloadSchemaId
    # Declare protocol payload explicitly in the venue trade event contract.
    protocol_payload: bytes

    def __post_init__(self) -> None:
        # Execute the venue trade event post init workflow in explicit, reviewable steps.
        if not isinstance(self.envelope, EventEnvelope):
            raise TypeError("envelope must be an EventEnvelope")
        for field_name, expected_type in (
            ("venue_id", VenueId),
            ("sold_asset_id", AssetId),
            # Traverse venue id, sold asset id and asset id explicitly so each venue trade
            # event post init iteration remains traceable.
            ("bought_asset_id", AssetId),
        ):
            # Process venue id, sold asset id and asset id inside the bounded venue trade
            # event post init loop.
            if not isinstance(getattr(self, field_name), expected_type):
                raise TypeError(f"{field_name} must be a {expected_type.__name__}")
        if self.sold_asset_id == self.bought_asset_id:
            raise ValueError("a venue trade must exchange two different assets")
        for field_name in ("sold_amount_atomic", "bought_amount_atomic"):
            # Historical protocol transitions may contain an exact zero-output dust leg.
            # Simulated quotes and fills keep their separate strictly-positive contracts.
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.sold_amount_atomic == 0 and self.bought_amount_atomic == 0:
            raise ValueError("a venue trade must have at least one positive amount")
        if not isinstance(self.fee_components, tuple) or any(
            not isinstance(component, FeeComponent)
            # Pass component explicitly so any receives a reviewable fee components and
            # isinstance input in venue trade event post init.
            for component in self.fee_components
            # Complete any only after its fee components and isinstance inputs are visible in
            # venue trade event post init.
        ):
            raise TypeError("fee_components must be a tuple of FeeComponent values")
        keys = tuple(
            (component.component_id.value, component.asset_id.value)
            for component in self.fee_components
            # Complete tuple only after its value and fee components inputs are visible in
            # venue trade event post init.
        )
        if len(set(keys)) != len(keys):
            raise ValueError("fee components must have unique component/asset identities")
        if keys != tuple(sorted(keys)):
            raise ValueError("fee components must use canonical component/asset order")
        # Invoke _validate_protocol_payload for protocol payload schema and protocol
        # payload as a visible venue trade event post init step.
        _validate_protocol_payload(self.protocol_payload_schema, self.protocol_payload)

    @property
    def kind(self) -> EventKind:
        return EventKind.VENUE_TRADE

    @property
    # Define venue trade event pool id as one focused operation with an explicit boundary.
    def pool_id(self) -> PoolId:
        # Execute the venue trade event pool id workflow in explicit, reviewable steps.
        self._reference_amm_payload()
        return PoolId(self.venue_id.value)

    @property
    def fee_amount_atomic(self) -> int:
        # Execute the venue trade event fee amount atomic workflow in explicit, reviewable
        # steps.
        self._reference_amm_payload()
        if any(component.asset_id != self.sold_asset_id for component in self.fee_components):
            raise ValueError("legacy aggregate fee requires sold-asset fee components")
        return sum(component.amount_atomic for component in self.fee_components)

    @property
    # Define venue trade event pool asset a id as one focused operation with an explicit
    # boundary.
    def pool_asset_a_id(self) -> AssetId:
        return AssetId(_payload_string(self._reference_amm_payload(), "asset_a_id"))

    @property
    def pool_asset_b_id(self) -> AssetId:
        return AssetId(_payload_string(self._reference_amm_payload(), "asset_b_id"))

    # Apply property semantics to the following venue trade event reserve a after atomic
    # contract.
    @property
    def reserve_a_after_atomic(self) -> int | None:
        return _payload_optional_integer(self._reference_amm_payload(), "reserve_a_after_atomic")

    @property
    def reserve_b_after_atomic(self) -> int | None:
        # Return the completed venue trade event reserve b after atomic result without a
        # hidden fallback.
        return _payload_optional_integer(self._reference_amm_payload(), "reserve_b_after_atomic")

    def _reference_amm_payload(self) -> dict[str, object]:
        # Execute the venue trade event reference amm payload workflow in explicit,
        # reviewable steps.
        if self.protocol_payload_schema != REFERENCE_AMM_TRADE_PAYLOAD_SCHEMA_ID:
            raise ValueError("legacy pool view requires reference AMM payload schema")
        expected_keys = {
            "asset_a_id",
            "asset_b_id",
            # Keep the reserve a after atomic component named inside the expected keys
            # contract.
            "reserve_a_after_atomic",
            "reserve_b_after_atomic",
        }
        try:
            value: Any = json.loads(self.protocol_payload)
        # Translate type error through the venue trade event reference amm payload
        # boundary without hiding other errors.
        except (TypeError, ValueError, UnicodeDecodeError) as error:
            raise ValueError("reference AMM payload is not canonical JSON") from error
        if not isinstance(value, dict) or set(value) != expected_keys:
            raise ValueError("reference AMM payload fields are invalid")
        if canonical_json_bytes(value) != self.protocol_payload:
            # Fail the venue trade event reference amm payload path with ValueError for
            # reference amm payload bytes are not canonical when protocol payload,
            # canonical json bytes and value is true; do not continue ambiguously.
            raise ValueError("reference AMM payload bytes are not canonical")
        asset_a = _payload_string(value, "asset_a_id")
        asset_b = _payload_string(value, "asset_b_id")
        if AssetId(asset_a) == AssetId(asset_b):
            raise ValueError("reference AMM payload assets must be different")
        # Assemble reserve a once so the venue trade event reference amm payload workflow
        # shares one value.
        reserve_a = _payload_optional_integer(value, "reserve_a_after_atomic")
        reserve_b = _payload_optional_integer(value, "reserve_b_after_atomic")
        if (reserve_a is None) != (reserve_b is None):
            raise ValueError("reference AMM reserves must both be present or absent")
        return value


# Keep the venue lifecycle event contract and validation rules together.
@dataclass(frozen=True, slots=True)
class VenueLifecycleEvent:
    envelope: EventEnvelope
    venue_id: VenueId
    lifecycle_kind: VenueLifecycleKind
    # Declare protocol payload schema explicitly in the venue lifecycle event contract.
    protocol_payload_schema: ProtocolPayloadSchemaId
    protocol_payload: bytes

    def __post_init__(self) -> None:
        # Execute the venue lifecycle event post init workflow in explicit, reviewable
        # steps.
        if not isinstance(self.envelope, EventEnvelope):
            raise TypeError("envelope must be an EventEnvelope")
        if not isinstance(self.venue_id, VenueId):
            raise TypeError("venue_id must be a VenueId")
        if not isinstance(self.lifecycle_kind, VenueLifecycleKind):
            # Fail the venue lifecycle event post init path with TypeError for lifecycle
            # kind must be a venue lifecycle kind when isinstance, lifecycle kind and
            # venue lifecycle kind is true; do not continue ambiguously.
            raise TypeError("lifecycle_kind must be a VenueLifecycleKind")
        _validate_protocol_payload(self.protocol_payload_schema, self.protocol_payload)

    @property
    def kind(self) -> EventKind:
        return EventKind.VENUE_LIFECYCLE


# Define reference amm trade payload as one focused operation with an explicit boundary.
def reference_amm_trade_payload(
    *,
    asset_a_id: AssetId,
    asset_b_id: AssetId,
    reserve_a_after_atomic: int | None,
    # Keep the reserve b after atomic input explicit in the reference amm trade payload
    # contract.
    reserve_b_after_atomic: int | None,
) -> bytes:
    """Build the temporary exact payload used by the checked-in reference AMM."""

    if asset_a_id == asset_b_id:
        raise ValueError("reference AMM payload assets must be different")
    for name, value in (
        ("reserve_a_after_atomic", reserve_a_after_atomic),
        ("reserve_b_after_atomic", reserve_b_after_atomic),
        # Traverse reserve a after atomic and reserve b after atomic explicitly so each
        # reference amm trade payload iteration remains traceable.
    ):
        # Process reserve a after atomic and reserve b after atomic inside the bounded
        # reference amm trade payload loop.
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise ValueError(f"{name} must be a non-negative integer or None")
    if (reserve_a_after_atomic is None) != (reserve_b_after_atomic is None):
        # Fail the reference amm trade payload path with ValueError for reference amm
        # reserves must both be present or absent when reserve a after atomic and reserve
        # b after atomic is true; do not continue ambiguously.
        raise ValueError("reference AMM reserves must both be present or absent")
    return canonical_json_bytes(
        {
            "asset_a_id": asset_a_id.value,
            "asset_b_id": asset_b_id.value,
            # Keep reserve a after atomic named so the asset a id and asset b id payload
            # passed to canonical_json_bytes remains self-describing within reference amm
            # trade payload.
            "reserve_a_after_atomic": reserve_a_after_atomic,
            "reserve_b_after_atomic": reserve_b_after_atomic,
        }
    )


# Temporary source-level aliases. They name the generic contracts and never
# create a legacy serialization branch.
TokenCreationEvent = TokenLaunchEvent
SwapEvent = VenueTradeEvent

CanonicalEvent = BlockEvent | TokenLaunchEvent | VenueTradeEvent | VenueLifecycleEvent


def canonical_event_sort_key(event: CanonicalEvent) -> tuple[str, str, int, str, int, str]:
    """Total physical order that never upgrades declared source fidelity."""

    event_index = event.envelope.position.event_index
    return (
        event.envelope.position.network_id.value,
        event.envelope.position.position_schema_id.value,
        event.envelope.boundary_ordinal,
        # Include event in the completed canonical event sort key result.
        event.envelope.transaction_group_id.hex,
        -1 if event_index is None else event_index,
        event.envelope.stable_causal_id.hex,
    )


def _validate_protocol_payload(
    # Keep the schema input explicit in the validate protocol payload contract.
    schema: ProtocolPayloadSchemaId,
    payload: bytes,
) -> None:
    # Execute the validate protocol payload workflow in explicit, reviewable steps.
    if not isinstance(schema, ProtocolPayloadSchemaId):
        raise TypeError("protocol_payload_schema must be a ProtocolPayloadSchemaId")
    if not isinstance(payload, bytes):
        raise TypeError("protocol_payload must be immutable bytes")


def _payload_string(value: dict[str, object], field: str) -> str:
    # Execute the payload string workflow in explicit, reviewable steps.
    item = value.get(field)
    if not isinstance(item, str):
        raise ValueError(f"reference AMM payload {field} must be a string")
    return item


def _payload_optional_integer(value: dict[str, object], field: str) -> int | None:
    # Execute the payload optional integer workflow in explicit, reviewable steps.
    item = value.get(field)
    if item is None:
        return None
    if isinstance(item, bool) or not isinstance(item, int) or item < 0:
        raise ValueError(f"reference AMM payload {field} must be non-negative or null")
    # Return the completed payload optional integer result without a hidden fallback.
    return item


__all__ = [
    "REFERENCE_AMM_TRADE_PAYLOAD_SCHEMA_ID",
    "BlockEvent",
    "CanonicalEvent",
    # Keep the chain position component named inside the all contract.
    "ChainPosition",
    "EventEnvelope",
    "EventKind",
    "EventKindName",
    "FeeComponent",
    # Keep the swap event component named inside the all contract.
    "SwapEvent",
    "TokenCreationEvent",
    "TokenLaunchEvent",
    "VenueLifecycleEvent",
    "VenueLifecycleKind",
    # Keep the venue trade event component named inside the all contract.
    "VenueTradeEvent",
    "boundary_ordinal",
    "canonical_event_sort_key",
    "event_kind_name",
    "reference_amm_trade_payload",
    # Complete the all group only after its semantic components are visible.
]
