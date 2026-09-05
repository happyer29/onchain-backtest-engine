# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import pytest

from backtest.application.run_contracts import (
    PUMPFUN_SNIPING_CONTRACT,
    QueryRunContracts,
    # Include run contract not found error so the run contracts dependency remains
    # explicit.
    RunContractNotFoundError,
)


def test_sniping_contract_discovers_editable_and_fixed_fields_separately() -> None:
    # Execute the test sniping contract discovers editable and fixed fields separately
    # workflow in explicit, reviewable steps.
    descriptor = QueryRunContracts().get("pumpfun-sniping-run-draft/v3")

    editable = {field.name for field in descriptor.editable_fields}
    fixed = dict(descriptor.fixed_semantics)
    assert descriptor is PUMPFUN_SNIPING_CONTRACT
    assert "buy_slippage_bps" in editable
    # Verify 'delivery_schedule_id' in editable before this scenario is accepted.
    assert "delivery_schedule_id" in editable
    assert "execution_mode" in editable
    assert "cooldown_seconds" not in editable
    # Discovery exposes the exact closed enum used to populate transport clients.
    mode_field = next(
        field for field in descriptor.editable_fields if field.name == "execution_mode"
    )
    assert mode_field.required is True
    assert mode_field.enum_values == (
        "EXOGENOUS_REPLAY",
        "EXOGENOUS_VIRTUAL_SETTLEMENT",
    )
    # Only latency, universe, quote asset, and sell-all remain immutable semantics.
    assert fixed == {
        "buy_delay_transactions": "500",
        "cooldown_seconds": "600",
        "quote_asset": "SOL",
        # The mode is deliberately absent because it is now editable and required.
        "sell_all": "true",
        "sell_decision_delay_seconds": "2",
        "universe_policy": (
            "successful-sol-paired-non-mayhem-pumpfun-launches-in-decision-range-v2"
        ),
    }


# Define test unknown run contract fails closed as one focused operation with an explicit
# boundary.
def test_unknown_run_contract_fails_closed() -> None:
    # Execute the test unknown run contract fails closed workflow in explicit, reviewable
    # steps.
    with pytest.raises(RunContractNotFoundError):
        QueryRunContracts().get("arbitrary-json/v1")
