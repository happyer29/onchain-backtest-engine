"""Signer fidelity, immutable source identity and batch-independent normalization."""

import json
from dataclasses import replace

import pytest
import test_pumpfun_live_normalizer as source
import test_pumpfun_projector as projection

# Compare against existing exact fixtures, not a second independent curve codec.
from backtest.application.models import CapabilityStream
from backtest.domain.event_hashing import canonical_event_digest
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import AccountId, CapabilityId
from backtest.domain.market_events import EventKindName, VenueTradeEvent

# Payload rejection uses the same stable protocol-contract boundary as execution.
from backtest.engine.sniping_contracts import ProtocolContractError
from backtest.plugins.protocols.pumpfun.copybuy_normalizer import PumpfunCopyBuyLiveNormalizer
from backtest.plugins.protocols.pumpfun.copybuy_payload import (
    COPYBUY_TRADE_PAYLOAD_SCHEMA,
    COPYBUY_UNIVERSE_POLICY_ID,
    # The copy schema and exclusion policy have identities separate from old Sniping payloads.
    CopyBuyTradePayload,
    decode_copybuy_trade_payload,
)

# Existing normalizer errors must remain sticky for malformed source signers.
from backtest.plugins.protocols.pumpfun.live_normalizer import PumpfunLiveNormalizationError
from backtest.plugins.protocols.pumpfun.projector import PumpfunProtocolProjector
from backtest.plugins.protocols.pumpfun.sniping import encode_trade_payload


def test_payload_roundtrip_preserves_actor_and_integer_state() -> None:
    # Payer and creator are deliberately absent from this versioned contract.
    state = projection._pump_state(projection._STATE)
    payload = CopyBuyTradePayload(AccountId(source._key(11)), state)
    assert decode_copybuy_trade_payload(payload.encode()) == payload
    assert json.loads(payload.encode())["state_after"] == json.loads(encode_trade_payload(state))


@pytest.mark.parametrize("actor", (None, 123, "", "payer", "1" * 31, "1" * 33, " 1" * 32))
def test_payload_rejects_unproven_actor(actor: object) -> None:
    # Even otherwise valid state must never compensate for a missing exact signer.
    state = projection._pump_state(projection._STATE)
    document = {"signing_wallet": actor, "state_after": json.loads(encode_trade_payload(state))}
    with pytest.raises(ProtocolContractError):
        decode_copybuy_trade_payload(canonical_json_bytes(document))


def test_payload_rejects_legacy_and_noncanonical_json() -> None:
    # No replay-time enrichment, duplicate-key acceptance or whitespace normalization.
    state = projection._pump_state(projection._STATE)
    payload = CopyBuyTradePayload(AccountId(source._key(11)), state).encode()
    for invalid in (encode_trade_payload(state), payload + b" ", b"[]", b"\xff"):
        with pytest.raises(ProtocolContractError):
            decode_copybuy_trade_payload(invalid)


@pytest.mark.parametrize("physical", ("creator", "fee_payer", "user", "payer"))
def test_copy_projection_rejects_signer_substitution(physical: str) -> None:
    """A valid public key from another field still cannot identify the copied wallet."""
    base = projection._spec(EventKindName.VENUE_TRADE)
    with pytest.raises(ValueError, match="exact signing_wallet"):
        replace(
            base,
            # The semantic name cannot legitimize a different physical source column.
            protocol_payload_schema_id=COPYBUY_TRADE_PAYLOAD_SCHEMA,
            columns=(*base.columns, ("signing_wallet", physical)),
        )


def test_signer_changes_content_but_not_source_occurrence() -> None:
    # Copy payload selection is explicit in the projection configuration.
    base = projection._spec(EventKindName.VENUE_TRADE)
    spec = replace(
        base,
        protocol_payload_schema_id=COPYBUY_TRADE_PAYLOAD_SCHEMA,
        columns=(*base.columns, ("signing_wallet", "signing_wallet")),
        # The physical signer mapping is explicit and cannot fall back to creator or payer.
    )
    kinds = tuple(projection._CAPABILITIES)
    # Every other event kind retains its original schema and identity rules.
    projector = PumpfunProtocolProjector(
        network_id=source.SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=source.BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        specs=tuple(spec if kind == base.kind else projection._spec(kind) for kind in kinds),
    )
    # Two projections of one exact source occurrence differ only in actor content.
    row = {
        **projection._event_row(event_index=2),
        **projection._STATE,
        "side": "BUY",
        "base_amount_atomic": 100,
        # Quote amounts and fee components remain unchanged when only the signer changes.
        "quote_amount_atomic": 200,
        "creator_fee_atomic": 1,
        "protocol_fee_atomic": 2,
        "signing_wallet": source._key(11),
    }
    # Changing actor bytes must affect canonical content without changing source occurrence
    # identity.
    first = projection._project(projector, base.kind, row)
    row["signing_wallet"] = source._key(12)
    # Source/event/group identities cannot be reconstructed from changing payload bytes.
    second = projection._project(projector, base.kind, row)
    assert isinstance(first, VenueTradeEvent)
    assert first.envelope == second.envelope
    assert canonical_event_digest(first) != canonical_event_digest(second)
    # The decoded payload must retain the original signing wallet exactly.
    assert decode_copybuy_trade_payload(first.protocol_payload).signing_wallet.value == source._key(
        11
    )


def test_copy_projection_requires_signer_column() -> None:
    # Declaring the payload alone cannot upgrade a legacy mapping's fidelity.
    with pytest.raises(ValueError, match="signing_wallet"):
        replace(
            projection._spec(EventKindName.VENUE_TRADE),
            protocol_payload_schema_id=COPYBUY_TRADE_PAYLOAD_SCHEMA,
        )


def test_normalizer_preserves_signer_and_batch_independent_digest() -> None:
    # Both profiles share exact fee/reserve transforms; actor transport is additive.
    legacy = source._normalizer()
    copy = PumpfunCopyBuyLiveNormalizer(legacy.fee_profile)
    assert copy.config_digest != legacy.config_digest
    rows = tuple(source._trade_row(transaction=index, raw_instruction=1) for index in (1, 2))
    # A single batch and two driver batches must yield identical canonical rows/digests.
    whole, whole_summary = _normalize(copy, (rows,))
    split, split_summary = _normalize(copy, tuple((row,) for row in rows))
    assert whole == split
    assert whole_summary == split_summary
    # The existing Sniping output keeps its byte-level trade shape.
    old, _ = _normalize(legacy, (rows,))
    assert tuple(row[:-1] for row in whole) == old
    assert all(row[-1] == source._key(11) for row in whole)
    assert copy.launch_universe_policy_id == COPYBUY_UNIVERSE_POLICY_ID


@pytest.mark.parametrize("signer", (None, "bad", "1" * 31))
def test_normalizer_rejects_signer_even_with_valid_fee_payer(signer: object) -> None:
    # Raw payer stays valid, proving it is never a fallback for signing_wallet.
    normalizer = PumpfunCopyBuyLiveNormalizer(source._normalizer().fee_profile)
    row = source._trade_row(transaction=1, raw_instruction=1)
    row["signing_wallet"] = signer
    with pytest.raises(PumpfunLiveNormalizationError):
        _normalize(normalizer, ((row,),))


def _normalize(normalizer, batches):
    """Run the same bounded source shard under different driver batch partitions."""
    stream = CapabilityStream.PUMP_CURVE_TRADE
    capability = CapabilityId("pumpfun.curve-trade.v2")
    session = normalizer.begin(
        stream=stream, capability_id=capability, covered_range=source._range(10, 11)
    )
    # The same bounded normalization session accepts different physical batch splits.
    output = []
    # Only normalizer output participates in equality, not transient batch provenance.
    for rows in batches:
        output.extend(
            session.normalize(
                source._batch(normalizer, capability, stream, source._range(10, 11), rows)
            ).rows
            # Finish validates cross-batch observations after all selected source rows arrive.
        )
    return tuple(output), session.finish()
