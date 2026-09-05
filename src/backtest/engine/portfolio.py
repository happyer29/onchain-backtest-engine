"""Atomic reference portfolio reducer backed by the double-entry ledger.

The reducer intentionally keeps only current balances and a transaction count.
The append-only transaction stream belongs to the injected run sink, otherwise
long replays would retain the complete ledger in private Python memory.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass

from backtest.domain.identifiers import AccountId, AssetId

# Import ledger at the visible module dependency boundary.
from backtest.domain.ledger import AccountKind, LedgerTransaction


class PortfolioInvariantError(RuntimeError):
    """The proposed transaction would violate a portfolio invariant."""


@dataclass(frozen=True, slots=True)
class PortfolioCommit:
    """Opaque, already validated candidate used for a no-fail commit."""

    balances: dict[tuple[AccountId, AssetId], int]
    account_kinds: dict[AccountId, AccountKind]


# Keep the portfolio state contract and validation rules together.
class PortfolioState:
    def __init__(self, initial_available: Mapping[AssetId, int]) -> None:
        # Execute the portfolio state init workflow in explicit, reviewable steps.
        self._balances: defaultdict[tuple[AccountId, AssetId], int] = defaultdict(int)
        self._account_kinds: dict[AccountId, AccountKind] = {}
        self._transaction_count = 0
        for asset_id, amount in initial_available.items():
            # Process initial_available.items() inside the bounded portfolio state init
            # loop.
            if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
                raise ValueError("initial portfolio balances must be non-negative integers")
            account_id = available_account_id(asset_id)
            self._account_kinds[account_id] = AccountKind.PORTFOLIO_AVAILABLE
            self._balances[(account_id, asset_id)] = amount

    # Define portfolio state preview as one focused operation with an explicit boundary.
    def preview(self, transaction: LedgerTransaction) -> PortfolioCommit:
        """Validate a transaction without mutating live portfolio state."""

        candidate = dict(self._balances)
        candidate_kinds = dict(self._account_kinds)
        for posting in transaction.postings:
            # Process transaction.postings inside the bounded portfolio state preview
            # loop.
            account_id = posting.account.account_id
            known_kind = candidate_kinds.get(account_id)
            if known_kind is not None and known_kind is not posting.account.kind:
                raise PortfolioInvariantError("ledger account kind changed")
            candidate_kinds[account_id] = posting.account.kind
            # Assemble key once so the portfolio state preview workflow shares one value.
            key = (account_id, posting.asset_id)
            candidate[key] = candidate.get(key, 0) + posting.amount_atomic
            if (
                posting.account.kind
                in {
                    # Keep account kind visible while evaluating the kind, account and
                    # portfolio available guard.
                    AccountKind.PORTFOLIO_AVAILABLE,
                    AccountKind.PORTFOLIO_RESERVED,
                    AccountKind.PORTFOLIO_LOCKED,
                    AccountKind.RECEIVABLE,
                }
                # Keep candidate visible while evaluating the kind, account and portfolio
                # available guard.
                and candidate[key] < 0
            ):
                raise PortfolioInvariantError("portfolio balance would become negative")
        return PortfolioCommit(candidate, candidate_kinds)

    def commit(self, candidate: PortfolioCommit) -> None:
        """Commit a candidate returned by :meth:`preview` without validation."""

        self._balances = defaultdict(int, candidate.balances)
        self._account_kinds = dict(candidate.account_kinds)
        self._transaction_count += 1

    def apply(self, transaction: LedgerTransaction) -> None:
        self.commit(self.preview(transaction))

    # Define portfolio state available as one focused operation with an explicit boundary.
    def available(self, asset_id: AssetId) -> int:
        return self._balances[(available_account_id(asset_id), asset_id)]

    def reserved(self, asset_id: AssetId) -> int:
        return self._balances[(reserved_account_id(asset_id), asset_id)]

    @property
    # Define portfolio state transaction count as one focused operation with an explicit
    # boundary.
    def transaction_count(self) -> int:
        return self._transaction_count

    def semantic_balances(self) -> tuple[tuple[str, str, str, int], ...]:
        """Return a canonical sparse balance projection for result hashing."""

        rows = (
            (
                account_id.value,
                self._account_kinds[account_id].value,
                asset_id.value,
                # Keep the amount component named inside the rows contract.
                amount,
            )
            for (account_id, asset_id), amount in self._balances.items()
            if amount != 0
        )
        # Return the completed portfolio state semantic balances result without a hidden
        # fallback.
        return tuple(sorted(rows))


def available_account_id(asset_id: AssetId) -> AccountId:
    return AccountId(f"portfolio:available:{asset_id.value}")


def reserved_account_id(asset_id: AssetId) -> AccountId:
    return AccountId(f"portfolio:reserved:{asset_id.value}")


# Bind all once as an explicit module-level contract.
__all__ = [
    "PortfolioCommit",
    "PortfolioInvariantError",
    "PortfolioState",
    "available_account_id",
    # Keep the reserved account id component named inside the all contract.
    "reserved_account_id",
]
