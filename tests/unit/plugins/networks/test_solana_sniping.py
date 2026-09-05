# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from backtest.domain.account_requirements import (
    AccountReleasePolicy,
    AccountRequirement,
    AccountRequirementScope,
)
from backtest.domain.identifiers import AssetId
from backtest.plugins.networks.solana import (
    SOLANA_LEGACY_V0_FEE_FORMULA_V1,
    SolanaAccountCostProfile,
    # Include solana account deposit cost so the solana dependency remains explicit.
    SolanaAccountDepositCost,
    SolanaFeeProfile,
    SolanaSnipingCostModel,
    SolanaTransactionFormat,
)


# Define fee as one focused operation with an explicit boundary.
def _fee(profile_id: str, *, cu: int, price: int) -> SolanaFeeProfile:
    # Execute the fee workflow in explicit, reviewable steps.
    return SolanaFeeProfile(
        profile_id=profile_id,
        formula_version=SOLANA_LEGACY_V0_FEE_FORMULA_V1,
        transaction_format=SolanaTransactionFormat.V0,
        effective_from_unix_s=1_700_000_000,
        # Pass effective until unix s explicitly so SolanaFeeProfile receives a reviewable
        # v0 and profile id input in fee.
        effective_until_unix_s=1_800_000_000,
        charged_signature_count=1,
        lamports_per_signature=5_000,
        compute_unit_limit=cu,
        micro_lamports_per_compute_unit=price,
        # Complete SolanaFeeProfile only after its v0 and profile id inputs are visible in
        # fee.
    )


def test_buy_and_sell_profiles_remain_independent_and_accounts_are_priced() -> None:
    # Execute the test buy and sell profiles remain independent and rent is explicit
    # workflow in explicit, reviewable steps.
    model = SolanaSnipingCostModel(
        buy_fee_profile=_fee("buy-v1", cu=100_001, price=10),
        sell_fee_profile=_fee("sell-v1", cu=200_001, price=20),
        account_cost_profile=SolanaAccountCostProfile(
            profile_id="account-v1",
            # Pass effective from unix s explicitly so SolanaAccountCostProfile receives a
            # reviewable account-v1 and pump-token-account-v1 input in test buy and sell
            # profiles remain independent and rent is explicit.
            effective_from_unix_s=1_700_000_000,
            effective_until_unix_s=1_800_000_000,
            costs=(
                SolanaAccountDepositCost("pump-token-account-v1", 2_039_280),
                SolanaAccountDepositCost("pump-user-volume-v1", 1_844_400),
            ),
        ),
        # Complete SolanaSnipingCostModel only after its buy-v1 and sell-v1 inputs are visible
        # in test buy and sell profiles remain independent and rent is explicit.
    )

    requirements = (
        AccountRequirement(
            "pump-token-account-v1",
            AccountRequirementScope.MINT,
            AccountReleasePolicy.CLOSE_ON_SUCCESSFUL_SELL,
        ),
        AccountRequirement(
            "pump-user-volume-v1",
            AccountRequirementScope.WALLET,
            AccountReleasePolicy.RUN_LOCKED,
        ),
    )
    buy = model.quote_buy(
        effective_at_unix_s=1_750_000_000,
        requirements=requirements,
    )
    sell = model.quote_sell(effective_at_unix_s=1_750_000_000)

    # Verify the fee asset id, fresh buy and asset id relationship before this scenario is
    # accepted.
    assert buy.fee_asset_id == AssetId("SOL")
    assert sell.fee_asset_id == AssetId("SOL")
    # Verify the account deposit asset id, sell and asset id relationship before this
    # scenario is accepted.
    assert buy.base_fee_atomic == 5_000
    assert buy.priority_fee_atomic == 2
    assert tuple(item.maximum_deposit_atomic for item in buy.account_requirements) == (
        2_039_280,
        1_844_400,
    )
    assert {item.asset_id for item in buy.account_requirements} == {AssetId("SOL")}
    # Verify sell.priority_fee_atomic == 5 before this scenario is accepted.
    assert sell.priority_fee_atomic == 5
