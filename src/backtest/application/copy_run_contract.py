"""Materialized copy-only component configuration and exact preparation compatibility."""

import json
from dataclasses import fields
from typing import Any, cast

# Application owns serialization/compatibility; plugins only implement the declared contracts.
from backtest.application.copy_source import COPYBUY_UNIVERSE_POLICY_ID
from backtest.application.copy_source_contracts import require_copy_source_contract
from backtest.application.ml_contracts import ExactInferencePolicy
from backtest.application.models import CopyBuySettlementRequirement, DatasetSpec

# Account and fee profiles remain typed across configuration reconstruction.
from backtest.application.run_drafts import (
    PumpFeeProfileDraft,
    PumpfunCopyBuyRunDraft,
    # Profile codecs preserve the shared effective-dated fee/account contract.
    SolanaAccountDepositCostDraft,
    SolanaFeeProfileDraft,
    WalletAccountMode,
    WalletAccountProfileDraft,
    # Resolved component configs are read without importing concrete plugin implementations.
)
from backtest.application.run_specs import ResolvedRunSpec

# Shared exogenous funding and wallet costs retain their existing integer semantics.
from backtest.application.sniping_run_contract import (
    PUMPFUN_SNIPING_QUOTE_ASSET_ID,
    sniping_execution_policies,
)
from backtest.application.source_evidence import PumpfunCopyBuySourceEvidenceBinding

# Source coverage and integer policy are independent prerequisites for execution.
from backtest.domain.copytrading import CopyBuyPolicy
from backtest.domain.execution import ExecutionMode
from backtest.domain.identifiers import AccountId

# A new run family cannot inherit the identity of an older Sniping backend.
COPY_RUN_CONTRACT = "pumpfun-copy-buy-run-draft/v1"
COPY_BACKEND = "reference-pumpfun-copy-buy-v1"
COPY_MAXIMUM_POSITIONS = 100_000
COPY_MAXIMUM_EVENTS = 5_000_000
# Dynamic state has a hard admission ceiling rather than unbounded per-event allocations.
COPY_MAXIMUM_DYNAMIC_ITEMS = 400_000


def copy_draft_from_spec(spec: ResolvedRunSpec) -> PumpfunCopyBuyRunDraft:
    """Strictly reconstruct the one supported config family before creating runtime state."""
    if not is_copy_run_spec(spec):
        raise ValueError("resolved spec is not a copy-buy run")
    # Derived schedules and ML overlays need their own copy causality gate before admission.
    if (
        spec.delivery_schedule_id
        or spec.feature_set_ids
        or spec.model_schedule_id
        or spec.prediction_set_ids
        # Any unsupported input rejects the entire closure before runtime construction.
    ):
        raise ValueError(
            "copy reference v1 does not accept materialized schedules or inference inputs"
        )
    # A copy wallet starts with one explicit native quote balance; other assets need a new contract.
    if (
        len(spec.initial_portfolio) != 1
        or spec.initial_portfolio[0].asset_id != PUMPFUN_SNIPING_QUOTE_ASSET_ID
    ):
        raise ValueError("copy initial portfolio must contain only the explicit SOL balance")
    # The sole initial asset is verified before indexing its immutable amount.
    configs = {item.role: json.loads(item.canonical_config) for item in spec.components}
    try:
        strategy, network = configs["strategy"], configs["network:solana"]
        wallet = network["account_profile"]
        # Typed profile constructors verify amounts, dates, modes and schema sets.
        account = WalletAccountProfileDraft(
            profile_id=wallet["profile_id"],
            initial_uva_state=WalletAccountMode(wallet["initial_uva_state"]),
            effective_from_unix_s=wallet["effective_from_unix_s"],
            effective_until_unix_s=wallet["effective_until_unix_s"],
            # Per-schema deposits preserve legacy ATA, Token-2022 ATA and wallet UVA distinctions.
            account_costs=tuple(
                SolanaAccountDepositCostDraft(**value) for value in wallet["account_costs"]
            ),
        )
        # Reconstruction keeps the exact prepared inputs rather than resolving aliases again.
        draft = PumpfunCopyBuyRunDraft(
            spec.dataset_revision_id,
            spec.snapshot_id,
            spec.replay_input.replay_pack_id,
            # Signer spelling/order and all threshold operands are validated independently.
            tuple(AccountId(value) for value in strategy["signing_wallets"]),
            spec.initial_portfolio[0].amount_atomic,
            copy_policy_from_document(strategy["policy"]),
            ExecutionMode(strategy["execution_mode"]),
            account,
            # Protocol fees retain their own effective interval and integer math version.
            PumpFeeProfileDraft(**cast(Any, configs["protocol:pumpfun"]["fee_profile"])),
            # Buy and sell fee profiles may differ and therefore retain separate identities.
            SolanaFeeProfileDraft(**cast(Any, network["buy_fee_profile"])),
            SolanaFeeProfileDraft(**cast(Any, network["sell_fee_profile"])),
            spec.root_seed,
        )
    # Malformed nested fields collapse to one bounded application-level config error.
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("copy resolved config has invalid or missing operands") from error
    # Exact reconstruction rejects extra keys, altered fixed rules and divergent component modes.
    if copy_component_configs(draft) != configs:
        raise ValueError("copy resolved components differ from the canonical draft contract")
    return draft


def copy_component_configs(draft: PumpfunCopyBuyRunDraft) -> dict[str, dict[str, object]]:
    """Resolve every default/fixed policy into canonical component config identity."""
    settlement, proceeds = sniping_execution_policies(draft.execution_mode)
    policy = draft.policy
    return {
        "clock": {"contract": "solana-all-transactions-v1", "block_time_resolution": "seconds-v1"},
        # Replay uses one sequential reference process and bounded dynamic state.
        "engine": {"run_contract": COPY_RUN_CONTRACT, "execution_mode": draft.execution_mode.value},
        "execution": {
            "mode": draft.execution_mode.value,
            "sell_settlement_policy": settlement,
            "synthetic_proceeds_policy": proceeds,
            # Full exits preserve historical reference state and never recompute external trades.
            "sell_all": True,
            "historical_curve_impact": "none",
            "fee_on_landed_failure": "network-only",
        },
        # No inference artifact is implicitly added to an otherwise exact replay.
        "inference": ExactInferencePolicy.disabled().document(),
        # Observation and both order delays remain independent semantic operands.
        "latency": {
            "observation_delay_transactions": policy.observation_delay_transactions,
            "buy_delay_transactions": policy.buy_delay_transactions,
            "sell_delay_transactions": policy.sell_delay_transactions,
        },
        # Each side retains its own network cost profile and asset-tagged accounting.
        "network:solana": {
            "account_profile": draft.wallet_account_profile.document(),
            "buy_fee_profile": draft.buy_solana_fee_profile.document(),
            # No undeclared priority payment or Jito tip enters accounting.
            "sell_fee_profile": draft.sell_solana_fee_profile.document(),
            "jito_tip_lamports": 0,
        },
        # Copy requires the actor-bearing payload even when shared curve math is unchanged.
        "protocol:pumpfun": {
            "fee_profile": draft.pump_fee_profile.document(),
            "venue": "bonding-curve",
            "trade_payload": "pumpfun-copybuy-trade-payload-v1",
        },
        # A single wallet reserves every additional network and account cost before submission.
        "risk": {
            "buy_reservation": "gross-plus-network-plus-component-deposits-v2",
            "wallet_scope": "single-shared-wallet-v1",
        },
        # The canonical scheduler preserves whole transaction delivery and later execution.
        "scheduler": {
            "phase_table": "canonical-v1",
            "merge": "copy-historical-observed-dynamic-v1",
        },
        # Wallet selection and price policy enter the strategy component digest together.
        "strategy": {
            "contract": COPY_RUN_CONTRACT,
            "policy": policy.document(),
            "signing_wallets": [wallet.value for wallet in draft.signing_wallets],
            "execution_mode": draft.execution_mode.value,
            # Quote units cannot be inferred from the selected fee profile.
            "quote_asset_id": PUMPFUN_SNIPING_QUOTE_ASSET_ID.value,
        },
        # Known Mayhem has evidence counts only; the tail never creates new entry targets.
        "universe": {
            "decision_targets": COPYBUY_UNIVERSE_POLICY_ID,
            "settlement_tail_creates_targets": False,
        },
        # Open valuation remains separate from actually settled proceeds.
        "valuation:price_source": {
            "cashback": "separate-economic-receivable-v1",
            "open_position": "net-pump-liquidation-plus-rent-return-v1",
            "post_migration": "stale-pre-migration-v1",
            # A migration mark is qualified as stale and never triggers a forced exit.
        },
    }


def copy_policy_from_document(value: object) -> CopyBuyPolicy:
    """Reject omitted fixed rules and unknown keys instead of silently applying defaults."""
    if not isinstance(value, dict):
        raise ValueError("copy policy must be an object")
    document = cast(dict[str, object], value)
    names = tuple(field.name for field in fields(CopyBuyPolicy))
    # Constructor enforces exact integers and all threshold/latency bounds.
    if any(type(document.get(name)) is not int for name in names):
        raise ValueError("copy policy numeric operands must be explicit integers")
    policy = CopyBuyPolicy(**{name: cast(int, document[name]) for name in names})
    # Canonical round-trip equality also checks the fixed retry and mint-consumption rules.
    if policy.document() != document:
        raise ValueError("copy policy does not match the complete versioned contract")
    return policy


def is_copy_run_spec(spec: ResolvedRunSpec) -> bool:
    """Dispatch uses the immutable typed contract, never a backend alias or strategy name."""
    strategy = next((item for item in spec.components if item.role == "strategy"), None)
    if strategy is None:
        return False
    document = json.loads(strategy.canonical_config)
    # Only the exact schema dispatches to this runtime; display names carry no authority.
    return isinstance(document, dict) and document.get("contract") == COPY_RUN_CONTRACT


# Preparation compatibility is checked before the engine receives its local reader.
def require_copy_preparation(
    spec: DatasetSpec, wallets: tuple[AccountId, ...], policy: CopyBuyPolicy
) -> None:
    """The exact source evidence and full four-attempt tail must cover the resolved run."""
    require_copy_source_contract(spec)
    binding = spec.source_evidence_binding
    requirement = spec.settlement_requirement
    # Both source and settlement contracts must belong to the copy family.
    if not isinstance(binding, PumpfunCopyBuySourceEvidenceBinding) or not isinstance(
        requirement,
        CopyBuySettlementRequirement,
        # Old signerless or one-sale evidence cannot satisfy this source contract.
    ):
        raise ValueError("copy run has no exact preparation evidence")
    # The first implementation requires the exact prepared wallet set, never an expanded set.
    if wallets != binding.copy_coverage.selection.signing_wallets:
        raise ValueError("copy signing wallets differ from their prepared source coverage")
    # Every latency operand is bounded by the pre-publication full-settlement proof.
    for name in (
        "observation_delay_transactions",
        "buy_delay_transactions",
        "sell_delay_transactions",
        "maximum_hold_seconds",
        # A shorter run policy can reuse the proven tail; a longer one needs new preparation.
    ):
        if getattr(policy, name) > getattr(requirement, name):
            raise ValueError("copy run timing exceeds its prepared settlement requirement")
