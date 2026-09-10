"""Core-owned seams for a copy-buy strategy and an atomic historical venue."""

from typing import Protocol

from backtest.domain.account_requirements import AccountRequirement
from backtest.domain.chain import ChainPosition
from backtest.domain.copytrading import CopyBuyIntent, CopyBuyPolicy, CopyBuySignal, TokenPrice
from backtest.domain.identifiers import AccountId, BundleId, ContentDigest, ProtocolPayloadSchemaId

# Atomic group inputs carry canonical event identity and causality metadata.
from backtest.domain.market_events import CanonicalEvent

# Execution quotes and asset-tagged account requirements retain their shared semantics.
from backtest.engine.sniping_contracts import ProtocolQuote, ValuationQuote


class CopyBuyStrategy(Protocol):
    """Entry consumption belongs to strategy; all money belongs to the ledger."""

    policy: CopyBuyPolicy
    bundle_id: BundleId
    component_id: ContentDigest

    @property
    def signing_wallets(self) -> tuple[AccountId, ...]: ...

    def decide(
        self, signal: CopyBuySignal, *, decision_position: ChainPosition
    ) -> CopyBuyIntent | None:
        """Consume the first eligible mint before quotation or balance checks."""
        ...


class CopyBuyProtocolRuntime(Protocol):
    """Historical and observed views are separate instances of this atomic reducer."""

    @property
    def bundle_id(self) -> BundleId: ...

    @property
    def trade_payload_schema_id(self) -> ProtocolPayloadSchemaId: ...

    def apply_group(
        self, events: tuple[CanonicalEvent, ...], *, effective_at_unix_s: int
    ) -> tuple[CopyBuySignal, ...]:
        """Apply one whole source transaction before exposing any real BUY signal."""
        ...

    def current_price(self, intent: CopyBuyIntent) -> TokenPrice | None:
        """Return active marginal price without fees or simulated order impact."""
        ...

    def quote_buy(self, intent: CopyBuyIntent, *, effective_at_unix_s: int) -> ProtocolQuote:
        """Quote the fixed gross budget including protocol component fees."""
        ...

    def quote_sell(
        self, intent: CopyBuyIntent, *, tokens_in_atomic: int, effective_at_unix_s: int
    ) -> ProtocolQuote:
        """Quote a full exit with explicit strict or synthetic liquidity evidence."""
        ...

    def account_requirements(self, intent: CopyBuyIntent) -> tuple[AccountRequirement, ...]:
        """Describe the mode-specific accounts independently of their rent price."""
        ...

    def valuation_quote(
        self, intent: CopyBuyIntent, *, tokens_in_atomic: int, effective_at_unix_s: int
    ) -> ValuationQuote | None:
        """Value remaining tokens without silently executing an end-of-run sale."""
        ...
