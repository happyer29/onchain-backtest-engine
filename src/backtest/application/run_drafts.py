"""Typed convenience input that must be resolved before queueing or execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from backtest.application.ml_contracts import ExactInferencePolicy, InferenceMode
from backtest.application.run_specs import AssetBalance

# Copy policy and public-key validation are pure domain semantics.
from backtest.domain.copytrading import CopyBuyPolicy, require_solana_wallet

# Import execution at the visible module dependency boundary.
from backtest.domain.execution import ExecutionMode
from backtest.domain.identifiers import (
    AccountId,
    AssetId,
    DatasetRevisionId,
    # Prepared dataset and optional replay identities remain separate typed inputs.
    DeliveryScheduleId,
    # Include feature set id so the identifiers dependency remains explicit.
    FeatureSetId,
    ModelScheduleId,
    PoolId,
    PredictionSetId,
    ReplayPackId,
    # Include snapshot id so the identifiers dependency remains explicit.
    SnapshotId,
)

PUMPFUN_SNIPING_RUN_DRAFT_SCHEMA = "pumpfun-sniping-run-draft/v3"
PUMPFUN_SNIPING_LEGACY_RUN_DRAFT_SCHEMA = "pumpfun-sniping-run-draft/v2"
PUMPFUN_SOLANA_WALLET_ACCOUNT_PROFILE_SCHEMA = "pumpfun-solana-wallet-account-profile/v2"

# Keep the supported Sniping mode set closed and canonically ordered for discovery.
PUMPFUN_SNIPING_EXECUTION_MODES = (
    ExecutionMode.EXOGENOUS_REPLAY,
    ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT,
)


# Keep the reference run draft contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ReferenceRunDraft:
    snapshot_id: SnapshotId
    replay_pack_id: ReplayPackId | None
    delivery_schedule_id: DeliveryScheduleId | None
    # Declare pool id explicitly in the reference run draft contract.
    pool_id: PoolId
    sold_asset_id: AssetId
    bought_asset_id: AssetId
    amount_in_atomic: int
    minimum_amount_out_atomic: int
    # Declare fee bps explicitly in the reference run draft contract.
    fee_bps: int
    execution_mode: ExecutionMode
    maximum_order_input_atomic: int
    observation_slots: int
    order_slots: int
    # Declare initial portfolio explicitly in the reference run draft contract.
    initial_portfolio: tuple[AssetBalance, ...]
    root_seed: int
    maximum_dynamic_items: int = 1_000_000
    feature_set_ids: tuple[FeatureSetId, ...] = ()
    model_schedule_id: ModelScheduleId | None = None
    # Declare prediction set ids explicitly in the reference run draft contract.
    prediction_set_ids: tuple[PredictionSetId, ...] = ()
    inference_policy: ExactInferencePolicy = field(default_factory=ExactInferencePolicy.disabled)

    def __post_init__(self) -> None:
        # Execute the reference run draft post init workflow in explicit, reviewable
        # steps.
        if self.delivery_schedule_id is not None and self.replay_pack_id is None:
            raise ValueError("DeliverySchedule requires a ReplayPack")
        for field_name in (
            "amount_in_atomic",
            "maximum_order_input_atomic",
            # Traverse amount in atomic, maximum order input atomic and maximum dynamic
            # items explicitly so each reference run draft post init iteration remains
            # traceable.
            "maximum_dynamic_items",
        ):
            # Process amount in atomic, maximum order input atomic and maximum dynamic
            # items inside the bounded reference run draft post init loop.
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        for field_name in (
            "minimum_amount_out_atomic",
            # Traverse minimum amount out atomic, fee bps and observation slots explicitly
            # so each reference run draft post init iteration remains traceable.
            "fee_bps",
            "observation_slots",
            "order_slots",
        ):
            # Process minimum amount out atomic, fee bps and observation slots inside the
            # bounded reference run draft post init loop.
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.fee_bps > 10_000:
            raise ValueError("fee_bps cannot exceed 10000")
        # Evaluate the complete reference run draft post init amount in atomic and maximum
        # order input atomic condition before guarded effects.
        if self.amount_in_atomic > self.maximum_order_input_atomic:
            raise ValueError("strategy amount exceeds the resolved risk limit")
        if not self.initial_portfolio:
            raise ValueError("initial portfolio must not be empty")
        if tuple(sorted(self.initial_portfolio, key=lambda item: item.asset_id.value)) != (
            # Keep self visible while evaluating the initial portfolio, sorted and asset
            # id guard.
            self.initial_portfolio
        ) or len({item.asset_id for item in self.initial_portfolio}) != len(self.initial_portfolio):
            raise ValueError("initial portfolio must be sorted and unique")
        for field_name in ("feature_set_ids", "prediction_set_ids"):
            # Process feature set ids and prediction set ids inside the bounded reference
            # run draft post init loop.
            values = getattr(self, field_name)
            if tuple(sorted(values, key=lambda item: item.hex)) != values or len(values) != len(
                set(values)
            ):
                raise ValueError(f"{field_name} must be sorted and unique")
        # Evaluate the complete reference run draft post init mode, disabled and inference
        # policy condition before guarded effects.
        if self.inference_policy.mode is InferenceMode.DISABLED:
            # Handle the reference run draft post init mode, disabled and inference policy
            # condition as a distinct block.
            if self.model_schedule_id is not None or self.prediction_set_ids:
                raise ValueError("disabled inference cannot declare models or predictions")
        # Handle the reference run draft post init complement of mode, disabled and
        # inference policy explicitly.
        elif self.inference_policy.mode is InferenceMode.FROZEN:
            # Handle the reference run draft post init mode, frozen and inference policy
            # condition as a distinct block.
            if (
                self.model_schedule_id is None
                or not self.feature_set_ids
                or not self.prediction_set_ids
            ):
                # Handle the reference run draft post init model schedule id, feature set
                # ids and prediction set ids condition as a distinct block.
                raise ValueError(
                    "frozen inference requires features, a ModelSchedule and PredictionSets"
                )
        # Handle the reference run draft post init complement of mode, frozen and
        # inference policy explicitly.
        elif self.inference_policy.mode is InferenceMode.EMBEDDED_BATCH:
            # Handle the reference run draft post init mode, embedded batch and inference
            # policy condition as a distinct block.
            if self.model_schedule_id is None or not self.feature_set_ids:
                raise ValueError("embedded inference requires features and a ModelSchedule")
            if self.prediction_set_ids:
                raise ValueError("embedded inference cannot declare frozen PredictionSets")
        else:  # pragma: no cover - ExactInferencePolicy rejects unsupported modes
            raise ValueError("unsupported run inference mode")
        if (
            isinstance(self.root_seed, bool)
            or not isinstance(self.root_seed, int)
            or not 0 <= self.root_seed < 1 << 256
            # Evaluate the complete reference run draft post init isinstance and root seed
            # condition before guarded effects.
        ):
            raise ValueError("root seed must be an unsigned 256-bit integer")


# Keep the wallet account mode contract and validation rules together.
class WalletAccountMode(StrEnum):
    FRESH = "fresh"
    PREWARMED = "prewarmed"


@dataclass(frozen=True, slots=True)
class SolanaAccountDepositCostDraft:
    """One exact schema price inside the effective-dated account profile."""

    requirement_schema_id: str
    deposit_lamports: int

    def __post_init__(self) -> None:
        # Account schema and amount are semantic inputs and cannot be inferred at runtime.
        _stable_text(self.requirement_schema_id, field_name="requirement_schema_id")
        _positive_integer(self.deposit_lamports, field_name="deposit_lamports")

    def document(self) -> dict[str, object]:
        """Return the canonical component price document."""

        return {
            "deposit_lamports": self.deposit_lamports,
            "requirement_schema_id": self.requirement_schema_id,
        }


# Keep the wallet account profile draft contract and validation rules together.
@dataclass(frozen=True, slots=True)
class WalletAccountProfileDraft:
    profile_id: str
    initial_uva_state: WalletAccountMode
    effective_from_unix_s: int
    effective_until_unix_s: int
    account_costs: tuple[SolanaAccountDepositCostDraft, ...]

    def __post_init__(self) -> None:
        """Require one exact effective profile containing the three v2 schemas."""

        _stable_text(self.profile_id, field_name="profile_id")
        if not isinstance(self.initial_uva_state, WalletAccountMode):
            raise TypeError("initial UVA state must be WalletAccountMode")
        _effective_interval(self.effective_from_unix_s, self.effective_until_unix_s)
        if not isinstance(self.account_costs, tuple) or not all(
            isinstance(item, SolanaAccountDepositCostDraft) for item in self.account_costs
        ):
            raise TypeError("account_costs must be a canonical component tuple")
        schema_ids = tuple(item.requirement_schema_id for item in self.account_costs)
        if len(schema_ids) != 3 or schema_ids != tuple(sorted(schema_ids)):
            raise ValueError("account profile requires three sorted schema prices")
        if len(schema_ids) != len(set(schema_ids)):
            raise ValueError("account profile schema prices must be unique")

    # Define wallet account profile draft document as one focused operation with an
    # explicit boundary.
    def document(self) -> dict[str, object]:
        # Version is embedded so legacy v1 objects cannot be silently reinterpreted.
        return {
            "account_costs": [item.document() for item in self.account_costs],
            "effective_from_unix_s": self.effective_from_unix_s,
            "effective_until_unix_s": self.effective_until_unix_s,
            "initial_uva_state": self.initial_uva_state.value,
            "profile_id": self.profile_id,
            "schema": PUMPFUN_SOLANA_WALLET_ACCOUNT_PROFILE_SCHEMA,
        }


# Keep the pump fee profile draft contract and validation rules together.
@dataclass(frozen=True, slots=True)
class PumpFeeProfileDraft:
    profile_id: str
    program_version: str
    buy_formula_version: str
    # Declare sell formula version explicitly in the pump fee profile draft contract.
    sell_formula_version: str
    effective_from_unix_s: int
    effective_until_unix_s: int
    protocol_fee_bps: int
    creator_fee_bps: int

    # Define pump fee profile draft post init as one focused operation with an explicit
    # boundary.
    def __post_init__(self) -> None:
        # Execute the pump fee profile draft post init workflow in explicit, reviewable
        # steps.
        for field_name in (
            "profile_id",
            "program_version",
            "buy_formula_version",
            "sell_formula_version",
            # Traverse profile id, program version and buy formula version explicitly so each
            # pump fee profile draft post init iteration remains traceable.
        ):
            _stable_text(getattr(self, field_name), field_name=field_name)
        _effective_interval(self.effective_from_unix_s, self.effective_until_unix_s)
        _basis_points(self.protocol_fee_bps, field_name="protocol_fee_bps")
        _basis_points(self.creator_fee_bps, field_name="creator_fee_bps")
        # Evaluate the complete pump fee profile draft post init protocol fee bps and
        # creator fee bps condition before guarded effects.
        if self.protocol_fee_bps + self.creator_fee_bps >= 10_000:
            raise ValueError("combined Pump fees must be below 10000 basis points")

    def document(self) -> dict[str, object]:
        # Execute the pump fee profile draft document workflow in explicit, reviewable
        # steps.
        return {
            "buy_formula_version": self.buy_formula_version,
            "creator_fee_bps": self.creator_fee_bps,
            "effective_from_unix_s": self.effective_from_unix_s,
            "effective_until_unix_s": self.effective_until_unix_s,
            # Include profile id in the completed pump fee profile draft document result.
            "profile_id": self.profile_id,
            "program_version": self.program_version,
            "protocol_fee_bps": self.protocol_fee_bps,
            "sell_formula_version": self.sell_formula_version,
        }


# Keep the solana fee profile draft contract and validation rules together.
@dataclass(frozen=True, slots=True)
class SolanaFeeProfileDraft:
    profile_id: str
    formula_version: str
    transaction_format: str
    # Declare effective from unix s explicitly in the solana fee profile draft contract.
    effective_from_unix_s: int
    effective_until_unix_s: int
    charged_signature_count: int
    lamports_per_signature: int
    compute_unit_limit: int
    # Declare micro lamports per compute unit explicitly in the solana fee profile draft
    # contract.
    micro_lamports_per_compute_unit: int

    def __post_init__(self) -> None:
        # Execute the solana fee profile draft post init workflow in explicit, reviewable
        # steps.
        for field_name in ("profile_id", "formula_version", "transaction_format"):
            _stable_text(getattr(self, field_name), field_name=field_name)
        _effective_interval(self.effective_from_unix_s, self.effective_until_unix_s)
        for field_name in (
            "charged_signature_count",
            # Traverse charged signature count, lamports per signature and compute unit
            # limit explicitly so each solana fee profile draft post init iteration
            # remains traceable.
            "lamports_per_signature",
            "compute_unit_limit",
        ):
            _positive_integer(getattr(self, field_name), field_name=field_name)
        _non_negative_integer(
            # Pass self explicitly so _non_negative_integer receives a reviewable micro
            # lamports per compute unit input in solana fee profile draft post init.
            self.micro_lamports_per_compute_unit,
            field_name="micro_lamports_per_compute_unit",
        )

    def document(self) -> dict[str, object]:
        # Execute the solana fee profile draft document workflow in explicit, reviewable
        # steps.
        return {
            "charged_signature_count": self.charged_signature_count,
            "compute_unit_limit": self.compute_unit_limit,
            "effective_from_unix_s": self.effective_from_unix_s,
            "effective_until_unix_s": self.effective_until_unix_s,
            # Include formula version in the completed solana fee profile draft document
            # result.
            "formula_version": self.formula_version,
            "lamports_per_signature": self.lamports_per_signature,
            "micro_lamports_per_compute_unit": self.micro_lamports_per_compute_unit,
            "profile_id": self.profile_id,
            "transaction_format": self.transaction_format,
            # Return the completed solana fee profile draft document result without a hidden
            # fallback.
        }


@dataclass(frozen=True, slots=True)
class PumpfunSnipingRunDraft:
    """Strict v3 input whose remaining fixed semantics are materialized by the resolver."""

    dataset_revision_id: DatasetRevisionId
    snapshot_id: SnapshotId
    replay_pack_id: ReplayPackId | None
    initial_sol_balance_lamports: int
    gross_buy_budget_lamports: int
    # Declare buy slippage bps explicitly in the pumpfun sniping run draft contract.
    buy_slippage_bps: int
    sell_slippage_bps: int
    # The mode is mandatory because v2's implicit default cannot be reinterpreted.
    execution_mode: ExecutionMode
    sell_delay_transactions: int
    wallet_account_profile: WalletAccountProfileDraft
    pump_fee_profile: PumpFeeProfileDraft
    # Declare buy solana fee profile explicitly in the pumpfun sniping run draft contract.
    buy_solana_fee_profile: SolanaFeeProfileDraft
    sell_solana_fee_profile: SolanaFeeProfileDraft
    root_seed: int
    delivery_schedule_id: DeliveryScheduleId | None = None

    def __post_init__(self) -> None:
        # Execute the pumpfun sniping run draft post init workflow in explicit, reviewable
        # steps.
        if self.delivery_schedule_id is not None and self.replay_pack_id is None:
            raise ValueError("DeliverySchedule requires a ReplayPack")
        _non_negative_integer(
            self.initial_sol_balance_lamports,
            field_name="initial_sol_balance_lamports",
            # Complete _non_negative_integer only after its initial sol balance lamports
            # inputs are visible in pumpfun sniping run draft post init.
        )
        _positive_integer(
            self.gross_buy_budget_lamports,
            field_name="gross_buy_budget_lamports",
        )
        # Invoke _basis_points for buy slippage bps as a visible pumpfun sniping run draft
        # post init step.
        _basis_points(
            self.buy_slippage_bps,
            field_name="buy_slippage_bps",
            allow_full=True,
        )
        # Invoke _basis_points for sell slippage bps as a visible pumpfun sniping run
        # draft post init step.
        _basis_points(
            self.sell_slippage_bps,
            field_name="sell_slippage_bps",
            allow_full=True,
        )
        # Only the two reviewed exogenous Pump.fun settlement policies may execute.
        if (
            not isinstance(self.execution_mode, ExecutionMode)
            or self.execution_mode not in PUMPFUN_SNIPING_EXECUTION_MODES
        ):
            raise ValueError("execution_mode is unsupported for Pump.fun Sniping v3")
        # Invoke _positive_integer for sell delay transactions as a visible pumpfun
        # sniping run draft post init step.
        _positive_integer(
            self.sell_delay_transactions,
            field_name="sell_delay_transactions",
        )
        if not isinstance(self.wallet_account_profile, WalletAccountProfileDraft):
            # Fail the pumpfun sniping run draft post init path with TypeError for wallet
            # account profile has an invalid type when isinstance, wallet account profile
            # and wallet account profile draft is true; do not continue ambiguously.
            raise TypeError("wallet_account_profile has an invalid type")
        if not isinstance(self.pump_fee_profile, PumpFeeProfileDraft):
            raise TypeError("pump_fee_profile has an invalid type")
        if not isinstance(self.buy_solana_fee_profile, SolanaFeeProfileDraft):
            raise TypeError("buy_solana_fee_profile has an invalid type")
        # Evaluate the complete pumpfun sniping run draft post init isinstance, sell
        # solana fee profile and solana fee profile draft condition before guarded
        # effects.
        if not isinstance(self.sell_solana_fee_profile, SolanaFeeProfileDraft):
            raise TypeError("sell_solana_fee_profile has an invalid type")
        if (
            isinstance(self.root_seed, bool)
            or not isinstance(self.root_seed, int)
            # Keep self visible while evaluating the isinstance and root seed guard.
            or not 0 <= self.root_seed < 1 << 256
        ):
            raise ValueError("root seed must be an unsigned 256-bit integer")

    @property
    def contract_schema(self) -> str:
        # Return the completed pumpfun sniping run draft contract schema result without a
        # hidden fallback.
        return PUMPFUN_SNIPING_RUN_DRAFT_SCHEMA


@dataclass(frozen=True, slots=True)
class PumpfunCopyBuyRunDraft:
    """Explicit copy-only inputs; existing Sniping draft versions retain their meaning."""

    dataset_revision_id: DatasetRevisionId
    snapshot_id: SnapshotId
    replay_pack_id: ReplayPackId | None
    signing_wallets: tuple[AccountId, ...]
    initial_sol_balance_lamports: int
    # Price thresholds and independent latency are one immutable policy contract.
    policy: CopyBuyPolicy
    execution_mode: ExecutionMode
    wallet_account_profile: WalletAccountProfileDraft
    pump_fee_profile: PumpFeeProfileDraft
    buy_solana_fee_profile: SolanaFeeProfileDraft
    # Fees and root seed remain explicit even when a trial uses deterministic defaults.
    sell_solana_fee_profile: SolanaFeeProfileDraft
    root_seed: int

    def __post_init__(self) -> None:
        """Validate canonical signer identities before any executable component exists."""
        if not isinstance(self.signing_wallets, tuple) or not 1 <= len(self.signing_wallets) <= 128:
            raise ValueError("copy draft requires one to 128 canonical signing wallets")
        for wallet in self.signing_wallets:
            require_solana_wallet(wallet)
        # Reordering or duplicating wallets must not create another interpretation of the list.
        if self.signing_wallets != tuple(
            sorted(set(self.signing_wallets), key=lambda item: item.value)
        ):
            raise ValueError("copy signing wallets must be sorted and unique")
        # The initial SOL budget may be zero and must still consume failed entry signals.
        _non_negative_integer(
            self.initial_sol_balance_lamports, field_name="initial_sol_balance_lamports"
        )
        # The copy policy object carries its fixed retry and price-trigger contract.
        if not isinstance(self.policy, CopyBuyPolicy):
            raise TypeError("copy draft requires CopyBuyPolicy")
        # The two existing exogenous modes retain their shared fee/account funding semantics.
        if (
            not isinstance(self.execution_mode, ExecutionMode)
            or self.execution_mode not in PUMPFUN_SNIPING_EXECUTION_MODES
        ):
            raise ValueError("copy draft has an unsupported execution mode")
        # Every executable draft retains explicit typed financial profiles.
        profiles = (
            (self.wallet_account_profile, WalletAccountProfileDraft),
            (self.pump_fee_profile, PumpFeeProfileDraft),
            # Effective dates and exact formula versions are validated by their typed profiles.
            (self.buy_solana_fee_profile, SolanaFeeProfileDraft),
            (self.sell_solana_fee_profile, SolanaFeeProfileDraft),
        )
        if any(not isinstance(value, expected) for value, expected in profiles):
            raise TypeError("copy draft contains an invalid financial profile")
        # The canonical seed is validated even when no future trade will occur.
        _non_negative_integer(self.root_seed, field_name="root_seed")
        # Keyed RNG identity is bounded consistently with the generic ResolvedRunSpec.
        if self.root_seed >= 1 << 256:
            raise ValueError("copy root seed must fit unsigned 256 bits")

    @property
    def contract_schema(self) -> str:
        """No old draft can silently acquire the copy strategy's source/exit semantics."""
        return "pumpfun-copy-buy-run-draft/v1"


# The shared CLI/API application boundary admits the separate copy draft explicitly.
RunDraft = ReferenceRunDraft | PumpfunSnipingRunDraft | PumpfunCopyBuyRunDraft


def _stable_text(value: object, *, field_name: str) -> str:
    # Execute the stable text workflow in explicit, reviewable steps.
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise ValueError(f"{field_name} must be a non-empty trimmed NUL-free string")
    return value


def _positive_integer(value: object, *, field_name: str) -> int:
    # Execute the positive integer workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _non_negative_integer(value: object, *, field_name: str) -> int:
    # Execute the non negative integer workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _basis_points(value: object, *, field_name: str, allow_full: bool = False) -> int:
    # Execute the basis points workflow in explicit, reviewable steps.
    maximum = 10_000 if allow_full else 9_999
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise ValueError(f"{field_name} must be an integer between 0 and {maximum}")
    return value


def _effective_interval(start: object, end: object) -> None:
    # Execute the effective interval workflow in explicit, reviewable steps.
    _non_negative_integer(start, field_name="effective_from_unix_s")
    _positive_integer(end, field_name="effective_until_unix_s")
    if not isinstance(start, int) or not isinstance(end, int) or end <= start:
        raise ValueError("effective profile interval must be non-empty and half-open")


__all__ = [
    "PUMPFUN_SNIPING_EXECUTION_MODES",
    "PUMPFUN_SNIPING_LEGACY_RUN_DRAFT_SCHEMA",
    # Keep the pumpfun sniping run draft schema component named inside the all contract.
    "PUMPFUN_SNIPING_RUN_DRAFT_SCHEMA",
    "PUMPFUN_SOLANA_WALLET_ACCOUNT_PROFILE_SCHEMA",
    "PumpFeeProfileDraft",
    "PumpfunSnipingRunDraft",
    "ReferenceRunDraft",
    # Keep the draft union adjacent to its concrete transport-safe members.
    "RunDraft",
    "SolanaAccountDepositCostDraft",
    # Keep the solana fee profile draft component named inside the all contract.
    "SolanaFeeProfileDraft",
    "WalletAccountMode",
    "WalletAccountProfileDraft",
]
