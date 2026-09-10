"""Closed discovery metadata for versioned, typed run-draft contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from backtest.application.copy_run_contract import COPY_RUN_CONTRACT
from backtest.application.run_drafts import (
    # Discovery exposes separate copy and Sniping draft families.
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
    # Copy observation can be immediate; leaders are a bounded canonical wallet list.
    NON_NEGATIVE_INTEGER = "NON_NEGATIVE_INTEGER"
    SIGNING_WALLETS = "SIGNING_WALLETS"


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


def _copy_contract() -> RunContractDescriptor:
    """Share financial inputs while exposing only the separate copy timing policy."""
    shared = tuple(
        item
        for item in PUMPFUN_SNIPING_CONTRACT.editable_fields
        if item.name != "delivery_schedule_id"
    )
    # A copy draft adds independent observation/entry timing and fee-free price exits.
    added = (
        RunContractField("signing_wallets", RunFieldKind.SIGNING_WALLETS, True),
        RunContractField("take_profit_bps", RunFieldKind.POSITIVE_INTEGER, True),
        RunContractField("stop_loss_bps", RunFieldKind.BASIS_POINTS, True),
        RunContractField("maximum_hold_seconds", RunFieldKind.POSITIVE_INTEGER, True),
        # Zero observation delay is valid; a simulated order must still land in the future.
        RunContractField("observation_delay_transactions", RunFieldKind.NON_NEGATIVE_INTEGER, True),
        RunContractField("buy_delay_transactions", RunFieldKind.POSITIVE_INTEGER, True),
    )
    # Fixed one-entry and four-attempt rules are not editable UI parameters.
    fixed = (
        ("maximum_sell_attempts", "4"),
        ("mint_entry_limit", "1"),
        # Discovery explains consumed rejected entries and the exact retry clock.
        ("price_basis", "TOKEN_PRICE_WITHOUT_FEES"),
        ("quote_asset", "SOL"),
        ("sell_all", "true"),
        ("sell_retry_seconds", "2"),
    )
    # No Sniping cooldown or fixed entry latency is inherited into the copy descriptor.
    return RunContractDescriptor(
        COPY_RUN_CONTRACT,
        "Pump.fun Copy Buy v1",
        tuple(sorted((*shared, *added), key=lambda item: item.name)),
        fixed,
        # Field order is canonical so CLI and browser discovery agree byte for byte.
    )


PUMPFUN_COPY_BUY_CONTRACT = _copy_contract()


class RunContractNotFoundError(LookupError):
    # Keep this explicitly supported no-op branch visible.
    pass


class QueryRunContracts:
    """Read-only use case shared by CLI and Control API discovery."""

    def list(self) -> tuple[RunContractDescriptor, ...]:
        """Canonical schema order is identical for local and delegated discovery."""
        return (PUMPFUN_COPY_BUY_CONTRACT, PUMPFUN_SNIPING_CONTRACT)

    def get(self, schema: str) -> RunContractDescriptor:
        """Only implemented versioned draft families can be selected."""
        for contract in self.list():
            if contract.schema == schema:
                return contract
        raise RunContractNotFoundError(schema)


# Only advertised installed contracts are exported for transport discovery.
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
