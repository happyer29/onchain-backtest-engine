"""Copy discovery and typed transport preserve the independent approved strategy rules."""

import json

import pytest
import test_pumpfun_run_schema as sniping
from pydantic import ValidationError

# Reuse only financial profile inputs; copy timing and signer selection stay explicit.
from backtest.application.run_contracts import QueryRunContracts
from backtest.interfaces.api.schemas import run_draft_command_from_bytes


def copy_document():
    """Build a complete transport draft without inheriting a Sniping delivery schedule."""
    document = sniping._document()
    document.pop("delivery_schedule_id", None)
    document.update(contract_schema="pumpfun-copy-buy-run-draft/v1")
    document.update(signing_wallets=["11111111111111111111111111111111"])
    # Own exits compare prices without fees; all three delays are independent inputs.
    document.update(take_profit_bps=2000, stop_loss_bps=1000, maximum_hold_seconds=60)
    document.update(observation_delay_transactions=0, buy_delay_transactions=5)
    return document


def test_copy_discovery_matches_complete_typed_draft() -> None:
    """Clients can discover every required field without guessing hidden defaults."""
    descriptor = QueryRunContracts().get("pumpfun-copy-buy-run-draft/v1")
    command = run_draft_command_from_bytes(json.dumps(copy_document()).encode())
    editable = {field.name for field in descriptor.editable_fields}
    assert editable == set(type(command).model_fields) - {"contract_schema"}
    # New contracts must not alter the existing Sniping discovery or fixed semantics.
    assert "cooldown_seconds" not in dict(descriptor.fixed_semantics)
    assert dict(descriptor.fixed_semantics)["maximum_sell_attempts"] == "4"
    assert command.to_domain().policy.maximum_hold_seconds == 60
    assert command.to_domain().policy.observation_delay_transactions == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("signing_wallets", []),
        ("signing_wallets", ["not-a-solana-address"]),
        # Buy latency and price thresholds reject zero just as malformed wallet lists reject entry.
        ("buy_delay_transactions", 0),
        ("stop_loss_bps", 0),
        # Missing semantic values never become permissive execution defaults.
        ("maximum_hold_seconds", None),
        ("execution_mode", "UNKNOWN"),
    ],
)
def test_copy_draft_rejects_incomplete_or_unsupported_policy(field, value) -> None:
    """Reject before resolution, input reads or any engine mutation."""
    document = {**copy_document(), field: value}
    with pytest.raises((ValidationError, ValueError)):
        run_draft_command_from_bytes(json.dumps(document).encode()).to_domain()
