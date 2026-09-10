"""Immutable copy outcomes reconcile execution, money and qualified open valuation."""

from dataclasses import FrozenInstanceError, replace

import pytest
import test_copytrading_execution as execution
import test_copytrading_replay as replay
import test_sniping_engine as base

# Core result tests derive expectations from actual postings and frozen execution state.
from backtest.domain.execution import ExecutionMode

# Independent ledger-derived assertions guard against quoted proceeds becoming cash.
from backtest.domain.identifiers import BundleId, ContentDigest
from backtest.domain.ledger import AccountKind
from backtest.engine.copytrading_results import freeze_copy_position
from backtest.engine.copytrading_run import CopyRunConfig, CopyTotalsAccumulator, run_copy_backtest
from backtest.engine.sniping_contracts import ProtocolExecutionRejected


def test_copy_closed_result_matches_actual_cash_and_is_immutable() -> None:
    executor, state, ledger = execution._setup()
    execution._buy(executor, state)
    attempt = executor.begin_sell(state, execution._trigger(executor, state))
    executor.land(state, attempt.expected_landing)
    # Final result projects committed postings, including fee and ATA refund effects.
    result = freeze_copy_position(state, executor)
    cash = sum(
        post.amount_atomic
        for row in ledger
        for post in row.postings
        # Only wallet-owned available and reserved quote postings define realized cash.
        if post.asset_id == base.SOL
        and post.account.kind in {AccountKind.PORTFOLIO_AVAILABLE, AccountKind.PORTFOLIO_RESERVED}
    )
    # A closed position must reconcile both cash projections with no remaining inventory.
    assert result.realized_cash_pnl_atomic == cash == result.quote_cashflow_atomic
    assert result.remaining_tokens_atomic == 0
    # A later mutation of controller state cannot change previously frozen row bytes.
    document = result.document()
    state.attempts[0].failure_code = "CHANGED_AFTER_FREEZE"
    assert result.document() == document
    with pytest.raises(FrozenInstanceError):
        result.status = state.control.status


def test_copy_rejected_buy_counts_consumption_without_fees() -> None:
    executor, state, ledger = execution._setup(balance=0)
    executor.begin_buy(state)
    result = freeze_copy_position(state, executor)
    # A rejected entry still consumes one position while producing no paid instruction.
    totals = CopyTotalsAccumulator()
    totals.append(result)
    # An unaffordable first signal is an entry outcome, even with no ledger postings.
    summary = totals.finish()
    assert summary.position_count == summary.rejected_buy_count == 1
    assert result.realized_cash_pnl_atomic == 0 and not ledger
    assert summary.network_base_fee_paid_atomic == summary.account_deposit_paid_atomic == 0
    assert result.document()["attempts"][0]["failure_stage"] == "PRE_SUBMIT"


def test_copy_four_rejections_keep_open_inventory_and_actual_valuation(monkeypatch) -> None:
    executor, state, ledger = execution._setup()
    execution._buy(executor, state)
    position = execution._trigger(executor, state)

    def reject(*args, **kwargs):
        """A supported quote rejection consumes an attempt but no network fee."""
        raise ProtocolExecutionRejected("CURVE_COMPLETED")

    # All four pre-submit failures are exercised before the position is frozen.
    monkeypatch.setattr(executor.observed, "quote_sell", reject)
    for _ in range(4):
        executor.begin_sell(state, position)
        position = state.control.retry_position
    result = freeze_copy_position(state, executor)
    # Partial valuation affects aggregate completeness, not whether the run can publish.
    totals = CopyTotalsAccumulator()
    totals.append(result)
    # Sell retries never release inventory or book hypothetical liquidation into cash.
    summary = totals.finish()
    assert summary.exhausted_position_count == 1 and summary.rejected_sell_count == 4
    assert result.realized_cash_pnl_atomic is None and result.remaining_tokens_atomic > 0
    assert result.economic_pnl_atomic is not None and len(ledger) == 2
    assert all(attempt.network_base_fee_paid_atomic == 0 for attempt in result.attempts[1:])
    # Incomplete histories and fifth attempts cannot be dressed up as terminal results.
    with pytest.raises(ValueError, match="four sell failures"):
        replace(result, attempts=result.attempts[:-1])


def test_copy_recorded_run_has_real_fill_audit_and_ledger_streams() -> None:
    arguments, _, _ = replay._runner((base._launch(), replay._trade(1)))
    executor = arguments["executor"]
    prototype = executor.historical

    def runtime():
        """Validation and the two execution views each receive a fresh protocol state."""
        return type(prototype)(
            quote_asset_id=base.SOL,
            fee_profile=prototype.fee_profile,
            protocol_version=prototype.protocol_version,
        )

    # Explicit test config binds initial cash and component identities even without a sink.
    config = CopyRunConfig(
        base.SOL,
        10_000_000_000,
        ExecutionMode.EXOGENOUS_REPLAY,
        BundleId("1" * 64),
        # Separate identities prevent accidental protocol or network bundle substitution.
        BundleId("2" * 64),
        BundleId("3" * 64),
        BundleId("4" * 64),
        # The admitted limits and wallet state are shared contracts, not test-only execution.
        executor.accounts.state,
        arguments["limits"],
        ContentDigest("5" * 64),
    )
    # The complete recorder hashes execution, positions and final balances together.
    summary = run_copy_backtest(
        source=arguments["source"],
        clock=executor.clock,
        decision_range=arguments["decision_range"],
        strategy=arguments["strategy"],
        # The factory supplies isolated validation, historical and observed views.
        protocol_factory=runtime,
        network_costs=executor.network_costs,
        config=config,
    )
    # One real buy and one timeout sell produce two fills and four correlated transactions.
    assert summary.fill_count == 2 and summary.ledger_transaction_count == 4
    assert summary.totals.closed_position_count == 1
    assert len({summary.audit_hash, summary.ledger_hash, summary.fill_hash}) == 3
    assert summary.final_balances and summary.delivered_event_count == 2


@pytest.mark.parametrize(
    "field",
    ["entry_price", "acquired_tokens_atomic", "economic_pnl_atomic", "cashback_receivable_atomic"],
)
def test_copy_result_rejects_tampered_entry_and_economics(field) -> None:
    """A matching file hash cannot legitimize inconsistent financial fields."""
    executor, state, _ = execution._setup()
    execution._buy(executor, state)
    attempt = executor.begin_sell(state, execution._trigger(executor, state))
    executor.land(state, attempt.expected_landing)
    result = freeze_copy_position(state, executor)
    # Mutate one independent observable while preserving the rest of the real execution.
    value = None if field == "entry_price" else getattr(result, field) + 1
    with pytest.raises(ValueError):
        replace(result, **{field: value})


@pytest.mark.parametrize("change", ["identity", "landing", "fee", "early", "retry_after_success"])
def test_copy_result_rejects_tampered_instruction_history(change) -> None:
    """Order correlation, exact landing and four-attempt history remain immutable."""
    executor, state, _ = execution._setup()
    execution._buy(executor, state)
    attempt = executor.begin_sell(state, execution._trigger(executor, state))
    executor.land(state, attempt.expected_landing)
    result = freeze_copy_position(state, executor)
    # Tampering is checked on a fully executed position rather than an incomplete draft.
    with pytest.raises(ValueError):
        # Each mutation attacks a different boundary rather than copying validator internals.
        if change == "identity":
            from backtest.domain.identifiers import OrderId

            replace(
                result,
                # A forged order identity must be rejected even when all money fields are unchanged.
                attempts=(
                    replace(result.attempts[0], order_id=OrderId("f" * 64)),
                    *result.attempts[1:],
                ),
            )
        # Landing coordinates and paid fee amounts have independent validation obligations.
        elif change == "landing":
            replace(result.attempts[0], landed_at=result.attempts[0].decision)
        elif change == "fee":
            replace(result.attempts[0], network_base_fee_paid_atomic=-1)
        elif change == "early":
            # A landing at its decision boundary would violate causal order eligibility.
            replace(result.attempts[0], expected_landing=result.attempts[0].decision)
        else:
            replace(result, attempts=(*result.attempts, result.attempts[-1]))
