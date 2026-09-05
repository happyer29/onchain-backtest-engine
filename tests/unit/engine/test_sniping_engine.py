# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from typing import cast

import pytest

from backtest.domain.account_requirements import (
    AccountComponentLifecycle,
    AccountRequirement,
    AccountRequirementScope,
    PricedAccountRequirement,
)
from backtest.domain.chain import (
    # Include block32 transaction32 position schema id so the chain dependency remains
    # explicit.
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
    ChainPosition,
)
from backtest.domain.execution import ExecutionMode, Fill

# Import fidelity at the visible module dependency boundary.
from backtest.domain.fidelity import OrderingFidelity
from backtest.domain.identifiers import (
    AccountId,
    AssetId,
    BundleId,
    # Include capability id so the identifiers dependency remains explicit.
    CapabilityId,
    ContentDigest,
    DatasetRevisionId,
    LogicalContentHash,
    VenueId,
    # Close the identifiers import after its required symbols are visible.
)
from backtest.domain.intents import RoundTripIntent
from backtest.domain.ledger import AccountKind, LedgerCorrelationKind, LedgerTransaction
from backtest.domain.market_events import (
    CanonicalEvent,
    # Include event envelope so the market events dependency remains explicit.
    EventEnvelope,
    TokenLaunchEvent,
    VenueLifecycleEvent,
    VenueLifecycleKind,
    VenueTradeEvent,
    # Close the market events import after its required symbols are visible.
)
from backtest.domain.roundtrips import (
    MtmStatus,
    RoundTripRecord,
    RoundTripStatus,
)
from backtest.domain.time import BlockRange
from backtest.engine.replay import ObservationDelivery, ReplayBoundary
from backtest.engine.sniping import (
    # Include sniping engine error so the sniping dependency remains explicit.
    SnipingEngineError,
    SnipingEngineErrorCode,
    SnipingReferenceEngine,
    SnipingRunConfig,
    SnipingRunSummary,
    # Include sniping valuation status so the sniping dependency remains explicit.
    SnipingValuationStatus,
)
from backtest.engine.sniping_contracts import (
    REAL_RESERVE_CAPPED_LIQUIDITY_POLICY_ID,
    VIRTUAL_RESERVE_EXPLICIT_SHORTFALL_LIQUIDITY_POLICY_ID,
    LaunchTarget,
    NetworkCostQuote,
    ProtocolLiquidityEvidence,
    # Include protocol quote so the sniping contracts dependency remains explicit.
    ProtocolQuote,
    ProtocolQuoteSide,
    ValuationQuote,
    synthetic_liquidity_account_id,
)

# Import transaction clock at the visible module dependency boundary.
from backtest.engine.transaction_clock import (
    CompactTransactionClock,
    TransactionClockError,
    TransactionClockErrorCode,
)
from backtest.engine.wallet_accounts import WalletUvaInitialState

# Import solana at the visible module dependency boundary.
from backtest.plugins.networks.solana import (
    SOLANA_LEGACY_V0_FEE_FORMULA_V1,
    SolanaAccountCostProfile,
    SolanaAccountDepositCost,
    SolanaFeeProfile,
    # Include solana sniping cost model so the solana dependency remains explicit.
    SolanaSnipingCostModel,
    SolanaTransactionFormat,
)
from backtest.plugins.protocols.pumpfun import (
    PUMPFUN_LAUNCH_PAYLOAD_SCHEMA_ID,
    PUMPFUN_LEGACY_ATA_SCHEMA_ID,
    # Include pumpfun lifecycle payload schema id so the pumpfun dependency remains
    # explicit.
    PUMPFUN_LIFECYCLE_PAYLOAD_SCHEMA_ID,
    PUMPFUN_PROTOCOL_NAME,
    PUMPFUN_TOKEN_2022_ATA_SCHEMA_ID,
    PUMPFUN_TRADE_PAYLOAD_SCHEMA_ID,
    PUMPFUN_UVA_SCHEMA_ID,
    PumpCurveLifecycle,
    PumpCurveStateV1,
    # Include pump fee profile so the pumpfun dependency remains explicit.
    PumpFeeProfile,
    PumpfunSnipingProtocolRuntime,
    PumpMode,
    encode_launch_payload,
    encode_lifecycle_payload,
    # Include encode trade payload so the pumpfun dependency remains explicit.
    encode_trade_payload,
    pumpfun_account_requirements,
)
from backtest.plugins.strategies import PumpfunSnipingStrategy

SOL = AssetId("SOL")
NETWORK_FEE_ASSET = AssetId("NETWORK-FEE")
# Bind account deposit asset once as an explicit module-level contract.
ACCOUNT_DEPOSIT_ASSET = AssetId("ACCOUNT-DEPOSIT")
BASE_TIME_S = 1_750_000_000


# Keep the source contract and validation rules together.
@dataclass(frozen=True)
class _Source:
    values: tuple[CanonicalEvent, ...]

    @property
    def dataset_revision_id(self) -> DatasetRevisionId:
        # Return the completed source dataset revision id result without a hidden
        # fallback.
        return DatasetRevisionId("1" * 64)

    @property
    def logical_content_hash(self) -> LogicalContentHash:
        return LogicalContentHash("2" * 64)

    @property
    # Define source replay semantics id as one focused operation with an explicit
    # boundary.
    def replay_semantics_id(self) -> ContentDigest:
        return ContentDigest("3" * 64)

    @property
    def event_count(self) -> int:
        return len(self.values)

    # Define source boundaries as one focused operation with an explicit boundary.
    def boundaries(self) -> tuple[ReplayBoundary, ...]:
        return tuple(ReplayBoundary.from_position(event.envelope.position) for event in self.values)

    def events(self) -> Iterator[CanonicalEvent]:
        yield from self.values

    def event_at(self, event_row_index: int) -> CanonicalEvent:
        # Return the completed source event at result without a hidden fallback.
        return self.values[event_row_index]


# Keep the schedule contract and validation rules together.
@dataclass(frozen=True)
class _Schedule:
    values: tuple[ObservationDelivery, ...]
    input_event_count: int
    outside_horizon_count: int = 0

    # Apply property semantics to the following schedule delivery count contract.
    @property
    def delivery_count(self) -> int:
        return len(self.values)

    def deliveries(self) -> Iterator[ObservationDelivery]:
        yield from self.values


# Keep the sink contract and validation rules together.
@dataclass
class _Sink:
    audits: list[dict[str, object]] = field(default_factory=list)
    ledger: list[LedgerTransaction] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    # Declare roundtrips explicitly in the sink contract.
    roundtrips: list[RoundTripRecord] = field(default_factory=list)

    def append_audit(self, record: dict[str, object]) -> None:
        self.audits.append(record)

    def append_ledger(self, transaction: LedgerTransaction) -> None:
        self.ledger.append(transaction)

    # Define sink append fill as one focused operation with an explicit boundary.
    def append_fill(self, fill: Fill) -> None:
        self.fills.append(fill)

    def append_roundtrip(self, record: RoundTripRecord) -> None:
        self.roundtrips.append(record)


class _ScriptedProtocol:
    """Minimal generic protocol double for exact slippage boundary vectors."""

    bundle_id = BundleId("4" * 64)

    def __init__(
        self,
        *,
        buy_outputs: tuple[int, int],
        # Keep the sell outputs input explicit in the init contract.
        sell_outputs: tuple[int, int],
        sell_liquidity_evidence: ProtocolLiquidityEvidence | None = None,
    ) -> None:
        # Execute the scripted protocol init workflow in explicit, reviewable steps.
        self._buy_outputs = iter(buy_outputs)
        self._sell_outputs = iter(sell_outputs)
        self._sell_liquidity_evidence = sell_liquidity_evidence

    def apply_historical_group(
        self,
        events: tuple[CanonicalEvent, ...],
        # Close the apply historical group signature after its explicit inputs.
        *,
        effective_at_unix_s: int,
    ) -> tuple[LaunchTarget, ...]:
        # Execute the scripted protocol apply historical group workflow in explicit,
        # reviewable steps.
        del effective_at_unix_s
        return tuple(
            LaunchTarget(
                target_event_id=event.envelope.canonical_event_id,
                position=event.envelope.position,
                # Pass asset id explicitly so LaunchTarget receives a reviewable canonical
                # event id and envelope input in scripted protocol apply historical group.
                asset_id=event.asset_id,
                developer_id=event.developer_id,
                creation_user_id=event.creation_user_id,
                venue_id=event.venue_id,
                quote_asset_id=event.quote_asset_id,
                # Complete LaunchTarget only after its canonical event id and envelope inputs
                # are visible in scripted protocol apply historical group.
            )
            for event in events
            if isinstance(event, TokenLaunchEvent)
        )

    def quote_buy(
        # Keep the remaining quote buy inputs visible at the scripted protocol quote buy
        # boundary.
        self,
        intent: RoundTripIntent,
        *,
        effective_at_unix_s: int,
    ) -> ProtocolQuote:
        # Execute the scripted protocol quote buy workflow in explicit, reviewable steps.
        del effective_at_unix_s
        output = next(self._buy_outputs)
        return _scripted_quote(
            intent=intent,
            side=ProtocolQuoteSide.BUY,
            # Pass amount in explicitly so _scripted_quote receives a reviewable buy and
            # intent input in scripted protocol quote buy.
            amount_in=100,
            amount_out=output,
        )

    def account_requirements(
        self,
        intent: RoundTripIntent,
    ) -> tuple[AccountRequirement, ...]:
        """Use the normal Pump account contract for the scripted quote path."""

        del intent
        return pumpfun_account_requirements(PumpMode.NORMAL)

    def quote_sell(
        self,
        # Keep the intent input explicit in the quote sell contract.
        intent: RoundTripIntent,
        *,
        tokens_in_atomic: int,
        effective_at_unix_s: int,
    ) -> ProtocolQuote:
        # Execute the scripted protocol quote sell workflow in explicit, reviewable steps.
        del effective_at_unix_s
        output = next(self._sell_outputs)
        quote = _scripted_quote(
            intent=intent,
            side=ProtocolQuoteSide.SELL,
            # Pass amount in explicitly so _scripted_quote receives a reviewable sell and
            # intent input in scripted protocol quote sell.
            amount_in=tokens_in_atomic,
            amount_out=output,
        )
        # A configured override models an untrusted protocol returning bad evidence.
        if self._sell_liquidity_evidence is None:
            return quote
        return replace(quote, liquidity_evidence=self._sell_liquidity_evidence)

    def valuation_quote(
        self,
        # Keep the intent input explicit in the valuation quote contract.
        intent: RoundTripIntent,
        *,
        tokens_in_atomic: int,
        effective_at_unix_s: int,
    ) -> ValuationQuote | None:
        # Execute the scripted protocol valuation quote workflow in explicit, reviewable
        # steps.
        del intent, tokens_in_atomic, effective_at_unix_s
        return None


class _SplitAssetNetworkCosts:
    """Network-cost double whose assets deliberately differ from venue quote."""

    bundle_id = BundleId("5" * 64)
    fee_collector_account_id = AccountId("network-fee:split-asset-test")

    def quote_buy(
        self,
        *,
        # Keep the effective at unix s input explicit in the quote buy contract.
        effective_at_unix_s: int,
        requirements: tuple[AccountRequirement, ...],
    ) -> NetworkCostQuote:
        # Execute the split asset network costs quote buy workflow in explicit, reviewable
        # steps.
        del effective_at_unix_s
        priced = tuple(
            PricedAccountRequirement(
                item,
                ACCOUNT_DEPOSIT_ASSET,
                5 if item.scope is AccountRequirementScope.MINT else 2,
            )
            for item in requirements
        )
        return NetworkCostQuote(
            fee_asset_id=NETWORK_FEE_ASSET,
            base_fee_atomic=3,
            # Pass priority fee atomic explicitly so NetworkCostQuote receives a
            # reviewable network fee asset and account deposit asset input in split asset
            # network costs quote buy.
            priority_fee_atomic=2,
            account_requirements=priced,
        )

    def quote_sell(self, *, effective_at_unix_s: int) -> NetworkCostQuote:
        # Execute the split asset network costs quote sell workflow in explicit,
        # reviewable steps.
        del effective_at_unix_s
        return NetworkCostQuote(
            fee_asset_id=NETWORK_FEE_ASSET,
            base_fee_atomic=4,
            # Pass priority fee atomic explicitly so NetworkCostQuote receives a
            # reviewable network fee asset and account deposit asset input in split asset
            # network costs quote sell.
            priority_fee_atomic=2,
        )


def _scripted_quote(
    *,
    intent: RoundTripIntent,
    # Keep the side input explicit in the scripted quote contract.
    side: ProtocolQuoteSide,
    amount_in: int,
    amount_out: int,
) -> ProtocolQuote:
    # Execute the scripted quote workflow in explicit, reviewable steps.
    is_buy = side is ProtocolQuoteSide.BUY
    return ProtocolQuote(
        side=side,
        input_asset_id=intent.quote_asset_id if is_buy else intent.asset_id,
        output_asset_id=intent.asset_id if is_buy else intent.quote_asset_id,
        # Pass amount in atomic explicitly so ProtocolQuote receives a reviewable
        # scripted-protocol-fee and scripted-creator-fee input in scripted quote.
        amount_in_atomic=amount_in,
        amount_out_atomic=amount_out,
        venue_input_atomic=amount_in,
        venue_output_atomic=amount_out,
        protocol_fee_atomic=0,
        # Pass creator fee atomic explicitly so ProtocolQuote receives a reviewable
        # scripted-protocol-fee and scripted-creator-fee input in scripted quote.
        creator_fee_atomic=0,
        cashback_receivable_atomic=0,
        protocol_fee_account_id=AccountId("scripted-protocol-fee"),
        creator_fee_account_id=AccountId("scripted-creator-fee"),
        cashback_source_account_id=AccountId("scripted-cashback-source"),
        liquidity_evidence=(
            None
            if is_buy
            else ProtocolLiquidityEvidence(
                policy_id=REAL_RESERVE_CAPPED_LIQUIDITY_POLICY_ID,
                asset_id=intent.quote_asset_id,
                required_output_atomic=amount_out,
                observed_available_output_atomic=amount_out,
                synthetic_shortfall_atomic=0,
                synthetic_source_account_id=None,
            )
        ),
        # Complete ProtocolQuote only after its scripted-protocol-fee and scripted-creator-fee
        # inputs are visible in scripted quote.
    )


def _state(**changes: object) -> PumpCurveStateV1:
    # Execute the state workflow in explicit, reviewable steps.
    return replace(
        PumpCurveStateV1(
            virtual_token_reserves_atomic=1_073_000_000_000_000,
            virtual_sol_reserves_lamports=30_000_000_000,
            real_token_reserves_atomic=793_100_000_000_000,
            # Pass real sol reserves lamports explicitly so PumpCurveStateV1 receives a
            # reviewable active and normal input in state.
            real_sol_reserves_lamports=100_000_000_000,
            token_total_supply_atomic=1_000_000_000_000_000,
            lifecycle=PumpCurveLifecycle.ACTIVE,
            mode=PumpMode.NORMAL,
        ),
        # Pass changes explicitly so replace receives a reviewable active and normal input
        # in state.
        **changes,
    )


def _position(block: int, transaction: int, event_index: int | None) -> ChainPosition:
    # Execute the position workflow in explicit, reviewable steps.
    return ChainPosition(
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        block_ordinal=block,
        transaction_index=transaction,
        # Pass event index explicitly so ChainPosition receives a reviewable solana
        # mainnet network id and block32 transaction32 position schema id input in
        # position.
        event_index=event_index,
    )


def _envelope(
    block: int,
    transaction: int,
    # Keep the event index input explicit in the envelope contract.
    event_index: int,
    *,
    group: int,
) -> EventEnvelope:
    # Execute the envelope workflow in explicit, reviewable steps.
    identity = group * 100 + event_index + 1
    return EventEnvelope(
        position=_position(block, transaction, event_index),
        transaction_group_id=ContentDigest(f"{group:064x}"),
        source_record_id=ContentDigest(f"{identity:064x}"),
        # Include canonical event id in the completed envelope result.
        canonical_event_id=ContentDigest(f"{identity + 10_000:064x}"),
        stable_causal_id=ContentDigest(f"{identity + 20_000:064x}"),
        capability_id=CapabilityId("pumpfun.fixture.v1"),
        protocol=PUMPFUN_PROTOCOL_NAME,
        protocol_version="pump-program-v1",
        # Pass ordering fidelity explicitly so EventEnvelope receives a reviewable 064x
        # and v1 input in envelope.
        ordering_fidelity=OrderingFidelity.INSTRUCTION_EXACT,
    )


def _launch(
    *,
    block: int = 100,
    # Keep the transaction input explicit in the launch contract.
    transaction: int = 0,
    event_index: int = 0,
    group: int = 1,
    token: str = "TOKEN",
    venue: str = "curve",
    # Keep the developer input explicit in the launch contract.
    developer: str = "developer",
    state: PumpCurveStateV1 | None = None,
) -> TokenLaunchEvent:
    # Execute the launch workflow in explicit, reviewable steps.
    return TokenLaunchEvent(
        envelope=_envelope(block, transaction, event_index, group=group),
        asset_id=AssetId(token),
        developer_id=AccountId(developer),
        creation_user_id=AccountId(f"payer-{token}"),
        # Include venue id in the completed launch result.
        venue_id=VenueId(venue),
        quote_asset_id=SOL,
        protocol_payload_schema=PUMPFUN_LAUNCH_PAYLOAD_SCHEMA_ID,
        protocol_payload=encode_launch_payload(_state() if state is None else state),
    )


# Define trade as one focused operation with an explicit boundary.
def _trade(
    state_after: PumpCurveStateV1,
    *,
    block: int,
    transaction: int,
    # Keep the event index input explicit in the trade contract.
    event_index: int,
    group: int,
    token: str = "TOKEN",
    venue: str = "curve",
) -> VenueTradeEvent:
    # Execute the trade workflow in explicit, reviewable steps.
    return VenueTradeEvent(
        envelope=_envelope(block, transaction, event_index, group=group),
        venue_id=VenueId(venue),
        sold_asset_id=SOL,
        bought_asset_id=AssetId(token),
        # Pass sold amount atomic explicitly so VenueTradeEvent receives a reviewable
        # envelope and venue id input in trade.
        sold_amount_atomic=1,
        bought_amount_atomic=1,
        fee_components=(),
        protocol_payload_schema=PUMPFUN_TRADE_PAYLOAD_SCHEMA_ID,
        protocol_payload=encode_trade_payload(state_after),
        # Complete VenueTradeEvent only after its envelope and venue id inputs are visible in
        # trade.
    )


def _lifecycle(
    state_after: PumpCurveStateV1,
    *,
    block: int,
    # Keep the transaction input explicit in the lifecycle contract.
    transaction: int,
    group: int,
    kind: VenueLifecycleKind = VenueLifecycleKind.MIGRATED,
) -> VenueLifecycleEvent:
    # Execute the lifecycle workflow in explicit, reviewable steps.
    return VenueLifecycleEvent(
        envelope=_envelope(block, transaction, 0, group=group),
        venue_id=VenueId("curve"),
        lifecycle_kind=kind,
        protocol_payload_schema=PUMPFUN_LIFECYCLE_PAYLOAD_SCHEMA_ID,
        # Include protocol payload in the completed lifecycle result.
        protocol_payload=encode_lifecycle_payload(state_after),
    )


def _clock(
    rows: tuple[tuple[int, int, int], ...] = (
        (100, 501, BASE_TIME_S),
        # Keep the base time s input explicit in the clock contract.
        (101, 0, BASE_TIME_S + 1),
        (102, 2, BASE_TIME_S + 2),
        (103, 1, BASE_TIME_S + 3),
    ),
) -> CompactTransactionClock:
    # Execute the clock workflow in explicit, reviewable steps.
    prefix: list[int] = []
    total = 0
    for _, count, _ in rows:
        # Process rows inside the bounded clock loop.
        prefix.append(total)
        total += count
    return CompactTransactionClock(
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        # Include block ordinals in the completed clock result.
        block_ordinals=tuple(block for block, _, _ in rows),
        transaction_counts=tuple(count for _, count, _ in rows),
        cumulative_transaction_prefix=tuple(prefix),
        block_time_ns=tuple(time * 1_000_000_000 for _, _, time in rows),
    )


# Define fee as one focused operation with an explicit boundary.
def _fee(profile_id: str, priority_price: int) -> SolanaFeeProfile:
    # Execute the fee workflow in explicit, reviewable steps.
    return SolanaFeeProfile(
        profile_id=profile_id,
        formula_version=SOLANA_LEGACY_V0_FEE_FORMULA_V1,
        transaction_format=SolanaTransactionFormat.V0,
        effective_from_unix_s=1_700_000_000,
        # Pass effective until unix s explicitly so SolanaFeeProfile receives a reviewable
        # v0 and profile id input in fee.
        effective_until_unix_s=1_800_000_000,
        charged_signature_count=1,
        lamports_per_signature=5_000,
        compute_unit_limit=100_000,
        micro_lamports_per_compute_unit=priority_price,
        # Complete SolanaFeeProfile only after its v0 and profile id inputs are visible in
        # fee.
    )


def _components(
    *,
    buy_slippage_bps: int = 0,
    sell_slippage_bps: int = 0,
    # Keep the budget input explicit in the components contract.
    budget: int = 1_000_000_000,
    execution_mode: ExecutionMode = ExecutionMode.EXOGENOUS_REPLAY,
) -> tuple[
    PumpfunSnipingStrategy,
    PumpfunSnipingProtocolRuntime,
    SolanaSnipingCostModel,
    # Close the components signature after its explicit inputs.
]:
    # Execute the components workflow in explicit, reviewable steps.
    strategy = PumpfunSnipingStrategy(
        quote_asset_id=SOL,
        gross_buy_budget_atomic=budget,
        buy_slippage_bps=buy_slippage_bps,
        sell_slippage_bps=sell_slippage_bps,
        execution_mode=execution_mode,
        # Pass sell delay transactions explicitly so PumpfunSnipingStrategy receives a
        # reviewable sol and budget input in components.
        sell_delay_transactions=1,
    )
    protocol = PumpfunSnipingProtocolRuntime(
        quote_asset_id=SOL,
        fee_profile=PumpFeeProfile.static_95_30(
            # Pass profile id explicitly so static_95_30 receives a reviewable pump-
            # static-95-30-engine-v1 input in components.
            profile_id="pump-static-95-30-engine-v1",
            effective_from_unix_s=1_700_000_000,
            effective_until_unix_s=1_800_000_000,
        ),
        protocol_version="pump-program-v1",
        # Complete PumpfunSnipingProtocolRuntime only after its pump-static-95-30-engine-v1
        # and pump-program-v1 inputs are visible in components.
    )
    network = SolanaSnipingCostModel(
        buy_fee_profile=_fee("buy-fee-v1", 10),
        sell_fee_profile=_fee("sell-fee-v1", 20),
        account_cost_profile=SolanaAccountCostProfile(
            # Pass profile id explicitly so SolanaAccountCostProfile receives a reviewable
            # account-cost-v1 and pump-token-account-v1 input in components.
            profile_id="account-cost-v1",
            effective_from_unix_s=1_700_000_000,
            effective_until_unix_s=1_800_000_000,
            costs=(
                SolanaAccountDepositCost(PUMPFUN_UVA_SCHEMA_ID, 1_844_400),
                SolanaAccountDepositCost(PUMPFUN_LEGACY_ATA_SCHEMA_ID, 2_039_280),
                SolanaAccountDepositCost(PUMPFUN_TOKEN_2022_ATA_SCHEMA_ID, 2_074_080),
            ),
        ),
    )
    return strategy, protocol, network


def _run(
    events: tuple[CanonicalEvent, ...],
    # Close the run signature after its explicit inputs.
    *,
    clock: CompactTransactionClock | None = None,
    initial_sol: int = 2_000_000_000,
    buy_slippage_bps: int = 0,
    sell_slippage_bps: int = 0,
    # Keep the decision to input explicit in the run contract.
    decision_to: int = 101,
    initial_uva_state: WalletUvaInitialState = WalletUvaInitialState.FRESH,
    delivery_schedule: _Schedule | None = None,
    execution_mode: ExecutionMode = ExecutionMode.EXOGENOUS_REPLAY,
) -> tuple[SnipingRunSummary, _Sink]:
    # Execute the run workflow in explicit, reviewable steps.
    selected_clock = _clock() if clock is None else clock
    strategy, protocol, network = _components(
        buy_slippage_bps=buy_slippage_bps,
        sell_slippage_bps=sell_slippage_bps,
        execution_mode=execution_mode,
    )
    # Assemble sink once so the run workflow shares one value.
    sink = _Sink()
    summary = SnipingReferenceEngine().run(
        source=_Source(events),
        clock=selected_clock,
        strategy=strategy,
        # Pass protocol explicitly so run receives a reviewable test-wallet-profile-v1 and
        # pump-token-account-v1 input in run.
        protocol=protocol,
        network_costs=network,
        config=SnipingRunConfig(
            quote_asset_id=SOL,
            decision_range=BlockRange(
                # Pass solana mainnet network id explicitly so BlockRange receives a
                # reviewable solana mainnet network id and block32 transaction32 position
                # schema id input in run.
                SOLANA_MAINNET_NETWORK_ID,
                BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
                100,
                decision_to,
            ),
            # Pass initial available explicitly so SnipingRunConfig receives a reviewable
            # test-wallet-profile-v1 and pump-token-account-v1 input in run.
            initial_available={SOL: initial_sol},
            initial_uva_state=initial_uva_state,
            wallet_account_profile_id="test-wallet-profile-v1",
            uva_schema_id=PUMPFUN_UVA_SCHEMA_ID,
            root_seed=7,
            execution_mode=execution_mode,
            # Complete SnipingRunConfig only after its test-wallet-profile-v1 and pump-token-
            # account-v1 inputs are visible in run.
        ),
        sink=sink,
        delivery_schedule=delivery_schedule,
    )
    return summary, sink


# Define run scripted as one focused operation with an explicit boundary.
def _run_scripted(
    *,
    buy_outputs: tuple[int, int],
    sell_outputs: tuple[int, int],
    buy_slippage_bps: int = 100,
    # Keep the sell slippage bps input explicit in the run scripted contract.
    sell_slippage_bps: int = 100,
    execution_mode: ExecutionMode = ExecutionMode.EXOGENOUS_REPLAY,
    sell_liquidity_evidence: ProtocolLiquidityEvidence | None = None,
) -> tuple[SnipingRunSummary, _Sink]:
    # Execute the run scripted workflow in explicit, reviewable steps.
    strategy = PumpfunSnipingStrategy(
        quote_asset_id=SOL,
        gross_buy_budget_atomic=1_000_000_000,
        buy_slippage_bps=buy_slippage_bps,
        sell_slippage_bps=sell_slippage_bps,
        # Pass sell delay transactions explicitly so PumpfunSnipingStrategy receives a
        # reviewable sol and buy slippage bps input in run scripted.
        sell_delay_transactions=1,
        execution_mode=execution_mode,
    )
    _, _, network = _components()
    sink = _Sink()
    summary = SnipingReferenceEngine().run(
        # Keep the source and launch _Source step visible while building summary.
        source=_Source((_launch(),)),
        clock=_clock(),
        strategy=strategy,
        protocol=_ScriptedProtocol(
            buy_outputs=buy_outputs,
            # Pass sell outputs explicitly so _ScriptedProtocol receives a reviewable buy
            # outputs and sell outputs input in run scripted.
            sell_outputs=sell_outputs,
            sell_liquidity_evidence=sell_liquidity_evidence,
        ),
        network_costs=network,
        config=SnipingRunConfig(
            quote_asset_id=SOL,
            # Keep the solana mainnet network id BlockRange step visible while building
            # summary.
            decision_range=BlockRange(
                SOLANA_MAINNET_NETWORK_ID,
                BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
                100,
                101,
                # Complete BlockRange only after its solana mainnet network id and block32
                # transaction32 position schema id inputs are visible in run scripted.
            ),
            initial_available={SOL: 2_000_000_000},
            initial_uva_state=WalletUvaInitialState.FRESH,
            wallet_account_profile_id="test-fresh-v1",
            uva_schema_id=PUMPFUN_UVA_SCHEMA_ID,
            # Pass root seed explicitly so SnipingRunConfig receives a reviewable test-
            # fresh-v1 and pump-token-account-v1 input in run scripted.
            root_seed=7,
            execution_mode=execution_mode,
        ),
        sink=sink,
    )
    return summary, sink


# Define run split asset as one focused operation with an explicit boundary.
def _run_split_asset(
    *,
    initial_fee: int = 11,
    initial_deposit: int = 7,
    buy_outputs: tuple[int, int] = (100, 100),
    # Keep the tuple input explicit in the run split asset contract.
) -> tuple[SnipingRunSummary, _Sink]:
    # Execute the run split asset workflow in explicit, reviewable steps.
    strategy = PumpfunSnipingStrategy(
        quote_asset_id=SOL,
        gross_buy_budget_atomic=100,
        buy_slippage_bps=0,
        sell_slippage_bps=0,
        # Pass sell delay transactions explicitly so PumpfunSnipingStrategy receives a
        # reviewable sol input in run split asset.
        sell_delay_transactions=1,
    )
    sink = _Sink()
    summary = SnipingReferenceEngine().run(
        source=_Source((_launch(),)),
        # Keep the clock _clock step visible while building summary.
        clock=_clock(),
        strategy=strategy,
        protocol=_ScriptedProtocol(
            buy_outputs=buy_outputs,
            sell_outputs=(120, 120),
            # Complete _ScriptedProtocol only after its buy outputs inputs are visible in run
            # split asset.
        ),
        network_costs=_SplitAssetNetworkCosts(),
        config=SnipingRunConfig(
            quote_asset_id=SOL,
            decision_range=BlockRange(
                # Pass solana mainnet network id explicitly so BlockRange receives a
                # reviewable solana mainnet network id and block32 transaction32 position
                # schema id input in run split asset.
                SOLANA_MAINNET_NETWORK_ID,
                BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
                100,
                101,
            ),
            # Pass initial available explicitly so SnipingRunConfig receives a reviewable
            # test-split-assets-v1 and pump-token-account-v1 input in run split asset.
            initial_available={
                SOL: 100,
                NETWORK_FEE_ASSET: initial_fee,
                ACCOUNT_DEPOSIT_ASSET: initial_deposit,
            },
            # Pass wallet account profile explicitly so SnipingRunConfig receives a
            # reviewable test-split-assets-v1 and pump-token-account-v1 input in run split
            # asset.
            initial_uva_state=WalletUvaInitialState.FRESH,
            wallet_account_profile_id="test-split-assets-v1",
            uva_schema_id=PUMPFUN_UVA_SCHEMA_ID,
            root_seed=7,
        ),
        # Pass sink explicitly so run receives a reviewable test-split-assets-v1 and pump-
        # token-account-v1 input in run split asset.
        sink=sink,
    )
    return summary, sink


def _ending_available_balance(
    sink: _Sink,
    # Close the ending available balance signature after its explicit inputs.
    *,
    asset_id: AssetId,
    initial: int,
) -> int:
    # Execute the ending available balance workflow in explicit, reviewable steps.
    return initial + sum(
        posting.amount_atomic
        for transaction in sink.ledger
        for posting in transaction.postings
        if posting.asset_id == asset_id and posting.account.kind is AccountKind.PORTFOLIO_AVAILABLE
        # Complete sum only after its amount atomic and ledger inputs are visible in ending
        # available balance.
    )


def test_sniping_run_config_rejects_raw_string_execution_mode() -> None:
    # StrEnum equality must not let an untyped transport value enter the engine.
    with pytest.raises(TypeError, match="execution_mode must be an ExecutionMode"):
        SnipingRunConfig(
            quote_asset_id=SOL,
            # Keep the exact network/schema contract valid in this type-only test.
            decision_range=BlockRange(
                SOLANA_MAINNET_NETWORK_ID,
                BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
                100,
                101,
            ),
            # Keep the remaining resolved inputs valid so only the type boundary fails.
            initial_available={SOL: 2_000_000_000},
            initial_uva_state=WalletUvaInitialState.FRESH,
            wallet_account_profile_id="test-fresh-v1",
            uva_schema_id=PUMPFUN_UVA_SCHEMA_ID,
            # Cast only satisfies static typing; runtime must still reject the string.
            root_seed=7,
            execution_mode=cast(ExecutionMode, "EXOGENOUS_REPLAY"),
        )


def test_end_to_end_uses_post_group_quote_plus_500_then_two_seconds_and_sell_delay() -> None:
    # Execute the test end to end uses post group quote plus 500 then two seconds and sell
    # delay workflow in explicit, reviewable steps.
    initial = _state()
    bundled = replace(
        initial,
        virtual_token_reserves_atomic=1_000_000_000_000_000,
        virtual_sol_reserves_lamports=32_000_000_000,
        # Pass real token reserves atomic explicitly so replace receives a reviewable
        # initial input in test end to end uses post group quote plus 500 then two seconds
        # and sell delay.
        real_token_reserves_atomic=720_100_000_000_000,
        real_sol_reserves_lamports=102_000_000_000,
    )

    summary, sink = _run(
        (
            # Keep the launch and initial _launch step visible while building (summary,
            # sink).
            _launch(state=initial),
            _trade(bundled, block=100, transaction=0, event_index=1, group=1),
        )
    )

    assert summary.closed_roundtrip_count == 1
    # Verify summary.fill_count == 2 before this scenario is accepted.
    assert summary.fill_count == 2
    assert summary.roundtrip_count == 1
    (record,) = sink.roundtrips
    assert record.status is RoundTripStatus.CLOSED
    assert record.buy is not None and record.sell is not None
    # Verify the landing position, buy and position relationship before this scenario is
    # accepted.
    assert record.buy.landing_position == _position(100, 500, None)
    assert record.sell.decision_position == _position(102, 0, None)
    assert record.sell.landing_position == _position(102, 1, None)
    assert record.buy.reference_out_atomic == record.buy.landing_out_atomic
    assert record.sell.reference_out_atomic == record.sell.landing_out_atomic
    mint_account = next(
        item for item in record.account_components if item.scope is AccountRequirementScope.MINT
    )
    wallet_account = next(
        item for item in record.account_components if item.scope is AccountRequirementScope.WALLET
    )
    assert mint_account.lifecycle is AccountComponentLifecycle.CLOSED_REFUNDED
    assert mint_account.paid_atomic == mint_account.refunded_atomic == 2_039_280
    assert wallet_account.lifecycle is AccountComponentLifecycle.CREATED_LOCKED
    assert wallet_account.locked_delta_atomic == 1_844_400
    assert record.account_profile_id == "test-wallet-profile-v1"
    assert mint_account.requirement_schema_id == PUMPFUN_LEGACY_ATA_SCHEMA_ID
    assert record.realized_cash_pnl_atomic is not None
    assert record.mtm_status is MtmStatus.NOT_APPLICABLE
    assert all(
        sum(posting.amount_atomic for posting in transaction.postings if posting.asset_id == asset)
        # Keep transaction, ledger and asset visible while completing all within test end
        # to end uses post group quote plus 500 then two seconds and sell delay.
        == 0
        for transaction in sink.ledger
        for asset in {posting.asset_id for posting in transaction.postings}
    )
    assert all(
        # Pass transaction explicitly so all receives a reviewable ledger and correlation
        # kind input in test end to end uses post group quote plus 500 then two seconds
        # and sell delay.
        transaction.correlation_kind is LedgerCorrelationKind.ROUNDTRIP
        and transaction.correlation_id == record.roundtrip_id
        for transaction in sink.ledger
    )
    committed_quote_cashflow = sum(
        # Pass posting explicitly so sum receives a reviewable amount atomic and ledger
        # input in test end to end uses post group quote plus 500 then two seconds and
        # sell delay.
        posting.amount_atomic
        for transaction in sink.ledger
        if transaction.correlation_id == record.roundtrip_id
        for posting in transaction.postings
        if posting.asset_id == record.quote_asset_id
        # Pass posting explicitly so sum receives a reviewable amount atomic and ledger
        # input in test end to end uses post group quote plus 500 then two seconds and
        # sell delay.
        and posting.account.kind
        in {AccountKind.PORTFOLIO_AVAILABLE, AccountKind.PORTFOLIO_RESERVED}
    )
    assert committed_quote_cashflow == record.realized_cash_pnl_atomic
    assert record.economic_pnl_atomic == record.realized_cash_pnl_atomic + 1_844_400
    locked = tuple(row for row in summary.final_balances if row[1] == "PORTFOLIO_LOCKED")
    assert sum(row[3] for row in locked) == 1_844_400


# Define test split asset costs reserve and settle each asset independently as one focused
# operation with an explicit boundary.
def test_split_asset_costs_reserve_and_settle_each_asset_independently() -> None:
    # Execute the test split asset costs reserve and settle each asset independently
    # workflow in explicit, reviewable steps.
    summary, sink = _run_split_asset()

    assert summary.closed_roundtrip_count == 1
    buy_reservation = next(
        transaction
        for transaction in sink.ledger
        # Pass reason explicitly so next receives a reviewable sniping buy reservation and
        # ledger input in test split asset costs reserve and settle each asset
        # independently.
        if transaction.reason == "SNIPING_BUY_RESERVATION"
    )
    assert {
        posting.asset_id: posting.amount_atomic
        for posting in buy_reservation.postings
        # Keep the posting expectation tied to asset id, amount atomic and sol in this
        # scenario.
        if posting.account.kind is AccountKind.PORTFOLIO_AVAILABLE
    } == {
        SOL: -100,
        NETWORK_FEE_ASSET: -5,
        ACCOUNT_DEPOSIT_ASSET: -7,
        # Verify the asset id, amount atomic and sol relationship before this scenario is
        # accepted.
    }
    network_fee_postings = [
        posting
        for transaction in sink.ledger
        for posting in transaction.postings
        # Keep the posting component named inside the network fee postings contract.
        if posting.account.kind is AccountKind.NETWORK_FEE
    ]
    assert {posting.asset_id for posting in network_fee_postings} == {NETWORK_FEE_ASSET}
    assert sum(posting.amount_atomic for posting in network_fee_postings) == 11
    deposit_postings = [
        # Keep the posting component named inside the deposit postings contract.
        posting
        for transaction in sink.ledger
        for posting in transaction.postings
        if posting.account.kind is AccountKind.PORTFOLIO_LOCKED
    ]
    # Verify the asset id, account deposit asset and posting relationship before this
    # scenario is accepted.
    assert {posting.asset_id for posting in deposit_postings} == {ACCOUNT_DEPOSIT_ASSET}
    # The mint ATA closes; the wallet-scoped UVA remains locked through run end.
    assert sum(posting.amount_atomic for posting in deposit_postings) == 2
    assert _ending_available_balance(sink, asset_id=SOL, initial=100) == 120
    assert _ending_available_balance(sink, asset_id=NETWORK_FEE_ASSET, initial=11) == 0
    assert _ending_available_balance(sink, asset_id=ACCOUNT_DEPOSIT_ASSET, initial=7) == 5
    # Assemble (record,) once so the test split asset costs reserve and settle each asset
    # independently workflow shares one value.
    (record,) = sink.roundtrips
    assert record.realized_cash_pnl_atomic == 20


@pytest.mark.parametrize(
    ("initial_fee", "initial_deposit"),
    ((4, 7), (5, 6)),
    # Complete parametrize only after its initial fee and initial deposit inputs are visible
    # in test split asset buy rejects atomically when one cost asset is short.
)
def test_split_asset_buy_rejects_atomically_when_one_cost_asset_is_short(
    initial_fee: int,
    initial_deposit: int,
) -> None:
    # Execute the test split asset buy rejects atomically when one cost asset is short
    # workflow in explicit, reviewable steps.
    summary, sink = _run_split_asset(
        initial_fee=initial_fee,
        initial_deposit=initial_deposit,
    )

    assert summary.rejected_buy_count == 1
    # Verify sink.ledger == [] before this scenario is accepted.
    assert sink.ledger == []
    (record,) = sink.roundtrips
    assert record.cooldown_consumed is True
    assert record.status is RoundTripStatus.BUY_PRE_SUBMIT_INSUFFICIENT_FUNDS


def test_split_asset_landed_failure_charges_only_the_fee_asset() -> None:
    # Execute the test split asset landed failure charges only the fee asset workflow in
    # explicit, reviewable steps.
    summary, sink = _run_split_asset(buy_outputs=(100, 99))

    assert summary.failed_buy_count == 1
    assert _ending_available_balance(sink, asset_id=SOL, initial=100) == 100
    assert _ending_available_balance(sink, asset_id=NETWORK_FEE_ASSET, initial=11) == 6
    assert _ending_available_balance(sink, asset_id=ACCOUNT_DEPOSIT_ASSET, initial=7) == 7
    # Assemble failure once so the test split asset landed failure charges only the fee
    # asset workflow shares one value.
    failure = sink.ledger[-1]
    network_fee_postings = [
        posting for posting in failure.postings if posting.account.kind is AccountKind.NETWORK_FEE
    ]
    assert [(posting.asset_id, posting.amount_atomic) for posting in network_fee_postings] == [
        # Keep the network fee asset expectation tied to asset id, amount atomic and
        # posting in this scenario.
        (NETWORK_FEE_ASSET, 5)
    ]


def test_materialized_post_group_observations_are_byte_identical_to_dynamic() -> None:
    # Execute the test materialized post group observations are byte identical to dynamic
    # workflow in explicit, reviewable steps.
    initial = _state()
    bundled = replace(
        initial,
        virtual_token_reserves_atomic=1_000_000_000_000_000,
        virtual_sol_reserves_lamports=32_000_000_000,
        # Pass real token reserves atomic explicitly so replace receives a reviewable
        # initial input in test materialized post group observations are byte identical to
        # dynamic.
        real_token_reserves_atomic=720_100_000_000_000,
        real_sol_reserves_lamports=102_000_000_000,
    )
    events = (
        _launch(state=initial),
        # Register bundled through _trade so the events table remains scannable.
        _trade(bundled, block=100, transaction=0, event_index=1, group=1),
    )
    rows = tuple(
        ObservationDelivery(event.envelope.boundary_ordinal, row)
        for row, event in sorted(
            # Keep the events enumerate step visible while building rows.
            enumerate(events),
            key=lambda item: (
                item[1].envelope.boundary_ordinal,
                item[1].envelope.stable_causal_id.hex,
            ),
            # Complete sorted only after its boundary ordinal and hex inputs are visible in
            # test materialized post group observations are byte identical to dynamic.
        )
    )

    dynamic_summary, dynamic_sink = _run(events)
    materialized_summary, materialized_sink = _run(
        events,
        # Keep the rows _Schedule step visible while building materialized summary and
        # materialized sink.
        delivery_schedule=_Schedule(rows, len(events)),
    )

    assert materialized_summary == dynamic_summary
    assert materialized_sink.audits == dynamic_sink.audits
    assert materialized_sink.ledger == dynamic_sink.ledger
    # Verify the fills, materialized sink and dynamic sink relationship before this
    # scenario is accepted.
    assert materialized_sink.fills == dynamic_sink.fills
    assert materialized_sink.roundtrips == dynamic_sink.roundtrips


def test_materialized_observation_mismatch_fails_before_historical_mutation() -> None:
    # Execute the test materialized observation mismatch fails before historical mutation
    # workflow in explicit, reviewable steps.
    event = _launch()
    malformed = _Schedule(
        (ObservationDelivery(event.envelope.boundary_ordinal + 1, 0),),
        1,
    )
    # Assemble (strategy, protocol, network) once so the test materialized observation
    # mismatch fails before historical mutation workflow shares one value.
    strategy, protocol, network = _components()

    with pytest.raises(SnipingEngineError) as rejected:
        # Keep raises, sniping engine error and pytest active only for the bounded test
        # materialized observation mismatch fails before historical mutation operation.
        SnipingReferenceEngine().run(
            source=_Source((event,)),
            clock=_clock(),
            strategy=strategy,
            protocol=protocol,
            # Pass network costs explicitly so run receives a reviewable test-fresh-v1 and
            # pump-token-account-v1 input in test materialized observation mismatch fails
            # before historical mutation.
            network_costs=network,
            config=SnipingRunConfig(
                quote_asset_id=SOL,
                decision_range=BlockRange(
                    SOLANA_MAINNET_NETWORK_ID,
                    # Pass block32 transaction32 position schema id explicitly so
                    # BlockRange receives a reviewable solana mainnet network id and
                    # block32 transaction32 position schema id input in test materialized
                    # observation mismatch fails before historical mutation.
                    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
                    100,
                    101,
                ),
                initial_available={SOL: 2_000_000_000},
                # Pass wallet account profile explicitly so SnipingRunConfig receives a
                # reviewable test-fresh-v1 and pump-token-account-v1 input in test
                # materialized observation mismatch fails before historical mutation.
                initial_uva_state=WalletUvaInitialState.FRESH,
                wallet_account_profile_id="test-fresh-v1",
                uva_schema_id=PUMPFUN_UVA_SCHEMA_ID,
                root_seed=7,
            ),
            # Pass delivery schedule explicitly so run receives a reviewable test-fresh-v1
            # and pump-token-account-v1 input in test materialized observation mismatch
            # fails before historical mutation.
            delivery_schedule=malformed,
        )

    assert rejected.value.code is SnipingEngineErrorCode.DELIVERY_SCHEDULE_INVALID
    assert protocol._curves == {}


def test_noncanonical_bundled_instruction_order_fails_closed() -> None:
    # Execute the test noncanonical bundled instruction order fails closed workflow in
    # explicit, reviewable steps.
    bundled = _state(
        virtual_token_reserves_atomic=1_000_000_000_000_000,
        virtual_sol_reserves_lamports=32_000_000_000,
        real_token_reserves_atomic=720_100_000_000_000,
        real_sol_reserves_lamports=102_000_000_000,
        # Complete _state only after its declared inputs are visible in test noncanonical
        # bundled instruction order fails closed.
    )

    with pytest.raises(SnipingEngineError) as rejected:
        # Keep raises, sniping engine error and pytest active only for the bounded test
        # noncanonical bundled instruction order fails closed operation.
        _run(
            (
                _trade(bundled, block=100, transaction=0, event_index=1, group=1),
                _launch(state=_state()),
            )
            # Complete _run only after its trade and launch inputs are visible in test
            # noncanonical bundled instruction order fails closed.
        )

    assert rejected.value.code is SnipingEngineErrorCode.SOURCE_ORDER_INVALID


@pytest.mark.parametrize(
    ("landing_output", "expected_status", "expected_delta"),
    (
        # Open the landing output and expected status payload explicitly for parametrize
        # within test buy slippage accepts exact minimum rejects minus one and keeps
        # favorable.
        (990, RoundTripStatus.CLOSED, -10),
        (989, RoundTripStatus.BUY_LANDED_FAILED, -11),
        (1_001, RoundTripStatus.CLOSED, 1),
    ),
)
# Define test buy slippage accepts exact minimum rejects minus one and keeps favorable as
# one focused operation with an explicit boundary.
def test_buy_slippage_accepts_exact_minimum_rejects_minus_one_and_keeps_favorable(
    landing_output: int,
    expected_status: RoundTripStatus,
    expected_delta: int,
) -> None:
    # Execute the test buy slippage accepts exact minimum rejects minus one and keeps
    # favorable workflow in explicit, reviewable steps.
    _, sink = _run_scripted(
        buy_outputs=(1_000, landing_output),
        sell_outputs=(1_000, 1_000),
    )

    (record,) = sink.roundtrips
    # Verify record.status is expected_status before this scenario is accepted.
    assert record.status is expected_status
    assert record.buy is not None
    assert record.buy.minimum_out_atomic == 990
    assert record.buy.landing_out_atomic == landing_output
    assert record.buy.signed_slippage_atomic == expected_delta


# Apply parametrize semantics to the following test sell slippage accepts exact minimum
# rejects minus one and keeps favorable contract.
@pytest.mark.parametrize(
    ("landing_output", "expected_status", "expected_delta"),
    (
        (990, RoundTripStatus.CLOSED, -10),
        (989, RoundTripStatus.SELL_LANDED_FAILED_OPEN, -11),
        # Open the landing output and expected status payload explicitly for parametrize
        # within test sell slippage accepts exact minimum rejects minus one and keeps
        # favorable.
        (1_001, RoundTripStatus.CLOSED, 1),
    ),
)
def test_sell_slippage_accepts_exact_minimum_rejects_minus_one_and_keeps_favorable(
    landing_output: int,
    # Keep the expected status input explicit in the test sell slippage accepts exact
    # minimum rejects minus one and keeps favorable contract.
    expected_status: RoundTripStatus,
    expected_delta: int,
) -> None:
    # Execute the test sell slippage accepts exact minimum rejects minus one and keeps
    # favorable workflow in explicit, reviewable steps.
    _, sink = _run_scripted(
        buy_outputs=(1_000, 1_000),
        sell_outputs=(1_000, landing_output),
    )

    (record,) = sink.roundtrips
    # Verify record.status is expected_status before this scenario is accepted.
    assert record.status is expected_status
    assert record.sell is not None
    assert record.sell.minimum_out_atomic == 990
    assert record.sell.landing_out_atomic == landing_output
    assert record.sell.signed_slippage_atomic == expected_delta


# Define test cooldown is consumed before funds and suppressed target does not submit as
# one focused operation with an explicit boundary.
def test_cooldown_is_consumed_before_funds_and_suppressed_target_does_not_submit() -> None:
    # Execute the test cooldown is consumed before funds and suppressed target does not
    # submit workflow in explicit, reviewable steps.
    clock = _clock(
        (
            (100, 501, BASE_TIME_S),
            (101, 501, BASE_TIME_S + 599),
            (102, 1, BASE_TIME_S + 600),
            # Open the base time s payload explicitly for _clock within test cooldown is
            # consumed before funds and suppressed target does not submit.
            (103, 2, BASE_TIME_S + 601),
        )
    )
    summary, sink = _run(
        (
            # Keep the launch and token-a _launch step visible while building (summary,
            # sink).
            _launch(token="TOKEN-A", venue="curve-a", group=1),
            _launch(
                block=101,
                token="TOKEN-B",
                venue="curve-b",
                # Pass group explicitly so _launch receives a reviewable token-b and
                # curve-b input in test cooldown is consumed before funds and suppressed
                # target does not submit.
                group=2,
            ),
        ),
        clock=clock,
        initial_sol=0,
        # Pass decision to explicitly so _run receives a reviewable token-a and curve-a
        # input in test cooldown is consumed before funds and suppressed target does not
        # submit.
        decision_to=102,
    )

    assert summary.target_count == 2
    assert summary.cooldown_skipped_count == 1
    assert {record.status for record in sink.roundtrips} == {
        # Keep the round trip status expectation tied to status, buy pre submit
        # insufficient funds and cooldown skipped in this scenario.
        RoundTripStatus.BUY_PRE_SUBMIT_INSUFFICIENT_FUNDS,
        RoundTripStatus.COOLDOWN_SKIPPED,
    }
    assert sink.ledger == []


def test_migration_at_buy_landing_charges_only_network_fee_and_creates_no_account() -> None:
    # Execute the test migration at buy landing charges only network fee and creates no
    # account workflow in explicit, reviewable steps.
    migrated = _state(lifecycle=PumpCurveLifecycle.MIGRATED)
    summary, sink = _run(
        (
            _launch(),
            _lifecycle(migrated, block=100, transaction=500, group=2),
            # Complete _run only after its launch and lifecycle inputs are visible in test
            # migration at buy landing charges only network fee and creates no account.
        )
    )

    assert summary.failed_buy_count == 1
    assert summary.fill_count == 0
    (record,) = sink.roundtrips
    # Verify the status, buy landed failed and record relationship before this scenario is
    # accepted.
    assert record.status is RoundTripStatus.BUY_LANDED_FAILED
    assert all(
        item.lifecycle is AccountComponentLifecycle.RESERVATION_RELEASED
        for item in record.account_components
    )
    assert sum(item.maximum_reserved_atomic for item in record.account_components) == 3_883_680
    assert all(item.locked_delta_atomic == 0 for item in record.account_components)
    assert record.buy is not None
    # Verify the failure code, pumpswap routing forbidden and buy relationship before this
    # scenario is accepted.
    assert record.buy.failure_code == "PUMPSWAP_ROUTING_FORBIDDEN"
    assert record.buy.protocol_fee_atomic == record.buy.creator_fee_atomic == 0
    assert record.buy.network_base_fee_atomic == 5_000
    assert record.acquired_token_amount_atomic == 0
    assert not any(row[1] == "PORTFOLIO_LOCKED" for row in summary.final_balances)


def test_strict_mode_rejects_synthetic_evidence_from_malicious_protocol() -> None:
    # This evidence is structurally valid but forbidden by strict replay semantics.
    evidence = ProtocolLiquidityEvidence(
        policy_id=REAL_RESERVE_CAPPED_LIQUIDITY_POLICY_ID,
        asset_id=SOL,
        required_output_atomic=100,
        # The forged strict quote asks an external source to cover the full deficit.
        observed_available_output_atomic=0,
        synthetic_shortfall_atomic=100,
        synthetic_source_account_id=AccountId("malicious-synthetic-source"),
    )

    with pytest.raises(SnipingEngineError) as rejected:
        _run_scripted(
            buy_outputs=(100, 100),
            sell_outputs=(100, 100),
            sell_liquidity_evidence=evidence,
        )

    assert rejected.value.code is SnipingEngineErrorCode.QUOTE_CONTRACT_MISMATCH


def test_strict_mode_rejects_synthetic_source_without_shortfall() -> None:
    evidence = ProtocolLiquidityEvidence(
        policy_id=REAL_RESERVE_CAPPED_LIQUIDITY_POLICY_ID,
        asset_id=SOL,
        required_output_atomic=100,
        # Start valid, then bypass the frozen constructor below to isolate source checks.
        observed_available_output_atomic=100,
        synthetic_shortfall_atomic=0,
        synthetic_source_account_id=None,
    )
    # Simulate a malicious plugin bypassing the source/shortfall value invariant.
    object.__setattr__(
        evidence,
        "synthetic_source_account_id",
        AccountId("malicious-synthetic-source"),
    )

    with pytest.raises(SnipingEngineError) as rejected:
        _run_scripted(
            buy_outputs=(100, 100),
            sell_outputs=(100, 100),
            sell_liquidity_evidence=evidence,
        )

    assert rejected.value.code is SnipingEngineErrorCode.QUOTE_CONTRACT_MISMATCH


def test_virtual_mode_rejects_wrong_synthetic_account_from_malicious_protocol() -> None:
    # A plugin cannot redirect synthetic proceeds to an arbitrary external account.
    evidence = ProtocolLiquidityEvidence(
        policy_id=VIRTUAL_RESERVE_EXPLICIT_SHORTFALL_LIQUIDITY_POLICY_ID,
        asset_id=SOL,
        required_output_atomic=100,
        # Arithmetic is valid; only deterministic account identity is malicious.
        observed_available_output_atomic=0,
        synthetic_shortfall_atomic=100,
        synthetic_source_account_id=AccountId("malicious-synthetic-source"),
    )

    with pytest.raises(SnipingEngineError) as rejected:
        _run_scripted(
            buy_outputs=(100, 100),
            sell_outputs=(100, 100),
            execution_mode=ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT,
            sell_liquidity_evidence=evidence,
        )

    assert rejected.value.code is SnipingEngineErrorCode.QUOTE_CONTRACT_MISMATCH


def test_virtual_mode_rejects_inexact_shortfall_from_malicious_protocol() -> None:
    expected_source = synthetic_liquidity_account_id(
        protocol_namespace="pumpfun",
        network_id=SOLANA_MAINNET_NETWORK_ID,
        venue_id=VenueId("curve"),
    )
    # Start with canonical virtual evidence so mutation isolates arithmetic validation.
    evidence = ProtocolLiquidityEvidence(
        policy_id=VIRTUAL_RESERVE_EXPLICIT_SHORTFALL_LIQUIDITY_POLICY_ID,
        asset_id=SOL,
        required_output_atomic=100,
        # The full deficit initially matches both observed liquidity and its source.
        observed_available_output_atomic=0,
        synthetic_shortfall_atomic=100,
        synthetic_source_account_id=expected_source,
    )
    # Simulate a malicious plugin bypassing the frozen value object's constructor.
    object.__setattr__(evidence, "synthetic_shortfall_atomic", 99)

    with pytest.raises(SnipingEngineError) as rejected:
        _run_scripted(
            buy_outputs=(100, 100),
            sell_outputs=(100, 100),
            execution_mode=ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT,
            sell_liquidity_evidence=evidence,
        )

    assert rejected.value.code is SnipingEngineErrorCode.QUOTE_CONTRACT_MISMATCH


# Define test buy program failure charges network only and has no venue transition as one
# focused operation with an explicit boundary.
def test_virtual_settlement_closes_against_historical_virtual_reserves() -> None:
    state_without_observed_real_sol = _state(real_sol_reserves_lamports=0)
    summary, sink = _run(
        (_launch(state=state_without_observed_real_sol),),
        execution_mode=ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT,
    )

    (record,) = sink.roundtrips
    assert record.status is RoundTripStatus.CLOSED
    assert record.execution_mode is ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT
    assert record.sell is not None
    assert record.sell_landing_liquidity is not None
    evidence = record.sell_landing_liquidity
    assert evidence.observed_available_output_atomic == 0
    assert evidence.synthetic_shortfall_atomic == evidence.required_output_atomic
    assert record.settled_venue_funded_atomic == 0
    assert record.settled_synthetic_funded_atomic == evidence.required_output_atomic

    assert summary.execution_mode is ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT
    assert summary.filled_sell_count == 1
    assert summary.synthetic_liquidity_used_sell_count == 1
    assert summary.real_liquidity_sufficient_filled_sell_count == 0
    assert summary.synthetic_funded_sell_atomic == evidence.required_output_atomic
    assert summary.venue_funded_sell_atomic == 0
    synthetic_postings = [
        posting
        for transaction in sink.ledger
        for posting in transaction.postings
        if posting.account.kind is AccountKind.EXTERNAL
        and posting.account.account_id.value.startswith("synthetic-liquidity:pumpfun:")
    ]
    assert len(synthetic_postings) == 1
    assert synthetic_postings[0].amount_atomic == -evidence.required_output_atomic


def test_real_reserve_capped_mode_keeps_the_same_sell_failure() -> None:
    summary, sink = _run((_launch(state=_state(real_sol_reserves_lamports=0)),))

    (record,) = sink.roundtrips
    assert record.status is RoundTripStatus.SELL_REFERENCE_UNAVAILABLE_OPEN
    assert record.execution_mode is ExecutionMode.EXOGENOUS_REPLAY
    assert record.settled_synthetic_funded_atomic == 0
    assert summary.synthetic_liquidity_used_sell_count == 0
    assert not any(
        posting.account.account_id.value.startswith("synthetic-liquidity:pumpfun:")
        for transaction in sink.ledger
        for posting in transaction.postings
    )


def test_buy_program_failure_charges_network_only_and_has_no_venue_transition() -> None:
    # Execute the test buy program failure charges network only and has no venue
    # transition workflow in explicit, reviewable steps.
    adverse = _state(
        virtual_sol_reserves_lamports=100_000_000_000,
        real_sol_reserves_lamports=170_000_000_000,
    )
    summary, sink = _run(
        # Open the launch and trade payload explicitly for _run within test buy program
        # failure charges network only and has no venue transition.
        (
            _launch(),
            _trade(
                adverse,
                block=100,
                # Pass transaction explicitly so _trade receives a reviewable adverse
                # input in test buy program failure charges network only and has no venue
                # transition.
                transaction=500,
                event_index=0,
                group=2,
            ),
        )
        # Complete _run only after its launch and trade inputs are visible in test buy program
        # failure charges network only and has no venue transition.
    )

    assert summary.failed_buy_count == 1
    (record,) = sink.roundtrips
    assert record.status is RoundTripStatus.BUY_LANDED_FAILED
    assert record.buy is not None
    # Verify the failure code, minimum output not met and buy relationship before this
    # scenario is accepted.
    assert record.buy.failure_code == "MINIMUM_OUTPUT_NOT_MET"
    assert record.buy.landing_out_atomic is not None
    assert record.buy.landing_out_atomic < record.buy.minimum_out_atomic
    assert record.buy.protocol_fee_atomic == record.buy.creator_fee_atomic == 0
    failure = sink.ledger[-1]
    # Verify the kind, posting and postings relationship before this scenario is accepted.
    assert all(
        posting.account.kind
        not in {AccountKind.VENUE, AccountKind.PROTOCOL_FEE, AccountKind.CREATOR_FEE}
        for posting in failure.postings
    )


# Define test sell slippage failure keeps tokens and rent and records signed landing delta
# as one focused operation with an explicit boundary.
def test_sell_slippage_failure_keeps_tokens_and_rent_and_records_signed_landing_delta() -> None:
    # Execute the test sell slippage failure keeps tokens and rent and records signed
    # landing delta workflow in explicit, reviewable steps.
    adverse = _state(
        virtual_sol_reserves_lamports=10_000_000_000,
        real_sol_reserves_lamports=80_000_000_000,
    )
    summary, sink = _run(
        # Open the launch and trade payload explicitly for _run within test sell slippage
        # failure keeps tokens and rent and records signed landing delta.
        (
            _launch(),
            _trade(
                adverse,
                block=102,
                # Pass transaction explicitly so _trade receives a reviewable adverse
                # input in test sell slippage failure keeps tokens and rent and records
                # signed landing delta.
                transaction=1,
                event_index=0,
                group=2,
            ),
        ),
        # Pass sell slippage bps explicitly so _run receives a reviewable launch and trade
        # input in test sell slippage failure keeps tokens and rent and records signed
        # landing delta.
        sell_slippage_bps=0,
    )

    assert summary.failed_sell_count == 1
    assert summary.open_position_count == 1
    (record,) = sink.roundtrips
    # Verify the status, sell landed failed open and record relationship before this
    # scenario is accepted.
    assert record.status is RoundTripStatus.SELL_LANDED_FAILED_OPEN
    mint_account = next(
        item for item in record.account_components if item.scope is AccountRequirementScope.MINT
    )
    assert mint_account.lifecycle is AccountComponentLifecycle.CREATED_LOCKED
    assert record.sell is not None
    assert record.sell.failure_code == "MINIMUM_OUTPUT_NOT_MET"
    assert record.sell.landing_out_atomic is not None
    # Verify the signed slippage atomic, sell and record relationship before this scenario
    # is accepted.
    assert record.sell.signed_slippage_atomic is not None
    assert record.sell.signed_slippage_atomic < 0
    assert record.sell.protocol_fee_atomic == record.sell.creator_fee_atomic == 0
    assert record.sell.network_base_fee_atomic == 5_000
    assert record.mtm_status is MtmStatus.EXECUTABLE
    # Verify the portfolio locked, row and final balances relationship before this
    # scenario is accepted.
    assert any(row[1] == "PORTFOLIO_LOCKED" for row in summary.final_balances)
    assert any(row[0] == "portfolio:available:TOKEN" for row in summary.final_balances)


def test_cashback_is_nonspendable_and_insufficient_sell_fee_is_pre_submit() -> None:
    # Execute the test cashback is nonspendable and insufficient sell fee is pre submit
    # workflow in explicit, reviewable steps.
    exact_buy_reservation = 1_000_000_000 + 5_001 + 2_074_080 + 1_844_400
    summary, sink = _run(
        (_launch(state=_state(mode=PumpMode.CASHBACK)),),
        initial_sol=exact_buy_reservation,
    )

    # Verify summary.failed_sell_count == 0 before this scenario is accepted.
    assert summary.failed_sell_count == 0
    (record,) = sink.roundtrips
    assert record.status is RoundTripStatus.SELL_PRE_SUBMIT_INSUFFICIENT_FUNDS_OPEN
    assert record.cashback_receivable_atomic > 5_002
    assert record.sell is not None
    # Verify record.sell.landing_position is None before this scenario is accepted.
    assert record.sell.landing_position is None
    assert record.sell.network_base_fee_atomic == 0
    assert any(row[1] == "RECEIVABLE" for row in summary.final_balances)
    assert not any(transaction.reason == "SNIPING_SELL_RESERVATION" for transaction in sink.ledger)


def test_prewarmed_wallet_skips_uva_cashflow_but_still_cycles_mint_ata() -> None:
    # Prewarming is wallet-scoped; every mint still needs its own ATA lifecycle.
    summary, sink = _run(
        (_launch(),),
        initial_uva_state=WalletUvaInitialState.PREWARMED,
    )

    (record,) = sink.roundtrips
    # Verify the status, closed and record relationship before this scenario is accepted.
    assert record.status is RoundTripStatus.CLOSED
    mint_account = next(
        item for item in record.account_components if item.scope is AccountRequirementScope.MINT
    )
    wallet_account = next(
        item for item in record.account_components if item.scope is AccountRequirementScope.WALLET
    )
    assert mint_account.lifecycle is AccountComponentLifecycle.CLOSED_REFUNDED
    assert mint_account.paid_atomic == mint_account.refunded_atomic == 2_039_280
    assert wallet_account.lifecycle is AccountComponentLifecycle.PREWARMED
    assert record.account_profile_id == "test-wallet-profile-v1"
    assert not any(row[1] == "PORTFOLIO_LOCKED" for row in summary.final_balances)
    assert any(
        posting.account.kind is AccountKind.PORTFOLIO_LOCKED
        for transaction in sink.ledger
        for posting in transaction.postings
    )


def test_migration_before_sell_decision_leaves_stale_pre_migration_mtm() -> None:
    # Execute the test migration before sell decision leaves stale pre migration mtm
    # workflow in explicit, reviewable steps.
    migrated = _state(lifecycle=PumpCurveLifecycle.MIGRATED)
    summary, sink = _run(
        (
            _launch(),
            _lifecycle(migrated, block=102, transaction=0, group=2),
            # Complete _run only after its launch and lifecycle inputs are visible in test
            # migration before sell decision leaves stale pre migration mtm.
        )
    )

    assert summary.open_position_count == 1
    (record,) = sink.roundtrips
    assert record.status is RoundTripStatus.SELL_REFERENCE_UNAVAILABLE_OPEN
    # Verify record.sell is None before this scenario is accepted.
    assert record.sell is None
    assert record.mtm_status is MtmStatus.STALE_PRE_MIGRATION
    assert record.mtm_liquidation_value_atomic is not None
    assert record.mtm_cash_pnl_atomic is not None


def test_unvalued_completed_curve_makes_full_economic_pnl_explicitly_unknown() -> None:
    # Execute the test unvalued completed curve makes full economic pnl explicitly unknown
    # workflow in explicit, reviewable steps.
    completed = _state(lifecycle=PumpCurveLifecycle.COMPLETED)
    summary, sink = _run(
        (
            _launch(),
            _lifecycle(
                # Pass completed explicitly so _lifecycle receives a reviewable completed
                # and venue lifecycle kind input in test unvalued completed curve makes
                # full economic pnl explicitly unknown.
                completed,
                block=102,
                transaction=0,
                group=2,
                kind=VenueLifecycleKind.COMPLETED,
                # Complete _lifecycle only after its completed and venue lifecycle kind inputs
                # are visible in test unvalued completed curve makes full economic pnl
                # explicitly unknown.
            ),
        )
    )

    assert summary.open_position_count == 1
    assert summary.unvalued_open_position_count == 1
    # Verify the valuation status, partial unvalued open positions and summary
    # relationship before this scenario is accepted.
    assert summary.valuation_status is SnipingValuationStatus.PARTIAL_UNVALUED_OPEN_POSITIONS
    assert summary.economic_pnl_atomic is None
    assert summary.valued_economic_pnl_subtotal_atomic == 0
    (record,) = sink.roundtrips
    assert record.mtm_status is MtmStatus.UNAVAILABLE
    # Verify record.economic_pnl_atomic is None before this scenario is accepted.
    assert record.economic_pnl_atomic is None


def test_shared_wallet_reserves_in_canonical_launch_order() -> None:
    # Execute the test shared wallet reserves in canonical launch order workflow in
    # explicit, reviewable steps.
    exact_buy_reservation = 1_000_000_000 + 5_001 + 2_039_280 + 1_844_400
    summary, sink = _run(
        (
            _launch(token="TOKEN-A", venue="curve-a", developer="dev-a", event_index=0),
            _launch(token="TOKEN-B", venue="curve-b", developer="dev-b", event_index=1),
            # Complete _run only after its token-a and curve-a inputs are visible in test
            # shared wallet reserves in canonical launch order.
        ),
        initial_sol=exact_buy_reservation,
    )

    assert summary.accepted_buy_count == 1
    assert [record.asset_id.value for record in sink.roundtrips] == ["TOKEN-A", "TOKEN-B"]
    # Assemble (first, second) once so the test shared wallet reserves in canonical launch
    # order workflow shares one value.
    first, second = sink.roundtrips
    assert first.acquired_token_amount_atomic > 0
    assert second.status is RoundTripStatus.BUY_PRE_SUBMIT_INSUFFICIENT_FUNDS


def test_concurrent_accepted_buys_create_and_charge_wallet_uva_once() -> None:
    # Both targets decide before either buy lands, so a fresh wallet conservatively
    # reserves the UVA twice.  Canonical landing order must charge it exactly once.
    exact_buy_reservation = 1_000_000_000 + 5_001 + 2_039_280 + 1_844_400
    summary, sink = _run(
        (
            _launch(token="TOKEN-A", venue="curve-a", developer="dev-a", event_index=0),
            _launch(token="TOKEN-B", venue="curve-b", developer="dev-b", event_index=1),
        ),
        initial_sol=exact_buy_reservation * 2,
    )

    assert summary.accepted_buy_count == 2
    assert summary.closed_roundtrip_count == 2
    wallet_components = [
        component
        for record in sink.roundtrips
        for component in record.account_components
        if component.scope is AccountRequirementScope.WALLET
    ]
    assert [component.lifecycle for component in wallet_components] == [
        AccountComponentLifecycle.CREATED_LOCKED,
        AccountComponentLifecycle.EXISTING_RUN_LOCKED,
    ]
    assert sum(component.paid_atomic for component in wallet_components) == 1_844_400
    assert sum(component.released_atomic for component in wallet_components) == 1_844_400
    assert (
        sum(row[3] for row in summary.final_balances if row[1] == "PORTFOLIO_LOCKED") == 1_844_400
    )
    assert (
        sum(
            (record.economic_pnl_atomic or 0) - (record.realized_cash_pnl_atomic or 0)
            for record in sink.roundtrips
        )
        == 1_844_400
    )


def test_insufficient_settlement_tail_aborts_instead_of_censoring_pending_buy() -> None:
    # Execute the test insufficient settlement tail aborts instead of censoring pending
    # buy workflow in explicit, reviewable steps.
    clock = _clock(((100, 500, BASE_TIME_S),))

    with pytest.raises(TransactionClockError) as rejected:
        _run((_launch(),), clock=clock)

    assert rejected.value.code is TransactionClockErrorCode.SETTLEMENT_TAIL_EXHAUSTED


def test_clock_tail_failure_happens_before_strategy_protocol_or_sink_mutation() -> None:
    # Execute the test clock tail failure happens before strategy protocol or sink
    # mutation workflow in explicit, reviewable steps.
    strategy, protocol, network = _components()
    sink = _Sink()
    source = _Source((_launch(),))
    engine = SnipingReferenceEngine()

    with pytest.raises(TransactionClockError) as rejected:
        # Keep raises, transaction clock error and pytest active only for the bounded test
        # clock tail failure happens before strategy protocol or sink mutation operation.
        engine.run(
            source=source,
            clock=_clock(((100, 500, BASE_TIME_S),)),
            strategy=strategy,
            protocol=protocol,
            # Pass network costs explicitly so run receives a reviewable test-fresh-v1 and
            # pump-token-account-v1 input in test clock tail failure happens before
            # strategy protocol or sink mutation.
            network_costs=network,
            config=SnipingRunConfig(
                quote_asset_id=SOL,
                decision_range=BlockRange(
                    SOLANA_MAINNET_NETWORK_ID,
                    # Pass block32 transaction32 position schema id explicitly so
                    # BlockRange receives a reviewable solana mainnet network id and
                    # block32 transaction32 position schema id input in test clock tail
                    # failure happens before strategy protocol or sink mutation.
                    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
                    100,
                    101,
                ),
                initial_available={SOL: 2_000_000_000},
                # Pass wallet account profile explicitly so SnipingRunConfig receives a
                # reviewable test-fresh-v1 and pump-token-account-v1 input in test clock
                # tail failure happens before strategy protocol or sink mutation.
                initial_uva_state=WalletUvaInitialState.FRESH,
                wallet_account_profile_id="test-fresh-v1",
                uva_schema_id=PUMPFUN_UVA_SCHEMA_ID,
                root_seed=7,
            ),
            # Pass sink explicitly so run receives a reviewable test-fresh-v1 and pump-
            # token-account-v1 input in test clock tail failure happens before strategy
            # protocol or sink mutation.
            sink=sink,
        )
    assert rejected.value.code is TransactionClockErrorCode.SETTLEMENT_TAIL_EXHAUSTED
    assert sink.audits == sink.ledger == sink.fills == sink.roundtrips == []

    # Reusing the exact instances proves neither cooldown nor Pump curve state
    # was changed by the failed preflight.
    recovered = engine.run(
        source=source,
        clock=_clock(),
        strategy=strategy,
        protocol=protocol,
        # Pass network costs explicitly so run receives a reviewable test-fresh-v1 and
        # pump-token-account-v1 input in test clock tail failure happens before strategy
        # protocol or sink mutation.
        network_costs=network,
        config=SnipingRunConfig(
            quote_asset_id=SOL,
            decision_range=BlockRange(
                SOLANA_MAINNET_NETWORK_ID,
                # Pass block32 transaction32 position schema id explicitly so BlockRange
                # receives a reviewable solana mainnet network id and block32
                # transaction32 position schema id input in test clock tail failure
                # happens before strategy protocol or sink mutation.
                BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
                100,
                101,
            ),
            initial_available={SOL: 2_000_000_000},
            # Pass wallet account profile explicitly so SnipingRunConfig receives a
            # reviewable test-fresh-v1 and pump-token-account-v1 input in test clock tail
            # failure happens before strategy protocol or sink mutation.
            initial_uva_state=WalletUvaInitialState.FRESH,
            wallet_account_profile_id="test-fresh-v1",
            uva_schema_id=PUMPFUN_UVA_SCHEMA_ID,
            root_seed=7,
        ),
        # Complete run only after its test-fresh-v1 and pump-token-account-v1 inputs are
        # visible in test clock tail failure happens before strategy protocol or sink
        # mutation.
    )
    assert recovered.closed_roundtrip_count == 1
