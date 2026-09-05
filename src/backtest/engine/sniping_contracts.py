"""Core-owned ports and values for generic launchpad round-trip replay."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol, runtime_checkable

# Import chain at the visible module dependency boundary.
from backtest.domain.account_requirements import (
    AccountRequirement,
    PricedAccountRequirement,
    priced_account_requirement_key,
)
from backtest.domain.chain import ChainPosition
from backtest.domain.execution import ExecutionMode, Fill
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import (
    AccountId,
    AssetId,
    # Include bundle id so the identifiers dependency remains explicit.
    BundleId,
    ContentDigest,
    NetworkId,
    VenueId,
)
from backtest.domain.intents import RoundTripIntent

# Import ledger at the visible module dependency boundary.
from backtest.domain.ledger import LedgerTransaction
from backtest.domain.market_events import CanonicalEvent
from backtest.domain.roundtrips import RoundTripRecord

REAL_RESERVE_CAPPED_LIQUIDITY_POLICY_ID: Final = "real-reserve-capped-v1"
# Keep the synthetic policy core-owned so empty-result summaries need no plugin import.
VIRTUAL_RESERVE_EXPLICIT_SHORTFALL_LIQUIDITY_POLICY_ID: Final = (
    "virtual-reserve-output-with-explicit-synthetic-shortfall-v1"
)


def liquidity_policy_id_for_execution_mode(mode: ExecutionMode) -> str:
    """Resolve the closed Sniping mode to its identity-bearing liquidity policy."""

    if not isinstance(mode, ExecutionMode):
        raise TypeError("mode must be an ExecutionMode")
    if mode is ExecutionMode.EXOGENOUS_REPLAY:
        return REAL_RESERVE_CAPPED_LIQUIDITY_POLICY_ID
    if mode is ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT:
        return VIRTUAL_RESERVE_EXPLICIT_SHORTFALL_LIQUIDITY_POLICY_ID
    # Shadow/conditional replays are not admitted by this Sniping contract.
    raise ValueError("unsupported Pump.fun Sniping execution mode")


def synthetic_liquidity_account_id(
    *,
    protocol_namespace: str,
    network_id: NetworkId,
    venue_id: VenueId,
) -> AccountId:
    """Derive one versioned synthetic source without importing a protocol plugin."""

    # A canonical lowercase namespace prevents multiple spellings of one protocol.
    if not isinstance(protocol_namespace, str):
        raise TypeError("protocol_namespace must be a string")
    stable_namespace = protocol_namespace.replace("-", "")
    if (
        not protocol_namespace
        or protocol_namespace != protocol_namespace.lower()
        or not protocol_namespace.isascii()
        or not stable_namespace.isalnum()
    ):
        raise ValueError("protocol_namespace must be a lowercase ASCII token")

    # Network and venue are semantic operands, never endpoint or mutable aliases.
    if not isinstance(network_id, NetworkId):
        raise TypeError("network_id must be a NetworkId")
    if not isinstance(venue_id, VenueId):
        raise TypeError("venue_id must be a VenueId")
    digest = domain_digest(
        f"backtest.{protocol_namespace}-synthetic-liquidity-account.v1",
        {
            "network_id": network_id.value,
            "venue_id": venue_id.value,
        },
    )
    return AccountId(f"synthetic-liquidity:{protocol_namespace}:{digest.hex}")


# Keep the launch decision status contract and validation rules together.
class LaunchDecisionStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    COOLDOWN_SUPPRESSED = "COOLDOWN_SUPPRESSED"


# Keep the protocol quote side contract and validation rules together.
class ProtocolQuoteSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


# Keep the protocol contract error code contract and validation rules together.
class ProtocolContractErrorCode(StrEnum):
    UNSUPPORTED_PAYLOAD_SCHEMA = "UNSUPPORTED_PAYLOAD_SCHEMA"
    UNSUPPORTED_PROTOCOL_VERSION = "UNSUPPORTED_PROTOCOL_VERSION"
    UNKNOWN_PROGRAM_MODE = "UNKNOWN_PROGRAM_MODE"
    EXCLUDED_PROGRAM_MODE = "EXCLUDED_PROGRAM_MODE"
    UNKNOWN_LIFECYCLE = "UNKNOWN_LIFECYCLE"
    # Declare non supported quote asset explicitly in the protocol contract error code
    # contract.
    NON_SUPPORTED_QUOTE_ASSET = "NON_SUPPORTED_QUOTE_ASSET"
    MALFORMED_PROTOCOL_PAYLOAD = "MALFORMED_PROTOCOL_PAYLOAD"
    UNKNOWN_VENUE = "UNKNOWN_VENUE"
    INCONSISTENT_VENUE_IDENTITY = "INCONSISTENT_VENUE_IDENTITY"
    PROFILE_NOT_EFFECTIVE = "PROFILE_NOT_EFFECTIVE"


# Keep the protocol contract error contract and validation rules together.
class ProtocolContractError(RuntimeError):
    """A protocol payload/config cannot be interpreted without approximation."""

    def __init__(self, code: ProtocolContractErrorCode) -> None:
        # Execute the protocol contract error init workflow in explicit, reviewable steps.
        if not isinstance(code, ProtocolContractErrorCode):
            raise TypeError("code must be a ProtocolContractErrorCode")
        self.code = code
        super().__init__(code.value)


class ProtocolExecutionRejected(ValueError):
    """Expected original-venue program rejection at decision or landing."""

    def __init__(self, code: str) -> None:
        # Execute the protocol execution rejected init workflow in explicit, reviewable
        # steps.
        if (
            not isinstance(code, str)
            or not code
            or code != code.strip()
            or not code.replace("_", "").isalnum()
            # Evaluate the complete protocol execution rejected init code, isinstance and
            # strip condition before guarded effects.
        ):
            raise ValueError("execution rejection code must be a stable token")
        self.code = code
        super().__init__(code)


class NetworkCostContractError(RuntimeError):
    """Resolved network fee/account profile cannot price an execution."""

    def __init__(self, code: str) -> None:
        # Execute the network cost contract error init workflow in explicit, reviewable
        # steps.
        if (
            not isinstance(code, str)
            or not code
            or code != code.strip()
            or not code.replace("_", "").isalnum()
            # Evaluate the complete network cost contract error init code, isinstance and
            # strip condition before guarded effects.
        ):
            raise ValueError("network cost error code must be a stable token")
        self.code = code
        super().__init__(code)


# Keep the launch target contract and validation rules together.
@dataclass(frozen=True, slots=True)
class LaunchTarget:
    target_event_id: ContentDigest
    position: ChainPosition
    asset_id: AssetId
    # Declare developer id explicitly in the launch target contract.
    developer_id: AccountId
    creation_user_id: AccountId
    venue_id: VenueId
    quote_asset_id: AssetId


# Keep the launch decision contract and validation rules together.
@dataclass(frozen=True, slots=True)
class LaunchDecision:
    roundtrip_id: ContentDigest
    status: LaunchDecisionStatus
    cooldown_until_ns: int | None
    # Declare intent explicitly in the launch decision contract.
    intent: RoundTripIntent | None

    def __post_init__(self) -> None:
        # Execute the launch decision post init workflow in explicit, reviewable steps.
        if not isinstance(self.status, LaunchDecisionStatus):
            raise TypeError("status must be a LaunchDecisionStatus")
        if (self.status is LaunchDecisionStatus.ELIGIBLE) is (self.intent is None):
            raise ValueError("only an eligible decision carries an intent")
        if self.cooldown_until_ns is not None and (
            # Keep isinstance visible while evaluating the cooldown until ns and
            # isinstance guard.
            isinstance(self.cooldown_until_ns, bool)
            or not isinstance(self.cooldown_until_ns, int)
            or self.cooldown_until_ns < 0
        ):
            raise ValueError("cooldown_until_ns must be non-negative or None")


# Keep causal venue-liquidity evidence separate from protocol-specific math.
@dataclass(frozen=True, slots=True)
class ProtocolLiquidityEvidence:
    """Exact sell-funding evidence carried from quote through settlement."""

    policy_id: str
    asset_id: AssetId
    required_output_atomic: int
    # Preserve the full observed venue reserve, not only the funded portion.
    observed_available_output_atomic: int
    synthetic_shortfall_atomic: int
    synthetic_source_account_id: AccountId | None

    def __post_init__(self) -> None:
        # Policy IDs are persisted semantic values, so reject ambiguous spellings.
        if not isinstance(self.policy_id, str):
            raise TypeError("liquidity policy ID must be a string")
        if not self.policy_id or self.policy_id != self.policy_id.strip():
            raise ValueError("liquidity policy ID must be non-empty and trimmed")
        if len(self.policy_id) > 128 or any(
            ord(character) < 32 or ord(character) > 126 for character in self.policy_id
        ):
            raise ValueError("liquidity policy ID must be printable ASCII up to 128 characters")

        # Evidence is asset-tagged so the engine never assumes the quote currency.
        if not isinstance(self.asset_id, AssetId):
            raise TypeError("liquidity evidence asset_id must be an AssetId")
        for field_name in (
            "required_output_atomic",
            "observed_available_output_atomic",
            "synthetic_shortfall_atomic",
        ):
            value = getattr(self, field_name)
            # Boolean values are not valid integer atomic amounts.
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.required_output_atomic <= 0:
            raise ValueError("required liquidity output must be positive")

        # A shortfall is mathematical evidence, never a discretionary adjustment.
        expected_shortfall = max(
            0,
            self.required_output_atomic - self.observed_available_output_atomic,
        )
        if self.synthetic_shortfall_atomic != expected_shortfall:
            raise ValueError("synthetic shortfall is inconsistent with observed liquidity")

        # A funding account exists exactly when a synthetic debit can be posted.
        if self.synthetic_shortfall_atomic > 0:
            if not isinstance(self.synthetic_source_account_id, AccountId):
                raise TypeError("positive synthetic shortfall requires an AccountId source")
        elif self.synthetic_source_account_id is not None:
            raise ValueError("zero synthetic shortfall must not carry a source account")


# Apply dataclass semantics to the following protocol quote contract.
@dataclass(frozen=True, slots=True)
class ProtocolQuote:
    """Launchpad-neutral exact quote with separately routed component fees."""

    side: ProtocolQuoteSide
    input_asset_id: AssetId
    output_asset_id: AssetId
    amount_in_atomic: int
    amount_out_atomic: int
    # Declare venue input atomic explicitly in the protocol quote contract.
    venue_input_atomic: int
    venue_output_atomic: int
    protocol_fee_atomic: int
    creator_fee_atomic: int
    cashback_receivable_atomic: int
    # Declare protocol fee account id explicitly in the protocol quote contract.
    protocol_fee_account_id: AccountId
    creator_fee_account_id: AccountId
    cashback_source_account_id: AccountId
    # Liquidity evidence is sell-only and remains launchpad-neutral.
    liquidity_evidence: ProtocolLiquidityEvidence | None = None

    def __post_init__(self) -> None:
        # Execute the protocol quote post init workflow in explicit, reviewable steps.
        if not isinstance(self.side, ProtocolQuoteSide):
            raise TypeError("side must be a ProtocolQuoteSide")
        if self.input_asset_id == self.output_asset_id:
            raise ValueError("protocol quote assets must differ")
        for field_name in (
            # Traverse amount in atomic, amount out atomic and venue input atomic
            # explicitly so each protocol quote post init iteration remains traceable.
            "amount_in_atomic",
            "amount_out_atomic",
            "venue_input_atomic",
            "venue_output_atomic",
            "protocol_fee_atomic",
            # Traverse amount in atomic, amount out atomic and venue input atomic
            # explicitly so each protocol quote post init iteration remains traceable.
            "creator_fee_atomic",
            "cashback_receivable_atomic",
        ):
            # Process amount in atomic, amount out atomic and venue input atomic inside
            # the bounded protocol quote post init loop.
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.amount_in_atomic <= 0 or self.amount_out_atomic <= 0:
            raise ValueError("protocol quote input/output must be positive")
        # Evaluate the complete protocol quote post init cashback receivable atomic and
        # creator fee atomic condition before guarded effects.
        if self.cashback_receivable_atomic not in {0, self.creator_fee_atomic}:
            raise ValueError("cashback receivable must be zero or the creator fee")
        if self.side is ProtocolQuoteSide.BUY:
            # Handle the protocol quote post init self.side is ProtocolQuoteSide.BUY
            # branch as a distinct logical block.
            if self.amount_in_atomic != (
                self.venue_input_atomic + self.protocol_fee_atomic + self.creator_fee_atomic
            ):
                raise ValueError("buy gross input does not conserve fee components")
            if self.venue_output_atomic != self.amount_out_atomic:
                # Fail the protocol quote post init path with ValueError for buy venue
                # output must equal token output when venue output atomic and amount out
                # atomic is true; do not continue ambiguously.
                raise ValueError("buy venue output must equal token output")
            if self.liquidity_evidence is not None:
                raise ValueError("buy quote must not carry sell-liquidity evidence")
        else:
            # Handle the protocol quote post init complement of self.side is
            # ProtocolQuoteSide.BUY explicitly.
            if self.venue_input_atomic != self.amount_in_atomic:
                raise ValueError("sell venue input must equal sold token amount")
            if self.venue_output_atomic != (
                self.amount_out_atomic + self.protocol_fee_atomic + self.creator_fee_atomic
            ):
                # Fail the protocol quote post init path with ValueError for sell gross
                # output does not conserve fee components when venue output atomic,
                # creator fee atomic and amount out atomic is true; do not continue
                # ambiguously.
                raise ValueError("sell gross output does not conserve fee components")
            # Every sell quote must prove how its gross output relates to venue liquidity.
            evidence = self.liquidity_evidence
            if not isinstance(evidence, ProtocolLiquidityEvidence):
                raise TypeError("sell quote requires ProtocolLiquidityEvidence")
            if evidence.asset_id != self.output_asset_id:
                raise ValueError("sell-liquidity evidence uses the wrong output asset")
            if evidence.required_output_atomic != self.venue_output_atomic:
                raise ValueError("sell-liquidity evidence must cover the gross venue output")


# Keep the network cost quote contract and validation rules together.
@dataclass(frozen=True, slots=True)
class NetworkCostQuote:
    fee_asset_id: AssetId
    base_fee_atomic: int
    # Declare priority fee atomic explicitly in the network cost quote contract.
    priority_fee_atomic: int
    account_requirements: tuple[PricedAccountRequirement, ...] = ()

    def __post_init__(self) -> None:
        # Execute the network cost quote post init workflow in explicit, reviewable steps.
        if not isinstance(self.fee_asset_id, AssetId):
            raise TypeError("fee_asset_id must be an AssetId")
        for field_name in (
            # Traverse base fee atomic, priority fee atomic and required account deposit
            # atomic explicitly so each network cost quote post init iteration remains
            # traceable.
            "base_fee_atomic",
            "priority_fee_atomic",
        ):
            # Process base fee atomic, priority fee atomic and required account deposit
            # atomic inside the bounded network cost quote post init loop.
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if not isinstance(self.account_requirements, tuple) or not all(
            isinstance(item, PricedAccountRequirement) for item in self.account_requirements
        ):
            raise TypeError("account requirements must be a canonical priced tuple")
        if self.account_requirements != tuple(
            sorted(self.account_requirements, key=priced_account_requirement_key)
        ):
            raise ValueError("account requirements must be canonically sorted")

    # Apply property semantics to the following network cost quote transaction fee atomic
    # contract.
    @property
    def transaction_fee_atomic(self) -> int:
        return self.base_fee_atomic + self.priority_fee_atomic


# Keep the valuation quote contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ValuationQuote:
    quote: ProtocolQuote
    stale_pre_migration: bool


# Keep the sniping strategy instance contract and validation rules together.
@runtime_checkable
class SnipingStrategyInstance(Protocol):
    @property
    def bundle_id(self) -> BundleId: ...

    @property
    # Define sniping strategy instance component id as one focused operation with an
    # explicit boundary.
    def component_id(self) -> ContentDigest: ...

    @property
    def buy_delay_transactions(self) -> int: ...

    @property
    def sell_decision_delay_ns(self) -> int: ...

    # Apply property semantics to the following sniping strategy instance sell delay
    # transactions contract.
    @property
    def sell_delay_transactions(self) -> int: ...

    def decide(self, target: LaunchTarget, *, decision_time_ns: int) -> LaunchDecision: ...


# Keep the sniping protocol runtime contract and validation rules together.
@runtime_checkable
class SnipingProtocolRuntime(Protocol):
    @property
    def bundle_id(self) -> BundleId: ...

    def apply_historical_group(
        # Keep the remaining apply historical group inputs visible at the sniping protocol
        # runtime apply historical group boundary.
        self,
        events: tuple[CanonicalEvent, ...],
        *,
        effective_at_unix_s: int,
    ) -> tuple[LaunchTarget, ...]: ...

    # Define sniping protocol runtime quote buy as one focused operation with an explicit
    # boundary.
    def quote_buy(self, intent: RoundTripIntent, *, effective_at_unix_s: int) -> ProtocolQuote: ...

    def account_requirements(
        self,
        intent: RoundTripIntent,
    ) -> tuple[AccountRequirement, ...]: ...

    def quote_sell(
        self,
        intent: RoundTripIntent,
        *,
        # Keep the tokens in atomic input explicit in the quote sell contract.
        tokens_in_atomic: int,
        effective_at_unix_s: int,
    ) -> ProtocolQuote: ...

    def valuation_quote(
        self,
        # Keep the intent input explicit in the valuation quote contract.
        intent: RoundTripIntent,
        *,
        tokens_in_atomic: int,
        effective_at_unix_s: int,
    ) -> ValuationQuote | None: ...


# Keep the sniping network cost model contract and validation rules together.
@runtime_checkable
class SnipingNetworkCostModel(Protocol):
    @property
    def bundle_id(self) -> BundleId: ...

    @property
    # Define sniping network cost model fee collector account id as one focused operation
    # with an explicit boundary.
    def fee_collector_account_id(self) -> AccountId: ...

    def quote_buy(
        self,
        *,
        effective_at_unix_s: int,
        requirements: tuple[AccountRequirement, ...],
    ) -> NetworkCostQuote: ...

    def quote_sell(self, *, effective_at_unix_s: int) -> NetworkCostQuote: ...


# Keep the sniping run event sink contract and validation rules together.
@runtime_checkable
class SnipingRunEventSink(Protocol):
    def append_audit(self, record: dict[str, object]) -> None: ...

    def append_ledger(self, transaction: LedgerTransaction) -> None: ...

    def append_fill(self, fill: Fill) -> None: ...

    # Define sniping run event sink append roundtrip as one focused operation with an
    # explicit boundary.
    def append_roundtrip(self, record: RoundTripRecord) -> None: ...


def ensure_single_launch(
    launches: Iterable[LaunchTarget],
) -> tuple[LaunchTarget, ...]:
    """Canonicalize a plugin iterable without hiding duplicate target IDs."""

    values = tuple(launches)
    identities = tuple(value.target_event_id for value in values)
    if len(identities) != len(set(identities)):
        raise ProtocolContractError(ProtocolContractErrorCode.INCONSISTENT_VENUE_IDENTITY)
    return tuple(
        # Include sorted in the completed ensure single launch result.
        sorted(
            values,
            key=lambda value: (
                value.position.boundary_ordinal,
                -1 if value.position.event_index is None else value.position.event_index,
                # Pass value explicitly so sorted receives a reviewable boundary ordinal
                # and hex input in ensure single launch.
                value.target_event_id.hex,
            ),
        )
    )


__all__ = [
    "REAL_RESERVE_CAPPED_LIQUIDITY_POLICY_ID",
    "VIRTUAL_RESERVE_EXPLICIT_SHORTFALL_LIQUIDITY_POLICY_ID",
    # Keep the launch decision component named inside the all contract.
    "LaunchDecision",
    "LaunchDecisionStatus",
    "LaunchTarget",
    "NetworkCostContractError",
    "NetworkCostQuote",
    # Keep the protocol contract error component named inside the all contract.
    "ProtocolContractError",
    "ProtocolContractErrorCode",
    "ProtocolExecutionRejected",
    "ProtocolLiquidityEvidence",
    "ProtocolQuote",
    "ProtocolQuoteSide",
    # Keep the sniping network cost model component named inside the all contract.
    "SnipingNetworkCostModel",
    "SnipingProtocolRuntime",
    "SnipingRunEventSink",
    "SnipingStrategyInstance",
    "ValuationQuote",
    "ensure_single_launch",
    "liquidity_policy_id_for_execution_mode",
    "synthetic_liquidity_account_id",
]
