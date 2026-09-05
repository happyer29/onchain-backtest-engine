# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

# Import repository at the visible module dependency boundary.
from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.adapters.columnar.numpy import (
    LocalNumpyReplayPackCompiler,
    NumpyMmapPumpfunSnipingEngine,
    NumpyMmapReplaySource,
    # Close the numpy import after its required symbols are visible.
)
from backtest.adapters.columnar.numpy import layout as replay_physical
from backtest.adapters.columnar.numpy.layout import COMPILER_VERSION
from backtest.adapters.delivery_schedule.numpy import (
    LocalNumpyDeliveryScheduleCompiler,
    # Include numpy mmap delivery schedule so the numpy dependency remains explicit.
    NumpyMmapDeliverySchedule,
)
from backtest.adapters.delivery_schedule.numpy import layout as delivery_physical
from backtest.application.delivery_schedules import CompileDeliveryScheduleRequest
from backtest.application.models import ArtifactDraft, ArtifactKind, DatasetSpec

# Import replay packs at the visible module dependency boundary.
from backtest.application.replay_packs import ReplaySemanticsManifest
from backtest.application.run_specs import ResolvedComponent
from backtest.application.use_cases.compile_delivery_schedule import CompileDeliverySchedule
from backtest.domain.account_requirements import (
    AccountRequirement,
    AccountRequirementScope,
    PricedAccountRequirement,
)
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    # Include solana mainnet network id so the chain dependency remains explicit.
    SOLANA_MAINNET_NETWORK_ID,
    ChainPosition,
)
from backtest.domain.event_hashing import canonical_event_stream_hash
from backtest.domain.execution import ExecutionMode, Fill

# Import fidelity at the visible module dependency boundary.
from backtest.domain.fidelity import OrderingFidelity
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import (
    AccountId,
    AssetId,
    # Include bundle id so the identifiers dependency remains explicit.
    BundleId,
    CapabilityId,
    ContentDigest,
    DatasetRevisionId,
    DeliveryScheduleId,
    # Include logical content hash so the identifiers dependency remains explicit.
    LogicalContentHash,
    ReplayPackId,
    RuntimeLockId,
    SnapshotId,
    VenueId,
    # Close the identifiers import after its required symbols are visible.
)
from backtest.domain.ledger import AccountKind, LedgerTransaction
from backtest.domain.market_events import (
    BlockEvent,
    CanonicalEvent,
    # Include event envelope so the market events dependency remains explicit.
    EventEnvelope,
    TokenLaunchEvent,
    VenueLifecycleEvent,
    VenueLifecycleKind,
    VenueTradeEvent,
    # Close the market events import after its required symbols are visible.
)
from backtest.domain.roundtrips import MtmStatus, RoundTripRecord, RoundTripStatus
from backtest.domain.time import BlockRange
from backtest.engine.contracts import EnginePhysicalSettings
from backtest.engine.replay import ObservationDelivery, ObservationDeliverySource, ReplayBoundary

# Import rng at the visible module dependency boundary.
from backtest.engine.rng import RNG_ALGORITHM
from backtest.engine.sniping import (
    SnipingEngineError,
    SnipingEngineErrorCode,
    SnipingReferenceEngine,
    # Include sniping run config so the sniping dependency remains explicit.
    SnipingRunConfig,
    SnipingRunSummary,
)
from backtest.engine.sniping_contracts import NetworkCostQuote
from backtest.engine.transaction_clock import CompactTransactionClock
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
)
from backtest.plugins.strategies import PumpfunSnipingStrategy
from tests.support.replay_v3 import (
    FIXTURE_DECISION_RANGE,
    # Include fixture dataset spec so the replay v3 dependency remains explicit.
    fixture_dataset_spec,
    fixture_snapshot_manifest,
)

SOL = AssetId("SOL")
NETWORK_FEE_ASSET = AssetId("NETWORK-FEE")
# Bind account deposit asset once as an explicit module-level contract.
ACCOUNT_DEPOSIT_ASSET = AssetId("ACCOUNT-DEPOSIT")
BASE_TIME_S = 1_750_000_000


# Keep the canonical source contract and validation rules together.
@dataclass(frozen=True, slots=True)
class _CanonicalSource:
    values: tuple[CanonicalEvent, ...]

    @property
    def dataset_revision_id(self) -> DatasetRevisionId:
        # Return the completed canonical source dataset revision id result without a
        # hidden fallback.
        return DatasetRevisionId("d" * 64)

    @property
    def logical_content_hash(self) -> LogicalContentHash:
        return canonical_event_stream_hash(self.values)

    @property
    # Define canonical source replay semantics id as one focused operation with an
    # explicit boundary.
    def replay_semantics_id(self) -> ContentDigest:
        return ReplaySemanticsManifest.canonical_v3().replay_semantics_id

    @property
    def decision_range(self) -> BlockRange:
        return FIXTURE_DECISION_RANGE

    # Apply property semantics to the following canonical source dataset spec contract.
    @property
    def dataset_spec(self) -> DatasetSpec:
        return fixture_dataset_spec()

    @property
    def event_count(self) -> int:
        # Return the completed canonical source event count result without a hidden
        # fallback.
        return len(self.values)

    def boundaries(self) -> tuple[ReplayBoundary, ...]:
        # Execute the canonical source boundaries workflow in explicit, reviewable steps.
        result: list[ReplayBoundary] = []
        previous: int | None = None
        for event in self.values:
            # Process self.values inside the bounded canonical source boundaries loop.
            if event.envelope.boundary_ordinal != previous:
                # Handle the canonical source boundaries boundary ordinal, previous and
                # envelope condition as a distinct block.
                result.append(ReplayBoundary.from_position(event.envelope.position))
                previous = event.envelope.boundary_ordinal
        return tuple(result)

    def events(self) -> Iterator[CanonicalEvent]:
        yield from self.values

    # Define canonical source event at as one focused operation with an explicit boundary.
    def event_at(self, event_row_index: int) -> CanonicalEvent:
        return self.values[event_row_index]


# Keep the sink contract and validation rules together.
@dataclass(slots=True)
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

    def roundtrip_bytes(self) -> tuple[bytes, ...]:
        # Return the completed sink roundtrip bytes result without a hidden fallback.
        return tuple(canonical_json_bytes(record.document()) for record in self.roundtrips)


# Keep the columnar schedule contract and validation rules together.
@dataclass(frozen=True, slots=True)
class _ColumnarSchedule:
    release_values: tuple[int, ...]
    row_values: tuple[int, ...]
    input_event_count: int

    # Apply property semantics to the following columnar schedule delivery count contract.
    @property
    def delivery_count(self) -> int:
        return len(self.row_values)

    @property
    def outside_horizon_count(self) -> int:
        # Return the completed columnar schedule outside horizon count result without a
        # hidden fallback.
        return 0

    def deliveries(self) -> Iterator[ObservationDelivery]:
        # Execute the columnar schedule deliveries workflow in explicit, reviewable steps.
        for release, row in zip(self.release_values, self.row_values, strict=True):
            yield ObservationDelivery(release, row)

    def delivery_columns(self) -> tuple[tuple[int, ...], tuple[int, ...]]:
        return self.release_values, self.row_values


# Keep the split asset network costs contract and validation rules together.
class _SplitAssetNetworkCosts:
    bundle_id = BundleId("5" * 64)
    fee_collector_account_id = AccountId("network-fee:split-asset-equivalence")

    def quote_buy(
        self,
        # Close the quote buy signature after its explicit inputs.
        *,
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


def test_three_way_sniping_equivalence_and_physical_setting_independence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    # Close the test three way sniping equivalence and physical setting independence signature
    # after its explicit inputs.
) -> None:
    # Execute the test three way sniping equivalence and physical setting independence
    # workflow in explicit, reviewable steps.
    events = _events()
    canonical_source = _CanonicalSource(events)
    canonical_summary, canonical_sink = _run_reference(canonical_source, _clock())
    artifacts, replay_id = _compile(tmp_path, canonical_source)

    with NumpyMmapReplaySource(artifacts, replay_id) as replay:
        # Keep numpy mmap replay source, artifacts and replay id active only for the
        # bounded test three way sniping equivalence and physical setting independence
        # operation.
        replay_clock = replay.transaction_clock()
        assert replay_clock == _clock()
        replay_summary, replay_sink = _run_reference(replay, replay_clock)
        _assert_exact_equivalence(
            expected_summary=canonical_summary,
            # Pass expected sink explicitly so _assert_exact_equivalence receives a
            # reviewable canonical summary and canonical sink input in test three way
            # sniping equivalence and physical setting independence.
            expected_sink=canonical_sink,
            actual_summary=replay_summary,
            actual_sink=replay_sink,
        )
        delivery_schedule_id = _compile_delivery_schedule(artifacts, replay)

        # Acquire numpy mmap delivery schedule, artifacts and delivery schedule id at an
        # explicit test three way sniping equivalence and physical setting independence
        # context boundary so cleanup remains scoped.
        with NumpyMmapDeliverySchedule(artifacts, delivery_schedule_id) as schedule:
            # Keep numpy mmap delivery schedule, artifacts and delivery schedule id active
            # only for the bounded test three way sniping equivalence and physical setting
            # independence operation.
            materialized_summary, materialized_sink = _run_reference(
                replay,
                replay_clock,
                delivery_schedule=schedule,
            )
            # Invoke _assert_exact_equivalence for canonical summary and canonical sink as
            # a visible test three way sniping equivalence and physical setting
            # independence step.
            _assert_exact_equivalence(
                expected_summary=canonical_summary,
                expected_sink=canonical_sink,
                actual_summary=materialized_summary,
                actual_sink=materialized_sink,
                # Complete _assert_exact_equivalence only after its canonical summary and
                # canonical sink inputs are visible in test three way sniping equivalence and
                # physical setting independence.
            )

            def forbidden_event_decode(index: int) -> CanonicalEvent:
                # Execute the forbidden event decode workflow in explicit, reviewable
                # steps.
                del index
                raise AssertionError("optimized sniping hot loop decoded a CanonicalEvent")

            def forbidden_event_allocation(*args: object, **kwargs: object) -> None:
                # Execute the forbidden event allocation workflow in explicit, reviewable
                # steps.
                del args, kwargs
                raise AssertionError("optimized sniping hot loop allocated a CanonicalEvent")

            monkeypatch.setattr(replay, "_event", forbidden_event_decode)
            for event_type in (
                BlockEvent,
                # Traverse block event, token launch event and venue trade event
                # explicitly so each test three way sniping equivalence and physical
                # setting independence iteration remains traceable.
                TokenLaunchEvent,
                VenueTradeEvent,
                VenueLifecycleEvent,
            ):
                monkeypatch.setattr(event_type, "__init__", forbidden_event_allocation)

            # Traverse (2, 3, 32768, 65536, 131072, 262144) explicitly so each test three
            # way sniping equivalence and physical setting independence iteration remains
            # traceable.
            for batch_rows in (2, 3, 32_768, 65_536, 131_072, 262_144):
                # Process (2, 3, 32768, 65536, 131072, 262144) inside the bounded test
                # three way sniping equivalence and physical setting independence loop.
                for readahead in (1, 2, 4):
                    # Process (1, 2, 4) inside the bounded test three way sniping
                    # equivalence and physical setting independence loop.
                    for selected_schedule in (None, schedule):
                        # Process (None, schedule) inside the bounded test three way
                        # sniping equivalence and physical setting independence loop.
                        optimized_sink = _Sink()
                        optimized_summary = _optimized_engine().run(
                            source=replay,
                            clock=replay_clock,
                            strategy=_strategy(),
                            # Keep the protocol _protocol step visible while building
                            # optimized summary.
                            protocol=_protocol(),
                            network_costs=_network_costs(),
                            config=_config(),
                            sink=optimized_sink,
                            delivery_schedule=selected_schedule,
                            # Keep the batch rows EnginePhysicalSettings step visible
                            # while building optimized summary.
                            physical_settings=EnginePhysicalSettings(batch_rows, readahead, 1),
                        )
                        _assert_exact_equivalence(
                            expected_summary=canonical_summary,
                            expected_sink=canonical_sink,
                            # Pass actual summary explicitly so _assert_exact_equivalence
                            # receives a reviewable canonical summary and canonical sink
                            # input in test three way sniping equivalence and physical
                            # setting independence.
                            actual_summary=optimized_summary,
                            actual_sink=optimized_sink,
                        )


def test_split_cost_assets_are_exact_between_reference_and_optimized(
    tmp_path: Path,
    # Close the test split cost assets are exact between reference and optimized signature
    # after its explicit inputs.
) -> None:
    # Execute the test split cost assets are exact between reference and optimized
    # workflow in explicit, reviewable steps.
    source = _CanonicalSource(_events())
    clock = _clock()
    config = replace(
        _config(initial_sol=1_000_000_000),
        initial_available={
            # Pass sol explicitly so replace receives a reviewable config and sol input in
            # test split cost assets are exact between reference and optimized.
            SOL: 1_000_000_000,
            NETWORK_FEE_ASSET: 11,
            ACCOUNT_DEPOSIT_ASSET: 7,
        },
    )
    # Assemble expected sink once so the test split cost assets are exact between
    # reference and optimized workflow shares one value.
    expected_sink = _Sink()
    expected_summary = SnipingReferenceEngine().run(
        source=source,
        clock=clock,
        strategy=_strategy(),
        # Keep the protocol _protocol step visible while building expected summary.
        protocol=_protocol(),
        network_costs=_SplitAssetNetworkCosts(),
        config=config,
        sink=expected_sink,
    )
    # Assemble (artifacts, replay id) once so the test split cost assets are exact between
    # reference and optimized workflow shares one value.
    artifacts, replay_id = _compile(tmp_path, source)

    with NumpyMmapReplaySource(artifacts, replay_id) as replay:
        # Keep numpy mmap replay source, artifacts and replay id active only for the
        # bounded test split cost assets are exact between reference and optimized
        # operation.
        actual_sink = _Sink()
        actual_summary = NumpyMmapPumpfunSnipingEngine(
            strategy_type=PumpfunSnipingStrategy,
            protocol_type=PumpfunSnipingProtocolRuntime,
            network_cost_type=_SplitAssetNetworkCosts,
            # Complete NumpyMmapPumpfunSnipingEngine only after its pumpfun sniping strategy
            # and pumpfun sniping protocol runtime inputs are visible in test split cost
            # assets are exact between reference and optimized.
        ).run(
            source=replay,
            clock=replay.transaction_clock(),
            strategy=_strategy(),
            protocol=_protocol(),
            # Keep the split asset network costs _SplitAssetNetworkCosts step visible
            # while building actual summary.
            network_costs=_SplitAssetNetworkCosts(),
            config=config,
            sink=actual_sink,
            physical_settings=EnginePhysicalSettings(3, 2, 1),
        )

    # Invoke _assert_exact_equivalence for expected summary and expected sink as a visible
    # test split cost assets are exact between reference and optimized step.
    _assert_exact_equivalence(
        expected_summary=expected_summary,
        expected_sink=expected_sink,
        actual_summary=actual_summary,
        actual_sink=actual_sink,
        # Complete _assert_exact_equivalence only after its expected summary and expected sink
        # inputs are visible in test split cost assets are exact between reference and
        # optimized.
    )
    assert {
        posting.asset_id
        for transaction in actual_sink.ledger
        for posting in transaction.postings
        # Keep the posting expectation tied to asset id, network fee asset and posting in
        # this scenario.
        if posting.account.kind is AccountKind.NETWORK_FEE
    } == {NETWORK_FEE_ASSET}
    assert {
        posting.asset_id
        for transaction in actual_sink.ledger
        # Keep the posting expectation tied to asset id, account deposit asset and posting
        # in this scenario.
        for posting in transaction.postings
        if posting.account.kind is AccountKind.PORTFOLIO_LOCKED
    } == {ACCOUNT_DEPOSIT_ASSET}


# Keep the full-shortfall baseline visible as one bounded admission vector.
def test_virtual_settlement_is_exact_between_canonical_replay_and_optimized(
    tmp_path: Path,
) -> None:
    # The zero-real-reserve baseline exercises a fully synthetic successful sell.
    summary, sink = _run_virtual_three_way(
        tmp_path,
        _virtual_settlement_events(),
        _clock(),
    )
    # Summary funding must match the exact deterministic EXTERNAL ledger debit.
    assert summary.synthetic_liquidity_used_sell_count == 1
    assert summary.synthetic_funded_sell_atomic > 0
    assert _external_debit_atomic(sink) == summary.synthetic_funded_sell_atomic


# Prove virtual mode retains ordinary venue-funded settlement unchanged.
def test_virtual_real_sufficient_sell_is_three_way_exact(tmp_path: Path) -> None:
    # The strict fixture has ample venue SOL and is reusable under virtual semantics.
    summary, sink = _run_virtual_three_way(tmp_path, _events(), _clock())

    # Inspect both row evidence and bounded summary classification.
    (record,) = sink.roundtrips
    assert record.status is RoundTripStatus.CLOSED
    assert record.sell_landing_liquidity is not None
    assert record.sell_landing_liquidity.synthetic_shortfall_atomic == 0
    # A real-sufficient sell must not create an EXTERNAL synthetic debit.
    assert summary.real_liquidity_sufficient_filled_sell_count == 1
    assert summary.synthetic_liquidity_used_sell_count == 0
    assert _external_debit_atomic(sink) == 0


# Prove historical movement changes both quote evidence and the partial funding split.
def test_virtual_changing_quotes_and_partial_shortfall_are_three_way_exact(
    tmp_path: Path,
) -> None:
    # Two causal historical trades give decision and landing distinct reserve states.
    summary, sink = _run_virtual_three_way(
        tmp_path,
        _changing_partial_shortfall_events(),
        _clock(),
        # This vector isolates liquidity evidence rather than slippage rejection.
        sell_slippage_bps=10_000,
    )

    # Compare the two causal evidence snapshots before checking settlement.
    (record,) = sink.roundtrips
    reference = record.sell_reference_liquidity
    landing = record.sell_landing_liquidity
    assert record.status is RoundTripStatus.CLOSED
    assert reference is not None and landing is not None
    # Historical transactions between boundaries must change the exact quote evidence.
    assert reference.required_output_atomic != landing.required_output_atomic
    assert 0 < landing.synthetic_shortfall_atomic < landing.required_output_atomic
    assert record.settled_synthetic_funded_atomic == landing.synthetic_shortfall_atomic
    # The complementary venue amount proves the partial split conserves gross output.
    assert record.settled_venue_funded_atomic == (
        landing.required_output_atomic - landing.synthetic_shortfall_atomic
    )
    assert _external_debit_atomic(sink) == summary.synthetic_funded_sell_atomic


# Keep projected MTM liquidity separate from committed synthetic cash.
def test_virtual_open_mtm_shortfall_is_three_way_exact_without_external_posting(
    tmp_path: Path,
) -> None:
    # Leave no cash for the sell fee after the exact successful buy reservation.
    exact_buy_reservation = 1_000_000_000 + 5_001 + 2_039_280 + 1_844_400
    summary, sink = _run_virtual_three_way(
        tmp_path,
        _virtual_settlement_events(),
        _clock(),
        # Insufficient post-buy cash terminates before a sell can be submitted.
        initial_sol=exact_buy_reservation,
    )

    # Open-position valuation carries evidence but no successful settlement fields.
    (record,) = sink.roundtrips
    assert record.status is RoundTripStatus.SELL_PRE_SUBMIT_INSUFFICIENT_FUNDS_OPEN
    assert record.mtm_status is MtmStatus.EXECUTABLE
    assert record.mtm_liquidity is not None
    assert record.mtm_liquidity.synthetic_shortfall_atomic > 0
    # MTM evidence is a projection and cannot create spendable wallet proceeds.
    assert summary.open_position_count == 1
    assert summary.synthetic_funded_sell_atomic == 0
    assert _external_debit_atomic(sink) == 0


# Prove landing slippage failure cannot debit the synthetic source.
def test_virtual_slippage_failure_is_three_way_exact_without_synthetic_posting(
    tmp_path: Path,
) -> None:
    # An adverse landing state violates the zero-bps minimum-output boundary.
    summary, sink = _run_virtual_three_way(
        tmp_path,
        _virtual_slippage_failure_events(),
        _clock(),
    )

    # The landing quote exists, but the failed program transition settles no output.
    (record,) = sink.roundtrips
    assert record.status is RoundTripStatus.SELL_LANDED_FAILED_OPEN
    assert record.sell is not None
    assert record.sell.failure_code == "MINIMUM_OUTPUT_NOT_MET"
    assert record.sell_landing_liquidity is not None
    # Failed execution records potential shortage but settles none of it.
    assert record.sell_landing_liquidity.synthetic_shortfall_atomic > 0
    assert summary.synthetic_funded_sell_atomic == 0
    assert _external_debit_atomic(sink) == 0


# Prove a terminal lifecycle at landing cannot debit the synthetic source.
def test_virtual_migration_failure_is_three_way_exact_without_synthetic_posting(
    tmp_path: Path,
) -> None:
    # Migration lands after decision and makes the original Pump route non-executable.
    summary, sink = _run_virtual_three_way(
        tmp_path,
        _virtual_migration_failure_events(),
        _clock(),
    )

    # The failure remains an open position and cannot debit synthetic liquidity.
    (record,) = sink.roundtrips
    assert record.status is RoundTripStatus.SELL_LANDED_FAILED_OPEN
    assert record.sell is not None
    assert record.sell.failure_code == "PUMPSWAP_ROUTING_FORBIDDEN"
    # Migration failure pays network cost but never mints synthetic settlement.
    assert record.settled_synthetic_funded_atomic == 0
    assert summary.synthetic_funded_sell_atomic == 0
    assert _external_debit_atomic(sink) == 0


# Prove frozen historical states and shared-wallet spendability across two round trips.
def test_two_virtual_sells_reuse_observed_state_and_fund_the_next_buy(
    tmp_path: Path,
) -> None:
    # Initial cash can fund only one gross buy; the second depends on settled proceeds.
    gross_buy = 100_000_000
    initial_sol = 110_000_000
    # Run both launches through every exact backend with the same constrained wallet.
    summary, sink = _run_virtual_three_way(
        tmp_path,
        _two_virtual_roundtrips_events(),
        _two_virtual_roundtrips_clock(),
        # Carry the deliberately constrained wallet and smaller fixed budget to all paths.
        initial_sol=initial_sol,
        gross_buy_budget_atomic=gross_buy,
    )

    # Two accepted buys prove the first synthetic proceeds became spendable.
    assert initial_sol < gross_buy * 2
    assert summary.accepted_buy_count == 2
    assert summary.closed_roundtrip_count == 2
    assert summary.synthetic_liquidity_used_sell_count == 2
    assert all(record.status is RoundTripStatus.CLOSED for record in sink.roundtrips)
    # Both equal historical states yield equal shortage despite the first own sell.
    shortfalls = {
        record.sell_landing_liquidity.synthetic_shortfall_atomic
        for record in sink.roundtrips
        if record.sell_landing_liquidity is not None
    }
    # Equal shortages prove neither own sell mutated the observed curve input.
    assert len(shortfalls) == 1
    assert _external_debit_atomic(sink) == summary.synthetic_funded_sell_atomic


def test_optimized_matches_reference_for_cooldown_and_migration_failure(
    tmp_path: Path,
    # Close the test optimized matches reference for cooldown and migration failure signature
    # after its explicit inputs.
) -> None:
    # Execute the test optimized matches reference for cooldown and migration failure
    # workflow in explicit, reviewable steps.
    source = _CanonicalSource(_cooldown_and_migration_events())
    clock = _cooldown_and_migration_clock()
    expected_summary, expected_sink = _run_reference(
        source,
        clock,
        # Pass initial sol explicitly so _run_reference receives a reviewable source and
        # clock input in test optimized matches reference for cooldown and migration
        # failure.
        initial_sol=3_100_000_000,
    )
    artifacts, replay_id = _compile(tmp_path, source)

    with NumpyMmapReplaySource(artifacts, replay_id) as replay:
        # Keep numpy mmap replay source, artifacts and replay id active only for the
        # bounded test optimized matches reference for cooldown and migration failure
        # operation.
        actual_sink = _Sink()
        actual_summary = _optimized_engine().run(
            source=replay,
            clock=replay.transaction_clock(),
            strategy=_strategy(),
            # Keep the protocol _protocol step visible while building actual summary.
            protocol=_protocol(),
            network_costs=_network_costs(),
            config=_config(initial_sol=3_100_000_000),
            sink=actual_sink,
            physical_settings=EnginePhysicalSettings(3, 2, 1),
            # Complete run only after its transaction clock and strategy inputs are visible in
            # test optimized matches reference for cooldown and migration failure.
        )

    _assert_exact_equivalence(
        expected_summary=expected_summary,
        expected_sink=expected_sink,
        actual_summary=actual_summary,
        # Pass actual sink explicitly so _assert_exact_equivalence receives a reviewable
        # expected summary and expected sink input in test optimized matches reference for
        # cooldown and migration failure.
        actual_sink=actual_sink,
    )
    assert actual_summary.target_count == 3
    assert actual_summary.cooldown_skipped_count == 1
    assert actual_summary.closed_roundtrip_count == 1
    # Verify actual_summary.failed_buy_count == 1 before this scenario is accepted.
    assert actual_summary.failed_buy_count == 1
    assert [record.status for record in actual_sink.roundtrips] == [
        RoundTripStatus.CLOSED,
        RoundTripStatus.COOLDOWN_SKIPPED,
        RoundTripStatus.BUY_LANDED_FAILED,
        # Verify the status, closed and cooldown skipped relationship before this scenario is
        # accepted.
    ]


def test_total_target_state_arena_is_hard_bounded_for_both_backends(tmp_path: Path) -> None:
    # Execute the test total target state arena is hard bounded for both backends workflow
    # in explicit, reviewable steps.
    source = _CanonicalSource(_cooldown_and_migration_events())
    clock = _cooldown_and_migration_clock()
    bounded_config = _config(initial_sol=3_100_000_000, maximum_dynamic_items=2)

    with pytest.raises(SnipingEngineError) as reference_error:
        # Keep raises, sniping engine error and pytest active only for the bounded test
        # total target state arena is hard bounded for both backends operation.
        SnipingReferenceEngine().run(
            source=source,
            clock=clock,
            strategy=_strategy(),
            protocol=_protocol(),
            # Pass network costs explicitly to run for strategy and protocol.
            network_costs=_network_costs(),
            config=bounded_config,
        )
    assert reference_error.value.code is SnipingEngineErrorCode.DYNAMIC_ITEM_LIMIT_EXCEEDED

    artifacts, replay_id = _compile(tmp_path, source)
    # Acquire numpy mmap replay source, artifacts and replay id at an explicit test total
    # target state arena is hard bounded for both backends context boundary so cleanup
    # remains scoped.
    with (
        NumpyMmapReplaySource(artifacts, replay_id) as replay,
        pytest.raises(SnipingEngineError) as optimized_error,
    ):
        # Keep numpy mmap replay source, artifacts and replay id active only for the
        # bounded test total target state arena is hard bounded for both backends
        # operation.
        _optimized_engine().run(
            source=replay,
            clock=replay.transaction_clock(),
            strategy=_strategy(),
            protocol=_protocol(),
            # Pass network costs explicitly to run for transaction clock and strategy.
            network_costs=_network_costs(),
            config=bounded_config,
            physical_settings=EnginePhysicalSettings(3, 1, 1),
        )
    assert optimized_error.value.code is SnipingEngineErrorCode.DYNAMIC_ITEM_LIMIT_EXCEEDED


# Define test optimized schedule mismatch fails before protocol mutation as one focused
# operation with an explicit boundary.
def test_optimized_schedule_mismatch_fails_before_protocol_mutation(tmp_path: Path) -> None:
    # Execute the test optimized schedule mismatch fails before protocol mutation workflow
    # in explicit, reviewable steps.
    source = _CanonicalSource(_events())
    artifacts, replay_id = _compile(tmp_path, source)

    with NumpyMmapReplaySource(artifacts, replay_id) as replay:
        # Keep numpy mmap replay source, artifacts and replay id active only for the
        # bounded test optimized schedule mismatch fails before protocol mutation
        # operation.
        protocol = _protocol()
        malformed = _ColumnarSchedule(
            release_values=tuple(
                int(value) + (1 if index == 0 else 0)
                for index, value in enumerate(
                    # Keep the arrays and replay arrays step visible while building
                    # malformed.
                    replay.arrays()[replay_physical.ENVELOPE_BOUNDARY_ORDINAL]
                )
            ),
            row_values=tuple(range(replay.event_count)),
            input_event_count=replay.event_count,
            # Complete _ColumnarSchedule only after its envelope boundary ordinal and arrays
            # inputs are visible in test optimized schedule mismatch fails before protocol
            # mutation.
        )
        with pytest.raises(SnipingEngineError) as rejected:
            # Keep raises, sniping engine error and pytest active only for the bounded
            # test optimized schedule mismatch fails before protocol mutation operation.
            _optimized_engine().run(
                source=replay,
                clock=replay.transaction_clock(),
                strategy=_strategy(),
                protocol=protocol,
                # Pass network costs explicitly to run for transaction clock and strategy.
                network_costs=_network_costs(),
                config=_config(),
                delivery_schedule=malformed,
                physical_settings=EnginePhysicalSettings(3, 1, 1),
            )

    # Verify the code, delivery schedule invalid and value relationship before this
    # scenario is accepted.
    assert rejected.value.code is SnipingEngineErrorCode.DELIVERY_SCHEDULE_INVALID
    assert protocol._curves == {}


def _assert_exact_equivalence(
    *,
    expected_summary: SnipingRunSummary,
    # Keep the expected sink input explicit in the assert exact equivalence contract.
    expected_sink: _Sink,
    actual_summary: SnipingRunSummary,
    actual_sink: _Sink,
) -> None:
    # Execute the assert exact equivalence workflow in explicit, reviewable steps.
    assert actual_summary == expected_summary
    assert actual_summary.result_hash == expected_summary.result_hash
    assert actual_summary.audit_hash == expected_summary.audit_hash
    assert actual_summary.ledger_hash == expected_summary.ledger_hash
    assert actual_summary.fill_hash == expected_summary.fill_hash
    # Verify the roundtrip digest, actual summary and expected summary relationship before
    # this scenario is accepted.
    assert actual_summary.roundtrip_digest == expected_summary.roundtrip_digest
    assert actual_summary.final_balances_digest == expected_summary.final_balances_digest
    assert actual_sink.audits == expected_sink.audits
    assert actual_sink.ledger == expected_sink.ledger
    assert actual_sink.fills == expected_sink.fills
    # Verify the roundtrip bytes, actual sink and expected sink relationship before this
    # scenario is accepted.
    assert actual_sink.roundtrip_bytes() == expected_sink.roundtrip_bytes()


# Keep actual synthetic ledger funding reusable across admission vectors.
def _external_debit_atomic(sink: _Sink) -> int:
    """Return synthetic funding debited from deterministic EXTERNAL accounts."""

    return -sum(
        posting.amount_atomic
        for transaction in sink.ledger
        for posting in transaction.postings
        # Other future EXTERNAL accounts must not be confused with virtual settlement.
        if posting.account.kind is AccountKind.EXTERNAL
        and posting.account.account_id.value.startswith("synthetic-liquidity:pumpfun:")
    )


# Run the readable oracle against either canonical rows or verified ReplayPack bytes.
def _run_reference(
    source: _CanonicalSource | NumpyMmapReplaySource,
    clock: CompactTransactionClock,
    *,
    # Keep the initial sol input explicit in the run reference contract.
    initial_sol: int = 2_000_000_000,
    delivery_schedule: ObservationDeliverySource | None = None,
    execution_mode: ExecutionMode = ExecutionMode.EXOGENOUS_REPLAY,
    # These strategy parameters let failure vectors share the same runner.
    gross_buy_budget_atomic: int = 1_000_000_000,
    sell_slippage_bps: int = 0,
) -> tuple[SnipingRunSummary, _Sink]:
    # Execute the run reference workflow in explicit, reviewable steps.
    sink = _Sink()
    summary = SnipingReferenceEngine().run(
        source=source,
        clock=clock,
        # Use the exact same semantic strategy inputs as the optimized comparison.
        strategy=_strategy(
            execution_mode=execution_mode,
            gross_buy_budget_atomic=gross_buy_budget_atomic,
            sell_slippage_bps=sell_slippage_bps,
        ),
        # Keep the protocol _protocol step visible while building summary.
        protocol=_protocol(),
        network_costs=_network_costs(),
        config=_config(initial_sol=initial_sol, execution_mode=execution_mode),
        sink=sink,
        delivery_schedule=delivery_schedule,
        # Complete run only after its strategy and protocol inputs are visible in run
        # reference.
    )
    return summary, sink


# Centralize three-way equivalence so every vector compares the same surfaces.
def _run_virtual_three_way(
    tmp_path: Path,
    events: tuple[CanonicalEvent, ...],
    clock: CompactTransactionClock,
    *,
    # Wallet and strategy variations are semantic test operands, never backend knobs.
    initial_sol: int = 2_000_000_000,
    gross_buy_budget_atomic: int = 1_000_000_000,
    sell_slippage_bps: int = 0,
) -> tuple[SnipingRunSummary, _Sink]:
    """Compare canonical, ReplayPack reference, and optimized virtual execution."""

    mode = ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT
    source = _CanonicalSource(events)
    # Canonical Parquet-equivalent objects remain the first semantic oracle.
    expected_summary, expected_sink = _run_reference(
        source,
        clock,
        initial_sol=initial_sol,
        # Carry strategy behavior identically through all three execution paths.
        execution_mode=mode,
        gross_buy_budget_atomic=gross_buy_budget_atomic,
        sell_slippage_bps=sell_slippage_bps,
    )
    # Compile exactly the canonical source already consumed by the first oracle.
    artifacts, replay_id = _compile(tmp_path, source)

    with NumpyMmapReplaySource(artifacts, replay_id) as replay:
        # The readable engine must remain byte-identical after ReplayPack decoding.
        replay_summary, replay_sink = _run_reference(
            replay,
            replay.transaction_clock(),
            initial_sol=initial_sol,
            # ReplayPack reference remains the semantic bridge to the optimized path.
            execution_mode=mode,
            gross_buy_budget_atomic=gross_buy_budget_atomic,
            sell_slippage_bps=sell_slippage_bps,
        )
        # Check every bounded financial/result stream, not only the headline hash.
        _assert_exact_equivalence(
            expected_summary=expected_summary,
            expected_sink=expected_sink,
            # Compare the decoded ReplayPack run back to canonical object replay.
            actual_summary=replay_summary,
            actual_sink=replay_sink,
        )

        # Only after the ReplayPack oracle passes may the optimized path be admitted.
        optimized_sink = _Sink()
        optimized_summary = _optimized_engine().run(
            source=replay,
            clock=replay.transaction_clock(),
            # Keep strategy semantics identical to both readable oracle executions.
            strategy=_strategy(
                execution_mode=mode,
                gross_buy_budget_atomic=gross_buy_budget_atomic,
                sell_slippage_bps=sell_slippage_bps,
            ),
            # Use the same resolved protocol/network profiles as both reference paths.
            protocol=_protocol(),
            network_costs=_network_costs(),
            config=_config(initial_sol=initial_sol, execution_mode=mode),
            # Physical settings remain attempt provenance, not semantic inputs.
            sink=optimized_sink,
            physical_settings=EnginePhysicalSettings(3, 2, 1),
        )

    # The optimized output must equal the canonical oracle byte for byte.
    _assert_exact_equivalence(
        expected_summary=expected_summary,
        expected_sink=expected_sink,
        # Compare all optimized streams back to the original canonical oracle.
        actual_summary=optimized_summary,
        actual_sink=optimized_sink,
    )
    return optimized_summary, optimized_sink


# Compile the optional exact delivery schedule used by the broader strict matrix.
def _compile_delivery_schedule(
    artifacts: LocalArtifactRepository,
    replay: NumpyMmapReplaySource,
    # Keep the delivery schedule id input explicit in the compile delivery schedule contract.
) -> DeliveryScheduleId:
    # Execute the compile delivery schedule workflow in explicit, reviewable steps.
    components = (
        ResolvedComponent.create(
            role="clock",
            bundle_id=BundleId("1" * 64),
            config={
                # Keep block time resolution named so the clock and 1 payload passed to
                # create remains self-describing within compile delivery schedule.
                "block_time_resolution": "seconds-v1",
                "contract": "compact-global-transaction-clock-v1",
            },
        ),
        ResolvedComponent.create(
            # Pass role explicitly so create receives a reviewable engine and 2 input in
            # compile delivery schedule.
            role="engine",
            bundle_id=BundleId("2" * 64),
            config={
                "execution_mode": "EXOGENOUS_REPLAY",
                "maximum_dynamic_items": 1_000_000,
                # Keep run contract named so the engine and 2 payload passed to create
                # remains self-describing within compile delivery schedule.
                "run_contract": "pumpfun-sniping-run-draft/v3",
            },
        ),
        ResolvedComponent.create(
            role="latency",
            # Register bundle id through BundleId so the components table remains
            # scannable.
            bundle_id=BundleId("3" * 64),
            config={
                "buy_delay_transactions": 500,
                "sell_decision_delay_seconds": 2,
                "sell_delay_transactions": 1,
                # Close the latency and 3 payload only after all compile delivery schedule
                # fields are present.
            },
        ),
        ResolvedComponent.create(
            role="scheduler",
            bundle_id=BundleId("4" * 64),
            # Pass config explicitly so create receives a reviewable scheduler and 4 input
            # in compile delivery schedule.
            config={
                "phase_table": "canonical-v1",
                "synthetic_boundary_merge": "historical-synthetic-two-way-merge-v1",
            },
        ),
        # Complete the components group only after its semantic components are visible.
    )
    compiled = CompileDeliverySchedule(
        LocalNumpyDeliveryScheduleCompiler(
            artifacts,
            runtime_lock_id=RuntimeLockId("9" * 64),
            # Complete LocalNumpyDeliveryScheduleCompiler only after its 9 and runtime lock id
            # inputs are visible in compile delivery schedule.
        )
    ).execute(
        CompileDeliveryScheduleRequest(
            replay_pack_id=replay.replay_pack_id,
            replay_semantics_id=replay.replay_semantics_id,
            # Pass replay layout schema id explicitly so CompileDeliveryScheduleRequest
            # receives a reviewable replay pack id and replay semantics id input in
            # compile delivery schedule.
            replay_layout_schema_id=replay.replay_layout_schema_id,
            components=components,
            rng_algorithm=RNG_ALGORITHM,
            root_seed=7,
            compiler_version=delivery_physical.COMPILER_VERSION,
            # Complete CompileDeliveryScheduleRequest only after its replay pack id and replay
            # semantics id inputs are visible in compile delivery schedule.
        )
    )
    return compiled.delivery_schedule_id


def _optimized_engine() -> NumpyMmapPumpfunSnipingEngine:
    # Execute the optimized engine workflow in explicit, reviewable steps.
    return NumpyMmapPumpfunSnipingEngine(
        strategy_type=PumpfunSnipingStrategy,
        protocol_type=PumpfunSnipingProtocolRuntime,
        network_cost_type=SolanaSnipingCostModel,
    )


# Define strategy as one focused operation with an explicit boundary.
def _strategy(
    *,
    execution_mode: ExecutionMode = ExecutionMode.EXOGENOUS_REPLAY,
    # Vary only the behaviors required by the bounded equivalence vectors.
    gross_buy_budget_atomic: int = 1_000_000_000,
    sell_slippage_bps: int = 0,
) -> PumpfunSnipingStrategy:
    # Execute the strategy workflow in explicit, reviewable steps.
    return PumpfunSnipingStrategy(
        quote_asset_id=SOL,
        gross_buy_budget_atomic=gross_buy_budget_atomic,
        buy_slippage_bps=0,
        sell_slippage_bps=sell_slippage_bps,
        # Pass sell delay transactions explicitly so PumpfunSnipingStrategy receives a
        # reviewable sol input in strategy.
        sell_delay_transactions=1,
        execution_mode=execution_mode,
    )


def _protocol() -> PumpfunSnipingProtocolRuntime:
    # Execute the protocol workflow in explicit, reviewable steps.
    return PumpfunSnipingProtocolRuntime(
        quote_asset_id=SOL,
        fee_profile=PumpFeeProfile.static_95_30(
            profile_id="pump-static-95-30-equivalence-v1",
            effective_from_unix_s=1_700_000_000,
            # Pass effective until unix s explicitly so static_95_30 receives a reviewable
            # pump-static-95-30-equivalence-v1 input in protocol.
            effective_until_unix_s=1_800_000_000,
        ),
        protocol_version="pump-program-v1",
    )


def _network_costs() -> SolanaSnipingCostModel:
    # Execute the network costs workflow in explicit, reviewable steps.
    return SolanaSnipingCostModel(
        buy_fee_profile=_fee("buy-fee-equivalence-v1", 10),
        sell_fee_profile=_fee("sell-fee-equivalence-v1", 20),
        account_cost_profile=SolanaAccountCostProfile(
            profile_id="account-cost-equivalence-v1",
            # Pass effective from unix s explicitly so SolanaAccountCostProfile receives a
            # reviewable account-cost-equivalence-v1 and pump-token-account-v1 input in
            # network costs.
            effective_from_unix_s=1_700_000_000,
            effective_until_unix_s=1_800_000_000,
            costs=(
                SolanaAccountDepositCost(PUMPFUN_UVA_SCHEMA_ID, 1_844_400),
                SolanaAccountDepositCost(PUMPFUN_LEGACY_ATA_SCHEMA_ID, 2_039_280),
                SolanaAccountDepositCost(PUMPFUN_TOKEN_2022_ATA_SCHEMA_ID, 2_074_080),
            ),
        ),
        # Complete SolanaSnipingCostModel only after its buy-fee-equivalence-v1 and sell-fee-
        # equivalence-v1 inputs are visible in network costs.
    )


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


def _config(
    *,
    initial_sol: int = 2_000_000_000,
    maximum_dynamic_items: int = 1_000_000,
    execution_mode: ExecutionMode = ExecutionMode.EXOGENOUS_REPLAY,
    # Keep the sniping run config input explicit in the config contract.
) -> SnipingRunConfig:
    # Execute the config workflow in explicit, reviewable steps.
    return SnipingRunConfig(
        quote_asset_id=SOL,
        decision_range=FIXTURE_DECISION_RANGE,
        initial_available={SOL: initial_sol},
        initial_uva_state=WalletUvaInitialState.FRESH,
        # Pass wallet account profile id explicitly so SnipingRunConfig receives a
        # reviewable test-fresh-v1 and pump-token-account-v1 input in config.
        wallet_account_profile_id="test-fresh-v1",
        uva_schema_id=PUMPFUN_UVA_SCHEMA_ID,
        root_seed=7,
        maximum_dynamic_items=maximum_dynamic_items,
        execution_mode=execution_mode,
    )


# Define compile as one focused operation with an explicit boundary.
def _compile(
    tmp_path: Path,
    source: _CanonicalSource,
) -> tuple[LocalArtifactRepository, ReplayPackId]:
    # Execute the compile workflow in explicit, reviewable steps.
    artifacts = LocalArtifactRepository(tmp_path / "var")
    writer = artifacts.stage(ArtifactDraft(ArtifactKind.SNAPSHOT, ContentDigest("a" * 64)))
    snapshot = writer.commit(canonical_json_bytes(fixture_snapshot_manifest()))
    snapshot_id = SnapshotId(snapshot.artifact_id.hex)
    compiled = LocalNumpyReplayPackCompiler(
        # Pass artifacts explicitly so compile receives a reviewable snapshot id and
        # compiler version input in compile.
        artifacts,
        lambda requested: _checked_source(requested, snapshot_id, source),
        runtime_lock_id=RuntimeLockId("9" * 64),
    ).compile(snapshot_id, COMPILER_VERSION)
    return artifacts, compiled.replay_pack_id


# Define checked source as one focused operation with an explicit boundary.
def _checked_source(
    requested: SnapshotId,
    expected: SnapshotId,
    source: _CanonicalSource,
) -> _CanonicalSource:
    # Execute the checked source workflow in explicit, reviewable steps.
    if requested != expected:
        raise AssertionError("compiler requested another snapshot")
    return source


def _events() -> tuple[CanonicalEvent, ...]:
    # Execute the events workflow in explicit, reviewable steps.
    initial = _state()
    bundled = replace(
        initial,
        virtual_token_reserves_atomic=1_000_000_000_000_000,
        virtual_sol_reserves_lamports=32_000_000_000,
        # Pass real token reserves atomic explicitly so replace receives a reviewable
        # initial input in events.
        real_token_reserves_atomic=720_100_000_000_000,
        real_sol_reserves_lamports=102_000_000_000,
    )
    return (
        _block(100, transaction_count=501, block_time_s=BASE_TIME_S, identity=1),
        # Include launch in the completed events result.
        _launch(initial),
        _trade(bundled),
        _block(101, transaction_count=0, block_time_s=BASE_TIME_S + 1, identity=4),
        _block(102, transaction_count=2, block_time_s=BASE_TIME_S + 2, identity=5),
    )


# Build the smallest successful full-shortfall virtual settlement history.
def _virtual_settlement_events() -> tuple[CanonicalEvent, ...]:
    # Zero observed real SOL forces all gross sell output to synthetic funding.
    state = replace(_state(), real_sol_reserves_lamports=0)
    return (
        _block(100, transaction_count=501, block_time_s=BASE_TIME_S, identity=21),
        _launch(state, identity=22, group_identity=22),
        # Empty and non-empty blocks establish the exact +2-second sell boundary.
        _block(101, transaction_count=0, block_time_s=BASE_TIME_S + 1, identity=23),
        _block(102, transaction_count=2, block_time_s=BASE_TIME_S + 2, identity=24),
    )


# Build distinct decision and landing states with some real venue funding.
def _changing_partial_shortfall_events() -> tuple[CanonicalEvent, ...]:
    # Decision and landing trades expose two causally distinct historical states.
    initial = _state()
    decision = replace(
        initial,
        virtual_token_reserves_atomic=1_000_000_000_000_000,
        virtual_sol_reserves_lamports=34_000_000_000,
        # Limited real SOL forces an explicit shortfall at the decision quote too.
        real_sol_reserves_lamports=600_000_000,
    )
    # Landing state changes price again while retaining a non-zero venue share.
    landing = replace(
        decision,
        virtual_token_reserves_atomic=1_080_000_000_000_000,
        virtual_sol_reserves_lamports=31_000_000_000,
        # Retain some observed venue funding while forcing a partial synthetic shortage.
        real_sol_reserves_lamports=100_000_000,
    )
    # Block rows and trade rows stay in exact causal boundary order.
    return (
        _block(100, transaction_count=501, block_time_s=BASE_TIME_S, identity=25),
        _launch(initial, identity=26, group_identity=26),
        _block(101, transaction_count=0, block_time_s=BASE_TIME_S + 1, identity=27),
        _block(102, transaction_count=2, block_time_s=BASE_TIME_S + 2, identity=28),
        # These historical boundaries causally determine reference and landing quotes.
        _trade(decision, block=102, transaction=0, event_index=0, identity=29, group_identity=29),
        _trade(landing, block=102, transaction=1, event_index=0, identity=30, group_identity=30),
    )


# Build an adverse landing transition after an accepted sell reference.
def _virtual_slippage_failure_events() -> tuple[CanonicalEvent, ...]:
    # The reference quote uses initial reserves; only landing sees the adverse trade.
    initial = replace(_state(), real_sol_reserves_lamports=0)
    adverse = replace(
        initial,
        virtual_token_reserves_atomic=1_500_000_000_000_000,
        # Lower virtual SOL makes the exact-token-in landing quote adverse.
        virtual_sol_reserves_lamports=20_000_000_000,
    )
    # Only the transaction immediately before landing mutates historical state.
    return (
        _block(100, transaction_count=501, block_time_s=BASE_TIME_S, identity=31),
        _launch(initial, identity=32, group_identity=32),
        _block(101, transaction_count=0, block_time_s=BASE_TIME_S + 1, identity=33),
        _block(102, transaction_count=2, block_time_s=BASE_TIME_S + 2, identity=34),
        # Historical deterioration lands before the simulated sell at the same boundary.
        _trade(adverse, block=102, transaction=1, event_index=0, identity=35, group_identity=35),
    )


# Build migration at landing so the accepted original-venue order fails.
def _virtual_migration_failure_events() -> tuple[CanonicalEvent, ...]:
    # The terminal lifecycle is introduced only at the simulated landing boundary.
    initial = replace(_state(), real_sol_reserves_lamports=0)
    migrated = replace(initial, lifecycle=PumpCurveLifecycle.MIGRATED)
    return (
        _block(100, transaction_count=501, block_time_s=BASE_TIME_S, identity=36),
        _launch(initial, identity=37, group_identity=37),
        # The intervening empty block preserves the two-second timing rule.
        _block(101, transaction_count=0, block_time_s=BASE_TIME_S + 1, identity=38),
        _block(102, transaction_count=2, block_time_s=BASE_TIME_S + 2, identity=39),
        # Migration occurs at landing, after the sell reference was accepted.
        _lifecycle(migrated, block=102, transaction=1, identity=40, venue="curve"),
    )


# Build two complete horizons whose curves begin from equal observed state.
def _two_virtual_roundtrips_events() -> tuple[CanonicalEvent, ...]:
    # Two venues deliberately start from byte-identical observed curve state.
    shared_state = replace(_state(), real_sol_reserves_lamports=0)
    return (
        _block(100, transaction_count=501, block_time_s=BASE_TIME_S, identity=41),
        _launch(shared_state, identity=42, group_identity=42),
        # The first sell closes before the second target enters the historical stream.
        _block(101, transaction_count=0, block_time_s=BASE_TIME_S + 1, identity=43),
        _block(102, transaction_count=2, block_time_s=BASE_TIME_S + 2, identity=44),
        _block(103, transaction_count=501, block_time_s=BASE_TIME_S + 3, identity=45),
        # The second target arrives only after the first synthetic proceeds are spendable.
        _launch(
            shared_state,
            block=103,
            identity=46,
            group_identity=46,
            # Distinct asset/developer avoids both venue collision and cooldown suppression.
            token="TOKEN-B",
            venue="curve-b",
            developer="developer-b",
        ),
        # The second sell uses the same empty/non-empty +2-second clock shape.
        _block(104, transaction_count=0, block_time_s=BASE_TIME_S + 4, identity=47),
        _block(105, transaction_count=2, block_time_s=BASE_TIME_S + 5, identity=48),
    )


# Define cooldown and migration events as one focused operation with an explicit boundary.
def _cooldown_and_migration_events() -> tuple[CanonicalEvent, ...]:
    # Execute the cooldown and migration events workflow in explicit, reviewable steps.
    initial = _state()
    bundled = replace(
        initial,
        virtual_token_reserves_atomic=1_000_000_000_000_000,
        virtual_sol_reserves_lamports=32_000_000_000,
        # Pass real token reserves atomic explicitly so replace receives a reviewable
        # initial input in cooldown and migration events.
        real_token_reserves_atomic=720_100_000_000_000,
        real_sol_reserves_lamports=102_000_000_000,
    )
    return (
        _block(100, transaction_count=501, block_time_s=BASE_TIME_S, identity=10),
        # Include identity in the completed cooldown and migration events result.
        _launch(initial, identity=11, group_identity=11),
        _trade(bundled, identity=12, group_identity=11),
        _launch(
            initial,
            transaction=1,
            # Pass identity explicitly so _launch receives a reviewable token-b and
            # curve-b input in cooldown and migration events.
            identity=13,
            group_identity=13,
            token="TOKEN-B",
            venue="curve-b",
        ),
        # Include launch in the completed cooldown and migration events result.
        _launch(
            initial,
            transaction=2,
            identity=14,
            group_identity=14,
            # Pass token explicitly so _launch receives a reviewable token-c and curve-c
            # input in cooldown and migration events.
            token="TOKEN-C",
            venue="curve-c",
            developer="developer-c",
        ),
        _block(101, transaction_count=0, block_time_s=BASE_TIME_S + 1, identity=15),
        # Include transaction count in the completed cooldown and migration events result.
        _block(102, transaction_count=2, block_time_s=BASE_TIME_S + 2, identity=16),
        _lifecycle(
            replace(initial, lifecycle=PumpCurveLifecycle.MIGRATED),
            block=102,
            transaction=1,
            # Pass identity explicitly so _lifecycle receives a reviewable curve-c and
            # migrated input in cooldown and migration events.
            identity=17,
            venue="curve-c",
        ),
        _block(103, transaction_count=0, block_time_s=BASE_TIME_S + 3, identity=18),
        _block(104, transaction_count=2, block_time_s=BASE_TIME_S + 4, identity=19),
        # Return the completed cooldown and migration events result without a hidden fallback.
    )


def _state() -> PumpCurveStateV1:
    # Execute the state workflow in explicit, reviewable steps.
    return PumpCurveStateV1(
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


def _block(
    # Keep the block input explicit in the block contract.
    block: int,
    *,
    transaction_count: int,
    block_time_s: int,
    identity: int,
    # Keep the block event input explicit in the block contract.
) -> BlockEvent:
    # Execute the block workflow in explicit, reviewable steps.
    return BlockEvent(
        envelope=_envelope(
            block,
            -1,
            0,
            # Pass identity explicitly so _envelope receives a reviewable solana and
            # block-clock-v1 input in block.
            identity=identity,
            group_identity=identity,
            protocol="solana",
            protocol_version="block-clock-v1",
        ),
        # Pass block time ns explicitly so BlockEvent receives a reviewable solana and
        # block-clock-v1 input in block.
        block_time_ns=block_time_s * 1_000_000_000,
        tx_count=transaction_count,
        block_hash=f"block-{block}",
    )


# Build a launch at any bounded decision boundary used by the matrix.
def _launch(
    # Keep the state input explicit in the launch contract.
    state: PumpCurveStateV1,
    *,
    block: int = 100,
    transaction: int = 0,
    # Identity/group locate this immutable creation independently of its asset labels.
    identity: int = 2,
    group_identity: int = 2,
    # Keep the token input explicit in the launch contract.
    token: str = "TOKEN",
    venue: str = "curve",
    developer: str = "developer",
) -> TokenLaunchEvent:
    # Execute the launch workflow in explicit, reviewable steps.
    return TokenLaunchEvent(
        envelope=_envelope(
            block,
            transaction,
            0,
            # Pass identity explicitly so _envelope receives a reviewable transaction and
            # identity input in launch.
            identity=identity,
            group_identity=group_identity,
        ),
        asset_id=AssetId(token),
        developer_id=AccountId(developer),
        # Include creation user id in the completed launch result.
        creation_user_id=AccountId(f"payer-{token}"),
        venue_id=VenueId(venue),
        quote_asset_id=SOL,
        protocol_payload_schema=PUMPFUN_LAUNCH_PAYLOAD_SCHEMA_ID,
        protocol_payload=encode_launch_payload(state),
        # Complete TokenLaunchEvent only after its payer- and envelope inputs are visible in
        # launch.
    )


# Build a historical Pump trade whose payload carries the authoritative after-state.
def _trade(
    state: PumpCurveStateV1,
    *,
    block: int = 100,
    transaction: int = 0,
    # Event index permits both bundled and later one-instruction transaction fixtures.
    event_index: int = 1,
    identity: int = 3,
    # Keep the group identity input explicit in the trade contract.
    group_identity: int = 2,
    token: str = "TOKEN",
    venue: str = "curve",
) -> VenueTradeEvent:
    # Execute the trade workflow in explicit, reviewable steps.
    return VenueTradeEvent(
        envelope=_envelope(
            block,
            transaction,
            event_index,
            # Pass identity explicitly so _envelope receives a reviewable identity and
            # group identity input in trade.
            identity=identity,
            group_identity=group_identity,
        ),
        venue_id=VenueId(venue),
        sold_asset_id=SOL,
        # Include bought asset id in the completed trade result.
        bought_asset_id=AssetId(token),
        sold_amount_atomic=1,
        bought_amount_atomic=1,
        fee_components=(),
        protocol_payload_schema=PUMPFUN_TRADE_PAYLOAD_SCHEMA_ID,
        # Include protocol payload in the completed trade result.
        protocol_payload=encode_trade_payload(state),
    )


def _lifecycle(
    state: PumpCurveStateV1,
    *,
    # Keep the block input explicit in the lifecycle contract.
    block: int,
    transaction: int,
    identity: int,
    venue: str,
) -> VenueLifecycleEvent:
    # Execute the lifecycle workflow in explicit, reviewable steps.
    return VenueLifecycleEvent(
        envelope=_envelope(
            block,
            transaction,
            0,
            # Pass identity explicitly so _envelope receives a reviewable block and
            # transaction input in lifecycle.
            identity=identity,
            group_identity=identity,
        ),
        venue_id=VenueId(venue),
        lifecycle_kind=VenueLifecycleKind.MIGRATED,
        # Pass protocol payload schema explicitly so VenueLifecycleEvent receives a
        # reviewable migrated and envelope input in lifecycle.
        protocol_payload_schema=PUMPFUN_LIFECYCLE_PAYLOAD_SCHEMA_ID,
        protocol_payload=encode_lifecycle_payload(state),
    )


def _envelope(
    block: int,
    # Keep the transaction input explicit in the envelope contract.
    transaction: int,
    event_index: int,
    *,
    identity: int,
    group_identity: int,
    # Keep the protocol input explicit in the envelope contract.
    protocol: str = PUMPFUN_PROTOCOL_NAME,
    protocol_version: str = "pump-program-v1",
) -> EventEnvelope:
    # Execute the envelope workflow in explicit, reviewable steps.
    return EventEnvelope(
        position=ChainPosition(
            network_id=SOLANA_MAINNET_NETWORK_ID,
            position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            block_ordinal=block,
            # Pass transaction index explicitly so ChainPosition receives a reviewable
            # solana mainnet network id and block32 transaction32 position schema id input
            # in envelope.
            transaction_index=transaction,
            event_index=event_index,
        ),
        transaction_group_id=ContentDigest(f"{group_identity:064x}"),
        source_record_id=ContentDigest(f"{identity + 100:064x}"),
        # Include canonical event id in the completed envelope result.
        canonical_event_id=ContentDigest(f"{identity + 200:064x}"),
        stable_causal_id=ContentDigest(f"{identity + 300:064x}"),
        capability_id=CapabilityId("fixture.events.v1"),
        protocol=protocol,
        protocol_version=protocol_version,
        # Pass ordering fidelity explicitly so EventEnvelope receives a reviewable 064x
        # and v1 input in envelope.
        ordering_fidelity=OrderingFidelity.INSTRUCTION_EXACT,
    )


def _clock() -> CompactTransactionClock:
    # Execute the clock workflow in explicit, reviewable steps.
    return CompactTransactionClock(
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        block_ordinals=(100, 101, 102),
        transaction_counts=(501, 0, 2),
        # Pass cumulative transaction prefix explicitly so CompactTransactionClock
        # receives a reviewable solana mainnet network id and block32 transaction32
        # position schema id input in clock.
        cumulative_transaction_prefix=(0, 501, 501),
        block_time_ns=(
            BASE_TIME_S * 1_000_000_000,
            (BASE_TIME_S + 1) * 1_000_000_000,
            (BASE_TIME_S + 2) * 1_000_000_000,
            # Complete CompactTransactionClock only after its solana mainnet network id and
            # block32 transaction32 position schema id inputs are visible in clock.
        ),
    )


# Extend the base clock for a second complete buy/sell horizon.
def _two_virtual_roundtrips_clock() -> CompactTransactionClock:
    # The second launch has its own +500 and +2-second settlement horizon.
    return CompactTransactionClock(
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        block_ordinals=(100, 101, 102, 103, 104, 105),
        transaction_counts=(501, 0, 2, 501, 0, 2),
        # Prefixes count every transaction before each corresponding block.
        cumulative_transaction_prefix=(0, 501, 501, 503, 1_004, 1_004),
        block_time_ns=tuple((BASE_TIME_S + offset) * 1_000_000_000 for offset in range(6)),
    )


def _cooldown_and_migration_clock() -> CompactTransactionClock:
    # Execute the cooldown and migration clock workflow in explicit, reviewable steps.
    return CompactTransactionClock(
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        block_ordinals=(100, 101, 102, 103, 104),
        transaction_counts=(501, 0, 2, 0, 2),
        # Pass cumulative transaction prefix explicitly so CompactTransactionClock
        # receives a reviewable tuple and range input in cooldown and migration clock.
        cumulative_transaction_prefix=(0, 501, 501, 503, 503),
        block_time_ns=tuple((BASE_TIME_S + offset) * 1_000_000_000 for offset in range(5)),
    )


def test_fixture_exercises_bundled_post_group_quote_and_synthetic_landings() -> None:
    # Execute the test fixture exercises bundled post group quote and synthetic landings
    # workflow in explicit, reviewable steps.
    summary, sink = _run_reference(_CanonicalSource(_events()), _clock())

    assert summary.closed_roundtrip_count == 1
    (record,) = sink.roundtrips
    assert record.status is RoundTripStatus.CLOSED
    assert record.buy is not None and record.sell is not None
    # Verify the transaction index, landing position and buy relationship before this
    # scenario is accepted.
    assert record.buy.landing_position.transaction_index == 500
    assert record.sell.decision_position.block_ordinal == 102
    assert record.sell.decision_position.transaction_index == 0
    assert record.sell.landing_position.transaction_index == 1
