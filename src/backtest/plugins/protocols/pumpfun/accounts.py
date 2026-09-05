"""Pump-owned mapping from token mode to generic account requirements."""

from __future__ import annotations

from typing import Final

from backtest.domain.account_requirements import (
    AccountReleasePolicy,
    AccountRequirement,
    AccountRequirementScope,
    account_requirement_key,
)
from backtest.engine.sniping_contracts import (
    ProtocolContractError,
    ProtocolContractErrorCode,
)
from backtest.plugins.protocols.pumpfun.model import PumpMode

PUMPFUN_LEGACY_ATA_SCHEMA_ID: Final = "solana-associated-token-account-legacy-v1"
PUMPFUN_TOKEN_2022_ATA_SCHEMA_ID: Final = (
    "solana-associated-token-account-token-2022-immutable-owner-v1"
)
PUMPFUN_UVA_SCHEMA_ID: Final = "pumpfun-user-volume-accumulator-v1"


def pumpfun_account_requirements(mode: PumpMode) -> tuple[AccountRequirement, ...]:
    """Return one mode-specific mint ATA and the one wallet-scoped UVA."""

    if mode is PumpMode.NORMAL:
        ata_schema = PUMPFUN_LEGACY_ATA_SCHEMA_ID
    elif mode in {PumpMode.TOKEN_2022, PumpMode.CASHBACK}:
        # Cashback changes fee routing, not the Token-2022 account schema.
        ata_schema = PUMPFUN_TOKEN_2022_ATA_SCHEMA_ID
    else:
        # Mayhem is excluded before execution; unknown modes always remain fail-closed.
        code = (
            ProtocolContractErrorCode.EXCLUDED_PROGRAM_MODE
            if mode is PumpMode.MAYHEM
            else ProtocolContractErrorCode.UNKNOWN_PROGRAM_MODE
        )
        raise ProtocolContractError(code)

    requirements = (
        AccountRequirement(
            ata_schema,
            AccountRequirementScope.MINT,
            AccountReleasePolicy.CLOSE_ON_SUCCESSFUL_SELL,
        ),
        AccountRequirement(
            PUMPFUN_UVA_SCHEMA_ID,
            AccountRequirementScope.WALLET,
            AccountReleasePolicy.RUN_LOCKED,
        ),
    )
    return tuple(sorted(requirements, key=account_requirement_key))


__all__ = [
    "PUMPFUN_LEGACY_ATA_SCHEMA_ID",
    "PUMPFUN_TOKEN_2022_ATA_SCHEMA_ID",
    "PUMPFUN_UVA_SCHEMA_ID",
    "pumpfun_account_requirements",
]
