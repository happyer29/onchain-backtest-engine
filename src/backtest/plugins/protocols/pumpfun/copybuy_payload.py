"""Strict signer-bearing Pump payload; source identity is never reconstructed."""

from __future__ import annotations

import json
from dataclasses import dataclass

# Core sees an opaque protocol payload, while the plugin validates its meaning.
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import AccountId, ProtocolPayloadSchemaId
from backtest.engine.sniping_contracts import ProtocolContractError, ProtocolContractErrorCode
from backtest.plugins.protocols.pumpfun.live_normalizer import _public_key
from backtest.plugins.protocols.pumpfun.model import PumpCurveStateV1

# Reuse exactly the existing integer curve codec instead of maintaining another one.
from backtest.plugins.protocols.pumpfun.sniping import _decode_state, encode_trade_payload

COPYBUY_TRADE_PAYLOAD_SCHEMA = ProtocolPayloadSchemaId("pumpfun-copybuy-trade-payload-v1")
COPYBUY_UNIVERSE_POLICY_ID = "successful-sol-paired-non-mayhem-pumpfun-copy-buys-v1"


@dataclass(frozen=True, slots=True)
class CopyBuyTradePayload:
    """One source signer plus its causally effective post-trade curve state."""

    signing_wallet: AccountId
    state_after: PumpCurveStateV1

    def __post_init__(self) -> None:
        # Canonical input rejects unknown, truncated, padded, or non-Solana addresses.
        if not isinstance(self.signing_wallet, AccountId):
            raise TypeError("signing_wallet must be an AccountId")
        if _public_key(self.signing_wallet.value) != self.signing_wallet.value:
            raise ValueError("signing_wallet must be canonical")
        # The opaque payload always carries the same validated integer state as Sniping.
        if not isinstance(self.state_after, PumpCurveStateV1):
            raise TypeError("state_after must be PumpCurveStateV1")

    def encode(self) -> bytes:
        """Both signer and curve state enter immutable canonical content bytes."""
        return canonical_json_bytes(
            {
                "signing_wallet": self.signing_wallet.value,
                "state_after": json.loads(encode_trade_payload(self.state_after)),
            }
            # Canonical bytes bind the original signer together with the verified post-trade state.
        )


def decode_copybuy_trade_payload(payload: bytes) -> CopyBuyTradePayload:
    """Reject signerless or ambiguous payloads before a strategy can see a BUY."""
    try:
        document = json.loads(payload)
        if not isinstance(document, dict) or set(document) != {"signing_wallet", "state_after"}:
            raise ValueError("copy-buy payload fields do not match its schema")
        # Exact serialization rejects duplicate keys and alternative numeric spellings.
        if canonical_json_bytes(document) != payload:
            raise ValueError("copy-buy payload is not canonical")
        return CopyBuyTradePayload(
            AccountId(document["signing_wallet"]),
            _decode_state(canonical_json_bytes(document["state_after"])),
            # Nested state decoding uses the same strict curve-state contract as historical replay.
        )
    except (TypeError, ValueError, UnicodeDecodeError) as error:
        # Surface a stable contract error, never a missing-signer fallback.
        raise ProtocolContractError(ProtocolContractErrorCode.MALFORMED_PROTOCOL_PAYLOAD) from error
