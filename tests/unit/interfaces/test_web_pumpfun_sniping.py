"""React form metadata retains explicit typed inputs and immutable financial defaults.

Executable command/discovery/precision tests live in frontend/src/commands.test.ts.
"""

import json
from pathlib import Path


def test_all_existing_typed_workflows_have_unique_react_field_metadata() -> None:
    """No legacy form can disappear during migration without an explicit contract change."""
    root = Path(__file__).parents[3]
    forms = json.loads((root / "frontend/src/form-fields.json").read_text())
    assert set(forms) == {
        "inspect-form",
        "dataset-plan-form",
        "sniping-form",
        "backtest-form",
        # Every admitted ML lifecycle command remains a separate typed form.
        "ml-features-form",
        "ml-universe-form",
        "ml-labels-form",
        "ml-train-form",
        "ml-schedule-form",
        "ml-predict-form",
    }
    for fields in forms.values():
        assert len(fields) == len({field["name"] for field in fields})
        assert all(field["label"] and isinstance(field["default"], str) for field in fields)


def test_pump_form_keeps_account_profiles_and_network_fees_separate() -> None:
    """Decimal text metadata must not coerce atomic inputs through JS number controls."""
    root = Path(__file__).parents[3]
    fields = json.loads((root / "frontend/src/form-fields.json").read_text())["sniping-form"]
    by_name = {field["name"]: field for field in fields}
    required = {"initial_sol_balance_lamports", "gross_buy_budget_lamports", "uva_rent_lamports"}
    # Per-mint ATA deposits and separate network-fee sides preserve their original meaning.
    required |= {"legacy_ata_rent_lamports", "token_2022_ata_rent_lamports"}
    required |= {"buy_lamports_per_signature", "sell_lamports_per_signature"}
    assert all(by_name[name]["type"] == "text" for name in required)
    assert by_name["wallet_profile_id"]["default"] == "pumpfun-solana-wallet-v2"
    assert not {"cooldown_seconds", "sell_all"} & by_name.keys()
