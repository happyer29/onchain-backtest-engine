"""Copy-buy signals over the shared, transaction-atomic Pump curve reducer."""

from dataclasses import replace

from backtest.domain.copytrading import CopyBuyIntent, CopyBuySignal, TokenPrice
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import AccountId, AssetId, BundleId, ProtocolPayloadSchemaId
from backtest.domain.market_events import CanonicalEvent, VenueTradeEvent

# Execution errors distinguish unsupported protocol state from a rejected trade.
from backtest.engine.sniping_contracts import ProtocolContractError, ProtocolContractErrorCode

# Actor bytes are validated before the shared state reducer receives a transaction.
from backtest.plugins.protocols.pumpfun.copybuy_payload import (
    COPYBUY_TRADE_PAYLOAD_SCHEMA,
    decode_copybuy_trade_payload,
)
from backtest.plugins.protocols.pumpfun.model import PumpCurveLifecycle, PumpFeeProfile

# The shared reducer supplies curve math while this wrapper retains the original actor.
from backtest.plugins.protocols.pumpfun.sniping import (
    PUMPFUN_SNIPING_PROTOCOL_BUNDLE_ID,
    PUMPFUN_TRADE_PAYLOAD_SCHEMA_ID,
    PumpfunSnipingProtocolRuntime,
    encode_trade_payload,
    # Shared state encoding never replaces the signer-bearing source event identity.
)

COPYBUY_PROTOCOL_BUNDLE_ID = BundleId(
    domain_digest(
        "backtest.pumpfun-copy-protocol-bundle.v1",
        # The copy protocol binds its own payload contract beside the shared curve implementation.
        {
            "shared_curve_bundle": PUMPFUN_SNIPING_PROTOCOL_BUNDLE_ID.hex,
            "trade_payload_schema": COPYBUY_TRADE_PAYLOAD_SCHEMA.value,
            # Shared math and signer payload version jointly distinguish this protocol family.
        },
    ).hex
)


class PumpfunCopyBuyProtocolRuntime(PumpfunSnipingProtocolRuntime):
    """Share exact state/quote/account math; expose only actual source BUYs."""

    def __init__(
        self,
        *,
        quote_asset_id: AssetId,
        fee_profile: PumpFeeProfile,
        # Supported program version and pinned bundle remain explicit construction operands.
        protocol_version: str,
        bundle_id: BundleId | None = None,
    ) -> None:
        """Copy protocol identity cannot silently inherit the launch-only Sniping identity."""
        super().__init__(
            quote_asset_id=quote_asset_id,
            fee_profile=fee_profile,
            protocol_version=protocol_version,
            bundle_id=COPYBUY_PROTOCOL_BUNDLE_ID if bundle_id is None else bundle_id,
            # Default unit identity is replaced by the exact pinned bundle during real resolution.
        )

    @property
    def trade_payload_schema_id(self) -> ProtocolPayloadSchemaId:
        """Readers and preflight must require the exact signer-bearing input schema."""
        return COPYBUY_TRADE_PAYLOAD_SCHEMA

    def apply_group(
        self, events: tuple[CanonicalEvent, ...], *, effective_at_unix_s: int
    ) -> tuple[CopyBuySignal, ...]:
        """No callback or state mutation occurs between instructions of a group."""
        state_events: list[CanonicalEvent] = []
        signals: list[CopyBuySignal] = []
        for event in events:
            # Existing creation/lifecycle validation remains in the shared reducer.
            if not isinstance(event, VenueTradeEvent):
                state_events.append(event)
                continue
            if event.protocol_payload_schema != COPYBUY_TRADE_PAYLOAD_SCHEMA:
                raise ProtocolContractError(ProtocolContractErrorCode.UNSUPPORTED_PAYLOAD_SCHEMA)
            # Decode all actor-bearing inputs before attempting the atomic state commit.
            payload = decode_copybuy_trade_payload(event.protocol_payload)
            state_events.append(
                replace(
                    event,
                    protocol_payload_schema=PUMPFUN_TRADE_PAYLOAD_SCHEMA_ID,
                    # Only the reducer input drops actor bytes; emitted signals retain the original
                    # event.
                    protocol_payload=encode_trade_payload(payload.state_after),
                )
            )
            if event.sold_asset_id == self.quote_asset_id:
                signals.append(_signal(event, payload.signing_wallet))
        # This internal state projection never rewrites stored bytes or invents an event.
        self.apply_historical_group(tuple(state_events), effective_at_unix_s=effective_at_unix_s)
        return tuple(signals)

    def current_price(self, intent: CopyBuyIntent) -> TokenPrice | None:
        """The decision price is marginal and excludes fees and own market impact."""
        state = self._intent_curve(intent).state
        if state.lifecycle is not PumpCurveLifecycle.ACTIVE:
            return None
        return TokenPrice(state.virtual_sol_reserves_lamports, state.virtual_token_reserves_atomic)


def _signal(event: VenueTradeEvent, signing_wallet: AccountId) -> CopyBuySignal:
    """Retain the original source occurrence and winning signer in position identity."""
    return CopyBuySignal(
        event_id=event.envelope.canonical_event_id,
        position=event.envelope.position,
        signing_wallet=signing_wallet,
        asset_id=event.bought_asset_id,
        # Signal venue and quote denomination come from the canonical successful buy.
        venue_id=event.venue_id,
        # The actual historical BUY fixes the quote asset; no payer inference occurs.
        quote_asset_id=event.sold_asset_id,
    )
