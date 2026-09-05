"""Append-only double-entry ledger contracts in integer atomic units."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum

from backtest.domain.identifiers import AccountId, AssetId, ContentDigest


# Keep the account kind contract and validation rules together.
class AccountKind(StrEnum):
    PORTFOLIO_AVAILABLE = "PORTFOLIO_AVAILABLE"
    PORTFOLIO_RESERVED = "PORTFOLIO_RESERVED"
    PORTFOLIO_LOCKED = "PORTFOLIO_LOCKED"
    RECEIVABLE = "RECEIVABLE"
    # Declare venue explicitly in the account kind contract.
    VENUE = "VENUE"
    PROTOCOL_FEE = "PROTOCOL_FEE"
    CREATOR_FEE = "CREATOR_FEE"
    NETWORK_FEE = "NETWORK_FEE"
    EXTERNAL = "EXTERNAL"


# Keep the ledger correlation kind contract and validation rules together.
class LedgerCorrelationKind(StrEnum):
    """Typed owner of one immutable ledger transaction."""

    ORDER = "ORDER"
    ROUNDTRIP = "ROUNDTRIP"


# Keep the ledger account contract and validation rules together.
@dataclass(frozen=True, slots=True)
class LedgerAccount:
    account_id: AccountId
    kind: AccountKind


# Keep the posting contract and validation rules together.
@dataclass(frozen=True, slots=True)
class Posting:
    account: LedgerAccount
    asset_id: AssetId
    amount_atomic: int

    # Define posting post init as one focused operation with an explicit boundary.
    def __post_init__(self) -> None:
        # Execute the posting post init workflow in explicit, reviewable steps.
        if isinstance(self.amount_atomic, bool) or not isinstance(self.amount_atomic, int):
            raise TypeError("posting amount must be an integer")
        if self.amount_atomic == 0:
            raise ValueError("zero-value postings are forbidden")


# Keep the ledger transaction contract and validation rules together.
@dataclass(frozen=True, slots=True)
class LedgerTransaction:
    transaction_id: ContentDigest
    correlation_kind: LedgerCorrelationKind
    correlation_id: ContentDigest
    # Declare boundary ordinal explicitly in the ledger transaction contract.
    boundary_ordinal: int
    postings: tuple[Posting, ...]
    reason: str

    def __post_init__(self) -> None:
        # Execute the ledger transaction post init workflow in explicit, reviewable steps.
        if not isinstance(self.correlation_kind, LedgerCorrelationKind):
            raise TypeError("ledger correlation kind must be a LedgerCorrelationKind")
        if not isinstance(self.correlation_id, ContentDigest):
            raise TypeError("ledger correlation ID must be a ContentDigest")
        if self.boundary_ordinal < 0:
            # Fail the ledger transaction post init path with ValueError for ledger
            # boundary must be non-negative when boundary ordinal is true; do not continue
            # ambiguously.
            raise ValueError("ledger boundary must be non-negative")
        if not self.reason or self.reason != self.reason.strip():
            raise ValueError("ledger reason must be non-empty and trimmed")
        if len(self.postings) < 2:
            raise ValueError("double-entry transaction requires at least two postings")
        # Assemble totals once so the ledger transaction post init workflow shares one
        # value.
        totals: defaultdict[AssetId, int] = defaultdict(int)
        for posting in self.postings:
            totals[posting.asset_id] += posting.amount_atomic
        if any(total != 0 for total in totals.values()):
            raise ValueError("ledger postings must conserve every asset")


# Bind all once as an explicit module-level contract.
__all__ = [
    "AccountKind",
    "LedgerAccount",
    "LedgerCorrelationKind",
    "LedgerTransaction",
    # Keep the posting component named inside the all contract.
    "Posting",
]
