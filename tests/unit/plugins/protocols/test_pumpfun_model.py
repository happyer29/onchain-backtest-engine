# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import strategies as st

# Import pumpfun at the visible module dependency boundary.
from backtest.plugins.protocols.pumpfun import (
    PUMP_BUY_EXACT_GROSS_SOL_FORMULA_V1,
    PUMP_BUY_LEGACY_EXACT_NET_SOL_FORMULA_V1,
    PUMP_HISTORICAL_COMPONENT_FEE_FORMULA_V1,
    PUMP_SELL_EXACT_TOKEN_IN_FORMULA_V1,
    PumpCreatorFeeRoute,
    # Include pump curve lifecycle so the pumpfun dependency remains explicit.
    PumpCurveLifecycle,
    PumpCurveStateV1,
    PumpFeeProfile,
    PumpMode,
    PumpProtocolFeeRoute,
    # Include pump quote error so the pumpfun dependency remains explicit.
    PumpQuoteError,
    PumpQuoteErrorCode,
    PumpTokenProgram,
    assess_slippage,
    buy_quote,
    historical_trade_fee_breakdown,
    # Include minimum output atomic so the pumpfun dependency remains explicit.
    minimum_output_atomic,
    sell_quote,
)
from backtest.plugins.protocols.pumpfun.model import PumpSellLiquidityPolicy

_PROFILE = PumpFeeProfile.static_95_30(
    profile_id="pump-static-95-30-fixture-v1",
    # Pass effective from unix s explicitly so static_95_30 receives a reviewable pump-
    # static-95-30-fixture-v1 input in module.
    effective_from_unix_s=1_700_000_000,
    effective_until_unix_s=1_800_000_000,
)
_EFFECTIVE_AT = 1_750_000_000


def _state(
    # Close the state signature after its explicit inputs.
    *,
    mode: PumpMode = PumpMode.NORMAL,
    lifecycle: PumpCurveLifecycle = PumpCurveLifecycle.ACTIVE,
    real_token_reserves_atomic: int = 793_100_000_000_000,
    real_sol_reserves_lamports: int = 100_000_000_000,
    # Keep the pump curve state v1 input explicit in the state contract.
) -> PumpCurveStateV1:
    # Execute the state workflow in explicit, reviewable steps.
    return PumpCurveStateV1(
        virtual_token_reserves_atomic=1_073_000_000_000_000,
        virtual_sol_reserves_lamports=30_000_000_000,
        real_token_reserves_atomic=real_token_reserves_atomic,
        real_sol_reserves_lamports=real_sol_reserves_lamports,
        # Pass token total supply atomic explicitly so PumpCurveStateV1 receives a
        # reviewable real token reserves atomic and real sol reserves lamports input in
        # state.
        token_total_supply_atomic=1_000_000_000_000_000,
        lifecycle=lifecycle,
        mode=mode,
    )


def test_buy_exact_gross_sol_matches_literal_official_formula_vector() -> None:
    # Literal expected values independently evaluated from the quote steps in
    # pump-fun/pump-public-docs idl/pump.json for buy_exact_sol_in.
    quote = buy_quote(
        _state(),
        spendable_gross_sol_lamports=1_000_000_000,
        fee_profile=_PROFILE,
        effective_at_unix_s=_EFFECTIVE_AT,
        # Complete buy_quote only after its state and profile inputs are visible in test buy
        # exact gross sol matches literal official formula vector.
    )

    assert quote.formula_version == PUMP_BUY_EXACT_GROSS_SOL_FORMULA_V1
    assert quote.fee_basis_sol_lamports == 987_654_320
    assert quote.net_curve_sol_lamports == 987_654_320
    assert quote.fees.protocol_fee_lamports == 9_382_717
    # Verify the creator fee lamports, fees and quote relationship before this scenario is
    # accepted.
    assert quote.fees.creator_fee_lamports == 2_962_963
    assert quote.gross_sol_spent_lamports == 1_000_000_000
    assert quote.unspent_sol_lamports == 0
    assert quote.tokens_out_atomic == 34_199_203_120_618


def test_historical_buy_formula_requires_explicit_profile_selection() -> None:
    # Execute the test historical buy formula requires explicit profile selection workflow
    # in explicit, reviewable steps.
    legacy_profile = replace(
        _PROFILE,
        buy_formula_version=PUMP_BUY_LEGACY_EXACT_NET_SOL_FORMULA_V1,
    )

    modern = buy_quote(
        # Keep the state _state step visible while building modern.
        _state(),
        spendable_gross_sol_lamports=1_000_000_000,
        fee_profile=_PROFILE,
        effective_at_unix_s=_EFFECTIVE_AT,
    )
    # Assemble legacy once so the test historical buy formula requires explicit profile
    # selection workflow shares one value.
    legacy = buy_quote(
        _state(),
        spendable_gross_sol_lamports=1_000_000_000,
        fee_profile=legacy_profile,
        effective_at_unix_s=_EFFECTIVE_AT,
        # Complete buy_quote only after its state and legacy profile inputs are visible in
        # test historical buy formula requires explicit profile selection.
    )

    assert modern.formula_version == PUMP_BUY_EXACT_GROSS_SOL_FORMULA_V1
    assert legacy.formula_version == PUMP_BUY_LEGACY_EXACT_NET_SOL_FORMULA_V1
    assert modern.tokens_out_atomic == 34_199_203_120_618
    assert legacy.tokens_out_atomic == 34_199_203_154_141

    # Acquire raises, pump quote error and pytest at an explicit test historical buy
    # formula requires explicit profile selection context boundary so cleanup remains
    # scoped.
    with pytest.raises(PumpQuoteError) as incompatible_mode:
        # Keep raises, pump quote error and pytest active only for the bounded test
        # historical buy formula requires explicit profile selection operation.
        buy_quote(
            _state(mode=PumpMode.TOKEN_2022),
            spendable_gross_sol_lamports=1_000_000_000,
            fee_profile=legacy_profile,
            effective_at_unix_s=_EFFECTIVE_AT,
            # Complete buy_quote only after its token 2022 and state inputs are visible in
            # test historical buy formula requires explicit profile selection.
        )
    assert incompatible_mode.value.code is PumpQuoteErrorCode.UNSUPPORTED_FORMULA_VERSION


def test_sell_all_matches_literal_integer_curve_and_fee_vector() -> None:
    # Execute the test sell all matches literal integer curve and fee vector workflow in
    # explicit, reviewable steps.
    quote = sell_quote(
        _state(),
        tokens_in_atomic=34_199_203_120_618,
        fee_profile=_PROFILE,
        effective_at_unix_s=_EFFECTIVE_AT,
        # Complete sell_quote only after its state and profile inputs are visible in test sell
        # all matches literal integer curve and fee vector.
    )

    assert quote.formula_version == PUMP_SELL_EXACT_TOKEN_IN_FORMULA_V1
    assert quote.gross_curve_sol_lamports == 926_640_924
    assert quote.fees.protocol_fee_lamports == 8_803_089
    assert quote.fees.creator_fee_lamports == 2_779_923
    # Verify quote.sol_out_lamports == 915057912 before this scenario is accepted.
    assert quote.sol_out_lamports == 915_057_912
    assert quote.liquidity_policy is PumpSellLiquidityPolicy.REAL_RESERVE_CAPPED_V1
    assert quote.observed_real_sol_reserves_lamports == 100_000_000_000
    assert quote.synthetic_shortfall_lamports == 0


def test_virtual_sell_quotes_gross_output_and_exact_synthetic_shortfall() -> None:
    """Virtual settlement relaxes only the real-SOL cap, not quote arithmetic."""

    policy = PumpSellLiquidityPolicy.VIRTUAL_RESERVE_OUTPUT_WITH_EXPLICIT_SYNTHETIC_SHORTFALL_V1
    quote = sell_quote(
        _state(real_sol_reserves_lamports=100_000_000),
        tokens_in_atomic=34_199_203_120_618,
        fee_profile=_PROFILE,
        effective_at_unix_s=_EFFECTIVE_AT,
        # Select the synthetic policy explicitly; strict remains the function default.
        liquidity_policy=policy,
    )

    assert quote.gross_curve_sol_lamports == 926_640_924
    assert quote.observed_real_sol_reserves_lamports == 100_000_000
    assert quote.synthetic_shortfall_lamports == 826_640_924
    assert quote.liquidity_policy is policy
    # Fee routing still conserves the same gross virtual-reserve output.
    assert quote.sol_out_lamports == 915_057_912
    with pytest.raises(ValueError, match="shortfall is inconsistent"):
        replace(quote, synthetic_shortfall_lamports=826_640_923)


def test_virtual_sell_policy_does_not_revive_a_migrated_curve() -> None:
    policy = PumpSellLiquidityPolicy.VIRTUAL_RESERVE_OUTPUT_WITH_EXPLICIT_SYNTHETIC_SHORTFALL_V1
    with pytest.raises(PumpQuoteError) as rejected:
        sell_quote(
            _state(
                lifecycle=PumpCurveLifecycle.MIGRATED,
                real_sol_reserves_lamports=0,
            ),
            tokens_in_atomic=34_199_203_120_618,
            fee_profile=_PROFILE,
            # Lifecycle validation remains ahead of the relaxed liquidity gate.
            effective_at_unix_s=_EFFECTIVE_AT,
            liquidity_policy=policy,
        )
    assert rejected.value.code is PumpQuoteErrorCode.PUMPSWAP_ROUTING_FORBIDDEN


def test_historical_trade_components_use_observed_curve_delta_and_independent_ceil() -> None:
    assert PUMP_HISTORICAL_COMPONENT_FEE_FORMULA_V1 == ("pump-historical-component-fees-v1")
    fees = historical_trade_fee_breakdown(
        PumpMode.CASHBACK,
        curve_sol_lamports=101,
        fee_profile=_PROFILE,
        effective_at_unix_s=_EFFECTIVE_AT,
    )

    assert fees.protocol_fee_lamports == 1
    assert fees.creator_fee_lamports == 1
    assert fees.cashback_receivable_lamports == 1


def test_historical_zero_quote_dust_sell_has_zero_components() -> None:
    fees = historical_trade_fee_breakdown(
        PumpMode.NORMAL,
        curve_sol_lamports=0,
        fee_profile=_PROFILE,
        effective_at_unix_s=_EFFECTIVE_AT,
    )

    assert fees.protocol_fee_lamports == 0
    assert fees.creator_fee_lamports == 0
    assert fees.cashback_receivable_lamports is None


def test_historical_components_fail_closed_outside_profile_interval() -> None:
    with pytest.raises(PumpQuoteError) as caught:
        historical_trade_fee_breakdown(
            PumpMode.NORMAL,
            curve_sol_lamports=1,
            fee_profile=_PROFILE,
            effective_at_unix_s=_PROFILE.effective_until_unix_s,
        )

    assert caught.value.code is PumpQuoteErrorCode.PROFILE_NOT_EFFECTIVE


@pytest.mark.parametrize(
    ("mode", "token_program", "protocol_route", "creator_route", "has_cashback"),
    (
        (
            # Pass pump mode explicitly so parametrize receives a reviewable mode and
            # token program input in test all supported modes match literal buy sell and
            # rounding vectors.
            PumpMode.NORMAL,
            PumpTokenProgram.LEGACY_SPL_TOKEN,
            PumpProtocolFeeRoute.NORMAL_RECIPIENT,
            PumpCreatorFeeRoute.CREATOR_VAULT,
            False,
            # Complete parametrize only after its mode and token program inputs are visible in
            # test all supported modes match literal buy sell and rounding vectors.
        ),
        (
            PumpMode.TOKEN_2022,
            PumpTokenProgram.TOKEN_2022,
            PumpProtocolFeeRoute.NORMAL_RECIPIENT,
            # Pass pump creator fee route explicitly so parametrize receives a reviewable
            # mode and token program input in test all supported modes match literal buy
            # sell and rounding vectors.
            PumpCreatorFeeRoute.CREATOR_VAULT,
            False,
        ),
        (
            PumpMode.CASHBACK,
            # Pass pump token program explicitly so parametrize receives a reviewable mode
            # and token program input in test all supported modes match literal buy sell
            # and rounding vectors.
            PumpTokenProgram.TOKEN_2022,
            PumpProtocolFeeRoute.NORMAL_RECIPIENT,
            PumpCreatorFeeRoute.CASHBACK_RECEIVABLE,
            True,
        ),
        # Open the mode and token program payload explicitly for parametrize within test
        # all supported modes match literal buy sell and rounding vectors.
        (
            PumpMode.MAYHEM,
            PumpTokenProgram.TOKEN_2022,
            PumpProtocolFeeRoute.MAYHEM_RECIPIENT,
            PumpCreatorFeeRoute.CREATOR_VAULT,
            # Keep parametrize, mark and mode visible while completing parametrize within
            # test all supported modes match literal buy sell and rounding vectors.
            False,
        ),
    ),
)
def test_all_supported_modes_match_literal_buy_sell_and_rounding_vectors(
    # Keep the mode input explicit in the test all supported modes match literal buy sell
    # and rounding vectors contract.
    mode: PumpMode,
    token_program: PumpTokenProgram,
    protocol_route: PumpProtocolFeeRoute,
    creator_route: PumpCreatorFeeRoute,
    has_cashback: bool,
    # Close the test all supported modes match literal buy sell and rounding vectors signature
    # after its explicit inputs.
) -> None:
    # Execute the test all supported modes match literal buy sell and rounding vectors
    # workflow in explicit, reviewable steps.
    buy = buy_quote(
        _state(mode=mode),
        spendable_gross_sol_lamports=1_000_000_000,
        fee_profile=_PROFILE,
        effective_at_unix_s=_EFFECTIVE_AT,
        # Complete buy_quote only after its state and mode inputs are visible in test all
        # supported modes match literal buy sell and rounding vectors.
    )
    sell = sell_quote(
        _state(mode=mode),
        tokens_in_atomic=34_199_203_120_618,
        fee_profile=_PROFILE,
        # Pass effective at unix s explicitly so sell_quote receives a reviewable state
        # and mode input in test all supported modes match literal buy sell and rounding
        # vectors.
        effective_at_unix_s=_EFFECTIVE_AT,
    )

    # Pump's published IDL uses the same integer curve and independent fee
    # rounding for all four modes; mode changes only token/account fee routing.
    assert (
        buy.fee_basis_sol_lamports,
        buy.net_curve_sol_lamports,
        buy.fees.protocol_fee_lamports,
        buy.fees.creator_fee_lamports,
        # Keep the buy expectation tied to fee basis sol lamports, net curve sol lamports
        # and protocol fee lamports in this scenario.
        buy.gross_sol_spent_lamports,
        buy.tokens_out_atomic,
    ) == (
        987_654_320,
        987_654_320,
        # Keep the 382 717 expectation tied to fee basis sol lamports, net curve sol
        # lamports and protocol fee lamports in this scenario.
        9_382_717,
        2_962_963,
        1_000_000_000,
        34_199_203_120_618,
    )
    # Verify the gross curve sol lamports, protocol fee lamports and creator fee lamports
    # relationship before this scenario is accepted.
    assert (
        sell.gross_curve_sol_lamports,
        sell.fees.protocol_fee_lamports,
        sell.fees.creator_fee_lamports,
        sell.sol_out_lamports,
        # Keep the 640 924 expectation tied to gross curve sol lamports, protocol fee lamports
        # and creator fee lamports in this scenario.
    ) == (926_640_924, 8_803_089, 2_779_923, 915_057_912)
    assert buy.fees.routing == sell.fees.routing
    assert buy.fees.routing.token_program is token_program
    assert buy.fees.routing.protocol_fee_route is protocol_route
    assert buy.fees.routing.creator_fee_route is creator_route
    # Guard this path with has_cashback before applying effects.
    if has_cashback:
        # Handle the test all supported modes match literal buy sell and rounding vectors
        # has_cashback branch as a distinct logical block.
        assert buy.fees.cashback_receivable_lamports == buy.fees.creator_fee_lamports
        assert sell.fees.cashback_receivable_lamports == sell.fees.creator_fee_lamports
    else:
        # Handle the test all supported modes match literal buy sell and rounding vectors
        # complement of has_cashback explicitly.
        assert buy.fees.cashback_receivable_lamports is None
        assert sell.fees.cashback_receivable_lamports is None


def test_profile_interval_is_half_open_and_formula_versions_fail_closed() -> None:
    # Execute the test profile interval is half open and formula versions fail closed
    # workflow in explicit, reviewable steps.
    assert (
        buy_quote(
            _state(),
            spendable_gross_sol_lamports=1_000_000,
            fee_profile=_PROFILE,
            # Pass effective at unix s explicitly so buy_quote receives a reviewable
            # effective from unix s and state input in test profile interval is half open
            # and formula versions fail closed.
            effective_at_unix_s=_PROFILE.effective_from_unix_s,
        ).tokens_out_atomic
        > 0
    )

    with pytest.raises(PumpQuoteError) as outside:
        # Keep raises, pump quote error and pytest active only for the bounded test
        # profile interval is half open and formula versions fail closed operation.
        buy_quote(
            _state(),
            spendable_gross_sol_lamports=1_000_000,
            fee_profile=_PROFILE,
            effective_at_unix_s=_PROFILE.effective_until_unix_s,
            # Complete buy_quote only after its effective until unix s and state inputs are
            # visible in test profile interval is half open and formula versions fail closed.
        )
    assert outside.value.code is PumpQuoteErrorCode.PROFILE_NOT_EFFECTIVE

    with pytest.raises(PumpQuoteError) as unsupported:
        # Keep raises, pump quote error and pytest active only for the bounded test
        # profile interval is half open and formula versions fail closed operation.
        buy_quote(
            _state(),
            spendable_gross_sol_lamports=1_000_000,
            fee_profile=replace(_PROFILE, buy_formula_version="future-buy-formula-v9"),
            effective_at_unix_s=_EFFECTIVE_AT,
            # Complete buy_quote only after its future-buy-formula-v9 and state inputs are
            # visible in test profile interval is half open and formula versions fail closed.
        )
    assert unsupported.value.code is PumpQuoteErrorCode.UNSUPPORTED_FORMULA_VERSION


@pytest.mark.parametrize(
    ("lifecycle", "code"),
    (
        # Open the lifecycle and code payload explicitly for parametrize within test non
        # active curve never silently routes to pumpswap.
        (PumpCurveLifecycle.UNKNOWN, PumpQuoteErrorCode.UNKNOWN_LIFECYCLE),
        (PumpCurveLifecycle.COMPLETED, PumpQuoteErrorCode.CURVE_COMPLETED),
        (PumpCurveLifecycle.MIGRATED, PumpQuoteErrorCode.PUMPSWAP_ROUTING_FORBIDDEN),
    ),
)
# Define test non active curve never silently routes to pumpswap as one focused operation
# with an explicit boundary.
def test_non_active_curve_never_silently_routes_to_pumpswap(
    lifecycle: PumpCurveLifecycle,
    code: PumpQuoteErrorCode,
) -> None:
    # Execute the test non active curve never silently routes to pumpswap workflow in
    # explicit, reviewable steps.
    with pytest.raises(PumpQuoteError) as rejected:
        # Keep raises, pump quote error and pytest active only for the bounded test non
        # active curve never silently routes to pumpswap operation.
        buy_quote(
            _state(lifecycle=lifecycle),
            spendable_gross_sol_lamports=1_000_000,
            fee_profile=_PROFILE,
            effective_at_unix_s=_EFFECTIVE_AT,
            # Complete buy_quote only after its state and lifecycle inputs are visible in test
            # non active curve never silently routes to pumpswap.
        )
    assert rejected.value.code is code


def test_unknown_mode_and_insufficient_real_reserves_fail_with_stable_codes() -> None:
    # Execute the test unknown mode and insufficient real reserves fail with stable codes
    # workflow in explicit, reviewable steps.
    with pytest.raises(PumpQuoteError) as unknown:
        # Keep raises, pump quote error and pytest active only for the bounded test
        # unknown mode and insufficient real reserves fail with stable codes operation.
        buy_quote(
            _state(mode=PumpMode.UNKNOWN),
            spendable_gross_sol_lamports=1_000_000,
            fee_profile=_PROFILE,
            effective_at_unix_s=_EFFECTIVE_AT,
            # Complete buy_quote only after its unknown and state inputs are visible in test
            # unknown mode and insufficient real reserves fail with stable codes.
        )
    assert unknown.value.code is PumpQuoteErrorCode.UNKNOWN_MODE

    with pytest.raises(PumpQuoteError) as buy_reserve:
        # Keep raises, pump quote error and pytest active only for the bounded test
        # unknown mode and insufficient real reserves fail with stable codes operation.
        buy_quote(
            _state(real_token_reserves_atomic=1),
            spendable_gross_sol_lamports=1_000_000,
            fee_profile=_PROFILE,
            effective_at_unix_s=_EFFECTIVE_AT,
            # Complete buy_quote only after its state and profile inputs are visible in test
            # unknown mode and insufficient real reserves fail with stable codes.
        )
    assert buy_reserve.value.code is PumpQuoteErrorCode.INSUFFICIENT_REAL_TOKEN_RESERVES

    with pytest.raises(PumpQuoteError) as sell_reserve:
        # Keep raises, pump quote error and pytest active only for the bounded test
        # unknown mode and insufficient real reserves fail with stable codes operation.
        sell_quote(
            _state(real_sol_reserves_lamports=1),
            tokens_in_atomic=1_000_000_000,
            fee_profile=_PROFILE,
            effective_at_unix_s=_EFFECTIVE_AT,
            # Complete sell_quote only after its state and profile inputs are visible in test
            # unknown mode and insufficient real reserves fail with stable codes.
        )
    assert sell_reserve.value.code is PumpQuoteErrorCode.INSUFFICIENT_REAL_SOL_RESERVES


def test_slippage_floor_and_signed_raw_delta_are_exact_integers() -> None:
    # Execute the test slippage floor and signed raw delta are exact integers workflow in
    # explicit, reviewable steps.
    assert minimum_output_atomic(999, 100) == 989

    failed = assess_slippage(
        reference_output_atomic=1_000,
        landing_output_atomic=989,
        slippage_bps=100,
        # Complete assess_slippage only after its declared inputs are visible in test slippage
        # floor and signed raw delta are exact integers.
    )
    favorable = assess_slippage(
        reference_output_atomic=1_000,
        landing_output_atomic=1_001,
        slippage_bps=100,
        # Complete assess_slippage only after its declared inputs are visible in test slippage
        # floor and signed raw delta are exact integers.
    )

    assert failed.minimum_output_atomic == 990
    assert failed.raw_delta_atomic == -11
    assert not failed.limit_met
    assert favorable.raw_delta_atomic == 1
    # Verify favorable.limit_met before this scenario is accepted.
    assert favorable.limit_met


@given(spendable=st.integers(min_value=100_000, max_value=10_000_000_000))
def test_buy_quote_never_exceeds_budget_and_rounds_components_separately(
    spendable: int,
) -> None:
    # Execute the test buy quote never exceeds budget and rounds components separately
    # workflow in explicit, reviewable steps.
    quote = buy_quote(
        _state(),
        spendable_gross_sol_lamports=spendable,
        fee_profile=_PROFILE,
        effective_at_unix_s=_EFFECTIVE_AT,
        # Complete buy_quote only after its state and spendable inputs are visible in test buy
        # quote never exceeds budget and rounds components separately.
    )

    expected_protocol_fee = (quote.fee_basis_sol_lamports * 95 + 9_999) // 10_000
    expected_creator_fee = (quote.fee_basis_sol_lamports * 30 + 9_999) // 10_000
    assert quote.gross_sol_spent_lamports <= spendable
    assert quote.fees.protocol_fee_lamports == expected_protocol_fee
    # Verify the creator fee lamports, expected creator fee and fees relationship before
    # this scenario is accepted.
    assert quote.fees.creator_fee_lamports == expected_creator_fee
    assert 0 < quote.tokens_out_atomic <= _state().real_token_reserves_atomic


@given(tokens=st.integers(min_value=1_000_000, max_value=100_000_000_000_000))
def test_sell_quote_conserves_gross_output_across_independent_fee_components(
    tokens: int,
    # Close the test sell quote conserves gross output across independent fee components
    # signature after its explicit inputs.
) -> None:
    # Execute the test sell quote conserves gross output across independent fee components
    # workflow in explicit, reviewable steps.
    quote = sell_quote(
        _state(),
        tokens_in_atomic=tokens,
        fee_profile=_PROFILE,
        effective_at_unix_s=_EFFECTIVE_AT,
        # Complete sell_quote only after its state and tokens inputs are visible in test sell
        # quote conserves gross output across independent fee components.
    )

    assert quote.gross_curve_sol_lamports == (
        quote.sol_out_lamports + quote.fees.protocol_fee_lamports + quote.fees.creator_fee_lamports
    )
    assert (
        # Keep the protocol fee lamports expectation tied to protocol fee lamports, fees
        # and quote in this scenario.
        quote.fees.protocol_fee_lamports == (quote.gross_curve_sol_lamports * 95 + 9_999) // 10_000
    )
    assert (
        quote.fees.creator_fee_lamports == (quote.gross_curve_sol_lamports * 30 + 9_999) // 10_000
    )


# Define test checked u64 state and boolean inputs are rejected as one focused operation
# with an explicit boundary.
def test_checked_u64_state_and_boolean_inputs_are_rejected() -> None:
    # Execute the test checked u64 state and boolean inputs are rejected workflow in
    # explicit, reviewable steps.
    with pytest.raises(TypeError, match="integer"):
        # Keep raises, type error and pytest active only for the bounded test checked u64
        # state and boolean inputs are rejected operation.
        buy_quote(
            _state(),
            spendable_gross_sol_lamports=True,
            fee_profile=_PROFILE,
            effective_at_unix_s=_EFFECTIVE_AT,
            # Complete buy_quote only after its state and profile inputs are visible in test
            # checked u64 state and boolean inputs are rejected.
        )
    with pytest.raises(ValueError, match="u64"):
        replace(_state(), virtual_sol_reserves_lamports=1 << 64)
