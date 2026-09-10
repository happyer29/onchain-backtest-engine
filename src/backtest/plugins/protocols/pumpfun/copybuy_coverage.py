"""Canonical signal coverage shared by bounded inspection and pre-root validation."""

from backtest.application.copy_source import CopySourceSelection
from backtest.domain.identifiers import AssetId, ContentDigest
from backtest.domain.market_events import CanonicalEvent, VenueTradeEvent, canonical_event_sort_key
from backtest.engine.sniping_contracts import ProtocolContractError, ProtocolContractErrorCode

# This read-only proof digest has no strategy access to future events or source statistics.
from backtest.plugins.protocols.pumpfun.copybuy_payload import (
    COPYBUY_TRADE_PAYLOAD_SCHEMA,
    decode_copybuy_trade_payload,
)
from backtest.plugins.protocols.pumpfun.live_normalizer import _OrderedDigest


class CopySignalCoverage:
    """Hash every eligible historical buy, including later same-mint purchases."""

    def __init__(self, selection: CopySourceSelection, *, maximum_mints: int) -> None:
        """Bound proof memory independently of input batch layout."""
        if type(maximum_mints) is not int or maximum_mints < 1:
            raise ValueError("copy coverage needs a positive mint cap")
        self.selection, self.maximum_mints = selection, maximum_mints
        self._wallets = frozenset(selection.signing_wallets)
        # The ordered digest binds selection even when there are zero eligible purchases.
        self._digest = _OrderedDigest(
            "backtest.pumpfun-copy-signal-coverage.v1", selection.document()
        )
        # Coverage retains only distinct mints and the last ordered occurrence key.
        self._mints: set[AssetId] = set()
        self._previous: tuple[str, str, int, str, int, str] | None = None
        self.count = 0

    def consume(self, event: CanonicalEvent) -> bool:
        """All trade actors must be valid before any eligible signal can enter the proof."""
        if not isinstance(event, VenueTradeEvent):
            return False
        if event.protocol_payload_schema != COPYBUY_TRADE_PAYLOAD_SCHEMA:
            raise ProtocolContractError(ProtocolContractErrorCode.UNSUPPORTED_PAYLOAD_SCHEMA)
        payload = decode_copybuy_trade_payload(event.protocol_payload)
        # Wallet and decision filters never alter the all-signer market stream itself.
        if (
            event.sold_asset_id != AssetId("SOL")
            or payload.signing_wallet not in self._wallets
            or not self.selection.decision_range.contains_position(event.envelope.position)
        ):
            # Unselected actors still affect market state but do not enter leader signal coverage.
            return False
        key = canonical_event_sort_key(event)
        if self._previous is not None and key <= self._previous:
            raise ValueError("copy signal coverage is unordered or duplicated")
        # A deterministic occurrence ID already binds its exact original chain position.
        self._digest.update(
            {
                "event_id": event.envelope.canonical_event_id.hex,
                "signing_wallet": payload.signing_wallet.value,
            }
            # Canonical framing binds original event identity and exact signing wallet.
        )
        self._previous = key
        self._mints.add(event.bought_asset_id)
        self.count += 1
        if len(self._mints) > self.maximum_mints:
            # Exceeding the coverage memory cap rejects the cut instead of sampling signals.
            raise ValueError("copy signal coverage mint limit exceeded")
        return True

    @property
    def mint_count(self) -> int:
        """The bounded set is evidence only and is never passed into strategy decisions."""
        return len(self._mints)

    @property
    def digest(self) -> ContentDigest:
        """The same canonical bytes are recomputed after extraction before publication."""
        return self._digest.digest()
