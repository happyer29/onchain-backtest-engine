"""Pure Solana network execution-cost semantics."""

from backtest.plugins.networks.solana.costs import (
    SOLANA_LEGACY_V0_FEE_FORMULA_V1,
    SOLANA_LEGACY_V0_MAX_COMPUTE_UNIT_LIMIT,
    SolanaAccountCostProfile,
    SolanaAccountDepositCost,
    # Include solana account deposit quote so the costs dependency remains explicit.
    SolanaAccountDepositQuote,
    SolanaAccountRequirement,
    SolanaCostError,
    SolanaCostErrorCode,
    SolanaFeeProfile,
    # Include solana transaction fee quote so the costs dependency remains explicit.
    SolanaTransactionFeeQuote,
    SolanaTransactionFormat,
    price_account_requirements,
    quote_account_deposits,
    quote_transaction_fee,
)

# Import sniping at the visible module dependency boundary.
from backtest.plugins.networks.solana.sniping import (
    SOLANA_SNIPING_COST_BUNDLE_ID,
    SolanaSnipingCostModel,
)

__all__ = [
    # Keep the solana legacy v0 fee formula v1 component named inside the all contract.
    "SOLANA_LEGACY_V0_FEE_FORMULA_V1",
    "SOLANA_LEGACY_V0_MAX_COMPUTE_UNIT_LIMIT",
    "SOLANA_SNIPING_COST_BUNDLE_ID",
    "SolanaAccountCostProfile",
    "SolanaAccountDepositCost",
    # Keep the solana account deposit quote component named inside the all contract.
    "SolanaAccountDepositQuote",
    "SolanaAccountRequirement",
    "SolanaCostError",
    "SolanaCostErrorCode",
    "SolanaFeeProfile",
    # Keep the solana sniping cost model component named inside the all contract.
    "SolanaSnipingCostModel",
    "SolanaTransactionFeeQuote",
    "SolanaTransactionFormat",
    "price_account_requirements",
    "quote_account_deposits",
    "quote_transaction_fee",
    # Complete the all group only after its semantic components are visible.
]
