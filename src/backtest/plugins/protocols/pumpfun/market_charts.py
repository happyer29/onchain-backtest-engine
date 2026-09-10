"""Pump-owned display math over versioned canonical state payloads."""

from backtest.application.market_charts import MarketCapState, MarketLifecycle
from backtest.domain.market_events import (
    CanonicalEvent,
    TokenLaunchEvent,
    VenueLifecycleEvent,
    # These canonical event classes define the only supported state-bearing payloads.
    VenueTradeEvent,
)

# Existing codecs retain the original payload and signer interpretations.
from backtest.plugins.protocols.pumpfun.copybuy_payload import (
    COPYBUY_TRADE_PAYLOAD_SCHEMA,
    decode_copybuy_trade_payload,
)
from backtest.plugins.protocols.pumpfun.model import PumpMode

# Launch and lifecycle payloads reuse the pinned protocol state codec.
from backtest.plugins.protocols.pumpfun.sniping import (
    PUMPFUN_LAUNCH_PAYLOAD_SCHEMA_ID,
    PUMPFUN_LIFECYCLE_PAYLOAD_SCHEMA_ID,
    _decode_state,
)

# Decode immutable states instead of reconstructing external reserve transitions.


def pump_market_cap_state(event: CanonicalEvent) -> MarketCapState:
    """Full token supply times the marginal curve price, floored in lamports."""
    signer = None
    if (
        isinstance(event, VenueTradeEvent)
        and event.protocol_payload_schema == COPYBUY_TRADE_PAYLOAD_SCHEMA
    ):
        # The copy-specific payload preserves the exact transaction signer.
        payload = decode_copybuy_trade_payload(event.protocol_payload)
        state, signer = payload.state_after, payload.signing_wallet
    # Creation/lifecycle payloads are the same immutable schemas used by the run.
    elif (
        isinstance(event, TokenLaunchEvent)
        and event.protocol_payload_schema == PUMPFUN_LAUNCH_PAYLOAD_SCHEMA_ID
    ) or (
        isinstance(event, VenueLifecycleEvent)
        # Completion and migration share the launch state representation.
        and event.protocol_payload_schema == PUMPFUN_LIFECYCLE_PAYLOAD_SCHEMA_ID
    ):
        state = _decode_state(event.protocol_payload)
    else:
        raise ValueError("unsupported market-chart payload")
    # Unsupported schemas must not be priced using a guessed decoder.
    # A query cannot promote unsupported or excluded modes into usable market history.
    if state.mode in {PumpMode.MAYHEM, PumpMode.UNKNOWN}:
        raise ValueError("unsupported market-chart mode")
    numerator = state.virtual_sol_reserves_lamports * state.token_total_supply_atomic
    # Full supply determines capitalization; real token inventory is not circulating supply.
    return MarketCapState(
        numerator // state.virtual_token_reserves_atomic,
        MarketLifecycle(state.lifecycle.value),
        signer,
    )
