"""Solana fee/account profile adapter for the generic sniping engine."""

from __future__ import annotations

from typing import Final

from backtest.domain.account_requirements import AccountRequirement
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import AccountId, AssetId, BundleId
from backtest.engine.sniping_contracts import (
    # Include network cost contract error so the sniping contracts dependency remains
    # explicit.
    NetworkCostContractError,
    NetworkCostQuote,
)
from backtest.plugins.networks.solana.costs import (
    SolanaAccountCostProfile,
    # Include solana account requirement so the costs dependency remains explicit.
    SolanaCostError,
    SolanaFeeProfile,
    price_account_requirements,
    quote_transaction_fee,
    # Close the costs import after its required symbols are visible.
)

SOLANA_NATIVE_ASSET_ID: Final = AssetId("SOL")

SOLANA_SNIPING_COST_BUNDLE_ID: Final = BundleId(
    domain_digest(
        "backtest.solana-sniping-cost-bundle.v3",
        # Open the v2 and account cost contract payload explicitly for domain_digest
        # within module.
        {
            "account_cost_contract": "generic-priced-requirements-v2",
            "account_deposit_asset_id": SOLANA_NATIVE_ASSET_ID.value,
            "fee_asset_id": SOLANA_NATIVE_ASSET_ID.value,
            "fee_contract": "base-plus-ceil-priority-v1",
            # Keep jito tip named so the v2 and account cost contract payload passed to
            # domain_digest remains self-describing within module.
            "jito_tip": "excluded",
        },
    ).hex
)


class SolanaSnipingCostModel:
    """Resolve separate buy/sell fees and explicit token-account deposits."""

    def __init__(
        self,
        *,
        buy_fee_profile: SolanaFeeProfile,
        sell_fee_profile: SolanaFeeProfile,
        # Keep the account cost profile input explicit in the init contract.
        account_cost_profile: SolanaAccountCostProfile,
        bundle_id: BundleId | None = None,
    ) -> None:
        # Execute the solana sniping cost model init workflow in explicit, reviewable
        # steps.
        self.buy_fee_profile = buy_fee_profile
        self.sell_fee_profile = sell_fee_profile
        self.account_cost_profile = account_cost_profile
        # Assemble self bundle id once so the solana sniping cost model init workflow
        # shares one value.
        self._bundle_id = SOLANA_SNIPING_COST_BUNDLE_ID if bundle_id is None else bundle_id
        self._fee_collector_account_id = AccountId("network-fee:solana")

    @property
    def bundle_id(self) -> BundleId:
        return self._bundle_id

    # Apply property semantics to the following solana sniping cost model fee collector
    # account id contract.
    @property
    def fee_collector_account_id(self) -> AccountId:
        return self._fee_collector_account_id

    def quote_buy(
        self,
        # Close the quote buy signature after its explicit inputs.
        *,
        effective_at_unix_s: int,
        requirements: tuple[AccountRequirement, ...],
    ) -> NetworkCostQuote:
        # Execute the solana sniping cost model quote buy workflow in explicit, reviewable
        # steps.
        try:
            # Perform the protected solana sniping cost model quote buy operation before
            # explicit failure handling.
            fee = quote_transaction_fee(
                self.buy_fee_profile,
                effective_at_unix_s=effective_at_unix_s,
            )
            priced = price_account_requirements(
                self.account_cost_profile,
                requirements=requirements,
                deposit_asset_id=SOLANA_NATIVE_ASSET_ID,
                effective_at_unix_s=effective_at_unix_s,
            )
        except SolanaCostError as error:
            raise NetworkCostContractError(error.code.value) from error
        return NetworkCostQuote(
            fee_asset_id=SOLANA_NATIVE_ASSET_ID,
            # Pass base fee atomic explicitly so NetworkCostQuote receives a reviewable
            # base fee lamports and priority fee lamports input in solana sniping cost
            # model quote buy.
            base_fee_atomic=fee.base_fee_lamports,
            priority_fee_atomic=fee.priority_fee_lamports,
            account_requirements=priced,
        )

    # Define solana sniping cost model quote sell as one focused operation with an
    # explicit boundary.
    def quote_sell(self, *, effective_at_unix_s: int) -> NetworkCostQuote:
        # Execute the solana sniping cost model quote sell workflow in explicit,
        # reviewable steps.
        try:
            # Perform the protected solana sniping cost model quote sell operation before
            # explicit failure handling.
            fee = quote_transaction_fee(
                self.sell_fee_profile,
                effective_at_unix_s=effective_at_unix_s,
            )
        except SolanaCostError as error:
            # Fail the solana sniping cost model quote sell path with
            # NetworkCostContractError for value and code; do not continue ambiguously.
            raise NetworkCostContractError(error.code.value) from error
        return NetworkCostQuote(
            fee_asset_id=SOLANA_NATIVE_ASSET_ID,
            base_fee_atomic=fee.base_fee_lamports,
            # Pass priority fee atomic explicitly so NetworkCostQuote receives a
            # reviewable base fee lamports and priority fee lamports input in solana
            # sniping cost model quote sell.
            priority_fee_atomic=fee.priority_fee_lamports,
        )


__all__ = [
    "SOLANA_NATIVE_ASSET_ID",
    "SOLANA_SNIPING_COST_BUNDLE_ID",
    # Keep the solana sniping cost model component named inside the all contract.
    "SolanaSnipingCostModel",
]
