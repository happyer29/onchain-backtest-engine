"""Exact physical schema for the network-aware NumPy mmap ReplayPack v3."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from backtest.application.replay_packs import (
    # Include replay array layout so the replay packs dependency remains explicit.
    ReplayArrayLayout,
    ReplayDictionaryLayout,
    ReplayLayoutManifest,
)

UINT32_MAX: Final = (1 << 32) - 1
# Bind compiler version once as an explicit module-level contract.
COMPILER_VERSION: Final = "numpy-mmap-v3"

DICTIONARY_NAMES: Final = (
    "accounts",
    "assets",
    "block_hashes",
    # Keep the capabilities component named inside the dictionary names contract.
    "capabilities",
    "fee_component_ids",
    "protocol_payload_schemas",
    "protocol_versions",
    "protocols",
    # Keep the venues component named inside the dictionary names contract.
    "venues",
)

CLOCK_BLOCK_ORDINAL: Final = "clock/block_ordinal.npy"
CLOCK_TRANSACTION_COUNT: Final = "clock/transaction_count.npy"
CLOCK_CUMULATIVE_TRANSACTION_PREFIX: Final = "clock/cumulative_transaction_prefix.npy"
# Bind clock block time ns once as an explicit module-level contract.
CLOCK_BLOCK_TIME_NS: Final = "clock/block_time_ns.npy"
CLOCK_BLOCK_HASH_CODE: Final = "clock/block_hash_code.npy"
CLOCK_BLOCK_HASH_VALID: Final = "clock/block_hash_code.validity.npy"

BOUNDARY_ORDINAL: Final = "boundaries/boundary_ordinal.npy"
BOUNDARY_BLOCK_ORDINAL: Final = "boundaries/block_ordinal.npy"
# Bind group offsets once as an explicit module-level contract.
GROUP_OFFSETS: Final = "indexes/group_offsets.npy"
BOUNDARY_OFFSETS: Final = "indexes/boundary_offsets.npy"

ENVELOPE_BOUNDARY_ORDINAL: Final = "envelopes/boundary_ordinal.npy"
ENVELOPE_BLOCK_ORDINAL: Final = "envelopes/block_ordinal.npy"
ENVELOPE_TRANSACTION_INDEX: Final = "envelopes/transaction_index.npy"
# Bind envelope event index once as an explicit module-level contract.
ENVELOPE_EVENT_INDEX: Final = "envelopes/event_index.npy"
ENVELOPE_EVENT_INDEX_VALID: Final = "envelopes/event_index.validity.npy"
ENVELOPE_TRANSACTION_GROUP_ID: Final = "envelopes/transaction_group_id.npy"
ENVELOPE_SOURCE_RECORD_ID: Final = "envelopes/source_record_id.npy"
ENVELOPE_CANONICAL_EVENT_ID: Final = "envelopes/canonical_event_id.npy"
# Bind envelope stable causal id once as an explicit module-level contract.
ENVELOPE_STABLE_CAUSAL_ID: Final = "envelopes/stable_causal_id.npy"
ENVELOPE_CAPABILITY_CODE: Final = "envelopes/capability_code.npy"
ENVELOPE_PROTOCOL_CODE: Final = "envelopes/protocol_code.npy"
ENVELOPE_PROTOCOL_VERSION_CODE: Final = "envelopes/protocol_version_code.npy"
ENVELOPE_ORDERING_FIDELITY_CODE: Final = "envelopes/ordering_fidelity_code.npy"
# Bind envelope event kind code once as an explicit module-level contract.
ENVELOPE_EVENT_KIND_CODE: Final = "envelopes/event_kind_code.npy"
ENVELOPE_PAYLOAD_INDEX: Final = "envelopes/payload_index.npy"
ENVELOPE_PROTOCOL_PAYLOAD_SCHEMA_CODE: Final = "envelopes/protocol_payload_schema_code.npy"
ENVELOPE_PROTOCOL_PAYLOAD_SCHEMA_VALID: Final = (
    "envelopes/protocol_payload_schema_code.validity.npy"
    # Complete the envelope protocol payload schema valid group only after its semantic
    # components are visible.
)
ENVELOPE_PROTOCOL_PAYLOAD_OFFSETS: Final = "envelopes/protocol_payload_offsets.npy"
ENVELOPE_PROTOCOL_PAYLOAD_BYTES: Final = "envelopes/protocol_payload_bytes.npy"

TOKEN_ASSET_CODE: Final = "payloads/token_launches/asset_code.npy"
TOKEN_DEVELOPER_CODE: Final = "payloads/token_launches/developer_code.npy"
# Bind token creation user code once as an explicit module-level contract.
TOKEN_CREATION_USER_CODE: Final = "payloads/token_launches/creation_user_code.npy"
TOKEN_VENUE_CODE: Final = "payloads/token_launches/venue_code.npy"
TOKEN_QUOTE_ASSET_CODE: Final = "payloads/token_launches/quote_asset_code.npy"
TOKEN_DECIMALS: Final = "payloads/token_launches/decimals.npy"
TOKEN_DECIMALS_VALID: Final = "payloads/token_launches/decimals.validity.npy"

# Bind trade venue code once as an explicit module-level contract.
TRADE_VENUE_CODE: Final = "payloads/venue_trades/venue_code.npy"
TRADE_SOLD_ASSET_CODE: Final = "payloads/venue_trades/sold_asset_code.npy"
TRADE_BOUGHT_ASSET_CODE: Final = "payloads/venue_trades/bought_asset_code.npy"
TRADE_SOLD_AMOUNT: Final = "payloads/venue_trades/sold_amount_atomic.npy"
TRADE_BOUGHT_AMOUNT: Final = "payloads/venue_trades/bought_amount_atomic.npy"
# Bind trade fee offsets once as an explicit module-level contract.
TRADE_FEE_OFFSETS: Final = "payloads/venue_trades/fee_offsets.npy"
TRADE_FEE_COMPONENT_CODE: Final = "payloads/venue_trades/fees/component_code.npy"
TRADE_FEE_ASSET_CODE: Final = "payloads/venue_trades/fees/asset_code.npy"
TRADE_FEE_AMOUNT: Final = "payloads/venue_trades/fees/amount_atomic.npy"

LIFECYCLE_VENUE_CODE: Final = "payloads/venue_lifecycles/venue_code.npy"
# Bind lifecycle kind code once as an explicit module-level contract.
LIFECYCLE_KIND_CODE: Final = "payloads/venue_lifecycles/lifecycle_kind_code.npy"

# Protocol-owned acceleration for the existing FirstSwap backend. The exact
# generic payload bytes above remain authoritative and are always retained.
REFERENCE_AMM_VALID: Final = "payloads/venue_trades/reference_amm.validity.npy"
REFERENCE_AMM_ASSET_A_CODE: Final = "payloads/venue_trades/reference_amm/asset_a_code.npy"
REFERENCE_AMM_ASSET_B_CODE: Final = "payloads/venue_trades/reference_amm/asset_b_code.npy"
REFERENCE_AMM_RESERVE_A: Final = "payloads/venue_trades/reference_amm/reserve_a_atomic.npy"
REFERENCE_AMM_RESERVE_A_VALID: Final = (
    # Keep the payloads venue trades reference amm reserve a atomic component named inside
    # the reference amm reserve a valid contract.
    "payloads/venue_trades/reference_amm/reserve_a_atomic.validity.npy"
)
REFERENCE_AMM_RESERVE_B: Final = "payloads/venue_trades/reference_amm/reserve_b_atomic.npy"
REFERENCE_AMM_RESERVE_B_VALID: Final = (
    "payloads/venue_trades/reference_amm/reserve_b_atomic.validity.npy"
    # Complete the reference amm reserve b valid group only after its semantic components are
    # visible.
)
REFERENCE_AMM_TOTAL_FEE: Final = "payloads/venue_trades/reference_amm/total_fee_atomic.npy"


# Keep the replay layout counts contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ReplayLayoutCounts:
    events: int
    boundaries: int
    groups: int
    # Declare blocks explicitly in the replay layout counts contract.
    blocks: int
    token_launches: int
    venue_trades: int
    venue_lifecycles: int
    fee_components: int
    # Declare protocol payload bytes explicitly in the replay layout counts contract.
    protocol_payload_bytes: int

    def cardinality(self, name: str) -> int:
        # Execute the replay layout counts cardinality workflow in explicit, reviewable
        # steps.
        values = {
            "events": self.events,
            "event_bitmap": _bitmap_size(self.events),
            "event_offsets": self.events + 1,
            "protocol_payload_bytes": self.protocol_payload_bytes,
            # Keep the boundaries component named inside the values contract.
            "boundaries": self.boundaries,
            "boundary_offsets": self.boundaries + 1,
            "group_offsets": self.groups + 1,
            "blocks": self.blocks,
            "block_bitmap": _bitmap_size(self.blocks),
            # Keep the token launches component named inside the values contract.
            "token_launches": self.token_launches,
            "token_bitmap": _bitmap_size(self.token_launches),
            "venue_trades": self.venue_trades,
            "trade_bitmap": _bitmap_size(self.venue_trades),
            "trade_offsets": self.venue_trades + 1,
            # Keep the venue lifecycles component named inside the values contract.
            "venue_lifecycles": self.venue_lifecycles,
            "fee_components": self.fee_components,
        }
        try:
            return values[name]
        except KeyError as error:  # pragma: no cover - module-owned templates
            raise AssertionError(f"unknown ReplayPack cardinality {name}") from error


# Keep the array template contract and validation rules together.
@dataclass(frozen=True, slots=True)
class _ArrayTemplate:
    path: str
    dtype: str
    byte_order: str
    # Declare cardinality explicitly in the array template contract.
    cardinality: str
    role: str
    overflow_policy: str
    validity_path: str | None = None


def _array(
    # Keep the path input explicit in the array contract.
    path: str,
    dtype: str,
    cardinality: str,
    role: str,
    overflow_policy: str,
    # Keep the validity path input explicit in the array contract.
    validity_path: str | None = None,
    *,
    byte_order: str = "little",
) -> _ArrayTemplate:
    # Execute the array workflow in explicit, reviewable steps.
    return _ArrayTemplate(
        path,
        dtype,
        byte_order,
        cardinality,
        # Pass role explicitly so _ArrayTemplate receives a reviewable path and dtype
        # input in array.
        role,
        overflow_policy,
        validity_path,
    )


_ARRAY_TEMPLATES: Final = (
    # Register clock block ordinal through _array so the array templates table remains
    # scannable.
    _array(CLOCK_BLOCK_ORDINAL, "<u4", "blocks", "clock.block_ordinal", "checked-uint32-v1"),
    _array(
        CLOCK_TRANSACTION_COUNT, "<u4", "blocks", "clock.transaction_count", "checked-uint32-v1"
    ),
    _array(
        # Pass clock cumulative transaction prefix explicitly so _array receives a
        # reviewable <u8 and blocks input in module.
        CLOCK_CUMULATIVE_TRANSACTION_PREFIX,
        "<u8",
        "blocks",
        "clock.cumulative_transaction_prefix",
        "checked-uint64-prefix-v1",
        # Complete _array only after its <u8 and blocks inputs are visible in module.
    ),
    _array(CLOCK_BLOCK_TIME_NS, "<i8", "blocks", "clock.block_time_ns", "checked-int64-v1"),
    _array(
        CLOCK_BLOCK_HASH_CODE,
        "<u4",
        # Pass blocks explicitly so _array receives a reviewable <u4 and blocks input in
        # module.
        "blocks",
        "clock.block_hash_code",
        "checked-uint32-dictionary-code-v1",
        CLOCK_BLOCK_HASH_VALID,
    ),
    # Register clock block hash valid through _array so the array templates table remains
    # scannable.
    _array(
        CLOCK_BLOCK_HASH_VALID,
        "|u1",
        "block_bitmap",
        "validity.clock.block_hash",
        # Pass packed-validity-bits-v1 explicitly so _array receives a reviewable |u1 and
        # block bitmap input in module.
        "packed-validity-bits-v1",
        byte_order="not-applicable",
    ),
    _array(BOUNDARY_ORDINAL, "<u8", "boundaries", "boundary.ordinal", "checked-uint64-v1"),
    _array(
        # Pass boundary block ordinal explicitly so _array receives a reviewable <u4 and
        # boundaries input in module.
        BOUNDARY_BLOCK_ORDINAL,
        "<u4",
        "boundaries",
        "boundary.block_ordinal",
        "checked-uint32-v1",
        # Complete _array only after its <u4 and boundaries inputs are visible in module.
    ),
    _array(
        ENVELOPE_BOUNDARY_ORDINAL, "<u8", "events", "envelope.boundary_ordinal", "checked-uint64-v1"
    ),
    # Register envelope block ordinal through _array so the array templates table remains
    # scannable.
    _array(ENVELOPE_BLOCK_ORDINAL, "<u4", "events", "envelope.block_ordinal", "checked-uint32-v1"),
    _array(
        ENVELOPE_TRANSACTION_INDEX,
        "<i8",
        "events",
        # Pass transaction index explicitly so _array receives a reviewable <i8 and events
        # input in module.
        "envelope.transaction_index",
        "checked-block32-transaction-index-v1",
    ),
    _array(
        ENVELOPE_EVENT_INDEX,
        # Pass u4 explicitly so _array receives a reviewable <u4 and events input in
        # module.
        "<u4",
        "events",
        "envelope.event_index",
        "checked-uint32-v1",
        ENVELOPE_EVENT_INDEX_VALID,
        # Complete _array only after its <u4 and events inputs are visible in module.
    ),
    _array(
        ENVELOPE_EVENT_INDEX_VALID,
        "|u1",
        "event_bitmap",
        # Pass event index explicitly so _array receives a reviewable |u1 and event bitmap
        # input in module.
        "validity.envelope.event_index",
        "packed-validity-bits-v1",
        byte_order="not-applicable",
    ),
    _array(
        # Pass envelope transaction group id explicitly so _array receives a reviewable
        # |v32 and events input in module.
        ENVELOPE_TRANSACTION_GROUP_ID,
        "|V32",
        "events",
        "envelope.transaction_group_id",
        "fixed-sha256-bytes-v1",
        # Pass byte order explicitly so _array receives a reviewable |v32 and events input
        # in module.
        byte_order="not-applicable",
    ),
    _array(
        ENVELOPE_SOURCE_RECORD_ID,
        "|V32",
        # Pass events explicitly so _array receives a reviewable |v32 and events input in
        # module.
        "events",
        "envelope.source_record_id",
        "fixed-sha256-bytes-v1",
        byte_order="not-applicable",
    ),
    # Register envelope canonical event id through _array so the array templates table
    # remains scannable.
    _array(
        ENVELOPE_CANONICAL_EVENT_ID,
        "|V32",
        "events",
        "envelope.canonical_event_id",
        # Pass fixed-sha256-bytes-v1 explicitly so _array receives a reviewable |v32 and
        # events input in module.
        "fixed-sha256-bytes-v1",
        byte_order="not-applicable",
    ),
    _array(
        ENVELOPE_STABLE_CAUSAL_ID,
        # Pass v32 explicitly so _array receives a reviewable |v32 and events input in
        # module.
        "|V32",
        "events",
        "envelope.stable_causal_id",
        "fixed-sha256-bytes-v1",
        byte_order="not-applicable",
        # Complete _array only after its |v32 and events inputs are visible in module.
    ),
    _array(
        ENVELOPE_CAPABILITY_CODE,
        "<u4",
        "events",
        # Pass capability code explicitly so _array receives a reviewable <u4 and events
        # input in module.
        "envelope.capability_code",
        "checked-uint32-dictionary-code-v1",
    ),
    _array(
        ENVELOPE_PROTOCOL_CODE,
        # Pass u4 explicitly so _array receives a reviewable <u4 and events input in
        # module.
        "<u4",
        "events",
        "envelope.protocol_code",
        "checked-uint32-dictionary-code-v1",
    ),
    # Register envelope protocol version code through _array so the array templates table
    # remains scannable.
    _array(
        ENVELOPE_PROTOCOL_VERSION_CODE,
        "<u4",
        "events",
        "envelope.protocol_version_code",
        # Pass checked-uint32-dictionary-code-v1 explicitly so _array receives a
        # reviewable <u4 and events input in module.
        "checked-uint32-dictionary-code-v1",
    ),
    _array(
        ENVELOPE_ORDERING_FIDELITY_CODE,
        "|u1",
        # Pass events explicitly so _array receives a reviewable |u1 and events input in
        # module.
        "events",
        "envelope.ordering_fidelity_code",
        "stable-fidelity-uint8-v1",
        byte_order="not-applicable",
    ),
    # Register envelope event kind code through _array so the array templates table
    # remains scannable.
    _array(
        ENVELOPE_EVENT_KIND_CODE,
        "|u1",
        "events",
        "envelope.event_kind_code",
        # Pass stable-generic-event-kind-uint8-v1 explicitly so _array receives a
        # reviewable |u1 and events input in module.
        "stable-generic-event-kind-uint8-v1",
        byte_order="not-applicable",
    ),
    _array(ENVELOPE_PAYLOAD_INDEX, "<u8", "events", "envelope.payload_index", "checked-uint64-v1"),
    _array(
        # Pass envelope protocol payload schema code explicitly so _array receives a
        # reviewable <u4 and events input in module.
        ENVELOPE_PROTOCOL_PAYLOAD_SCHEMA_CODE,
        "<u4",
        "events",
        "envelope.protocol_payload_schema_code",
        "checked-uint32-dictionary-code-v1",
        # Pass envelope protocol payload schema valid explicitly so _array receives a
        # reviewable <u4 and events input in module.
        ENVELOPE_PROTOCOL_PAYLOAD_SCHEMA_VALID,
    ),
    _array(
        ENVELOPE_PROTOCOL_PAYLOAD_SCHEMA_VALID,
        "|u1",
        # Pass event bitmap explicitly so _array receives a reviewable |u1 and event
        # bitmap input in module.
        "event_bitmap",
        "validity.envelope.protocol_payload_schema",
        "packed-validity-bits-v1",
        byte_order="not-applicable",
    ),
    # Register envelope protocol payload offsets through _array so the array templates
    # table remains scannable.
    _array(
        ENVELOPE_PROTOCOL_PAYLOAD_OFFSETS,
        "<u8",
        "event_offsets",
        "envelope.protocol_payload_offsets",
        # Pass checked-sentinel-offsets-v1 explicitly so _array receives a reviewable <u8
        # and event offsets input in module.
        "checked-sentinel-offsets-v1",
    ),
    _array(
        ENVELOPE_PROTOCOL_PAYLOAD_BYTES,
        "|u1",
        # Pass protocol payload bytes explicitly so _array receives a reviewable |u1 and
        # protocol payload bytes input in module.
        "protocol_payload_bytes",
        "envelope.protocol_payload_bytes",
        "exact-bytes-v1",
        byte_order="not-applicable",
    ),
    # Register boundary offsets through _array so the array templates table remains
    # scannable.
    _array(
        BOUNDARY_OFFSETS,
        "<u8",
        "boundary_offsets",
        "index.boundary_offsets",
        # Pass checked-sentinel-offsets-v1 explicitly so _array receives a reviewable <u8
        # and boundary offsets input in module.
        "checked-sentinel-offsets-v1",
    ),
    _array(
        GROUP_OFFSETS, "<u8", "group_offsets", "index.group_offsets", "checked-sentinel-offsets-v1"
    ),
    # Register token asset code through _array so the array templates table remains
    # scannable.
    _array(
        TOKEN_ASSET_CODE,
        "<u4",
        "token_launches",
        "payload.token_launch.asset_code",
        # Pass checked-uint32-dictionary-code-v1 explicitly so _array receives a
        # reviewable <u4 and token launches input in module.
        "checked-uint32-dictionary-code-v1",
    ),
    _array(
        TOKEN_DEVELOPER_CODE,
        "<u4",
        # Pass token launches explicitly so _array receives a reviewable <u4 and token
        # launches input in module.
        "token_launches",
        "payload.token_launch.developer_code",
        "checked-uint32-dictionary-code-v1",
    ),
    _array(
        # Pass token creation user code explicitly so _array receives a reviewable <u4 and
        # token launches input in module.
        TOKEN_CREATION_USER_CODE,
        "<u4",
        "token_launches",
        "payload.token_launch.creation_user_code",
        "checked-uint32-dictionary-code-v1",
        # Complete _array only after its <u4 and token launches inputs are visible in module.
    ),
    _array(
        TOKEN_VENUE_CODE,
        "<u4",
        "token_launches",
        # Pass venue code explicitly so _array receives a reviewable <u4 and token
        # launches input in module.
        "payload.token_launch.venue_code",
        "checked-uint32-dictionary-code-v1",
    ),
    _array(
        TOKEN_QUOTE_ASSET_CODE,
        # Pass u4 explicitly so _array receives a reviewable <u4 and token launches input
        # in module.
        "<u4",
        "token_launches",
        "payload.token_launch.quote_asset_code",
        "checked-uint32-dictionary-code-v1",
    ),
    # Register token decimals through _array so the array templates table remains
    # scannable.
    _array(
        TOKEN_DECIMALS,
        "|u1",
        "token_launches",
        "payload.token_launch.decimals",
        # Pass checked-uint8-v1 explicitly so _array receives a reviewable |u1 and token
        # launches input in module.
        "checked-uint8-v1",
        TOKEN_DECIMALS_VALID,
        byte_order="not-applicable",
    ),
    _array(
        # Pass token decimals valid explicitly so _array receives a reviewable |u1 and
        # token bitmap input in module.
        TOKEN_DECIMALS_VALID,
        "|u1",
        "token_bitmap",
        "validity.payload.token_launch.decimals",
        "packed-validity-bits-v1",
        # Pass byte order explicitly so _array receives a reviewable |u1 and token bitmap
        # input in module.
        byte_order="not-applicable",
    ),
    _array(
        TRADE_VENUE_CODE,
        "<u4",
        # Pass venue trades explicitly so _array receives a reviewable <u4 and venue
        # trades input in module.
        "venue_trades",
        "payload.venue_trade.venue_code",
        "checked-uint32-dictionary-code-v1",
    ),
    _array(
        # Pass trade sold asset code explicitly so _array receives a reviewable <u4 and
        # venue trades input in module.
        TRADE_SOLD_ASSET_CODE,
        "<u4",
        "venue_trades",
        "payload.venue_trade.sold_asset_code",
        "checked-uint32-dictionary-code-v1",
        # Complete _array only after its <u4 and venue trades inputs are visible in module.
    ),
    _array(
        TRADE_BOUGHT_ASSET_CODE,
        "<u4",
        "venue_trades",
        # Pass bought asset code explicitly so _array receives a reviewable <u4 and venue
        # trades input in module.
        "payload.venue_trade.bought_asset_code",
        "checked-uint32-dictionary-code-v1",
    ),
    _array(
        TRADE_SOLD_AMOUNT,
        # Pass v16 explicitly so _array receives a reviewable |v16 and venue trades input
        # in module.
        "|V16",
        "venue_trades",
        "payload.venue_trade.sold_amount_atomic",
        "checked-signed-int128-twos-complement-v1",
        byte_order="big",
        # Complete _array only after its |v16 and venue trades inputs are visible in module.
    ),
    _array(
        TRADE_BOUGHT_AMOUNT,
        "|V16",
        "venue_trades",
        # Pass bought amount atomic explicitly so _array receives a reviewable |v16 and
        # venue trades input in module.
        "payload.venue_trade.bought_amount_atomic",
        "checked-signed-int128-twos-complement-v1",
        byte_order="big",
    ),
    _array(
        # Pass trade fee offsets explicitly so _array receives a reviewable <u8 and trade
        # offsets input in module.
        TRADE_FEE_OFFSETS,
        "<u8",
        "trade_offsets",
        "payload.venue_trade.fee_offsets",
        "checked-sentinel-offsets-v1",
        # Complete _array only after its <u8 and trade offsets inputs are visible in module.
    ),
    _array(
        TRADE_FEE_COMPONENT_CODE,
        "<u4",
        "fee_components",
        # Pass component code explicitly so _array receives a reviewable <u4 and fee
        # components input in module.
        "payload.venue_trade.fee.component_code",
        "checked-uint32-dictionary-code-v1",
    ),
    _array(
        TRADE_FEE_ASSET_CODE,
        # Pass u4 explicitly so _array receives a reviewable <u4 and fee components input
        # in module.
        "<u4",
        "fee_components",
        "payload.venue_trade.fee.asset_code",
        "checked-uint32-dictionary-code-v1",
    ),
    # Register trade fee amount through _array so the array templates table remains
    # scannable.
    _array(
        TRADE_FEE_AMOUNT,
        "|V16",
        "fee_components",
        "payload.venue_trade.fee.amount_atomic",
        # Pass checked-signed-int128-twos-complement-v1 explicitly so _array receives a
        # reviewable |v16 and fee components input in module.
        "checked-signed-int128-twos-complement-v1",
        byte_order="big",
    ),
    _array(
        LIFECYCLE_VENUE_CODE,
        # Pass u4 explicitly so _array receives a reviewable <u4 and venue lifecycles
        # input in module.
        "<u4",
        "venue_lifecycles",
        "payload.venue_lifecycle.venue_code",
        "checked-uint32-dictionary-code-v1",
    ),
    # Register lifecycle kind code through _array so the array templates table remains
    # scannable.
    _array(
        LIFECYCLE_KIND_CODE,
        "|u1",
        "venue_lifecycles",
        "payload.venue_lifecycle.kind_code",
        # Pass stable-lifecycle-kind-uint8-v1 explicitly so _array receives a reviewable
        # |u1 and venue lifecycles input in module.
        "stable-lifecycle-kind-uint8-v1",
        byte_order="not-applicable",
    ),
    _array(
        REFERENCE_AMM_VALID,
        # Pass u1 explicitly so _array receives a reviewable |u1 and trade bitmap input in
        # module.
        "|u1",
        "trade_bitmap",
        "validity.protocol.reference_amm",
        "packed-validity-bits-v1",
        byte_order="not-applicable",
        # Complete _array only after its |u1 and trade bitmap inputs are visible in module.
    ),
    _array(
        REFERENCE_AMM_ASSET_A_CODE,
        "<u4",
        "venue_trades",
        # Pass asset a code explicitly so _array receives a reviewable <u4 and venue
        # trades input in module.
        "protocol.reference_amm.asset_a_code",
        "checked-uint32-dictionary-code-v1",
    ),
    _array(
        REFERENCE_AMM_ASSET_B_CODE,
        # Pass u4 explicitly so _array receives a reviewable <u4 and venue trades input in
        # module.
        "<u4",
        "venue_trades",
        "protocol.reference_amm.asset_b_code",
        "checked-uint32-dictionary-code-v1",
    ),
    # Register reference amm reserve a through _array so the array templates table remains
    # scannable.
    _array(
        REFERENCE_AMM_RESERVE_A,
        "|V16",
        "venue_trades",
        "protocol.reference_amm.reserve_a_atomic",
        # Pass checked-signed-int128-twos-complement-v1 explicitly so _array receives a
        # reviewable |v16 and venue trades input in module.
        "checked-signed-int128-twos-complement-v1",
        REFERENCE_AMM_RESERVE_A_VALID,
        byte_order="big",
    ),
    _array(
        # Pass reference amm reserve a valid explicitly so _array receives a reviewable
        # |u1 and trade bitmap input in module.
        REFERENCE_AMM_RESERVE_A_VALID,
        "|u1",
        "trade_bitmap",
        "validity.protocol.reference_amm.reserve_a",
        "packed-validity-bits-v1",
        # Pass byte order explicitly so _array receives a reviewable |u1 and trade bitmap
        # input in module.
        byte_order="not-applicable",
    ),
    _array(
        REFERENCE_AMM_RESERVE_B,
        "|V16",
        # Pass venue trades explicitly so _array receives a reviewable |v16 and venue
        # trades input in module.
        "venue_trades",
        "protocol.reference_amm.reserve_b_atomic",
        "checked-signed-int128-twos-complement-v1",
        REFERENCE_AMM_RESERVE_B_VALID,
        byte_order="big",
        # Complete _array only after its |v16 and venue trades inputs are visible in module.
    ),
    _array(
        REFERENCE_AMM_RESERVE_B_VALID,
        "|u1",
        "trade_bitmap",
        # Pass validity protocol reference amm reserve b explicitly so _array receives a
        # reviewable |u1 and trade bitmap input in module.
        "validity.protocol.reference_amm.reserve_b",
        "packed-validity-bits-v1",
        byte_order="not-applicable",
    ),
    _array(
        # Pass reference amm total fee explicitly so _array receives a reviewable |v16 and
        # venue trades input in module.
        REFERENCE_AMM_TOTAL_FEE,
        "|V16",
        "venue_trades",
        "protocol.reference_amm.total_fee_atomic",
        "checked-signed-int128-twos-complement-v1",
        # Pass byte order explicitly so _array receives a reviewable |v16 and venue trades
        # input in module.
        byte_order="big",
    ),
)


def dictionary_values_path(name: str) -> str:
    return f"dictionaries/{name}.utf8.npy"


# Define dictionary offsets path as one focused operation with an explicit boundary.
def dictionary_offsets_path(name: str) -> str:
    return f"dictionaries/{name}.offsets.npy"


def build_layout(
    counts: ReplayLayoutCounts,
    dictionary_sizes: Mapping[str, tuple[int, int]],
    # Keep the replay layout manifest input explicit in the build layout contract.
) -> ReplayLayoutManifest:
    # Execute the build layout workflow in explicit, reviewable steps.
    if set(dictionary_sizes) != set(DICTIONARY_NAMES):
        raise ValueError("ReplayPack dictionary set differs from layout v3")
    arrays = [
        ReplayArrayLayout(
            path=item.path,
            # Pass dtype explicitly so ReplayArrayLayout receives a reviewable path and
            # dtype input in build layout.
            dtype=item.dtype,
            byte_order=item.byte_order,
            shape=(counts.cardinality(item.cardinality),),
            role=item.role,
            overflow_policy=item.overflow_policy,
            # Pass validity path explicitly so ReplayArrayLayout receives a reviewable
            # path and dtype input in build layout.
            validity_path=item.validity_path,
        )
        for item in _ARRAY_TEMPLATES
    ]
    dictionaries: list[ReplayDictionaryLayout] = []
    # Traverse DICTIONARY_NAMES explicitly so each build layout iteration remains
    # traceable.
    for name in DICTIONARY_NAMES:
        # Process DICTIONARY_NAMES inside the bounded build layout loop.
        count, byte_count = dictionary_sizes[name]
        values_path = dictionary_values_path(name)
        offsets_path = dictionary_offsets_path(name)
        arrays.extend(
            (
                # Pass replay array layout explicitly to extend for |u1 and not-
                # applicable.
                ReplayArrayLayout(
                    path=values_path,
                    dtype="|u1",
                    byte_order="not-applicable",
                    shape=(byte_count,),
                    # Pass role explicitly so ReplayArrayLayout receives a reviewable |u1
                    # and not-applicable input in build layout.
                    role=f"dictionary.{name}.utf8_bytes",
                    overflow_policy="exact-utf8-bytes-v1",
                ),
                ReplayArrayLayout(
                    path=offsets_path,
                    # Pass dtype explicitly so ReplayArrayLayout receives a reviewable <u8
                    # and little input in build layout.
                    dtype="<u8",
                    byte_order="little",
                    shape=(count + 1,),
                    role=f"dictionary.{name}.offsets",
                    overflow_policy="checked-sentinel-offsets-v1",
                    # Complete ReplayArrayLayout only after its <u8 and little inputs are
                    # visible in build layout.
                ),
            )
        )
        dictionaries.append(
            ReplayDictionaryLayout(
                # Pass name explicitly so ReplayDictionaryLayout receives a reviewable <u4
                # and name input in build layout.
                name=name,
                values_path=values_path,
                offsets_path=offsets_path,
                code_dtype="<u4",
                count=count,
                # Complete ReplayDictionaryLayout only after its <u4 and name inputs are
                # visible in build layout.
            )
        )
    return ReplayLayoutManifest(
        arrays=tuple(sorted(arrays, key=lambda item: item.path)),
        dictionaries=tuple(sorted(dictionaries, key=lambda item: item.name)),
        # Complete ReplayLayoutManifest only after its path and name inputs are visible in
        # build layout.
    )


def _bitmap_size(value_count: int) -> int:
    return (value_count + 7) // 8


# Read-only Python aliases keep existing FirstSwap/feature code source-compatible;
# every serialized path and role above uses generic v3 terminology.
BOUNDARY_SLOT = BOUNDARY_BLOCK_ORDINAL
ENVELOPE_SLOT = ENVELOPE_BLOCK_ORDINAL
BLOCK_TIME = CLOCK_BLOCK_TIME_NS
BLOCK_HASH_CODE = CLOCK_BLOCK_HASH_CODE
BLOCK_HASH_VALID = CLOCK_BLOCK_HASH_VALID
# Bind token creator code once as an explicit module-level contract.
TOKEN_CREATOR_CODE = TOKEN_DEVELOPER_CODE
SWAP_POOL_CODE = TRADE_VENUE_CODE
SWAP_SOLD_ASSET_CODE = TRADE_SOLD_ASSET_CODE
SWAP_BOUGHT_ASSET_CODE = TRADE_BOUGHT_ASSET_CODE
SWAP_SOLD_AMOUNT = TRADE_SOLD_AMOUNT
# Bind swap bought amount once as an explicit module-level contract.
SWAP_BOUGHT_AMOUNT = TRADE_BOUGHT_AMOUNT
SWAP_FEE_AMOUNT = REFERENCE_AMM_TOTAL_FEE
SWAP_POOL_ASSET_A_CODE = REFERENCE_AMM_ASSET_A_CODE
SWAP_POOL_ASSET_B_CODE = REFERENCE_AMM_ASSET_B_CODE
SWAP_RESERVE_A = REFERENCE_AMM_RESERVE_A
# Bind swap reserve a valid once as an explicit module-level contract.
SWAP_RESERVE_A_VALID = REFERENCE_AMM_RESERVE_A_VALID
SWAP_RESERVE_B = REFERENCE_AMM_RESERVE_B
SWAP_RESERVE_B_VALID = REFERENCE_AMM_RESERVE_B_VALID


__all__ = [name for name in globals() if name.isupper()] + [
    "ReplayLayoutCounts",
    # Keep the build layout component named inside the all contract.
    "build_layout",
    "dictionary_offsets_path",
    "dictionary_values_path",
]
