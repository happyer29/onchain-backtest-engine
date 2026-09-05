"""Executable invariants for the shared Pump/Solana account reducer."""

from backtest.domain.account_requirements import (
    AccountComponentLifecycle,
    AccountReleasePolicy,
    AccountRequirement,
    AccountRequirementScope,
    PricedAccountRequirement,
)
from backtest.domain.identifiers import AssetId, ContentDigest
from backtest.engine.wallet_accounts import (
    WalletProvisioningReducer,
    WalletUvaInitialState,
    initial_wallet_provisioning_state,
    refundable_mint_deposits,
    run_locked_value,
)

SOL = AssetId("SOL")
MINT_A = AssetId("mint-a")
MINT_B = AssetId("mint-b")
ATA_SCHEMA = "solana-associated-token-account-legacy-v1"
UVA_SCHEMA = "pumpfun-user-volume-accumulator-v1"


def _digest(seed: str) -> ContentDigest:
    # Tests use readable deterministic IDs without depending on production hashing.
    return ContentDigest(seed * 64)


def _requirements() -> tuple[PricedAccountRequirement, ...]:
    # Mint and wallet requirements deliberately have different release policies.
    ata = AccountRequirement(
        ATA_SCHEMA,
        AccountRequirementScope.MINT,
        AccountReleasePolicy.CLOSE_ON_SUCCESSFUL_SELL,
    )
    uva = AccountRequirement(
        UVA_SCHEMA,
        AccountRequirementScope.WALLET,
        AccountReleasePolicy.RUN_LOCKED,
    )
    return (
        PricedAccountRequirement(ata, SOL, 2_039_280),
        PricedAccountRequirement(uva, SOL, 1_844_400),
    )


def _reducer(initial: WalletUvaInitialState) -> WalletProvisioningReducer:
    # One helper makes fresh/prewarmed comparisons use the same account prices.
    return WalletProvisioningReducer(
        initial_wallet_provisioning_state(initial, uva_schema_id=UVA_SCHEMA)
    )


def test_concurrent_fresh_reservations_create_uva_once() -> None:
    reducer = _reducer(WalletUvaInitialState.FRESH)
    first = reducer.reservation(
        roundtrip_id=_digest("1"),
        mint_asset_id=MINT_A,
        priced_requirements=_requirements(),
    )
    second = reducer.reservation(
        roundtrip_id=_digest("2"),
        mint_asset_id=MINT_B,
        priced_requirements=_requirements(),
    )

    # Both pending orders conservatively reserve ATA plus the still-absent UVA.
    expected = ((SOL, 2_039_280 + 1_844_400),)
    assert first.reserved_asset_amounts == expected
    assert second.reserved_asset_amounts == expected

    first_landing = reducer.preview_buy(first, successful=True)
    reducer.commit(first_landing)
    second_landing = reducer.preview_buy(second, successful=True)
    reducer.commit(second_landing)

    # The canonical first landing pays UVA; the later one releases its redundancy.
    first_wallet = next(
        item for item in first_landing.records if item.scope is AccountRequirementScope.WALLET
    )
    second_wallet = next(
        item for item in second_landing.records if item.scope is AccountRequirementScope.WALLET
    )
    assert first_wallet.lifecycle is AccountComponentLifecycle.CREATED_LOCKED
    assert first_wallet.paid_atomic == 1_844_400
    assert second_wallet.lifecycle is AccountComponentLifecycle.EXISTING_RUN_LOCKED
    assert second_wallet.released_atomic == 1_844_400
    assert run_locked_value(first_landing.records) == ((SOL, 1_844_400),)
    assert run_locked_value(second_landing.records) == ()


def test_failed_landing_releases_accounts_without_mutation() -> None:
    reducer = _reducer(WalletUvaInitialState.FRESH)
    plan = reducer.reservation(
        roundtrip_id=_digest("3"),
        mint_asset_id=MINT_A,
        priced_requirements=_requirements(),
    )
    failed = reducer.preview_buy(plan, successful=False)
    reducer.commit(failed)

    # Failure releases both reservations and leaves neither account provisioned.
    assert failed.state.uva_exists is False
    assert failed.state.open_mint_accounts == ()
    assert all(
        item.lifecycle is AccountComponentLifecycle.RESERVATION_RELEASED for item in failed.records
    )
    assert sum(item.released_atomic for item in failed.records) == 3_883_680


def test_successful_sell_refunds_only_the_mint_account() -> None:
    reducer = _reducer(WalletUvaInitialState.FRESH)
    plan = reducer.reservation(
        roundtrip_id=_digest("4"),
        mint_asset_id=MINT_A,
        priced_requirements=_requirements(),
    )
    bought = reducer.preview_buy(plan, successful=True)
    reducer.commit(bought)

    sold = reducer.preview_sell(
        roundtrip_id=plan.roundtrip_id,
        mint_asset_id=MINT_A,
        records=bought.records,
        successful=True,
    )
    reducer.commit(sold)

    # ATA closes and refunds; the one wallet UVA remains in run-scoped locked state.
    mint = next(item for item in sold.records if item.scope is AccountRequirementScope.MINT)
    wallet = next(item for item in sold.records if item.scope is AccountRequirementScope.WALLET)
    assert mint.lifecycle is AccountComponentLifecycle.CLOSED_REFUNDED
    assert mint.refunded_atomic == 2_039_280
    assert wallet.lifecycle is AccountComponentLifecycle.CREATED_LOCKED
    assert wallet.locked_delta_atomic == 1_844_400
    assert refundable_mint_deposits(bought.records) == ((SOL, 2_039_280),)
    assert refundable_mint_deposits(sold.records) == ()


def test_prewarmed_uva_never_creates_run_cashflow() -> None:
    reducer = _reducer(WalletUvaInitialState.PREWARMED)
    plan = reducer.reservation(
        roundtrip_id=_digest("5"),
        mint_asset_id=MINT_A,
        priced_requirements=_requirements(),
    )
    landing = reducer.preview_buy(plan, successful=True)

    # Only the new mint ATA is reserved and paid by a prewarmed wallet.
    assert plan.reserved_asset_amounts == ((SOL, 2_039_280),)
    wallet = next(item for item in landing.records if item.scope is AccountRequirementScope.WALLET)
    assert wallet.lifecycle is AccountComponentLifecycle.PREWARMED
    assert wallet.maximum_reserved_atomic == 0
    assert wallet.paid_atomic == 0
