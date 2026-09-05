"""Checked-integer constant-product reference venue model."""

from __future__ import annotations

from backtest.domain.execution import (
    ExecutionMode,
    ExecutionPlan,
    ExecutionRejected,
    # Include fill so the execution dependency remains explicit.
    Fill,
    VenueTransition,
)
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import AccountId, BundleId

# Import intents at the visible module dependency boundary.
from backtest.domain.intents import SwapExactInIntent
from backtest.domain.ledger import AccountKind, LedgerAccount, Posting
from backtest.engine.portfolio import available_account_id, reserved_account_id
from backtest.engine.state import SimulationVenueState

CONSTANT_PRODUCT_EXECUTION_BUNDLE_ID = BundleId(
    # Keep the v1 domain_digest step visible while building constant product execution
    # bundle id.
    domain_digest(
        "backtest.constant-product-execution-bundle.v1",
        {"api_version": 1, "arithmetic": "checked-integer-floor-v1"},
    ).hex
)


# Keep the constant product execution model contract and validation rules together.
class ConstantProductExecutionModel:
    """Pure x*y=k execution with explicit integer floor rounding."""

    def __init__(self, *, fee_bps: int, bundle_id: BundleId | None = None) -> None:
        # Execute the constant product execution model init workflow in explicit,
        # reviewable steps.
        if isinstance(fee_bps, bool) or not isinstance(fee_bps, int):
            raise TypeError("fee_bps must be an integer")
        if not 0 <= fee_bps < 10_000:
            raise ValueError("fee_bps must be in [0, 10000)")
        self.fee_bps = fee_bps
        # Assemble self bundle id once so the constant product execution model init
        # workflow shares one value.
        self._bundle_id = CONSTANT_PRODUCT_EXECUTION_BUNDLE_ID if bundle_id is None else bundle_id

    @property
    def bundle_id(self) -> BundleId:
        return self._bundle_id

    def execute(
        # Keep the remaining execute inputs visible at the constant product execution
        # model execute boundary.
        self,
        intent: SwapExactInIntent,
        venue_state: SimulationVenueState,
        *,
        boundary_ordinal: int,
        # Keep the mode input explicit in the execute contract.
        mode: ExecutionMode,
    ) -> ExecutionPlan:
        # Execute the constant product execution model execute workflow in explicit,
        # reviewable steps.
        pool = venue_state.pool(intent.pool_id)
        if pool is None:
            raise ExecutionRejected("UNKNOWN_POOL")
        if (intent.sold_asset_id, intent.bought_asset_id) == (
            pool.asset_a_id,
            # Keep pool visible while evaluating the sold asset id, bought asset id and
            # asset a id guard.
            pool.asset_b_id,
        ):
            # Handle the constant product execution model execute sold asset id, bought
            # asset id and asset a id condition as a distinct block.
            reserve_in = pool.reserve_a_atomic
            reserve_out = pool.reserve_b_atomic
            sold_is_a = True
        # Handle the constant product execution model execute complement of sold asset id,
        # bought asset id and asset a id explicitly.
        elif (intent.sold_asset_id, intent.bought_asset_id) == (
            pool.asset_b_id,
            pool.asset_a_id,
        ):
            # Handle the constant product execution model execute sold asset id, bought
            # asset id and asset b id condition as a distinct block.
            reserve_in = pool.reserve_b_atomic
            reserve_out = pool.reserve_a_atomic
            sold_is_a = False
        else:
            raise ExecutionRejected("POOL_ASSET_MISMATCH")
        # Guard this path with reserve_in <= 0 or reserve_out <= 0 before applying
        # effects.
        if reserve_in <= 0 or reserve_out <= 0:
            raise ExecutionRejected("EMPTY_POOL")

        fee = intent.amount_in_atomic * self.fee_bps // 10_000
        effective_input = intent.amount_in_atomic - fee
        amount_out = reserve_out * effective_input // (reserve_in + effective_input)
        # Evaluate the complete constant product execution model execute amount out and
        # reserve out condition before guarded effects.
        if amount_out <= 0 or amount_out >= reserve_out:
            raise ExecutionRejected("OUTPUT_OUT_OF_BOUNDS")
        if amount_out < intent.minimum_amount_out_atomic:
            raise ExecutionRejected("MINIMUM_OUTPUT_NOT_MET")

        next_in = reserve_in + effective_input
        # Assemble next out once so the constant product execution model execute workflow
        # shares one value.
        next_out = reserve_out - amount_out
        if sold_is_a:
            reserve_a_after, reserve_b_after = next_in, next_out
        else:
            reserve_a_after, reserve_b_after = next_out, next_in
        # Assemble transition once so the constant product execution model execute
        # workflow shares one value.
        transition = (
            None
            if mode is ExecutionMode.EXOGENOUS_REPLAY
            else VenueTransition(intent.pool_id, reserve_a_after, reserve_b_after)
        )
        # Assemble fill once so the constant product execution model execute workflow
        # shares one value.
        fill = Fill(
            order_id=intent.order_id,
            pool_id=intent.pool_id,
            sold_asset_id=intent.sold_asset_id,
            bought_asset_id=intent.bought_asset_id,
            # Pass amount in atomic explicitly so Fill receives a reviewable order id and
            # pool id input in constant product execution model execute.
            amount_in_atomic=intent.amount_in_atomic,
            amount_out_atomic=amount_out,
            fee_amount_atomic=fee,
            boundary_ordinal=boundary_ordinal,
        )
        # Assemble venue account once so the constant product execution model execute
        # workflow shares one value.
        venue_account = LedgerAccount(
            AccountId(f"venue:{intent.pool_id.value}"),
            AccountKind.VENUE,
        )
        postings = [
            # Register posting and sold asset id through Posting so the postings table
            # remains scannable.
            Posting(
                LedgerAccount(
                    reserved_account_id(intent.sold_asset_id),
                    AccountKind.PORTFOLIO_RESERVED,
                ),
                # Pass intent explicitly so Posting receives a reviewable portfolio
                # reserved and sold asset id input in constant product execution model
                # execute.
                intent.sold_asset_id,
                -intent.amount_in_atomic,
            ),
            Posting(venue_account, intent.sold_asset_id, effective_input),
            Posting(venue_account, intent.bought_asset_id, -amount_out),
            # Register posting and bought asset id through Posting so the postings table
            # remains scannable.
            Posting(
                LedgerAccount(
                    available_account_id(intent.bought_asset_id),
                    AccountKind.PORTFOLIO_AVAILABLE,
                ),
                # Pass intent explicitly so Posting receives a reviewable portfolio
                # available and bought asset id input in constant product execution model
                # execute.
                intent.bought_asset_id,
                amount_out,
            ),
        ]
        if fee:
            # Handle the constant product execution model execute fee branch as a distinct
            # logical block.
            postings.append(
                Posting(
                    LedgerAccount(
                        AccountId(f"protocol-fee:{intent.pool_id.value}"),
                        AccountKind.PROTOCOL_FEE,
                        # Complete LedgerAccount only after its protocol-fee: and value inputs
                        # are visible in constant product execution model execute.
                    ),
                    intent.sold_asset_id,
                    fee,
                )
            )
        # Return the completed constant product execution model execute result without a
        # hidden fallback.
        return ExecutionPlan(
            transition=transition,
            fills=(fill,),
            ledger_postings=tuple(postings),
            reports=("FILLED",),
            # Complete ExecutionPlan only after its filled and tuple inputs are visible in
            # constant product execution model execute.
        )


__all__ = ["CONSTANT_PRODUCT_EXECUTION_BUNDLE_ID", "ConstantProductExecutionModel"]
