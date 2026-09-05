"""Composition-owned exact runtime resolver for Pump.fun Sniping v3."""

from __future__ import annotations

import json
from typing import Any, cast

from backtest.application.code_bundles import CodeBundleIntegrityError
from backtest.application.ml_contracts import InferenceMode

# Import runs at the visible module dependency boundary.
from backtest.application.ports.runs import RuntimeComponentReceipt
from backtest.application.ports.sniping_runs import ResolvedSnipingRuntimeComponents
from backtest.application.run_drafts import (
    PUMPFUN_SNIPING_EXECUTION_MODES,
    PUMPFUN_SNIPING_RUN_DRAFT_SCHEMA,
    PUMPFUN_SOLANA_WALLET_ACCOUNT_PROFILE_SCHEMA,
)
from backtest.application.run_specs import ResolvedComponent, ResolvedRunSpec
from backtest.application.sniping_run_contract import (
    # Include pumpfun sniping buy delay transactions so the sniping run contract
    # dependency remains explicit.
    PUMPFUN_SNIPING_BUY_DELAY_TRANSACTIONS,
    PUMPFUN_SNIPING_COOLDOWN_SECONDS,
    PUMPFUN_SNIPING_QUOTE_ASSET_ID,
    PUMPFUN_SNIPING_SELL_DECISION_DELAY_SECONDS,
    PUMPFUN_SNIPING_UNIVERSE_POLICY_ID,
    is_pumpfun_sniping_spec,
    sniping_execution_policies,
    # Close the sniping run contract import after its required symbols are visible.
)
from backtest.bootstrap.reference_bundles import (
    PumpfunSnipingBundleRegistry,
    ReferenceBundleIntegrityError,
)

# Import execution at the visible module dependency boundary.
from backtest.domain.execution import ExecutionMode
from backtest.domain.identifiers import RuntimeLockId
from backtest.engine.wallet_accounts import WalletUvaInitialState
from backtest.plugins.networks.solana import (
    SolanaAccountCostProfile,
    # Include solana account deposit cost so the solana dependency remains explicit.
    SolanaAccountDepositCost,
    SolanaFeeProfile,
    SolanaSnipingCostModel,
    SolanaTransactionFormat,
)

# Import pumpfun at the visible module dependency boundary.
from backtest.plugins.protocols.pumpfun import (
    PUMPFUN_LEGACY_ATA_SCHEMA_ID,
    PUMPFUN_TOKEN_2022_ATA_SCHEMA_ID,
    PUMPFUN_UVA_SCHEMA_ID,
    PumpFeeProfile,
    PumpfunSnipingProtocolRuntime,
)
from backtest.plugins.strategies import PumpfunSnipingStrategy


class SnipingRuntimeResolutionError(RuntimeError):
    """A resolved sniping closure cannot be instantiated exactly."""


class PumpfunSnipingRuntimeComponentsResolver:
    def __init__(
        self,
        expected_runtime_lock_id: RuntimeLockId,
        bundle_registry: PumpfunSnipingBundleRegistry | None = None,
        # Close the init signature after its explicit inputs.
    ) -> None:
        # Execute the pumpfun sniping runtime components resolver init workflow in
        # explicit, reviewable steps.
        self._runtime_lock_id = expected_runtime_lock_id
        self._bundle_registry = bundle_registry or PumpfunSnipingBundleRegistry()

    def resolve(self, spec: ResolvedRunSpec) -> ResolvedSnipingRuntimeComponents:
        # Execute the pumpfun sniping runtime components resolver resolve workflow in
        # explicit, reviewable steps.
        if not is_pumpfun_sniping_spec(spec):
            raise SnipingRuntimeResolutionError("resolved spec is not Pump.fun Sniping v3")
        if spec.runtime_lock_id != self._runtime_lock_id:
            raise SnipingRuntimeResolutionError("resolved runtime lock differs from this process")
        try:
            # Perform the protected pumpfun sniping runtime components resolver resolve
            # operation before explicit failure handling.
            closure = self._bundle_registry.snapshot()
            closure.require_components(spec.components, spec.dependency_merkle_root)
        except (CodeBundleIntegrityError, ReferenceBundleIntegrityError) as error:
            # Translate the code bundle integrity error and reference bundle integrity
            # error failure through the pumpfun sniping runtime components resolver
            # resolve boundary.
            raise SnipingRuntimeResolutionError(
                "resolved bundle closure differs from installed exact source bytes"
            ) from error
        if (
            spec.inference_policy().mode is not InferenceMode.DISABLED
            # Keep spec visible while evaluating the feature set ids, prediction set ids
            # and mode guard.
            or spec.feature_set_ids
            or spec.model_schedule_id is not None
            or spec.prediction_set_ids
        ):
            raise SnipingRuntimeResolutionError("sniping v3 does not accept inference overlays")

        # Assemble clock once so the pumpfun sniping runtime components resolver resolve
        # workflow shares one value.
        clock = _config(
            _component(spec, "clock"),
            {"block_time_resolution", "contract"},
        )
        engine = _config(
            # Keep the spec _component step visible while building engine.
            _component(spec, "engine"),
            {"execution_mode", "maximum_dynamic_items", "run_contract"},
        )
        execution = _config(
            _component(spec, "execution"),
            # Open the execution and fee on landed failure payload explicitly for _config
            # within pumpfun sniping runtime components resolver resolve.
            {
                "fee_on_landed_failure",
                "historical_curve_impact",
                "mode",
                "sell_all",
                # Settlement funding is identity-bearing and cannot be inferred from mode.
                "sell_settlement_policy",
                "synthetic_proceeds_policy",
            },
        )
        latency = _config(
            _component(spec, "latency"),
            {
                # Pass buy delay transactions explicitly so _config receives a reviewable
                # latency and buy delay transactions input in pumpfun sniping runtime
                # components resolver resolve.
                "buy_delay_transactions",
                "sell_decision_delay_seconds",
                "sell_delay_transactions",
            },
        )
        # Assemble network once so the pumpfun sniping runtime components resolver resolve
        # workflow shares one value.
        network = _config(
            _component(spec, "network:solana"),
            {"account_profile", "buy_fee_profile", "jito_tip_lamports", "sell_fee_profile"},
        )
        protocol = _config(
            # Keep the spec _component step visible while building protocol.
            _component(spec, "protocol:pumpfun"),
            {"fee_profile", "venue"},
        )
        risk = _config(
            _component(spec, "risk"),
            # Open the risk and buy reservation payload explicitly for _config within
            # pumpfun sniping runtime components resolver resolve.
            {"buy_reservation", "sell_fee_reserved_at_target", "wallet_scope"},
        )
        scheduler = _config(
            _component(spec, "scheduler"),
            {"phase_table", "synthetic_boundary_merge"},
            # Complete _config only after its scheduler and phase table inputs are visible in
            # pumpfun sniping runtime components resolver resolve.
        )
        strategy = _config(
            _component(spec, "strategy"),
            {
                "buy_slippage_bps",
                # Pass contract explicitly so _config receives a reviewable strategy and
                # buy slippage bps input in pumpfun sniping runtime components resolver
                # resolve.
                "contract",
                "cooldown_seconds",
                "developer_identity",
                "execution_mode",
                "gross_buy_budget_atomic",
                "quote_asset_id",
                # Pass sell delay transactions explicitly so _config receives a reviewable
                # strategy and buy slippage bps input in pumpfun sniping runtime
                # components resolver resolve.
                "sell_delay_transactions",
                "sell_slippage_bps",
            },
        )
        universe = _config(
            # Keep the spec _component step visible while building universe.
            _component(spec, "universe"),
            {"decision_targets", "settlement_tail_creates_targets"},
        )
        valuation = _config(
            _component(spec, "valuation:price_source"),
            # Open the valuation:price source and cashback payload explicitly for _config
            # within pumpfun sniping runtime components resolver resolve.
            {"cashback", "open_position", "post_migration"},
        )
        _require_fixed_configs(
            clock=clock,
            engine=engine,
            # Pass execution explicitly so _require_fixed_configs receives a reviewable
            # clock and engine input in pumpfun sniping runtime components resolver
            # resolve.
            execution=execution,
            latency=latency,
            network=network,
            protocol=protocol,
            risk=risk,
            # Pass scheduler explicitly so _require_fixed_configs receives a reviewable
            # clock and engine input in pumpfun sniping runtime components resolver
            # resolve.
            scheduler=scheduler,
            strategy=strategy,
            universe=universe,
            valuation=valuation,
        )

        # Assemble strategy component once so the pumpfun sniping runtime components
        # resolver resolve workflow shares one value.
        strategy_component = _component(spec, "strategy")
        execution_mode = _sniping_execution_mode(engine)
        protocol_component = _component(spec, "protocol:pumpfun")
        network_component = _component(spec, "network:solana")
        # Decode the nested effective profiles only after fixed policy verification.
        account_profile = _object(network, "account_profile")
        initial_uva_state, account_cost_profile = _wallet_account_profile(account_profile)
        pump_fee = _pump_fee_profile(_object(protocol, "fee_profile"))
        buy_fee = _solana_fee_profile(_object(network, "buy_fee_profile"))
        # Assemble sell fee once so the pumpfun sniping runtime components resolver
        # resolve workflow shares one value.
        sell_fee = _solana_fee_profile(_object(network, "sell_fee_profile"))
        return ResolvedSnipingRuntimeComponents(
            strategy=PumpfunSnipingStrategy(
                # Pass quote asset id explicitly so PumpfunSnipingStrategy receives a
                # reviewable gross buy budget atomic and buy slippage bps input in pumpfun
                # sniping runtime components resolver resolve.
                quote_asset_id=PUMPFUN_SNIPING_QUOTE_ASSET_ID,
                gross_buy_budget_atomic=_integer(
                    strategy,
                    "gross_buy_budget_atomic",
                    minimum=1,
                    # Complete _integer only after its gross buy budget atomic and strategy
                    # inputs are visible in pumpfun sniping runtime components resolver
                    # resolve.
                ),
                buy_slippage_bps=_integer(strategy, "buy_slippage_bps", minimum=0),
                sell_slippage_bps=_integer(strategy, "sell_slippage_bps", minimum=0),
                sell_delay_transactions=_integer(
                    strategy,
                    # Pass sell delay transactions explicitly so _integer receives a
                    # reviewable sell delay transactions and strategy input in pumpfun
                    # sniping runtime components resolver resolve.
                    "sell_delay_transactions",
                    minimum=1,
                ),
                execution_mode=execution_mode,
                # The exact installed strategy bundle remains independently verified.
                bundle_id=strategy_component.bundle_id,
            ),
            # Include protocol in the completed pumpfun sniping runtime components
            # resolver resolve result.
            protocol=PumpfunSnipingProtocolRuntime(
                quote_asset_id=PUMPFUN_SNIPING_QUOTE_ASSET_ID,
                fee_profile=pump_fee,
                protocol_version=pump_fee.program_version,
                bundle_id=protocol_component.bundle_id,
                # Complete PumpfunSnipingProtocolRuntime only after its program version and
                # bundle id inputs are visible in pumpfun sniping runtime components resolver
                # resolve.
            ),
            network_costs=SolanaSnipingCostModel(
                buy_fee_profile=buy_fee,
                sell_fee_profile=sell_fee,
                account_cost_profile=account_cost_profile,
                # Network formula code is pinned separately from semantic fee profiles.
                bundle_id=network_component.bundle_id,
            ),
            initial_uva_state=initial_uva_state,
            wallet_account_profile_id=_string(account_profile, "profile_id"),
            uva_schema_id=PUMPFUN_UVA_SCHEMA_ID,
            maximum_dynamic_items=_integer(
                engine,
                "maximum_dynamic_items",
                minimum=1,
                # Complete _integer only after its maximum dynamic items and engine inputs are
                # visible in pumpfun sniping runtime components resolver resolve.
            ),
            receipts=tuple(_receipt(component) for component in spec.components),
        )


def _require_fixed_configs(
    *,
    # Keep the clock input explicit in the require fixed configs contract.
    clock: dict[str, object],
    engine: dict[str, object],
    execution: dict[str, object],
    latency: dict[str, object],
    network: dict[str, object],
    # Keep the protocol input explicit in the require fixed configs contract.
    protocol: dict[str, object],
    risk: dict[str, object],
    scheduler: dict[str, object],
    strategy: dict[str, object],
    universe: dict[str, object],
    # Keep the valuation input explicit in the require fixed configs contract.
    valuation: dict[str, object],
) -> None:
    # Execute the require fixed configs workflow in explicit, reviewable steps.
    if clock != {
        "block_time_resolution": "seconds-v1",
        "contract": "compact-global-transaction-clock-v1",
    }:
        raise SnipingRuntimeResolutionError("clock config is unsupported")
    # Decode the closed mode before comparing its redundant component declarations.
    execution_mode = _sniping_execution_mode(engine)
    if _string(engine, "run_contract") != PUMPFUN_SNIPING_RUN_DRAFT_SCHEMA:
        raise SnipingRuntimeResolutionError("engine config is unsupported")
    # Invoke _integer for maximum dynamic items and engine as a visible require fixed
    # configs step.
    _integer(engine, "maximum_dynamic_items", minimum=1)
    settlement_policy, synthetic_policy = sniping_execution_policies(execution_mode)
    expected_execution = {
        "fee_on_landed_failure": True,
        "historical_curve_impact": "none",
        "mode": execution_mode.value,
        # Keep sell all visible while evaluating the execution, fee on landed failure and
        # historical curve impact guard.
        "sell_all": True,
        "sell_settlement_policy": settlement_policy,
        "synthetic_proceeds_policy": synthetic_policy,
    }
    # A forged mode/policy pair must fail before any strategy or portfolio mutation.
    if execution != expected_execution:
        raise SnipingRuntimeResolutionError("execution config is unsupported")
    if (
        _integer(latency, "buy_delay_transactions", minimum=1)
        # Keep pumpfun sniping buy delay transactions visible while evaluating the pumpfun
        # sniping buy delay transactions, pumpfun sniping sell decision delay seconds and
        # integer guard.
        != PUMPFUN_SNIPING_BUY_DELAY_TRANSACTIONS
        or _integer(latency, "sell_decision_delay_seconds", minimum=1)
        != PUMPFUN_SNIPING_SELL_DECISION_DELAY_SECONDS
        or _integer(latency, "sell_delay_transactions", minimum=1)
        != _integer(strategy, "sell_delay_transactions", minimum=1)
        # Evaluate the complete require fixed configs pumpfun sniping buy delay transactions,
        # pumpfun sniping sell decision delay seconds and integer condition before guarded
        # effects.
    ):
        raise SnipingRuntimeResolutionError("latency config is unsupported")
    if network["jito_tip_lamports"] != 0:
        raise SnipingRuntimeResolutionError("Jito tips are outside sniping v3")
    if protocol["venue"] != "bonding-curve":
        # Fail the require fixed configs path with SnipingRuntimeResolutionError for only
        # the pump bonding curve is supported when bonding-curve, protocol and venue is
        # true; do not continue ambiguously.
        raise SnipingRuntimeResolutionError("only the Pump bonding curve is supported")
    if risk != {
        "buy_reservation": "gross-plus-network-plus-component-deposits-v2",
        "sell_fee_reserved_at_target": False,
        "wallet_scope": "single-shared-wallet-v1",
        # Evaluate the complete require fixed configs risk, buy reservation and sell fee
        # reserved at target condition before guarded effects.
    }:
        raise SnipingRuntimeResolutionError("risk config is unsupported")
    if scheduler != {
        "phase_table": "canonical-v1",
        "synthetic_boundary_merge": "historical-synthetic-two-way-merge-v1",
        # Evaluate the complete require fixed configs scheduler, phase table and synthetic
        # boundary merge condition before guarded effects.
    }:
        raise SnipingRuntimeResolutionError("scheduler config is unsupported")
    if (
        _string(strategy, "contract") != PUMPFUN_SNIPING_RUN_DRAFT_SCHEMA
        or _integer(strategy, "cooldown_seconds", minimum=1) != PUMPFUN_SNIPING_COOLDOWN_SECONDS
        # Keep strategy visible while evaluating the pumpfun sniping run draft schema,
        # pumpfun sniping cooldown seconds and immutable-create-event-creator-v1 guard.
        or strategy["developer_identity"] != "immutable-create-event-creator-v1"
        or strategy["quote_asset_id"] != PUMPFUN_SNIPING_QUOTE_ASSET_ID.value
        or _string(strategy, "execution_mode") != execution_mode.value
    ):
        raise SnipingRuntimeResolutionError("strategy config is unsupported")
    for field in ("buy_slippage_bps", "sell_slippage_bps"):
        # Process buy slippage bps and sell slippage bps inside the bounded require fixed
        # configs loop.
        if _integer(strategy, field, minimum=0) > 10_000:
            raise SnipingRuntimeResolutionError(f"{field} exceeds 10000 basis points")
    if universe != {
        "decision_targets": PUMPFUN_SNIPING_UNIVERSE_POLICY_ID,
        "settlement_tail_creates_targets": False,
        # Evaluate the complete require fixed configs universe, decision targets and
        # settlement tail creates targets condition before guarded effects.
    }:
        raise SnipingRuntimeResolutionError("universe config is unsupported")
    if valuation != {
        "cashback": "separate-economic-receivable-v1",
        "open_position": "net-pump-liquidation-plus-rent-return-v1",
        # Keep post migration visible while evaluating the valuation, cashback and open
        # position guard.
        "post_migration": "stale-pre-migration-v1",
    }:
        raise SnipingRuntimeResolutionError("valuation config is unsupported")


def _sniping_execution_mode(config: dict[str, object]) -> ExecutionMode:
    """Decode one of the two reviewed modes without accepting future enum members."""

    try:
        mode = ExecutionMode(_string(config, "execution_mode"))
    except ValueError as error:
        raise SnipingRuntimeResolutionError("sniping execution mode is unsupported") from error
    # The generic enum is wider than this Pump.fun strategy contract.
    if mode not in PUMPFUN_SNIPING_EXECUTION_MODES:
        raise SnipingRuntimeResolutionError("sniping execution mode is unsupported")
    return mode


def _wallet_account_profile(
    value: dict[str, object],
) -> tuple[WalletUvaInitialState, SolanaAccountCostProfile]:
    """Resolve the strict v2 initial UVA and three-schema cost closure."""

    _exact_fields(
        value,
        {
            "account_costs",
            "effective_from_unix_s",
            "effective_until_unix_s",
            "initial_uva_state",
            "profile_id",
            "schema",
        },
        "wallet account profile",
    )
    if _string(value, "schema") != PUMPFUN_SOLANA_WALLET_ACCOUNT_PROFILE_SCHEMA:
        raise SnipingRuntimeResolutionError("wallet account profile requires schema v2")
    try:
        initial_state = WalletUvaInitialState(_string(value, "initial_uva_state"))
    except ValueError as error:
        raise SnipingRuntimeResolutionError("initial UVA state is unsupported") from error

    costs: list[SolanaAccountDepositCost] = []
    for item in _object_array(value, "account_costs"):
        # Each schema price is explicit and legacy nullable fields are rejected.
        _exact_fields(
            item,
            {"deposit_lamports", "requirement_schema_id"},
            "account deposit cost",
        )
        costs.append(
            SolanaAccountDepositCost(
                _string(item, "requirement_schema_id"),
                _integer(item, "deposit_lamports", minimum=1),
            )
        )
    required = {
        PUMPFUN_LEGACY_ATA_SCHEMA_ID,
        PUMPFUN_TOKEN_2022_ATA_SCHEMA_ID,
        PUMPFUN_UVA_SCHEMA_ID,
    }
    if {item.account_schema_id for item in costs} != required or len(costs) != len(required):
        raise SnipingRuntimeResolutionError("wallet account profile has an incompatible schema set")
    return initial_state, SolanaAccountCostProfile(
        profile_id=_string(value, "profile_id"),
        effective_from_unix_s=_integer(value, "effective_from_unix_s", minimum=0),
        effective_until_unix_s=_integer(value, "effective_until_unix_s", minimum=1),
        costs=tuple(costs),
    )


def _pump_fee_profile(value: dict[str, object]) -> PumpFeeProfile:
    # Execute the pump fee profile workflow in explicit, reviewable steps.
    _exact_fields(
        value,
        {
            "buy_formula_version",
            "creator_fee_bps",
            # Pass effective from unix s explicitly so _exact_fields receives a reviewable
            # buy formula version and creator fee bps input in pump fee profile.
            "effective_from_unix_s",
            "effective_until_unix_s",
            "profile_id",
            "program_version",
            "protocol_fee_bps",
            # Pass sell formula version explicitly so _exact_fields receives a reviewable
            # buy formula version and creator fee bps input in pump fee profile.
            "sell_formula_version",
        },
        "Pump fee profile",
    )
    return PumpFeeProfile(
        # Include profile id in the completed pump fee profile result.
        profile_id=_string(value, "profile_id"),
        program_version=_string(value, "program_version"),
        buy_formula_version=_string(value, "buy_formula_version"),
        sell_formula_version=_string(value, "sell_formula_version"),
        effective_from_unix_s=_integer(value, "effective_from_unix_s", minimum=0),
        # Include effective until unix s in the completed pump fee profile result.
        effective_until_unix_s=_integer(value, "effective_until_unix_s", minimum=1),
        protocol_fee_bps=_integer(value, "protocol_fee_bps", minimum=0),
        creator_fee_bps=_integer(value, "creator_fee_bps", minimum=0),
    )


def _solana_fee_profile(value: dict[str, object]) -> SolanaFeeProfile:
    # Execute the solana fee profile workflow in explicit, reviewable steps.
    _exact_fields(
        value,
        {
            "charged_signature_count",
            "compute_unit_limit",
            # Pass effective from unix s explicitly so _exact_fields receives a reviewable
            # charged signature count and compute unit limit input in solana fee profile.
            "effective_from_unix_s",
            "effective_until_unix_s",
            "formula_version",
            "lamports_per_signature",
            "micro_lamports_per_compute_unit",
            # Pass profile id explicitly so _exact_fields receives a reviewable charged
            # signature count and compute unit limit input in solana fee profile.
            "profile_id",
            "transaction_format",
        },
        "Solana fee profile",
    )
    # Keep expected failures inside the solana fee profile error boundary.
    try:
        transaction_format = SolanaTransactionFormat(_string(value, "transaction_format"))
    except ValueError as error:
        raise SnipingRuntimeResolutionError("Solana transaction format is unsupported") from error
    return SolanaFeeProfile(
        # Include profile id in the completed solana fee profile result.
        profile_id=_string(value, "profile_id"),
        formula_version=_string(value, "formula_version"),
        transaction_format=transaction_format,
        effective_from_unix_s=_integer(value, "effective_from_unix_s", minimum=0),
        effective_until_unix_s=_integer(value, "effective_until_unix_s", minimum=1),
        # Include charged signature count in the completed solana fee profile result.
        charged_signature_count=_integer(value, "charged_signature_count", minimum=1),
        lamports_per_signature=_integer(value, "lamports_per_signature", minimum=0),
        compute_unit_limit=_integer(value, "compute_unit_limit", minimum=0),
        micro_lamports_per_compute_unit=_integer(
            value,
            # Pass micro lamports per compute unit explicitly so _integer receives a
            # reviewable micro lamports per compute unit and value input in solana fee
            # profile.
            "micro_lamports_per_compute_unit",
            minimum=0,
        ),
    )


def _component(spec: ResolvedRunSpec, role: str) -> ResolvedComponent:
    # Execute the component workflow in explicit, reviewable steps.
    try:
        return next(item for item in spec.components if item.role == role)
    except StopIteration as error:  # pragma: no cover - spec/closure validation precedes this
        raise SnipingRuntimeResolutionError(f"resolved run has no {role} component") from error


def _config(component: ResolvedComponent, fields: set[str]) -> dict[str, object]:
    # Execute the config workflow in explicit, reviewable steps.
    value = cast(dict[str, object], json.loads(component.canonical_config))
    _exact_fields(value, fields, f"component {component.role}")
    return value


def _exact_fields(value: dict[str, object], fields: set[str], label: str) -> None:
    # Execute the exact fields workflow in explicit, reviewable steps.
    if set(value) != fields:
        raise SnipingRuntimeResolutionError(f"{label} has missing or unknown fields")


def _object(value: dict[str, object], field_name: str) -> dict[str, object]:
    # Execute the object workflow in explicit, reviewable steps.
    nested = value[field_name]
    if not isinstance(nested, dict) or not all(isinstance(key, str) for key in nested):
        raise SnipingRuntimeResolutionError(f"{field_name} must be an object")
    return cast(dict[str, object], nested)


def _object_array(
    value: dict[str, object],
    field_name: str,
) -> tuple[dict[str, object], ...]:
    """Decode a strict array of string-keyed objects without coercion."""

    nested = value[field_name]
    if not isinstance(nested, list):
        raise SnipingRuntimeResolutionError(f"{field_name} must be an array")
    if not all(
        isinstance(item, dict) and all(isinstance(key, str) for key in item) for item in nested
    ):
        raise SnipingRuntimeResolutionError(f"{field_name} contains an invalid object")
    return tuple(cast(dict[str, object], item) for item in nested)


def _string(value: dict[str, object], field_name: str) -> str:
    # Execute the string workflow in explicit, reviewable steps.
    selected = value[field_name]
    if not isinstance(selected, str) or not selected or selected != selected.strip():
        raise SnipingRuntimeResolutionError(f"{field_name} must be a non-empty string")
    return selected


def _integer(value: dict[str, object], field_name: str, *, minimum: int) -> int:
    # Execute the integer workflow in explicit, reviewable steps.
    selected: Any = value[field_name]
    if isinstance(selected, bool) or not isinstance(selected, int) or selected < minimum:
        raise SnipingRuntimeResolutionError(f"{field_name} must be an integer >= {minimum}")
    return selected


def _receipt(component: ResolvedComponent) -> RuntimeComponentReceipt:
    # Return the completed receipt result without a hidden fallback.
    return RuntimeComponentReceipt(component.role, component.bundle_id, component.config_digest)


__all__ = [
    "PumpfunSnipingRuntimeComponentsResolver",
    "SnipingRuntimeResolutionError",
]
