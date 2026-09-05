# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import strategies as st

# Import solana at the visible module dependency boundary.
from backtest.plugins.networks.solana import (
    SolanaAccountCostProfile,
    SolanaAccountDepositCost,
    SolanaAccountRequirement,
    SolanaCostError,
    # Include solana cost error code so the solana dependency remains explicit.
    SolanaCostErrorCode,
    SolanaFeeProfile,
    SolanaTransactionFormat,
    quote_account_deposits,
    quote_transaction_fee,
    # Close the solana import after its required symbols are visible.
)

_START = 1_700_000_000
_END = 1_800_000_000


def _fee_profile(
    *,
    # Keep the transaction format input explicit in the fee profile contract.
    transaction_format: SolanaTransactionFormat = SolanaTransactionFormat.V0,
    compute_unit_limit: int = 400_000,
    micro_lamports_per_compute_unit: int = 1_001,
) -> SolanaFeeProfile:
    # Execute the fee profile workflow in explicit, reviewable steps.
    return SolanaFeeProfile.legacy_v0(
        profile_id="solana-fee-fixture-v1",
        transaction_format=transaction_format,
        effective_from_unix_s=_START,
        effective_until_unix_s=_END,
        # Pass charged signature count explicitly so legacy_v0 receives a reviewable
        # solana-fee-fixture-v1 and transaction format input in fee profile.
        charged_signature_count=2,
        lamports_per_signature=5_000,
        compute_unit_limit=compute_unit_limit,
        micro_lamports_per_compute_unit=micro_lamports_per_compute_unit,
    )


# Define test base and priority fee match literal official formula vector as one focused
# operation with an explicit boundary.
def test_base_and_priority_fee_match_literal_official_formula_vector() -> None:
    # Solana fee structure: base = signatures * lamports/signature;
    # priority = ceil(CU limit * micro-lamports/CU / 1_000_000).
    quote = quote_transaction_fee(_fee_profile(), effective_at_unix_s=_START)

    assert quote.base_fee_lamports == 10_000
    assert quote.priority_fee_lamports == 401
    assert quote.total_fee_lamports == 10_401
    assert quote.charged_on_execution_failure


# Apply parametrize semantics to the following test legacy and v0 share the resolved fee
# formula contract.
@pytest.mark.parametrize(
    "transaction_format",
    (SolanaTransactionFormat.LEGACY, SolanaTransactionFormat.V0),
)
def test_legacy_and_v0_share_the_resolved_fee_formula(
    # Keep the transaction format input explicit in the test legacy and v0 share the
    # resolved fee formula contract.
    transaction_format: SolanaTransactionFormat,
) -> None:
    # Execute the test legacy and v0 share the resolved fee formula workflow in explicit,
    # reviewable steps.
    assert (
        quote_transaction_fee(
            _fee_profile(transaction_format=transaction_format),
            effective_at_unix_s=_START,
        ).total_fee_lamports
        # Keep the 401 expectation tied to total fee lamports, quote transaction fee and
        # fee profile in this scenario.
        == 10_401
    )


@pytest.mark.parametrize(
    "transaction_format",
    (SolanaTransactionFormat.V1, SolanaTransactionFormat.UNKNOWN),
    # Complete parametrize only after its transaction format and v1 inputs are visible in test
    # v1 and unknown transaction formats fail closed.
)
def test_v1_and_unknown_transaction_formats_fail_closed(
    transaction_format: SolanaTransactionFormat,
) -> None:
    # Execute the test v1 and unknown transaction formats fail closed workflow in
    # explicit, reviewable steps.
    with pytest.raises(SolanaCostError) as rejected:
        # Keep raises, solana cost error and pytest active only for the bounded test v1
        # and unknown transaction formats fail closed operation.
        quote_transaction_fee(
            _fee_profile(transaction_format=transaction_format),
            effective_at_unix_s=_START,
        )
    assert rejected.value.code is SolanaCostErrorCode.UNSUPPORTED_TRANSACTION_FORMAT


# Define test fee profile interval is half open and formula is versioned as one focused
# operation with an explicit boundary.
def test_fee_profile_interval_is_half_open_and_formula_is_versioned() -> None:
    # Execute the test fee profile interval is half open and formula is versioned workflow
    # in explicit, reviewable steps.
    with pytest.raises(SolanaCostError) as outside:
        quote_transaction_fee(_fee_profile(), effective_at_unix_s=_END)
    assert outside.value.code is SolanaCostErrorCode.PROFILE_NOT_EFFECTIVE

    with pytest.raises(SolanaCostError) as formula:
        # Keep raises, solana cost error and pytest active only for the bounded test fee
        # profile interval is half open and formula is versioned operation.
        quote_transaction_fee(
            replace(_fee_profile(), formula_version="solana-fee-future-v9"),
            effective_at_unix_s=_START,
        )
    assert formula.value.code is SolanaCostErrorCode.UNSUPPORTED_FEE_FORMULA


# Define test account cost profile quotes only explicit known schemas as one focused
# operation with an explicit boundary.
def test_account_cost_profile_quotes_only_explicit_known_schemas() -> None:
    # Execute the test account cost profile quotes only explicit known schemas workflow in
    # explicit, reviewable steps.
    profile = SolanaAccountCostProfile(
        profile_id="solana-rent-fixture-v1",
        effective_from_unix_s=_START,
        effective_until_unix_s=_END,
        costs=(
            # Keep the associated-token-account-v1 SolanaAccountDepositCost step visible
            # while building profile.
            SolanaAccountDepositCost("associated-token-account-v1", 2_039_280),
            SolanaAccountDepositCost(
                "nonrefundable-extension-v1",
                500_000,
                refundable=False,
                # Complete SolanaAccountDepositCost only after its nonrefundable-extension-v1
                # inputs are visible in test account cost profile quotes only explicit known
                # schemas.
            ),
        ),
    )
    quote = quote_account_deposits(
        profile,
        # Pass requirements explicitly so quote_account_deposits receives a reviewable
        # associated-token-account-v1 and nonrefundable-extension-v1 input in test account
        # cost profile quotes only explicit known schemas.
        requirements=(
            SolanaAccountRequirement("associated-token-account-v1", count=2),
            SolanaAccountRequirement("nonrefundable-extension-v1"),
        ),
        effective_at_unix_s=_START,
        # Complete quote_account_deposits only after its associated-token-account-v1 and
        # nonrefundable-extension-v1 inputs are visible in test account cost profile quotes
        # only explicit known schemas.
    )

    assert quote.required_deposit_lamports == 4_578_560
    assert quote.refundable_deposit_lamports == 4_078_560

    with pytest.raises(SolanaCostError) as unknown:
        # Keep raises, solana cost error and pytest active only for the bounded test
        # account cost profile quotes only explicit known schemas operation.
        quote_account_deposits(
            profile,
            requirements=(SolanaAccountRequirement("unmapped-account-v1"),),
            effective_at_unix_s=_START,
        )
    # Verify the code, unknown account schema and value relationship before this scenario
    # is accepted.
    assert unknown.value.code is SolanaCostErrorCode.UNKNOWN_ACCOUNT_SCHEMA


def test_account_cost_profile_requires_canonical_unique_order() -> None:
    # Execute the test account cost profile requires canonical unique order workflow in
    # explicit, reviewable steps.
    with pytest.raises(ValueError, match="uniquely sorted"):
        # Keep raises, value error and pytest active only for the bounded test account
        # cost profile requires canonical unique order operation.
        SolanaAccountCostProfile(
            profile_id="bad-order-v1",
            effective_from_unix_s=_START,
            effective_until_unix_s=_END,
            costs=(
                # Pass solana account deposit cost explicitly to SolanaAccountCostProfile
                # for bad-order-v1 and z-account-v1.
                SolanaAccountDepositCost("z-account-v1", 1),
                SolanaAccountDepositCost("a-account-v1", 1),
            ),
        )


@given(
    # Define test priority fee is always exact ceiling as one focused operation with an
    # explicit boundary.
    compute_unit_limit=st.integers(min_value=0, max_value=1_400_000),
    micro_lamports_per_compute_unit=st.integers(min_value=0, max_value=10_000_000),
)
def test_priority_fee_is_always_exact_ceiling(
    compute_unit_limit: int,
    # Keep the micro lamports per compute unit input explicit in the test priority fee is
    # always exact ceiling contract.
    micro_lamports_per_compute_unit: int,
) -> None:
    # Execute the test priority fee is always exact ceiling workflow in explicit,
    # reviewable steps.
    quote = quote_transaction_fee(
        _fee_profile(
            compute_unit_limit=compute_unit_limit,
            micro_lamports_per_compute_unit=micro_lamports_per_compute_unit,
        ),
        # Pass effective at unix s explicitly so quote_transaction_fee receives a
        # reviewable fee profile and compute unit limit input in test priority fee is
        # always exact ceiling.
        effective_at_unix_s=_START,
    )
    numerator = compute_unit_limit * micro_lamports_per_compute_unit
    assert quote.priority_fee_lamports == (numerator + 999_999) // 1_000_000
    assert quote.total_fee_lamports == quote.base_fee_lamports + quote.priority_fee_lamports


# Define test boolean and overflowing fee inputs are rejected as one focused operation
# with an explicit boundary.
def test_boolean_and_overflowing_fee_inputs_are_rejected() -> None:
    # Execute the test boolean and overflowing fee inputs are rejected workflow in
    # explicit, reviewable steps.
    with pytest.raises(TypeError, match="integer"):
        replace(_fee_profile(), charged_signature_count=True)

    overflowing = SolanaFeeProfile.legacy_v0(
        profile_id="overflow-v1",
        transaction_format=SolanaTransactionFormat.V0,
        # Pass effective from unix s explicitly so legacy_v0 receives a reviewable
        # overflow-v1 and v0 input in test boolean and overflowing fee inputs are
        # rejected.
        effective_from_unix_s=_START,
        effective_until_unix_s=_END,
        charged_signature_count=(1 << 64) - 1,
        lamports_per_signature=2,
        compute_unit_limit=0,
        # Pass micro lamports per compute unit explicitly so legacy_v0 receives a
        # reviewable overflow-v1 and v0 input in test boolean and overflowing fee inputs
        # are rejected.
        micro_lamports_per_compute_unit=0,
    )
    with pytest.raises(SolanaCostError) as rejected:
        quote_transaction_fee(overflowing, effective_at_unix_s=_START)
    assert rejected.value.code is SolanaCostErrorCode.ARITHMETIC_OVERFLOW
