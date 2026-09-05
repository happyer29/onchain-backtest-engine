# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from dataclasses import replace

import pytest

from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    # Include solana mainnet network id so the chain dependency remains explicit.
    SOLANA_MAINNET_NETWORK_ID,
    ChainPosition,
)
from backtest.domain.execution import ExecutionMode
from backtest.domain.fidelity import OrderingFidelity
from backtest.domain.identifiers import (
    # Include account id so the identifiers dependency remains explicit.
    AccountId,
    AssetId,
    CapabilityId,
    ContentDigest,
    NetworkId,
    ProtocolPayloadSchemaId,
    # Include venue id so the identifiers dependency remains explicit.
    VenueId,
)
from backtest.domain.intents import RoundTripIntent
from backtest.domain.market_events import (
    EventEnvelope,
    # Include token launch event so the market events dependency remains explicit.
    TokenLaunchEvent,
    VenueLifecycleEvent,
    VenueLifecycleKind,
    VenueTradeEvent,
)

# Import sniping contracts at the visible module dependency boundary.
from backtest.engine.sniping_contracts import (
    VIRTUAL_RESERVE_EXPLICIT_SHORTFALL_LIQUIDITY_POLICY_ID,
    # Close the sniping contracts import after its required symbols are visible.
    LaunchTarget,
    ProtocolContractError,
    ProtocolContractErrorCode,
    ProtocolExecutionRejected,
)
from backtest.plugins.protocols.pumpfun import (
    PUMPFUN_LAUNCH_PAYLOAD_SCHEMA_ID,
    PUMPFUN_LIFECYCLE_PAYLOAD_SCHEMA_ID,
    PUMPFUN_PROTOCOL_NAME,
    # Include pumpfun trade payload schema id so the pumpfun dependency remains explicit.
    PUMPFUN_TRADE_PAYLOAD_SCHEMA_ID,
    PumpCurveLifecycle,
    PumpCurveStateV1,
    PumpFeeProfile,
    PumpfunSnipingProtocolRuntime,
    # Include pump mode so the pumpfun dependency remains explicit.
    PumpMode,
    buy_quote,
    encode_launch_payload,
    encode_lifecycle_payload,
    encode_trade_payload,
    # Close the pumpfun import after its required symbols are visible.
)
from backtest.plugins.protocols.pumpfun.model import PumpSellLiquidityPolicy
from backtest.plugins.strategies.pumpfun_sniping import PumpfunSnipingStrategy

SOL = AssetId("SOL")
TOKEN = AssetId("TOKEN")
VENUE = VenueId("pump-curve")
# Bind profile once as an explicit module-level contract.
PROFILE = PumpFeeProfile.static_95_30(
    profile_id="pump-static-95-30-test-v1",
    effective_from_unix_s=1_700_000_000,
    effective_until_unix_s=1_800_000_000,
)


# Define state as one focused operation with an explicit boundary.
def _state(**changes: object) -> PumpCurveStateV1:
    # Execute the state workflow in explicit, reviewable steps.
    value = PumpCurveStateV1(
        virtual_token_reserves_atomic=1_073_000_000_000_000,
        virtual_sol_reserves_lamports=30_000_000_000,
        real_token_reserves_atomic=793_100_000_000_000,
        real_sol_reserves_lamports=100_000_000_000,
        # Pass token total supply atomic explicitly so PumpCurveStateV1 receives a
        # reviewable active and normal input in state.
        token_total_supply_atomic=1_000_000_000_000_000,
        lifecycle=PumpCurveLifecycle.ACTIVE,
        mode=PumpMode.NORMAL,
    )
    return replace(value, **changes)


# Define envelope as one focused operation with an explicit boundary.
def _envelope(event_index: int, *, group: int = 1) -> EventEnvelope:
    # Execute the envelope workflow in explicit, reviewable steps.
    return EventEnvelope(
        position=ChainPosition(
            network_id=SOLANA_MAINNET_NETWORK_ID,
            position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            block_ordinal=100 + group,
            # Pass transaction index explicitly so ChainPosition receives a reviewable
            # solana mainnet network id and block32 transaction32 position schema id input
            # in envelope.
            transaction_index=0,
            event_index=event_index,
        ),
        transaction_group_id=ContentDigest(f"{group:064x}"),
        source_record_id=ContentDigest(f"{group * 10 + event_index + 1:064x}"),
        # Include canonical event id in the completed envelope result.
        canonical_event_id=ContentDigest(f"{group * 100 + event_index + 1:064x}"),
        stable_causal_id=ContentDigest(f"{group * 1000 + event_index + 1:064x}"),
        capability_id=CapabilityId("pumpfun.test.v1"),
        protocol=PUMPFUN_PROTOCOL_NAME,
        protocol_version="pump-program-v1",
        # Pass ordering fidelity explicitly so EventEnvelope receives a reviewable 064x
        # and v1 input in envelope.
        ordering_fidelity=OrderingFidelity.INSTRUCTION_EXACT,
    )


def _launch(state: PumpCurveStateV1, *, group: int = 1) -> TokenLaunchEvent:
    # Execute the launch workflow in explicit, reviewable steps.
    return TokenLaunchEvent(
        envelope=_envelope(0, group=group),
        asset_id=TOKEN,
        developer_id=AccountId("developer"),
        creation_user_id=AccountId("payer"),
        # Pass venue id explicitly so TokenLaunchEvent receives a reviewable developer and
        # payer input in launch.
        venue_id=VENUE,
        quote_asset_id=SOL,
        protocol_payload_schema=PUMPFUN_LAUNCH_PAYLOAD_SCHEMA_ID,
        protocol_payload=encode_launch_payload(state),
    )


# Define trade as one focused operation with an explicit boundary.
def _trade(state_after: PumpCurveStateV1, *, group: int = 1) -> VenueTradeEvent:
    # Execute the trade workflow in explicit, reviewable steps.
    return VenueTradeEvent(
        envelope=_envelope(1, group=group),
        venue_id=VENUE,
        sold_asset_id=SOL,
        bought_asset_id=TOKEN,
        # Pass sold amount atomic explicitly so VenueTradeEvent receives a reviewable
        # envelope and encode trade payload input in trade.
        sold_amount_atomic=100,
        bought_amount_atomic=1_000,
        fee_components=(),
        protocol_payload_schema=PUMPFUN_TRADE_PAYLOAD_SCHEMA_ID,
        protocol_payload=encode_trade_payload(state_after),
        # Complete VenueTradeEvent only after its envelope and encode trade payload inputs are
        # visible in trade.
    )


def _runtime() -> PumpfunSnipingProtocolRuntime:
    # Execute the runtime workflow in explicit, reviewable steps.
    return PumpfunSnipingProtocolRuntime(
        quote_asset_id=SOL,
        fee_profile=PROFILE,
        protocol_version="pump-program-v1",
    )


# Define intent as one focused operation with an explicit boundary.
def _intent(
    target: LaunchTarget,
    *,
    execution_mode: ExecutionMode = ExecutionMode.EXOGENOUS_REPLAY,
) -> RoundTripIntent | None:
    # Execute the intent workflow in explicit, reviewable steps.
    strategy = PumpfunSnipingStrategy(
        quote_asset_id=SOL,
        gross_buy_budget_atomic=1_000_000_000,
        buy_slippage_bps=100,
        sell_slippage_bps=100,
        # Pass sell delay transactions explicitly so PumpfunSnipingStrategy receives a
        # reviewable sol input in intent.
        sell_delay_transactions=1,
    )
    decision = strategy.decide(
        target,
        decision_time_ns=1_750_000_000_000_000_000,
        # Complete decide only after its target inputs are visible in intent.
    )
    assert decision.intent is not None
    # Strategy wiring selects the mode in a later slice; adapt its typed intent here.
    return replace(decision.intent, execution_mode=execution_mode)


def test_bundled_trade_is_applied_before_post_group_reference_quote() -> None:
    # Execute the test bundled trade is applied before post group reference quote workflow
    # in explicit, reviewable steps.
    runtime = _runtime()
    initial = _state()
    bundled = replace(
        initial,
        virtual_token_reserves_atomic=1_000_000_000_000_000,
        # Pass virtual sol reserves lamports explicitly so replace receives a reviewable
        # initial input in test bundled trade is applied before post group reference
        # quote.
        virtual_sol_reserves_lamports=32_000_000_000,
        real_token_reserves_atomic=720_100_000_000_000,
        real_sol_reserves_lamports=102_000_000_000,
    )

    (target,) = runtime.apply_historical_group(
        # Keep the initial _launch step visible while building (target,).
        (_launch(initial), _trade(bundled)),
        effective_at_unix_s=1_750_000_000,
    )
    intent = _intent(target)
    assert intent is not None
    # Assemble actual once so the test bundled trade is applied before post group
    # reference quote workflow shares one value.
    actual = runtime.quote_buy(intent, effective_at_unix_s=1_750_000_000)
    expected = buy_quote(
        bundled,
        spendable_gross_sol_lamports=1_000_000_000,
        fee_profile=PROFILE,
        # Pass effective at unix s explicitly so buy_quote receives a reviewable bundled
        # and profile input in test bundled trade is applied before post group reference
        # quote.
        effective_at_unix_s=1_750_000_000,
    )

    assert actual.amount_out_atomic == expected.tokens_out_atomic
    assert actual.liquidity_evidence is None


def test_virtual_sell_runtime_and_primitive_path_expose_exact_shortfall() -> None:
    """Object, primitive, and valuation paths share one synthetic quote contract."""

    runtime = _runtime()
    state = _state(real_sol_reserves_lamports=100_000_000)
    (target,) = runtime.apply_historical_group(
        (_launch(state),),
        effective_at_unix_s=1_750_000_000,
    )
    strict_intent = _intent(target)
    virtual_intent = _intent(
        target,
        execution_mode=ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT,
    )
    assert strict_intent is not None and virtual_intent is not None
    # Mode selection must not alter buy-side real-token or quote semantics.
    strict_buy = runtime.quote_buy(strict_intent, effective_at_unix_s=1_750_000_000)
    virtual_buy = runtime.quote_buy(virtual_intent, effective_at_unix_s=1_750_000_000)
    assert virtual_buy == strict_buy

    with pytest.raises(ProtocolExecutionRejected, match="INSUFFICIENT_REAL_SOL_RESERVES"):
        runtime.quote_sell(
            strict_intent,
            tokens_in_atomic=34_199_203_120_618,
            effective_at_unix_s=1_750_000_000,
        )
    object_quote = runtime.quote_sell(
        virtual_intent,
        tokens_in_atomic=34_199_203_120_618,
        effective_at_unix_s=1_750_000_000,
    )

    primitive_state = runtime.decode_primitive_state_payload(encode_launch_payload(state))
    primitive_quote = runtime.quote_sell_from_primitive_state(
        virtual_intent,
        primitive_state,
        tokens_in_atomic=34_199_203_120_618,
        effective_at_unix_s=1_750_000_000,
    )
    assert primitive_quote == object_quote

    evidence = object_quote.liquidity_evidence
    assert evidence is not None
    assert evidence.policy_id == VIRTUAL_RESERVE_EXPLICIT_SHORTFALL_LIQUIDITY_POLICY_ID
    assert evidence.required_output_atomic == 926_640_924
    assert evidence.observed_available_output_atomic == 100_000_000
    # Only the positive deficit receives a deterministic external source identity.
    assert evidence.synthetic_shortfall_atomic == 826_640_924
    assert evidence.synthetic_source_account_id is not None

    valuation = runtime.valuation_quote(
        virtual_intent,
        tokens_in_atomic=34_199_203_120_618,
        effective_at_unix_s=1_750_000_000,
    )
    primitive_valuation = runtime.valuation_quote_from_primitive_state(
        virtual_intent,
        primitive_state,
        None,
        None,
        tokens_in_atomic=34_199_203_120_618,
        effective_at_unix_s=1_750_000_000,
    )
    assert valuation is not None and primitive_valuation is not None
    assert valuation.quote == primitive_valuation.quote == object_quote

    # Keep both network identities valid so this check exercises account derivation.
    other_network = NetworkId("solana:11111111111111111111111111111112")
    other_position = replace(virtual_intent.target_position, network_id=other_network)
    other_intent = replace(virtual_intent, target_position=other_position)
    # The alternate genesis changes only the external settlement account's identity.
    other_quote = runtime.quote_sell(
        other_intent,
        tokens_in_atomic=34_199_203_120_618,
        effective_at_unix_s=1_750_000_000,
    )
    # The liquidity evidence must retain that network separation after protocol quoting.
    assert other_quote.liquidity_evidence is not None
    assert (
        other_quote.liquidity_evidence.synthetic_source_account_id
        != evidence.synthetic_source_account_id
    )


def test_virtual_sell_with_sufficient_real_liquidity_has_no_synthetic_account() -> None:
    runtime = _runtime()
    state = _state()
    (target,) = runtime.apply_historical_group(
        (_launch(state),),
        effective_at_unix_s=1_750_000_000,
    )
    intent = _intent(target, execution_mode=ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT)
    assert intent is not None

    quote = runtime.quote_sell(
        intent,
        tokens_in_atomic=34_199_203_120_618,
        effective_at_unix_s=1_750_000_000,
    )
    evidence = quote.liquidity_evidence
    assert evidence is not None
    # Potential and actual synthetic funding stay absent when real reserves cover gross.
    assert evidence.synthetic_shortfall_atomic == 0
    assert evidence.synthetic_source_account_id is None
    assert (
        evidence.policy_id
        == PumpSellLiquidityPolicy.VIRTUAL_RESERVE_OUTPUT_WITH_EXPLICIT_SYNTHETIC_SHORTFALL_V1.value
    )


def test_group_application_is_atomic_on_malformed_bundled_payload() -> None:
    # Execute the test group application is atomic on malformed bundled payload workflow
    # in explicit, reviewable steps.
    runtime = _runtime()
    malformed = replace(
        _trade(_state()),
        protocol_payload_schema=ProtocolPayloadSchemaId("wrong-trade-state-v1"),
    )

    # Acquire raises, protocol contract error and pytest at an explicit test group
    # application is atomic on malformed bundled payload context boundary so cleanup
    # remains scoped.
    with pytest.raises(ProtocolContractError) as rejected:
        # Keep raises, protocol contract error and pytest active only for the bounded test
        # group application is atomic on malformed bundled payload operation.
        runtime.apply_historical_group(
            (_launch(_state()), malformed),
            effective_at_unix_s=1_750_000_000,
        )
    assert rejected.value.code is ProtocolContractErrorCode.UNSUPPORTED_PAYLOAD_SCHEMA

    # The failed group did not leave a partial curve behind.
    assert (
        len(
            runtime.apply_historical_group(
                (_launch(_state()),),
                effective_at_unix_s=1_750_000_000,
                # Complete apply_historical_group only after its launch and state inputs are
                # visible in test group application is atomic on malformed bundled payload.
            )
        )
        == 1
    )


def test_migration_rejects_original_pump_execution_but_keeps_stale_valuation() -> None:
    # Execute the test migration rejects original pump execution but keeps stale valuation
    # workflow in explicit, reviewable steps.
    runtime = _runtime()
    (target,) = runtime.apply_historical_group(
        (_launch(_state()),),
        effective_at_unix_s=1_750_000_000,
    )
    # Assemble intent once so the test migration rejects original pump execution but keeps
    # stale valuation workflow shares one value.
    intent = _intent(target)
    assert intent is not None
    migrated = replace(_state(), lifecycle=PumpCurveLifecycle.MIGRATED)
    runtime.apply_historical_group(
        (
            # Pass venue lifecycle event explicitly to apply_historical_group for migrated
            # and venue lifecycle event.
            VenueLifecycleEvent(
                envelope=_envelope(0, group=2),
                venue_id=VENUE,
                lifecycle_kind=VenueLifecycleKind.MIGRATED,
                protocol_payload_schema=PUMPFUN_LIFECYCLE_PAYLOAD_SCHEMA_ID,
                # Pass protocol payload explicitly to apply_historical_group for migrated
                # and venue lifecycle event.
                protocol_payload=encode_lifecycle_payload(migrated),
            ),
        ),
        effective_at_unix_s=1_760_000_000,
    )

    # Acquire raises, protocol execution rejected and pytest at an explicit test migration
    # rejects original pump execution but keeps stale valuation context boundary so
    # cleanup remains scoped.
    with pytest.raises(ProtocolExecutionRejected, match="PUMPSWAP_ROUTING_FORBIDDEN"):
        # Keep raises, protocol execution rejected and pytest active only for the bounded
        # test migration rejects original pump execution but keeps stale valuation
        # operation.
        runtime.quote_sell(
            intent,
            tokens_in_atomic=1_000_000_000,
            effective_at_unix_s=1_750_000_000,
        )
    # Assemble valuation once so the test migration rejects original pump execution but
    # keeps stale valuation workflow shares one value.
    valuation = runtime.valuation_quote(
        intent,
        tokens_in_atomic=1_000_000_000,
        effective_at_unix_s=1_900_000_000,
    )
    # Verify valuation is not None before this scenario is accepted.
    assert valuation is not None
    assert valuation.stale_pre_migration


def test_unknown_mode_stops_group_instead_of_filtering_launch() -> None:
    # Execute the test unknown mode stops group instead of filtering launch workflow in
    # explicit, reviewable steps.
    runtime = _runtime()
    with pytest.raises(ProtocolContractError) as rejected:
        # Keep raises, protocol contract error and pytest active only for the bounded test
        # unknown mode stops group instead of filtering launch operation.
        runtime.apply_historical_group(
            (_launch(_state(mode=PumpMode.UNKNOWN)),),
            effective_at_unix_s=1_750_000_000,
        )
    assert rejected.value.code is ProtocolContractErrorCode.UNKNOWN_PROGRAM_MODE


def test_mayhem_launch_fails_before_target_or_curve_commit() -> None:
    # Mayhem should have been excluded by preparation; runtime rejects stale input before
    # returning a target that the strategy could turn into cooldown or an order.
    runtime = _runtime()
    with pytest.raises(ProtocolContractError) as rejected:
        runtime.apply_historical_group(
            (_launch(_state(mode=PumpMode.MAYHEM)),),
            effective_at_unix_s=1_750_000_000,
        )
    assert rejected.value.code is ProtocolContractErrorCode.EXCLUDED_PROGRAM_MODE

    # A normal launch of the same venue remains valid, proving the rejected candidate was
    # never committed to protocol state.
    (target,) = runtime.apply_historical_group(
        (_launch(_state(), group=2),),
        effective_at_unix_s=1_750_000_001,
    )
    assert target.venue_id == VENUE


def test_primitive_launch_validation_rejects_mayhem_for_optimized_path() -> None:
    # The mmap backend validates the decoded primitive before constructing LaunchTarget.
    runtime = _runtime()
    state = runtime.decode_primitive_state_payload(
        encode_launch_payload(_state(mode=PumpMode.MAYHEM))
    )

    with pytest.raises(ProtocolContractError) as rejected:
        runtime.validate_primitive_launch_state(state)
    assert rejected.value.code is ProtocolContractErrorCode.EXCLUDED_PROGRAM_MODE


@pytest.mark.parametrize("mode", (PumpMode.NORMAL, PumpMode.TOKEN_2022, PumpMode.CASHBACK))
def test_non_mayhem_launch_modes_remain_eligible(mode: PumpMode) -> None:
    # The universe migration narrows only Mayhem and preserves supported eligible modes.
    (target,) = _runtime().apply_historical_group(
        (_launch(_state(mode=mode)),),
        effective_at_unix_s=1_750_000_000,
    )

    assert target.asset_id == TOKEN
