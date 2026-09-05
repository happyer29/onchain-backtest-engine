"""Canonical round-trip result values independent of storage adapters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from backtest.domain.account_requirements import (
    AccountComponentLifecycle,
    AccountComponentRecord,
    AccountRequirementScope,
    account_component_from_document,
)
from backtest.domain.chain import ChainPosition
from backtest.domain.execution import ExecutionMode

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import (
    AccountId,
    AssetId,
    ContentDigest,
    NetworkId,
    # Include position schema id so the identifiers dependency remains explicit.
    PositionSchemaId,
    VenueId,
)


# Keep the round trip status contract and validation rules together.
class RoundTripStatus(StrEnum):
    COOLDOWN_SKIPPED = "COOLDOWN_SKIPPED"
    BUY_REFERENCE_REJECTED = "BUY_REFERENCE_REJECTED"
    BUY_PRE_SUBMIT_INSUFFICIENT_FUNDS = "BUY_PRE_SUBMIT_INSUFFICIENT_FUNDS"
    BUY_LANDED_FAILED = "BUY_LANDED_FAILED"
    # Declare sell reference unavailable open explicitly in the round trip status
    # contract.
    SELL_REFERENCE_UNAVAILABLE_OPEN = "SELL_REFERENCE_UNAVAILABLE_OPEN"
    SELL_PRE_SUBMIT_INSUFFICIENT_FUNDS_OPEN = "SELL_PRE_SUBMIT_INSUFFICIENT_FUNDS_OPEN"
    SELL_LANDED_FAILED_OPEN = "SELL_LANDED_FAILED_OPEN"
    OPEN_AT_HORIZON = "OPEN_AT_HORIZON"
    CLOSED = "CLOSED"


# Keep the round trip leg side contract and validation rules together.
class RoundTripLegSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


# Keep the mtm status contract and validation rules together.
class MtmStatus(StrEnum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    EXECUTABLE = "EXECUTABLE"
    STALE_PRE_MIGRATION = "STALE_PRE_MIGRATION"
    UNAVAILABLE = "UNAVAILABLE"


# Keep storage schema IDs beside the strict codec that understands both generations.
ROUNDTRIP_RESULT_SCHEMA_V3 = "pumpfun-roundtrips/v3"
ROUNDTRIP_RESULT_SCHEMA_V4 = "pumpfun-roundtrips/v4"


@dataclass(frozen=True, slots=True)
class QuoteLiquidityEvidenceRecord:
    """Exact sell-output funding evidence at one causal quote boundary."""

    policy_id: str
    asset_id: AssetId
    required_output_atomic: int
    observed_available_output_atomic: int
    synthetic_shortfall_atomic: int

    def __post_init__(self) -> None:
        """Reject lossy or internally inconsistent liquidity evidence."""

        _require_nonempty_trimmed("liquidity policy ID", self.policy_id)
        if not isinstance(self.asset_id, AssetId):
            raise TypeError("liquidity asset_id must be an AssetId")

        # Atomic values remain exact integers even when observed liquidity exceeds need.
        for field_name in (
            "required_output_atomic",
            "observed_available_output_atomic",
            "synthetic_shortfall_atomic",
        ):
            _require_non_negative_integer(field_name, getattr(self, field_name))
        if self.required_output_atomic == 0:
            raise ValueError("liquidity required output must be positive")

        # The recorded shortfall is derived, never supplied as an approximation.
        expected = max(0, self.required_output_atomic - self.observed_available_output_atomic)
        if self.synthetic_shortfall_atomic != expected:
            raise ValueError("synthetic shortfall differs from required-observed liquidity")

    def document(self) -> dict[str, object]:
        """Return the canonical integer-only storage projection."""

        return {
            "asset_id": self.asset_id.value,
            "observed_available_output_atomic": self.observed_available_output_atomic,
            "policy_id": self.policy_id,
            "required_output_atomic": self.required_output_atomic,
            "synthetic_shortfall_atomic": self.synthetic_shortfall_atomic,
        }


@dataclass(frozen=True, slots=True)
# Keep the round trip leg record contract and validation rules together.
class RoundTripLegRecord:
    """Exact decision/landing quote and fee evidence for one side."""

    side: RoundTripLegSide
    decision_position: ChainPosition
    landing_position: ChainPosition | None
    amount_in_atomic: int | None
    reference_out_atomic: int
    # Declare landing out atomic explicitly in the round trip leg record contract.
    landing_out_atomic: int | None
    minimum_out_atomic: int
    signed_slippage_atomic: int | None
    protocol_fee_atomic: int
    creator_fee_atomic: int
    # Declare network base fee atomic explicitly in the round trip leg record contract.
    network_base_fee_atomic: int
    network_priority_fee_atomic: int
    failure_code: str | None = None

    def __post_init__(self) -> None:
        # Execute the round trip leg record post init workflow in explicit, reviewable
        # steps.
        if not isinstance(self.side, RoundTripLegSide):
            raise TypeError("side must be a RoundTripLegSide")
        if self.landing_position is not None:
            # Handle the round trip leg record post init self.landing_position is not None
            # branch as a distinct logical block.
            self.decision_position.require_same_chain(self.landing_position)
            if self.landing_position.boundary_ordinal <= self.decision_position.boundary_ordinal:
                raise ValueError("leg landing must be strictly after its decision")
        for field_name in (
            "reference_out_atomic",
            # Traverse reference out atomic, minimum out atomic and protocol fee atomic
            # explicitly so each round trip leg record post init iteration remains
            # traceable.
            "minimum_out_atomic",
            "protocol_fee_atomic",
            "creator_fee_atomic",
            "network_base_fee_atomic",
            "network_priority_fee_atomic",
            # Traverse reference out atomic, minimum out atomic and protocol fee atomic
            # explicitly so each round trip leg record post init iteration remains traceable.
        ):
            _require_non_negative_integer(field_name, getattr(self, field_name))
        for field_name in ("amount_in_atomic", "landing_out_atomic"):
            # Process amount in atomic and landing out atomic inside the bounded round
            # trip leg record post init loop.
            value = getattr(self, field_name)
            if value is not None:
                _require_non_negative_integer(field_name, value)
        if self.signed_slippage_atomic is not None:
            # Handle the round trip leg record post init signed slippage atomic condition
            # as a distinct block.
            if isinstance(self.signed_slippage_atomic, bool) or not isinstance(
                self.signed_slippage_atomic, int
            ):
                raise TypeError("signed_slippage_atomic must be an integer or None")
            if self.landing_out_atomic is None:
                # Fail the round trip leg record post init path with ValueError for signed
                # slippage requires a landing output when landing out atomic is true; do
                # not continue ambiguously.
                raise ValueError("signed slippage requires a landing output")
            if self.signed_slippage_atomic != (self.landing_out_atomic - self.reference_out_atomic):
                raise ValueError("signed slippage does not match landing-reference")
        if self.failure_code is not None:
            _require_stable_token("failure_code", self.failure_code)

    # Define round trip leg record document as one focused operation with an explicit
    # boundary.
    def document(self) -> dict[str, object]:
        # Execute the round trip leg record document workflow in explicit, reviewable
        # steps.
        return {
            "amount_in_atomic": self.amount_in_atomic,
            "creator_fee_atomic": self.creator_fee_atomic,
            "decision_position": _position_document(self.decision_position),
            "failure_code": self.failure_code,
            # Include landing out atomic in the completed round trip leg record document
            # result.
            "landing_out_atomic": self.landing_out_atomic,
            "landing_position": (
                None if self.landing_position is None else _position_document(self.landing_position)
            ),
            "minimum_out_atomic": self.minimum_out_atomic,
            # Include network base fee atomic in the completed round trip leg record
            # document result.
            "network_base_fee_atomic": self.network_base_fee_atomic,
            "network_priority_fee_atomic": self.network_priority_fee_atomic,
            "protocol_fee_atomic": self.protocol_fee_atomic,
            "reference_out_atomic": self.reference_out_atomic,
            "side": self.side.value,
            # Include signed slippage atomic in the completed round trip leg record
            # document result.
            "signed_slippage_atomic": self.signed_slippage_atomic,
        }


@dataclass(frozen=True, slots=True)
class RoundTripRecord:
    """One target's complete deterministic lifecycle and valuation record."""

    roundtrip_id: ContentDigest
    network_id: NetworkId
    position_schema_id: PositionSchemaId
    target_event_id: ContentDigest
    target_position: ChainPosition
    # Declare target time ns explicitly in the round trip record contract.
    target_time_ns: int
    developer_id: AccountId
    creation_user_id: AccountId
    asset_id: AssetId
    quote_asset_id: AssetId
    # Declare venue id explicitly in the round trip record contract.
    venue_id: VenueId
    cooldown_consumed: bool
    cooldown_until_ns: int | None
    status: RoundTripStatus
    buy: RoundTripLegRecord | None
    # Declare sell explicitly in the round trip record contract.
    sell: RoundTripLegRecord | None
    acquired_token_amount_atomic: int
    cashback_receivable_atomic: int
    realized_cash_pnl_atomic: int | None
    # Declare mtm status explicitly in the round trip record contract.
    mtm_status: MtmStatus
    mtm_liquidation_value_atomic: int | None
    mtm_cash_pnl_atomic: int | None
    economic_pnl_atomic: int | None
    account_profile_id: str
    account_components: tuple[AccountComponentRecord, ...]
    # V4 keeps the execution assumption and every liquidity observation explicit.
    execution_mode: ExecutionMode = ExecutionMode.EXOGENOUS_REPLAY
    sell_reference_liquidity: QuoteLiquidityEvidenceRecord | None = None
    sell_landing_liquidity: QuoteLiquidityEvidenceRecord | None = None
    mtm_liquidity: QuoteLiquidityEvidenceRecord | None = None
    # Settlement values describe used funding, not a potential quote shortfall.
    settled_venue_funded_atomic: int = 0
    settled_synthetic_funded_atomic: int = 0
    source_schema_id: str = ROUNDTRIP_RESULT_SCHEMA_V4

    def __post_init__(self) -> None:
        # Execute the round trip record post init workflow in explicit, reviewable steps.
        if (
            self.target_position.network_id != self.network_id
            or self.target_position.position_schema_id != self.position_schema_id
        ):
            raise ValueError("target position does not match round-trip chain identity")
        # Guard this path with self.asset_id == self.quote_asset_id before applying
        # effects.
        if self.asset_id == self.quote_asset_id:
            raise ValueError("round-trip assets must differ")
        _require_non_negative_integer("target_time_ns", self.target_time_ns)
        if not isinstance(self.cooldown_consumed, bool):
            raise TypeError("cooldown_consumed must be a boolean")
        # Guard this path with self.cooldown_until_ns is not None before applying effects.
        if self.cooldown_until_ns is not None:
            # Handle the round trip record post init self.cooldown_until_ns is not None
            # branch as a distinct logical block.
            _require_non_negative_integer("cooldown_until_ns", self.cooldown_until_ns)
            if self.cooldown_until_ns <= self.target_time_ns:
                raise ValueError("cooldown expiry must be after target time")
        if not isinstance(self.status, RoundTripStatus):
            raise TypeError("status must be a RoundTripStatus")
        # Evaluate the complete round trip record post init isinstance and mtm status
        # condition before guarded effects.
        if not isinstance(self.mtm_status, MtmStatus):
            raise TypeError("mtm_status must be an MtmStatus")
        if not isinstance(self.execution_mode, ExecutionMode):
            raise TypeError("execution_mode must be an ExecutionMode")
        if self.source_schema_id not in {
            ROUNDTRIP_RESULT_SCHEMA_V3,
            ROUNDTRIP_RESULT_SCHEMA_V4,
        }:
            raise ValueError("unsupported round-trip source schema")
        _require_nonempty_trimmed("account_profile_id", self.account_profile_id)
        if not isinstance(self.account_components, tuple) or not all(
            isinstance(item, AccountComponentRecord) for item in self.account_components
        ):
            raise TypeError("account_components must be a canonical component tuple")
        component_keys = tuple(_account_component_key(item) for item in self.account_components)
        if component_keys != tuple(sorted(component_keys)):
            raise ValueError("account components must be canonically ordered")
        if len(component_keys) != len(set(component_keys)):
            raise ValueError("account components must be unique")
        for leg in (self.buy, self.sell):
            # Process (self.buy, self.sell) inside the bounded round trip record post init
            # loop.
            if leg is not None:
                self.target_position.require_same_chain(leg.decision_position)
        for field_name in ("acquired_token_amount_atomic", "cashback_receivable_atomic"):
            _require_non_negative_integer(field_name, getattr(self, field_name))

        # Suppressed launches never reached protocol/account requirement resolution.
        mint_components = tuple(
            item for item in self.account_components if item.scope is AccountRequirementScope.MINT
        )
        wallet_components = tuple(
            item for item in self.account_components if item.scope is AccountRequirementScope.WALLET
        )
        if self.cooldown_consumed and (len(mint_components) != 1 or len(wallet_components) != 1):
            raise ValueError("a consumed target must record one mint and one wallet requirement")
        if not self.cooldown_consumed and self.account_components:
            raise ValueError("a suppressed target cannot carry account requirements")
        created_lifecycles = {
            AccountComponentLifecycle.CREATED_LOCKED,
            AccountComponentLifecycle.CLOSED_REFUNDED,
        }
        if self.acquired_token_amount_atomic > 0 and not any(
            item.lifecycle in created_lifecycles for item in mint_components
        ):
            raise ValueError("acquired tokens require a successfully created mint account")
        if (
            any(
                item.lifecycle is AccountComponentLifecycle.CLOSED_REFUNDED
                for item in mint_components
            )
            and self.status is not RoundTripStatus.CLOSED
        ):
            raise ValueError("a refunded mint account requires a closed round trip")
        for field_name in (
            # Traverse realized cash pnl atomic, mtm liquidation value atomic and mtm cash
            # pnl atomic explicitly so each round trip record post init iteration remains
            # traceable.
            "realized_cash_pnl_atomic",
            "mtm_liquidation_value_atomic",
            "mtm_cash_pnl_atomic",
            "economic_pnl_atomic",
        ):
            # Process realized cash pnl atomic, mtm liquidation value atomic and mtm cash
            # pnl atomic inside the bounded round trip record post init loop.
            value = getattr(self, field_name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
                raise TypeError(f"{field_name} must be an integer or None")
        if self.mtm_status is MtmStatus.NOT_APPLICABLE and any(
            value is not None
            # Pass value explicitly so any receives a reviewable mtm liquidation value
            # atomic and mtm cash pnl atomic input in round trip record post init.
            for value in (
                self.mtm_liquidation_value_atomic,
                self.mtm_cash_pnl_atomic,
            )
        ):
            # Fail the round trip record post init path with ValueError for not-applicable
            # mtm cannot carry valuation amounts when mtm status, not applicable and value
            # is true; do not continue ambiguously.
            raise ValueError("not-applicable MTM cannot carry valuation amounts")

        # Liquidity evidence must use the round trip's quote asset and one policy.
        liquidity_values = tuple(
            item
            for item in (
                self.sell_reference_liquidity,
                self.sell_landing_liquidity,
                self.mtm_liquidity,
            )
            if item is not None
        )
        if not all(isinstance(item, QuoteLiquidityEvidenceRecord) for item in liquidity_values):
            raise TypeError("liquidity evidence must use QuoteLiquidityEvidenceRecord")
        if any(item.asset_id != self.quote_asset_id for item in liquidity_values):
            raise ValueError("liquidity evidence asset differs from the quote asset")

        # A single round trip cannot silently mix settlement policies across boundaries.
        policy_ids = {item.policy_id for item in liquidity_values}
        if len(policy_ids) > 1:
            raise ValueError("round-trip liquidity evidence mixes settlement policies")
        self._validate_settled_liquidity()
        if self.source_schema_id == ROUNDTRIP_RESULT_SCHEMA_V3:
            self._validate_legacy_v3_projection()

    def _validate_legacy_v3_projection(self) -> None:
        """Allow only the compatibility values uniquely implied by old row bytes."""

        if self.execution_mode is not ExecutionMode.EXOGENOUS_REPLAY:
            raise ValueError("legacy round trips require strict exogenous replay")
        if any(
            item is not None
            for item in (
                self.sell_reference_liquidity,
                self.sell_landing_liquidity,
                self.mtm_liquidity,
            )
        ):
            raise ValueError("legacy round trips cannot invent liquidity evidence")
        if self.settled_venue_funded_atomic or self.settled_synthetic_funded_atomic:
            raise ValueError("legacy round trips cannot invent settlement funding")

    def _validate_settled_liquidity(self) -> None:
        """Constrain actual synthetic funding to one successful sell landing."""

        _require_non_negative_integer(
            "settled_venue_funded_atomic", self.settled_venue_funded_atomic
        )
        _require_non_negative_integer(
            "settled_synthetic_funded_atomic", self.settled_synthetic_funded_atomic
        )

        # A closed sell is the only lifecycle state allowed to consume output funding.
        successful_sell = (
            self.status is RoundTripStatus.CLOSED
            and self.sell is not None
            and self.sell.failure_code is None
            and self.sell.landing_position is not None
        )
        settled_total = self.settled_venue_funded_atomic + self.settled_synthetic_funded_atomic
        if settled_total and not successful_sell:
            raise ValueError("only a successful closed sell may use settlement funding")

        # Whenever settlement evidence is present, the exact landing split is mandatory.
        evidence = self.sell_landing_liquidity
        if not successful_sell or evidence is None:
            return
        expected_synthetic = evidence.synthetic_shortfall_atomic
        expected_venue = evidence.required_output_atomic - expected_synthetic
        if self.settled_synthetic_funded_atomic != expected_synthetic:
            raise ValueError("settled synthetic funding differs from landing shortfall")
        if self.settled_venue_funded_atomic != expected_venue:
            raise ValueError("settled venue funding differs from landing available output")

    def document(self) -> dict[str, object]:
        """Return the canonical storage/hash projection without floats or paths."""

        document = {
            "acquired_token_amount_atomic": self.acquired_token_amount_atomic,
            "account_components": [item.document() for item in self.account_components],
            "account_profile_id": self.account_profile_id,
            # Include asset id in the completed round trip record document result.
            "asset_id": self.asset_id.value,
            "buy": None if self.buy is None else self.buy.document(),
            "cashback_receivable_atomic": self.cashback_receivable_atomic,
            "cooldown_consumed": self.cooldown_consumed,
            "cooldown_until_ns": self.cooldown_until_ns,
            # Include creation user id in the completed round trip record document result.
            "creation_user_id": self.creation_user_id.value,
            "developer_id": self.developer_id.value,
            "economic_pnl_atomic": self.economic_pnl_atomic,
            "execution_mode": self.execution_mode.value,
            "mtm_liquidity": _liquidity_document(self.mtm_liquidity),
            "mtm_cash_pnl_atomic": self.mtm_cash_pnl_atomic,
            "mtm_liquidation_value_atomic": self.mtm_liquidation_value_atomic,
            # Include mtm status in the completed round trip record document result.
            "mtm_status": self.mtm_status.value,
            "network_id": self.network_id.value,
            "position_schema_id": self.position_schema_id.value,
            "quote_asset_id": self.quote_asset_id.value,
            "realized_cash_pnl_atomic": self.realized_cash_pnl_atomic,
            "roundtrip_id": self.roundtrip_id.hex,
            "sell": None if self.sell is None else self.sell.document(),
            "sell_landing_liquidity": _liquidity_document(self.sell_landing_liquidity),
            "sell_reference_liquidity": _liquidity_document(self.sell_reference_liquidity),
            "settled_synthetic_funded_atomic": self.settled_synthetic_funded_atomic,
            "settled_venue_funded_atomic": self.settled_venue_funded_atomic,
            # Include status in the completed round trip record document result.
            "status": self.status.value,
            "target_event_id": self.target_event_id.hex,
            "target_position": _position_document(self.target_position),
            "target_time_ns": self.target_time_ns,
            "venue_id": self.venue_id.value,
            # Return the completed round trip record document result without a hidden
            # fallback.
        }
        if self.source_schema_id == ROUNDTRIP_RESULT_SCHEMA_V3:
            # Preserve the original strict field set for legacy API/query consumers.
            for field_name in (
                "execution_mode",
                "mtm_liquidity",
                "sell_landing_liquidity",
                "sell_reference_liquidity",
                "settled_synthetic_funded_atomic",
                "settled_venue_funded_atomic",
            ):
                document.pop(field_name)
        return document


def roundtrip_record_from_document(
    value: object,
    *,
    schema_id: str = ROUNDTRIP_RESULT_SCHEMA_V4,
) -> RoundTripRecord:
    """Strictly reconstruct one version-dispatched canonical result row."""

    document = _object(value, "round-trip record")
    legacy_expected = {
        "acquired_token_amount_atomic",
        "account_components",
        "account_profile_id",
        "asset_id",
        "buy",
        "cashback_receivable_atomic",
        "cooldown_consumed",
        # Keep the cooldown until ns component named inside the expected contract.
        "cooldown_until_ns",
        "creation_user_id",
        "developer_id",
        "economic_pnl_atomic",
        "mtm_cash_pnl_atomic",
        # Keep the mtm liquidation value atomic component named inside the expected
        # contract.
        "mtm_liquidation_value_atomic",
        "mtm_status",
        "network_id",
        "position_schema_id",
        "quote_asset_id",
        # Keep the realized cash pnl atomic component named inside the expected contract.
        "realized_cash_pnl_atomic",
        "roundtrip_id",
        # Keep the sell component named inside the expected contract.
        "sell",
        "status",
        "target_event_id",
        "target_position",
        "target_time_ns",
        # Keep the venue id component named inside the expected contract.
        "venue_id",
    }
    v4_expected = legacy_expected | {
        "execution_mode",
        "mtm_liquidity",
        "sell_landing_liquidity",
        "sell_reference_liquidity",
        "settled_synthetic_funded_atomic",
        "settled_venue_funded_atomic",
    }
    if schema_id not in {ROUNDTRIP_RESULT_SCHEMA_V3, ROUNDTRIP_RESULT_SCHEMA_V4}:
        raise ValueError("unsupported round-trip record schema")
    expected = v4_expected if schema_id == ROUNDTRIP_RESULT_SCHEMA_V4 else legacy_expected
    if set(document) != expected:
        raise ValueError("round-trip record schema is invalid")
    network_id = NetworkId(_string(document["network_id"], "network ID"))
    # Assemble position schema id once so the roundtrip record from document workflow
    # shares one value.
    position_schema_id = PositionSchemaId(
        _string(document["position_schema_id"], "position schema ID")
    )
    result = RoundTripRecord(
        roundtrip_id=ContentDigest(_string(document["roundtrip_id"], "roundtrip ID")),
        # Pass network id explicitly so RoundTripRecord receives a reviewable roundtrip id
        # and target event id input in roundtrip record from document.
        network_id=network_id,
        position_schema_id=position_schema_id,
        target_event_id=ContentDigest(_string(document["target_event_id"], "target event ID")),
        target_position=_position_from_document(
            document["target_position"],
            # Pass network id explicitly so _position_from_document receives a reviewable
            # target position and document input in roundtrip record from document.
            network_id,
            position_schema_id,
            # Complete _position_from_document only after its target position and document
            # inputs are visible in roundtrip record from document.
        ),
        target_time_ns=_integer(document["target_time_ns"], "target time"),
        developer_id=AccountId(_string(document["developer_id"], "developer ID")),
        creation_user_id=AccountId(_string(document["creation_user_id"], "creation user ID")),
        asset_id=AssetId(_string(document["asset_id"], "asset ID")),
        # Keep the asset id and string AssetId step visible while building result.
        quote_asset_id=AssetId(_string(document["quote_asset_id"], "quote asset ID")),
        venue_id=VenueId(_string(document["venue_id"], "venue ID")),
        cooldown_consumed=_boolean(document["cooldown_consumed"], "cooldown consumed"),
        cooldown_until_ns=_optional_integer(document["cooldown_until_ns"], "cooldown expiry"),
        status=RoundTripStatus(_string(document["status"], "round-trip status")),
        # Keep the optional leg from document and network id _optional_leg_from_document
        # step visible while building result.
        buy=_optional_leg_from_document(
            document["buy"], network_id, position_schema_id, RoundTripLegSide.BUY
        ),
        sell=_optional_leg_from_document(
            document["sell"],
            # Pass network id explicitly so _optional_leg_from_document receives a
            # reviewable sell and document input in roundtrip record from document.
            network_id,
            position_schema_id,
            RoundTripLegSide.SELL,
            # Complete _optional_leg_from_document only after its sell and document inputs are
            # visible in roundtrip record from document.
        ),
        acquired_token_amount_atomic=_integer(
            document["acquired_token_amount_atomic"], "acquired token amount"
        ),
        cashback_receivable_atomic=_integer(
            document["cashback_receivable_atomic"],
            # Pass cashback receivable explicitly so _integer receives a reviewable
            # cashback receivable atomic and cashback receivable input in roundtrip record
            # from document.
            "cashback receivable",
            # Complete _integer only after its cashback receivable atomic and cashback
            # receivable inputs are visible in roundtrip record from document.
        ),
        # Keep the optional integer and document _optional_integer step visible while
        # building result.
        realized_cash_pnl_atomic=_optional_integer(
            document["realized_cash_pnl_atomic"], "realized cash PnL"
        ),
        mtm_status=MtmStatus(_string(document["mtm_status"], "MTM status")),
        mtm_liquidation_value_atomic=_optional_integer(
            # Pass document explicitly so _optional_integer receives a reviewable mtm
            # liquidation value atomic and mtm liquidation value input in roundtrip record
            # from document.
            document["mtm_liquidation_value_atomic"],
            "MTM liquidation value",
        ),
        mtm_cash_pnl_atomic=_optional_integer(document["mtm_cash_pnl_atomic"], "MTM cash PnL"),
        economic_pnl_atomic=_optional_integer(document["economic_pnl_atomic"], "economic PnL"),
        # Keep the string and document _string step visible while building result.
        account_profile_id=_string(document["account_profile_id"], "account profile ID"),
        account_components=_account_components_from_document(document["account_components"]),
        # Legacy v3 was unambiguously strict exogenous replay with no stored evidence.
        execution_mode=(
            ExecutionMode.EXOGENOUS_REPLAY
            if schema_id == ROUNDTRIP_RESULT_SCHEMA_V3
            else ExecutionMode(_string(document["execution_mode"], "execution mode"))
        ),
        sell_reference_liquidity=(
            None
            if schema_id == ROUNDTRIP_RESULT_SCHEMA_V3
            else _optional_liquidity_from_document(document["sell_reference_liquidity"])
        ),
        sell_landing_liquidity=(
            None
            if schema_id == ROUNDTRIP_RESULT_SCHEMA_V3
            else _optional_liquidity_from_document(document["sell_landing_liquidity"])
        ),
        mtm_liquidity=(
            None
            if schema_id == ROUNDTRIP_RESULT_SCHEMA_V3
            else _optional_liquidity_from_document(document["mtm_liquidity"])
        ),
        # Used synthetic funding did not exist under the v3 execution contract.
        settled_venue_funded_atomic=(
            0
            if schema_id == ROUNDTRIP_RESULT_SCHEMA_V3
            else _integer(document["settled_venue_funded_atomic"], "settled venue funding")
        ),
        settled_synthetic_funded_atomic=(
            0
            if schema_id == ROUNDTRIP_RESULT_SCHEMA_V3
            else _integer(document["settled_synthetic_funded_atomic"], "settled synthetic funding")
        ),
        source_schema_id=schema_id,
    )
    if schema_id == ROUNDTRIP_RESULT_SCHEMA_V4:
        validate_roundtrip_record_v4(result)
    if result.document() != document:
        raise ValueError("round-trip record does not round-trip exactly")
    return result


def validate_roundtrip_record_v4(record: RoundTripRecord) -> None:
    """Enforce evidence completeness required for every newly written v4 row."""

    if not isinstance(record, RoundTripRecord):
        raise TypeError("record must be a RoundTripRecord")
    if record.source_schema_id != ROUNDTRIP_RESULT_SCHEMA_V4:
        raise ValueError("new result writes require the round-trip v4 schema")
    expected_policy = {
        ExecutionMode.EXOGENOUS_REPLAY: "real-reserve-capped-v1",
        ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT: (
            "virtual-reserve-output-with-explicit-synthetic-shortfall-v1"
        ),
    }.get(record.execution_mode)
    if expected_policy is None:
        raise ValueError("unsupported round-trip execution mode")

    # A materialized quote must retain evidence from the same causal boundary.
    if record.sell is None:
        if record.sell_reference_liquidity is not None or record.sell_landing_liquidity is not None:
            raise ValueError("sell liquidity evidence requires a sell result leg")
    elif record.sell_reference_liquidity is None:
        raise ValueError("a sell result leg requires reference liquidity evidence")
    if (
        record.sell is not None
        and record.sell.landing_out_atomic is not None
        and record.sell_landing_liquidity is None
    ):
        raise ValueError("a materialized sell landing requires liquidity evidence")
    if record.sell_landing_liquidity is not None and (
        record.sell is None or record.sell.landing_position is None
    ):
        raise ValueError("landing liquidity evidence requires a landed sell result leg")
    if record.mtm_status is MtmStatus.NOT_APPLICABLE and record.mtm_liquidity is not None:
        raise ValueError("not-applicable MTM cannot carry liquidity evidence")
    if record.mtm_liquidity is not None and (
        record.status is RoundTripStatus.CLOSED or record.acquired_token_amount_atomic == 0
    ):
        raise ValueError("MTM liquidity evidence requires an open acquired position")

    # Every stored quote uses the policy selected by semantic execution identity.
    evidence_values = tuple(
        item
        for item in (
            record.sell_reference_liquidity,
            record.sell_landing_liquidity,
            record.mtm_liquidity,
        )
        if item is not None
    )
    if any(item.policy_id != expected_policy for item in evidence_values):
        raise ValueError("liquidity evidence policy differs from execution mode")
    if record.execution_mode is ExecutionMode.EXOGENOUS_REPLAY and any(
        item.synthetic_shortfall_atomic for item in evidence_values
    ):
        raise ValueError("strict exogenous replay cannot record synthetic shortfall")

    # A successful sell must expose and reconcile the exact landed gross funding split.
    successful_sell = record.status is RoundTripStatus.CLOSED
    if successful_sell and (
        record.sell is None
        or record.sell.failure_code is not None
        or record.sell.landing_position is None
        or record.sell.landing_out_atomic is None
    ):
        raise ValueError("a closed round trip requires one successful landed sell")
    if successful_sell and record.sell_landing_liquidity is None:
        raise ValueError("a successful sell requires landing liquidity evidence")
    if successful_sell:
        landed = cast(QuoteLiquidityEvidenceRecord, record.sell_landing_liquidity)
        sell = cast(RoundTripLegRecord, record.sell)
        # Liquidity funds the gross curve output, while the leg stores net wallet output.
        expected_gross_output = (
            cast(int, sell.landing_out_atomic) + sell.protocol_fee_atomic + sell.creator_fee_atomic
        )
        if landed.required_output_atomic != expected_gross_output:
            raise ValueError(
                "landing liquidity gross output differs from net output plus Pump fees"
            )
        if (
            record.settled_venue_funded_atomic + record.settled_synthetic_funded_atomic
            != landed.required_output_atomic
        ):
            raise ValueError("settled sell funding does not equal landing required output")


def _optional_liquidity_from_document(value: object) -> QuoteLiquidityEvidenceRecord | None:
    """Decode one strict optional v4 liquidity evidence object."""

    if value is None:
        return None
    document = _object(value, "quote liquidity evidence")
    expected = {
        "asset_id",
        "observed_available_output_atomic",
        "policy_id",
        "required_output_atomic",
        "synthetic_shortfall_atomic",
    }
    if set(document) != expected:
        raise ValueError("quote liquidity evidence schema is invalid")
    result = QuoteLiquidityEvidenceRecord(
        policy_id=_string(document["policy_id"], "liquidity policy ID"),
        asset_id=AssetId(_string(document["asset_id"], "liquidity asset ID")),
        required_output_atomic=_integer(document["required_output_atomic"], "required output"),
        observed_available_output_atomic=_integer(
            document["observed_available_output_atomic"], "observed available output"
        ),
        synthetic_shortfall_atomic=_integer(
            document["synthetic_shortfall_atomic"], "synthetic shortfall"
        ),
    )
    if result.document() != document:
        raise ValueError("quote liquidity evidence does not round-trip exactly")
    return result


def _account_components_from_document(
    value: object,
) -> tuple[AccountComponentRecord, ...]:
    """Strictly decode the bounded v3 component array."""

    if not isinstance(value, list):
        raise ValueError("account components must be an array")
    return tuple(account_component_from_document(item) for item in value)


def _account_component_key(item: AccountComponentRecord) -> tuple[str, str, str, str]:
    """Keep result ordering stable across reference and primitive execution."""

    return (
        item.scope.value,
        item.requirement_schema_id,
        item.attribution_kind.value,
        item.attribution_id.hex,
    )


# Define optional leg from document as one focused operation with an explicit boundary.
def _optional_leg_from_document(
    value: object,
    network_id: NetworkId,
    position_schema_id: PositionSchemaId,
    expected_side: RoundTripLegSide,
    # Keep the round trip leg record input explicit in the optional leg from document
    # contract.
) -> RoundTripLegRecord | None:
    # Execute the optional leg from document workflow in explicit, reviewable steps.
    if value is None:
        return None
    document = _object(value, f"{expected_side.value.lower()} leg")
    expected = {
        "amount_in_atomic",
        # Keep the creator fee atomic component named inside the expected contract.
        "creator_fee_atomic",
        "decision_position",
        "failure_code",
        "landing_out_atomic",
        "landing_position",
        # Keep the minimum out atomic component named inside the expected contract.
        "minimum_out_atomic",
        "network_base_fee_atomic",
        "network_priority_fee_atomic",
        "protocol_fee_atomic",
        "reference_out_atomic",
        # Keep the side component named inside the expected contract.
        "side",
        "signed_slippage_atomic",
    }
    if set(document) != expected:
        raise ValueError("round-trip leg schema is invalid")
    # Assemble side once so the optional leg from document workflow shares one value.
    side = RoundTripLegSide(_string(document["side"], "round-trip leg side"))
    if side is not expected_side:
        raise ValueError("round-trip leg appears under the wrong side")
    landing = document["landing_position"]
    return RoundTripLegRecord(
        # Pass side explicitly so RoundTripLegRecord receives a reviewable decision
        # position and leg input amount input in optional leg from document.
        side=side,
        decision_position=_position_from_document(
            document["decision_position"], network_id, position_schema_id
        ),
        landing_position=(
            # Keep round trip leg record, side and position from document visible while
            # completing RoundTripLegRecord within optional leg from document.
            None
            if landing is None
            else _position_from_document(landing, network_id, position_schema_id)
        ),
        amount_in_atomic=_optional_integer(document["amount_in_atomic"], "leg input amount"),
        # Include reference out atomic in the completed optional leg from document result.
        reference_out_atomic=_integer(document["reference_out_atomic"], "reference output"),
        landing_out_atomic=_optional_integer(document["landing_out_atomic"], "landing output"),
        minimum_out_atomic=_integer(document["minimum_out_atomic"], "minimum output"),
        signed_slippage_atomic=_optional_integer(
            document["signed_slippage_atomic"],
            # Pass signed slippage explicitly so _optional_integer receives a reviewable
            # signed slippage atomic and signed slippage input in optional leg from
            # document.
            "signed slippage",
            # Complete _optional_integer only after its signed slippage atomic and signed
            # slippage inputs are visible in optional leg from document.
        ),
        protocol_fee_atomic=_integer(document["protocol_fee_atomic"], "protocol fee"),
        creator_fee_atomic=_integer(document["creator_fee_atomic"], "creator fee"),
        network_base_fee_atomic=_integer(document["network_base_fee_atomic"], "network base fee"),
        network_priority_fee_atomic=_integer(
            # Pass document explicitly so _integer receives a reviewable network priority
            # fee atomic and network priority fee input in optional leg from document.
            document["network_priority_fee_atomic"],
            "network priority fee",
        ),
        failure_code=(
            None
            # Pass document explicitly so RoundTripLegRecord receives a reviewable
            # decision position and leg input amount input in optional leg from document.
            if document["failure_code"] is None
            # Route all remaining cases through the explicit alternative branch.
            else _string(document["failure_code"], "failure code")
        ),
    )


def _position_from_document(
    value: object,
    # Keep the network id input explicit in the position from document contract.
    network_id: NetworkId,
    position_schema_id: PositionSchemaId,
) -> ChainPosition:
    # Execute the position from document workflow in explicit, reviewable steps.
    document = _object(value, "chain position")
    expected = {"block_ordinal", "boundary_ordinal", "event_index", "transaction_index"}
    if set(document) != expected:
        raise ValueError("chain position schema is invalid")
    result = ChainPosition(
        # Pass network id explicitly so ChainPosition receives a reviewable block ordinal
        # and transaction index input in position from document.
        network_id=network_id,
        position_schema_id=position_schema_id,
        block_ordinal=_integer(document["block_ordinal"], "block ordinal"),
        transaction_index=_integer(document["transaction_index"], "transaction index"),
        event_index=_optional_integer(document["event_index"], "event index"),
        # Complete ChainPosition only after its block ordinal and transaction index inputs are
        # visible in position from document.
    )
    if result.boundary_ordinal != _integer(document["boundary_ordinal"], "boundary ordinal"):
        raise ValueError("chain position boundary ordinal is inconsistent")
    return result


def _object(value: object, field: str) -> dict[str, object]:
    # Execute the object workflow in explicit, reviewable steps.
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    # Execute the string workflow in explicit, reviewable steps.
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def _integer(value: object, field: str) -> int:
    # Execute the integer workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def _optional_integer(value: object, field: str) -> int | None:
    return None if value is None else _integer(value, field)


# Define boolean as one focused operation with an explicit boundary.
def _boolean(value: object, field: str) -> bool:
    # Execute the boolean workflow in explicit, reviewable steps.
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _position_document(position: ChainPosition) -> dict[str, object]:
    # Execute the position document workflow in explicit, reviewable steps.
    return {
        "block_ordinal": position.block_ordinal,
        "boundary_ordinal": position.boundary_ordinal,
        "event_index": position.event_index,
        "transaction_index": position.transaction_index,
        # Return the completed position document result without a hidden fallback.
    }


def _liquidity_document(
    value: QuoteLiquidityEvidenceRecord | None,
) -> dict[str, object] | None:
    """Preserve absence separately from an exact zero-shortfall observation."""

    return None if value is None else value.document()


def _require_non_negative_integer(name: str, value: int) -> None:
    # Execute the require non negative integer workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _require_stable_token(name: str, value: str) -> None:
    # Execute the require stable token workflow in explicit, reviewable steps.
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or not value.replace("_", "").isalnum()
        # Evaluate the complete require stable token value, isinstance and strip condition
        # before guarded effects.
    ):
        raise ValueError(f"{name} must be a stable token")


def _require_nonempty_trimmed(name: str, value: str) -> None:
    # Execute the require nonempty trimmed workflow in explicit, reviewable steps.
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise ValueError(f"{name} must be non-empty, trimmed and NUL-free")


__all__ = [
    "ROUNDTRIP_RESULT_SCHEMA_V3",
    "ROUNDTRIP_RESULT_SCHEMA_V4",
    "MtmStatus",
    "QuoteLiquidityEvidenceRecord",
    "RoundTripLegRecord",
    # Keep the round trip leg side component named inside the all contract.
    "RoundTripLegSide",
    "RoundTripRecord",
    "RoundTripStatus",
    "roundtrip_record_from_document",
    "validate_roundtrip_record_v4",
    # Complete the all group only after its semantic components are visible.
]
