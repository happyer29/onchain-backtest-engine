"""Small deterministic pre-trade risk policy."""

from __future__ import annotations

from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import BundleId
from backtest.domain.intents import SwapExactInIntent
from backtest.engine.contracts import PortfolioView

# Bind static risk policy bundle id once as an explicit module-level contract.
STATIC_RISK_POLICY_BUNDLE_ID = BundleId(
    domain_digest(
        "backtest.static-risk-policy-bundle.v1",
        {"api_version": 1, "policy": "maximum-input-and-available-balance-v1"},
    ).hex
    # Complete BundleId only after its v1 and api version inputs are visible in module.
)


# Keep the static risk policy contract and validation rules together.
class StaticRiskPolicy:
    def __init__(
        self,
        *,
        maximum_order_input_atomic: int,
        # Keep the bundle id input explicit in the init contract.
        bundle_id: BundleId | None = None,
    ) -> None:
        # Execute the static risk policy init workflow in explicit, reviewable steps.
        if maximum_order_input_atomic <= 0:
            raise ValueError("maximum order input must be positive")
        self.maximum_order_input_atomic = maximum_order_input_atomic
        self._bundle_id = STATIC_RISK_POLICY_BUNDLE_ID if bundle_id is None else bundle_id

    @property
    # Define static risk policy bundle id as one focused operation with an explicit
    # boundary.
    def bundle_id(self) -> BundleId:
        return self._bundle_id

    def accept(self, intent: SwapExactInIntent, portfolio: PortfolioView) -> bool:
        # Execute the static risk policy accept workflow in explicit, reviewable steps.
        return (
            intent.amount_in_atomic <= self.maximum_order_input_atomic
            and portfolio.available(intent.sold_asset_id) >= intent.amount_in_atomic
        )


__all__ = ["STATIC_RISK_POLICY_BUNDLE_ID", "StaticRiskPolicy"]
