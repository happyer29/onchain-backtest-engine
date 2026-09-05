# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from backtest.domain.chain import (
    # Include block32 transaction32 position schema id so the chain dependency remains
    # explicit.
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
)
from backtest.domain.fidelity import IdentityFidelity, OrderingFidelity
from backtest.domain.identifiers import CapabilityId, ContentDigest

# Import market events at the visible module dependency boundary.
from backtest.domain.market_events import (
    BlockEvent,
    EventKindName,
    TokenLaunchEvent,
    VenueLifecycleEvent,
    # Include venue trade event so the market events dependency remains explicit.
    VenueTradeEvent,
)
from backtest.domain.time import BlockRange
from backtest.plugins.protocols.pumpfun import (
    PUMPFUN_LAUNCH_PAYLOAD_SCHEMA_ID,
    # Include pumpfun lifecycle payload schema id so the pumpfun dependency remains
    # explicit.
    PUMPFUN_LIFECYCLE_PAYLOAD_SCHEMA_ID,
    PUMPFUN_TRADE_PAYLOAD_SCHEMA_ID,
    PumpCurveLifecycle,
    PumpCurveStateV1,
    PumpMode,
    # Include encode launch payload so the pumpfun dependency remains explicit.
    encode_launch_payload,
    encode_lifecycle_payload,
    encode_trade_payload,
)
from backtest.plugins.protocols.pumpfun.projector import (
    # Include pumpfun projection error so the projector dependency remains explicit.
    PumpfunProjectionError,
    PumpfunProjectionErrorCode,
    PumpfunProjectionSpec,
    PumpfunProtocolProjector,
)

# Bind capabilities once as an explicit module-level contract.
_CAPABILITIES = {
    EventKindName.BLOCK: CapabilityId("pumpfun.block-clock.v2"),
    EventKindName.TOKEN_LAUNCH: CapabilityId("pumpfun.token-launch.v2"),
    EventKindName.VENUE_TRADE: CapabilityId("pumpfun.curve-trade.v2"),
    EventKindName.VENUE_LIFECYCLE: CapabilityId("pumpfun.curve-lifecycle.v2"),
    # Complete the capabilities group only after its semantic components are visible.
}

_STATE = {
    "virtual_token_reserves_atomic": 1_000_000,
    "virtual_sol_reserves_lamports": 2_000_000,
    "real_token_reserves_atomic": 800_000,
    # Keep the real sol reserves lamports component named inside the state contract.
    "real_sol_reserves_lamports": 100_000,
    "token_total_supply_atomic": 1_000_000,
    "lifecycle": "ACTIVE",
    "mode": "NORMAL",
}


# Keep the batch contract and validation rules together.
@dataclass(frozen=True)
class _Batch:
    capability_id: CapabilityId
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]

    # Apply property semantics to the following batch covered range contract.
    @property
    def covered_range(self) -> BlockRange:
        # Execute the batch covered range workflow in explicit, reviewable steps.
        return BlockRange(
            SOLANA_MAINNET_NETWORK_ID,
            BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            10,
            11,
            # Complete BlockRange only after its solana mainnet network id and block32
            # transaction32 position schema id inputs are visible in batch covered range.
        )

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    # Define batch query fingerprint as one focused operation with an explicit boundary.
    def query_fingerprint(self) -> ContentDigest | None:
        return None


def test_projector_builds_generic_block_launch_trade_and_lifecycle_events() -> None:
    # Execute the test projector builds generic block launch trade and lifecycle events
    # workflow in explicit, reviewable steps.
    projector = _projector()
    block = _project(
        projector,
        EventKindName.BLOCK,
        {
            # Keep block ordinal named so the block ordinal and block time payload passed
            # to _project remains self-describing within test projector builds generic
            # block launch trade and lifecycle events.
            "block_ordinal": 10,
            "block_time": 2_000_000_000,
            "transaction_count": 3,
            "block_hash": "block-hash",
        },
        # Complete _project only after its block ordinal and block time inputs are visible in
        # test projector builds generic block launch trade and lifecycle events.
    )
    launch = _project(
        projector,
        EventKindName.TOKEN_LAUNCH,
        _event_row(event_index=0) | _STATE,
        # Complete _project only after its token launch and event row inputs are visible in
        # test projector builds generic block launch trade and lifecycle events.
    )
    trade_state = _STATE | {
        "virtual_token_reserves_atomic": 900_000,
        "virtual_sol_reserves_lamports": 2_200_000,
        "real_token_reserves_atomic": 700_000,
        # Keep the real sol reserves lamports component named inside the trade state
        # contract.
        "real_sol_reserves_lamports": 300_000,
    }
    trade = _project(
        projector,
        EventKindName.VENUE_TRADE,
        # Keep the event row _event_row step visible while building trade.
        _event_row(event_index=1)
        | trade_state
        | {
            "side": "BUY",
            "base_amount_atomic": 100_000,
            # Keep quote amount atomic named so the side and base amount atomic payload
            # passed to _project remains self-describing within test projector builds
            # generic block launch trade and lifecycle events.
            "quote_amount_atomic": 200_000,
            "protocol_fee_atomic": 1_900,
            "creator_fee_atomic": 600,
        },
    )
    # Assemble migrated state once so the test projector builds generic block launch trade
    # and lifecycle events workflow shares one value.
    migrated_state = trade_state | {"lifecycle": "MIGRATED"}
    lifecycle = _project(
        projector,
        EventKindName.VENUE_LIFECYCLE,
        _event_row(event_index=2) | migrated_state | {"lifecycle_kind": "MIGRATED"},
        # Complete _project only after its lifecycle kind and migrated inputs are visible in
        # test projector builds generic block launch trade and lifecycle events.
    )

    assert isinstance(block, BlockEvent)
    assert block.tx_count == 3
    assert isinstance(launch, TokenLaunchEvent)
    assert launch.transaction_succeeded is True
    # Verify isinstance(trade, VenueTradeEvent) before this scenario is accepted.
    assert isinstance(trade, VenueTradeEvent)
    assert isinstance(lifecycle, VenueLifecycleEvent)
    assert launch.envelope.transaction_group_id == trade.envelope.transaction_group_id
    assert trade.envelope.transaction_group_id == lifecycle.envelope.transaction_group_id

    launch_state = _pump_state(_STATE)
    # Assemble trade curve state once so the test projector builds generic block launch
    # trade and lifecycle events workflow shares one value.
    trade_curve_state = _pump_state(trade_state)
    migrated_curve_state = _pump_state(migrated_state)
    assert launch.protocol_payload == encode_launch_payload(launch_state)
    assert trade.protocol_payload == encode_trade_payload(trade_curve_state)
    assert lifecycle.protocol_payload == encode_lifecycle_payload(migrated_curve_state)
    # Verify the value, creator and protocol relationship before this scenario is
    # accepted.
    assert [item.component_id.value for item in trade.fee_components] == [
        "creator",
        "protocol",
    ]
    assert trade.sold_asset_id.value == "SOL"
    # Verify trade.bought_asset_id.value == 'TOKEN' before this scenario is accepted.
    assert trade.bought_asset_id.value == "TOKEN"


def test_projector_preserves_zero_quote_dust_sell_and_rejects_zero_quote_buy() -> None:
    projector = _projector()
    dust = _project(
        projector,
        EventKindName.VENUE_TRADE,
        _event_row(event_index=1)
        | _STATE
        | {
            "side": "SELL",
            "base_amount_atomic": 35,
            "quote_amount_atomic": 0,
            "protocol_fee_atomic": 0,
            "creator_fee_atomic": 0,
        },
    )
    assert isinstance(dust, VenueTradeEvent)
    assert dust.sold_amount_atomic == 35
    assert dust.bought_amount_atomic == 0

    with pytest.raises(ValueError, match="buy quote amount must be positive"):
        _project(
            projector,
            EventKindName.VENUE_TRADE,
            _event_row(event_index=2)
            | _STATE
            | {
                "side": "BUY",
                "base_amount_atomic": 35,
                "quote_amount_atomic": 0,
                "protocol_fee_atomic": 0,
                "creator_fee_atomic": 0,
            },
        )


def test_unknown_mode_and_lifecycle_disagreement_fail_the_projection() -> None:
    # Execute the test unknown mode and lifecycle disagreement fail the projection
    # workflow in explicit, reviewable steps.
    projector = _projector()
    with pytest.raises(ValueError, match="unknown lifecycle or mode"):
        # Keep raises, value error and pytest active only for the bounded test unknown
        # mode and lifecycle disagreement fail the projection operation.
        _project(
            projector,
            EventKindName.TOKEN_LAUNCH,
            _event_row(event_index=0) | _STATE | {"mode": "UNKNOWN"},
        )


# Define test launch projection contract requires transaction success column as one
# focused operation with an explicit boundary.
def test_launch_projection_contract_requires_transaction_success_column() -> None:
    # Execute the test launch projection contract requires transaction success column
    # workflow in explicit, reviewable steps.
    columns = tuple(
        item
        for item in _spec(EventKindName.TOKEN_LAUNCH).columns
        if item[0] != "transaction_succeeded"
    )

    # Acquire raises, value error and pytest at an explicit test launch projection
    # contract requires transaction success column context boundary so cleanup remains
    # scoped.
    with pytest.raises(ValueError, match="transaction_succeeded"):
        # Keep raises, value error and pytest active only for the bounded test launch
        # projection contract requires transaction success column operation.
        PumpfunProjectionSpec(
            capability_id=_CAPABILITIES[EventKindName.TOKEN_LAUNCH],
            kind=EventKindName.TOKEN_LAUNCH,
            protocol="pumpfun",
            protocol_version="v1",
            # Pass identity fidelity explicitly so PumpfunProjectionSpec receives a
            # reviewable pumpfun and v1 input in test launch projection contract requires
            # transaction success column.
            identity_fidelity=IdentityFidelity.UNKNOWN,
            ordering_fidelity=OrderingFidelity.INSTRUCTION_EXACT,
            source_total_key=(),
            source_total_key_is_proven=False,
            protocol_payload_schema_id=PUMPFUN_LAUNCH_PAYLOAD_SCHEMA_ID,
            # Pass columns explicitly so PumpfunProjectionSpec receives a reviewable
            # pumpfun and v1 input in test launch projection contract requires transaction
            # success column.
            columns=columns,
        )


@pytest.mark.parametrize(
    ("transaction_succeeded", "expected_code"),
    [
        # Open the transaction succeeded and expected code payload explicitly for
        # parametrize within test launch projection rejects failed or non boolean
        # transaction status.
        (False, PumpfunProjectionErrorCode.LAUNCH_TRANSACTION_FAILED),
        (0, PumpfunProjectionErrorCode.LAUNCH_TRANSACTION_STATUS_INVALID),
        (1, PumpfunProjectionErrorCode.LAUNCH_TRANSACTION_STATUS_INVALID),
        ("true", PumpfunProjectionErrorCode.LAUNCH_TRANSACTION_STATUS_INVALID),
        (None, PumpfunProjectionErrorCode.LAUNCH_TRANSACTION_STATUS_INVALID),
        # Close the transaction succeeded and expected code payload only after all test launch
        # projection rejects failed or non boolean transaction status fields are present.
    ],
)
def test_launch_projection_rejects_failed_or_non_boolean_transaction_status(
    transaction_succeeded: object,
    expected_code: PumpfunProjectionErrorCode,
    # Close the test launch projection rejects failed or non boolean transaction status
    # signature after its explicit inputs.
) -> None:
    # Execute the test launch projection rejects failed or non boolean transaction status
    # workflow in explicit, reviewable steps.
    projector = _projector()

    with pytest.raises(PumpfunProjectionError) as raised:
        # Keep raises, pumpfun projection error and pytest active only for the bounded
        # test launch projection rejects failed or non boolean transaction status
        # operation.
        _project(
            projector,
            EventKindName.TOKEN_LAUNCH,
            _event_row(event_index=0) | _STATE | {"transaction_succeeded": transaction_succeeded},
        )

    # Verify raised.value.code is expected_code before this scenario is accepted.
    assert raised.value.code is expected_code

    with pytest.raises(ValueError, match="kind and after-state disagree"):
        # Keep raises, value error and pytest active only for the bounded test launch
        # projection rejects failed or non boolean transaction status operation.
        _project(
            projector,
            EventKindName.VENUE_LIFECYCLE,
            _event_row(event_index=2) | _STATE | {"lifecycle_kind": "MIGRATED"},
        )


# Define projector as one focused operation with an explicit boundary.
def _projector() -> PumpfunProtocolProjector:
    # Execute the projector workflow in explicit, reviewable steps.
    return PumpfunProtocolProjector(
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        specs=tuple(_spec(kind) for kind in _CAPABILITIES),
    )


# Define spec as one focused operation with an explicit boundary.
def _spec(kind: EventKindName) -> PumpfunProjectionSpec:
    # Execute the spec workflow in explicit, reviewable steps.
    columns = {
        EventKindName.BLOCK: {
            "block_ordinal",
            "block_time",
            "transaction_count",
            # Keep the block hash component named inside the columns contract.
            "block_hash",
        },
        EventKindName.TOKEN_LAUNCH: {
            "block_ordinal",
            "transaction_index",
            # Keep the event index component named inside the columns contract.
            "event_index",
            "signature",
            "transaction_succeeded",
            "asset",
            "developer",
            # Keep the creation user component named inside the columns contract.
            "creation_user",
            "venue",
            "quote_asset",
            *_STATE,
        },
        # Keep the event kind name component named inside the columns contract.
        EventKindName.VENUE_TRADE: {
            "block_ordinal",
            "transaction_index",
            "event_index",
            "signature",
            # Keep the asset component named inside the columns contract.
            "asset",
            "venue",
            "quote_asset",
            "side",
            "base_amount_atomic",
            # Keep the quote amount atomic component named inside the columns contract.
            "quote_amount_atomic",
            "protocol_fee_atomic",
            "creator_fee_atomic",
            *_STATE,
        },
        # Keep the event kind name component named inside the columns contract.
        EventKindName.VENUE_LIFECYCLE: {
            "block_ordinal",
            "transaction_index",
            "event_index",
            "signature",
            # Keep the venue component named inside the columns contract.
            "venue",
            "lifecycle_kind",
            *_STATE,
        },
    }[kind]
    # Assemble payload schema once so the spec workflow shares one value.
    payload_schema = {
        EventKindName.BLOCK: None,
        EventKindName.TOKEN_LAUNCH: PUMPFUN_LAUNCH_PAYLOAD_SCHEMA_ID,
        EventKindName.VENUE_TRADE: PUMPFUN_TRADE_PAYLOAD_SCHEMA_ID,
        EventKindName.VENUE_LIFECYCLE: PUMPFUN_LIFECYCLE_PAYLOAD_SCHEMA_ID,
        # Keep the kind component named inside the payload schema contract.
    }[kind]
    return PumpfunProjectionSpec(
        capability_id=_CAPABILITIES[kind],
        kind=kind,
        protocol="solana" if kind is EventKindName.BLOCK else "pumpfun",
        # Pass protocol version explicitly so PumpfunProjectionSpec receives a reviewable
        # solana and pumpfun input in spec.
        protocol_version="v1",
        identity_fidelity=IdentityFidelity.UNKNOWN,
        ordering_fidelity=(
            OrderingFidelity.UNKNOWN
            if kind is EventKindName.BLOCK
            # Route all remaining cases through the explicit alternative branch.
            else OrderingFidelity.INSTRUCTION_EXACT
        ),
        source_total_key=(),
        source_total_key_is_proven=False,
        protocol_payload_schema_id=payload_schema,
        # Include columns in the completed spec result.
        columns=tuple((name, name) for name in sorted(columns)),
    )


def _event_row(*, event_index: int) -> dict[str, object]:
    # Execute the event row workflow in explicit, reviewable steps.
    return {
        "block_ordinal": 10,
        "transaction_index": 1,
        "event_index": event_index,
        "signature": "same-transaction",
        # Include transaction succeeded in the completed event row result.
        "transaction_succeeded": True,
        "asset": "TOKEN",
        "developer": "DEV",
        "creation_user": "USER",
        "venue": "pump-curve:TOKEN",
        # Include quote asset in the completed event row result.
        "quote_asset": "SOL",
    }


def _project(
    projector: PumpfunProtocolProjector,
    kind: EventKindName,
    # Keep the row input explicit in the project contract.
    row: dict[str, object],
) -> BlockEvent | TokenLaunchEvent | VenueTradeEvent | VenueLifecycleEvent:
    # Execute the project workflow in explicit, reviewable steps.
    columns = tuple(sorted(row))
    return projector.project(
        _Batch(
            _CAPABILITIES[kind],
            columns,
            # Include tuple in the completed project result.
            (tuple(row[column] for column in columns),),
        )
    )[0]


def _pump_state(values: dict[str, object]) -> PumpCurveStateV1:
    # Execute the pump state workflow in explicit, reviewable steps.
    return PumpCurveStateV1(
        virtual_token_reserves_atomic=int(values["virtual_token_reserves_atomic"]),
        virtual_sol_reserves_lamports=int(values["virtual_sol_reserves_lamports"]),
        real_token_reserves_atomic=int(values["real_token_reserves_atomic"]),
        real_sol_reserves_lamports=int(values["real_sol_reserves_lamports"]),
        # Include token total supply atomic in the completed pump state result.
        token_total_supply_atomic=int(values["token_total_supply_atomic"]),
        lifecycle=PumpCurveLifecycle(str(values["lifecycle"])),
        mode=PumpMode(str(values["mode"])),
    )
