"""Generic account requirements and canonical lifecycle result components.

Protocol plugins describe *which* accounts an order needs, network plugins
price those requirements, and the engine owns provisioning state.  Keeping the
three responsibilities separate prevents Solana rent rules from leaking into
strategy or protocol math.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from backtest.domain.identifiers import AssetId, ContentDigest
from backtest.domain.ledger import LedgerCorrelationKind


class AccountRequirementScope(StrEnum):
    """Lifetime key used by the wallet provisioning reducer."""

    MINT = "MINT"
    WALLET = "WALLET"


class AccountReleasePolicy(StrEnum):
    """When a successfully created account may return its deposit."""

    CLOSE_ON_SUCCESSFUL_SELL = "CLOSE_ON_SUCCESSFUL_SELL"
    RUN_LOCKED = "RUN_LOCKED"


class AccountComponentLifecycle(StrEnum):
    """Final outcome of one account requirement for one round trip."""

    NOT_CREATED = "NOT_CREATED"
    RESERVATION_RELEASED = "RESERVATION_RELEASED"
    PREWARMED = "PREWARMED"
    EXISTING_RUN_LOCKED = "EXISTING_RUN_LOCKED"
    CREATED_LOCKED = "CREATED_LOCKED"
    CLOSED_REFUNDED = "CLOSED_REFUNDED"


@dataclass(frozen=True, slots=True)
class AccountRequirement:
    """Protocol-owned account need without any network price."""

    requirement_schema_id: str
    scope: AccountRequirementScope
    release_policy: AccountReleasePolicy

    def __post_init__(self) -> None:
        # Schema IDs are semantic inputs and therefore must serialize canonically.
        _require_stable_name("requirement_schema_id", self.requirement_schema_id)
        if not isinstance(self.scope, AccountRequirementScope):
            raise TypeError("account requirement scope must be resolved")
        if not isinstance(self.release_policy, AccountReleasePolicy):
            raise TypeError("account release policy must be resolved")

        # The scope and release policy pairing is closed for the initial contract.
        expected = {
            AccountRequirementScope.MINT: AccountReleasePolicy.CLOSE_ON_SUCCESSFUL_SELL,
            AccountRequirementScope.WALLET: AccountReleasePolicy.RUN_LOCKED,
        }
        if expected[self.scope] is not self.release_policy:
            raise ValueError("account requirement scope and release policy are incompatible")


@dataclass(frozen=True, slots=True)
class PricedAccountRequirement:
    """Network-priced account requirement in an explicit fee asset."""

    requirement: AccountRequirement
    asset_id: AssetId
    maximum_deposit_atomic: int

    def __post_init__(self) -> None:
        # Network pricing must never silently infer the native/quote asset.
        if not isinstance(self.requirement, AccountRequirement):
            raise TypeError("requirement must be an AccountRequirement")
        if not isinstance(self.asset_id, AssetId):
            raise TypeError("account deposit asset must be an AssetId")
        _require_u64("maximum_deposit_atomic", self.maximum_deposit_atomic, positive=True)


@dataclass(frozen=True, slots=True)
class AccountComponentRecord:
    """Canonical v3 result projection for one account requirement."""

    requirement_schema_id: str
    asset_id: AssetId
    scope: AccountRequirementScope
    release_policy: AccountReleasePolicy
    maximum_reserved_atomic: int
    # Paid and released split actual reservation consumption from unused release.
    paid_atomic: int
    released_atomic: int
    refunded_atomic: int
    locked_delta_atomic: int
    lifecycle: AccountComponentLifecycle
    # Attribution is explicit rather than reconstructed from a reason string.
    attribution_kind: LedgerCorrelationKind
    attribution_id: ContentDigest

    def __post_init__(self) -> None:
        # Reuse the requirement validator so result rows cannot invent invalid pairings.
        AccountRequirement(
            self.requirement_schema_id,
            self.scope,
            self.release_policy,
        )
        for name in (
            "maximum_reserved_atomic",
            "paid_atomic",
            "released_atomic",
            "refunded_atomic",
        ):
            _require_u64(name, getattr(self, name))

        # Locked delta is signed but must still fit the portable Int128 result encoding.
        if isinstance(self.locked_delta_atomic, bool) or not isinstance(
            self.locked_delta_atomic, int
        ):
            raise TypeError("locked_delta_atomic must be an integer")
        if not -(1 << 127) <= self.locked_delta_atomic < 1 << 127:
            raise ValueError("locked_delta_atomic must fit signed Int128")
        if not isinstance(self.lifecycle, AccountComponentLifecycle):
            raise TypeError("account component lifecycle must be resolved")

        # Every component in this schema is attributed to one immutable ledger owner.
        if not isinstance(self.attribution_kind, LedgerCorrelationKind):
            raise TypeError("account component attribution kind must be resolved")
        if not isinstance(self.attribution_id, ContentDigest):
            raise TypeError("account component attribution ID must be a ContentDigest")
        if self.paid_atomic + self.released_atomic > self.maximum_reserved_atomic:
            raise ValueError("account component consumes more than its reservation")
        if self.refunded_atomic > self.paid_atomic:
            raise ValueError("account component refund exceeds its paid deposit")

        # The final locked amount is exactly the paid deposit minus any close refund.
        if self.locked_delta_atomic != self.paid_atomic - self.refunded_atomic:
            raise ValueError("account component locked delta is inconsistent")
        self._validate_lifecycle_amounts()

    def _validate_lifecycle_amounts(self) -> None:
        # No account bytes or cashflow exist for a pre-submit rejection.
        if self.lifecycle is AccountComponentLifecycle.NOT_CREATED:
            if any((self.paid_atomic, self.released_atomic, self.refunded_atomic)):
                raise ValueError("an uncreated account cannot carry cashflows")
            return

        # Released reservations did not create an account and leave no locked value.
        if self.lifecycle is AccountComponentLifecycle.RESERVATION_RELEASED:
            if self.paid_atomic or self.refunded_atomic or self.locked_delta_atomic:
                raise ValueError("a released reservation cannot carry a deposit")
            if self.released_atomic != self.maximum_reserved_atomic:
                raise ValueError("a released reservation must release its full maximum")
            return

        # A prewarmed account has neither an in-run reservation nor cashflow.
        if self.lifecycle is AccountComponentLifecycle.PREWARMED:
            if any(
                (
                    self.maximum_reserved_atomic,
                    self.paid_atomic,
                    self.released_atomic,
                    self.refunded_atomic,
                    self.locked_delta_atomic,
                )
            ):
                raise ValueError("an existing account cannot duplicate lifecycle cashflow")
            return

        # An already-created UVA may release a conservative concurrent reservation.
        if self.lifecycle is AccountComponentLifecycle.EXISTING_RUN_LOCKED:
            if self.paid_atomic or self.refunded_atomic or self.locked_delta_atomic:
                raise ValueError("an existing account cannot duplicate lifecycle cashflow")
            if self.released_atomic != self.maximum_reserved_atomic:
                raise ValueError("an existing account must release any redundant reservation")
            return

        # Created accounts consume their full accepted reservation at successful landing.
        if self.lifecycle is AccountComponentLifecycle.CREATED_LOCKED:
            if self.paid_atomic <= 0 or self.paid_atomic != self.maximum_reserved_atomic:
                raise ValueError("a locked account must pay its full reserved deposit")
            if self.released_atomic or self.refunded_atomic:
                raise ValueError("a locked account cannot release or refund its deposit")
            return

        # A closed mint account returns exactly the deposit created by this round trip.
        if self.lifecycle is AccountComponentLifecycle.CLOSED_REFUNDED:
            if self.release_policy is not AccountReleasePolicy.CLOSE_ON_SUCCESSFUL_SELL:
                raise ValueError("a run-locked account cannot be closed by a sell")
            if self.paid_atomic <= 0 or self.paid_atomic != self.refunded_atomic:
                raise ValueError("a closed account must refund its complete paid deposit")
            if self.released_atomic or self.maximum_reserved_atomic != self.paid_atomic:
                raise ValueError("a closed account has inconsistent reservation amounts")

    def document(self) -> dict[str, object]:
        """Return a canonical integer-only nested result record."""

        return {
            "asset_id": self.asset_id.value,
            "attribution_id": self.attribution_id.hex,
            "attribution_kind": self.attribution_kind.value,
            "lifecycle": self.lifecycle.value,
            "locked_delta_atomic": self.locked_delta_atomic,
            # Reservation accounting remains explicit for redundant UVA reservations.
            "maximum_reserved_atomic": self.maximum_reserved_atomic,
            "paid_atomic": self.paid_atomic,
            "refunded_atomic": self.refunded_atomic,
            "release_policy": self.release_policy.value,
            "released_atomic": self.released_atomic,
            # Scope and schema are enough to interpret component ownership deterministically.
            "requirement_schema_id": self.requirement_schema_id,
            "scope": self.scope.value,
        }


def account_requirement_key(item: AccountRequirement) -> tuple[int, str, str]:
    """Order mint-scoped requirements before wallet-scoped requirements."""

    if not isinstance(item, AccountRequirement):
        raise TypeError("account requirement key requires AccountRequirement")
    scope_order = {
        AccountRequirementScope.MINT: 0,
        AccountRequirementScope.WALLET: 1,
    }
    return (
        scope_order[item.scope],
        item.requirement_schema_id,
        item.release_policy.value,
    )


def priced_account_requirement_key(
    item: PricedAccountRequirement,
) -> tuple[int, str, str, str]:
    """Extend protocol ordering with the explicit deposit asset."""

    if not isinstance(item, PricedAccountRequirement):
        raise TypeError("priced account requirement key requires PricedAccountRequirement")
    return (*account_requirement_key(item.requirement), item.asset_id.value)


def account_component_from_document(value: object) -> AccountComponentRecord:
    """Strictly decode a nested v3 account-component document."""

    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("account component must be an object")
    expected = {
        "asset_id",
        "attribution_id",
        "attribution_kind",
        "lifecycle",
        "locked_delta_atomic",
        "maximum_reserved_atomic",
        # Keep every accounting dimension closed; nullable/extra legacy fields are rejected.
        "paid_atomic",
        "refunded_atomic",
        "release_policy",
        "released_atomic",
        "requirement_schema_id",
        "scope",
    }
    if set(value) != expected:
        raise ValueError("account component schema is invalid")

    # Field constructors provide the exact enum/identifier validation contract.
    result = AccountComponentRecord(
        requirement_schema_id=_string(value["requirement_schema_id"], "requirement schema ID"),
        asset_id=AssetId(_string(value["asset_id"], "account deposit asset ID")),
        scope=AccountRequirementScope(_string(value["scope"], "account requirement scope")),
        release_policy=AccountReleasePolicy(
            _string(value["release_policy"], "account release policy")
        ),
        maximum_reserved_atomic=_integer(value["maximum_reserved_atomic"], "maximum reserved"),
        # Cashflow fields remain integers, including the signed locked delta.
        paid_atomic=_integer(value["paid_atomic"], "paid account deposit"),
        released_atomic=_integer(value["released_atomic"], "released reservation"),
        refunded_atomic=_integer(value["refunded_atomic"], "refunded account deposit"),
        locked_delta_atomic=_integer(value["locked_delta_atomic"], "locked account delta"),
        lifecycle=AccountComponentLifecycle(
            _string(value["lifecycle"], "account component lifecycle")
        ),
        attribution_kind=LedgerCorrelationKind(
            _string(value["attribution_kind"], "account attribution kind")
        ),
        attribution_id=ContentDigest(_string(value["attribution_id"], "account attribution ID")),
    )
    if result.document() != value:
        raise ValueError("account component does not round-trip exactly")
    return result


def _require_stable_name(name: str, value: str) -> None:
    # Stable names participate in identities and cannot contain transport surprises.
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise ValueError(f"{name} must be non-empty, trimmed and NUL-free")


def _require_u64(name: str, value: int, *, positive: bool = False) -> None:
    # Account prices originate as Solana UInt64 lamports.
    lower = 1 if positive else 0
    if isinstance(value, bool) or not isinstance(value, int) or not lower <= value < 1 << 64:
        raise ValueError(f"{name} must be an unsigned 64-bit integer >= {lower}")


def _string(value: object, field: str) -> str:
    # Decoder helpers reject coercion so canonical bytes have one interpretation.
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def _integer(value: object, field: str) -> int:
    # Boolean is an int subclass and must not enter atomic accounting.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


__all__ = [
    "AccountComponentLifecycle",
    "AccountComponentRecord",
    "AccountReleasePolicy",
    "AccountRequirement",
    "AccountRequirementScope",
    # Expose the priced bridge and strict nested decoder to engine/result adapters.
    "PricedAccountRequirement",
    "account_component_from_document",
    "account_requirement_key",
    "priced_account_requirement_key",
]
