"""Closed observation-policy resolver for DeliverySchedule compilation.

The DeliverySchedule stores observation releases only.  FirstSwap exposes an
explicit block/slot observation delay, while Pump.fun Sniping v3 observes the
atomic creation group at its own boundary and keeps buy/sell latency in the
engine's dynamic order queue.  Keeping this distinction here prevents order
latency from being accidentally materialized as observation latency.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast

from backtest.application.run_drafts import (
    PUMPFUN_SNIPING_EXECUTION_MODES,
    PUMPFUN_SNIPING_RUN_DRAFT_SCHEMA,
)
from backtest.application.run_specs import ResolvedComponent


# Keep the delivery observation policy error contract and validation rules together.
class DeliveryObservationPolicyError(ValueError):
    """Resolved components do not describe a supported observation policy."""


@dataclass(frozen=True, slots=True)
class ResolvedObservationPolicy:
    block_delay: int
    contract: str


def resolve_observation_policy(
    # Keep the components input explicit in the resolve observation policy contract.
    components: tuple[ResolvedComponent, ...],
) -> ResolvedObservationPolicy:
    # Execute the resolve observation policy workflow in explicit, reviewable steps.
    by_role = {component.role: component for component in components}
    if set(by_role) != {"clock", "engine", "latency", "scheduler"}:
        # Handle the resolve observation policy by role, clock and engine condition as a
        # distinct block.
        raise DeliveryObservationPolicyError(
            "delivery components must be clock/engine/latency/scheduler"
        )
    latency = _config(by_role["latency"])
    if set(latency) == {"observation_slots", "order_slots"}:
        # Handle the resolve observation policy latency, observation slots and order slots
        # condition as a distinct block.
        scheduler = _config(by_role["scheduler"])
        if scheduler != {"phase_table": "canonical-v1"}:
            # Handle the resolve observation policy scheduler, phase table and
            # canonical-v1 condition as a distinct block.
            raise DeliveryObservationPolicyError(
                "slot delivery requires the canonical scheduler config"
            )
        observation_slots = _integer(latency, "observation_slots", minimum=0)
        _integer(latency, "order_slots", minimum=0)
        # Return the completed resolve observation policy result without a hidden
        # fallback.
        return ResolvedObservationPolicy(
            block_delay=observation_slots,
            contract="slot-latency-v1",
        )

    if set(latency) == {
        # Keep buy delay transactions visible while evaluating the latency, buy delay
        # transactions and sell decision delay seconds guard.
        "buy_delay_transactions",
        "sell_decision_delay_seconds",
        "sell_delay_transactions",
    }:
        # Handle the resolve observation policy latency, buy delay transactions and sell
        # decision delay seconds condition as a distinct block.
        clock = _config(by_role["clock"])
        engine = _config(by_role["engine"])
        scheduler = _config(by_role["scheduler"])
        if clock != {
            "block_time_resolution": "seconds-v1",
            # Keep contract visible while evaluating the clock, block time resolution and
            # contract guard.
            "contract": "compact-global-transaction-clock-v1",
        }:
            # Handle the resolve observation policy clock, block time resolution and
            # contract condition as a distinct block.
            raise DeliveryObservationPolicyError(
                "sniping delivery requires the compact transaction clock"
            )
        if set(engine) != {"execution_mode", "maximum_dynamic_items", "run_contract"}:
            raise DeliveryObservationPolicyError("sniping engine config is unsupported")
        # Observation timing is shared by both reviewed exogenous settlement modes.
        supported_modes = {mode.value for mode in PUMPFUN_SNIPING_EXECUTION_MODES}
        if (
            engine["execution_mode"] not in supported_modes
            or engine["run_contract"] != PUMPFUN_SNIPING_RUN_DRAFT_SCHEMA
        ):
            # Reject future modes instead of reusing this observation contract silently.
            raise DeliveryObservationPolicyError("sniping engine contract is unsupported")
        # Invoke _integer for maximum dynamic items and engine as a visible resolve
        # observation policy step.
        _integer(engine, "maximum_dynamic_items", minimum=1)
        if scheduler != {
            "phase_table": "canonical-v1",
            "synthetic_boundary_merge": "historical-synthetic-two-way-merge-v1",
        }:
            # Handle the resolve observation policy scheduler, phase table and synthetic
            # boundary merge condition as a distinct block.
            raise DeliveryObservationPolicyError(
                "sniping delivery requires the canonical synthetic-boundary scheduler"
            )
        if _integer(latency, "buy_delay_transactions", minimum=1) != 500:
            # Handle the resolve observation policy integer, latency and buy delay
            # transactions condition as a distinct block.
            raise DeliveryObservationPolicyError(
                "sniping buy delay must be exactly 500 global transactions"
            )
        if _integer(latency, "sell_decision_delay_seconds", minimum=1) != 2:
            # Handle the resolve observation policy integer, latency and sell decision
            # delay seconds condition as a distinct block.
            raise DeliveryObservationPolicyError(
                "sniping sell decision delay must be exactly 2 seconds"
            )
        _integer(latency, "sell_delay_transactions", minimum=1)
        return ResolvedObservationPolicy(
            # Pass block delay explicitly so ResolvedObservationPolicy receives a
            # reviewable pumpfun-sniping-post-group-observation-v1 input in resolve
            # observation policy.
            block_delay=0,
            contract="pumpfun-sniping-post-group-observation-v1",
        )

    raise DeliveryObservationPolicyError("delivery latency config is unsupported")


def _config(component: ResolvedComponent) -> dict[str, object]:
    # Execute the config workflow in explicit, reviewable steps.
    try:
        value = json.loads(component.canonical_config)
    except (TypeError, ValueError) as error:  # pragma: no cover - component validates JSON
        raise DeliveryObservationPolicyError(
            f"component {component.role} config is invalid"
        ) from error
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise DeliveryObservationPolicyError(f"component {component.role} config must be an object")
    # Return the completed config result without a hidden fallback.
    return cast(dict[str, object], value)


def _integer(config: dict[str, object], field: str, *, minimum: int) -> int:
    # Execute the integer workflow in explicit, reviewable steps.
    value = config[field]
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise DeliveryObservationPolicyError(f"{field} must be an integer >= {minimum}")
    return value


__all__ = [
    # Keep the delivery observation policy error component named inside the all contract.
    "DeliveryObservationPolicyError",
    "ResolvedObservationPolicy",
    "resolve_observation_policy",
]
