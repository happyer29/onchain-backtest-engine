"""Pump.fun canonical payload codec and generic sniping runtime adapter."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any, Final, Never

from backtest.domain.account_requirements import AccountRequirement
from backtest.domain.execution import ExecutionMode
from backtest.domain.fidelity import OrderingFidelity

# Import hashing at the visible module dependency boundary.
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.domain.identifiers import (
    AccountId,
    AssetId,
    BundleId,
    # Include protocol payload schema id so the identifiers dependency remains explicit.
    ProtocolPayloadSchemaId,
    VenueId,
)
from backtest.domain.intents import RoundTripIntent
from backtest.domain.market_events import (
    # Include block event so the market events dependency remains explicit.
    BlockEvent,
    CanonicalEvent,
    TokenLaunchEvent,
    VenueLifecycleEvent,
    VenueLifecycleKind,
    # Include venue trade event so the market events dependency remains explicit.
    VenueTradeEvent,
)
from backtest.engine.sniping_contracts import (
    LaunchTarget,
    ProtocolContractError,
    # Include protocol contract error code so the sniping contracts dependency remains
    # explicit.
    ProtocolContractErrorCode,
    ProtocolExecutionRejected,
    ProtocolLiquidityEvidence,
    ProtocolQuote,
    ProtocolQuoteSide,
    ValuationQuote,
    liquidity_policy_id_for_execution_mode,
    synthetic_liquidity_account_id,
    # Close the sniping contracts import after its required symbols are visible.
)
from backtest.plugins.protocols.pumpfun.accounts import pumpfun_account_requirements
from backtest.plugins.protocols.pumpfun.model import (
    PumpBuyQuote,
    PumpCurveLifecycle,
    PumpCurveStateV1,
    # Include pump fee profile so the model dependency remains explicit.
    PumpFeeProfile,
    PumpMode,
    PumpQuoteError,
    PumpQuoteErrorCode,
    PumpSellLiquidityPolicy,
    PumpSellQuote,
    # Include buy quote so the model dependency remains explicit.
    buy_quote,
    sell_quote,
)

PUMPFUN_PROTOCOL_NAME: Final = "pumpfun"
PUMPFUN_LAUNCH_PAYLOAD_SCHEMA_ID: Final = ProtocolPayloadSchemaId("pump-launch-state-v1")
# Bind pumpfun trade payload schema id once as an explicit module-level contract.
PUMPFUN_TRADE_PAYLOAD_SCHEMA_ID: Final = ProtocolPayloadSchemaId("pump-trade-state-v1")
PUMPFUN_LIFECYCLE_PAYLOAD_SCHEMA_ID: Final = ProtocolPayloadSchemaId("pump-lifecycle-state-v1")

PUMPFUN_SNIPING_PROTOCOL_BUNDLE_ID: Final = BundleId(
    domain_digest(
        "backtest.pumpfun-sniping-protocol-bundle.v2",
        # Open the v2 payload explicitly so supported settlement policies enter identity.
        # within module.
        {
            "launch_payload_schema": PUMPFUN_LAUNCH_PAYLOAD_SCHEMA_ID.value,
            "lifecycle_payload_schema": PUMPFUN_LIFECYCLE_PAYLOAD_SCHEMA_ID.value,
            "math_state_schema": PumpCurveStateV1.SCHEMA_VERSION,
            # Pin the closed policy set without depending on enum declaration order.
            "sell_liquidity_policies": sorted(policy.value for policy in PumpSellLiquidityPolicy),
            "trade_payload_schema": PUMPFUN_TRADE_PAYLOAD_SCHEMA_ID.value,
            # Close the v2 payload only after all semantic fields are present.
            # present.
        },
    ).hex
)

_STATE_FIELDS = {
    "lifecycle",
    # Keep the mode component named inside the state fields contract.
    "mode",
    "real_sol_reserves_lamports",
    "real_token_reserves_atomic",
    "token_total_supply_atomic",
    "virtual_sol_reserves_lamports",
    # Keep the virtual token reserves atomic component named inside the state fields
    # contract.
    "virtual_token_reserves_atomic",
}

type PumpPrimitiveStateV1 = tuple[int, int, int, int, int, int, int]

_PRIMITIVE_LIFECYCLE_CODES: Final = {
    PumpCurveLifecycle.ACTIVE: 1,
    # Keep the pump curve lifecycle component named inside the primitive lifecycle codes
    # contract.
    PumpCurveLifecycle.COMPLETED: 2,
    PumpCurveLifecycle.MIGRATED: 3,
}
_PRIMITIVE_LIFECYCLE_VALUES: Final = {
    value: key
    # Keep the items and primitive lifecycle codes items step visible while building
    # primitive lifecycle values.
    for key, value in _PRIMITIVE_LIFECYCLE_CODES.items()
    # Complete the primitive lifecycle values group only after its semantic components are
    # visible.
}
_PRIMITIVE_MODE_CODES: Final = {
    PumpMode.NORMAL: 1,
    PumpMode.TOKEN_2022: 2,
    PumpMode.CASHBACK: 3,
    # Keep the pump mode component named inside the primitive mode codes contract.
    PumpMode.MAYHEM: 4,
}
_PRIMITIVE_MODE_VALUES: Final = {value: key for key, value in _PRIMITIVE_MODE_CODES.items()}


# Keep the curve record contract and validation rules together.
@dataclass(frozen=True, slots=True)
class _CurveRecord:
    asset_id: AssetId
    quote_asset_id: AssetId
    state: PumpCurveStateV1
    # Declare last active state explicitly in the curve record contract.
    last_active_state: PumpCurveStateV1 | None
    last_active_effective_at_unix_s: int | None


def encode_launch_payload(state: PumpCurveStateV1) -> bytes:
    return _encode_state(state)


def encode_trade_payload(state_after: PumpCurveStateV1) -> bytes:
    # Return the completed encode trade payload result without a hidden fallback.
    return _encode_state(state_after)


def encode_lifecycle_payload(state_after: PumpCurveStateV1) -> bytes:
    return _encode_state(state_after)


class PumpfunSnipingProtocolRuntime:
    """Apply exact Pump groups and adapt Pump math to core quote contracts."""

    def __init__(
        self,
        *,
        quote_asset_id: AssetId,
        fee_profile: PumpFeeProfile,
        # Keep the protocol version input explicit in the init contract.
        protocol_version: str,
        bundle_id: BundleId | None = None,
    ) -> None:
        # Execute the pumpfun sniping protocol runtime init workflow in explicit,
        # reviewable steps.
        if not protocol_version or protocol_version != protocol_version.strip():
            raise ValueError("protocol_version must be non-empty and trimmed")
        self.quote_asset_id = quote_asset_id
        self.fee_profile = fee_profile
        self.protocol_version = protocol_version
        # Assemble self bundle id once so the pumpfun sniping protocol runtime init
        # workflow shares one value.
        self._bundle_id = PUMPFUN_SNIPING_PROTOCOL_BUNDLE_ID if bundle_id is None else bundle_id
        self._curves: dict[VenueId, _CurveRecord] = {}

    @property
    def bundle_id(self) -> BundleId:
        return self._bundle_id

    # Apply property semantics to the following pumpfun sniping protocol runtime launch
    # payload schema id contract.
    @property
    def launch_payload_schema_id(self) -> ProtocolPayloadSchemaId:
        return PUMPFUN_LAUNCH_PAYLOAD_SCHEMA_ID

    @property
    def trade_payload_schema_id(self) -> ProtocolPayloadSchemaId:
        # Return the completed pumpfun sniping protocol runtime trade payload schema id
        # result without a hidden fallback.
        return PUMPFUN_TRADE_PAYLOAD_SCHEMA_ID

    @property
    def lifecycle_payload_schema_id(self) -> ProtocolPayloadSchemaId:
        return PUMPFUN_LIFECYCLE_PAYLOAD_SCHEMA_ID

    @property
    # Define pumpfun sniping protocol runtime primitive active lifecycle code as one
    # focused operation with an explicit boundary.
    def primitive_active_lifecycle_code(self) -> int:
        return _PRIMITIVE_LIFECYCLE_CODES[PumpCurveLifecycle.ACTIVE]

    @property
    def primitive_migrated_lifecycle_code(self) -> int:
        return _PRIMITIVE_LIFECYCLE_CODES[PumpCurveLifecycle.MIGRATED]

    # Define pumpfun sniping protocol runtime decode primitive state payload as one
    # focused operation with an explicit boundary.
    def decode_primitive_state_payload(self, payload: bytes) -> PumpPrimitiveStateV1:
        """Decode one canonical payload during a bounded adapter load phase."""

        state = _decode_state(payload)
        _require_known_state(state)
        try:
            # Perform the protected pumpfun sniping protocol runtime decode primitive
            # state payload operation before explicit failure handling.
            lifecycle_code = _PRIMITIVE_LIFECYCLE_CODES[state.lifecycle]
            mode_code = _PRIMITIVE_MODE_CODES[state.mode]
        except KeyError as error:  # pragma: no cover - guarded by _require_known_state
            raise ProtocolContractError(ProtocolContractErrorCode.UNKNOWN_PROGRAM_MODE) from error
        return (
            state.virtual_token_reserves_atomic,
            state.virtual_sol_reserves_lamports,
            state.real_token_reserves_atomic,
            # Include state in the completed pumpfun sniping protocol runtime decode
            # primitive state payload result.
            state.real_sol_reserves_lamports,
            state.token_total_supply_atomic,
            lifecycle_code,
            mode_code,
        )

    # Define pumpfun sniping protocol runtime primitive state is active as one focused
    # operation with an explicit boundary.
    def primitive_state_is_active(self, state: PumpPrimitiveStateV1) -> bool:
        return _state_from_primitive(state).lifecycle is PumpCurveLifecycle.ACTIVE

    def primitive_state_is_migrated(self, state: PumpPrimitiveStateV1) -> bool:
        return _state_from_primitive(state).lifecycle is PumpCurveLifecycle.MIGRATED

    def validate_primitive_launch_state(self, state: PumpPrimitiveStateV1) -> None:
        # Execute the pumpfun sniping protocol runtime validate primitive launch state
        # workflow in explicit, reviewable steps.
        _require_eligible_launch_state(_state_from_primitive(state))

    def validate_primitive_lifecycle_state(
        self,
        state: PumpPrimitiveStateV1,
        # Close the validate primitive lifecycle state signature after its explicit
        # inputs.
        *,
        lifecycle_kind_code: int,
    ) -> None:
        # Execute the pumpfun sniping protocol runtime validate primitive lifecycle state
        # workflow in explicit, reviewable steps.
        expected = {
            1: PumpCurveLifecycle.COMPLETED,
            2: PumpCurveLifecycle.MIGRATED,
        }.get(lifecycle_kind_code)
        if expected is None or _state_from_primitive(state).lifecycle is not expected:
            # Fail the pumpfun sniping protocol runtime validate primitive lifecycle state
            # path with ProtocolContractError for unknown lifecycle and protocol contract
            # error code when expected, lifecycle and state from primitive is true; do not
            # continue ambiguously.
            raise ProtocolContractError(ProtocolContractErrorCode.UNKNOWN_LIFECYCLE)

    def quote_buy_from_primitive_state(
        self,
        intent: RoundTripIntent,
        state: PumpPrimitiveStateV1,
        # Close the quote buy from primitive state signature after its explicit inputs.
        *,
        effective_at_unix_s: int,
    ) -> ProtocolQuote:
        # Execute the pumpfun sniping protocol runtime quote buy from primitive state
        # workflow in explicit, reviewable steps.
        return self._quote_buy_state(
            intent,
            _state_from_primitive(state),
            effective_at_unix_s=effective_at_unix_s,
        )

    def account_requirements_from_primitive_state(
        self,
        state: PumpPrimitiveStateV1,
    ) -> tuple[AccountRequirement, ...]:
        """Resolve account schemas from the same state used by optimized quotes."""

        return pumpfun_account_requirements(_state_from_primitive(state).mode)

    # Define pumpfun sniping protocol runtime quote sell from primitive state as one
    # focused operation with an explicit boundary.
    def quote_sell_from_primitive_state(
        self,
        intent: RoundTripIntent,
        state: PumpPrimitiveStateV1,
        *,
        # Keep the tokens in atomic input explicit in the quote sell from primitive state
        # contract.
        tokens_in_atomic: int,
        effective_at_unix_s: int,
    ) -> ProtocolQuote:
        # Execute the pumpfun sniping protocol runtime quote sell from primitive state
        # workflow in explicit, reviewable steps.
        return self._quote_sell_state(
            intent,
            _state_from_primitive(state),
            tokens_in_atomic=tokens_in_atomic,
            effective_at_unix_s=effective_at_unix_s,
            # Complete _quote_sell_state only after its state from primitive and intent inputs
            # are visible in pumpfun sniping protocol runtime quote sell from primitive state.
        )

    def valuation_quote_from_primitive_state(
        self,
        intent: RoundTripIntent,
        state: PumpPrimitiveStateV1,
        # Keep the last active state input explicit in the valuation quote from primitive
        # state contract.
        last_active_state: PumpPrimitiveStateV1 | None,
        last_active_effective_at_unix_s: int | None,
        *,
        tokens_in_atomic: int,
        effective_at_unix_s: int,
        # Keep the valuation quote input explicit in the valuation quote from primitive state
        # contract.
    ) -> ValuationQuote | None:
        # Execute the pumpfun sniping protocol runtime valuation quote from primitive
        # state workflow in explicit, reviewable steps.
        current = _state_from_primitive(state)
        if current.lifecycle is PumpCurveLifecycle.ACTIVE:
            # Handle the pumpfun sniping protocol runtime valuation quote from primitive
            # state lifecycle, active and current condition as a distinct block.
            return ValuationQuote(
                self._quote_sell_state(
                    intent,
                    current,
                    tokens_in_atomic=tokens_in_atomic,
                    # Pass effective at unix s explicitly so _quote_sell_state receives a
                    # reviewable intent and current input in pumpfun sniping protocol
                    # runtime valuation quote from primitive state.
                    effective_at_unix_s=effective_at_unix_s,
                ),
                stale_pre_migration=False,
            )
        if current.lifecycle is PumpCurveLifecycle.MIGRATED and last_active_state is not None:
            # Handle the pumpfun sniping protocol runtime valuation quote from primitive
            # state lifecycle, migrated and last active state condition as a distinct
            # block.
            if last_active_effective_at_unix_s is None:
                raise ProtocolContractError(ProtocolContractErrorCode.UNKNOWN_LIFECYCLE)
            return ValuationQuote(
                self._quote_sell_state(
                    intent,
                    # Include state from primitive in the completed pumpfun sniping
                    # protocol runtime valuation quote from primitive state result.
                    _state_from_primitive(last_active_state),
                    tokens_in_atomic=tokens_in_atomic,
                    effective_at_unix_s=last_active_effective_at_unix_s,
                ),
                stale_pre_migration=True,
                # Complete ValuationQuote only after its quote sell state and state from
                # primitive inputs are visible in pumpfun sniping protocol runtime valuation
                # quote from primitive state.
            )
        return None

    def apply_historical_group(
        self,
        events: tuple[CanonicalEvent, ...],
        # Close the apply historical group signature after its explicit inputs.
        *,
        effective_at_unix_s: int,
    ) -> tuple[LaunchTarget, ...]:
        # Execute the pumpfun sniping protocol runtime apply historical group workflow in
        # explicit, reviewable steps.
        if not events:
            raise ValueError("historical group must be non-empty")
        if (
            isinstance(effective_at_unix_s, bool)
            or not isinstance(effective_at_unix_s, int)
            # Keep effective at unix s visible while evaluating the isinstance and
            # effective at unix s guard.
            or effective_at_unix_s < 0
        ):
            raise ValueError("historical group effective time must be non-negative")
        boundary = events[0].envelope.boundary_ordinal
        group_id = events[0].envelope.transaction_group_id
        # Evaluate the complete pumpfun sniping protocol runtime apply historical group
        # event, events and boundary ordinal condition before guarded effects.
        if any(
            event.envelope.boundary_ordinal != boundary
            or event.envelope.transaction_group_id != group_id
            for event in events
        ):
            # Fail the pumpfun sniping protocol runtime apply historical group path with
            # ProtocolContractError for inconsistent venue identity and protocol contract
            # error code when event, events and boundary ordinal is true; do not continue
            # ambiguously.
            raise ProtocolContractError(ProtocolContractErrorCode.INCONSISTENT_VENUE_IDENTITY)
        candidate = dict(self._curves)
        launches: list[LaunchTarget] = []
        for event in events:
            # Process events inside the bounded pumpfun sniping protocol runtime apply
            # historical group loop.
            if isinstance(event, BlockEvent) or event.envelope.protocol != PUMPFUN_PROTOCOL_NAME:
                continue
            if event.envelope.protocol_version != self.protocol_version:
                raise ProtocolContractError(ProtocolContractErrorCode.UNSUPPORTED_PROTOCOL_VERSION)
            if event.envelope.ordering_fidelity is not OrderingFidelity.INSTRUCTION_EXACT:
                # Fail the pumpfun sniping protocol runtime apply historical group path
                # with ProtocolContractError for inconsistent venue identity and protocol
                # contract error code when ordering fidelity, instruction exact and
                # envelope is true; do not continue ambiguously.
                raise ProtocolContractError(ProtocolContractErrorCode.INCONSISTENT_VENUE_IDENTITY)
            if isinstance(event, TokenLaunchEvent):
                # Handle the pumpfun sniping protocol runtime apply historical group
                # isinstance(event, TokenLaunchEvent) branch as a distinct logical block.
                if event.protocol_payload_schema != PUMPFUN_LAUNCH_PAYLOAD_SCHEMA_ID:
                    # Handle the pumpfun sniping protocol runtime apply historical group
                    # protocol payload schema, pumpfun launch payload schema id and event
                    # condition as a distinct block.
                    raise ProtocolContractError(
                        ProtocolContractErrorCode.UNSUPPORTED_PAYLOAD_SCHEMA
                    )
                if event.quote_asset_id != self.quote_asset_id:
                    raise ProtocolContractError(ProtocolContractErrorCode.NON_SUPPORTED_QUOTE_ASSET)
                # Guard this path with event.venue_id in candidate before applying
                # effects.
                if event.venue_id in candidate:
                    # Handle the pumpfun sniping protocol runtime apply historical group
                    # event.venue_id in candidate branch as a distinct logical block.
                    raise ProtocolContractError(
                        ProtocolContractErrorCode.INCONSISTENT_VENUE_IDENTITY
                    )
                state = _decode_state(event.protocol_payload)
                # Validate eligibility before candidate curve state or LaunchTarget
                # creation so a stale all-modes artifact cannot consume cooldown.
                _require_eligible_launch_state(state)
                candidate[event.venue_id] = _CurveRecord(
                    asset_id=event.asset_id,
                    quote_asset_id=event.quote_asset_id,
                    # Pass state explicitly so _CurveRecord receives a reviewable asset id
                    # and quote asset id input in pumpfun sniping protocol runtime apply
                    # historical group.
                    state=state,
                    last_active_state=state,
                    last_active_effective_at_unix_s=effective_at_unix_s,
                )
                launches.append(
                    # Pass launch target explicitly to append for canonical event id and
                    # position.
                    LaunchTarget(
                        target_event_id=event.envelope.canonical_event_id,
                        position=event.envelope.position,
                        asset_id=event.asset_id,
                        developer_id=event.developer_id,
                        # Pass creation user id explicitly so LaunchTarget receives a
                        # reviewable canonical event id and envelope input in pumpfun
                        # sniping protocol runtime apply historical group.
                        creation_user_id=event.creation_user_id,
                        venue_id=event.venue_id,
                        quote_asset_id=event.quote_asset_id,
                    )
                )
                # Keep the continue step explicit within the pumpfun sniping protocol
                # runtime apply historical group workflow.
                continue
            if isinstance(event, VenueTradeEvent):
                # Handle the pumpfun sniping protocol runtime apply historical group
                # isinstance(event, VenueTradeEvent) branch as a distinct logical block.
                if event.protocol_payload_schema != PUMPFUN_TRADE_PAYLOAD_SCHEMA_ID:
                    # Handle the pumpfun sniping protocol runtime apply historical group
                    # protocol payload schema, pumpfun trade payload schema id and event
                    # condition as a distinct block.
                    raise ProtocolContractError(
                        ProtocolContractErrorCode.UNSUPPORTED_PAYLOAD_SCHEMA
                    )
                record = _require_curve(candidate, event.venue_id)
                if {event.sold_asset_id, event.bought_asset_id} != {
                    # Keep record visible while evaluating the sold asset id, bought asset
                    # id and asset id guard.
                    record.asset_id,
                    record.quote_asset_id,
                }:
                    # Handle the pumpfun sniping protocol runtime apply historical group
                    # sold asset id, bought asset id and asset id condition as a distinct
                    # block.
                    raise ProtocolContractError(
                        ProtocolContractErrorCode.INCONSISTENT_VENUE_IDENTITY
                    )
                state = _decode_state(event.protocol_payload)
                _require_known_state(state)
                # Assemble candidate[event venue id] once so the pumpfun sniping protocol
                # runtime apply historical group workflow shares one value.
                candidate[event.venue_id] = replace(
                    record,
                    state=state,
                    last_active_state=(
                        state
                        # Pass state explicitly so replace receives a reviewable last
                        # active state and lifecycle input in pumpfun sniping protocol
                        # runtime apply historical group.
                        if state.lifecycle is PumpCurveLifecycle.ACTIVE
                        else record.last_active_state
                    ),
                    last_active_effective_at_unix_s=(
                        effective_at_unix_s
                        # Pass state explicitly so replace receives a reviewable last
                        # active state and lifecycle input in pumpfun sniping protocol
                        # runtime apply historical group.
                        if state.lifecycle is PumpCurveLifecycle.ACTIVE
                        else record.last_active_effective_at_unix_s
                    ),
                )
                continue
            # Guard this path with isinstance(event, VenueLifecycleEvent) before applying
            # effects.
            if isinstance(event, VenueLifecycleEvent):
                # Handle the pumpfun sniping protocol runtime apply historical group
                # isinstance(event, VenueLifecycleEvent) branch as a distinct logical
                # block.
                if event.protocol_payload_schema != PUMPFUN_LIFECYCLE_PAYLOAD_SCHEMA_ID:
                    # Handle the pumpfun sniping protocol runtime apply historical group
                    # protocol payload schema, pumpfun lifecycle payload schema id and
                    # event condition as a distinct block.
                    raise ProtocolContractError(
                        ProtocolContractErrorCode.UNSUPPORTED_PAYLOAD_SCHEMA
                    )
                record = _require_curve(candidate, event.venue_id)
                state = _decode_state(event.protocol_payload)
                # Invoke _require_known_state for state as a visible pumpfun sniping
                # protocol runtime apply historical group step.
                _require_known_state(state)
                expected_lifecycle = {
                    VenueLifecycleKind.COMPLETED: PumpCurveLifecycle.COMPLETED,
                    VenueLifecycleKind.MIGRATED: PumpCurveLifecycle.MIGRATED,
                }.get(event.lifecycle_kind)
                # Evaluate the complete pumpfun sniping protocol runtime apply historical
                # group expected lifecycle, lifecycle and state condition before guarded
                # effects.
                if expected_lifecycle is None or state.lifecycle is not expected_lifecycle:
                    raise ProtocolContractError(ProtocolContractErrorCode.UNKNOWN_LIFECYCLE)
                candidate[event.venue_id] = replace(record, state=state)
                continue
            raise ProtocolContractError(ProtocolContractErrorCode.UNSUPPORTED_PAYLOAD_SCHEMA)
        # Assemble self curves once so the pumpfun sniping protocol runtime apply
        # historical group workflow shares one value.
        self._curves = candidate
        return tuple(launches)

    def quote_buy(
        self,
        intent: RoundTripIntent,
        # Close the quote buy signature after its explicit inputs.
        *,
        effective_at_unix_s: int,
    ) -> ProtocolQuote:
        # Execute the pumpfun sniping protocol runtime quote buy workflow in explicit,
        # reviewable steps.
        record = self._intent_curve(intent)
        return self._quote_buy_state(
            intent,
            record.state,
            effective_at_unix_s=effective_at_unix_s,
            # Complete _quote_buy_state only after its state and intent inputs are visible in
            # pumpfun sniping protocol runtime quote buy.
        )

    def account_requirements(
        self,
        intent: RoundTripIntent,
    ) -> tuple[AccountRequirement, ...]:
        """Describe mode-specific accounts without importing Solana rent prices."""

        return pumpfun_account_requirements(self._intent_curve(intent).state.mode)

    def _quote_buy_state(
        self,
        intent: RoundTripIntent,
        state: PumpCurveStateV1,
        # Close the quote buy state signature after its explicit inputs.
        *,
        effective_at_unix_s: int,
    ) -> ProtocolQuote:
        # Execute the pumpfun sniping protocol runtime quote buy state workflow in
        # explicit, reviewable steps.
        try:
            # Perform the protected pumpfun sniping protocol runtime quote buy state
            # operation before explicit failure handling.
            quote = buy_quote(
                state,
                spendable_gross_sol_lamports=intent.gross_buy_budget_atomic,
                fee_profile=self.fee_profile,
                effective_at_unix_s=effective_at_unix_s,
                # Complete buy_quote only after its gross buy budget atomic and fee profile
                # inputs are visible in pumpfun sniping protocol runtime quote buy state.
            )
        except PumpQuoteError as error:
            _raise_mapped_quote_error(error)
        return _buy_contract(intent, quote)

    def quote_sell(
        # Keep the remaining quote sell inputs visible at the pumpfun sniping protocol
        # runtime quote sell boundary.
        self,
        intent: RoundTripIntent,
        *,
        tokens_in_atomic: int,
        effective_at_unix_s: int,
        # Keep the protocol quote input explicit in the quote sell contract.
    ) -> ProtocolQuote:
        # Execute the pumpfun sniping protocol runtime quote sell workflow in explicit,
        # reviewable steps.
        record = self._intent_curve(intent)
        return self._quote_sell_state(
            intent,
            record.state,
            tokens_in_atomic=tokens_in_atomic,
            # Pass effective at unix s explicitly so _quote_sell_state receives a
            # reviewable state and intent input in pumpfun sniping protocol runtime quote
            # sell.
            effective_at_unix_s=effective_at_unix_s,
        )

    def _quote_sell_state(
        self,
        intent: RoundTripIntent,
        # Keep the state input explicit in the quote sell state contract.
        state: PumpCurveStateV1,
        *,
        tokens_in_atomic: int,
        effective_at_unix_s: int,
    ) -> ProtocolQuote:
        # Execute the pumpfun sniping protocol runtime quote sell state workflow in
        # explicit, reviewable steps.
        try:
            # Perform the protected pumpfun sniping protocol runtime quote sell state
            # operation before explicit failure handling.
            quote = sell_quote(
                state,
                tokens_in_atomic=tokens_in_atomic,
                fee_profile=self.fee_profile,
                effective_at_unix_s=effective_at_unix_s,
                liquidity_policy=_sell_liquidity_policy(intent.execution_mode),
                # Complete sell_quote only after its fee profile and state inputs are visible
                # in pumpfun sniping protocol runtime quote sell state.
            )
        except PumpQuoteError as error:
            _raise_mapped_quote_error(error)
        return _sell_contract(intent, quote)

    def valuation_quote(
        # Keep the remaining valuation quote inputs visible at the pumpfun sniping
        # protocol runtime valuation quote boundary.
        self,
        intent: RoundTripIntent,
        *,
        tokens_in_atomic: int,
        effective_at_unix_s: int,
        # Keep the valuation quote input explicit in the valuation quote contract.
    ) -> ValuationQuote | None:
        # Execute the pumpfun sniping protocol runtime valuation quote workflow in
        # explicit, reviewable steps.
        record = self._intent_curve(intent)
        if record.state.lifecycle is PumpCurveLifecycle.ACTIVE:
            # Handle the pumpfun sniping protocol runtime valuation quote lifecycle,
            # active and state condition as a distinct block.
            return ValuationQuote(
                self.quote_sell(
                    intent,
                    tokens_in_atomic=tokens_in_atomic,
                    effective_at_unix_s=effective_at_unix_s,
                    # Complete quote_sell only after its intent and tokens in atomic inputs
                    # are visible in pumpfun sniping protocol runtime valuation quote.
                ),
                stale_pre_migration=False,
            )
        if (
            record.state.lifecycle is PumpCurveLifecycle.MIGRATED
            # Keep record visible while evaluating the lifecycle, migrated and last active
            # state guard.
            and record.last_active_state is not None
        ):
            # Handle the pumpfun sniping protocol runtime valuation quote lifecycle,
            # migrated and last active state condition as a distinct block.
            if record.last_active_effective_at_unix_s is None:
                raise ProtocolContractError(ProtocolContractErrorCode.UNKNOWN_LIFECYCLE)
            try:
                # Perform the protected pumpfun sniping protocol runtime valuation quote
                # operation before explicit failure handling.
                quote = sell_quote(
                    record.last_active_state,
                    tokens_in_atomic=tokens_in_atomic,
                    fee_profile=self.fee_profile,
                    effective_at_unix_s=record.last_active_effective_at_unix_s,
                    liquidity_policy=_sell_liquidity_policy(intent.execution_mode),
                    # Complete sell_quote only after its last active state and fee profile
                    # inputs are visible in pumpfun sniping protocol runtime valuation quote.
                )
            except PumpQuoteError as error:
                _raise_mapped_quote_error(error)
            return ValuationQuote(
                _sell_contract(intent, quote),
                # Pass stale pre migration explicitly so ValuationQuote receives a
                # reviewable sell contract and intent input in pumpfun sniping protocol
                # runtime valuation quote.
                stale_pre_migration=True,
            )
        return None

    def _intent_curve(self, intent: RoundTripIntent) -> _CurveRecord:
        # Execute the pumpfun sniping protocol runtime intent curve workflow in explicit,
        # reviewable steps.
        record = _require_curve(self._curves, intent.venue_id)
        if (
            record.asset_id != intent.asset_id
            or record.quote_asset_id != intent.quote_asset_id
            or record.quote_asset_id != self.quote_asset_id
            # Evaluate the complete pumpfun sniping protocol runtime intent curve asset id,
            # quote asset id and record condition before guarded effects.
        ):
            raise ProtocolContractError(ProtocolContractErrorCode.INCONSISTENT_VENUE_IDENTITY)
        return record


def _buy_contract(intent: RoundTripIntent, quote: PumpBuyQuote) -> ProtocolQuote:
    # Execute the buy contract workflow in explicit, reviewable steps.
    protocol_account, creator_account, cashback_source = _fee_accounts(
        intent.venue_id,
        quote.fees.routing.protocol_fee_route.value,
        quote.fees.routing.creator_fee_route.value,
    )
    # Return the completed buy contract result without a hidden fallback.
    return ProtocolQuote(
        side=ProtocolQuoteSide.BUY,
        input_asset_id=intent.quote_asset_id,
        output_asset_id=intent.asset_id,
        amount_in_atomic=quote.gross_sol_spent_lamports,
        # Pass amount out atomic explicitly so ProtocolQuote receives a reviewable buy and
        # quote asset id input in buy contract.
        amount_out_atomic=quote.tokens_out_atomic,
        venue_input_atomic=quote.net_curve_sol_lamports,
        venue_output_atomic=quote.tokens_out_atomic,
        protocol_fee_atomic=quote.fees.protocol_fee_lamports,
        creator_fee_atomic=quote.fees.creator_fee_lamports,
        # Pass cashback receivable atomic explicitly so ProtocolQuote receives a
        # reviewable buy and quote asset id input in buy contract.
        cashback_receivable_atomic=quote.fees.cashback_receivable_lamports or 0,
        protocol_fee_account_id=protocol_account,
        creator_fee_account_id=creator_account,
        cashback_source_account_id=cashback_source,
        liquidity_evidence=None,
    )


# Define sell contract as one focused operation with an explicit boundary.
def _sell_contract(intent: RoundTripIntent, quote: PumpSellQuote) -> ProtocolQuote:
    # Execute the sell contract workflow in explicit, reviewable steps.
    protocol_account, creator_account, cashback_source = _fee_accounts(
        intent.venue_id,
        quote.fees.routing.protocol_fee_route.value,
        quote.fees.routing.creator_fee_route.value,
    )
    # Only an actual deficit gets a synthetic funding-account identity.
    synthetic_account = (
        _synthetic_liquidity_account(intent) if quote.synthetic_shortfall_lamports > 0 else None
    )
    liquidity_evidence = ProtocolLiquidityEvidence(
        policy_id=quote.liquidity_policy.value,
        asset_id=intent.quote_asset_id,
        required_output_atomic=quote.gross_curve_sol_lamports,
        # Preserve the full observed reserve for result diagnostics.
        observed_available_output_atomic=quote.observed_real_sol_reserves_lamports,
        synthetic_shortfall_atomic=quote.synthetic_shortfall_lamports,
        synthetic_source_account_id=synthetic_account,
    )
    # Return the completed sell contract result without a hidden fallback.
    return ProtocolQuote(
        side=ProtocolQuoteSide.SELL,
        input_asset_id=intent.asset_id,
        output_asset_id=intent.quote_asset_id,
        amount_in_atomic=quote.tokens_in_atomic,
        # Pass amount out atomic explicitly so ProtocolQuote receives a reviewable sell
        # and asset id input in sell contract.
        amount_out_atomic=quote.sol_out_lamports,
        venue_input_atomic=quote.tokens_in_atomic,
        venue_output_atomic=quote.gross_curve_sol_lamports,
        protocol_fee_atomic=quote.fees.protocol_fee_lamports,
        creator_fee_atomic=quote.fees.creator_fee_lamports,
        # Pass cashback receivable atomic explicitly so ProtocolQuote receives a
        # reviewable sell and asset id input in sell contract.
        cashback_receivable_atomic=quote.fees.cashback_receivable_lamports or 0,
        protocol_fee_account_id=protocol_account,
        creator_fee_account_id=creator_account,
        cashback_source_account_id=cashback_source,
        liquidity_evidence=liquidity_evidence,
    )


def _sell_liquidity_policy(execution_mode: ExecutionMode) -> PumpSellLiquidityPolicy:
    """Map the closed core execution modes to exact Pump sell semantics."""

    policy_id = liquidity_policy_id_for_execution_mode(execution_mode)
    return PumpSellLiquidityPolicy(policy_id)


def _synthetic_liquidity_account(intent: RoundTripIntent) -> AccountId:
    """Derive one stable bounded external source per exact network and venue."""

    # The engine-owned helper lets storage reconciliation reproduce this exact ID.
    return synthetic_liquidity_account_id(
        protocol_namespace=PUMPFUN_PROTOCOL_NAME,
        network_id=intent.target_position.network_id,
        venue_id=intent.venue_id,
    )


# Define fee accounts as one focused operation with an explicit boundary.
def _fee_accounts(
    venue_id: VenueId,
    protocol_route: str,
    creator_route: str,
) -> tuple[AccountId, AccountId, AccountId]:
    # Execute the fee accounts workflow in explicit, reviewable steps.
    route_prefix = f"pumpfun:{venue_id.value}"
    creator_account = AccountId(f"creator-fee:{route_prefix}:{creator_route.lower()}")
    return (
        AccountId(f"protocol-fee:{route_prefix}:{protocol_route.lower()}"),
        creator_account,
        # Include account id in the completed fee accounts result.
        AccountId(f"cashback-source:{route_prefix}:{creator_route.lower()}"),
    )


def _raise_mapped_quote_error(error: PumpQuoteError) -> Never:
    # Execute the raise mapped quote error workflow in explicit, reviewable steps.
    if error.code in {
        PumpQuoteErrorCode.UNSUPPORTED_PROGRAM_VERSION,
        PumpQuoteErrorCode.UNSUPPORTED_FORMULA_VERSION,
        PumpQuoteErrorCode.PROFILE_NOT_EFFECTIVE,
        PumpQuoteErrorCode.UNKNOWN_MODE,
        # Keep pump quote error code visible while evaluating the code, error and
        # unsupported program version guard.
        PumpQuoteErrorCode.UNKNOWN_LIFECYCLE,
    }:
        # Handle the raise mapped quote error code, error and unsupported program version
        # condition as a distinct block.
        mapping = {
            PumpQuoteErrorCode.PROFILE_NOT_EFFECTIVE: (
                ProtocolContractErrorCode.PROFILE_NOT_EFFECTIVE
            ),
            PumpQuoteErrorCode.UNKNOWN_MODE: ProtocolContractErrorCode.UNKNOWN_PROGRAM_MODE,
            # Keep the pump quote error code component named inside the mapping contract.
            PumpQuoteErrorCode.UNKNOWN_LIFECYCLE: ProtocolContractErrorCode.UNKNOWN_LIFECYCLE,
        }
        raise ProtocolContractError(
            mapping.get(
                error.code,
                # Pass protocol contract error code explicitly so get receives a
                # reviewable code and unsupported protocol version input in raise mapped
                # quote error.
                ProtocolContractErrorCode.UNSUPPORTED_PROTOCOL_VERSION,
            )
        ) from error
    raise ProtocolExecutionRejected(error.code.value) from error


def _require_curve(
    # Keep the curves input explicit in the require curve contract.
    curves: dict[VenueId, _CurveRecord],
    venue_id: VenueId,
) -> _CurveRecord:
    # Execute the require curve workflow in explicit, reviewable steps.
    try:
        return curves[venue_id]
    except KeyError as error:
        raise ProtocolContractError(ProtocolContractErrorCode.UNKNOWN_VENUE) from error


def _require_known_state(state: PumpCurveStateV1) -> None:
    # Execute the require known state workflow in explicit, reviewable steps.
    if state.mode is PumpMode.UNKNOWN:
        raise ProtocolContractError(ProtocolContractErrorCode.UNKNOWN_PROGRAM_MODE)
    if state.lifecycle is PumpCurveLifecycle.UNKNOWN:
        raise ProtocolContractError(ProtocolContractErrorCode.UNKNOWN_LIFECYCLE)


def _require_eligible_launch_state(state: PumpCurveStateV1) -> None:
    """Defend the execution boundary against launches excluded during preparation."""

    _require_known_state(state)
    if state.mode is PumpMode.MAYHEM:
        # A known Mayhem row belongs only to bounded source exclusion evidence; reaching
        # runtime means the pinned universe closure is incompatible.
        raise ProtocolContractError(ProtocolContractErrorCode.EXCLUDED_PROGRAM_MODE)
    if state.lifecycle is not PumpCurveLifecycle.ACTIVE:
        raise ProtocolContractError(ProtocolContractErrorCode.UNKNOWN_LIFECYCLE)


def _state_from_primitive(state: PumpPrimitiveStateV1) -> PumpCurveStateV1:
    # Execute the state from primitive workflow in explicit, reviewable steps.
    if not isinstance(state, tuple) or len(state) != 7:
        raise TypeError("primitive Pump state must be a seven-integer tuple")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in state):
        raise TypeError("primitive Pump state fields must be integers")
    try:
        # Assemble lifecycle once so the state from primitive workflow shares one value.
        lifecycle = _PRIMITIVE_LIFECYCLE_VALUES[state[5]]
    except KeyError as error:
        raise ProtocolContractError(ProtocolContractErrorCode.UNKNOWN_LIFECYCLE) from error
    try:
        mode = _PRIMITIVE_MODE_VALUES[state[6]]
    # Translate key error through the state from primitive boundary without hiding other
    # errors.
    except KeyError as error:
        raise ProtocolContractError(ProtocolContractErrorCode.UNKNOWN_PROGRAM_MODE) from error
    return PumpCurveStateV1(
        virtual_token_reserves_atomic=state[0],
        virtual_sol_reserves_lamports=state[1],
        # Pass real token reserves atomic explicitly so PumpCurveStateV1 receives a
        # reviewable state and lifecycle input in state from primitive.
        real_token_reserves_atomic=state[2],
        real_sol_reserves_lamports=state[3],
        token_total_supply_atomic=state[4],
        lifecycle=lifecycle,
        mode=mode,
        # Complete PumpCurveStateV1 only after its state and lifecycle inputs are visible in
        # state from primitive.
    )


def _encode_state(state: PumpCurveStateV1) -> bytes:
    # Execute the encode state workflow in explicit, reviewable steps.
    if not isinstance(state, PumpCurveStateV1):
        raise TypeError("state must be a PumpCurveStateV1")
    return canonical_json_bytes(
        {
            "lifecycle": state.lifecycle.value,
            # Keep mode named so the lifecycle and mode payload passed to
            # canonical_json_bytes remains self-describing within encode state.
            "mode": state.mode.value,
            "real_sol_reserves_lamports": state.real_sol_reserves_lamports,
            "real_token_reserves_atomic": state.real_token_reserves_atomic,
            "token_total_supply_atomic": state.token_total_supply_atomic,
            "virtual_sol_reserves_lamports": state.virtual_sol_reserves_lamports,
            # Keep virtual token reserves atomic named so the lifecycle and mode payload
            # passed to canonical_json_bytes remains self-describing within encode state.
            "virtual_token_reserves_atomic": state.virtual_token_reserves_atomic,
        }
    )


def _decode_state(payload: bytes) -> PumpCurveStateV1:
    # Execute the decode state workflow in explicit, reviewable steps.
    try:
        document: Any = json.loads(payload)
    except (TypeError, ValueError, UnicodeDecodeError) as error:
        raise ProtocolContractError(ProtocolContractErrorCode.MALFORMED_PROTOCOL_PAYLOAD) from error
    if (
        # Keep isinstance visible while evaluating the state fields, payload and
        # isinstance guard.
        not isinstance(document, dict)
        or set(document) != _STATE_FIELDS
        or canonical_json_bytes(document) != payload
    ):
        raise ProtocolContractError(ProtocolContractErrorCode.MALFORMED_PROTOCOL_PAYLOAD)
    # Keep expected failures inside the decode state error boundary.
    try:
        # Perform the protected decode state operation before explicit failure handling.
        return PumpCurveStateV1(
            virtual_token_reserves_atomic=_integer(document, "virtual_token_reserves_atomic"),
            virtual_sol_reserves_lamports=_integer(document, "virtual_sol_reserves_lamports"),
            real_token_reserves_atomic=_integer(document, "real_token_reserves_atomic"),
            real_sol_reserves_lamports=_integer(document, "real_sol_reserves_lamports"),
            # Include token total supply atomic in the completed decode state result.
            token_total_supply_atomic=_integer(document, "token_total_supply_atomic"),
            lifecycle=PumpCurveLifecycle(_string(document, "lifecycle")),
            mode=PumpMode(_string(document, "mode")),
        )
    except (TypeError, ValueError) as error:
        # Fail the decode state path with ProtocolContractError for malformed protocol
        # payload and protocol contract error code; do not continue ambiguously.
        raise ProtocolContractError(ProtocolContractErrorCode.MALFORMED_PROTOCOL_PAYLOAD) from error


def _integer(document: dict[str, object], field: str) -> int:
    # Execute the integer workflow in explicit, reviewable steps.
    value = document[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    return value


def _string(document: dict[str, object], field: str) -> str:
    # Execute the string workflow in explicit, reviewable steps.
    value = document[field]
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    return value


__all__ = [
    # Keep the pumpfun launch payload schema id component named inside the all contract.
    "PUMPFUN_LAUNCH_PAYLOAD_SCHEMA_ID",
    "PUMPFUN_LIFECYCLE_PAYLOAD_SCHEMA_ID",
    "PUMPFUN_PROTOCOL_NAME",
    "PUMPFUN_SNIPING_PROTOCOL_BUNDLE_ID",
    "PUMPFUN_TRADE_PAYLOAD_SCHEMA_ID",
    # Keep the pump primitive state v1 component named inside the all contract.
    "PumpPrimitiveStateV1",
    "PumpfunSnipingProtocolRuntime",
    "encode_launch_payload",
    "encode_lifecycle_payload",
    "encode_trade_payload",
    # Complete the all group only after its semantic components are visible.
]
