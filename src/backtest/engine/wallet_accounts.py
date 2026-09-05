"""Pure run-scoped reducer for wallet and per-mint account provisioning."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from backtest.domain.account_requirements import (
    AccountComponentLifecycle,
    AccountComponentRecord,
    AccountReleasePolicy,
    AccountRequirementScope,
    PricedAccountRequirement,
)
from backtest.domain.identifiers import AssetId, ContentDigest
from backtest.domain.ledger import LedgerCorrelationKind


class WalletUvaInitialState(StrEnum):
    """Opening state of the one wallet-scoped Pump UVA."""

    FRESH = "fresh"
    PREWARMED = "prewarmed"


class WalletProvisioningError(ValueError):
    """An account transition contradicts the resolved provisioning contract."""


@dataclass(frozen=True, slots=True)
class WalletProvisioningState:
    """Small immutable state shared by reference and optimized execution paths."""

    initial_uva_state: WalletUvaInitialState
    uva_schema_id: str
    uva_created_by_roundtrip_id: ContentDigest | None
    open_mint_accounts: tuple[tuple[AssetId, str, ContentDigest], ...] = ()

    def __post_init__(self) -> None:
        # The initial profile fixes whether UVA exists before any run cashflow.
        if not isinstance(self.initial_uva_state, WalletUvaInitialState):
            raise TypeError("initial UVA state must be resolved")
        _stable_name(self.uva_schema_id, "UVA schema ID")
        if (
            self.initial_uva_state is WalletUvaInitialState.PREWARMED
            and self.uva_created_by_roundtrip_id is not None
        ):
            raise ValueError("prewarmed UVA cannot have an in-run creator")

        # Open mint accounts are a deterministic sorted set owned by distinct round trips.
        if self.open_mint_accounts != tuple(sorted(self.open_mint_accounts)):
            raise ValueError("open mint accounts must be canonically sorted")
        if len({item[0] for item in self.open_mint_accounts}) != len(self.open_mint_accounts):
            raise ValueError("a mint cannot have multiple open accounts")

    @property
    def uva_exists(self) -> bool:
        # A prewarmed account exists without an in-run creation posting.
        return (
            self.initial_uva_state is WalletUvaInitialState.PREWARMED
            or self.uva_created_by_roundtrip_id is not None
        )


@dataclass(frozen=True, slots=True)
class AccountReservationComponent:
    """Accepted maximum reservation for one priced requirement."""

    priced: PricedAccountRequirement
    maximum_reserved_atomic: int

    def __post_init__(self) -> None:
        # Existing wallet accounts legitimately reduce a priced requirement to zero.
        if (
            isinstance(self.maximum_reserved_atomic, bool)
            or not isinstance(self.maximum_reserved_atomic, int)
            or not 0 <= self.maximum_reserved_atomic <= self.priced.maximum_deposit_atomic
        ):
            raise ValueError("account reservation is outside its priced maximum")


@dataclass(frozen=True, slots=True)
class AccountReservationPlan:
    """Canonical account portion of one accepted buy reservation."""

    roundtrip_id: ContentDigest
    mint_asset_id: AssetId
    components: tuple[AccountReservationComponent, ...]

    def __post_init__(self) -> None:
        # A buy must carry exactly one mint account and one wallet account requirement.
        if not isinstance(self.roundtrip_id, ContentDigest):
            raise TypeError("account reservation round-trip ID must be a ContentDigest")
        if not isinstance(self.mint_asset_id, AssetId):
            raise TypeError("account reservation mint must be an AssetId")
        keys = tuple(_component_key(item.priced) for item in self.components)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("account reservation components must be sorted and unique")
        scopes = tuple(item.priced.requirement.scope for item in self.components)
        if scopes.count(AccountRequirementScope.MINT) != 1:
            raise ValueError("account reservation requires exactly one mint component")
        if scopes.count(AccountRequirementScope.WALLET) != 1:
            raise ValueError("account reservation requires exactly one wallet component")

    @property
    def reserved_asset_amounts(self) -> tuple[tuple[AssetId, int], ...]:
        """Aggregate actual accepted reservation by explicit asset."""

        totals: dict[AssetId, int] = {}
        for component in self.components:
            # Zero means an already-provisioned wallet account and creates no posting.
            if component.maximum_reserved_atomic:
                asset = component.priced.asset_id
                totals[asset] = totals.get(asset, 0) + component.maximum_reserved_atomic
        return tuple(sorted(totals.items(), key=lambda item: item[0].value))


@dataclass(frozen=True, slots=True)
class AccountProvisioningTransition:
    """Previewed atomic state and canonical component outcomes."""

    state: WalletProvisioningState
    records: tuple[AccountComponentRecord, ...]


class WalletProvisioningReducer:
    """Mutable commit shell around pure preview functions.

    Engine code previews a candidate, commits the ledger transaction, and only
    then commits this state.  A failed portfolio preview therefore cannot leak an
    account mutation.
    """

    def __init__(self, state: WalletProvisioningState) -> None:
        # The wrapper owns one immutable value and introduces no duplicate semantics.
        if not isinstance(state, WalletProvisioningState):
            raise TypeError("wallet provisioning state must be resolved")
        self._state = state

    @property
    def state(self) -> WalletProvisioningState:
        return self._state

    def reservation(
        self,
        *,
        roundtrip_id: ContentDigest,
        mint_asset_id: AssetId,
        priced_requirements: tuple[PricedAccountRequirement, ...],
    ) -> AccountReservationPlan:
        # Planning is pure and observes only already committed account state.
        return prepare_account_reservation(
            self._state,
            roundtrip_id=roundtrip_id,
            mint_asset_id=mint_asset_id,
            priced_requirements=priced_requirements,
        )

    def preview_buy(
        self,
        plan: AccountReservationPlan,
        *,
        successful: bool,
    ) -> AccountProvisioningTransition:
        return apply_buy_account_transition(self._state, plan, successful=successful)

    def preview_sell(
        self,
        *,
        roundtrip_id: ContentDigest,
        mint_asset_id: AssetId,
        records: tuple[AccountComponentRecord, ...],
        successful: bool,
    ) -> AccountProvisioningTransition:
        # Sell can only release the mint-scoped component; UVA remains run-locked.
        return apply_sell_account_transition(
            self._state,
            roundtrip_id=roundtrip_id,
            mint_asset_id=mint_asset_id,
            records=records,
            successful=successful,
        )

    def commit(self, transition: AccountProvisioningTransition) -> None:
        # Callers commit only after the matching portfolio ledger candidate succeeds.
        if not isinstance(transition, AccountProvisioningTransition):
            raise TypeError("account provisioning transition must be resolved")
        self._state = transition.state


def initial_wallet_provisioning_state(
    initial_uva_state: WalletUvaInitialState,
    *,
    uva_schema_id: str,
) -> WalletProvisioningState:
    """Create the deterministic run-opening account state."""

    return WalletProvisioningState(initial_uva_state, uva_schema_id, None)


def prepare_account_reservation(
    state: WalletProvisioningState,
    *,
    roundtrip_id: ContentDigest,
    mint_asset_id: AssetId,
    priced_requirements: tuple[PricedAccountRequirement, ...],
) -> AccountReservationPlan:
    """Compute an accepted reservation without mutating provisioning state."""

    if not isinstance(priced_requirements, tuple) or not priced_requirements:
        raise TypeError("priced account requirements must be a non-empty tuple")
    if any(not isinstance(item, PricedAccountRequirement) for item in priced_requirements):
        raise TypeError("priced account requirements contain an invalid value")
    if any(opened[0] == mint_asset_id for opened in state.open_mint_accounts):
        raise WalletProvisioningError("mint account is already open")

    # The resolved wallet profile and protocol requirement must name one exact UVA.
    wallet_requirements = tuple(
        item
        for item in priced_requirements
        if item.requirement.scope is AccountRequirementScope.WALLET
    )
    if len(wallet_requirements) != 1:
        raise WalletProvisioningError("exactly one wallet requirement is required")
    if wallet_requirements[0].requirement.requirement_schema_id != state.uva_schema_id:
        raise WalletProvisioningError("wallet requirement does not match the resolved UVA")

    components: list[AccountReservationComponent] = []
    for priced in priced_requirements:
        # Wallet price is reserved only while the committed UVA does not exist.
        required = priced.maximum_deposit_atomic
        if priced.requirement.scope is AccountRequirementScope.WALLET and state.uva_exists:
            required = 0
        components.append(AccountReservationComponent(priced, required))
    components.sort(key=lambda item: _component_key(item.priced))
    return AccountReservationPlan(roundtrip_id, mint_asset_id, tuple(components))


def unsubmitted_account_records(
    state: WalletProvisioningState,
    plan: AccountReservationPlan,
) -> tuple[AccountComponentRecord, ...]:
    """Describe requirements that never became a portfolio reservation."""

    records: list[AccountComponentRecord] = []
    for component in plan.components:
        # Existing wallet state is still visible without attributing opening/in-run cash.
        lifecycle = _existing_wallet_lifecycle(state, component.priced)
        if lifecycle is None:
            lifecycle = AccountComponentLifecycle.NOT_CREATED
        records.append(_record(component, plan.roundtrip_id, lifecycle=lifecycle))
    return tuple(records)


def apply_buy_account_transition(
    state: WalletProvisioningState,
    plan: AccountReservationPlan,
    *,
    successful: bool,
) -> AccountProvisioningTransition:
    """Preview buy landing account state and reservation outcomes."""

    if not isinstance(successful, bool):
        raise TypeError("successful must be a boolean")
    if any(opened[0] == plan.mint_asset_id for opened in state.open_mint_accounts):
        raise WalletProvisioningError("mint account is already open")
    if not successful:
        # Failed landing releases every actual accepted reservation and changes no state.
        failed_records = tuple(
            _record(
                component,
                plan.roundtrip_id,
                lifecycle=(
                    _existing_wallet_lifecycle(state, component.priced)
                    or AccountComponentLifecycle.RESERVATION_RELEASED
                ),
                released_atomic=component.maximum_reserved_atomic,
            )
            for component in plan.components
        )
        return AccountProvisioningTransition(state, failed_records)

    candidate = state
    records: list[AccountComponentRecord] = []
    for component in plan.components:
        requirement = component.priced.requirement
        if requirement.scope is AccountRequirementScope.MINT:
            # A successful buy creates a distinct ATA for this mint.
            opened = (
                *candidate.open_mint_accounts,
                (plan.mint_asset_id, requirement.requirement_schema_id, plan.roundtrip_id),
            )
            candidate = replace(candidate, open_mint_accounts=tuple(sorted(opened)))
            records.append(
                _record(
                    component,
                    plan.roundtrip_id,
                    lifecycle=AccountComponentLifecycle.CREATED_LOCKED,
                    paid_atomic=component.maximum_reserved_atomic,
                )
            )
            continue

        # Only the first successful canonical landing creates and pays for the UVA.
        existing = _existing_wallet_lifecycle(candidate, component.priced)
        if existing is not None:
            records.append(
                _record(
                    component,
                    plan.roundtrip_id,
                    lifecycle=existing,
                    released_atomic=component.maximum_reserved_atomic,
                )
            )
            continue
        candidate = replace(candidate, uva_created_by_roundtrip_id=plan.roundtrip_id)
        records.append(
            _record(
                component,
                plan.roundtrip_id,
                lifecycle=AccountComponentLifecycle.CREATED_LOCKED,
                paid_atomic=component.maximum_reserved_atomic,
            )
        )
    return AccountProvisioningTransition(candidate, tuple(records))


def apply_sell_account_transition(
    state: WalletProvisioningState,
    *,
    roundtrip_id: ContentDigest,
    mint_asset_id: AssetId,
    records: tuple[AccountComponentRecord, ...],
    successful: bool,
) -> AccountProvisioningTransition:
    """Preview optional ATA close while preserving wallet-scoped UVA."""

    if not isinstance(successful, bool):
        raise TypeError("successful must be a boolean")
    if not successful:
        return AccountProvisioningTransition(state, records)
    matching = tuple(item for item in state.open_mint_accounts if item[0] == mint_asset_id)
    if len(matching) != 1 or matching[0][2] != roundtrip_id:
        raise WalletProvisioningError("sell does not own the open mint account")

    updated: list[AccountComponentRecord] = []
    for record in records:
        # Close only this round trip's mint-scoped account; wallet UVA remains untouched.
        if record.scope is AccountRequirementScope.MINT:
            if record.lifecycle is not AccountComponentLifecycle.CREATED_LOCKED:
                raise WalletProvisioningError("mint account is not in a closable state")
            record = replace(
                record,
                refunded_atomic=record.paid_atomic,
                locked_delta_atomic=0,
                lifecycle=AccountComponentLifecycle.CLOSED_REFUNDED,
            )
        updated.append(record)
    remaining = tuple(item for item in state.open_mint_accounts if item[0] != mint_asset_id)
    return AccountProvisioningTransition(
        replace(state, open_mint_accounts=remaining),
        tuple(updated),
    )


def refundable_mint_deposits(
    records: tuple[AccountComponentRecord, ...],
) -> tuple[tuple[AssetId, int], ...]:
    """Return currently locked closeable ATA value by explicit asset."""

    totals: dict[AssetId, int] = {}
    for record in records:
        # Only positive final mint lock is liquidated/returned on a successful sell.
        if (
            record.scope is AccountRequirementScope.MINT
            and record.release_policy is AccountReleasePolicy.CLOSE_ON_SUCCESSFUL_SELL
            and record.locked_delta_atomic > 0
        ):
            totals[record.asset_id] = totals.get(record.asset_id, 0) + record.locked_delta_atomic
    return tuple(sorted(totals.items(), key=lambda item: item[0].value))


def run_locked_value(
    records: tuple[AccountComponentRecord, ...],
) -> tuple[tuple[AssetId, int], ...]:
    """Return wallet-scoped value created and still locked by this round trip."""

    totals: dict[AssetId, int] = {}
    for record in records:
        # Existing/prewarmed UVA is intentionally not attributed a second time.
        if (
            record.scope is AccountRequirementScope.WALLET
            and record.release_policy is AccountReleasePolicy.RUN_LOCKED
            and record.locked_delta_atomic > 0
        ):
            totals[record.asset_id] = totals.get(record.asset_id, 0) + record.locked_delta_atomic
    return tuple(sorted(totals.items(), key=lambda item: item[0].value))


def _existing_wallet_lifecycle(
    state: WalletProvisioningState,
    priced: PricedAccountRequirement,
) -> AccountComponentLifecycle | None:
    # Mint requirements never share another target's account state.
    if priced.requirement.scope is not AccountRequirementScope.WALLET:
        return None
    if state.initial_uva_state is WalletUvaInitialState.PREWARMED:
        return AccountComponentLifecycle.PREWARMED
    if state.uva_created_by_roundtrip_id is not None:
        return AccountComponentLifecycle.EXISTING_RUN_LOCKED
    return None


def _record(
    component: AccountReservationComponent,
    roundtrip_id: ContentDigest,
    *,
    lifecycle: AccountComponentLifecycle,
    paid_atomic: int = 0,
    released_atomic: int = 0,
) -> AccountComponentRecord:
    # Attribution remains with the round trip that accepted this exact reservation.
    priced = component.priced
    return AccountComponentRecord(
        requirement_schema_id=priced.requirement.requirement_schema_id,
        asset_id=priced.asset_id,
        scope=priced.requirement.scope,
        release_policy=priced.requirement.release_policy,
        maximum_reserved_atomic=component.maximum_reserved_atomic,
        # Landing outcome fields are explicit and use no inferred scalar rent bucket.
        paid_atomic=paid_atomic,
        released_atomic=released_atomic,
        refunded_atomic=0,
        locked_delta_atomic=paid_atomic,
        lifecycle=lifecycle,
        attribution_kind=LedgerCorrelationKind.ROUNDTRIP,
        attribution_id=roundtrip_id,
    )


def _component_key(priced: PricedAccountRequirement) -> tuple[str, str]:
    # Scope-first order keeps the per-mint ATA before the wallet-scoped UVA.
    return priced.requirement.scope.value, priced.requirement.requirement_schema_id


def _stable_name(value: str, label: str) -> None:
    # Reducer state is semantic and therefore rejects ambiguous schema names.
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise ValueError(f"{label} must be non-empty, trimmed and NUL-free")


__all__ = [
    "AccountProvisioningTransition",
    "AccountReservationComponent",
    "AccountReservationPlan",
    "WalletProvisioningError",
    "WalletProvisioningReducer",
    # Expose immutable state and pure functions for golden/property tests.
    "WalletProvisioningState",
    "WalletUvaInitialState",
    "apply_buy_account_transition",
    "apply_sell_account_transition",
    "initial_wallet_provisioning_state",
    "prepare_account_reservation",
    "refundable_mint_deposits",
    "run_locked_value",
    "unsubmitted_account_records",
]
