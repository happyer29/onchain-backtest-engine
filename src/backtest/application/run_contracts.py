"""Closed discovery metadata for versioned, typed run-draft contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from backtest.application.run_drafts import (
    PUMPFUN_SNIPING_EXECUTION_MODES,
    PUMPFUN_SNIPING_RUN_DRAFT_SCHEMA,
)
from backtest.application.sniping_run_contract import PUMPFUN_SNIPING_UNIVERSE_POLICY_ID


# Keep the run field kind contract and validation rules together.
class RunFieldKind(StrEnum):
    CONTENT_ID = "CONTENT_ID"
    ATOMIC_DECIMAL = "ATOMIC_DECIMAL"
    BASIS_POINTS = "BASIS_POINTS"
    POSITIVE_INTEGER = "POSITIVE_INTEGER"
    # Declare closed enum explicitly in the run field kind contract.
    CLOSED_ENUM = "CLOSED_ENUM"
    TYPED_PROFILE = "TYPED_PROFILE"
    ROOT_SEED_DECIMAL = "ROOT_SEED_DECIMAL"


# Keep the run contract field contract and validation rules together.
@dataclass(frozen=True, slots=True, order=True)
class RunContractField:
    name: str
    kind: RunFieldKind
    required: bool
    # Declare enum values explicitly in the run contract field contract.
    enum_values: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # Execute the run contract field post init workflow in explicit, reviewable steps.
        if not self.name or self.name != self.name.strip():
            raise ValueError("run contract field name must be non-empty and trimmed")
        if self.kind is RunFieldKind.CLOSED_ENUM:
            # Handle the run contract field post init self.kind is
            # RunFieldKind.CLOSED_ENUM branch as a distinct logical block.
            if not self.enum_values or tuple(sorted(set(self.enum_values))) != self.enum_values:
                raise ValueError("closed enum values must be non-empty, sorted and unique")
        # Handle the run contract field post init complement of self.kind is
        # RunFieldKind.CLOSED_ENUM explicitly.
        elif self.enum_values:
            raise ValueError("only a closed enum field may expose enum values")

    def document(self) -> dict[str, object]:
        # Execute the run contract field document workflow in explicit, reviewable steps.
        return {
            "enum_values": list(self.enum_values),
            "kind": self.kind.value,
            "name": self.name,
            "required": self.required,
            # Return the completed run contract field document result without a hidden
            # fallback.
        }


# Keep the run contract descriptor contract and validation rules together.
@dataclass(frozen=True, slots=True)
class RunContractDescriptor:
    schema: str
    title: str
    editable_fields: tuple[RunContractField, ...]
    # Declare fixed semantics explicitly in the run contract descriptor contract.
    fixed_semantics: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        # Execute the run contract descriptor post init workflow in explicit, reviewable
        # steps.
        if not self.schema or self.schema != self.schema.strip():
            raise ValueError("run contract schema must be non-empty and trimmed")
        if not self.title or self.title != self.title.strip():
            raise ValueError("run contract title must be non-empty and trimmed")
        if tuple(sorted(self.editable_fields, key=lambda item: item.name)) != self.editable_fields:
            # Fail the run contract descriptor post init path with ValueError for editable
            # run fields must be sorted when editable fields, sorted and name is true; do
            # not continue ambiguously.
            raise ValueError("editable run fields must be sorted")
        if len({item.name for item in self.editable_fields}) != len(self.editable_fields):
            raise ValueError("editable run fields must be unique")
        if tuple(sorted(self.fixed_semantics)) != self.fixed_semantics:
            raise ValueError("fixed run semantics must be sorted")
        # Evaluate the complete run contract descriptor post init fixed semantics, name
        # and value condition before guarded effects.
        if len({name for name, _ in self.fixed_semantics}) != len(self.fixed_semantics):
            raise ValueError("fixed run semantics must be unique")

    def document(self) -> dict[str, object]:
        # Execute the run contract descriptor document workflow in explicit, reviewable
        # steps.
        return {
            "editable_fields": [item.document() for item in self.editable_fields],
            "fixed_semantics": dict(self.fixed_semantics),
            "schema": self.schema,
            "title": self.title,
            # Return the completed run contract descriptor document result without a hidden
            # fallback.
        }


PUMPFUN_SNIPING_CONTRACT = RunContractDescriptor(
    schema=PUMPFUN_SNIPING_RUN_DRAFT_SCHEMA,
    title="Pump.fun Sniping v3",
    editable_fields=tuple(
        # Keep the sorted and run contract field sorted step visible while building
        # pumpfun sniping contract.
        sorted(
            (
                RunContractField("buy_slippage_bps", RunFieldKind.BASIS_POINTS, True),
                RunContractField("buy_solana_fee_profile", RunFieldKind.TYPED_PROFILE, True),
                RunContractField("dataset_revision_id", RunFieldKind.CONTENT_ID, True),
                # Keep the delivery schedule id RunContractField step visible while
                # building pumpfun sniping contract.
                RunContractField("delivery_schedule_id", RunFieldKind.CONTENT_ID, False),
                RunContractField(
                    "execution_mode",
                    RunFieldKind.CLOSED_ENUM,
                    True,
                    # Discovery is authoritative for the UI's selectable mode list.
                    tuple(mode.value for mode in PUMPFUN_SNIPING_EXECUTION_MODES),
                ),
                RunContractField("gross_buy_budget_lamports", RunFieldKind.ATOMIC_DECIMAL, True),
                RunContractField("initial_sol_balance_lamports", RunFieldKind.ATOMIC_DECIMAL, True),
                # Keep exact profile and replay references explicit editable inputs.
                RunContractField("pump_fee_profile", RunFieldKind.TYPED_PROFILE, True),
                RunContractField("replay_pack_id", RunFieldKind.CONTENT_ID, False),
                # Keep the root seed RunContractField step visible while building pumpfun
                # sniping contract.
                RunContractField("root_seed", RunFieldKind.ROOT_SEED_DECIMAL, True),
                RunContractField("sell_delay_transactions", RunFieldKind.POSITIVE_INTEGER, True),
                RunContractField("sell_slippage_bps", RunFieldKind.BASIS_POINTS, True),
                RunContractField("sell_solana_fee_profile", RunFieldKind.TYPED_PROFILE, True),
                RunContractField("snapshot_id", RunFieldKind.CONTENT_ID, True),
                # Keep the wallet account profile RunContractField step visible while
                # building pumpfun sniping contract.
                RunContractField("wallet_account_profile", RunFieldKind.TYPED_PROFILE, True),
            ),
            key=lambda item: item.name,
        )
    ),
    # Pass fixed semantics explicitly so RunContractDescriptor receives a reviewable fun
    # sniping v1 and buy slippage bps input in module.
    fixed_semantics=(
        ("buy_delay_transactions", "500"),
        ("cooldown_seconds", "600"),
        ("quote_asset", "SOL"),
        # Open the fun sniping v1 and buy slippage bps payload explicitly for
        # RunContractDescriptor within module.
        ("sell_all", "true"),
        ("sell_decision_delay_seconds", "2"),
        ("universe_policy", PUMPFUN_SNIPING_UNIVERSE_POLICY_ID),
    ),
)


class RunContractNotFoundError(LookupError):
    # Keep this explicitly supported no-op branch visible.
    pass


class QueryRunContracts:
    """Read-only use case shared by CLI and Control API discovery."""

    def list(self) -> tuple[RunContractDescriptor, ...]:
        return (PUMPFUN_SNIPING_CONTRACT,)

    def get(self, schema: str) -> RunContractDescriptor:
        # Execute the query run contracts get workflow in explicit, reviewable steps.
        if schema != PUMPFUN_SNIPING_CONTRACT.schema:
            raise RunContractNotFoundError(schema)
        return PUMPFUN_SNIPING_CONTRACT


__all__ = [
    "PUMPFUN_SNIPING_CONTRACT",
    # Keep the query run contracts component named inside the all contract.
    "QueryRunContracts",
    "RunContractDescriptor",
    "RunContractField",
    "RunContractNotFoundError",
    "RunFieldKind",
    # Complete the all group only after its semantic components are visible.
]
