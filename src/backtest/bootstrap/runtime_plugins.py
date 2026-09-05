"""Strict composition-root resolver for checked-in reference plugins."""

from __future__ import annotations

import json
from typing import Any, cast

from backtest.application.code_bundles import CodeBundleIntegrityError
from backtest.application.ports.runs import (
    # Include resolved runtime components so the runs dependency remains explicit.
    ResolvedRuntimeComponents,
    RuntimeComponentReceipt,
)
from backtest.application.run_specs import ResolvedComponent, ResolvedRunSpec
from backtest.bootstrap.reference_bundles import (
    # Include reference bundle integrity error so the reference bundles dependency remains
    # explicit.
    ReferenceBundleIntegrityError,
    ReferenceBundleRegistry,
)
from backtest.domain.execution import ExecutionMode
from backtest.domain.identifiers import AssetId, PoolId, RuntimeLockId

# Import reference at the visible module dependency boundary.
from backtest.engine.reference import SlotLatencyModel
from backtest.plugins.execution import ConstantProductExecutionModel
from backtest.plugins.risk import StaticRiskPolicy
from backtest.plugins.strategies import FirstSwapStrategy


class RuntimePluginResolutionError(RuntimeError):
    """A resolved component cannot be instantiated by this runtime."""


class ReferenceRuntimeComponentsResolver:
    def __init__(
        self,
        expected_runtime_lock_id: RuntimeLockId,
        bundle_registry: ReferenceBundleRegistry | None = None,
        # Close the init signature after its explicit inputs.
    ) -> None:
        # Execute the reference runtime components resolver init workflow in explicit,
        # reviewable steps.
        self._runtime_lock_id = expected_runtime_lock_id
        self._bundle_registry = bundle_registry or ReferenceBundleRegistry()

    def resolve(self, spec: ResolvedRunSpec) -> ResolvedRuntimeComponents:
        # Execute the reference runtime components resolver resolve workflow in explicit,
        # reviewable steps.
        if spec.runtime_lock_id != self._runtime_lock_id:
            raise RuntimePluginResolutionError("resolved runtime lock differs from this process")
        try:
            # Perform the protected reference runtime components resolver resolve
            # operation before explicit failure handling.
            closure = self._bundle_registry.snapshot()
            closure.require_components(spec.components, spec.dependency_merkle_root)
        except (CodeBundleIntegrityError, ReferenceBundleIntegrityError) as error:
            # Translate the code bundle integrity error and reference bundle integrity
            # error failure through the reference runtime components resolver resolve
            # boundary.
            raise RuntimePluginResolutionError(
                "resolved bundle closure differs from installed exact source bytes"
            ) from error
        strategy_component = _component(spec, "strategy")
        execution_component = _component(spec, "execution")
        # Assemble risk component once so the reference runtime components resolver
        # resolve workflow shares one value.
        risk_component = _component(spec, "risk")
        latency_component = _component(spec, "latency")

        clock_config = _config(_component(spec, "clock"), {"duration_mapping"})
        engine_config = _config(_component(spec, "engine"), {"maximum_dynamic_items"})
        protocol_config = _config(_component(spec, "protocol:reference_amm"), {"version"})
        # Assemble scheduler config once so the reference runtime components resolver
        # resolve workflow shares one value.
        scheduler_config = _config(_component(spec, "scheduler"), {"phase_table"})
        universe_config = _config(_component(spec, "universe"), {"policy"})
        valuation_config = _config(_component(spec, "valuation:price_source"), {"policy"})
        try:
            spec.inference_policy()
        except ValueError as error:  # pragma: no cover - ResolvedRunSpec already validates it
            raise RuntimePluginResolutionError("exact inference policy is unsupported") from error
        if clock_config != {"duration_mapping": "ceil-to-next-boundary-v1"}:
            raise RuntimePluginResolutionError("clock policy config is unsupported")
        _integer(engine_config, "maximum_dynamic_items", minimum=1)
        if protocol_config != {"version": 1}:
            # Fail the reference runtime components resolver resolve path with
            # RuntimePluginResolutionError for reference protocol config is unsupported
            # when protocol config and version is true; do not continue ambiguously.
            raise RuntimePluginResolutionError("reference protocol config is unsupported")
        if scheduler_config != {"phase_table": "canonical-v1"}:
            raise RuntimePluginResolutionError("scheduler config is unsupported")
        if universe_config != {"policy": "point-in-time-observed-assets-v1"}:
            raise RuntimePluginResolutionError("universe config is unsupported")
        # Evaluate the complete reference runtime components resolver resolve valuation
        # config, policy and none-v1 condition before guarded effects.
        if valuation_config != {"policy": "none-v1"}:
            raise RuntimePluginResolutionError("valuation config is unsupported")

        strategy_config = _config(
            strategy_component,
            {
                # Pass amount in atomic explicitly so _config receives a reviewable amount
                # in atomic and bought asset id input in reference runtime components
                # resolver resolve.
                "amount_in_atomic",
                "bought_asset_id",
                "minimum_amount_out_atomic",
                "pool_id",
                "sold_asset_id",
                # Close the amount in atomic and bought asset id payload only after all
                # reference runtime components resolver resolve fields are present.
            },
        )
        execution_config = _config(execution_component, {"fee_bps", "mode"})
        risk_config = _config(risk_component, {"maximum_order_input_atomic"})
        latency_config = _config(latency_component, {"observation_slots", "order_slots"})
        # Keep expected failures inside the reference runtime components resolver resolve
        # error boundary.
        try:
            mode = ExecutionMode(_string(execution_config, "mode"))
        except ValueError as error:
            raise RuntimePluginResolutionError("execution mode is unsupported") from error
        if mode is not spec.execution_mode():  # pragma: no cover - same exact config
            raise RuntimePluginResolutionError("execution mode resolution is inconsistent")

        latency = SlotLatencyModel(
            observation_slots=_integer(latency_config, "observation_slots", minimum=0),
            order_slots=_integer(latency_config, "order_slots", minimum=0),
            bundle_identity=latency_component.bundle_id,
            # Complete SlotLatencyModel only after its observation slots and order slots
            # inputs are visible in reference runtime components resolver resolve.
        )
        return ResolvedRuntimeComponents(
            strategy=FirstSwapStrategy(
                pool_id=PoolId(_string(strategy_config, "pool_id")),
                sold_asset_id=AssetId(_string(strategy_config, "sold_asset_id")),
                # Include bought asset id in the completed reference runtime components
                # resolver resolve result.
                bought_asset_id=AssetId(_string(strategy_config, "bought_asset_id")),
                amount_in_atomic=_integer(strategy_config, "amount_in_atomic", minimum=1),
                minimum_amount_out_atomic=_integer(
                    strategy_config,
                    "minimum_amount_out_atomic",
                    # Pass minimum explicitly so _integer receives a reviewable minimum
                    # amount out atomic and strategy config input in reference runtime
                    # components resolver resolve.
                    minimum=0,
                ),
                bundle_id=strategy_component.bundle_id,
            ),
            execution_model=ConstantProductExecutionModel(
                # Include fee bps in the completed reference runtime components resolver
                # resolve result.
                fee_bps=_integer(execution_config, "fee_bps", minimum=0),
                bundle_id=execution_component.bundle_id,
            ),
            risk_policy=StaticRiskPolicy(
                maximum_order_input_atomic=_integer(
                    # Pass risk config explicitly so _integer receives a reviewable
                    # maximum order input atomic and risk config input in reference
                    # runtime components resolver resolve.
                    risk_config,
                    "maximum_order_input_atomic",
                    minimum=1,
                ),
                bundle_id=risk_component.bundle_id,
                # Complete StaticRiskPolicy only after its maximum order input atomic and
                # bundle id inputs are visible in reference runtime components resolver
                # resolve.
            ),
            latency=latency,
            receipts=tuple(_receipt(component) for component in spec.components),
        )


def _component(spec: ResolvedRunSpec, role: str) -> ResolvedComponent:
    # Return the completed component result without a hidden fallback.
    return next(item for item in spec.components if item.role == role)


def _config(component: ResolvedComponent, exact_fields: set[str]) -> dict[str, object]:
    # Execute the config workflow in explicit, reviewable steps.
    value = cast(dict[str, object], json.loads(component.canonical_config))
    if set(value) != exact_fields:
        # Handle the config set(value) != exact_fields branch as a distinct logical block.
        raise RuntimePluginResolutionError(
            f"component {component.role} config has missing or unknown fields"
        )
    return value


def _string(config: dict[str, object], field_name: str) -> str:
    # Execute the string workflow in explicit, reviewable steps.
    value = config[field_name]
    if not isinstance(value, str) or not value or value != value.strip():
        raise RuntimePluginResolutionError(f"{field_name} must be a non-empty string")
    return value


def _integer(config: dict[str, object], field_name: str, *, minimum: int) -> int:
    # Execute the integer workflow in explicit, reviewable steps.
    value: Any = config[field_name]
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise RuntimePluginResolutionError(f"{field_name} must be an integer >= {minimum}")
    return value


def _receipt(component: ResolvedComponent) -> RuntimeComponentReceipt:
    # Execute the receipt workflow in explicit, reviewable steps.
    return RuntimeComponentReceipt(
        component.role,
        component.bundle_id,
        component.config_digest,
    )


# Bind all once as an explicit module-level contract.
__all__ = ["ReferenceRuntimeComponentsResolver", "RuntimePluginResolutionError"]
