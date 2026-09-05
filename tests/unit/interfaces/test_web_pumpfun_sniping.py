# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from pathlib import Path


def test_web_ui_uses_typed_sniping_contract_and_bigint_atomic_values() -> None:
    # Execute the test web ui uses typed sniping contract and bigint atomic values
    # workflow in explicit, reviewable steps.
    static = (
        Path(__file__).resolve().parents[3] / "src" / "backtest" / "interfaces" / "web" / "static"
    )
    markup = (static / "index.html").read_text(encoding="utf-8")
    script = (static / "app.js").read_text(encoding="utf-8")

    # Verify 'id="sniping-form"' in markup before this scenario is accepted.
    assert 'id="sniping-form"' in markup
    assert 'id="sniping-summary-cards"' in markup
    assert 'id="sniping-roundtrips-body"' in markup
    for heading in (
        "Buy quote",
        # Traverse cashback and mtm explicitly so each test web ui uses typed sniping
        # contract and bigint atomic values iteration remains traceable.
        "Sell quote",
        "Sell liquidity",
        "Account / rent",
        "Cashback",
        "Realized PnL",
        "Economic PnL",
        # Traverse cashback and mtm explicitly so each test web ui uses typed sniping
        # contract and bigint atomic values iteration remains traceable.
        "MTM",
    ):
        assert f"<th>{heading}</th>" in markup
    assert 'api("/api/v1/run-contracts")' in script
    assert "contract_schema: snipingContract.schema" in script
    assert 'item.schema === "pumpfun-sniping-run-draft/v3"' in script
    assert 'name="execution_mode"' in markup
    assert 'id="sniping-execution-warning"' in markup
    assert "синтетическая модель" in markup
    # The options come from discovery and the chosen value enters the typed draft.
    assert "configureSnipingExecutionModes(contract)" in script
    assert "for (const value of field.enum_values)" in script
    assert 'execution_mode: values.get("execution_mode")' in script
    assert 'snipingExecutionMode.addEventListener("change"' in script
    assert 'snipingExecutionMode.value !== "EXOGENOUS_VIRTUAL_SETTLEMENT"' in script
    # Verify the markup relationship before this scenario is accepted.
    assert 'name="delivery_schedule_id"' in markup
    assert 'delivery_schedule_id: optionalText(values, "delivery_schedule_id")' in script
    assert "BigInt(raw)" in script
    assert (
        "cooldown_seconds:"
        # Keep the script expectation tied to cooldown seconds:, split and script in this
        # scenario.
        not in script.split("function pumpfunSnipingDraft", 1)[1].split(
            "function runPhysicalSettings", 1
        )[0]
    )
    assert "/roundtrips?${params}" in script
    assert "/dashboard?limit=${SNIPING_PAGE_SIZE}" in script
    assert "validateSnipingPage(dashboard.roundtrips)" in script
    assert "snipingLoadGeneration" in script
    assert 'option value="target_time"' in markup
    # Verify the script relationship before this scenario is accepted.
    assert "snipingResultActionButton(run.run_artifact_id)" in script
    result_button = script.split("function snipingResultActionButton", 1)[1].split(
        "async function showArtifact", 1
    )[0]
    assert 'document.createElement("a")' in result_button
    assert "/sniping-results?run_artifact_id=${encodeURIComponent(runArtifactId)}" in result_button
    assert 'button.target = "_blank"' in result_button
    assert 'button.rel = "noopener noreferrer"' in result_button
    assert "await openSnipingResult(runArtifactId)" not in result_button
    summary_renderer = script.split("function renderSnipingSummary", 1)[1].split(
        "function atomicSum", 1
    )[0]
    assert '["Targets", summary.target_count]' in summary_renderer
    # Verify the summary renderer relationship before this scenario is accepted.
    assert '["Targets", summary.roundtrip_count]' not in summary_renderer
    for field in (
        "valuation_status",
        "unvalued_open_position_count",
        "valued_economic_pnl_subtotal_atomic",
        # Traverse valuation status, unvalued open position count and valued economic pnl
        # subtotal atomic explicitly so each test web ui uses typed sniping contract and
        # bigint atomic values iteration remains traceable.
        "economic_pnl_atomic",
        "protocol_fee_paid_atomic",
        "creator_fee_paid_atomic",
        "network_base_fee_paid_atomic",
        "network_priority_fee_paid_atomic",
        # Traverse valuation status, unvalued open position count and valued economic pnl
        # subtotal atomic explicitly so each test web ui uses typed sniping contract and
        # bigint atomic values iteration remains traceable.
        "account_deposit_paid_atomic",
        "account_deposit_refunded_atomic",
        "account_deposit_locked_atomic",
        "favorable_slippage_count",
        "adverse_slippage_count",
        # Traverse valuation status, unvalued open position count and valued economic pnl
        # subtotal atomic explicitly so each test web ui uses typed sniping contract and
        # bigint atomic values iteration remains traceable.
        "buy_slippage_failure_count",
        "sell_slippage_failure_count",
    ):
        assert f"summary.{field}" in summary_renderer
    assert "atomicText(summary.economic_pnl_atomic)" in summary_renderer
    # Verify '.filter(' not in summary_renderer before this scenario is accepted.
    assert ".filter(" not in summary_renderer
    roundtrip_renderer = script.split("function renderSnipingRoundtrips", 1)[1].split(
        "async function loadSnipingRoundtrips", 1
    )[0]
    assert "Number(" not in roundtrip_renderer
    # Verify the roundtrip renderer relationship before this scenario is accepted.
    assert "legQuoteLines(item.buy)" in roundtrip_renderer
    assert "legQuoteLines(item.sell)" in roundtrip_renderer
    assert "accountAndRentLines(item)" in roundtrip_renderer
    assert "sellLiquidityLines(item)" in roundtrip_renderer
    assert "settled_synthetic_funded_atomic" in script
    assert "cashback_receivable_atomic" in roundtrip_renderer
    assert "realized_cash_pnl_atomic" in roundtrip_renderer
    # Verify the economic pnl atomic and roundtrip renderer relationship before this
    # scenario is accepted.
    assert "economic_pnl_atomic" in roundtrip_renderer
    assert "mtm_status" in roundtrip_renderer
    assert "mtm_liquidation_value_atomic" in roundtrip_renderer
    assert "mtm_cash_pnl_atomic" in roundtrip_renderer

    leg_renderer = script.split("function legQuoteLines", 1)[1].split("function legFeeLines", 1)[0]
    # Verify 'leg.failure_code' in leg_renderer before this scenario is accepted.
    assert "leg.failure_code" in leg_renderer

    account_renderer = script.split("function accountAndRentLines", 1)[1].split(
        "function renderSnipingRoundtrips", 1
    )[0]
    assert "Number(" not in account_renderer
    # Verify the account profile id and account renderer relationship before this scenario
    # is accepted.
    assert "item.account_profile_id" in account_renderer
    assert "item.account_components" in account_renderer
    assert "component.requirement_schema_id" in account_renderer
    assert "component.maximum_reserved_atomic" in account_renderer
    assert "component.paid_atomic" in account_renderer
    assert "component.released_atomic" in account_renderer
    assert "component.refunded_atomic" in account_renderer
    assert "component.locked_delta_atomic" in account_renderer

    draft_builder = script.split("function pumpfunSnipingDraft", 1)[1].split(
        "function runPhysicalSettings", 1
    )[0]
    assert 'schema: "pumpfun-solana-wallet-account-profile/v2"' in draft_builder
    assert "initial_uva_state: values.get" in draft_builder
    assert "account_costs:" in draft_builder
    for field_name in (
        "uva_rent_lamports",
        "legacy_ata_rent_lamports",
        "token_2022_ata_rent_lamports",
    ):
        assert field_name in draft_builder
        assert f'name="{field_name}"' in markup
