"""Representative hermetic one-day release gate for Pump.fun sniping.

The fixture models a full Solana-shaped day as a compact block clock rather
than allocating one object per network transaction.  Both measured backends
open the same verified ReplayPack and execute the complete strategy, protocol,
network-cost, ledger, fill and result-hash path in an isolated spawn child.
"""

from __future__ import annotations

import gc
import json
import multiprocessing
import os

# Import resource at the visible module dependency boundary.
import resource
import statistics
import time
import traceback
from collections.abc import Iterator, Mapping

# Import dataclasses at the visible module dependency boundary.
from dataclasses import dataclass
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Final, Literal, cast

import pytest

# Import repository at the visible module dependency boundary.
from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.adapters.columnar.numpy import (
    LocalNumpyReplayPackCompiler,
    NumpyMmapPumpfunSnipingEngine,
    NumpyMmapReplaySource,
    # Close the numpy import after its required symbols are visible.
)
from backtest.adapters.columnar.numpy import layout as physical
from backtest.adapters.performance.metrics import (
    PeakPrivateRssSampler,
    peak_total_rss_bytes,
    # Close the metrics import after its required symbols are visible.
)
from backtest.application.dataset_plans import dataset_spec_document
from backtest.application.models import (
    CAPABILITY_PROOF_FIELDS,
    DATASET_SPEC_VERSION,
    # Include pumpfun sniping source contract so the models dependency remains explicit.
    PUMPFUN_SNIPING_SOURCE_CONTRACT,
    ArtifactDraft,
    ArtifactKind,
    CapabilityCutEvidence,
    CapabilityExtractionRange,
    # Include capability proofs so the models dependency remains explicit.
    CapabilityProofs,
    CapabilityStream,
    DatasetShard,
    DatasetSpec,
    EvidenceStatus,
    # Include planned capability so the models dependency remains explicit.
    PlannedCapability,
    dataset_spec_identity_digest,
)
from backtest.application.replay_packs import ReplaySemanticsManifest
from backtest.application.sniping_run_contract import PUMPFUN_SNIPING_UNIVERSE_POLICY_ID
from backtest.application.source_contracts import (
    # Include pumpfun sniping settlement requirement so the source contracts dependency
    # remains explicit.
    pumpfun_sniping_settlement_requirement,
    require_pumpfun_sniping_source_contract,
)
from backtest.application.source_evidence import (
    PUMPFUN_TERMINAL_LIFECYCLE_ORDERING_POLICY_ID,
    SOLANA_SKIPPED_SLOT_SENTINEL_POLICY_ID,
    LaunchUniverseEvidence,
    PumpfunSnipingSourceEvidenceBinding,
    SkippedSlotSentinelEvidence,
    SourceEvidenceReceiptRef,
    TerminalLifecycleOrderingEvidence,
)
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    # Include solana mainnet network id so the chain dependency remains explicit.
    SOLANA_MAINNET_NETWORK_ID,
    ChainPosition,
)
from backtest.domain.event_hashing import canonical_event_stream_hash

# Import execution mode so each performance cell carries its semantic policy explicitly.
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
    CapabilityId,
    # Include content digest so the identifiers dependency remains explicit.
    ContentDigest,
    DatasetRevisionId,
    FeeComponentId,
    LogicalContentHash,
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
    # Include fee component so the market events dependency remains explicit.
    FeeComponent,
    TokenLaunchEvent,
    VenueTradeEvent,
)
from backtest.domain.time import BlockRange

# Import contracts at the visible module dependency boundary.
from backtest.engine.contracts import EnginePhysicalSettings
from backtest.engine.replay import ReplayBoundary
from backtest.engine.sniping import SnipingReferenceEngine, SnipingRunConfig
from backtest.engine.wallet_accounts import WalletUvaInitialState
from backtest.plugins.networks.solana import (
    # Include solana legacy v0 fee formula v1 so the solana dependency remains explicit.
    SOLANA_LEGACY_V0_FEE_FORMULA_V1,
    SolanaAccountCostProfile,
    SolanaAccountDepositCost,
    SolanaFeeProfile,
    SolanaSnipingCostModel,
    # Include solana transaction format so the solana dependency remains explicit.
    SolanaTransactionFormat,
)
from backtest.plugins.protocols.pumpfun import (
    PUMPFUN_LAUNCH_PAYLOAD_SCHEMA_ID,
    PUMPFUN_LEGACY_ATA_SCHEMA_ID,
    PUMPFUN_PROTOCOL_NAME,
    PUMPFUN_TOKEN_2022_ATA_SCHEMA_ID,
    # Include pumpfun trade payload schema id so the pumpfun dependency remains explicit.
    PUMPFUN_TRADE_PAYLOAD_SCHEMA_ID,
    PUMPFUN_UVA_SCHEMA_ID,
    PumpCurveLifecycle,
    PumpCurveStateV1,
    PumpFeeProfile,
    PumpfunSnipingProtocolRuntime,
    # Include pump mode so the pumpfun dependency remains explicit.
    PumpMode,
    encode_launch_payload,
    encode_trade_payload,
)
from backtest.plugins.strategies import PumpfunSnipingStrategy

# Import thread limits at the visible module dependency boundary.
from backtest.runtime.thread_limits import (
    apply_child_process_determinism,
    require_child_process_determinism,
)

_SOL: Final = AssetId("SOL")
# Bind source id once as an explicit module-level contract.
_SOURCE_ID: Final = SourceId("hermetic-solana-pumpfun-one-day")
_RUNTIME_LOCK_ID: Final = RuntimeLockId("9" * 64)
_BASE_TIME_S: Final = 1_750_000_000
_DAY_SECONDS: Final = 86_400
_START_BLOCK: Final = 10_000

# 216,001 produced blocks model the roughly 2.5 block/s clock shape of one day.
# A launch every 50 blocks gives 4,320 targets without turning the test into a
# synthetic one-row microbenchmark.  Sixteen final blocks are settlement tail.
_BLOCK_COUNT: Final = 216_001
_LAUNCH_EVERY_BLOCKS: Final = 50
_SETTLEMENT_TAIL_BLOCKS: Final = 16
_TRANSACTIONS_PER_BLOCK: Final = 1_200
_MEASURED_ITERATIONS: Final = 3
# Bind spawn timeout seconds once as an explicit module-level contract.
_SPAWN_TIMEOUT_SECONDS: Final = 15 * 60
_GIB: Final = 1 << 30

_BLOCK_CAPABILITY = CapabilityId("benchmark.solana.block-clock.v1")
_LAUNCH_CAPABILITY = CapabilityId("benchmark.pumpfun.token-launch.v1")
_TRADE_CAPABILITY = CapabilityId("benchmark.pumpfun.curve-trade.v1")
# Bind lifecycle capability once as an explicit module-level contract.
_LIFECYCLE_CAPABILITY = CapabilityId("benchmark.pumpfun.curve-lifecycle.v1")

_CAPABILITY_COLUMNS: Final = {
    CapabilityStream.BLOCK_CLOCK: (
        "block_hash",
        "block_ordinal",
        # Keep the block time component named inside the capability columns contract.
        "block_time",
        "transaction_count",
    ),
    CapabilityStream.TOKEN_LAUNCH: (
        "block_ordinal",
        # Keep the creation user component named inside the capability columns contract.
        "creation_user",
        "creator",
        "event_index",
        "lifecycle",
        "mint",
        # Keep the mode component named inside the capability columns contract.
        "mode",
        "quote_asset",
        "real_sol_reserves_lamports",
        "real_token_reserves_atomic",
        "signature",
        # Keep the token total supply atomic component named inside the capability columns
        # contract.
        "token_total_supply_atomic",
        "transaction_index",
        "transaction_succeeded",
        "venue",
        "virtual_sol_reserves_lamports",
        # Keep the virtual token reserves atomic component named inside the capability
        # columns contract.
        "virtual_token_reserves_atomic",
    ),
    CapabilityStream.PUMP_CURVE_TRADE: (
        "base_amount_atomic",
        "block_ordinal",
        # Keep the creator fee atomic component named inside the capability columns
        # contract.
        "creator_fee_atomic",
        "event_index",
        "lifecycle",
        "mint",
        "mode",
        # Keep the protocol fee atomic component named inside the capability columns
        # contract.
        "protocol_fee_atomic",
        "quote_amount_atomic",
        "quote_asset",
        "real_sol_reserves_lamports",
        "real_token_reserves_atomic",
        # Keep the side component named inside the capability columns contract.
        "side",
        "signature",
        "token_total_supply_atomic",
        "transaction_index",
        "venue",
        # Keep the virtual sol reserves lamports component named inside the capability
        # columns contract.
        "virtual_sol_reserves_lamports",
        "virtual_token_reserves_atomic",
    ),
    CapabilityStream.PUMP_CURVE_LIFECYCLE: (
        "block_ordinal",
        # Keep the event index component named inside the capability columns contract.
        "event_index",
        "lifecycle",
        "lifecycle_kind",
        "mint",
        "mode",
        # Keep the real sol reserves lamports component named inside the capability
        # columns contract.
        "real_sol_reserves_lamports",
        "real_token_reserves_atomic",
        "signature",
        "token_total_supply_atomic",
        "transaction_index",
        # Keep the venue component named inside the capability columns contract.
        "venue",
        "virtual_sol_reserves_lamports",
        "virtual_token_reserves_atomic",
    ),
}

# Bind initial curve once as an explicit module-level contract.
_INITIAL_CURVE = PumpCurveStateV1(
    virtual_token_reserves_atomic=1_073_000_000_000_000,
    virtual_sol_reserves_lamports=30_000_000_000,
    real_token_reserves_atomic=793_100_000_000_000,
    real_sol_reserves_lamports=100_000_000_000,
    # Pass token total supply atomic explicitly so PumpCurveStateV1 receives a reviewable
    # active and normal input in module.
    token_total_supply_atomic=1_000_000_000_000_000,
    lifecycle=PumpCurveLifecycle.ACTIVE,
    mode=PumpMode.NORMAL,
)
_POST_BUNDLED_BUY_CURVE = PumpCurveStateV1(
    # Pass virtual token reserves atomic explicitly so PumpCurveStateV1 receives a
    # reviewable active and normal input in module.
    virtual_token_reserves_atomic=1_072_964_234_525_381,
    virtual_sol_reserves_lamports=30_001_000_000,
    real_token_reserves_atomic=793_064_234_525_381,
    real_sol_reserves_lamports=100_001_000_000,
    token_total_supply_atomic=1_000_000_000_000_000,
    # Pass lifecycle explicitly so PumpCurveStateV1 receives a reviewable active and
    # normal input in module.
    lifecycle=PumpCurveLifecycle.ACTIVE,
    mode=PumpMode.NORMAL,
)
_LAUNCH_PAYLOAD: Final = encode_launch_payload(_INITIAL_CURVE)
_TRADE_PAYLOAD: Final = encode_trade_payload(_POST_BUNDLED_BUY_CURVE)

# Keep the backend step explicit within the module workflow.
type _Backend = Literal["reference", "optimized"]


# Keep the measurement contract and validation rules together.
@dataclass(frozen=True, slots=True)
class _Measurement:
    backend: _Backend
    execution_mode: ExecutionMode
    # Preserve spawned-process evidence independently from semantic mode evidence.
    worker_pid: int
    engine_threads: int
    # Declare event count explicitly in the measurement contract.
    event_count: int
    target_count: int
    wall_time_ns: tuple[int, ...]
    result_hashes: tuple[str, ...]
    peak_private_rss_bytes: int
    # Declare rss basis explicitly in the measurement contract.
    rss_basis: str
    swap_operations: tuple[int, ...]

    @property
    def median_wall_time_ns(self) -> int:
        return int(statistics.median(self.wall_time_ns))


# Keep the one day canonical source contract and validation rules together.
class _OneDayCanonicalSource:
    def __init__(self, dataset_spec: DatasetSpec) -> None:
        # Execute the one day canonical source init workflow in explicit, reviewable
        # steps.
        self._dataset_spec = dataset_spec
        self._logical_content_hash: LogicalContentHash | None = None

    @property
    def dataset_revision_id(self) -> DatasetRevisionId:
        return DatasetRevisionId("d" * 64)

    # Apply property semantics to the following one day canonical source logical content
    # hash contract.
    @property
    def logical_content_hash(self) -> LogicalContentHash:
        # Execute the one day canonical source logical content hash workflow in explicit,
        # reviewable steps.
        if self._logical_content_hash is None:
            self._logical_content_hash = canonical_event_stream_hash(self.events())
        return self._logical_content_hash

    @property
    def replay_semantics_id(self) -> ContentDigest:
        # Return the completed one day canonical source replay semantics id result without
        # a hidden fallback.
        return ReplaySemanticsManifest.canonical_v3().replay_semantics_id

    @property
    def decision_range(self) -> BlockRange:
        return self._dataset_spec.decision_range

    @property
    # Define one day canonical source dataset spec as one focused operation with an
    # explicit boundary.
    def dataset_spec(self) -> DatasetSpec:
        return self._dataset_spec

    def boundaries(self) -> tuple[ReplayBoundary, ...]:
        # Execute the one day canonical source boundaries workflow in explicit, reviewable
        # steps.
        values: list[ReplayBoundary] = []
        for block_offset in range(_BLOCK_COUNT):
            # Process range(_BLOCK_COUNT) inside the bounded one day canonical source
            # boundaries loop.
            block = _START_BLOCK + block_offset
            values.append(ReplayBoundary.from_position(_position(block, -1, 0)))
            if _is_launch_block(block_offset):
                values.append(ReplayBoundary.from_position(_position(block, 0, 0)))
        return tuple(values)

    # Define one day canonical source events as one focused operation with an explicit
    # boundary.
    def events(self) -> Iterator[CanonicalEvent]:
        # Execute the one day canonical source events workflow in explicit, reviewable
        # steps.
        for block_offset in range(_BLOCK_COUNT):
            # Process range(_BLOCK_COUNT) inside the bounded one day canonical source
            # events loop.
            block = _START_BLOCK + block_offset
            yield _block_event(block_offset, block)
            if not _is_launch_block(block_offset):
                continue
            launch_number = block_offset // _LAUNCH_EVERY_BLOCKS
            # Keep the yield step explicit within the one day canonical source events
            # workflow.
            yield _launch_event(launch_number, block)
            yield _bundled_trade_event(launch_number, block)


@pytest.mark.performance
@pytest.mark.parametrize(
    "execution_mode",
    # Keep the existing strict cell and add one independently reported virtual cell.
    (
        ExecutionMode.EXOGENOUS_REPLAY,
        ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT,
    ),
    # Give strict and virtual performance evidence stable, readable pytest cells.
    ids=("exogenous-replay", "exogenous-virtual-settlement"),
)
def test_one_day_sniping_release_capacity_gate(
    tmp_path: Path,
    execution_mode: ExecutionMode,
) -> None:
    """Require exact equality, >=2x speedup, bounded RSS and no swap."""

    artifacts, replay_pack_id = _compile_one_day_replay(tmp_path)
    with NumpyMmapReplaySource(artifacts, replay_pack_id) as replay:
        # Keep numpy mmap replay source, artifacts and replay pack id active only for the
        # bounded test one day sniping release capacity gate operation.
        require_pumpfun_sniping_source_contract(replay.dataset_spec)
        clock = replay.transaction_clock()
        assert clock.block_time_ns[-1] - clock.block_time_ns[0] == _DAY_SECONDS * 1_000_000_000
        assert len(clock.block_ordinals) == _BLOCK_COUNT
        assert replay.manifest.payload_counts.token_launches == _expected_target_count()
        # Verify the blocks, block count and payload counts relationship before this
        # scenario is accepted.
        assert replay.manifest.payload_counts.blocks == _BLOCK_COUNT
        event_count = replay.event_count

    original_environment = dict(os.environ)
    try:
        # Perform the protected test one day sniping release capacity gate operation
        # before explicit failure handling.
        apply_child_process_determinism(1)
        reference = _spawn_measurement(
            artifacts.data_root,
            replay_pack_id,
            "reference",
            execution_mode,
            # Complete _spawn_measurement only after its reference and data root inputs are
            # visible in test one day sniping release capacity gate.
        )
        optimized = _spawn_measurement(
            artifacts.data_root,
            replay_pack_id,
            "optimized",
            execution_mode,
            # Complete _spawn_measurement only after its optimized and data root inputs are
            # visible in test one day sniping release capacity gate.
        )
    finally:
        # Handle the cleanup path after the protected test one day sniping release
        # capacity gate operation.
        os.environ.clear()
        os.environ.update(original_environment)

    assert reference.worker_pid != os.getpid()
    assert optimized.worker_pid != os.getpid()
    assert reference.worker_pid != optimized.worker_pid
    assert reference.execution_mode is execution_mode
    assert optimized.execution_mode is execution_mode
    # Verify the engine threads, reference and optimized relationship before this scenario
    # is accepted.
    assert reference.engine_threads == optimized.engine_threads == 1
    assert reference.event_count == optimized.event_count == event_count
    assert reference.target_count == optimized.target_count == _expected_target_count()
    assert len(set(reference.result_hashes)) == 1
    assert len(set(optimized.result_hashes)) == 1
    # Verify the result hashes, reference and optimized relationship before this scenario
    # is accepted.
    assert reference.result_hashes[0] == optimized.result_hashes[0]
    assert all(value == 0 for value in reference.swap_operations)
    assert all(value == 0 for value in optimized.swap_operations)
    assert reference.peak_private_rss_bytes <= 3 * _GIB
    assert optimized.peak_private_rss_bytes <= 3 * _GIB
    # Verify the peak private rss bytes, reference and gib relationship before this
    # scenario is accepted.
    assert reference.peak_private_rss_bytes <= 6 * _GIB
    assert optimized.peak_private_rss_bytes <= 6 * _GIB

    speedup = reference.median_wall_time_ns / optimized.median_wall_time_ns
    assert speedup >= 2.0
    print(
        # Pass json explicitly to print for clock blocks and clock transactions.
        json.dumps(
            {
                "clock_blocks": _BLOCK_COUNT,
                "clock_transactions": _BLOCK_COUNT * _TRANSACTIONS_PER_BLOCK,
                "day_seconds": _DAY_SECONDS,
                "execution_mode": execution_mode.value,
                # Keep event count named so the clock blocks and clock transactions
                # payload passed to dumps remains self-describing within test one day
                # sniping release capacity gate.
                "event_count": event_count,
                "optimized": _measurement_document(optimized),
                "reference": _measurement_document(reference),
                "result_hash": reference.result_hashes[0],
                "speedup_x": speedup,
                # Pass targets explicitly to print for clock blocks and clock
                # transactions.
                "targets": _expected_target_count(),
            },
            sort_keys=True,
        )
    )


# Define spawn measurement as one focused operation with an explicit boundary.
def _spawn_measurement(
    data_root: Path,
    replay_pack_id: ReplayPackId,
    backend: _Backend,
    # Carry the semantic cell into the spawned worker instead of relying on defaults.
    execution_mode: ExecutionMode,
) -> _Measurement:
    # Execute the spawn measurement workflow in explicit, reviewable steps.
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_measure_backend_worker,
        args=(str(data_root), replay_pack_id.hex, backend, execution_mode, sender),
        # Pass name explicitly so Process receives a reviewable sniping-capacity- and hex
        # input in spawn measurement.
        name=f"sniping-capacity-{execution_mode.value.lower()}-{backend}",
    )
    process.start()
    sender.close()
    process.join(_SPAWN_TIMEOUT_SECONDS)
    # Guard this path with process.is_alive() before applying effects.
    if process.is_alive():
        # Handle the spawn measurement process.is_alive() branch as a distinct logical
        # block.
        process.terminate()
        process.join()
        pytest.fail(f"{backend} sniping performance child exceeded timeout")
    if not receiver.poll():
        # Handle the spawn measurement not receiver.poll() branch as a distinct logical
        # block.
        pytest.fail(
            f"{backend} sniping performance child exited without a result: "
            f"exitcode={process.exitcode}"
        )
    payload = receiver.recv()
    # Invoke close as a visible step within the spawn measurement workflow.
    receiver.close()
    if isinstance(payload, dict) and "error" in payload:
        pytest.fail(f"{backend} sniping performance child failed:\n{payload['error']}")
    assert process.exitcode == 0
    if not isinstance(payload, _Measurement):
        # Invoke fail for sniping performance child returned an invalid result and backend
        # as a visible spawn measurement step.
        pytest.fail(f"{backend} sniping performance child returned an invalid result")
    return payload


def _measure_backend_worker(
    data_root: str,
    replay_pack_id: str,
    # Keep the backend input explicit in the measure backend worker contract.
    backend: _Backend,
    execution_mode: ExecutionMode,
    sender: Connection,
) -> None:
    # Execute the measure backend worker workflow in explicit, reviewable steps.
    try:
        # Perform the protected measure backend worker operation before explicit failure
        # handling.
        require_child_process_determinism(1)
        artifacts = LocalArtifactRepository(Path(data_root))
        with NumpyMmapReplaySource(artifacts, ReplayPackId(replay_pack_id)) as source:
            # Keep numpy mmap replay source, artifacts and replay pack id active only for
            # the bounded measure backend worker operation.
            physical_settings = EnginePhysicalSettings(
                reader_batch_rows=65_536,
                reader_readahead=1,
                threads=1,
            )
            # Invoke _execute_backend_once for backend and source as a visible measure
            # backend worker step.
            _execute_backend_once(
                backend,
                source=source,
                physical_settings=physical_settings,
                # Bind both component and engine configuration inside the child process.
                execution_mode=execution_mode,
            )
            # Assemble wall times once so the measure backend worker workflow shares one
            # value.
            wall_times: list[int] = []
            hashes: list[str] = []
            swaps: list[int] = []
            peak_private = 0
            rss_basis = "TOTAL_RSS_CONSERVATIVE_FALLBACK"
            # Assemble target count once so the measure backend worker workflow shares one
            # value.
            target_count = 0
            for _ in range(_MEASURED_ITERATIONS):
                # Process range(_MEASURED_ITERATIONS) inside the bounded measure backend
                # worker loop.
                gc.collect()
                before = resource.getrusage(resource.RUSAGE_SELF)
                sampler = PeakPrivateRssSampler()
                sampler.start()
                started = time.perf_counter_ns()
                # Assemble summary once so the measure backend worker workflow shares one
                # value.
                summary = _execute_backend_once(
                    backend,
                    source=source,
                    physical_settings=physical_settings,
                    # Measure the exact mode selected by the parent performance cell.
                    execution_mode=execution_mode,
                )
                # Assemble elapsed once so the measure backend worker workflow shares one
                # value.
                elapsed = max(1, time.perf_counter_ns() - started)
                sampler.stop()
                after = resource.getrusage(resource.RUSAGE_SELF)
                measured_private = sampler.peak_bytes
                if measured_private is None:
                    # Assemble measured private once so the measure backend worker
                    # workflow shares one value.
                    measured_private = peak_total_rss_bytes()
                else:
                    rss_basis = sampler.basis.value
                peak_private = max(peak_private, measured_private)
                wall_times.append(elapsed)
                # Invoke append for hex and result hash as a visible measure backend
                # worker step.
                hashes.append(summary.result_hash.hex)
                swaps.append(max(0, after.ru_nswap - before.ru_nswap))
                target_count = summary.target_count
            sender.send(
                _Measurement(
                    # Pass backend explicitly so _Measurement receives a reviewable getpid
                    # and threads input in measure backend worker.
                    backend=backend,
                    execution_mode=execution_mode,
                    # Record child/runtime evidence after the semantic inputs.
                    worker_pid=os.getpid(),
                    engine_threads=physical_settings.threads,
                    event_count=source.event_count,
                    target_count=target_count,
                    # Pass wall time ns explicitly to send for threads and event count.
                    wall_time_ns=tuple(wall_times),
                    result_hashes=tuple(hashes),
                    peak_private_rss_bytes=peak_private,
                    rss_basis=rss_basis,
                    swap_operations=tuple(swaps),
                    # Complete _Measurement only after its getpid and threads inputs are
                    # visible in measure backend worker.
                )
            )
    except Exception:
        # Translate the Exception failure through the measure backend worker boundary.
        sender.send({"error": traceback.format_exc()})
        raise
    finally:
        sender.close()


def _execute_backend_once(
    # Keep the backend input explicit in the execute backend once contract.
    backend: _Backend,
    *,
    source: NumpyMmapReplaySource,
    physical_settings: EnginePhysicalSettings,
    # Keep strategy and run configuration on the same closed execution mode.
    execution_mode: ExecutionMode,
):
    # Execute the execute backend once workflow in explicit, reviewable steps.
    strategy, protocol, network = _components(execution_mode)
    config = SnipingRunConfig(
        quote_asset_id=_SOL,
        decision_range=source.decision_range,
        initial_available={_SOL: 10**15},
        # Pass wallet account profile explicitly so SnipingRunConfig receives a reviewable
        # performance-fresh-v1 and pump-token-account-v1 input in execute backend once.
        initial_uva_state=WalletUvaInitialState.FRESH,
        wallet_account_profile_id="performance-fresh-v1",
        uva_schema_id=PUMPFUN_UVA_SCHEMA_ID,
        root_seed=7,
        maximum_dynamic_items=100_000,
        # Avoid a config default that could diverge from the strategy component.
        execution_mode=execution_mode,
        # Complete SnipingRunConfig only after its performance-fresh-v1 and pump-token-
        # account-v1 inputs are visible in execute backend once.
    )
    if backend == "reference":
        engine = SnipingReferenceEngine()
    else:
        # Handle the execute backend once complement of backend == 'reference' explicitly.
        engine = NumpyMmapPumpfunSnipingEngine(
            strategy_type=PumpfunSnipingStrategy,
            protocol_type=PumpfunSnipingProtocolRuntime,
            network_cost_type=SolanaSnipingCostModel,
        )
    # Return the completed execute backend once result without a hidden fallback.
    return engine.run(
        source=source,
        clock=source.transaction_clock(),
        strategy=strategy,
        protocol=protocol,
        # Pass network costs explicitly so run receives a reviewable transaction clock and
        # source input in execute backend once.
        network_costs=network,
        config=config,
        physical_settings=physical_settings,
    )


def _components(
    execution_mode: ExecutionMode,
) -> tuple[
    # Keep the pumpfun sniping strategy input explicit in the components contract.
    PumpfunSnipingStrategy,
    PumpfunSnipingProtocolRuntime,
    SolanaSnipingCostModel,
]:
    # Execute the components workflow in explicit, reviewable steps.
    strategy = PumpfunSnipingStrategy(
        quote_asset_id=_SOL,
        gross_buy_budget_atomic=100_000_000,
        buy_slippage_bps=100,
        sell_slippage_bps=100,
        # Pass sell delay transactions explicitly so PumpfunSnipingStrategy receives a
        # reviewable sol input in components.
        sell_delay_transactions=1,
        execution_mode=execution_mode,
    )
    protocol = PumpfunSnipingProtocolRuntime(
        quote_asset_id=_SOL,
        fee_profile=PumpFeeProfile.static_95_30(
            # Pass profile id explicitly so static_95_30 receives a reviewable pump-
            # static-95-30-performance-v1 and base time s input in components.
            profile_id="pump-static-95-30-performance-v1",
            effective_from_unix_s=_BASE_TIME_S - 1,
            effective_until_unix_s=_BASE_TIME_S + _DAY_SECONDS + 1,
        ),
        protocol_version="pump-program-v1",
        # Complete PumpfunSnipingProtocolRuntime only after its pump-
        # static-95-30-performance-v1 and pump-program-v1 inputs are visible in components.
    )
    network = SolanaSnipingCostModel(
        buy_fee_profile=_solana_fee("buy-performance-v1", 10),
        sell_fee_profile=_solana_fee("sell-performance-v1", 20),
        account_cost_profile=SolanaAccountCostProfile(
            # Pass profile id explicitly so SolanaAccountCostProfile receives a reviewable
            # account-cost-performance-v1 and pump-token-account-v1 input in components.
            profile_id="account-cost-performance-v1",
            effective_from_unix_s=_BASE_TIME_S - 1,
            effective_until_unix_s=_BASE_TIME_S + _DAY_SECONDS + 1,
            costs=(
                SolanaAccountDepositCost(PUMPFUN_UVA_SCHEMA_ID, 1_844_400),
                SolanaAccountDepositCost(PUMPFUN_LEGACY_ATA_SCHEMA_ID, 2_039_280),
                SolanaAccountDepositCost(PUMPFUN_TOKEN_2022_ATA_SCHEMA_ID, 2_074_080),
            ),
        ),
    )
    return strategy, protocol, network


def _solana_fee(profile_id: str, priority_price: int) -> SolanaFeeProfile:
    # Execute the solana fee workflow in explicit, reviewable steps.
    return SolanaFeeProfile(
        profile_id=profile_id,
        formula_version=SOLANA_LEGACY_V0_FEE_FORMULA_V1,
        transaction_format=SolanaTransactionFormat.V0,
        effective_from_unix_s=_BASE_TIME_S - 1,
        # Pass effective until unix s explicitly so SolanaFeeProfile receives a reviewable
        # v0 and profile id input in solana fee.
        effective_until_unix_s=_BASE_TIME_S + _DAY_SECONDS + 1,
        charged_signature_count=1,
        lamports_per_signature=5_000,
        compute_unit_limit=100_000,
        micro_lamports_per_compute_unit=priority_price,
        # Complete SolanaFeeProfile only after its v0 and profile id inputs are visible in
        # solana fee.
    )


def _compile_one_day_replay(
    tmp_path: Path,
) -> tuple[LocalArtifactRepository, ReplayPackId]:
    # Execute the compile one day replay workflow in explicit, reviewable steps.
    artifacts = LocalArtifactRepository(tmp_path / "var")
    dataset_spec = _dataset_spec()
    writer = artifacts.stage(ArtifactDraft(ArtifactKind.SNAPSHOT, ContentDigest("a" * 64)))
    committed = writer.commit(canonical_json_bytes(_snapshot_manifest(dataset_spec)))
    snapshot_id = SnapshotId(committed.artifact_id.hex)
    # Assemble source once so the compile one day replay workflow shares one value.
    source = _OneDayCanonicalSource(dataset_spec)
    compiled = LocalNumpyReplayPackCompiler(
        artifacts,
        lambda requested: _require_snapshot(requested, snapshot_id, source),
        runtime_lock_id=_RUNTIME_LOCK_ID,
        # Complete compile only after its compiler version and snapshot id inputs are visible
        # in compile one day replay.
    ).compile(snapshot_id, physical.COMPILER_VERSION)
    return artifacts, compiled.replay_pack_id


def _require_snapshot(
    requested: SnapshotId,
    expected: SnapshotId,
    # Keep the source input explicit in the require snapshot contract.
    source: _OneDayCanonicalSource,
) -> _OneDayCanonicalSource:
    # Execute the require snapshot workflow in explicit, reviewable steps.
    if requested != expected:
        raise AssertionError("ReplayPack compiler requested another snapshot")
    return source


def _dataset_spec() -> DatasetSpec:
    # Execute the dataset spec workflow in explicit, reviewable steps.
    extraction = BlockRange(
        SOLANA_MAINNET_NETWORK_ID,
        BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        _START_BLOCK,
        _START_BLOCK + _BLOCK_COUNT,
        # Complete BlockRange only after its solana mainnet network id and block32
        # transaction32 position schema id inputs are visible in dataset spec.
    )
    decision = BlockRange(
        SOLANA_MAINNET_NETWORK_ID,
        BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        _START_BLOCK,
        # Pass extraction explicitly so BlockRange receives a reviewable to block ordinal
        # and solana mainnet network id input in dataset spec.
        extraction.to_block_ordinal - _SETTLEMENT_TAIL_BLOCKS,
    )
    settlement = BlockRange(
        SOLANA_MAINNET_NETWORK_ID,
        BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        # Pass decision explicitly so BlockRange receives a reviewable to block ordinal
        # and solana mainnet network id input in dataset spec.
        decision.to_block_ordinal,
        extraction.to_block_ordinal,
    )
    fidelity = _source_fidelity()
    proofs = CapabilityProofs(
        # Keep the cast and mapping cast step visible while building proofs.
        **cast(
            Mapping[str, EvidenceStatus],
            dict.fromkeys(CAPABILITY_PROOF_FIELDS, EvidenceStatus.PROVEN),
        )
    )
    # Assemble declarations once so the dataset spec workflow shares one value.
    declarations = (
        (_BLOCK_CAPABILITY, CapabilityStream.BLOCK_CLOCK),
        (_LAUNCH_CAPABILITY, CapabilityStream.TOKEN_LAUNCH),
        (_TRADE_CAPABILITY, CapabilityStream.PUMP_CURVE_TRADE),
        (_LIFECYCLE_CAPABILITY, CapabilityStream.PUMP_CURVE_LIFECYCLE),
        # Complete the declarations group only after its semantic components are visible.
    )
    capabilities = tuple(
        PlannedCapability(
            capability_id=capability_id,
            protocol="solana" if stream is CapabilityStream.BLOCK_CLOCK else PUMPFUN_PROTOCOL_NAME,
            # Pass protocol version explicitly so PlannedCapability receives a reviewable
            # solana and 1 input in dataset spec.
            protocol_version="1",
            schema_version="1",
            stream=stream,
            columns=_CAPABILITY_COLUMNS[stream],
            fidelity=fidelity,
            # Pass proofs explicitly so PlannedCapability receives a reviewable solana and
            # 1 input in dataset spec.
            proofs=proofs,
            total_key=(),
            keyset_key_is_proven=False,
            utc_pruning_column=None,
            utc_pruning_is_proven=False,
            # Complete PlannedCapability only after its solana and 1 inputs are visible in
            # dataset spec.
        )
        for capability_id, stream in declarations
    )
    range_by_capability = {
        item.capability_id: (
            decision if item.stream is CapabilityStream.TOKEN_LAUNCH else extraction
        )
        for item in capabilities
    }
    capability_ranges = tuple(
        CapabilityExtractionRange(item.capability_id, range_by_capability[item.capability_id])
        # Pass item explicitly so tuple receives a reviewable capability id and capability
        # extraction range input in dataset spec.
        for item in capabilities
        # Complete tuple only after its capability id and capability extraction range inputs
        # are visible in dataset spec.
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
    # Assemble cut evidence once so the dataset spec workflow shares one value.
    cut_evidence = tuple(
        CapabilityCutEvidence(
            capability_id=item.capability_id,
            block_range=extraction,
            snapshot_cut_to_block=extraction.to_block_ordinal,
            # Pass chain finality explicitly so CapabilityCutEvidence receives a
            # reviewable hermetic-one-day-v1 and capability id input in dataset spec.
            chain_finality=ChainFinality.FINALIZED,
            ingestion_watermark_to_block=extraction.to_block_ordinal,
            completeness=IngestionCompleteness.COMPLETE_TO_WATERMARK,
            consistency=SourceConsistency.SNAPSHOT_CONSISTENT,
            upstream_revision="hermetic-one-day-v1",
            # Complete CapabilityCutEvidence only after its hermetic-one-day-v1 and capability
            # id inputs are visible in dataset spec.
        )
        for item in capabilities
    )
    kwargs = {
        "spec_version": DATASET_SPEC_VERSION,
        # Keep the source id component named inside the kwargs contract.
        "source_id": _SOURCE_ID,
        "source_inspection_artifact_id": ArtifactId("f" * 64),
        "source_schema_fingerprint": ContentDigest("e" * 64),
        "capability_mapping_digest": ContentDigest("c" * 64),
        "query_template_digest": ContentDigest("b" * 64),
        # Keep the network id component named inside the kwargs contract.
        "network_id": SOLANA_MAINNET_NETWORK_ID,
        "position_schema_id": BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        "decision_range": decision,
        "settlement_tail": settlement,
        "warmup_blocks": 0,
        # Keep the evidence contracts component named inside the kwargs contract.
        "evidence_contracts": (PUMPFUN_SNIPING_SOURCE_CONTRACT,),
        "capabilities": capabilities,
        "capability_ranges": capability_ranges,
        "cut_evidence": cut_evidence,
        "shards": shards,
        # Register pumpfun sniping settlement requirement and span through
        # pumpfun_sniping_settlement_requirement so the kwargs table remains scannable.
        "settlement_requirement": pumpfun_sniping_settlement_requirement(
            maximum_sell_delay_transactions=1,
            maximum_tail_blocks=settlement.span,
        ),
        "source_evidence_binding": _source_evidence_binding(
            capabilities,
            decision,
            eligible_launch_count=_expected_target_count(),
        ),
    }
    # Return the completed dataset spec result without a hidden fallback.
    return DatasetSpec(spec_id=dataset_spec_identity_digest(**kwargs), **kwargs)


def _source_evidence_binding(
    capabilities: tuple[PlannedCapability, ...],
    decision_range: BlockRange,
    *,
    eligible_launch_count: int,
) -> PumpfunSnipingSourceEvidenceBinding:
    """Bind the one-day fixture to a complete, secret-free v2 source receipt set."""

    empty_ordered_digest = ContentDigest("0" * 64)
    return PumpfunSnipingSourceEvidenceBinding(
        receipt_refs=tuple(
            sorted(
                (
                    SourceEvidenceReceiptRef(
                        item.capability_id,
                        ContentDigest(f"{index + 101:064x}"),
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
            decision_range=decision_range,
            policy_id=PUMPFUN_SNIPING_UNIVERSE_POLICY_ID,
            classified_count=eligible_launch_count,
            eligible_count=eligible_launch_count,
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


def _snapshot_manifest(spec: DatasetSpec) -> dict[str, object]:
    # Execute the snapshot manifest workflow in explicit, reviewable steps.
    event_kinds = {
        _BLOCK_CAPABILITY: EventKind.BLOCK,
        _LAUNCH_CAPABILITY: EventKind.TOKEN_LAUNCH,
        _TRADE_CAPABILITY: EventKind.VENUE_TRADE,
        _LIFECYCLE_CAPABILITY: EventKind.VENUE_LIFECYCLE,
        # Complete the event kinds group only after its semantic components are visible.
    }
    return {
        "artifact_schema": "canonical-snapshot/v4",
        "canonical_schema_version": 3,
        "dataset_spec": dataset_spec_document(spec),
        # Include network id in the completed snapshot manifest result.
        "network_id": spec.network_id.value,
        "position_schema_id": spec.position_schema_id.value,
        "requested_decision_range": _range_document(spec.decision_range),
        "source_boundaries": [
            _source_boundary_document(
                # Pass item explicitly so _source_boundary_document receives a reviewable
                # capability id and block range input in snapshot manifest.
                item.capability_id,
                event_kinds[item.capability_id],
                item.block_range,
            )
            for item in spec.capability_ranges
            # Return the completed snapshot manifest result without a hidden fallback.
        ],
        "spec_id": spec.spec_id.hex,
    }


def _source_boundary_document(
    capability_id: CapabilityId,
    # Keep the event kind input explicit in the source boundary document contract.
    event_kind: EventKind,
    block_range: BlockRange,
) -> dict[str, object]:
    # Execute the source boundary document workflow in explicit, reviewable steps.
    fidelity = {
        "chain_finality": ChainFinality.FINALIZED.value,
        "completeness": IngestionCompleteness.COMPLETE_TO_WATERMARK.value,
        "consistency": SourceConsistency.SNAPSHOT_CONSISTENT.value,
        "fees": FeesFidelity.COMPONENTS.value,
        # Keep the identity component named inside the fidelity contract.
        "identity": IdentityFidelity.EXACT.value,
        "ordering": OrderingFidelity.INSTRUCTION_EXACT.value,
        "state": StateFidelity.BEFORE_AFTER.value,
    }
    return {
        # Include block range in the completed source boundary document result.
        "block_range": _range_document(block_range),
        "capability_id": capability_id.value,
        "capability_schema_version": "1",
        "chain_finality": fidelity["chain_finality"],
        "completeness": fidelity["completeness"],
        # Include event kind in the completed source boundary document result.
        "event_kind": event_kind.name,
        "ingestion_watermark_to_block": block_range.to_block_ordinal,
        "internal_revision": _digest(900, len(capability_id.value)).hex,
        "query_fingerprints": [_digest(901, len(capability_id.value)).hex],
        "snapshot_cut_to_block": block_range.to_block_ordinal,
        # Include source consistency in the completed source boundary document result.
        "source_consistency": fidelity["consistency"],
        "source_fidelity": fidelity,
        "source_id": _SOURCE_ID.value,
        "upstream_revision": "hermetic-one-day-v1",
        "validation_status": "PASS",
        # Return the completed source boundary document result without a hidden fallback.
    }


def _source_fidelity() -> SourceFidelity:
    # Execute the source fidelity workflow in explicit, reviewable steps.
    return SourceFidelity(
        identity=IdentityFidelity.EXACT,
        ordering=OrderingFidelity.INSTRUCTION_EXACT,
        state=StateFidelity.BEFORE_AFTER,
        fees=FeesFidelity.COMPONENTS,
        # Pass chain finality explicitly so SourceFidelity receives a reviewable exact and
        # instruction exact input in source fidelity.
        chain_finality=ChainFinality.FINALIZED,
        completeness=IngestionCompleteness.COMPLETE_TO_WATERMARK,
        consistency=SourceConsistency.SNAPSHOT_CONSISTENT,
    )


def _range_document(value: BlockRange) -> dict[str, object]:
    # Execute the range document workflow in explicit, reviewable steps.
    return {
        "from_block_ordinal": value.from_block_ordinal,
        "network_id": value.network_id.value,
        "position_schema_id": value.position_schema_id.value,
        "to_block_ordinal": value.to_block_ordinal,
        # Return the completed range document result without a hidden fallback.
    }


def _block_event(block_offset: int, block: int) -> BlockEvent:
    # Execute the block event workflow in explicit, reviewable steps.
    return BlockEvent(
        envelope=_envelope(
            block=block,
            transaction=-1,
            event_index=0,
            # Include group id in the completed block event result.
            group_id=_digest(1, block_offset),
            source_id=_digest(2, block_offset),
            event_id=_digest(3, block_offset),
            stable_id=_digest(4, block_offset),
            capability_id=_BLOCK_CAPABILITY,
            # Pass protocol explicitly so _envelope receives a reviewable solana and
            # block-clock-v1 input in block event.
            protocol="solana",
            protocol_version="block-clock-v1",
        ),
        block_time_ns=(_BASE_TIME_S + (block_offset * _DAY_SECONDS) // (_BLOCK_COUNT - 1))
        * 1_000_000_000,
        # Pass tx count explicitly so BlockEvent receives a reviewable solana and block-
        # clock-v1 input in block event.
        tx_count=_TRANSACTIONS_PER_BLOCK,
        block_hash=None,
    )


def _launch_event(launch_number: int, block: int) -> TokenLaunchEvent:
    # Execute the launch event workflow in explicit, reviewable steps.
    token = AssetId(f"TOKEN-{launch_number:06d}")
    venue = VenueId(f"pump-curve-{launch_number:06d}")
    return TokenLaunchEvent(
        envelope=_pump_envelope(block, 0, launch_number, _LAUNCH_CAPABILITY),
        asset_id=token,
        # Include developer id in the completed launch event result.
        developer_id=AccountId(f"developer-{launch_number:06d}"),
        creation_user_id=AccountId(f"payer-{launch_number:06d}"),
        venue_id=venue,
        quote_asset_id=_SOL,
        protocol_payload_schema=PUMPFUN_LAUNCH_PAYLOAD_SCHEMA_ID,
        # Pass protocol payload explicitly so TokenLaunchEvent receives a reviewable
        # developer- and 06d input in launch event.
        protocol_payload=_LAUNCH_PAYLOAD,
        decimals=6,
    )


def _bundled_trade_event(launch_number: int, block: int) -> VenueTradeEvent:
    # Execute the bundled trade event workflow in explicit, reviewable steps.
    token = AssetId(f"TOKEN-{launch_number:06d}")
    return VenueTradeEvent(
        envelope=_pump_envelope(block, 1, launch_number, _TRADE_CAPABILITY),
        venue_id=VenueId(f"pump-curve-{launch_number:06d}"),
        sold_asset_id=_SOL,
        # Pass bought asset id explicitly so VenueTradeEvent receives a reviewable pump-
        # curve- and 06d input in bundled trade event.
        bought_asset_id=token,
        sold_amount_atomic=1_000_000,
        bought_amount_atomic=35_765_474_619,
        fee_components=(
            FeeComponent(FeeComponentId("pump-creator"), _SOL, 3_000),
            # Include fee component in the completed bundled trade event result.
            FeeComponent(FeeComponentId("pump-protocol"), _SOL, 9_500),
        ),
        protocol_payload_schema=PUMPFUN_TRADE_PAYLOAD_SCHEMA_ID,
        protocol_payload=_TRADE_PAYLOAD,
    )


# Define pump envelope as one focused operation with an explicit boundary.
def _pump_envelope(
    block: int,
    event_index: int,
    launch_number: int,
    capability_id: CapabilityId,
    # Keep the event envelope input explicit in the pump envelope contract.
) -> EventEnvelope:
    # Execute the pump envelope workflow in explicit, reviewable steps.
    return _envelope(
        block=block,
        transaction=0,
        event_index=event_index,
        group_id=_digest(10, launch_number),
        # Include source id in the completed pump envelope result.
        source_id=_digest(11 + event_index, launch_number),
        event_id=_digest(13 + event_index, launch_number),
        stable_id=_digest(15 + event_index, launch_number),
        capability_id=capability_id,
        protocol=PUMPFUN_PROTOCOL_NAME,
        # Pass protocol version explicitly so _envelope receives a reviewable pump-
        # program-v1 and digest input in pump envelope.
        protocol_version="pump-program-v1",
    )


def _envelope(
    *,
    block: int,
    # Keep the transaction input explicit in the envelope contract.
    transaction: int,
    event_index: int,
    group_id: ContentDigest,
    source_id: ContentDigest,
    event_id: ContentDigest,
    # Keep the stable id input explicit in the envelope contract.
    stable_id: ContentDigest,
    capability_id: CapabilityId,
    protocol: str,
    protocol_version: str,
) -> EventEnvelope:
    # Execute the envelope workflow in explicit, reviewable steps.
    return EventEnvelope(
        position=_position(block, transaction, event_index),
        transaction_group_id=group_id,
        source_record_id=source_id,
        canonical_event_id=event_id,
        # Pass stable causal id explicitly so EventEnvelope receives a reviewable
        # instruction exact and position input in envelope.
        stable_causal_id=stable_id,
        capability_id=capability_id,
        protocol=protocol,
        protocol_version=protocol_version,
        ordering_fidelity=OrderingFidelity.INSTRUCTION_EXACT,
        # Complete EventEnvelope only after its instruction exact and position inputs are
        # visible in envelope.
    )


def _position(block: int, transaction: int, event_index: int) -> ChainPosition:
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


def _digest(namespace: int, value: int) -> ContentDigest:
    return ContentDigest(f"{((namespace << 48) | value):064x}")


def _is_launch_block(block_offset: int) -> bool:
    # Execute the is launch block workflow in explicit, reviewable steps.
    return (
        block_offset < _BLOCK_COUNT - _SETTLEMENT_TAIL_BLOCKS
        and block_offset % _LAUNCH_EVERY_BLOCKS == 0
    )


def _expected_target_count() -> int:
    # Execute the expected target count workflow in explicit, reviewable steps.
    decision_blocks = _BLOCK_COUNT - _SETTLEMENT_TAIL_BLOCKS
    return (decision_blocks + _LAUNCH_EVERY_BLOCKS - 1) // _LAUNCH_EVERY_BLOCKS


def _measurement_document(value: _Measurement) -> dict[str, object]:
    # Execute the measurement document workflow in explicit, reviewable steps.
    return {
        "median_wall_seconds": value.median_wall_time_ns / 1_000_000_000,
        "peak_private_rss_bytes": value.peak_private_rss_bytes,
        "rss_basis": value.rss_basis,
        "swap_operations": list(value.swap_operations),
        # Include wall time seconds in the completed measurement document result.
        "wall_time_seconds": [item / 1_000_000_000 for item in value.wall_time_ns],
        "worker_pid": value.worker_pid,
    }
