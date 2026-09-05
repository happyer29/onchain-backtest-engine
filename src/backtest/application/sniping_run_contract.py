"""Canonical semantic configuration for the Pump.fun Sniping v3 draft."""

from __future__ import annotations

import json
from typing import Final, cast

from backtest.application.ml_contracts import ExactInferencePolicy
from backtest.application.run_drafts import (
    # Include pumpfun sniping run draft schema so the run drafts dependency remains
    # explicit.
    PUMPFUN_SNIPING_RUN_DRAFT_SCHEMA,
    PumpfunSnipingRunDraft,
)
from backtest.application.run_specs import ResolvedRunSpec
from backtest.domain.execution import ExecutionMode

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import AssetId
from backtest.engine.sniping_contracts import (
    REAL_RESERVE_CAPPED_LIQUIDITY_POLICY_ID,
    VIRTUAL_RESERVE_EXPLICIT_SHORTFALL_LIQUIDITY_POLICY_ID,
    liquidity_policy_id_for_execution_mode,
)

PUMPFUN_SNIPING_QUOTE_ASSET_ID: Final = AssetId("SOL")
PUMPFUN_SNIPING_COOLDOWN_SECONDS: Final = 600
PUMPFUN_SNIPING_BUY_DELAY_TRANSACTIONS: Final = 500
PUMPFUN_SNIPING_SELL_DECISION_DELAY_SECONDS: Final = 2
# Re-export the core-owned liquidity policy names for resolver wiring.
PUMPFUN_REAL_RESERVE_SETTLEMENT_POLICY_ID: Final = REAL_RESERVE_CAPPED_LIQUIDITY_POLICY_ID
PUMPFUN_VIRTUAL_SETTLEMENT_POLICY_ID: Final = VIRTUAL_RESERVE_EXPLICIT_SHORTFALL_LIQUIDITY_POLICY_ID
# Synthetic proceeds are either absent or explicitly reusable by the shared wallet.
PUMPFUN_NO_SYNTHETIC_PROCEEDS_POLICY_ID: Final = "no-synthetic-proceeds-v1"
PUMPFUN_SPENDABLE_SYNTHETIC_PROCEEDS_POLICY_ID: Final = "spendable-synthetic-proceeds-v1"
# Bind pumpfun sniping maximum dynamic items once as an explicit module-level contract.
PUMPFUN_SNIPING_MAXIMUM_DYNAMIC_ITEMS: Final = 1_000_000
# Bind the causal target-universe policy once so resolver and runtime identities cannot
# drift independently.
PUMPFUN_SNIPING_UNIVERSE_POLICY_ID: Final = (
    "successful-sol-paired-non-mayhem-pumpfun-launches-in-decision-range-v2"
)


def sniping_component_configs(
    draft: PumpfunSnipingRunDraft,
) -> dict[str, dict[str, object]]:
    """Materialize every editable and immutable semantic input exactly once."""

    if not isinstance(draft, PumpfunSnipingRunDraft):
        raise TypeError("draft must be PumpfunSnipingRunDraft")
    wallet = draft.wallet_account_profile.document()
    settlement_policy, synthetic_proceeds_policy = sniping_execution_policies(draft.execution_mode)
    # Every returned object is canonical semantic input to a resolved component.
    return {
        "clock": {
            # Include block time resolution in the completed sniping component configs
            # result.
            "block_time_resolution": "seconds-v1",
            "contract": "compact-global-transaction-clock-v1",
        },
        "engine": {
            "execution_mode": draft.execution_mode.value,
            # Include maximum dynamic items in the completed sniping component configs
            # result.
            "maximum_dynamic_items": PUMPFUN_SNIPING_MAXIMUM_DYNAMIC_ITEMS,
            "run_contract": PUMPFUN_SNIPING_RUN_DRAFT_SCHEMA,
        },
        "execution": {
            "fee_on_landed_failure": True,
            # Include historical curve impact in the completed sniping component configs
            # result.
            "historical_curve_impact": "none",
            "mode": draft.execution_mode.value,
            "sell_all": True,
            # Both policy IDs enter the component digest and therefore semantic identity.
            "sell_settlement_policy": settlement_policy,
            "synthetic_proceeds_policy": synthetic_proceeds_policy,
        },
        "inference": ExactInferencePolicy.disabled().document(),
        # Include latency in the completed sniping component configs result.
        "latency": {
            "buy_delay_transactions": PUMPFUN_SNIPING_BUY_DELAY_TRANSACTIONS,
            "sell_decision_delay_seconds": PUMPFUN_SNIPING_SELL_DECISION_DELAY_SECONDS,
            "sell_delay_transactions": draft.sell_delay_transactions,
        },
        # Include network:solana in the completed sniping component configs result.
        "network:solana": {
            "account_profile": wallet,
            "buy_fee_profile": draft.buy_solana_fee_profile.document(),
            "jito_tip_lamports": 0,
            "sell_fee_profile": draft.sell_solana_fee_profile.document(),
            # Return the completed sniping component configs result without a hidden fallback.
        },
        "protocol:pumpfun": {
            "fee_profile": draft.pump_fee_profile.document(),
            "venue": "bonding-curve",
        },
        # Include risk in the completed sniping component configs result.
        "risk": {
            "buy_reservation": "gross-plus-network-plus-component-deposits-v2",
            "sell_fee_reserved_at_target": False,
            "wallet_scope": "single-shared-wallet-v1",
        },
        # Include scheduler in the completed sniping component configs result.
        "scheduler": {
            "phase_table": "canonical-v1",
            "synthetic_boundary_merge": "historical-synthetic-two-way-merge-v1",
        },
        "strategy": {
            # Include buy slippage bps in the completed sniping component configs result.
            "buy_slippage_bps": draft.buy_slippage_bps,
            "contract": PUMPFUN_SNIPING_RUN_DRAFT_SCHEMA,
            "cooldown_seconds": PUMPFUN_SNIPING_COOLDOWN_SECONDS,
            "developer_identity": "immutable-create-event-creator-v1",
            # Strategy identity carries the same mode as engine and execution.
            "execution_mode": draft.execution_mode.value,
            "gross_buy_budget_atomic": draft.gross_buy_budget_lamports,
            # Include quote asset id in the completed sniping component configs result.
            "quote_asset_id": PUMPFUN_SNIPING_QUOTE_ASSET_ID.value,
            "sell_delay_transactions": draft.sell_delay_transactions,
            "sell_slippage_bps": draft.sell_slippage_bps,
        },
        "universe": {
            # Include decision targets in the completed sniping component configs result.
            "decision_targets": PUMPFUN_SNIPING_UNIVERSE_POLICY_ID,
            "settlement_tail_creates_targets": False,
        },
        "valuation:price_source": {
            "cashback": "separate-economic-receivable-v1",
            # Include open position in the completed sniping component configs result.
            "open_position": "net-pump-liquidation-plus-rent-return-v1",
            "post_migration": "stale-pre-migration-v1",
        },
    }


def sniping_execution_policies(mode: ExecutionMode) -> tuple[str, str]:
    """Resolve the exact sell funding contract for one admitted execution mode."""

    settlement_policy = liquidity_policy_id_for_execution_mode(mode)
    if mode is ExecutionMode.EXOGENOUS_REPLAY:
        return settlement_policy, PUMPFUN_NO_SYNTHETIC_PROCEEDS_POLICY_ID
    # Virtual settlement makes its synthetic funding and spendability explicit.
    if mode is ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT:
        return settlement_policy, PUMPFUN_SPENDABLE_SYNTHETIC_PROCEEDS_POLICY_ID
    raise ValueError("unsupported Pump.fun Sniping execution mode")


def is_pumpfun_sniping_spec(spec: ResolvedRunSpec) -> bool:
    """Recognize the closed contract without trusting a physical backend name."""

    strategy = next((item for item in spec.components if item.role == "strategy"), None)
    if strategy is None:
        return False
    try:
        document = cast(dict[str, object], json.loads(strategy.canonical_config))
    except (TypeError, ValueError):  # pragma: no cover - ResolvedComponent validates JSON
        return False
    return document.get("contract") == PUMPFUN_SNIPING_RUN_DRAFT_SCHEMA


__all__ = [
    "PUMPFUN_NO_SYNTHETIC_PROCEEDS_POLICY_ID",
    "PUMPFUN_REAL_RESERVE_SETTLEMENT_POLICY_ID",
    "PUMPFUN_SNIPING_BUY_DELAY_TRANSACTIONS",
    "PUMPFUN_SNIPING_COOLDOWN_SECONDS",
    # Keep the pumpfun sniping maximum dynamic items component named inside the all
    # contract.
    "PUMPFUN_SNIPING_MAXIMUM_DYNAMIC_ITEMS",
    "PUMPFUN_SNIPING_QUOTE_ASSET_ID",
    "PUMPFUN_SNIPING_SELL_DECISION_DELAY_SECONDS",
    "PUMPFUN_SNIPING_UNIVERSE_POLICY_ID",
    "PUMPFUN_SPENDABLE_SYNTHETIC_PROCEEDS_POLICY_ID",
    "PUMPFUN_VIRTUAL_SETTLEMENT_POLICY_ID",
    "is_pumpfun_sniping_spec",
    "sniping_component_configs",
    "sniping_execution_policies",
    # Complete the all group only after its semantic components are visible.
]
