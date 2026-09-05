"""Typed strategy intents accepted by the deterministic engine."""

from __future__ import annotations

from dataclasses import dataclass

from backtest.domain.chain import ChainPosition
from backtest.domain.execution import ExecutionMode
from backtest.domain.identifiers import (
    # Include account id so the identifiers dependency remains explicit.
    AccountId,
    AssetId,
    ContentDigest,
    OrderId,
    PoolId,
    # Include venue id so the identifiers dependency remains explicit.
    VenueId,
)

PUMPFUN_SNIPING_BUY_DELAY_TRANSACTIONS = 500
PUMPFUN_SNIPING_SELL_DECISION_DELAY_NS = 2_000_000_000


# Keep the swap exact in intent contract and validation rules together.
@dataclass(frozen=True, slots=True)
class SwapExactInIntent:
    order_id: OrderId
    pool_id: PoolId
    sold_asset_id: AssetId
    # Declare bought asset id explicitly in the swap exact in intent contract.
    bought_asset_id: AssetId
    amount_in_atomic: int
    minimum_amount_out_atomic: int
    created_boundary_ordinal: int

    def __post_init__(self) -> None:
        # Execute the swap exact in intent post init workflow in explicit, reviewable
        # steps.
        if self.sold_asset_id == self.bought_asset_id:
            raise ValueError("a swap intent must exchange different assets")
        if self.amount_in_atomic <= 0:
            raise ValueError("amount_in_atomic must be positive")
        if self.minimum_amount_out_atomic < 0:
            # Fail the swap exact in intent post init path with ValueError for minimum
            # amount out atomic must be non-negative when minimum amount out atomic is
            # true; do not continue ambiguously.
            raise ValueError("minimum_amount_out_atomic must be non-negative")
        if self.created_boundary_ordinal < 0:
            raise ValueError("created_boundary_ordinal must be non-negative")

    @property
    def intent_kind(self) -> str:
        # Return the completed swap exact in intent intent kind result without a hidden
        # fallback.
        return "SWAP_EXACT_IN"


@dataclass(frozen=True, slots=True)
class RoundTripIntent:
    """Generic launchpad round-trip intent with fully materialized semantics."""

    roundtrip_id: ContentDigest
    target_event_id: ContentDigest
    target_position: ChainPosition
    asset_id: AssetId
    developer_id: AccountId
    # Declare creation user id explicitly in the round trip intent contract.
    creation_user_id: AccountId
    venue_id: VenueId
    quote_asset_id: AssetId
    gross_buy_budget_atomic: int
    buy_slippage_bps: int
    # Declare sell slippage bps explicitly in the round trip intent contract.
    sell_slippage_bps: int
    sell_delay_transactions: int
    created_boundary_ordinal: int
    buy_delay_transactions: int = PUMPFUN_SNIPING_BUY_DELAY_TRANSACTIONS
    sell_decision_delay_ns: int = PUMPFUN_SNIPING_SELL_DECISION_DELAY_NS
    # Declare execution mode explicitly in the round trip intent contract.
    execution_mode: ExecutionMode = ExecutionMode.EXOGENOUS_REPLAY

    def __post_init__(self) -> None:
        # Execute the round trip intent post init workflow in explicit, reviewable steps.
        if self.asset_id == self.quote_asset_id:
            raise ValueError("round-trip assets must be different")
        if (
            isinstance(self.gross_buy_budget_atomic, bool)
            or not isinstance(self.gross_buy_budget_atomic, int)
            # Keep self visible while evaluating the isinstance and gross buy budget
            # atomic guard.
            or self.gross_buy_budget_atomic <= 0
        ):
            raise ValueError("gross buy budget must be a positive integer")
        for field_name in ("buy_slippage_bps", "sell_slippage_bps"):
            # Process buy slippage bps and sell slippage bps inside the bounded round trip
            # intent post init loop.
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10_000:
                raise ValueError(f"{field_name} must be in [0, 10000]")
        if (
            isinstance(self.sell_delay_transactions, bool)
            # Keep isinstance visible while evaluating the isinstance and sell delay
            # transactions guard.
            or not isinstance(self.sell_delay_transactions, int)
            or self.sell_delay_transactions < 1
        ):
            raise ValueError("sell delay transactions must be positive")
        if self.created_boundary_ordinal != self.target_position.boundary_ordinal:
            # Fail the round trip intent post init path with ValueError for intent
            # decision boundary must equal its target boundary when created boundary
            # ordinal, boundary ordinal and target position is true; do not continue
            # ambiguously.
            raise ValueError("intent decision boundary must equal its target boundary")
        if self.buy_delay_transactions != PUMPFUN_SNIPING_BUY_DELAY_TRANSACTIONS:
            raise ValueError("Pump.fun sniping v1 buy delay is fixed at 500 transactions")
        if self.sell_decision_delay_ns != PUMPFUN_SNIPING_SELL_DECISION_DELAY_NS:
            raise ValueError("Pump.fun sniping v1 sell decision delay is fixed at two seconds")
        # The two exogenous modes share scheduling and differ only at sell settlement.
        supported_modes = {
            ExecutionMode.EXOGENOUS_REPLAY,
            ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT,
        }
        if not isinstance(self.execution_mode, ExecutionMode):
            raise TypeError("execution_mode must be an ExecutionMode")
        # Shadow and conditional replays remain outside the Sniping contract.
        if self.execution_mode not in supported_modes:
            raise ValueError("Pump.fun sniping requires a supported exogenous execution mode")

    @property
    def intent_kind(self) -> str:
        return "ROUND_TRIP"


# Bind intent once as an explicit module-level contract.
Intent = SwapExactInIntent | RoundTripIntent


__all__ = [
    "PUMPFUN_SNIPING_BUY_DELAY_TRANSACTIONS",
    "PUMPFUN_SNIPING_SELL_DECISION_DELAY_NS",
    "Intent",
    # Keep the round trip intent component named inside the all contract.
    "RoundTripIntent",
    "SwapExactInIntent",
]
