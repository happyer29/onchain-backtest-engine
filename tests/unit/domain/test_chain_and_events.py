# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from dataclasses import replace

import pytest

from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    # Include solana mainnet network id so the chain dependency remains explicit.
    SOLANA_MAINNET_NETWORK_ID,
    UINT32_MAX,
    UINT32_SIZE,
    UINT64_MAX,
    ChainIdentityMismatchError,
    # Include chain position so the chain dependency remains explicit.
    ChainPosition,
    UnsupportedPositionSchemaError,
    boundary_coordinates,
    boundary_ordinal,
)

# Import event hashing at the visible module dependency boundary.
from backtest.domain.event_hashing import canonical_event_digest, canonical_event_document
from backtest.domain.fidelity import OrderingFidelity
from backtest.domain.identifiers import (
    AccountId,
    AssetId,
    # Include capability id so the identifiers dependency remains explicit.
    CapabilityId,
    ContentDigest,
    FeeComponentId,
    NetworkId,
    PositionSchemaId,
    # Include protocol payload schema id so the identifiers dependency remains explicit.
    ProtocolPayloadSchemaId,
    VenueId,
)
from backtest.domain.market_events import (
    BlockEvent,
    # Include event envelope so the market events dependency remains explicit.
    EventEnvelope,
    EventKind,
    FeeComponent,
    TokenLaunchEvent,
    VenueLifecycleEvent,
    # Include venue lifecycle kind so the market events dependency remains explicit.
    VenueLifecycleKind,
    VenueTradeEvent,
)
from backtest.domain.time import BlockRange


def test_solana_mainnet_network_id_uses_the_complete_genesis_hash() -> None:
    # Execute the test solana mainnet network id uses the complete genesis hash workflow
    # in explicit, reviewable steps.
    assert SOLANA_MAINNET_NETWORK_ID.value == (
        "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"
    )


def test_block32_transaction32_boundary_golden_edges_round_trip() -> None:
    # Execute the test block32 transaction32 boundary golden edges round trip workflow in
    # explicit, reviewable steps.
    schema = BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID

    assert boundary_ordinal(0, -1, position_schema_id=schema) == 0
    assert boundary_ordinal(0, 0, position_schema_id=schema) == 1
    assert boundary_ordinal(1, -1, position_schema_id=schema) == 1 << 32
    assert boundary_ordinal(UINT32_MAX, UINT32_MAX - 1, position_schema_id=schema) == UINT64_MAX
    # Verify the boundary coordinates, uint64 max and uint32 max relationship before this
    # scenario is accepted.
    assert boundary_coordinates(UINT64_MAX, position_schema_id=schema) == (
        UINT32_MAX,
        UINT32_MAX - 1,
    )


@pytest.mark.parametrize(
    # Open the block and transaction payload explicitly for parametrize within test
    # block32 transaction32 rejects invalid coordinates.
    ("block", "transaction", "error"),
    (
        (-1, 0, ValueError),
        (UINT32_SIZE, 0, OverflowError),
        (0, -2, ValueError),
        # Open the block and transaction payload explicitly for parametrize within test
        # block32 transaction32 rejects invalid coordinates.
        (0, UINT32_MAX, OverflowError),
        (True, 0, TypeError),
        (0, False, TypeError),
    ),
)
# Define test block32 transaction32 rejects invalid coordinates as one focused operation
# with an explicit boundary.
def test_block32_transaction32_rejects_invalid_coordinates(
    block: int,
    transaction: int,
    error: type[Exception],
) -> None:
    # Execute the test block32 transaction32 rejects invalid coordinates workflow in
    # explicit, reviewable steps.
    with pytest.raises(error):
        # Keep raises, error and pytest active only for the bounded test block32
        # transaction32 rejects invalid coordinates operation.
        boundary_ordinal(
            block,
            transaction,
            position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        )


# Define test position schema is explicit and unsupported schema fails closed as one
# focused operation with an explicit boundary.
def test_position_schema_is_explicit_and_unsupported_schema_fails_closed() -> None:
    # Execute the test position schema is explicit and unsupported schema fails closed
    # workflow in explicit, reviewable steps.
    with pytest.raises(ValueError, match="family:immutable"):
        NetworkId("mainnet")
    with pytest.raises(ValueError, match="mutable network alias"):
        NetworkId("solana:mainnet-beta")
    with pytest.raises(UnsupportedPositionSchemaError):
        # Keep raises, unsupported position schema error and pytest active only for the
        # bounded test position schema is explicit and unsupported schema fails closed
        # operation.
        ChainPosition(
            network_id=SOLANA_MAINNET_NETWORK_ID,
            position_schema_id=PositionSchemaId("block64-transaction64-v1"),
            block_ordinal=1,
            transaction_index=0,
            # Pass event index explicitly so ChainPosition receives a reviewable
            # block64-transaction64-v1 and position schema id input in test position
            # schema is explicit and unsupported schema fails closed.
            event_index=0,
        )


def test_block_range_rejects_cross_network_position_and_preserves_half_open_bounds() -> None:
    # Execute the test block range rejects cross network position and preserves half open
    # bounds workflow in explicit, reviewable steps.
    block_range = BlockRange(
        SOLANA_MAINNET_NETWORK_ID,
        BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        UINT32_MAX - 1,
        UINT32_SIZE,
        # Complete BlockRange only after its solana mainnet network id and block32
        # transaction32 position schema id inputs are visible in test block range rejects
        # cross network position and preserves half open bounds.
    )
    position = _position(SOLANA_MAINNET_NETWORK_ID, UINT32_MAX, 0)

    assert block_range.contains_position(position)
    assert block_range.span == 2
    assert block_range.split(1) == (
        # Keep the block range expectation tied to split, block range and solana mainnet
        # network id in this scenario.
        BlockRange(
            SOLANA_MAINNET_NETWORK_ID,
            BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            UINT32_MAX - 1,
            UINT32_MAX,
            # Complete BlockRange only after its solana mainnet network id and block32
            # transaction32 position schema id inputs are visible in test block range rejects
            # cross network position and preserves half open bounds.
        ),
        BlockRange(
            SOLANA_MAINNET_NETWORK_ID,
            BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            UINT32_MAX,
            # Pass uint32 size explicitly so BlockRange receives a reviewable solana
            # mainnet network id and block32 transaction32 position schema id input in
            # test block range rejects cross network position and preserves half open
            # bounds.
            UINT32_SIZE,
        ),
    )
    with pytest.raises(ChainIdentityMismatchError):
        # Keep raises, chain identity mismatch error and pytest active only for the
        # bounded test block range rejects cross network position and preserves half open
        # bounds operation.
        block_range.contains_position(
            _position(NetworkId("solana:11111111111111111111111111111112"), UINT32_MAX, 0)
        )


def test_same_coordinates_on_different_networks_have_different_event_identity() -> None:
    # Execute the test same coordinates on different networks have different event
    # identity workflow in explicit, reviewable steps.
    first = _block(SOLANA_MAINNET_NETWORK_ID)
    second = replace(
        first,
        envelope=replace(
            first.envelope,
            # A distinct valid 32-byte genesis preserves the cross-network identity test.
            position=_position(NetworkId("solana:11111111111111111111111111111112"), 123, -1),
        ),
    )

    assert first.envelope.boundary_ordinal == second.envelope.boundary_ordinal
    assert canonical_event_digest(first) != canonical_event_digest(second)
    # Assemble document once so the test same coordinates on different networks have
    # different event identity workflow shares one value.
    document = canonical_event_document(first)
    assert document["network_id"] == SOLANA_MAINNET_NETWORK_ID.value
    assert document["position_schema_id"] == "block32-transaction32-v1"
    assert document["block_ordinal"] == 123
    assert "slot" not in document
    # Verify the name, document and event kind relationship before this scenario is
    # accepted.
    assert document["event_kind"] == EventKind.BLOCK.name


def test_generic_event_documents_keep_exact_protocol_owned_payloads() -> None:
    # Execute the test generic event documents keep exact protocol owned payloads workflow
    # in explicit, reviewable steps.
    envelope = _envelope(SOLANA_MAINNET_NETWORK_ID, 123, 4)
    launch = TokenLaunchEvent(
        envelope=envelope,
        asset_id=AssetId("TOKEN"),
        developer_id=AccountId("developer"),
        # Keep the creation-user AccountId step visible while building launch.
        creation_user_id=AccountId("creation-user"),
        venue_id=VenueId("example-venue"),
        quote_asset_id=AssetId("QUOTE"),
        decimals=6,
        protocol_payload_schema=ProtocolPayloadSchemaId("example-launch-payload-v1"),
        # Pass protocol payload explicitly so TokenLaunchEvent receives a reviewable token
        # and developer input in test generic event documents keep exact protocol owned
        # payloads.
        protocol_payload=b"\x00\xff",
    )
    trade = VenueTradeEvent(
        envelope=envelope,
        venue_id=VenueId("example-venue"),
        # Keep the quote AssetId step visible while building trade.
        sold_asset_id=AssetId("QUOTE"),
        bought_asset_id=AssetId("TOKEN"),
        sold_amount_atomic=100,
        bought_amount_atomic=90,
        fee_components=(
            # Keep the fee component and fee component id FeeComponent step visible while
            # building trade.
            FeeComponent(FeeComponentId("creator"), AssetId("QUOTE"), 1),
            FeeComponent(FeeComponentId("protocol"), AssetId("QUOTE"), 2),
        ),
        protocol_payload_schema=ProtocolPayloadSchemaId("example-trade-payload-v1"),
        protocol_payload=b"\x10\x11",
        # Complete VenueTradeEvent only after its example-venue and quote inputs are visible
        # in test generic event documents keep exact protocol owned payloads.
    )
    lifecycle = VenueLifecycleEvent(
        envelope=envelope,
        venue_id=VenueId("example-venue"),
        lifecycle_kind=VenueLifecycleKind.MIGRATED,
        # Keep the example-lifecycle-payload-v1 ProtocolPayloadSchemaId step visible while
        # building lifecycle.
        protocol_payload_schema=ProtocolPayloadSchemaId("example-lifecycle-payload-v1"),
        protocol_payload=b"\x20\x21",
    )

    launch_document = canonical_event_document(launch)
    trade_document = canonical_event_document(trade)
    # Assemble lifecycle document once so the test generic event documents keep exact
    # protocol owned payloads workflow shares one value.
    lifecycle_document = canonical_event_document(lifecycle)
    assert launch_document["event_kind"] == "TOKEN_LAUNCH"
    assert launch_document["payload"] == {
        "asset_id": "TOKEN",
        "creation_user_id": "creation-user",
        # Keep the decimals expectation tied to launch document, payload and asset id in
        # this scenario.
        "decimals": 6,
        "developer_id": "developer",
        "protocol_payload": "00ff",
        "protocol_payload_schema": "example-launch-payload-v1",
        "quote_asset_id": "QUOTE",
        # Keep the venue id expectation tied to launch document, payload and asset id in
        # this scenario.
        "venue_id": "example-venue",
    }
    assert trade_document["event_kind"] == "VENUE_TRADE"
    assert trade_document["payload"] == {
        "bought_amount_atomic": 90,
        # Keep the bought asset id expectation tied to trade document, payload and bought
        # amount atomic in this scenario.
        "bought_asset_id": "TOKEN",
        "fee_components": [
            {"amount_atomic": 1, "asset_id": "QUOTE", "component_id": "creator"},
            {"amount_atomic": 2, "asset_id": "QUOTE", "component_id": "protocol"},
        ],
        # Keep the protocol payload expectation tied to trade document, payload and bought
        # amount atomic in this scenario.
        "protocol_payload": "1011",
        "protocol_payload_schema": "example-trade-payload-v1",
        "sold_amount_atomic": 100,
        "sold_asset_id": "QUOTE",
        "venue_id": "example-venue",
        # Verify the trade document, payload and bought amount atomic relationship before this
        # scenario is accepted.
    }
    assert lifecycle_document["event_kind"] == "VENUE_LIFECYCLE"
    assert lifecycle_document["payload"] == {
        "lifecycle_kind": "MIGRATED",
        "protocol_payload": "2021",
        # Keep the protocol payload schema expectation tied to lifecycle document, payload
        # and lifecycle kind in this scenario.
        "protocol_payload_schema": "example-lifecycle-payload-v1",
        "venue_id": "example-venue",
    }
    assert int(EventKind.TOKEN_CREATION) == int(EventKind.TOKEN_LAUNCH)
    assert int(EventKind.SWAP) == int(EventKind.VENUE_TRADE)


# Define test event contract rejects position capacity overflow and noncanonical fees as
# one focused operation with an explicit boundary.
def test_event_contract_rejects_position_capacity_overflow_and_noncanonical_fees() -> None:
    # Execute the test event contract rejects position capacity overflow and noncanonical
    # fees workflow in explicit, reviewable steps.
    with pytest.raises(ValueError, match="position schema transaction capacity"):
        replace(_block(SOLANA_MAINNET_NETWORK_ID), tx_count=UINT32_SIZE)

    with pytest.raises(ValueError, match="canonical component/asset order"):
        # Keep raises, value error and pytest active only for the bounded test event
        # contract rejects position capacity overflow and noncanonical fees operation.
        VenueTradeEvent(
            envelope=_envelope(SOLANA_MAINNET_NETWORK_ID, 123, 4),
            venue_id=VenueId("example-venue"),
            sold_asset_id=AssetId("QUOTE"),
            bought_asset_id=AssetId("TOKEN"),
            # Pass sold amount atomic explicitly so VenueTradeEvent receives a reviewable
            # example-venue and quote input in test event contract rejects position
            # capacity overflow and noncanonical fees.
            sold_amount_atomic=100,
            bought_amount_atomic=90,
            fee_components=(
                FeeComponent(FeeComponentId("protocol"), AssetId("QUOTE"), 2),
                FeeComponent(FeeComponentId("creator"), AssetId("QUOTE"), 1),
                # Complete VenueTradeEvent only after its example-venue and quote inputs are
                # visible in test event contract rejects position capacity overflow and
                # noncanonical fees.
            ),
            protocol_payload_schema=ProtocolPayloadSchemaId("example-trade-payload-v1"),
            protocol_payload=b"",
        )


def test_historical_trade_allows_one_zero_dust_leg_but_rejects_a_noop() -> None:
    dust = VenueTradeEvent(
        envelope=_envelope(SOLANA_MAINNET_NETWORK_ID, 123, 4),
        venue_id=VenueId("example-venue"),
        sold_asset_id=AssetId("TOKEN"),
        bought_asset_id=AssetId("QUOTE"),
        sold_amount_atomic=35,
        bought_amount_atomic=0,
        fee_components=(),
        protocol_payload_schema=ProtocolPayloadSchemaId("example-dust-transition-v1"),
        protocol_payload=b"state-after",
    )
    assert dust.sold_amount_atomic == 35
    assert dust.bought_amount_atomic == 0

    with pytest.raises(ValueError, match="at least one positive amount"):
        replace(dust, sold_amount_atomic=0)


def _position(network_id: NetworkId, block: int, transaction: int) -> ChainPosition:
    # Execute the position workflow in explicit, reviewable steps.
    return ChainPosition(
        network_id=network_id,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        block_ordinal=block,
        transaction_index=transaction,
        # Pass event index explicitly so ChainPosition receives a reviewable network id
        # and block32 transaction32 position schema id input in position.
        event_index=0,
    )


def _block(network_id: NetworkId) -> BlockEvent:
    # Execute the block workflow in explicit, reviewable steps.
    return BlockEvent(
        envelope=_envelope(network_id, 123, -1),
        block_time_ns=123_000_000_000,
        tx_count=42,
        block_hash="block-hash",
        # Complete BlockEvent only after its block-hash and envelope inputs are visible in
        # block.
    )


def _envelope(network_id: NetworkId, block: int, transaction: int) -> EventEnvelope:
    # Execute the envelope workflow in explicit, reviewable steps.
    digest = ContentDigest("1" * 64)
    return EventEnvelope(
        position=_position(network_id, block, transaction),
        transaction_group_id=digest,
        source_record_id=digest,
        # Pass canonical event id explicitly so EventEnvelope receives a reviewable v1 and
        # example input in envelope.
        canonical_event_id=digest,
        stable_causal_id=digest,
        capability_id=CapabilityId("events.v1"),
        protocol="example",
        protocol_version="1",
        # Pass ordering fidelity explicitly so EventEnvelope receives a reviewable v1 and
        # example input in envelope.
        ordering_fidelity=OrderingFidelity.INSTRUCTION_EXACT,
    )
