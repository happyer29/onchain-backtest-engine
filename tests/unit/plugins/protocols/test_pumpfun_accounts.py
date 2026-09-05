"""Tests for the Pump-owned mode-to-account mapper."""

import pytest

from backtest.domain.account_requirements import AccountRequirementScope
from backtest.engine.sniping_contracts import ProtocolContractError
from backtest.plugins.protocols.pumpfun import (
    PUMPFUN_LEGACY_ATA_SCHEMA_ID,
    PUMPFUN_TOKEN_2022_ATA_SCHEMA_ID,
    PUMPFUN_UVA_SCHEMA_ID,
    PumpMode,
    pumpfun_account_requirements,
)


@pytest.mark.parametrize(
    ("mode", "expected_ata"),
    (
        (PumpMode.NORMAL, PUMPFUN_LEGACY_ATA_SCHEMA_ID),
        (PumpMode.TOKEN_2022, PUMPFUN_TOKEN_2022_ATA_SCHEMA_ID),
        (PumpMode.CASHBACK, PUMPFUN_TOKEN_2022_ATA_SCHEMA_ID),
    ),
)
def test_mode_selects_exact_mint_ata_and_shared_uva(
    mode: PumpMode,
    expected_ata: str,
) -> None:
    requirements = pumpfun_account_requirements(mode)

    # Every eligible mode produces one per-mint ATA plus the wallet-scoped UVA.
    assert tuple(item.scope for item in requirements) == (
        AccountRequirementScope.MINT,
        AccountRequirementScope.WALLET,
    )
    assert requirements[0].requirement_schema_id == expected_ata
    assert requirements[1].requirement_schema_id == PUMPFUN_UVA_SCHEMA_ID


@pytest.mark.parametrize("mode", (PumpMode.MAYHEM, PumpMode.UNKNOWN))
def test_unsupported_modes_fail_closed_before_pricing(mode: PumpMode) -> None:
    # Mayhem should have been excluded; unknown mode cannot select an ATA safely.
    with pytest.raises(ProtocolContractError):
        pumpfun_account_requirements(mode)
