# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from typing import cast

import pytest

from backtest.domain.identifiers import AccountId, AssetId, ContentDigest
from backtest.domain.ledger import (
    # Include account kind so the ledger dependency remains explicit.
    AccountKind,
    LedgerAccount,
    LedgerCorrelationKind,
    LedgerTransaction,
    Posting,
    # Close the ledger import after its required symbols are visible.
)
from backtest.engine.audit import ledger_document


def _postings() -> tuple[Posting, ...]:
    # Execute the postings workflow in explicit, reviewable steps.
    asset_id = AssetId("SOL")
    return (
        Posting(
            LedgerAccount(AccountId("portfolio:available:SOL"), AccountKind.PORTFOLIO_AVAILABLE),
            asset_id,
            # Keep posting, asset id and ledger account visible while completing Posting
            # within postings.
            -100,
        ),
        Posting(
            LedgerAccount(AccountId("venue:SOL"), AccountKind.VENUE),
            asset_id,
            # Keep posting, asset id and ledger account visible while completing Posting
            # within postings.
            100,
        ),
    )


def test_ledger_transaction_requires_typed_correlation_and_exports_it() -> None:
    # Execute the test ledger transaction requires typed correlation and exports it
    # workflow in explicit, reviewable steps.
    transaction = LedgerTransaction(
        transaction_id=ContentDigest("1" * 64),
        correlation_kind=LedgerCorrelationKind.ORDER,
        correlation_id=ContentDigest("2" * 64),
        boundary_ordinal=17,
        # Keep the postings _postings step visible while building transaction.
        postings=_postings(),
        reason="ORDER_SETTLEMENT",
    )

    assert ledger_document(transaction) == {
        "boundary_ordinal": 17,
        # Keep the correlation id expectation tied to ledger document, transaction and
        # boundary ordinal in this scenario.
        "correlation_id": "2" * 64,
        "correlation_kind": "ORDER",
        "postings": [
            {
                "account_id": "portfolio:available:SOL",
                # Keep the account kind expectation tied to ledger document, transaction
                # and boundary ordinal in this scenario.
                "account_kind": "PORTFOLIO_AVAILABLE",
                "amount_atomic": -100,
                "asset_id": "SOL",
            },
            {
                # Keep the account id expectation tied to ledger document, transaction and
                # boundary ordinal in this scenario.
                "account_id": "venue:SOL",
                "account_kind": "VENUE",
                "amount_atomic": 100,
                "asset_id": "SOL",
            },
            # Verify the ledger document, transaction and boundary ordinal relationship before
            # this scenario is accepted.
        ],
        "reason": "ORDER_SETTLEMENT",
        "transaction_id": "1" * 64,
    }


def test_ledger_transaction_rejects_raw_string_correlation_kind() -> None:
    # Execute the test ledger transaction rejects raw string correlation kind workflow in
    # explicit, reviewable steps.
    with pytest.raises(TypeError, match="correlation kind"):
        # Keep raises, type error and pytest active only for the bounded test ledger
        # transaction rejects raw string correlation kind operation.
        LedgerTransaction(
            transaction_id=ContentDigest("1" * 64),
            correlation_kind=cast(LedgerCorrelationKind, "ORDER"),
            correlation_id=ContentDigest("2" * 64),
            boundary_ordinal=17,
            # Pass postings explicitly to LedgerTransaction for 1 and order.
            postings=_postings(),
            reason="ORDER_SETTLEMENT",
        )


def test_ledger_transaction_rejects_raw_string_correlation_id() -> None:
    # Execute the test ledger transaction rejects raw string correlation id workflow in
    # explicit, reviewable steps.
    with pytest.raises(TypeError, match="correlation ID"):
        # Keep raises, type error and pytest active only for the bounded test ledger
        # transaction rejects raw string correlation id operation.
        LedgerTransaction(
            transaction_id=ContentDigest("1" * 64),
            correlation_kind=LedgerCorrelationKind.ROUNDTRIP,
            correlation_id=cast(ContentDigest, "2" * 64),
            boundary_ordinal=17,
            # Pass postings explicitly to LedgerTransaction for 1 and 2.
            postings=_postings(),
            reason="BUY_SETTLEMENT",
        )
