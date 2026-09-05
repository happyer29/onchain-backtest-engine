"""Canonical semantic stream normalization shared by engine and result sinks."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from backtest.domain.execution import Fill
from backtest.domain.hashing import canonical_json_bytes

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import ContentDigest
from backtest.domain.ledger import LedgerTransaction, Posting


class CanonicalStreamHasher:
    """Length-framed hash so record boundaries cannot be ambiguous."""

    def __init__(self, domain: str) -> None:
        # Execute the canonical stream hasher init workflow in explicit, reviewable steps.
        if not domain or domain != domain.strip() or "\x00" in domain:
            raise ValueError("stream hash domain must be non-empty, trimmed and NUL-free")
        self._hash = hashlib.sha256(domain.encode("utf-8") + b"\x00")
        self._count = 0

    def append(self, value: object) -> None:
        # Execute the canonical stream hasher append workflow in explicit, reviewable
        # steps.
        encoded = canonical_json_bytes(value)
        self.append_canonical_bytes(encoded)

    def append_canonical_bytes(self, encoded: bytes) -> None:
        """Append trusted canonical JSON bytes without rebuilding Python objects.

        The method is intentionally narrow: callers are deterministic engine/output
        implementations that already own the canonical encoder.  Untrusted input must
        still pass through :meth:`append`, which canonicalizes it first.
        """

        if not isinstance(encoded, bytes) or not encoded:
            raise ValueError("canonical stream record must be non-empty bytes")
        self._hash.update(len(encoded).to_bytes(8, "big"))
        self._hash.update(encoded)
        self._count += 1

    # Apply property semantics to the following canonical stream hasher count contract.
    @property
    def count(self) -> int:
        return self._count

    @property
    def digest(self) -> ContentDigest:
        # Return the completed canonical stream hasher digest result without a hidden
        # fallback.
        return ContentDigest(self._hash.hexdigest())


def posting_documents(postings: Iterable[Posting]) -> list[dict[str, object]]:
    # Execute the posting documents workflow in explicit, reviewable steps.
    values: list[dict[str, object]] = [
        {
            "account_id": posting.account.account_id.value,
            "account_kind": posting.account.kind.value,
            "amount_atomic": posting.amount_atomic,
            # Keep the asset id component named inside the values contract.
            "asset_id": posting.asset_id.value,
        }
        for posting in postings
    ]
    return sorted(values, key=_posting_document_sort_key)


# Define ledger document as one focused operation with an explicit boundary.
def ledger_document(transaction: LedgerTransaction) -> dict[str, object]:
    # Execute the ledger document workflow in explicit, reviewable steps.
    return {
        "boundary_ordinal": transaction.boundary_ordinal,
        "correlation_id": transaction.correlation_id.hex,
        "correlation_kind": transaction.correlation_kind.value,
        "postings": posting_documents(transaction.postings),
        # Include reason in the completed ledger document result.
        "reason": transaction.reason,
        "transaction_id": transaction.transaction_id.hex,
    }


def fill_document(fill: Fill) -> dict[str, object]:
    # Execute the fill document workflow in explicit, reviewable steps.
    return {
        "amount_in_atomic": fill.amount_in_atomic,
        "amount_out_atomic": fill.amount_out_atomic,
        "boundary_ordinal": fill.boundary_ordinal,
        "bought_asset_id": fill.bought_asset_id.value,
        # Include fee amount atomic in the completed fill document result.
        "fee_amount_atomic": fill.fee_amount_atomic,
        "order_id": fill.order_id.hex,
        "pool_id": fill.pool_id.value,
        "sold_asset_id": fill.sold_asset_id.value,
    }


# Define posting document sort key as one focused operation with an explicit boundary.
def _posting_document_sort_key(value: dict[str, object]) -> tuple[str, str, int]:
    # Execute the posting document sort key workflow in explicit, reviewable steps.
    account_id = value["account_id"]
    asset_id = value["asset_id"]
    amount = value["amount_atomic"]
    if (
        not isinstance(account_id, str)
        # Keep isinstance visible while evaluating the isinstance, account id and asset id
        # guard.
        or not isinstance(asset_id, str)
        or not isinstance(amount, int)
    ):
        raise TypeError("internal posting document has invalid field types")
    return account_id, asset_id, amount


# Bind all once as an explicit module-level contract.
__all__ = [
    "CanonicalStreamHasher",
    "fill_document",
    "ledger_document",
    "posting_documents",
    # Complete the all group only after its semantic components are visible.
]
