"""Golden vertical-slice strategy: trade once after the first observed swap."""

from __future__ import annotations

from backtest.domain.execution import ExecutionNotification
from backtest.domain.fidelity import (
    FidelityRequirement,
    IdentityFidelity,
    # Include ordering fidelity so the fidelity dependency remains explicit.
    OrderingFidelity,
    StateFidelity,
)
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import AssetId, BundleId, ContentDigest, OrderId, PoolId

# Import intents at the visible module dependency boundary.
from backtest.domain.intents import Intent, SwapExactInIntent
from backtest.domain.market_events import CanonicalEvent, SwapEvent
from backtest.engine.contracts import StrategyContext

FIRST_SWAP_MINIMUM_FIDELITY = FidelityRequirement(
    identity=IdentityFidelity.EXACT,
    # Pass ordering explicitly so FidelityRequirement receives a reviewable exact and
    # transaction exact input in module.
    ordering=OrderingFidelity.TRANSACTION_EXACT,
    state=StateFidelity.AFTER_ONLY,
)

FIRST_SWAP_STRATEGY_BUNDLE_ID = BundleId(
    domain_digest(
        # Pass version tag explicitly so domain_digest receives a reviewable v2 and api
        # version input in module.
        "backtest.first-swap-strategy-bundle.v2",
        {
            "api_version": 1,
            "contract": "first-observed-swap-exact-in-v1",
            "minimum_fidelity": {
                # Keep chain finality named so the v2 and api version payload passed to
                # domain_digest remains self-describing within module.
                "chain_finality": FIRST_SWAP_MINIMUM_FIDELITY.chain_finality.value,
                "completeness": FIRST_SWAP_MINIMUM_FIDELITY.completeness.value,
                "consistency": FIRST_SWAP_MINIMUM_FIDELITY.consistency.value,
                "fees": FIRST_SWAP_MINIMUM_FIDELITY.fees.value,
                "identity": FIRST_SWAP_MINIMUM_FIDELITY.identity.value,
                # Keep ordering named so the v2 and api version payload passed to
                # domain_digest remains self-describing within module.
                "ordering": FIRST_SWAP_MINIMUM_FIDELITY.ordering.value,
                "state": FIRST_SWAP_MINIMUM_FIDELITY.state.value,
            },
        },
    ).hex
    # Complete BundleId only after its v2 and api version inputs are visible in module.
)


# Keep the first swap strategy contract and validation rules together.
class FirstSwapStrategy:
    def __init__(
        self,
        *,
        pool_id: PoolId,
        # Keep the sold asset id input explicit in the init contract.
        sold_asset_id: AssetId,
        bought_asset_id: AssetId,
        amount_in_atomic: int,
        minimum_amount_out_atomic: int = 0,
        bundle_id: BundleId | None = None,
        # Close the init signature after its explicit inputs.
    ) -> None:
        # Execute the first swap strategy init workflow in explicit, reviewable steps.
        if amount_in_atomic <= 0 or minimum_amount_out_atomic < 0:
            raise ValueError("strategy amounts are outside their valid range")
        self.pool_id = pool_id
        self.sold_asset_id = sold_asset_id
        self.bought_asset_id = bought_asset_id
        # Assemble self amount in atomic once so the first swap strategy init workflow
        # shares one value.
        self.amount_in_atomic = amount_in_atomic
        self.minimum_amount_out_atomic = minimum_amount_out_atomic
        self._bundle_id = FIRST_SWAP_STRATEGY_BUNDLE_ID if bundle_id is None else bundle_id
        self._component_id = domain_digest(
            "backtest.configured-strategy-component.v1",
            # Open the v1 and amount in atomic payload explicitly for domain_digest within
            # first swap strategy init.
            {
                "amount_in_atomic": amount_in_atomic,
                "bought_asset_id": bought_asset_id.value,
                "bundle_id": self._bundle_id.hex,
                "minimum_amount_out_atomic": minimum_amount_out_atomic,
                # Keep pool id named so the v1 and amount in atomic payload passed to
                # domain_digest remains self-describing within first swap strategy init.
                "pool_id": pool_id.value,
                "sold_asset_id": sold_asset_id.value,
            },
        )
        self._submitted = False

    # Apply property semantics to the following first swap strategy bundle id contract.
    @property
    def bundle_id(self) -> BundleId:
        return self._bundle_id

    @property
    def component_id(self) -> ContentDigest:
        # Return the completed first swap strategy component id result without a hidden
        # fallback.
        return self._component_id

    def on_event(
        self,
        event: CanonicalEvent,
        context: StrategyContext,
        # Keep the tuple input explicit in the on event contract.
    ) -> tuple[Intent, ...]:
        # Execute the first swap strategy on event workflow in explicit, reviewable steps.
        if self._submitted or not isinstance(event, SwapEvent) or event.pool_id != self.pool_id:
            return ()
        if context.observed_market.pool(self.pool_id) is None:
            return ()
        return self.on_exact_primitive_swap(
            # Pass event id explicitly so on_exact_primitive_swap receives a reviewable
            # canonical event id and envelope input in first swap strategy on event.
            event_id=event.envelope.canonical_event_id,
            decision_boundary_ordinal=context.instant.boundary_ordinal,
        )

    def on_exact_primitive_swap(
        self,
        # Close the on exact primitive swap signature after its explicit inputs.
        *,
        event_id: ContentDigest,
        decision_boundary_ordinal: int,
    ) -> tuple[Intent, ...]:
        """Submit from the optimized reader after equivalent guards are proven.

        This method deliberately accepts no market/source service and no arbitrary
        payload.  The optimized backend may call it only after proving that the
        delivered primitive row is a matching swap and that its observed pool state
        exists.  Keeping order construction here gives both backends one semantic
        implementation and one source-bound bundle identity.
        """

        if self._submitted:
            return ()
        if (
            isinstance(decision_boundary_ordinal, bool)
            or not isinstance(decision_boundary_ordinal, int)
            # Keep decision boundary ordinal visible while evaluating the isinstance and
            # decision boundary ordinal guard.
            or decision_boundary_ordinal < 0
        ):
            raise ValueError("decision boundary must be a non-negative integer")
        order_digest = domain_digest(
            "backtest.strategy-order.v1",
            # Open the v1 and decision boundary payload explicitly for domain_digest
            # within first swap strategy on exact primitive swap.
            {
                "decision_boundary": decision_boundary_ordinal,
                "event_id": event_id.hex,
                "sequence": 0,
                "strategy_component_id": self.component_id.hex,
                # Close the v1 and decision boundary payload only after all first swap
                # strategy on exact primitive swap fields are present.
            },
        )
        self._submitted = True
        return (
            SwapExactInIntent(
                # Include order id in the completed first swap strategy on exact primitive
                # swap result.
                order_id=OrderId(order_digest.hex),
                pool_id=self.pool_id,
                sold_asset_id=self.sold_asset_id,
                bought_asset_id=self.bought_asset_id,
                amount_in_atomic=self.amount_in_atomic,
                # Pass minimum amount out atomic explicitly so SwapExactInIntent receives
                # a reviewable hex and pool id input in first swap strategy on exact
                # primitive swap.
                minimum_amount_out_atomic=self.minimum_amount_out_atomic,
                created_boundary_ordinal=decision_boundary_ordinal,
            ),
        )

    def on_execution(
        # Keep the remaining on execution inputs visible at the first swap strategy on
        # execution boundary.
        self,
        notification: ExecutionNotification,
        context: StrategyContext,
    ) -> None:
        """The reference strategy has no post-fill state beyond its audit."""

        del notification, context


__all__ = [
    "FIRST_SWAP_MINIMUM_FIDELITY",
    "FIRST_SWAP_STRATEGY_BUNDLE_ID",
    "FirstSwapStrategy",
    # Complete the all group only after its semantic components are visible.
]
