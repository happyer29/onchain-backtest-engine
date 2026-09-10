"""Independent copy position/summary reconciliation against emitted ledger postings."""

from backtest.application.run_results import CopySummaryMetadata
from backtest.domain.identifiers import AssetId, ContentDigest
from backtest.domain.ledger import AccountKind, LedgerCorrelationKind, LedgerTransaction
from backtest.engine.copytrading_execution import CopyAttemptStatus

# Immutable row projections and fixed-size totals are independently checked against postings.
from backtest.engine.copytrading_results import CopyPositionRecord
from backtest.engine.copytrading_run import CopyTotalsAccumulator


class CopyLedgerReconciler:
    """Keep bounded per-position sums until the corresponding terminal result arrives."""

    def __init__(self) -> None:
        self._pending: dict[ContentDigest, dict[tuple[AccountKind, AssetId], int]] = {}
        self._seen: set[ContentDigest] = set()
        self._synthetic: dict[ContentDigest, dict[tuple[str, AssetId], int]] = {}
        self._totals = CopyTotalsAccumulator()

    # Financial rows arrive before their bounded terminal position in the output stream.

    def append_ledger(self, transaction: LedgerTransaction) -> None:
        """No uncorrelated posting or late posting may escape terminal row reconciliation."""
        identity = transaction.correlation_id
        if (
            transaction.correlation_kind is not LedgerCorrelationKind.ROUNDTRIP
            or identity in self._seen
        ):
            # A position cannot receive more postings after its terminal row was reconciled.
            raise ValueError("copy ledger has an invalid or completed position correlation")
        # Keep one asset-tagged accumulator per still-unreconciled position.
        sums = self._pending.setdefault(identity, {})
        for posting in transaction.postings:
            # Asset-tagged sums cannot offset an unexpected token debit with native SOL.
            key = (posting.account.kind, posting.asset_id)
            sums[key] = sums.get(key, 0) + posting.amount_atomic
            if (
                posting.account.kind is AccountKind.EXTERNAL
                and posting.account.account_id.value.startswith("synthetic-liquidity:")
                # Synthetic funding is tracked from actual external debits, not potential quote
                # shortfalls.
            ):
                # Only a committed sale can debit the explicit synthetic funding account.
                if (
                    transaction.reason != "COPY_SELL_FILLED_ACCOUNT_CLOSED"
                    or posting.amount_atomic >= 0
                ):
                    raise ValueError(
                        # Rejecting here prevents a quote's shortfall from funding the wallet.
                        "copy synthetic posting is not a successful sell funding debit"
                    )
                # Match the exact versioned synthetic account, asset and debit amount.
                sources = self._synthetic.setdefault(identity, {})
                source = (posting.account.account_id.value, posting.asset_id)
                sources[source] = sources.get(source, 0) - posting.amount_atomic

    def append_position(self, record: CopyPositionRecord) -> None:
        """Join one immutable row to its actual correlated token/cash/fee/deposit flows."""
        identity, quote_asset = record.roundtrip_id, record.intent.quote_asset_id
        if identity in self._seen:
            raise ValueError("copy result repeats a position")
        has_ledger = identity in self._pending
        requires_ledger = record.attempts[0].status is not CopyAttemptStatus.REJECTED
        # A rejected first entry consumes its mint but must have no financial postings.
        if has_ledger != requires_ledger:
            raise ValueError("copy position and correlated ledger presence disagree")
        amounts = self._pending.pop(identity, {})
        # Wallet cash includes available and reserved balances, so reservations have zero net
        # effect.
        cash = sum(
            amounts.get((kind, quote_asset), 0)
            for kind in (
                AccountKind.PORTFOLIO_AVAILABLE,
                # Reservation transfers cancel when both spendable portfolio buckets are summed.
                AccountKind.PORTFOLIO_RESERVED,
            )
        )
        tokens = sum(
            # Count actual inventory in the mint asset, without quote-asset netting.
            amounts.get((kind, record.intent.asset_id), 0)
            for kind in (
                AccountKind.PORTFOLIO_AVAILABLE,
                AccountKind.PORTFOLIO_RESERVED,
            )
            # A full successful close leaves this aggregate at zero.
        )
        # Exhausted inventory remains in actual portfolio postings and cannot become a fill.
        if cash != record.quote_cashflow_atomic or tokens != record.remaining_tokens_atomic:
            raise ValueError("copy row token/cash amounts differ from committed ledger")
        quotes = tuple(
            item.actual_quote for item in record.attempts if item.actual_quote is not None
        )
        # Pump fees accrue only on successful instructions; failed landing quotes pay none.
        checks = {
            AccountKind.PROTOCOL_FEE: sum(item.protocol_fee_atomic for item in quotes),
            AccountKind.CREATOR_FEE: sum(item.creator_fee_atomic for item in quotes),
            # Cashback and deposits are separate balance buckets, not realized wallet cash.
            AccountKind.RECEIVABLE: record.cashback_receivable_atomic,
            AccountKind.PORTFOLIO_LOCKED: sum(
                item.locked_delta_atomic for item in record.account_components
            ),
            # Fees remain tagged by asset even though this strategy currently spends native SOL.
            AccountKind.NETWORK_FEE: sum(
                item.network_base_fee_paid_atomic + item.network_priority_fee_paid_atomic
                for item in record.attempts
                if item.network_fee_asset_id == quote_asset.value
            ),
            # These independent buckets must each match, not merely their aggregate total.
        }
        for kind, expected in checks.items():
            if amounts.get((kind, quote_asset), 0) != expected:
                raise ValueError("copy row fee/deposit/receivable differs from committed ledger")
        # Full exact synthetic source matching distinguishes reference shortfall from settled funds.
        expected_sources = {}
        for attempt in record.attempts[1:]:
            quote = attempt.actual_quote
            evidence = None if quote is None else quote.liquidity_evidence
            if evidence is not None and evidence.synthetic_shortfall_atomic:
                # A shortfall without its deterministic source cannot be reconciled as cash.
                if evidence.synthetic_source_account_id is None:
                    raise ValueError("copy synthetic fill has no explicit source account")
                expected_sources[
                    (evidence.synthetic_source_account_id.value, evidence.asset_id)
                ] = evidence.synthetic_shortfall_atomic
        # The successful full exit supplies at most one funding debit per position.
        if self._synthetic.pop(identity, {}) != expected_sources:
            raise ValueError("copy settled synthetic funding differs from ledger source debits")
        self._seen.add(identity)
        # Mark the correlation closed only after all cash, token and funding checks pass.
        self._totals.append(record)

    def verify_summary(self, summary: CopySummaryMetadata) -> None:
        """Every emitted ledger correlation must terminate in exactly one bounded result row."""
        if self._pending or self._synthetic:
            raise ValueError("copy ledger contains orphan position correlations")
        if self._totals.finish() != summary.totals:
            raise ValueError("copy summary totals differ from reconciled position rows")
