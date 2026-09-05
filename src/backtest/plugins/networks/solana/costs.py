"""Versioned checked-integer Solana fee and account-deposit profiles."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Self

from backtest.domain.account_requirements import (
    AccountRequirement,
    PricedAccountRequirement,
    account_requirement_key,
    priced_account_requirement_key,
)
from backtest.domain.identifiers import AssetId

_MICRO_LAMPORTS_PER_LAMPORT = 1_000_000
# Bind max u64 once as an explicit module-level contract.
_MAX_U64 = (1 << 64) - 1
_MAX_U128 = (1 << 128) - 1

SOLANA_LEGACY_V0_FEE_FORMULA_V1 = "solana-legacy-v0-base-priority-v1"
SOLANA_LEGACY_V0_MAX_COMPUTE_UNIT_LIMIT = 1_400_000


# Keep the solana transaction format contract and validation rules together.
class SolanaTransactionFormat(StrEnum):
    LEGACY = "LEGACY"
    V0 = "V0"
    V1 = "V1"
    UNKNOWN = "UNKNOWN"


# Keep the solana cost error code contract and validation rules together.
class SolanaCostErrorCode(StrEnum):
    PROFILE_NOT_EFFECTIVE = "PROFILE_NOT_EFFECTIVE"
    UNSUPPORTED_FEE_FORMULA = "UNSUPPORTED_FEE_FORMULA"
    UNSUPPORTED_TRANSACTION_FORMAT = "UNSUPPORTED_TRANSACTION_FORMAT"
    UNKNOWN_ACCOUNT_SCHEMA = "UNKNOWN_ACCOUNT_SCHEMA"
    NON_REFUNDABLE_ACCOUNT_COST = "NON_REFUNDABLE_ACCOUNT_COST"
    # Declare arithmetic overflow explicitly in the solana cost error code contract.
    ARITHMETIC_OVERFLOW = "ARITHMETIC_OVERFLOW"


class SolanaCostError(ValueError):
    """Expected deterministic fee/account-cost rejection with a stable code."""

    def __init__(self, code: SolanaCostErrorCode) -> None:
        # Execute the solana cost error init workflow in explicit, reviewable steps.
        if not isinstance(code, SolanaCostErrorCode):
            raise TypeError("code must be a SolanaCostErrorCode")
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
# Keep the solana fee profile contract and validation rules together.
class SolanaFeeProfile:
    """Resolved legacy/v0 transaction fee inputs for one effective interval.

    ``charged_signature_count`` includes transaction signatures and any charged
    precompile signatures.  Priority fees use the requested CU limit, not the
    actual CUs consumed.  V1 transaction messages have different semantics and
    intentionally fail closed in this contract.
    """

    profile_id: str
    formula_version: str
    transaction_format: SolanaTransactionFormat
    effective_from_unix_s: int
    effective_until_unix_s: int
    # Declare charged signature count explicitly in the solana fee profile contract.
    charged_signature_count: int
    lamports_per_signature: int
    compute_unit_limit: int
    micro_lamports_per_compute_unit: int

    def __post_init__(self) -> None:
        # Execute the solana fee profile post init workflow in explicit, reviewable steps.
        _require_stable_name("profile_id", self.profile_id)
        _require_stable_name("formula_version", self.formula_version)
        if not isinstance(self.transaction_format, SolanaTransactionFormat):
            raise TypeError("transaction_format must be a SolanaTransactionFormat")
        _validate_effective_interval(
            # Pass self explicitly so _validate_effective_interval receives a reviewable
            # effective from unix s and effective until unix s input in solana fee profile
            # post init.
            self.effective_from_unix_s,
            self.effective_until_unix_s,
        )
        _require_u64("charged_signature_count", self.charged_signature_count, positive=True)
        _require_u64("lamports_per_signature", self.lamports_per_signature)
        # Invoke _require_u64 for compute unit limit as a visible solana fee profile post
        # init step.
        _require_u64("compute_unit_limit", self.compute_unit_limit)
        if self.compute_unit_limit > SOLANA_LEGACY_V0_MAX_COMPUTE_UNIT_LIMIT:
            raise ValueError("compute_unit_limit exceeds the legacy/v0 protocol maximum")
        _require_u64(
            "micro_lamports_per_compute_unit",
            # Pass self explicitly so _require_u64 receives a reviewable micro lamports
            # per compute unit input in solana fee profile post init.
            self.micro_lamports_per_compute_unit,
        )

    @classmethod
    def legacy_v0(
        cls,
        # Close the legacy v0 signature after its explicit inputs.
        *,
        profile_id: str,
        transaction_format: SolanaTransactionFormat,
        effective_from_unix_s: int,
        effective_until_unix_s: int,
        # Keep the charged signature count input explicit in the legacy v0 contract.
        charged_signature_count: int,
        lamports_per_signature: int,
        compute_unit_limit: int,
        micro_lamports_per_compute_unit: int,
    ) -> Self:
        # Execute the solana fee profile legacy v0 workflow in explicit, reviewable steps.
        return cls(
            profile_id=profile_id,
            formula_version=SOLANA_LEGACY_V0_FEE_FORMULA_V1,
            transaction_format=transaction_format,
            effective_from_unix_s=effective_from_unix_s,
            # Pass effective until unix s explicitly so cls receives a reviewable profile
            # id and solana legacy v0 fee formula v1 input in solana fee profile legacy
            # v0.
            effective_until_unix_s=effective_until_unix_s,
            charged_signature_count=charged_signature_count,
            lamports_per_signature=lamports_per_signature,
            compute_unit_limit=compute_unit_limit,
            micro_lamports_per_compute_unit=micro_lamports_per_compute_unit,
            # Complete cls only after its profile id and solana legacy v0 fee formula v1
            # inputs are visible in solana fee profile legacy v0.
        )


# Keep the solana transaction fee quote contract and validation rules together.
@dataclass(frozen=True, slots=True)
class SolanaTransactionFeeQuote:
    base_fee_lamports: int
    priority_fee_lamports: int
    total_fee_lamports: int
    # Declare charged on execution failure explicitly in the solana transaction fee quote
    # contract.
    charged_on_execution_failure: bool = True

    def __post_init__(self) -> None:
        # Execute the solana transaction fee quote post init workflow in explicit,
        # reviewable steps.
        _require_u64("base_fee_lamports", self.base_fee_lamports)
        _require_u64("priority_fee_lamports", self.priority_fee_lamports)
        _require_u64("total_fee_lamports", self.total_fee_lamports)
        if self.total_fee_lamports != self.base_fee_lamports + self.priority_fee_lamports:
            raise ValueError("total fee must equal base plus priority fee")
        # Evaluate the complete solana transaction fee quote post init charged on
        # execution failure condition before guarded effects.
        if self.charged_on_execution_failure is not True:
            raise ValueError("legacy/v0 transaction fee must be charged on execution failure")


@dataclass(frozen=True, slots=True, order=True)
class SolanaAccountDepositCost:
    """Refundable rent-exempt deposit for one versioned account schema."""

    account_schema_id: str
    deposit_lamports: int
    refundable: bool = True

    def __post_init__(self) -> None:
        # Execute the solana account deposit cost post init workflow in explicit,
        # reviewable steps.
        _require_stable_name("account_schema_id", self.account_schema_id)
        _require_u64("deposit_lamports", self.deposit_lamports)
        if not isinstance(self.refundable, bool):
            raise TypeError("refundable must be a boolean")


@dataclass(frozen=True, slots=True)
# Keep the solana account cost profile contract and validation rules together.
class SolanaAccountCostProfile:
    """Canonical account-schema to rent-deposit mapping for an effective cut."""

    profile_id: str
    effective_from_unix_s: int
    effective_until_unix_s: int
    costs: tuple[SolanaAccountDepositCost, ...]

    def __post_init__(self) -> None:
        # Execute the solana account cost profile post init workflow in explicit,
        # reviewable steps.
        _require_stable_name("profile_id", self.profile_id)
        _validate_effective_interval(
            self.effective_from_unix_s,
            self.effective_until_unix_s,
        )
        # Guard this path with not isinstance(self.costs, tuple) before applying effects.
        if not isinstance(self.costs, tuple):
            raise TypeError("costs must be a canonical tuple")
        if not all(isinstance(cost, SolanaAccountDepositCost) for cost in self.costs):
            raise TypeError("costs must contain SolanaAccountDepositCost values")
        schema_ids = tuple(cost.account_schema_id for cost in self.costs)
        # Evaluate the complete solana account cost profile post init schema ids and
        # sorted condition before guarded effects.
        if schema_ids != tuple(sorted(schema_ids)) or len(schema_ids) != len(set(schema_ids)):
            raise ValueError("account costs must be uniquely sorted by account_schema_id")


# Keep the solana account requirement contract and validation rules together.
@dataclass(frozen=True, slots=True, order=True)
class SolanaAccountRequirement:
    account_schema_id: str
    count: int = 1

    def __post_init__(self) -> None:
        # Execute the solana account requirement post init workflow in explicit,
        # reviewable steps.
        _require_stable_name("account_schema_id", self.account_schema_id)
        _require_u64("count", self.count, positive=True)


# Keep the solana account deposit quote contract and validation rules together.
@dataclass(frozen=True, slots=True)
class SolanaAccountDepositQuote:
    required_deposit_lamports: int
    refundable_deposit_lamports: int

    def __post_init__(self) -> None:
        # Execute the solana account deposit quote post init workflow in explicit,
        # reviewable steps.
        _require_u64("required_deposit_lamports", self.required_deposit_lamports)
        _require_u64("refundable_deposit_lamports", self.refundable_deposit_lamports)
        if self.refundable_deposit_lamports > self.required_deposit_lamports:
            raise ValueError("refundable deposit cannot exceed the required deposit")


def quote_transaction_fee(
    # Keep the profile input explicit in the quote transaction fee contract.
    profile: SolanaFeeProfile,
    *,
    effective_at_unix_s: int,
) -> SolanaTransactionFeeQuote:
    """Quote base plus ceil-rounded priority fee for legacy/v0 messages."""

    if not isinstance(profile, SolanaFeeProfile):
        raise TypeError("profile must be SolanaFeeProfile")
    _require_effective(
        profile.effective_from_unix_s,
        profile.effective_until_unix_s,
        # Pass effective at unix s explicitly so _require_effective receives a reviewable
        # effective from unix s and effective until unix s input in quote transaction fee.
        effective_at_unix_s,
    )
    if profile.formula_version != SOLANA_LEGACY_V0_FEE_FORMULA_V1:
        raise SolanaCostError(SolanaCostErrorCode.UNSUPPORTED_FEE_FORMULA)
    if profile.transaction_format not in (
        # Keep solana transaction format visible while evaluating the transaction format,
        # profile and legacy guard.
        SolanaTransactionFormat.LEGACY,
        SolanaTransactionFormat.V0,
    ):
        raise SolanaCostError(SolanaCostErrorCode.UNSUPPORTED_TRANSACTION_FORMAT)

    base_fee = _checked_mul_u64(
        # Pass profile explicitly so _checked_mul_u64 receives a reviewable charged
        # signature count and lamports per signature input in quote transaction fee.
        profile.charged_signature_count,
        profile.lamports_per_signature,
    )
    priority_numerator = _checked_mul_u128(
        profile.compute_unit_limit,
        # Pass profile explicitly so _checked_mul_u128 receives a reviewable compute unit
        # limit and micro lamports per compute unit input in quote transaction fee.
        profile.micro_lamports_per_compute_unit,
    )
    priority_fee = (
        priority_numerator + _MICRO_LAMPORTS_PER_LAMPORT - 1
    ) // _MICRO_LAMPORTS_PER_LAMPORT
    # Assemble total fee once so the quote transaction fee workflow shares one value.
    total_fee = _checked_add_u64(base_fee, priority_fee)
    return SolanaTransactionFeeQuote(
        base_fee_lamports=base_fee,
        priority_fee_lamports=priority_fee,
        total_fee_lamports=total_fee,
        # Complete SolanaTransactionFeeQuote only after its base fee and priority fee inputs
        # are visible in quote transaction fee.
    )


def quote_account_deposits(
    profile: SolanaAccountCostProfile,
    *,
    requirements: tuple[SolanaAccountRequirement, ...],
    # Keep the effective at unix s input explicit in the quote account deposits contract.
    effective_at_unix_s: int,
) -> SolanaAccountDepositQuote:
    """Resolve explicit account requirements without silently assuming rent."""

    if not isinstance(profile, SolanaAccountCostProfile):
        raise TypeError("profile must be SolanaAccountCostProfile")
    if not isinstance(requirements, tuple) or not all(
        isinstance(requirement, SolanaAccountRequirement) for requirement in requirements
    ):
        # Fail the quote account deposits path with TypeError for requirements must be a
        # tuple of solana account requirement when isinstance, requirements and
        # requirement is true; do not continue ambiguously.
        raise TypeError("requirements must be a tuple of SolanaAccountRequirement")
    _require_effective(
        profile.effective_from_unix_s,
        profile.effective_until_unix_s,
        effective_at_unix_s,
        # Complete _require_effective only after its effective from unix s and effective until
        # unix s inputs are visible in quote account deposits.
    )
    costs_by_schema = {cost.account_schema_id: cost for cost in profile.costs}
    required_total = 0
    refundable_total = 0
    for requirement in requirements:
        # Process requirements inside the bounded quote account deposits loop.
        cost = costs_by_schema.get(requirement.account_schema_id)
        if cost is None:
            raise SolanaCostError(SolanaCostErrorCode.UNKNOWN_ACCOUNT_SCHEMA)
        subtotal = _checked_mul_u64(cost.deposit_lamports, requirement.count)
        required_total = _checked_add_u64(required_total, subtotal)
        # Guard this path with cost.refundable before applying effects.
        if cost.refundable:
            refundable_total = _checked_add_u64(refundable_total, subtotal)
    return SolanaAccountDepositQuote(
        required_deposit_lamports=required_total,
        refundable_deposit_lamports=refundable_total,
        # Complete SolanaAccountDepositQuote only after its required total and refundable
        # total inputs are visible in quote account deposits.
    )


def price_account_requirements(
    profile: SolanaAccountCostProfile,
    *,
    requirements: tuple[AccountRequirement, ...],
    deposit_asset_id: AssetId,
    effective_at_unix_s: int,
) -> tuple[PricedAccountRequirement, ...]:
    """Attach exact Solana deposit prices while preserving protocol ownership."""

    if not isinstance(profile, SolanaAccountCostProfile):
        raise TypeError("profile must be SolanaAccountCostProfile")
    if not isinstance(requirements, tuple) or not all(
        isinstance(item, AccountRequirement) for item in requirements
    ):
        raise TypeError("requirements must be a tuple of AccountRequirement")
    if requirements != tuple(sorted(requirements, key=account_requirement_key)):
        raise ValueError("account requirements must be canonically sorted")

    # Every initial Pump account deposit is recoverable; lifecycle controls when.
    _require_effective(
        profile.effective_from_unix_s,
        profile.effective_until_unix_s,
        effective_at_unix_s,
    )
    costs = {item.account_schema_id: item for item in profile.costs}
    priced: list[PricedAccountRequirement] = []
    for requirement in requirements:
        cost = costs.get(requirement.requirement_schema_id)
        if cost is None:
            raise SolanaCostError(SolanaCostErrorCode.UNKNOWN_ACCOUNT_SCHEMA)
        if not cost.refundable:
            raise SolanaCostError(SolanaCostErrorCode.NON_REFUNDABLE_ACCOUNT_COST)
        priced.append(
            PricedAccountRequirement(requirement, deposit_asset_id, cost.deposit_lamports)
        )
    return tuple(sorted(priced, key=priced_account_requirement_key))


def _validate_effective_interval(start: int, end: int) -> None:
    # Execute the validate effective interval workflow in explicit, reviewable steps.
    _require_u64("effective_from_unix_s", start)
    _require_u64("effective_until_unix_s", end)
    if end <= start:
        raise ValueError("profile effective interval must be non-empty and half-open")


def _require_effective(start: int, end: int, effective_at_unix_s: int) -> None:
    # Execute the require effective workflow in explicit, reviewable steps.
    _require_u64("effective_at_unix_s", effective_at_unix_s)
    if not start <= effective_at_unix_s < end:
        raise SolanaCostError(SolanaCostErrorCode.PROFILE_NOT_EFFECTIVE)


def _checked_mul_u64(left: int, right: int) -> int:
    # Execute the checked mul u64 workflow in explicit, reviewable steps.
    result = left * right
    if result > _MAX_U64:
        raise SolanaCostError(SolanaCostErrorCode.ARITHMETIC_OVERFLOW)
    return result


def _checked_mul_u128(left: int, right: int) -> int:
    # Execute the checked mul u128 workflow in explicit, reviewable steps.
    result = left * right
    if result > _MAX_U128:
        raise SolanaCostError(SolanaCostErrorCode.ARITHMETIC_OVERFLOW)
    return result


def _checked_add_u64(left: int, right: int) -> int:
    # Execute the checked add u64 workflow in explicit, reviewable steps.
    result = left + right
    if result > _MAX_U64:
        raise SolanaCostError(SolanaCostErrorCode.ARITHMETIC_OVERFLOW)
    return result


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
    "SOLANA_LEGACY_V0_FEE_FORMULA_V1",
    "SOLANA_LEGACY_V0_MAX_COMPUTE_UNIT_LIMIT",
    "SolanaAccountCostProfile",
    # Keep the solana account deposit cost component named inside the all contract.
    "SolanaAccountDepositCost",
    "SolanaAccountDepositQuote",
    "SolanaAccountRequirement",
    "SolanaCostError",
    "SolanaCostErrorCode",
    # Keep the solana fee profile component named inside the all contract.
    "SolanaFeeProfile",
    "SolanaTransactionFeeQuote",
    "SolanaTransactionFormat",
    "price_account_requirements",
    "quote_account_deposits",
    "quote_transaction_fee",
    # Complete the all group only after its semantic components are visible.
]
