"""Execution-mode and pure venue-plan contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from backtest.domain.identifiers import AssetId, OrderId, PoolId
from backtest.domain.ledger import Posting


# Keep the execution mode contract and validation rules together.
class ExecutionMode(StrEnum):
    EXOGENOUS_REPLAY = "EXOGENOUS_REPLAY"
    # Keep synthetic settlement distinct from strict historical venue solvency.
    EXOGENOUS_VIRTUAL_SETTLEMENT = "EXOGENOUS_VIRTUAL_SETTLEMENT"
    SHADOW_STATE_REPLAY = "SHADOW_STATE_REPLAY"
    CONDITIONAL_PROTOCOL_REPLAY = "CONDITIONAL_PROTOCOL_REPLAY"


# Keep the order status contract and validation rules together.
class OrderStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    EXECUTION_FAILED = "EXECUTION_FAILED"


# Keep the execution rejected contract and validation rules together.
class ExecutionRejected(ValueError):
    """Expected deterministic venue rejection, safe to encode in audit."""

    def __init__(self, code: str) -> None:
        # Execute the execution rejected init workflow in explicit, reviewable steps.
        if not code or code != code.strip() or not code.replace("_", "").isalnum():
            raise ValueError("execution rejection code must be a stable token")
        self.code = code
        super().__init__(code)


# Keep the venue transition contract and validation rules together.
@dataclass(frozen=True, slots=True)
class VenueTransition:
    pool_id: PoolId
    reserve_a_after_atomic: int
    reserve_b_after_atomic: int

    # Define venue transition post init as one focused operation with an explicit
    # boundary.
    def __post_init__(self) -> None:
        # Execute the venue transition post init workflow in explicit, reviewable steps.
        if self.reserve_a_after_atomic < 0 or self.reserve_b_after_atomic < 0:
            raise ValueError("venue reserves must remain non-negative")


# Keep the fill contract and validation rules together.
@dataclass(frozen=True, slots=True)
class Fill:
    order_id: OrderId
    pool_id: PoolId
    sold_asset_id: AssetId
    # Declare bought asset id explicitly in the fill contract.
    bought_asset_id: AssetId
    amount_in_atomic: int
    amount_out_atomic: int
    fee_amount_atomic: int
    boundary_ordinal: int

    # Define fill post init as one focused operation with an explicit boundary.
    def __post_init__(self) -> None:
        # Execute the fill post init workflow in explicit, reviewable steps.
        if self.sold_asset_id == self.bought_asset_id:
            raise ValueError("fill assets must be different")
        if self.amount_in_atomic <= 0 or self.amount_out_atomic <= 0:
            raise ValueError("fill amounts must be positive")
        if not 0 <= self.fee_amount_atomic <= self.amount_in_atomic:
            # Fail the fill post init path with ValueError for fill fee is outside its
            # input amount when fee amount atomic and amount in atomic is true; do not
            # continue ambiguously.
            raise ValueError("fill fee is outside its input amount")
        if self.boundary_ordinal < 0:
            raise ValueError("fill boundary must be non-negative")


# Keep the execution plan contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    transition: VenueTransition | None
    fills: tuple[Fill, ...]
    ledger_postings: tuple[Posting, ...]
    # Declare reports explicitly in the execution plan contract.
    reports: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # Execute the execution plan post init workflow in explicit, reviewable steps.
        if not self.fills:
            raise ValueError("an execution plan must contain at least one fill")
        if len({fill.order_id for fill in self.fills}) != len(self.fills):
            raise ValueError("an execution plan cannot fill one order twice")
        if len(self.ledger_postings) < 2:
            # Fail the execution plan post init path with ValueError for an execution plan
            # requires balanced ledger postings when ledger postings is true; do not
            # continue ambiguously.
            raise ValueError("an execution plan requires balanced ledger postings")


# Keep the execution notification contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ExecutionNotification:
    order_id: OrderId
    status: OrderStatus
    boundary_ordinal: int
    # Declare fills explicitly in the execution notification contract.
    fills: tuple[Fill, ...] = ()
    reports: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # Execute the execution notification post init workflow in explicit, reviewable
        # steps.
        if self.boundary_ordinal < 0:
            raise ValueError("notification boundary must be non-negative")
        if any(fill.order_id != self.order_id for fill in self.fills):
            raise ValueError("notification contains a fill for another order")
        if self.status is OrderStatus.FILLED and not self.fills:
            # Fail the execution notification post init path with ValueError for filled
            # notification requires at least one fill when status, filled and fills is
            # true; do not continue ambiguously.
            raise ValueError("filled notification requires at least one fill")


__all__ = [
    "ExecutionMode",
    "ExecutionNotification",
    "ExecutionPlan",
    # Keep the execution rejected component named inside the all contract.
    "ExecutionRejected",
    "Fill",
    "OrderStatus",
    "VenueTransition",
]
