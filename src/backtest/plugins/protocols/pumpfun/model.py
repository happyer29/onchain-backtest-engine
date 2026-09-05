"""Versioned, checked-integer Pump bonding-curve quote semantics.

This module deliberately does not infer which deployed Pump program/version was
active at a historical boundary.  A caller must first resolve a versioned,
half-open :class:`PumpFeeProfile` from proven source data.  Consequently these
formulas are deterministic protocol contracts, not a claim that an arbitrary
live or historical Pump transaction has exact fidelity.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar, Self

from backtest.engine.sniping_contracts import (
    REAL_RESERVE_CAPPED_LIQUIDITY_POLICY_ID,
    VIRTUAL_RESERVE_EXPLICIT_SHORTFALL_LIQUIDITY_POLICY_ID,
)

_BASIS_POINTS_DENOMINATOR = 10_000
# Bind max u64 once as an explicit module-level contract.
_MAX_U64 = (1 << 64) - 1
_MAX_U128 = (1 << 128) - 1

PUMP_STATIC_PROGRAM_CONTRACT_V1 = "pump-program-static-fee-v1"
PUMP_BUY_EXACT_GROSS_SOL_FORMULA_V1 = "pump-buy-exact-gross-sol-v1"
PUMP_BUY_LEGACY_EXACT_NET_SOL_FORMULA_V1 = "pump-buy-legacy-exact-net-sol-v1"
# Bind pump sell exact token in formula v1 once as an explicit module-level contract.
PUMP_SELL_EXACT_TOKEN_IN_FORMULA_V1 = "pump-sell-exact-token-in-v1"
PUMP_HISTORICAL_COMPONENT_FEE_FORMULA_V1 = "pump-historical-component-fees-v1"

_SUPPORTED_BUY_FORMULAS = frozenset(
    {
        PUMP_BUY_EXACT_GROSS_SOL_FORMULA_V1,
        PUMP_BUY_LEGACY_EXACT_NET_SOL_FORMULA_V1,
        # Close the pump buy exact gross sol formula v1 and pump buy legacy exact net sol
        # formula v1 payload only after all module fields are present.
    }
)
_SUPPORTED_SELL_FORMULAS = frozenset({PUMP_SELL_EXACT_TOKEN_IN_FORMULA_V1})


class PumpMode(StrEnum):
    """Closed Pump coin modes supported by this quote contract.

    ``CASHBACK`` and ``MAYHEM`` are create-v2/Token-2022 modes.  The explicit
    ``TOKEN_2022`` member represents an otherwise normal create-v2 coin.
    """

    NORMAL = "NORMAL"
    TOKEN_2022 = "TOKEN_2022"
    CASHBACK = "CASHBACK"
    MAYHEM = "MAYHEM"
    UNKNOWN = "UNKNOWN"


# Keep the pump curve lifecycle contract and validation rules together.
class PumpCurveLifecycle(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    MIGRATED = "MIGRATED"
    UNKNOWN = "UNKNOWN"


# Keep the pump token program contract and validation rules together.
class PumpTokenProgram(StrEnum):
    LEGACY_SPL_TOKEN = "LEGACY_SPL_TOKEN"
    TOKEN_2022 = "TOKEN_2022"


# Keep the pump protocol fee route contract and validation rules together.
class PumpProtocolFeeRoute(StrEnum):
    NORMAL_RECIPIENT = "NORMAL_RECIPIENT"
    MAYHEM_RECIPIENT = "MAYHEM_RECIPIENT"


# Keep the pump creator fee route contract and validation rules together.
class PumpCreatorFeeRoute(StrEnum):
    CREATOR_VAULT = "CREATOR_VAULT"
    CASHBACK_RECEIVABLE = "CASHBACK_RECEIVABLE"


# Keep the pump quote error code contract and validation rules together.
class PumpQuoteErrorCode(StrEnum):
    UNSUPPORTED_PROGRAM_VERSION = "UNSUPPORTED_PROGRAM_VERSION"
    UNSUPPORTED_FORMULA_VERSION = "UNSUPPORTED_FORMULA_VERSION"
    PROFILE_NOT_EFFECTIVE = "PROFILE_NOT_EFFECTIVE"
    UNKNOWN_MODE = "UNKNOWN_MODE"
    # Declare unknown lifecycle explicitly in the pump quote error code contract.
    UNKNOWN_LIFECYCLE = "UNKNOWN_LIFECYCLE"
    CURVE_COMPLETED = "CURVE_COMPLETED"
    PUMPSWAP_ROUTING_FORBIDDEN = "PUMPSWAP_ROUTING_FORBIDDEN"
    INPUT_OUT_OF_BOUNDS = "INPUT_OUT_OF_BOUNDS"
    OUTPUT_OUT_OF_BOUNDS = "OUTPUT_OUT_OF_BOUNDS"
    # Declare insufficient real token reserves explicitly in the pump quote error code
    # contract.
    INSUFFICIENT_REAL_TOKEN_RESERVES = "INSUFFICIENT_REAL_TOKEN_RESERVES"
    INSUFFICIENT_REAL_SOL_RESERVES = "INSUFFICIENT_REAL_SOL_RESERVES"
    ARITHMETIC_OVERFLOW = "ARITHMETIC_OVERFLOW"


# Keep the sell solvency policy explicit and versioned in quote semantics.
class PumpSellLiquidityPolicy(StrEnum):
    REAL_RESERVE_CAPPED_V1 = REAL_RESERVE_CAPPED_LIQUIDITY_POLICY_ID
    VIRTUAL_RESERVE_OUTPUT_WITH_EXPLICIT_SYNTHETIC_SHORTFALL_V1 = (
        VIRTUAL_RESERVE_EXPLICIT_SHORTFALL_LIQUIDITY_POLICY_ID
    )


class PumpQuoteError(ValueError):
    """Expected deterministic Pump quote rejection with a stable code."""

    def __init__(self, code: PumpQuoteErrorCode) -> None:
        # Execute the pump quote error init workflow in explicit, reviewable steps.
        if not isinstance(code, PumpQuoteErrorCode):
            raise TypeError("code must be a PumpQuoteErrorCode")
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
# Keep the pump curve state v1 contract and validation rules together.
class PumpCurveStateV1:
    """Minimum immutable state needed by the static-fee Pump curve model."""

    SCHEMA_VERSION: ClassVar[str] = "pump-curve-state-v1"

    virtual_token_reserves_atomic: int
    virtual_sol_reserves_lamports: int
    real_token_reserves_atomic: int
    real_sol_reserves_lamports: int
    # Declare token total supply atomic explicitly in the pump curve state v1 contract.
    token_total_supply_atomic: int
    lifecycle: PumpCurveLifecycle
    mode: PumpMode

    def __post_init__(self) -> None:
        # Execute the pump curve state v1 post init workflow in explicit, reviewable
        # steps.
        _require_u64(
            "virtual_token_reserves_atomic",
            self.virtual_token_reserves_atomic,
            positive=True,
        )
        # Invoke _require_u64 for virtual sol reserves lamports as a visible pump curve
        # state v1 post init step.
        _require_u64(
            "virtual_sol_reserves_lamports",
            self.virtual_sol_reserves_lamports,
            positive=True,
        )
        # Invoke _require_u64 for real token reserves atomic as a visible pump curve state
        # v1 post init step.
        _require_u64("real_token_reserves_atomic", self.real_token_reserves_atomic)
        _require_u64("real_sol_reserves_lamports", self.real_sol_reserves_lamports)
        _require_u64(
            "token_total_supply_atomic",
            self.token_total_supply_atomic,
            # Pass positive explicitly so _require_u64 receives a reviewable token total
            # supply atomic input in pump curve state v1 post init.
            positive=True,
        )
        if self.real_token_reserves_atomic > self.token_total_supply_atomic:
            raise ValueError("real token reserves cannot exceed total token supply")
        if not isinstance(self.lifecycle, PumpCurveLifecycle):
            # Fail the pump curve state v1 post init path with TypeError for lifecycle
            # must be a pump curve lifecycle when isinstance, lifecycle and pump curve
            # lifecycle is true; do not continue ambiguously.
            raise TypeError("lifecycle must be a PumpCurveLifecycle")
        if not isinstance(self.mode, PumpMode):
            raise TypeError("mode must be a PumpMode")


@dataclass(frozen=True, slots=True)
class PumpFeeProfile:
    """Resolved static Pump fee and formula contract for one effective interval."""

    profile_id: str
    program_version: str
    buy_formula_version: str
    sell_formula_version: str
    effective_from_unix_s: int
    # Declare effective until unix s explicitly in the pump fee profile contract.
    effective_until_unix_s: int
    protocol_fee_bps: int
    creator_fee_bps: int

    def __post_init__(self) -> None:
        # Execute the pump fee profile post init workflow in explicit, reviewable steps.
        _require_stable_name("profile_id", self.profile_id)
        _require_stable_name("program_version", self.program_version)
        _require_stable_name("buy_formula_version", self.buy_formula_version)
        _require_stable_name("sell_formula_version", self.sell_formula_version)
        _require_u64("effective_from_unix_s", self.effective_from_unix_s)
        # Invoke _require_u64 for effective until unix s as a visible pump fee profile
        # post init step.
        _require_u64("effective_until_unix_s", self.effective_until_unix_s)
        if self.effective_until_unix_s <= self.effective_from_unix_s:
            raise ValueError("fee profile effective interval must be non-empty and half-open")
        _require_basis_points("protocol_fee_bps", self.protocol_fee_bps)
        _require_basis_points("creator_fee_bps", self.creator_fee_bps)
        # Evaluate the complete pump fee profile post init basis points denominator,
        # protocol fee bps and creator fee bps condition before guarded effects.
        if self.protocol_fee_bps + self.creator_fee_bps >= _BASIS_POINTS_DENOMINATOR:
            raise ValueError("combined Pump fees must be below 10000 basis points")

    @classmethod
    def static_95_30(
        cls,
        # Close the static 95 30 signature after its explicit inputs.
        *,
        profile_id: str,
        effective_from_unix_s: int,
        effective_until_unix_s: int,
    ) -> Self:
        """Build the explicitly bounded 95-bps protocol/30-bps creator profile."""

        return cls(
            profile_id=profile_id,
            program_version=PUMP_STATIC_PROGRAM_CONTRACT_V1,
            buy_formula_version=PUMP_BUY_EXACT_GROSS_SOL_FORMULA_V1,
            sell_formula_version=PUMP_SELL_EXACT_TOKEN_IN_FORMULA_V1,
            # Pass effective from unix s explicitly so cls receives a reviewable profile
            # id and pump static program contract v1 input in pump fee profile static 95
            # 30.
            effective_from_unix_s=effective_from_unix_s,
            effective_until_unix_s=effective_until_unix_s,
            protocol_fee_bps=95,
            creator_fee_bps=30,
        )


# Keep the pump fee routing contract and validation rules together.
@dataclass(frozen=True, slots=True)
class PumpFeeRouting:
    token_program: PumpTokenProgram
    protocol_fee_route: PumpProtocolFeeRoute
    creator_fee_route: PumpCreatorFeeRoute

    # Define pump fee routing post init as one focused operation with an explicit
    # boundary.
    def __post_init__(self) -> None:
        # Execute the pump fee routing post init workflow in explicit, reviewable steps.
        if not isinstance(self.token_program, PumpTokenProgram):
            raise TypeError("token_program must be PumpTokenProgram")
        if not isinstance(self.protocol_fee_route, PumpProtocolFeeRoute):
            raise TypeError("protocol_fee_route must be PumpProtocolFeeRoute")
        if not isinstance(self.creator_fee_route, PumpCreatorFeeRoute):
            # Fail the pump fee routing post init path with TypeError for creator fee
            # route must be pump creator fee route when isinstance, creator fee route and
            # pump creator fee route is true; do not continue ambiguously.
            raise TypeError("creator_fee_route must be PumpCreatorFeeRoute")


# Keep the pump fee breakdown contract and validation rules together.
@dataclass(frozen=True, slots=True)
class PumpFeeBreakdown:
    protocol_fee_lamports: int
    creator_fee_lamports: int
    routing: PumpFeeRouting
    # Declare cashback receivable lamports explicitly in the pump fee breakdown contract.
    cashback_receivable_lamports: int | None

    def __post_init__(self) -> None:
        # Execute the pump fee breakdown post init workflow in explicit, reviewable steps.
        _require_u64("protocol_fee_lamports", self.protocol_fee_lamports)
        _require_u64("creator_fee_lamports", self.creator_fee_lamports)
        if not isinstance(self.routing, PumpFeeRouting):
            raise TypeError("routing must be PumpFeeRouting")
        if self.routing.creator_fee_route is PumpCreatorFeeRoute.CASHBACK_RECEIVABLE:
            # Handle the pump fee breakdown post init creator fee route, cashback
            # receivable and routing condition as a distinct block.
            if self.cashback_receivable_lamports != self.creator_fee_lamports:
                raise ValueError("cashback receivable must equal the routed creator fee")
        # Handle the pump fee breakdown post init complement of creator fee route,
        # cashback receivable and routing explicitly.
        elif self.cashback_receivable_lamports is not None:
            raise ValueError("non-cashback routing cannot expose a cashback receivable")

    @property
    def total_fee_lamports(self) -> int:
        return self.protocol_fee_lamports + self.creator_fee_lamports


# Keep the pump buy quote contract and validation rules together.
@dataclass(frozen=True, slots=True)
class PumpBuyQuote:
    formula_version: str
    spendable_gross_sol_lamports: int
    gross_sol_spent_lamports: int
    # Declare fee basis sol lamports explicitly in the pump buy quote contract.
    fee_basis_sol_lamports: int
    net_curve_sol_lamports: int
    tokens_out_atomic: int
    fees: PumpFeeBreakdown

    def __post_init__(self) -> None:
        # Execute the pump buy quote post init workflow in explicit, reviewable steps.
        _require_stable_name("formula_version", self.formula_version)
        _require_u64(
            "spendable_gross_sol_lamports",
            self.spendable_gross_sol_lamports,
            positive=True,
            # Complete _require_u64 only after its spendable gross sol lamports inputs are
            # visible in pump buy quote post init.
        )
        _require_u64("gross_sol_spent_lamports", self.gross_sol_spent_lamports, positive=True)
        _require_u64("fee_basis_sol_lamports", self.fee_basis_sol_lamports, positive=True)
        _require_u64("net_curve_sol_lamports", self.net_curve_sol_lamports, positive=True)
        _require_u64("tokens_out_atomic", self.tokens_out_atomic, positive=True)
        # Evaluate the complete pump buy quote post init isinstance, fees and pump fee
        # breakdown condition before guarded effects.
        if not isinstance(self.fees, PumpFeeBreakdown):
            raise TypeError("fees must be PumpFeeBreakdown")
        if self.gross_sol_spent_lamports != (
            self.net_curve_sol_lamports + self.fees.total_fee_lamports
        ):
            # Fail the pump buy quote post init path with ValueError for buy gross spend
            # must equal curve input plus fee components when gross sol spent lamports,
            # net curve sol lamports and total fee lamports is true; do not continue
            # ambiguously.
            raise ValueError("buy gross spend must equal curve input plus fee components")
        if self.gross_sol_spent_lamports > self.spendable_gross_sol_lamports:
            raise ValueError("buy gross spend cannot exceed the spendable budget")
        if self.fee_basis_sol_lamports < self.net_curve_sol_lamports:
            raise ValueError("buy fee basis cannot be below the adjusted curve input")

    # Apply property semantics to the following pump buy quote unspent sol lamports
    # contract.
    @property
    def unspent_sol_lamports(self) -> int:
        return self.spendable_gross_sol_lamports - self.gross_sol_spent_lamports

    @property
    def amount_out_atomic(self) -> int:
        # Return the completed pump buy quote amount out atomic result without a hidden
        # fallback.
        return self.tokens_out_atomic


# Keep the pump sell quote contract and validation rules together.
@dataclass(frozen=True, slots=True)
class PumpSellQuote:
    formula_version: str
    tokens_in_atomic: int
    gross_curve_sol_lamports: int
    # Declare sol out lamports explicitly in the pump sell quote contract.
    sol_out_lamports: int
    liquidity_policy: PumpSellLiquidityPolicy
    observed_real_sol_reserves_lamports: int
    # Shortfall is measured against gross curve output before component fees.
    synthetic_shortfall_lamports: int
    fees: PumpFeeBreakdown

    def __post_init__(self) -> None:
        # Execute the pump sell quote post init workflow in explicit, reviewable steps.
        _require_stable_name("formula_version", self.formula_version)
        _require_u64("tokens_in_atomic", self.tokens_in_atomic, positive=True)
        _require_u64("gross_curve_sol_lamports", self.gross_curve_sol_lamports, positive=True)
        _require_u64("sol_out_lamports", self.sol_out_lamports, positive=True)
        if not isinstance(self.liquidity_policy, PumpSellLiquidityPolicy):
            raise TypeError("liquidity_policy must be a PumpSellLiquidityPolicy")
        _require_u64(
            "observed_real_sol_reserves_lamports",
            self.observed_real_sol_reserves_lamports,
        )
        _require_u64("synthetic_shortfall_lamports", self.synthetic_shortfall_lamports)
        if not isinstance(self.fees, PumpFeeBreakdown):
            # Fail the pump sell quote post init path with TypeError for fees must be pump
            # fee breakdown when isinstance, fees and pump fee breakdown is true; do not
            # continue ambiguously.
            raise TypeError("fees must be PumpFeeBreakdown")
        if self.gross_curve_sol_lamports != self.sol_out_lamports + self.fees.total_fee_lamports:
            raise ValueError("sell gross output must equal net output plus fee components")
        # The evidence must exactly expose any gross-output liquidity deficit.
        expected_shortfall = max(
            0,
            self.gross_curve_sol_lamports - self.observed_real_sol_reserves_lamports,
        )
        if self.synthetic_shortfall_lamports != expected_shortfall:
            raise ValueError("sell synthetic shortfall is inconsistent with real reserves")
        if (
            self.liquidity_policy is PumpSellLiquidityPolicy.REAL_RESERVE_CAPPED_V1
            and self.synthetic_shortfall_lamports != 0
        ):
            raise ValueError("real-reserve-capped quote cannot contain a synthetic shortfall")

    @property
    def amount_out_atomic(self) -> int:
        # Return the completed pump sell quote amount out atomic result without a hidden
        # fallback.
        return self.sol_out_lamports


# Keep the pump slippage assessment contract and validation rules together.
@dataclass(frozen=True, slots=True)
class PumpSlippageAssessment:
    reference_output_atomic: int
    landing_output_atomic: int
    minimum_output_atomic: int
    # Declare raw delta atomic explicitly in the pump slippage assessment contract.
    raw_delta_atomic: int
    limit_met: bool

    def __post_init__(self) -> None:
        # Execute the pump slippage assessment post init workflow in explicit, reviewable
        # steps.
        _require_u64("reference_output_atomic", self.reference_output_atomic, positive=True)
        _require_u64("landing_output_atomic", self.landing_output_atomic)
        _require_u64("minimum_output_atomic", self.minimum_output_atomic)
        if isinstance(self.raw_delta_atomic, bool) or not isinstance(self.raw_delta_atomic, int):
            raise TypeError("raw_delta_atomic must be an integer")
        # Guard this path with not isinstance(self.limit_met, bool) before applying
        # effects.
        if not isinstance(self.limit_met, bool):
            raise TypeError("limit_met must be a boolean")
        if self.raw_delta_atomic != self.landing_output_atomic - self.reference_output_atomic:
            raise ValueError("raw slippage delta is inconsistent with quote outputs")
        if self.limit_met is not (self.landing_output_atomic >= self.minimum_output_atomic):
            # Fail the pump slippage assessment post init path with ValueError for
            # slippage limit status is inconsistent with minimum output when limit met,
            # landing output atomic and minimum output atomic is true; do not continue
            # ambiguously.
            raise ValueError("slippage limit status is inconsistent with minimum output")


def buy_quote(
    state: PumpCurveStateV1,
    *,
    spendable_gross_sol_lamports: int,
    # Keep the fee profile input explicit in the buy quote contract.
    fee_profile: PumpFeeProfile,
    effective_at_unix_s: int,
) -> PumpBuyQuote:
    """Quote Pump ``buy_exact_sol_in`` from a fixed gross SOL budget.

    The implementation follows the formula version named by the profile:
    derive net SOL, ceil each fee independently and adjust net SOL if the two
    independent round-ups exceed the budget.  Modern ``buy_exact_sol_in`` then
    applies its documented ``-1`` curve term.  The explicitly selected legacy
    ``buy`` contract uses the full net amount.
    """

    _validate_quote_contract(
        state,
        fee_profile,
        effective_at_unix_s,
        supported_formulas=_SUPPORTED_BUY_FORMULAS,
        # Pass actual formula explicitly so _validate_quote_contract receives a reviewable
        # buy formula version and state input in buy quote.
        actual_formula=fee_profile.buy_formula_version,
    )
    if (
        fee_profile.buy_formula_version == PUMP_BUY_LEGACY_EXACT_NET_SOL_FORMULA_V1
        and state.mode is not PumpMode.NORMAL
        # Evaluate the complete buy quote buy formula version, pump buy legacy exact net sol
        # formula v1 and mode condition before guarded effects.
    ):
        raise PumpQuoteError(PumpQuoteErrorCode.UNSUPPORTED_FORMULA_VERSION)
    _require_quote_input(spendable_gross_sol_lamports)

    total_fee_bps = fee_profile.protocol_fee_bps + fee_profile.creator_fee_bps
    initial_net_sol = _checked_mul_u128(
        # Pass spendable gross sol lamports explicitly so _checked_mul_u128 receives a
        # reviewable spendable gross sol lamports and basis points denominator input in
        # buy quote.
        spendable_gross_sol_lamports,
        _BASIS_POINTS_DENOMINATOR,
    ) // (_BASIS_POINTS_DENOMINATOR + total_fee_bps)
    protocol_fee = _fee_ceil(initial_net_sol, fee_profile.protocol_fee_bps)
    creator_fee = _fee_ceil(initial_net_sol, fee_profile.creator_fee_bps)
    # Assemble gross before adjustment once so the buy quote workflow shares one value.
    gross_before_adjustment = initial_net_sol + protocol_fee + creator_fee
    budget_excess = max(0, gross_before_adjustment - spendable_gross_sol_lamports)
    net_curve_sol = initial_net_sol - budget_excess
    if fee_profile.buy_formula_version == PUMP_BUY_EXACT_GROSS_SOL_FORMULA_V1:
        # Handle the buy quote buy formula version, pump buy exact gross sol formula v1
        # and fee profile condition as a distinct block.
        if net_curve_sol <= 1:
            raise PumpQuoteError(PumpQuoteErrorCode.OUTPUT_OUT_OF_BOUNDS)
        curve_sol = net_curve_sol - 1
    else:
        # Handle the buy quote complement of buy formula version, pump buy exact gross sol
        # formula v1 and fee profile explicitly.
        if net_curve_sol <= 0:
            raise PumpQuoteError(PumpQuoteErrorCode.OUTPUT_OUT_OF_BOUNDS)
        curve_sol = net_curve_sol

    _checked_add_u64(state.virtual_sol_reserves_lamports, net_curve_sol)
    _checked_add_u64(state.real_sol_reserves_lamports, net_curve_sol)
    # Assemble tokens out once so the buy quote workflow shares one value.
    tokens_out = _checked_mul_u128(
        curve_sol,
        state.virtual_token_reserves_atomic,
    ) // (state.virtual_sol_reserves_lamports + curve_sol)
    if tokens_out <= 0 or tokens_out >= state.virtual_token_reserves_atomic:
        # Fail the buy quote path with PumpQuoteError for output out of bounds and pump
        # quote error code when tokens out, virtual token reserves atomic and state is
        # true; do not continue ambiguously.
        raise PumpQuoteError(PumpQuoteErrorCode.OUTPUT_OUT_OF_BOUNDS)
    if tokens_out > state.real_token_reserves_atomic:
        raise PumpQuoteError(PumpQuoteErrorCode.INSUFFICIENT_REAL_TOKEN_RESERVES)

    fees = _fee_breakdown(state.mode, protocol_fee, creator_fee)
    gross_spent = net_curve_sol + fees.total_fee_lamports
    # Evaluate the complete buy quote gross spent and spendable gross sol lamports
    # condition before guarded effects.
    if gross_spent > spendable_gross_sol_lamports:
        raise PumpQuoteError(PumpQuoteErrorCode.ARITHMETIC_OVERFLOW)
    return PumpBuyQuote(
        formula_version=fee_profile.buy_formula_version,
        spendable_gross_sol_lamports=spendable_gross_sol_lamports,
        # Pass gross sol spent lamports explicitly so PumpBuyQuote receives a reviewable
        # buy formula version and fee profile input in buy quote.
        gross_sol_spent_lamports=gross_spent,
        fee_basis_sol_lamports=initial_net_sol,
        net_curve_sol_lamports=net_curve_sol,
        tokens_out_atomic=tokens_out,
        fees=fees,
        # Complete PumpBuyQuote only after its buy formula version and fee profile inputs are
        # visible in buy quote.
    )


def sell_quote(
    state: PumpCurveStateV1,
    *,
    tokens_in_atomic: int,
    # Keep the fee profile input explicit in the sell quote contract.
    fee_profile: PumpFeeProfile,
    effective_at_unix_s: int,
    # Default preserves the original on-program real-reserve solvency gate.
    liquidity_policy: PumpSellLiquidityPolicy = PumpSellLiquidityPolicy.REAL_RESERVE_CAPPED_V1,
) -> PumpSellQuote:
    """Quote selling the supplied full token balance into the Pump curve."""

    if not isinstance(liquidity_policy, PumpSellLiquidityPolicy):
        raise TypeError("liquidity_policy must be a PumpSellLiquidityPolicy")
    _validate_quote_contract(
        state,
        fee_profile,
        effective_at_unix_s,
        supported_formulas=_SUPPORTED_SELL_FORMULAS,
        # Pass actual formula explicitly so _validate_quote_contract receives a reviewable
        # sell formula version and state input in sell quote.
        actual_formula=fee_profile.sell_formula_version,
    )
    _require_quote_input(tokens_in_atomic)
    _checked_add_u64(state.virtual_token_reserves_atomic, tokens_in_atomic)
    _checked_add_u64(state.real_token_reserves_atomic, tokens_in_atomic)

    # Assemble gross curve sol once so the sell quote workflow shares one value.
    gross_curve_sol = _checked_mul_u128(
        tokens_in_atomic,
        state.virtual_sol_reserves_lamports,
    ) // (state.virtual_token_reserves_atomic + tokens_in_atomic)
    if gross_curve_sol <= 0 or gross_curve_sol >= state.virtual_sol_reserves_lamports:
        # Fail the sell quote path with PumpQuoteError for output out of bounds and pump
        # quote error code when gross curve sol, virtual sol reserves lamports and state
        # is true; do not continue ambiguously.
        raise PumpQuoteError(PumpQuoteErrorCode.OUTPUT_OUT_OF_BOUNDS)
    synthetic_shortfall = max(0, gross_curve_sol - state.real_sol_reserves_lamports)
    if (
        liquidity_policy is PumpSellLiquidityPolicy.REAL_RESERVE_CAPPED_V1
        and synthetic_shortfall > 0
    ):
        raise PumpQuoteError(PumpQuoteErrorCode.INSUFFICIENT_REAL_SOL_RESERVES)

    protocol_fee = _fee_ceil(gross_curve_sol, fee_profile.protocol_fee_bps)
    creator_fee = _fee_ceil(gross_curve_sol, fee_profile.creator_fee_bps)
    # Assemble total fee once so the sell quote workflow shares one value.
    total_fee = protocol_fee + creator_fee
    if total_fee >= gross_curve_sol:
        raise PumpQuoteError(PumpQuoteErrorCode.OUTPUT_OUT_OF_BOUNDS)
    sol_out = gross_curve_sol - total_fee
    return PumpSellQuote(
        # Pass formula version explicitly so PumpSellQuote receives a reviewable mode and
        # fee breakdown input in sell quote.
        formula_version=PUMP_SELL_EXACT_TOKEN_IN_FORMULA_V1,
        tokens_in_atomic=tokens_in_atomic,
        gross_curve_sol_lamports=gross_curve_sol,
        sol_out_lamports=sol_out,
        liquidity_policy=liquidity_policy,
        observed_real_sol_reserves_lamports=state.real_sol_reserves_lamports,
        # Preserve gross-output shortfall independently from fee routing.
        synthetic_shortfall_lamports=synthetic_shortfall,
        fees=_fee_breakdown(state.mode, protocol_fee, creator_fee),
        # Complete PumpSellQuote only after its mode and fee breakdown inputs are visible in
        # sell quote.
    )


def minimum_output_atomic(reference_output_atomic: int, slippage_bps: int) -> int:
    """Return a floor-rounded minimum output without floating point."""

    _require_u64("reference_output_atomic", reference_output_atomic, positive=True)
    _require_basis_points("slippage_bps", slippage_bps, allow_full=True)
    return (
        _checked_mul_u128(
            reference_output_atomic,
            # Pass basis points denominator explicitly so _checked_mul_u128 receives a
            # reviewable reference output atomic and basis points denominator input in
            # minimum output atomic.
            _BASIS_POINTS_DENOMINATOR - slippage_bps,
        )
        // _BASIS_POINTS_DENOMINATOR
    )


def historical_trade_fee_breakdown(
    mode: PumpMode,
    *,
    curve_sol_lamports: int,
    fee_profile: PumpFeeProfile,
    effective_at_unix_s: int,
) -> PumpFeeBreakdown:
    """Derive exact historical components from the observed curve-SOL delta.

    The indexer profile supplies the reserve delta, not fee-transfer rows.  Pump's
    effective-dated static profile applies protocol and creator basis points to that
    same amount and rounds the two components independently with integer ceil.
    """

    if not isinstance(mode, PumpMode):
        raise TypeError("mode must be a PumpMode")
    if not isinstance(fee_profile, PumpFeeProfile):
        raise TypeError("fee_profile must be a PumpFeeProfile")
    _require_u64("curve_sol_lamports", curve_sol_lamports)
    _require_u64("effective_at_unix_s", effective_at_unix_s)
    if fee_profile.program_version != PUMP_STATIC_PROGRAM_CONTRACT_V1:
        raise PumpQuoteError(PumpQuoteErrorCode.UNSUPPORTED_PROGRAM_VERSION)
    if not (
        fee_profile.effective_from_unix_s
        <= effective_at_unix_s
        < fee_profile.effective_until_unix_s
    ):
        raise PumpQuoteError(PumpQuoteErrorCode.PROFILE_NOT_EFFECTIVE)
    if mode is PumpMode.UNKNOWN:
        raise PumpQuoteError(PumpQuoteErrorCode.UNKNOWN_MODE)
    return _fee_breakdown(
        mode,
        _fee_ceil(curve_sol_lamports, fee_profile.protocol_fee_bps),
        _fee_ceil(curve_sol_lamports, fee_profile.creator_fee_bps),
    )


def assess_slippage(
    # Close the assess slippage signature after its explicit inputs.
    *,
    reference_output_atomic: int,
    landing_output_atomic: int,
    slippage_bps: int,
) -> PumpSlippageAssessment:
    """Compare a landing quote to an earlier quote and retain the signed delta."""

    minimum = minimum_output_atomic(reference_output_atomic, slippage_bps)
    _require_u64("landing_output_atomic", landing_output_atomic)
    return PumpSlippageAssessment(
        reference_output_atomic=reference_output_atomic,
        landing_output_atomic=landing_output_atomic,
        # Pass minimum output atomic explicitly so PumpSlippageAssessment receives a
        # reviewable reference output atomic and landing output atomic input in assess
        # slippage.
        minimum_output_atomic=minimum,
        raw_delta_atomic=landing_output_atomic - reference_output_atomic,
        limit_met=landing_output_atomic >= minimum,
    )


def _validate_quote_contract(
    # Keep the state input explicit in the validate quote contract contract.
    state: PumpCurveStateV1,
    fee_profile: PumpFeeProfile,
    effective_at_unix_s: int,
    *,
    supported_formulas: frozenset[str],
    # Keep the actual formula input explicit in the validate quote contract contract.
    actual_formula: str,
) -> None:
    # Execute the validate quote contract workflow in explicit, reviewable steps.
    if not isinstance(state, PumpCurveStateV1):
        raise TypeError("state must be PumpCurveStateV1")
    if not isinstance(fee_profile, PumpFeeProfile):
        raise TypeError("fee_profile must be PumpFeeProfile")
    _require_u64("effective_at_unix_s", effective_at_unix_s)
    # Evaluate the complete validate quote contract program version, pump static program
    # contract v1 and fee profile condition before guarded effects.
    if fee_profile.program_version != PUMP_STATIC_PROGRAM_CONTRACT_V1:
        raise PumpQuoteError(PumpQuoteErrorCode.UNSUPPORTED_PROGRAM_VERSION)
    if actual_formula not in supported_formulas:
        raise PumpQuoteError(PumpQuoteErrorCode.UNSUPPORTED_FORMULA_VERSION)
    if not (
        # Keep fee profile visible while evaluating the effective from unix s, effective
        # at unix s and effective until unix s guard.
        fee_profile.effective_from_unix_s
        <= effective_at_unix_s
        < fee_profile.effective_until_unix_s
    ):
        raise PumpQuoteError(PumpQuoteErrorCode.PROFILE_NOT_EFFECTIVE)
    # Evaluate the complete validate quote contract lifecycle, unknown and state condition
    # before guarded effects.
    if state.lifecycle is PumpCurveLifecycle.UNKNOWN:
        raise PumpQuoteError(PumpQuoteErrorCode.UNKNOWN_LIFECYCLE)
    if state.lifecycle is PumpCurveLifecycle.COMPLETED:
        raise PumpQuoteError(PumpQuoteErrorCode.CURVE_COMPLETED)
    if state.lifecycle is PumpCurveLifecycle.MIGRATED:
        # Fail the validate quote contract path with PumpQuoteError for pumpswap routing
        # forbidden and pump quote error code when lifecycle, migrated and state is true;
        # do not continue ambiguously.
        raise PumpQuoteError(PumpQuoteErrorCode.PUMPSWAP_ROUTING_FORBIDDEN)
    if state.mode is PumpMode.UNKNOWN:
        raise PumpQuoteError(PumpQuoteErrorCode.UNKNOWN_MODE)


def _fee_breakdown(
    mode: PumpMode,
    # Keep the protocol fee lamports input explicit in the fee breakdown contract.
    protocol_fee_lamports: int,
    creator_fee_lamports: int,
) -> PumpFeeBreakdown:
    # Execute the fee breakdown workflow in explicit, reviewable steps.
    routing = _fee_routing(mode)
    cashback = (
        creator_fee_lamports
        if routing.creator_fee_route is PumpCreatorFeeRoute.CASHBACK_RECEIVABLE
        else None
        # Complete the cashback group only after its semantic components are visible.
    )
    return PumpFeeBreakdown(
        protocol_fee_lamports=protocol_fee_lamports,
        creator_fee_lamports=creator_fee_lamports,
        routing=routing,
        # Pass cashback receivable lamports explicitly so PumpFeeBreakdown receives a
        # reviewable protocol fee lamports and creator fee lamports input in fee
        # breakdown.
        cashback_receivable_lamports=cashback,
    )


def _fee_routing(mode: PumpMode) -> PumpFeeRouting:
    # Execute the fee routing workflow in explicit, reviewable steps.
    if mode is PumpMode.NORMAL:
        # Handle the fee routing mode is PumpMode.NORMAL branch as a distinct logical
        # block.
        return PumpFeeRouting(
            token_program=PumpTokenProgram.LEGACY_SPL_TOKEN,
            protocol_fee_route=PumpProtocolFeeRoute.NORMAL_RECIPIENT,
            creator_fee_route=PumpCreatorFeeRoute.CREATOR_VAULT,
        )
    # Guard this path with mode is PumpMode.TOKEN_2022 before applying effects.
    if mode is PumpMode.TOKEN_2022:
        # Handle the fee routing mode is PumpMode.TOKEN_2022 branch as a distinct logical
        # block.
        return PumpFeeRouting(
            token_program=PumpTokenProgram.TOKEN_2022,
            protocol_fee_route=PumpProtocolFeeRoute.NORMAL_RECIPIENT,
            creator_fee_route=PumpCreatorFeeRoute.CREATOR_VAULT,
        )
    # Guard this path with mode is PumpMode.CASHBACK before applying effects.
    if mode is PumpMode.CASHBACK:
        # Handle the fee routing mode is PumpMode.CASHBACK branch as a distinct logical
        # block.
        return PumpFeeRouting(
            token_program=PumpTokenProgram.TOKEN_2022,
            protocol_fee_route=PumpProtocolFeeRoute.NORMAL_RECIPIENT,
            creator_fee_route=PumpCreatorFeeRoute.CASHBACK_RECEIVABLE,
        )
    # Guard this path with mode is PumpMode.MAYHEM before applying effects.
    if mode is PumpMode.MAYHEM:
        # Handle the fee routing mode is PumpMode.MAYHEM branch as a distinct logical
        # block.
        return PumpFeeRouting(
            token_program=PumpTokenProgram.TOKEN_2022,
            protocol_fee_route=PumpProtocolFeeRoute.MAYHEM_RECIPIENT,
            creator_fee_route=PumpCreatorFeeRoute.CREATOR_VAULT,
        )
    # Fail the fee routing path with PumpQuoteError for unknown mode and pump quote error
    # code; do not continue ambiguously.
    raise PumpQuoteError(PumpQuoteErrorCode.UNKNOWN_MODE)


def _fee_ceil(amount: int, fee_bps: int) -> int:
    # Execute the fee ceil workflow in explicit, reviewable steps.
    if fee_bps == 0:
        return 0
    numerator = _checked_mul_u128(amount, fee_bps)
    return (numerator + _BASIS_POINTS_DENOMINATOR - 1) // _BASIS_POINTS_DENOMINATOR


def _checked_mul_u128(left: int, right: int) -> int:
    # Execute the checked mul u128 workflow in explicit, reviewable steps.
    result = left * right
    if result > _MAX_U128:
        raise PumpQuoteError(PumpQuoteErrorCode.ARITHMETIC_OVERFLOW)
    return result


def _checked_add_u64(left: int, right: int) -> int:
    # Execute the checked add u64 workflow in explicit, reviewable steps.
    result = left + right
    if result > _MAX_U64:
        raise PumpQuoteError(PumpQuoteErrorCode.ARITHMETIC_OVERFLOW)
    return result


def _require_quote_input(value: int) -> None:
    # Execute the require quote input workflow in explicit, reviewable steps.
    try:
        _require_u64("quote input", value, positive=True)
    except ValueError as error:
        raise PumpQuoteError(PumpQuoteErrorCode.INPUT_OUT_OF_BOUNDS) from error


def _require_u64(name: str, value: int, *, positive: bool = False) -> None:
    # Execute the require u64 workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    minimum = 1 if positive else 0
    if not minimum <= value <= _MAX_U64:
        # Handle the require u64 not minimum <= value <= _MAX_U64 branch as a distinct
        # logical block.
        qualifier = "positive " if positive else ""
        raise ValueError(f"{name} must be a {qualifier}u64")


def _require_basis_points(name: str, value: int, *, allow_full: bool = False) -> None:
    # Execute the require basis points workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    upper = _BASIS_POINTS_DENOMINATOR if allow_full else _BASIS_POINTS_DENOMINATOR - 1
    if not 0 <= value <= upper:
        raise ValueError(f"{name} is outside its basis-point range")


# Define require stable name as one focused operation with an explicit boundary.
def _require_stable_name(name: str, value: str) -> None:
    # Execute the require stable name workflow in explicit, reviewable steps.
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value or value != value.strip() or len(value) > 128:
        raise ValueError(f"{name} must be non-empty, trimmed and at most 128 characters")
    if any(ord(character) < 32 or ord(character) > 126 for character in value):
        # Fail the require stable name path with ValueError for must contain printable
        # ascii only and name when character, value and ord is true; do not continue
        # ambiguously.
        raise ValueError(f"{name} must contain printable ASCII only")


__all__ = [
    "PUMP_BUY_EXACT_GROSS_SOL_FORMULA_V1",
    "PUMP_BUY_LEGACY_EXACT_NET_SOL_FORMULA_V1",
    "PUMP_HISTORICAL_COMPONENT_FEE_FORMULA_V1",
    "PUMP_SELL_EXACT_TOKEN_IN_FORMULA_V1",
    # Keep the pump static program contract v1 component named inside the all contract.
    "PUMP_STATIC_PROGRAM_CONTRACT_V1",
    "PumpBuyQuote",
    "PumpCreatorFeeRoute",
    "PumpCurveLifecycle",
    "PumpCurveStateV1",
    # Keep the pump fee breakdown component named inside the all contract.
    "PumpFeeBreakdown",
    "PumpFeeProfile",
    "PumpFeeRouting",
    "PumpMode",
    "PumpProtocolFeeRoute",
    # Keep the pump quote error component named inside the all contract.
    "PumpQuoteError",
    "PumpQuoteErrorCode",
    "PumpSellLiquidityPolicy",
    "PumpSellQuote",
    "PumpSlippageAssessment",
    "PumpTokenProgram",
    # Keep the assess slippage component named inside the all contract.
    "assess_slippage",
    "buy_quote",
    "historical_trade_fee_breakdown",
    "minimum_output_atomic",
    "sell_quote",
]
