"""Immutable strategy bundles."""

from backtest.plugins.strategies.first_swap import (
    FIRST_SWAP_MINIMUM_FIDELITY,
    FIRST_SWAP_STRATEGY_BUNDLE_ID,
    FirstSwapStrategy,
)

# Import pumpfun sniping at the visible module dependency boundary.
from backtest.plugins.strategies.pumpfun_sniping import (
    PUMPFUN_SNIPING_COOLDOWN_NS,
    PUMPFUN_SNIPING_STRATEGY_BUNDLE_ID,
    PumpfunSnipingStrategy,
)

# Bind all once as an explicit module-level contract.
__all__ = [
    "FIRST_SWAP_MINIMUM_FIDELITY",
    "FIRST_SWAP_STRATEGY_BUNDLE_ID",
    "PUMPFUN_SNIPING_COOLDOWN_NS",
    "PUMPFUN_SNIPING_STRATEGY_BUNDLE_ID",
    # Keep the first swap strategy component named inside the all contract.
    "FirstSwapStrategy",
    "PumpfunSnipingStrategy",
]
