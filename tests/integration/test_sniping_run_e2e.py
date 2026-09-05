"""Hermetic Pump.fun Sniping resolver-to-results acceptance."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

# Import pathlib at the visible module dependency boundary.
from pathlib import Path

import pytest

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.adapters.columnar.arrow import (
    CanonicalParquetReplaySource,
    # Include local arrow canonical store so the arrow dependency remains explicit.
    LocalArrowCanonicalStore,
)
from backtest.adapters.columnar.numpy import (
    NUMPY_MMAP_PUMPFUN_SNIPING_BACKEND,
    LocalNumpyReplayPackCompiler,
    # Include numpy mmap pumpfun sniping engine so the numpy dependency remains explicit.
    NumpyMmapPumpfunSnipingEngine,
)
from backtest.adapters.columnar.numpy.layout import COMPILER_VERSION
from backtest.adapters.delivery_schedule import LocalDeliveryScheduleSourceFactory
from backtest.adapters.delivery_schedule.numpy import LocalNumpyDeliveryScheduleCompiler

# Import layout at the visible module dependency boundary.
from backtest.adapters.delivery_schedule.numpy.layout import (
    COMPILER_VERSION as DELIVERY_COMPILER_VERSION,
)
from backtest.adapters.replay import LocalReplaySourceFactory
from backtest.adapters.results import LocalParquetRunOutputStore

# Import parquet at the visible module dependency boundary.
from backtest.adapters.results.parquet import LocalParquetRunResultReaderFactory
from backtest.application.canonical_data import PreparedSnapshot, ProjectedEventBatch
from backtest.application.delivery_schedules import (
    CompiledDeliverySchedule,
    CompileDeliveryScheduleRequest,
    # Close the delivery schedules import after its required symbols are visible.
)
from backtest.application.errors import SnapshotValidationError, SnapshotValidationErrorCode
from backtest.application.models import (
    CAPABILITY_PROOF_FIELDS,
    DATASET_SPEC_VERSION,
    # Include pumpfun sniping source contract so the models dependency remains explicit.
    PUMPFUN_SNIPING_SOURCE_CONTRACT,
    ArtifactDraft,
    ArtifactKind,
    BudgetReport,
    BudgetStatus,
    # Include capability cut evidence so the models dependency remains explicit.
    CapabilityCutEvidence,
    CapabilityExtractionRange,
    CapabilityProofs,
    CapabilityStream,
    DatasetPlan,
    # Include dataset shard so the models dependency remains explicit.
    DatasetShard,
    DatasetSpec,
    EvidenceStatus,
    PlannedCapability,
    QueryLimits,
    # Include dataset spec identity digest so the models dependency remains explicit.
    dataset_spec_identity_digest,
)
from backtest.application.ports.runs import RunOutputSession
from backtest.application.run_drafts import (
    PumpFeeProfileDraft,
    # Include pumpfun sniping run draft so the run drafts dependency remains explicit.
    PumpfunSnipingRunDraft,
    SolanaAccountDepositCostDraft,
    SolanaFeeProfileDraft,
    WalletAccountMode,
    WalletAccountProfileDraft,
)

# Import run results at the visible module dependency boundary.
from backtest.application.run_results import RunBackend, RunPhysicalSettings
from backtest.application.run_specs import ResolvedRunSpec
from backtest.application.sniping_run_contract import PUMPFUN_SNIPING_UNIVERSE_POLICY_ID
from backtest.application.source_contracts import pumpfun_sniping_settlement_requirement
from backtest.application.source_evidence import (
    PUMPFUN_TERMINAL_LIFECYCLE_ORDERING_POLICY_ID,
    SOLANA_SKIPPED_SLOT_SENTINEL_POLICY_ID,
    LaunchUniverseEvidence,
    PumpfunSnipingSourceEvidenceBinding,
    SkippedSlotSentinelEvidence,
    SourceEvidenceReceiptRef,
    TerminalLifecycleOrderingEvidence,
)
from backtest.application.use_cases.compile_delivery_schedule import CompileDeliverySchedule
from backtest.application.use_cases.query_run_results import QueryRunResults

# Import run backtest at the visible module dependency boundary.
from backtest.application.use_cases.run_backtest import (
    RunBacktest,
    RunBacktestRequest,
    RunPreflightError,
)

# Import reference run resolver at the visible module dependency boundary.
from backtest.bootstrap.reference_run_resolver import ReferenceRunSpecResolver
from backtest.bootstrap.runtime_plugins import ReferenceRuntimeComponentsResolver
from backtest.bootstrap.sniping_run_resolver import PumpfunSnipingRunResolutionError
from backtest.bootstrap.sniping_runtime import PumpfunSnipingRuntimeComponentsResolver
from backtest.domain.chain import (
    # Include block32 transaction32 position schema id so the chain dependency remains
    # explicit.
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
    ChainPosition,
)
from backtest.domain.execution import ExecutionMode
from backtest.domain.fidelity import (
    # Include chain finality so the fidelity dependency remains explicit.
    ChainFinality,
    FeesFidelity,
    IdentityFidelity,
    IngestionCompleteness,
    OrderingFidelity,
    # Include source consistency so the fidelity dependency remains explicit.
    SourceConsistency,
    SourceFidelity,
    StateFidelity,
)
from backtest.domain.hashing import canonical_json_bytes

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import (
    AccountId,
    ArtifactId,
    AssetId,
    BundleId,
    # Include capability id so the identifiers dependency remains explicit.
    CapabilityId,
    ContentDigest,
    DatasetRevisionId,
    ExecutionAttemptId,
    ReplayPackId,
    # Include runtime lock id so the identifiers dependency remains explicit.
    RuntimeLockId,
    SnapshotId,
    SourceId,
    VenueId,
)

# Import market events at the visible module dependency boundary.
from backtest.domain.market_events import (
    BlockEvent,
    CanonicalEvent,
    EventEnvelope,
    EventKind,
    # Include token launch event so the market events dependency remains explicit.
    TokenLaunchEvent,
    VenueTradeEvent,
)
from backtest.domain.roundtrips import RoundTripStatus
from backtest.domain.time import BlockRange

# Import engine at the visible module dependency boundary.
from backtest.engine import ReferenceBacktestEngine, SnipingReferenceEngine
from backtest.engine.rng import RNG_ALGORITHM
from backtest.plugins.networks.solana import (
    SOLANA_LEGACY_V0_FEE_FORMULA_V1,
    SolanaSnipingCostModel,
    # Close the solana import after its required symbols are visible.
)
from backtest.plugins.protocols.pumpfun import (
    PUMP_BUY_EXACT_GROSS_SOL_FORMULA_V1,
    PUMP_SELL_EXACT_TOKEN_IN_FORMULA_V1,
    PUMP_STATIC_PROGRAM_CONTRACT_V1,
    # Include pumpfun launch payload schema id so the pumpfun dependency remains explicit.
    PUMPFUN_LAUNCH_PAYLOAD_SCHEMA_ID,
    PUMPFUN_LEGACY_ATA_SCHEMA_ID,
    PUMPFUN_PROTOCOL_NAME,
    PUMPFUN_TOKEN_2022_ATA_SCHEMA_ID,
    PUMPFUN_TRADE_PAYLOAD_SCHEMA_ID,
    PUMPFUN_UVA_SCHEMA_ID,
    PumpCurveLifecycle,
    PumpCurveStateV1,
    # Include pumpfun snapshot validator so the pumpfun dependency remains explicit.
    PumpfunSnapshotValidator,
    PumpfunSnipingProtocolRuntime,
    PumpMode,
    encode_launch_payload,
    encode_trade_payload,
    # Close the pumpfun import after its required symbols are visible.
)
from backtest.plugins.strategies import PumpfunSnipingStrategy

_SOL = AssetId("SOL")
_BASE_TIME_S = 1_750_000_000
_RUNTIME_LOCK_ID = RuntimeLockId("9" * 64)
# Bind source id once as an explicit module-level contract.
_SOURCE_ID = SourceId("hermetic-sniping-e2e")
_BLOCK_CAPABILITY = CapabilityId("fixture.block-clock.v1")
_LAUNCH_CAPABILITY = CapabilityId("fixture.pump-launch.v1")
_TRADE_CAPABILITY = CapabilityId("fixture.pump-trade.v1")
_LIFECYCLE_CAPABILITY = CapabilityId("fixture.pump-lifecycle.v1")
# Bind projector bundle id once as an explicit module-level contract.
_PROJECTOR_BUNDLE_ID = BundleId("6" * 64)
_DECISION_RANGE = BlockRange(
    SOLANA_MAINNET_NETWORK_ID,
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    100,
    # Keep block range, solana mainnet network id and block32 transaction32 position
    # schema id visible while completing BlockRange within module.
    101,
)
_SETTLEMENT_TAIL = BlockRange(
    SOLANA_MAINNET_NETWORK_ID,
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    # Keep block range, solana mainnet network id and block32 transaction32 position
    # schema id visible while completing BlockRange within module.
    101,
    103,
)
_EXTRACTION_RANGE = BlockRange(
    SOLANA_MAINNET_NETWORK_ID,
    # Pass block32 transaction32 position schema id explicitly so BlockRange receives a
    # reviewable solana mainnet network id and block32 transaction32 position schema id
    # input in module.
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    100,
    103,
)


def test_snapshot_candidate_failures_never_publish_a_root(tmp_path: Path) -> None:
    # Execute the test snapshot candidate failures never publish a root workflow in
    # explicit, reviewable steps.
    cases = (
        (
            tuple(
                event
                for event in _events()
                # Register event through isinstance so the cases table remains scannable.
                if not isinstance(event, BlockEvent) or event.envelope.position.block_ordinal != 102
            ),
            SnapshotValidationErrorCode.SETTLEMENT_TAIL_INSUFFICIENT,
        ),
        (
            # Register event and isinstance through tuple so the cases table remains
            # scannable.
            tuple(
                replace(
                    event,
                    envelope=replace(
                        event.envelope,
                        # Register content digest and f through ContentDigest so the cases
                        # table remains scannable.
                        transaction_group_id=ContentDigest("f" * 64),
                    ),
                )
                if isinstance(event, VenueTradeEvent)
                else event
                # Register events through _events so the cases table remains scannable.
                for event in _events()
            ),
            SnapshotValidationErrorCode.TRANSACTION_GROUP_INVALID,
        ),
        (
            # Register event and isinstance through tuple so the cases table remains
            # scannable.
            tuple(
                replace(event, venue_id=VenueId("unknown-curve"))
                if isinstance(event, VenueTradeEvent)
                else event
                for event in _events()
                # Complete tuple only after its unknown-curve and isinstance inputs are
                # visible in test snapshot candidate failures never publish a root.
            ),
            SnapshotValidationErrorCode.PROTOCOL_STATE_INVALID,
        ),
    )
    for index, (events, expected_reason) in enumerate(cases):
        # Process enumerate(cases) inside the bounded test snapshot candidate failures
        # never publish a root loop.
        artifacts = LocalArtifactRepository(tmp_path / f"var-{index}")
        spec = _dataset_spec(_publish_source_inspection(artifacts))
        with pytest.raises(SnapshotValidationError) as caught:
            _publish_snapshot(artifacts, spec, events=events)
        assert caught.value.reason is expected_reason
        # Assemble snapshots once so the test snapshot candidate failures never publish a
        # root workflow shares one value.
        snapshots = artifacts.data_root / "snapshots"
        assert not snapshots.exists() or not tuple(snapshots.iterdir())


def test_sniping_resolver_rejects_sell_delay_above_prepared_maximum(
    tmp_path: Path,
) -> None:
    # Execute the test sniping resolver rejects sell delay above prepared maximum workflow
    # in explicit, reviewable steps.
    artifacts = LocalArtifactRepository(tmp_path / "var")
    prepared = _publish_snapshot(
        artifacts,
        _dataset_spec(_publish_source_inspection(artifacts)),
    )
    # Assemble resolver once so the test sniping resolver rejects sell delay above
    # prepared maximum workflow shares one value.
    resolver = ReferenceRunSpecResolver(
        artifacts,
        _RUNTIME_LOCK_ID,
        parquet_memory_limit_mb=256,
        threads=1,
        # Complete ReferenceRunSpecResolver only after its artifacts and runtime lock id
        # inputs are visible in test sniping resolver rejects sell delay above prepared
        # maximum.
    )
    draft = replace(
        _draft(prepared.dataset_revision_id, prepared.snapshot_id, None),
        sell_delay_transactions=2,
    )
    # Acquire raises, pumpfun sniping run resolution error and pytest at an explicit test
    # sniping resolver rejects sell delay above prepared maximum context boundary so
    # cleanup remains scoped.
    with pytest.raises(PumpfunSnipingRunResolutionError, match="prepared settlement"):
        resolver.resolve(draft)


@pytest.mark.parametrize(
    "backend_order",
    (
        # Open the backend order and reference pumpfun sniping payload explicitly for
        # parametrize within test sniping resolver run publication and verified queries
        # are backend equivalent.
        (RunBackend.REFERENCE_PUMPFUN_SNIPING, RunBackend.NUMPY_MMAP_PUMPFUN_SNIPING),
        (RunBackend.NUMPY_MMAP_PUMPFUN_SNIPING, RunBackend.REFERENCE_PUMPFUN_SNIPING),
    ),
)
def test_sniping_resolver_run_publication_and_verified_queries_are_backend_equivalent(
    # Keep the tmp path input explicit in the test sniping resolver run publication and
    # verified queries are backend equivalent contract.
    tmp_path: Path,
    backend_order: tuple[RunBackend, RunBackend],
) -> None:
    # Execute the test sniping resolver run publication and verified queries are backend
    # equivalent workflow in explicit, reviewable steps.
    artifacts = LocalArtifactRepository(tmp_path / "var")
    source_inspection_id = _publish_source_inspection(artifacts)
    prepared = _publish_snapshot(artifacts, _dataset_spec(source_inspection_id))
    snapshot_id = prepared.snapshot_id
    replay = LocalNumpyReplayPackCompiler(
        # Pass artifacts explicitly so compile receives a reviewable snapshot id and
        # compiler version input in test sniping resolver run publication and verified
        # queries are backend equivalent.
        artifacts,
        lambda requested: _open_canonical_source(artifacts, requested, snapshot_id),
        runtime_lock_id=_RUNTIME_LOCK_ID,
    ).compile(snapshot_id, COMPILER_VERSION)
    resolver = ReferenceRunSpecResolver(
        # Pass artifacts explicitly so ReferenceRunSpecResolver receives a reviewable
        # artifacts and runtime lock id input in test sniping resolver run publication and
        # verified queries are backend equivalent.
        artifacts,
        _RUNTIME_LOCK_ID,
        parquet_memory_limit_mb=256,
        threads=1,
    )
    # Assemble parquet spec once so the test sniping resolver run publication and verified
    # queries are backend equivalent workflow shares one value.
    parquet_spec = resolver.resolve(_draft(prepared.dataset_revision_id, snapshot_id, None))
    replay_draft = _draft(
        prepared.dataset_revision_id,
        snapshot_id,
        replay.replay_pack_id,
        # Complete _draft only after its dataset revision id and replay pack id inputs are
        # visible in test sniping resolver run publication and verified queries are backend
        # equivalent.
    )
    replay_spec = resolver.resolve(replay_draft)
    assert parquet_spec.logical_run_id == replay_spec.logical_run_id

    output_store = LocalParquetRunOutputStore(artifacts, tmp_path / "run-work")
    run_backtest = RunBacktest(
        # Keep the artifacts LocalReplaySourceFactory step visible while building run
        # backtest.
        LocalReplaySourceFactory(artifacts, parquet_memory_limit_mb=256),
        ReferenceRuntimeComponentsResolver(_RUNTIME_LOCK_ID),
        ReferenceBacktestEngine(),
        output_store,
        delivery_schedules=LocalDeliveryScheduleSourceFactory(artifacts),
        # Keep the runtime lock id PumpfunSnipingRuntimeComponentsResolver step visible
        # while building run backtest.
        sniping_components=PumpfunSnipingRuntimeComponentsResolver(_RUNTIME_LOCK_ID),
        sniping_engine=SnipingReferenceEngine(),
        additional_sniping_engines={
            NUMPY_MMAP_PUMPFUN_SNIPING_BACKEND: NumpyMmapPumpfunSnipingEngine(
                strategy_type=PumpfunSnipingStrategy,
                # Pass protocol type explicitly so NumpyMmapPumpfunSnipingEngine receives
                # a reviewable pumpfun sniping strategy and pumpfun sniping protocol
                # runtime input in test sniping resolver run publication and verified
                # queries are backend equivalent.
                protocol_type=PumpfunSnipingProtocolRuntime,
                network_cost_type=SolanaSnipingCostModel,
            )
        },
        clock=_clock(),
        # Complete RunBacktest only after its local replay source factory and reference
        # runtime components resolver inputs are visible in test sniping resolver run
        # publication and verified queries are backend equivalent.
    )

    parquet_reference = run_backtest.execute(
        RunBacktestRequest(
            parquet_spec,
            ContentDigest("7" * 64),
            # Keep the reference pumpfun sniping _physical_settings step visible while
            # building parquet reference.
            _physical_settings(RunBackend.REFERENCE_PUMPFUN_SNIPING, readahead=1),
        )
    )
    dynamic_results = {
        backend: run_backtest.execute(
            # Keep the replay spec RunBacktestRequest step visible while building dynamic
            # results.
            RunBacktestRequest(
                replay_spec,
                ContentDigest("7" * 64),
                _physical_settings(
                    backend,
                    # Pass readahead explicitly so _physical_settings receives a
                    # reviewable reference pumpfun sniping and backend input in test
                    # sniping resolver run publication and verified queries are backend
                    # equivalent.
                    readahead=(1 if backend is RunBackend.REFERENCE_PUMPFUN_SNIPING else 2),
                ),
            )
        )
        for backend in backend_order
        # Complete the dynamic results group only after its semantic components are visible.
    }
    compiled_schedule = _compile_delivery_schedule(artifacts, replay_spec)
    materialized_spec = resolver.resolve(
        replace(
            replay_draft,
            # Pass delivery schedule id explicitly so replace receives a reviewable
            # delivery schedule id and replay draft input in test sniping resolver run
            # publication and verified queries are backend equivalent.
            delivery_schedule_id=compiled_schedule.delivery_schedule_id,
        )
    )
    materialized_results = {
        backend: run_backtest.execute(
            # Keep the materialized spec RunBacktestRequest step visible while building
            # materialized results.
            RunBacktestRequest(
                materialized_spec,
                ContentDigest("8" * 64),
                _physical_settings(
                    backend,
                    # Pass readahead explicitly so _physical_settings receives a
                    # reviewable reference pumpfun sniping and backend input in test
                    # sniping resolver run publication and verified queries are backend
                    # equivalent.
                    readahead=(1 if backend is RunBackend.REFERENCE_PUMPFUN_SNIPING else 2),
                ),
            )
        )
        for backend in backend_order
        # Complete the materialized results group only after its semantic components are
        # visible.
    }
    all_results = (
        parquet_reference,
        dynamic_results[RunBackend.REFERENCE_PUMPFUN_SNIPING],
        dynamic_results[RunBackend.NUMPY_MMAP_PUMPFUN_SNIPING],
        # Keep the materialized results component named inside the all results contract.
        materialized_results[RunBackend.REFERENCE_PUMPFUN_SNIPING],
        materialized_results[RunBackend.NUMPY_MMAP_PUMPFUN_SNIPING],
    )

    assert materialized_spec.logical_run_id == replay_spec.logical_run_id
    assert {item.logical_run_id for item in all_results} == {replay_spec.logical_run_id}
    # Verify the all results, execution attempt id and item relationship before this
    # scenario is accepted.
    assert len({item.execution_attempt_id for item in all_results}) == len(all_results)
    assert len({item.canonical_result_hash for item in all_results}) == 1

    query = QueryRunResults(LocalParquetRunResultReaderFactory(artifacts))
    summaries = tuple(query.summary(item.artifact.artifact_id) for item in all_results)
    assert len({item.canonical_result_hash for item in summaries}) == 1
    # Verify the roundtrip digest, item and summaries relationship before this scenario is
    # accepted.
    assert len({item.roundtrip_digest for item in summaries}) == 1
    assert len({item.final_balances_digest for item in summaries}) == 1
    assert {item.target_count for item in summaries} == {1}
    assert {item.closed_position_count for item in summaries} == {1}
    assert {item.roundtrip_count for item in summaries} == {1}

    # Traverse parquet explicitly so each test sniping resolver run publication and
    # verified queries are backend equivalent iteration remains traceable.
    for relative_name in ("roundtrips.parquet", "final_balances.parquet"):
        # Process parquet inside the bounded test sniping resolver run publication and
        # verified queries are backend equivalent loop.
        exact_payloads = set()
        for result in all_results:
            # Process all_results inside the bounded test sniping resolver run publication
            # and verified queries are backend equivalent loop.
            with (
                artifacts.open_committed(result.artifact.artifact_id) as handle,
                handle.open_binary(relative_name) as stream,
            ):
                exact_payloads.add(stream.read())
        # Verify len(exact_payloads) == 1 before this scenario is accepted.
        assert len(exact_payloads) == 1

    materialized_artifacts = {item.artifact.artifact_id for item in materialized_results.values()}
    for result in all_results:
        # Process all_results inside the bounded test sniping resolver run publication and
        # verified queries are backend equivalent loop.
        with (
            artifacts.open_committed(result.artifact.artifact_id) as handle,
            handle.open_binary("manifest.json") as stream,
        ):
            manifest = json.load(stream)
        # Verify the manifest and artifact schema relationship before this scenario is
        # accepted.
        assert manifest["artifact_schema"] == "successful-run/v3"
        has_schedule = result.artifact.artifact_id in materialized_artifacts
        assert (
            compiled_schedule.delivery_schedule_id.hex in manifest["input_artifact_ids"]
        ) is has_schedule
        # Assemble page once so the test sniping resolver run publication and verified
        # queries are backend equivalent workflow shares one value.
        page = query.roundtrips(result.artifact.artifact_id, limit=1)
        assert page.next_cursor is None
        assert len(page.items) == 1
        (record,) = page.items
        assert record.status is RoundTripStatus.CLOSED
        # Verify the buy, sell and record relationship before this scenario is accepted.
        assert record.buy is not None and record.sell is not None
        assert record.buy.landing_position.transaction_index == 500
        assert record.sell.decision_position.block_ordinal == 102
        assert record.sell.decision_position.transaction_index == 0
        assert record.sell.landing_position.transaction_index == 1

    # Assemble mismatched spec once so the test sniping resolver run publication and
    # verified queries are backend equivalent workflow shares one value.
    mismatched_spec = _copy_spec_with_root_seed(materialized_spec, root_seed=8)
    output_guard = _NeverStartOutputStore()
    with pytest.raises(RunPreflightError, match="failed exact verification"):
        # Keep raises, run preflight error and pytest active only for the bounded test
        # sniping resolver run publication and verified queries are backend equivalent
        # operation.
        RunBacktest(
            LocalReplaySourceFactory(artifacts, parquet_memory_limit_mb=256),
            ReferenceRuntimeComponentsResolver(_RUNTIME_LOCK_ID),
            ReferenceBacktestEngine(),
            output_guard,
            # Pass delivery schedules explicitly to execute for 9 and reference pumpfun
            # sniping.
            delivery_schedules=LocalDeliveryScheduleSourceFactory(artifacts),
            sniping_components=PumpfunSnipingRuntimeComponentsResolver(_RUNTIME_LOCK_ID),
            sniping_engine=SnipingReferenceEngine(),
        ).execute(
            RunBacktestRequest(
                # Pass mismatched spec explicitly so RunBacktestRequest receives a
                # reviewable 9 and reference pumpfun sniping input in test sniping
                # resolver run publication and verified queries are backend equivalent.
                mismatched_spec,
                ContentDigest("9" * 64),
                _physical_settings(RunBackend.REFERENCE_PUMPFUN_SNIPING, readahead=1),
            )
        )
    # Verify not output_guard.started before this scenario is accepted.
    assert not output_guard.started


def test_virtual_settlement_resolves_executes_and_publishes_synthetic_funding(
    tmp_path: Path,
) -> None:
    """Prove the identity-bearing virtual mode through the verified result reader."""

    artifacts = LocalArtifactRepository(tmp_path / "var")
    source_inspection_id = _publish_source_inspection(artifacts)
    prepared = _publish_snapshot(
        artifacts,
        _dataset_spec(source_inspection_id),
        # Zero observed SOL makes the successful sell wholly synthetic.
        events=_virtual_shortfall_events(),
    )

    resolver = ReferenceRunSpecResolver(
        artifacts,
        _RUNTIME_LOCK_ID,
        # Keep the integration run inside the deterministic single-thread profile.
        parquet_memory_limit_mb=256,
        threads=1,
    )
    strict_spec = resolver.resolve(_draft(prepared.dataset_revision_id, prepared.snapshot_id, None))
    # Resolve the alternate mode from the same exact source artifacts.
    virtual_spec = resolver.resolve(
        _draft(
            prepared.dataset_revision_id,
            prepared.snapshot_id,
            None,
            # The draft is the sole editable execution-mode boundary.
            execution_mode=ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT,
        )
    )

    # A mode switch changes run semantics, never the verified data closure.
    assert virtual_spec.dataset_revision_id == strict_spec.dataset_revision_id
    assert virtual_spec.snapshot_id == strict_spec.snapshot_id
    assert virtual_spec.logical_run_id != strict_spec.logical_run_id

    output_store = LocalParquetRunOutputStore(artifacts, tmp_path / "run-work")
    run_backtest = RunBacktest(
        LocalReplaySourceFactory(artifacts, parquet_memory_limit_mb=256),
        ReferenceRuntimeComponentsResolver(_RUNTIME_LOCK_ID),
        ReferenceBacktestEngine(),
        # Publication is part of the acceptance path, not an in-memory shortcut.
        output_store,
        # Resolve virtual semantics through the same production composition boundary.
        sniping_components=PumpfunSnipingRuntimeComponentsResolver(_RUNTIME_LOCK_ID),
        sniping_engine=SnipingReferenceEngine(),
        clock=_clock(),
    )
    result = run_backtest.execute(
        RunBacktestRequest(
            virtual_spec,
            ContentDigest("e" * 64),
            # Physical provenance remains independent from the semantic mode.
            _physical_settings(RunBackend.REFERENCE_PUMPFUN_SNIPING, readahead=1),
        )
    )

    query = QueryRunResults(LocalParquetRunResultReaderFactory(artifacts))
    summary = query.summary(result.artifact.artifact_id)
    assert summary.execution_mode is ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT
    # Resolver-selected policy must survive publication and verified projection.
    assert summary.settlement_policy_id == (
        "virtual-reserve-output-with-explicit-synthetic-shortfall-v1"
    )
    # The bounded summary must conserve the fully synthetic successful sell.
    assert summary.filled_sell_count == 1
    assert summary.synthetic_liquidity_used_sell_count == 1
    assert summary.venue_funded_sell_atomic == 0
    # Gross proceeds must equal the positive explicit synthetic source.
    assert summary.synthetic_funded_sell_atomic is not None
    assert summary.synthetic_funded_sell_atomic > 0
    assert summary.gross_sell_settlement_atomic == summary.synthetic_funded_sell_atomic

    page = query.roundtrips(result.artifact.artifact_id, limit=1)
    assert page.next_cursor is None
    assert len(page.items) == 1
    (record,) = page.items
    # The row schema independently retains the mode and successful lifecycle.
    assert record.status is RoundTripStatus.CLOSED
    assert record.execution_mode is ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT

    landing = record.sell_landing_liquidity
    assert landing is not None
    assert landing.observed_available_output_atomic == 0
    assert landing.synthetic_shortfall_atomic == landing.required_output_atomic
    # Used landing funding is separate from potential quote evidence and reconciles.
    assert record.settled_venue_funded_atomic == 0
    assert record.settled_synthetic_funded_atomic == landing.required_output_atomic


def _physical_settings(backend: RunBackend, *, readahead: int) -> RunPhysicalSettings:
    # Execute the physical settings workflow in explicit, reviewable steps.
    return RunPhysicalSettings(
        backend=backend,
        reader_batch_rows=2,
        reader_readahead=readahead,
        output_buffer_rows=2,
        # Pass threads explicitly so RunPhysicalSettings receives a reviewable backend and
        # readahead input in physical settings.
        threads=1,
    )


def _clock() -> Callable[[], datetime]:
    # Execute the clock workflow in explicit, reviewable steps.
    current = datetime(2026, 1, 1, tzinfo=UTC)

    def advance() -> datetime:
        # Execute the advance workflow in explicit, reviewable steps.
        nonlocal current
        value = current
        current += timedelta(seconds=1)
        return value

    return advance


# Define draft as one focused operation with an explicit boundary.
def _draft(
    dataset_revision_id: DatasetRevisionId,
    snapshot_id: SnapshotId,
    replay_pack_id: ReplayPackId | None,
    # Defaulting here preserves the pre-existing strict fixture and golden path.
    *,
    execution_mode: ExecutionMode = ExecutionMode.EXOGENOUS_REPLAY,
) -> PumpfunSnipingRunDraft:
    # Execute the draft workflow in explicit, reviewable steps.
    return PumpfunSnipingRunDraft(
        dataset_revision_id=dataset_revision_id,
        snapshot_id=snapshot_id,
        replay_pack_id=replay_pack_id,
        initial_sol_balance_lamports=2_000_000_000,
        # Pass gross buy budget lamports explicitly so PumpfunSnipingRunDraft receives a
        # reviewable fresh-sniping-e2e-v1 and pump-token-account-v1 input in draft.
        gross_buy_budget_lamports=1_000_000_000,
        buy_slippage_bps=0,
        sell_slippage_bps=0,
        execution_mode=execution_mode,
        sell_delay_transactions=1,
        wallet_account_profile=WalletAccountProfileDraft(
            # Pass profile id explicitly so WalletAccountProfileDraft receives a
            # reviewable fresh-sniping-e2e-v1 and pump-token-account-v1 input in draft.
            profile_id="fresh-sniping-e2e-v1",
            initial_uva_state=WalletAccountMode.FRESH,
            effective_from_unix_s=1_700_000_000,
            effective_until_unix_s=1_800_000_000,
            account_costs=(
                SolanaAccountDepositCostDraft(PUMPFUN_UVA_SCHEMA_ID, 1_844_400),
                SolanaAccountDepositCostDraft(PUMPFUN_LEGACY_ATA_SCHEMA_ID, 2_039_280),
                SolanaAccountDepositCostDraft(PUMPFUN_TOKEN_2022_ATA_SCHEMA_ID, 2_074_080),
            ),
        ),
        # Include pump fee profile in the completed draft result.
        pump_fee_profile=PumpFeeProfileDraft(
            profile_id="pump-static-95-30-sniping-e2e-v1",
            program_version=PUMP_STATIC_PROGRAM_CONTRACT_V1,
            buy_formula_version=PUMP_BUY_EXACT_GROSS_SOL_FORMULA_V1,
            sell_formula_version=PUMP_SELL_EXACT_TOKEN_IN_FORMULA_V1,
            # Pass effective from unix s explicitly so PumpFeeProfileDraft receives a
            # reviewable pump-static-95-30-sniping-e2e-v1 and pump static program contract
            # v1 input in draft.
            effective_from_unix_s=1_700_000_000,
            effective_until_unix_s=1_800_000_000,
            protocol_fee_bps=95,
            creator_fee_bps=30,
        ),
        # Include buy solana fee profile in the completed draft result.
        buy_solana_fee_profile=_fee("buy-sniping-e2e-v1", 10),
        sell_solana_fee_profile=_fee("sell-sniping-e2e-v1", 20),
        root_seed=7,
    )


def _fee(profile_id: str, priority_price: int) -> SolanaFeeProfileDraft:
    # Execute the fee workflow in explicit, reviewable steps.
    return SolanaFeeProfileDraft(
        profile_id=profile_id,
        formula_version=SOLANA_LEGACY_V0_FEE_FORMULA_V1,
        transaction_format="V0",
        effective_from_unix_s=1_700_000_000,
        # Pass effective until unix s explicitly so SolanaFeeProfileDraft receives a
        # reviewable v0 and profile id input in fee.
        effective_until_unix_s=1_800_000_000,
        charged_signature_count=1,
        lamports_per_signature=5_000,
        compute_unit_limit=100_000,
        micro_lamports_per_compute_unit=priority_price,
        # Complete SolanaFeeProfileDraft only after its v0 and profile id inputs are visible
        # in fee.
    )


def _publish_snapshot(
    artifacts: LocalArtifactRepository,
    dataset_spec: DatasetSpec,
    *,
    # Keep the events input explicit in the publish snapshot contract.
    events: tuple[CanonicalEvent, ...] | None = None,
) -> PreparedSnapshot:
    # Execute the publish snapshot workflow in explicit, reviewable steps.
    canonical_events = _events() if events is None else events
    plan = DatasetPlan(
        spec=dataset_spec,
        budget=BudgetReport(
            status=BudgetStatus.PASS,
            # Keep the canonical events len step visible while building plan.
            estimated_source_rows=len(canonical_events),
            estimated_source_bytes=4_096,
            requested_days=1,
            requested_blocks=3,
            planned_shards=len(dataset_spec.shards),
            # Pass expected local parquet bytes explicitly so BudgetReport receives a
            # reviewable pass and shards input in publish snapshot.
            expected_local_parquet_bytes=4_096,
            temporary_reserve_bytes=0,
            current_free_disk_bytes=1_000_000,
            disk_low_watermark_bytes=0,
            max_remote_bytes=1_000_000,
            # Pass max local bytes explicitly so BudgetReport receives a reviewable pass
            # and shards input in publish snapshot.
            max_local_bytes=1_000_000,
            max_days=1,
            max_total_blocks=3,
            max_total_shards=len(dataset_spec.shards),
            max_shard_blocks=3,
            # Pass issues explicitly so BudgetReport receives a reviewable pass and shards
            # input in publish snapshot.
            issues=(),
        ),
        query_limits=QueryLimits(30, 256 * 1024**2, 10_000),
    )
    store = LocalArrowCanonicalStore(
        # Pass artifacts explicitly so LocalArrowCanonicalStore receives a reviewable
        # artifacts input in publish snapshot.
        artifacts,
        memory_limit_mb=256,
        threads=1,
        projection_batch_rows=2,
    )
    # Assemble capabilities once so the publish snapshot workflow shares one value.
    capabilities = {item.capability_id: item for item in dataset_spec.capabilities}
    event_kinds = {
        _BLOCK_CAPABILITY: EventKind.BLOCK,
        _LAUNCH_CAPABILITY: EventKind.TOKEN_LAUNCH,
        _TRADE_CAPABILITY: EventKind.VENUE_TRADE,
        # Keep the lifecycle capability component named inside the event kinds contract.
        _LIFECYCLE_CAPABILITY: EventKind.VENUE_LIFECYCLE,
    }
    distributions = tuple(
        store.publish_distribution(
            plan=plan,
            # Pass shard explicitly so publish_distribution receives a reviewable 064x and
            # capability id input in publish snapshot.
            shard=shard,
            capability=capabilities[shard.capability_id],
            event_kind=event_kinds[shard.capability_id],
            projector_bundle_id=_PROJECTOR_BUNDLE_ID,
            batches=(
                # Keep the projected event batch and content digest ProjectedEventBatch
                # step visible while building distributions.
                ProjectedEventBatch(
                    tuple(
                        event
                        for event in canonical_events
                        if event.envelope.capability_id == shard.capability_id
                        # Complete tuple only after its capability id and envelope inputs are
                        # visible in publish snapshot.
                    ),
                    ContentDigest(f"{shard.ordinal + 1:064x}"),
                ),
            ),
            extracted_at=datetime(2026, 1, 1, tzinfo=UTC),
            # Complete publish_distribution only after its 064x and capability id inputs are
            # visible in publish snapshot.
        )
        for shard in dataset_spec.shards
    )
    return store.publish_snapshot(
        plan=plan,
        # Pass projector bundle id explicitly so publish_snapshot receives a reviewable
        # datetime and pumpfun snapshot validator input in publish snapshot.
        projector_bundle_id=_PROJECTOR_BUNDLE_ID,
        distributions=distributions,
        extracted_at=datetime(2026, 1, 1, tzinfo=UTC),
        validator=PumpfunSnapshotValidator(),
    )


# Define open canonical source as one focused operation with an explicit boundary.
def _open_canonical_source(
    artifacts: LocalArtifactRepository,
    requested: SnapshotId,
    expected: SnapshotId,
) -> CanonicalParquetReplaySource:
    # Execute the open canonical source workflow in explicit, reviewable steps.
    if requested != expected:
        raise AssertionError("compiler requested another snapshot")
    return CanonicalParquetReplaySource(
        artifacts,
        requested,
        # Pass duckdb memory limit mb explicitly so CanonicalParquetReplaySource receives
        # a reviewable artifacts and requested input in open canonical source.
        duckdb_memory_limit_mb=256,
        threads=1,
        expected_projector_bundle_id=None,
    )


def _compile_delivery_schedule(
    # Keep the artifacts input explicit in the compile delivery schedule contract.
    artifacts: LocalArtifactRepository,
    spec: ResolvedRunSpec,
) -> CompiledDeliverySchedule:
    # Execute the compile delivery schedule workflow in explicit, reviewable steps.
    replay_pack_id = spec.replay_input.replay_pack_id
    replay_layout_schema_id = spec.replay_input.replay_layout_schema_id
    if replay_pack_id is None or replay_layout_schema_id is None:
        raise AssertionError("schedule fixture requires an exact ReplayPack")
    return CompileDeliverySchedule(
        # Include local numpy delivery schedule compiler in the completed compile delivery
        # schedule result.
        LocalNumpyDeliveryScheduleCompiler(
            artifacts,
            runtime_lock_id=_RUNTIME_LOCK_ID,
        )
    ).execute(
        # Include compile delivery schedule request in the completed compile delivery
        # schedule result.
        CompileDeliveryScheduleRequest(
            replay_pack_id=replay_pack_id,
            replay_semantics_id=spec.replay_semantics_id,
            replay_layout_schema_id=replay_layout_schema_id,
            components=tuple(
                # Pass component explicitly so tuple receives a reviewable clock and
                # engine input in compile delivery schedule.
                component
                for component in spec.components
                if component.role in {"clock", "engine", "latency", "scheduler"}
            ),
            rng_algorithm=RNG_ALGORITHM,
            # Pass root seed explicitly so CompileDeliveryScheduleRequest receives a
            # reviewable clock and engine input in compile delivery schedule.
            root_seed=spec.root_seed,
            compiler_version=DELIVERY_COMPILER_VERSION,
        )
    )


def _copy_spec_with_root_seed(spec: ResolvedRunSpec, *, root_seed: int) -> ResolvedRunSpec:
    # Execute the copy spec with root seed workflow in explicit, reviewable steps.
    return ResolvedRunSpec.create(
        network_id=spec.network_id,
        position_schema_id=spec.position_schema_id,
        dataset_revision_id=spec.dataset_revision_id,
        logical_content_hash=spec.logical_content_hash,
        # Pass snapshot id explicitly so create receives a reviewable network id and
        # position schema id input in copy spec with root seed.
        snapshot_id=spec.snapshot_id,
        replay_semantics_id=spec.replay_semantics_id,
        replay_input=spec.replay_input,
        components=spec.components,
        runtime_lock_id=spec.runtime_lock_id,
        # Pass initial portfolio explicitly so create receives a reviewable network id and
        # position schema id input in copy spec with root seed.
        initial_portfolio=spec.initial_portfolio,
        root_seed=root_seed,
        replay_contract=spec.replay_contract,
        feature_set_ids=spec.feature_set_ids,
        model_schedule_id=spec.model_schedule_id,
        # Pass prediction set ids explicitly so create receives a reviewable network id
        # and position schema id input in copy spec with root seed.
        prediction_set_ids=spec.prediction_set_ids,
        delivery_schedule_id=spec.delivery_schedule_id,
    )


# Keep the never start output store contract and validation rules together.
@dataclass(slots=True)
class _NeverStartOutputStore:
    started: bool = False

    def start(
        self,
        # Close the start signature after its explicit inputs.
        *,
        spec: ResolvedRunSpec,
        execution_attempt_id: ExecutionAttemptId,
        physical_settings: RunPhysicalSettings,
    ) -> RunOutputSession:
        # Execute the never start output store start workflow in explicit, reviewable
        # steps.
        del spec, execution_attempt_id, physical_settings
        self.started = True
        raise AssertionError("output staging must not start after schedule preflight rejection")


def _publish_source_inspection(artifacts: LocalArtifactRepository) -> ArtifactId:
    # Execute the publish source inspection workflow in explicit, reviewable steps.
    payload = canonical_json_bytes({"fixture": "hermetic-sniping-source-inspection-v1"})
    writer = artifacts.stage(
        ArtifactDraft(
            ArtifactKind.SOURCE_INSPECTION,
            ContentDigest("a" * 64),
            # Complete ArtifactDraft only after its a and source inspection inputs are visible
            # in publish source inspection.
        )
    )
    return writer.commit(payload, identity_manifest_bytes=payload).artifact_id


def _dataset_spec(source_inspection_artifact_id: ArtifactId) -> DatasetSpec:
    # Execute the dataset spec workflow in explicit, reviewable steps.
    fidelity = SourceFidelity(
        identity=IdentityFidelity.EXACT,
        ordering=OrderingFidelity.INSTRUCTION_EXACT,
        state=StateFidelity.BEFORE_AFTER,
        fees=FeesFidelity.COMPONENTS,
        # Pass chain finality explicitly so SourceFidelity receives a reviewable exact and
        # instruction exact input in dataset spec.
        chain_finality=ChainFinality.FINALIZED,
        completeness=IngestionCompleteness.COMPLETE_TO_WATERMARK,
        consistency=SourceConsistency.SNAPSHOT_CONSISTENT,
    )
    proofs = CapabilityProofs(**dict.fromkeys(CAPABILITY_PROOF_FIELDS, EvidenceStatus.PROVEN))
    # Assemble declarations once so the dataset spec workflow shares one value.
    declarations = (
        (
            _BLOCK_CAPABILITY,
            "solana",
            CapabilityStream.BLOCK_CLOCK,
            # Keep the block ordinal component named inside the declarations contract.
            ("block_ordinal", "block_time", "transaction_count", "block_hash"),
        ),
        (
            _LAUNCH_CAPABILITY,
            PUMPFUN_PROTOCOL_NAME,
            # Keep the capability stream component named inside the declarations contract.
            CapabilityStream.TOKEN_LAUNCH,
            (
                "block_ordinal",
                "transaction_index",
                "event_index",
                # Keep the signature component named inside the declarations contract.
                "signature",
                "transaction_succeeded",
                "mint",
                "creator",
                "creation_user",
                # Keep the venue component named inside the declarations contract.
                "venue",
                "quote_asset",
                "virtual_token_reserves_atomic",
                "virtual_sol_reserves_lamports",
                "real_token_reserves_atomic",
                # Keep the real sol reserves lamports component named inside the
                # declarations contract.
                "real_sol_reserves_lamports",
                "token_total_supply_atomic",
                "lifecycle",
                "mode",
            ),
            # Complete the declarations group only after its semantic components are visible.
        ),
        (
            _TRADE_CAPABILITY,
            PUMPFUN_PROTOCOL_NAME,
            CapabilityStream.PUMP_CURVE_TRADE,
            # Complete the declarations group only after its semantic components are
            # visible.
            (
                "block_ordinal",
                "transaction_index",
                "event_index",
                "signature",
                # Keep the mint component named inside the declarations contract.
                "mint",
                "venue",
                "quote_asset",
                "side",
                "base_amount_atomic",
                # Keep the quote amount atomic component named inside the declarations
                # contract.
                "quote_amount_atomic",
                "virtual_token_reserves_atomic",
                "virtual_sol_reserves_lamports",
                "real_token_reserves_atomic",
                "real_sol_reserves_lamports",
                # Keep the token total supply atomic component named inside the
                # declarations contract.
                "token_total_supply_atomic",
                "protocol_fee_atomic",
                "creator_fee_atomic",
                "mode",
                "lifecycle",
                # Complete the declarations group only after its semantic components are
                # visible.
            ),
        ),
        (
            _LIFECYCLE_CAPABILITY,
            PUMPFUN_PROTOCOL_NAME,
            # Keep the capability stream component named inside the declarations contract.
            CapabilityStream.PUMP_CURVE_LIFECYCLE,
            (
                "block_ordinal",
                "transaction_index",
                "event_index",
                # Keep the signature component named inside the declarations contract.
                "signature",
                "mint",
                "venue",
                "lifecycle_kind",
                "virtual_token_reserves_atomic",
                # Keep the virtual sol reserves lamports component named inside the
                # declarations contract.
                "virtual_sol_reserves_lamports",
                "real_token_reserves_atomic",
                "real_sol_reserves_lamports",
                "token_total_supply_atomic",
                "lifecycle",
                # Keep the mode component named inside the declarations contract.
                "mode",
            ),
        ),
    )
    capabilities = tuple(
        # Keep the planned capability and capability id PlannedCapability step visible
        # while building capabilities.
        PlannedCapability(
            capability_id=capability_id,
            protocol=protocol,
            protocol_version=(
                "block-clock-v1"
                # Pass stream explicitly so PlannedCapability receives a reviewable block-
                # clock-v1 and 1 input in dataset spec.
                if stream is CapabilityStream.BLOCK_CLOCK
                else PUMP_STATIC_PROGRAM_CONTRACT_V1
            ),
            schema_version="1",
            stream=stream,
            # Pass columns explicitly so PlannedCapability receives a reviewable block-
            # clock-v1 and 1 input in dataset spec.
            columns=columns,
            fidelity=fidelity,
            proofs=proofs,
            total_key=(),
            keyset_key_is_proven=False,
            # Pass utc pruning column explicitly so PlannedCapability receives a
            # reviewable block-clock-v1 and 1 input in dataset spec.
            utc_pruning_column=None,
            utc_pruning_is_proven=False,
        )
        for capability_id, protocol, stream, columns in declarations
    )
    # Assemble capability ranges once so the dataset spec workflow shares one value.
    range_by_capability = {
        item.capability_id: (
            _DECISION_RANGE if item.stream is CapabilityStream.TOKEN_LAUNCH else _EXTRACTION_RANGE
        )
        for item in capabilities
    }
    capability_ranges = tuple(
        CapabilityExtractionRange(item.capability_id, range_by_capability[item.capability_id])
        for item in capabilities
    )
    cut_evidence = tuple(
        CapabilityCutEvidence(
            # Pass capability id explicitly so CapabilityCutEvidence receives a reviewable
            # hermetic-sniping-e2e-v1 and capability id input in dataset spec.
            capability_id=item.capability_id,
            block_range=_EXTRACTION_RANGE,
            snapshot_cut_to_block=_EXTRACTION_RANGE.to_block_ordinal,
            chain_finality=ChainFinality.FINALIZED,
            ingestion_watermark_to_block=_EXTRACTION_RANGE.to_block_ordinal,
            # Pass completeness explicitly so CapabilityCutEvidence receives a reviewable
            # hermetic-sniping-e2e-v1 and capability id input in dataset spec.
            completeness=IngestionCompleteness.COMPLETE_TO_WATERMARK,
            consistency=SourceConsistency.SNAPSHOT_CONSISTENT,
            upstream_revision="hermetic-sniping-e2e-v1",
        )
        for item in capabilities
        # Complete tuple only after its hermetic-sniping-e2e-v1 and capability id inputs are
        # visible in dataset spec.
    )
    shards = tuple(
        DatasetShard(
            index,
            item.capability_id,
            range_by_capability[item.capability_id],
            item.columns,
        )
        for index, item in enumerate(capabilities)
    )
    source_evidence_binding = _source_evidence_binding(capabilities)
    # Assemble spec id once so the dataset spec workflow shares one value.
    spec_id = dataset_spec_identity_digest(
        spec_version=DATASET_SPEC_VERSION,
        source_id=_SOURCE_ID,
        source_inspection_artifact_id=source_inspection_artifact_id,
        source_schema_fingerprint=ContentDigest("e" * 64),
        # Keep the content digest and c ContentDigest step visible while building spec id.
        capability_mapping_digest=ContentDigest("c" * 64),
        query_template_digest=ContentDigest("b" * 64),
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        decision_range=_DECISION_RANGE,
        # Pass settlement tail explicitly so dataset_spec_identity_digest receives a
        # reviewable e and c input in dataset spec.
        settlement_tail=_SETTLEMENT_TAIL,
        warmup_blocks=0,
        evidence_contracts=(PUMPFUN_SNIPING_SOURCE_CONTRACT,),
        capabilities=capabilities,
        capability_ranges=capability_ranges,
        # Pass cut evidence explicitly so dataset_spec_identity_digest receives a
        # reviewable e and c input in dataset spec.
        cut_evidence=cut_evidence,
        shards=shards,
        settlement_requirement=pumpfun_sniping_settlement_requirement(
            maximum_sell_delay_transactions=1,
            maximum_tail_blocks=_SETTLEMENT_TAIL.span,
            # Complete pumpfun_sniping_settlement_requirement only after its span and
            # settlement tail inputs are visible in dataset spec.
        ),
        source_evidence_binding=source_evidence_binding,
    )
    return DatasetSpec(
        spec_version=DATASET_SPEC_VERSION,
        spec_id=spec_id,
        # Pass source id explicitly so DatasetSpec receives a reviewable e and c input in
        # dataset spec.
        source_id=_SOURCE_ID,
        source_inspection_artifact_id=source_inspection_artifact_id,
        source_schema_fingerprint=ContentDigest("e" * 64),
        capability_mapping_digest=ContentDigest("c" * 64),
        query_template_digest=ContentDigest("b" * 64),
        # Pass network id explicitly so DatasetSpec receives a reviewable e and c input in
        # dataset spec.
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        decision_range=_DECISION_RANGE,
        settlement_tail=_SETTLEMENT_TAIL,
        warmup_blocks=0,
        # Pass evidence contracts explicitly so DatasetSpec receives a reviewable e and c
        # input in dataset spec.
        evidence_contracts=(PUMPFUN_SNIPING_SOURCE_CONTRACT,),
        capabilities=capabilities,
        capability_ranges=capability_ranges,
        cut_evidence=cut_evidence,
        shards=shards,
        # Include settlement requirement in the completed dataset spec result.
        settlement_requirement=pumpfun_sniping_settlement_requirement(
            maximum_sell_delay_transactions=1,
            maximum_tail_blocks=_SETTLEMENT_TAIL.span,
        ),
        source_evidence_binding=source_evidence_binding,
    )


def _source_evidence_binding(
    capabilities: tuple[PlannedCapability, ...],
) -> PumpfunSnipingSourceEvidenceBinding:
    """Bind the hermetic fixture to a complete, secret-free v2 source receipt set."""

    empty_ordered_digest = ContentDigest("0" * 64)
    return PumpfunSnipingSourceEvidenceBinding(
        receipt_refs=tuple(
            sorted(
                (
                    SourceEvidenceReceiptRef(
                        item.capability_id,
                        ContentDigest(f"{index + 1:064x}"),
                    )
                    for index, item in enumerate(capabilities)
                ),
                key=lambda item: item.capability_id.value,
            )
        ),
        capability_mapping_digest=ContentDigest("c" * 64),
        query_template_digest=ContentDigest("b" * 64),
        projector_digest=ContentDigest("d" * 64),
        normalizer_digest=ContentDigest("a" * 64),
        launch_universe=LaunchUniverseEvidence(
            decision_range=_DECISION_RANGE,
            policy_id=PUMPFUN_SNIPING_UNIVERSE_POLICY_ID,
            classified_count=1,
            eligible_count=1,
            excluded_count=0,
            ordered_exclusion_digest=empty_ordered_digest,
        ),
        skipped_slot_sentinel=SkippedSlotSentinelEvidence(
            profile_id=SOLANA_SKIPPED_SLOT_SENTINEL_POLICY_ID,
            recognized_count=0,
            ordered_sentinel_digest=empty_ordered_digest,
        ),
        terminal_lifecycle_ordering=TerminalLifecycleOrderingEvidence(
            profile_id=PUMPFUN_TERMINAL_LIFECYCLE_ORDERING_POLICY_ID,
            derived_group_count=0,
            ordered_group_digest=empty_ordered_digest,
        ),
    )


# Define events as one focused operation with an explicit boundary.
def _events() -> tuple[CanonicalEvent, ...]:
    # Execute the events workflow in explicit, reviewable steps.
    initial = _curve_state()
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
        _block(100, 501, _BASE_TIME_S, 1),
        # Include token launch event in the completed events result.
        TokenLaunchEvent(
            envelope=_envelope(100, 0, 0, 2, 2, _LAUNCH_CAPABILITY),
            asset_id=AssetId("TOKEN"),
            developer_id=AccountId("developer"),
            creation_user_id=AccountId("payer"),
            # Include venue id in the completed events result.
            venue_id=VenueId("curve"),
            quote_asset_id=_SOL,
            protocol_payload_schema=PUMPFUN_LAUNCH_PAYLOAD_SCHEMA_ID,
            protocol_payload=encode_launch_payload(initial),
        ),
        # Include venue trade event in the completed events result.
        VenueTradeEvent(
            envelope=_envelope(100, 0, 1, 3, 2, _TRADE_CAPABILITY),
            venue_id=VenueId("curve"),
            sold_asset_id=_SOL,
            bought_asset_id=AssetId("TOKEN"),
            # Pass sold amount atomic explicitly so VenueTradeEvent receives a reviewable
            # curve and token input in events.
            sold_amount_atomic=1,
            bought_amount_atomic=1,
            fee_components=(),
            protocol_payload_schema=PUMPFUN_TRADE_PAYLOAD_SCHEMA_ID,
            protocol_payload=encode_trade_payload(bundled),
            # Complete VenueTradeEvent only after its curve and token inputs are visible in
            # events.
        ),
        _block(101, 0, _BASE_TIME_S + 1, 4),
        _block(102, 2, _BASE_TIME_S + 2, 5),
    )


def _virtual_shortfall_events() -> tuple[CanonicalEvent, ...]:
    """Return an active launch whose historical curve holds no real SOL."""

    launch_state = replace(_curve_state(), real_sol_reserves_lamports=0)
    return tuple(
        replace(event, protocol_payload=encode_launch_payload(launch_state))
        if isinstance(event, TokenLaunchEvent)
        else event
        # No observed trade is needed to establish this launch-time state.
        for event in _events()
        if not isinstance(event, VenueTradeEvent)
    )


def _curve_state() -> PumpCurveStateV1:
    # Execute the curve state workflow in explicit, reviewable steps.
    return PumpCurveStateV1(
        virtual_token_reserves_atomic=1_073_000_000_000_000,
        virtual_sol_reserves_lamports=30_000_000_000,
        real_token_reserves_atomic=793_100_000_000_000,
        real_sol_reserves_lamports=100_000_000_000,
        # Pass token total supply atomic explicitly so PumpCurveStateV1 receives a
        # reviewable active and normal input in curve state.
        token_total_supply_atomic=1_000_000_000_000_000,
        lifecycle=PumpCurveLifecycle.ACTIVE,
        mode=PumpMode.NORMAL,
    )


def _block(block: int, count: int, time_s: int, identity: int) -> BlockEvent:
    # Execute the block workflow in explicit, reviewable steps.
    return BlockEvent(
        envelope=_envelope(
            block,
            -1,
            0,
            # Pass identity explicitly so _envelope receives a reviewable solana and
            # block-clock-v1 input in block.
            identity,
            identity,
            _BLOCK_CAPABILITY,
            protocol="solana",
            protocol_version="block-clock-v1",
            # Complete _envelope only after its solana and block-clock-v1 inputs are visible
            # in block.
        ),
        block_time_ns=time_s * 1_000_000_000,
        tx_count=count,
        block_hash=f"block-{block}",
    )


# Define envelope as one focused operation with an explicit boundary.
def _envelope(
    block: int,
    transaction: int,
    event_index: int,
    identity: int,
    # Keep the group identity input explicit in the envelope contract.
    group_identity: int,
    capability_id: CapabilityId,
    *,
    protocol: str = PUMPFUN_PROTOCOL_NAME,
    protocol_version: str = PUMP_STATIC_PROGRAM_CONTRACT_V1,
    # Keep the event envelope input explicit in the envelope contract.
) -> EventEnvelope:
    # Execute the envelope workflow in explicit, reviewable steps.
    return EventEnvelope(
        position=ChainPosition(
            SOLANA_MAINNET_NETWORK_ID,
            BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            block,
            # Pass transaction explicitly so ChainPosition receives a reviewable solana
            # mainnet network id and block32 transaction32 position schema id input in
            # envelope.
            transaction,
            event_index,
        ),
        transaction_group_id=ContentDigest(f"{group_identity:064x}"),
        source_record_id=ContentDigest(f"{identity + 100:064x}"),
        # Include canonical event id in the completed envelope result.
        canonical_event_id=ContentDigest(f"{identity + 200:064x}"),
        stable_causal_id=ContentDigest(f"{identity + 300:064x}"),
        capability_id=capability_id,
        protocol=protocol,
        protocol_version=protocol_version,
        # Pass ordering fidelity explicitly so EventEnvelope receives a reviewable 064x
        # and instruction exact input in envelope.
        ordering_fidelity=OrderingFidelity.INSTRUCTION_EXACT,
    )
