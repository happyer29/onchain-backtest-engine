# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import io
import json
import shutil
from collections.abc import Callable, Iterator

# Import dataclasses at the visible module dependency boundary.
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from backtest.adapters.artifacts.localfs.repository import (
    # Include artifact integrity error so the repository dependency remains explicit.
    ArtifactIntegrityError,
    LocalArtifactRepository,
)
from backtest.adapters.columnar.numpy import (
    LocalNumpyReplayPackCompiler,
    # Close the numpy import after its required symbols are visible.
)
from backtest.adapters.columnar.numpy import layout as replay_physical
from backtest.adapters.delivery_schedule.numpy import (
    DeliveryScheduleCompileError,
    DeliveryScheduleFormatError,
    # Include local numpy delivery schedule compiler so the numpy dependency remains
    # explicit.
    LocalNumpyDeliveryScheduleCompiler,
    NumpyMmapDeliverySchedule,
)
from backtest.adapters.delivery_schedule.numpy import layout as delivery_physical
from backtest.adapters.delivery_schedule.numpy.compiler import unit_delivery_build_tools

# Import results at the visible module dependency boundary.
from backtest.adapters.results import LocalJobResultReader
from backtest.application.delivery_schedules import (
    CompiledDeliverySchedule,
    CompileDeliveryScheduleRequest,
    DeliveryScheduleManifest,
    # Include scheduled delivery so the delivery schedules dependency remains explicit.
    ScheduledDelivery,
)
from backtest.application.errors import WorkflowNotImplementedError
from backtest.application.job_commands import ResolvedCompileDeliveryScheduleJob
from backtest.application.ml_contracts import ExactInferencePolicy

# Import models at the visible module dependency boundary.
from backtest.application.models import ArtifactDraft, ArtifactKind, DatasetSpec
from backtest.application.replay_packs import (
    CompiledReplayPack,
    ReplaySemanticsManifest,
)

# Import run specs at the visible module dependency boundary.
from backtest.application.run_specs import (
    AssetBalance,
    ReplayInputFormat,
    ResolvedComponent,
    ResolvedReplayInput,
    # Include resolved run spec so the run specs dependency remains explicit.
    ResolvedRunSpec,
)
from backtest.application.use_cases.compile_delivery_schedule import (
    CompileDeliverySchedule,
)

# Import chain at the visible module dependency boundary.
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
)
from backtest.domain.event_hashing import canonical_event_stream_hash

# Import fidelity at the visible module dependency boundary.
from backtest.domain.fidelity import OrderingFidelity
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.domain.identifiers import (
    AccountId,
    AssetId,
    # Include bundle id so the identifiers dependency remains explicit.
    BundleId,
    ContentDigest,
    DatasetRevisionId,
    DeliveryScheduleId,
    LogicalContentHash,
    # Include protocol payload schema id so the identifiers dependency remains explicit.
    ProtocolPayloadSchemaId,
    ReplayPackId,
    RuntimeLockId,
    SnapshotId,
    VenueId,
    # Close the identifiers import after its required symbols are visible.
)
from backtest.domain.market_events import (
    BlockEvent,
    CanonicalEvent,
    ChainPosition,
    # Include event envelope so the market events dependency remains explicit.
    EventEnvelope,
    TokenCreationEvent,
)
from backtest.domain.time import BlockRange
from backtest.engine.reference import (
    # Include engine bundle id so the reference dependency remains explicit.
    ENGINE_BUNDLE_ID,
    SLOT_LATENCY_MODEL_BUNDLE_ID,
)
from backtest.engine.replay import ReplayBoundary
from backtest.engine.rng import RNG_ALGORITHM

# Import scheduler at the visible module dependency boundary.
from backtest.engine.scheduler import (
    SCHEDULER_BUNDLE_ID,
    CausalScheduler,
    SchedulerKey,
    SchedulerPhase,
    # Include first boundary at or after slot so the scheduler dependency remains
    # explicit.
    first_boundary_at_or_after_slot,
)
from tests.support.replay_v3 import (
    FIXTURE_CAPABILITY_ID,
    FIXTURE_DECISION_RANGE,
    # Include fixture dataset spec so the replay v3 dependency remains explicit.
    fixture_dataset_spec,
    fixture_snapshot_manifest,
)


# Keep the canonical source contract and validation rules together.
class _CanonicalSource:
    def __init__(self, events: tuple[CanonicalEvent, ...]) -> None:
        # Execute the canonical source init workflow in explicit, reviewable steps.
        self._events = events
        self._logical_hash = canonical_event_stream_hash(events)
        self._boundaries = _boundaries(events)

    @property
    def dataset_revision_id(self) -> DatasetRevisionId:
        # Return the completed canonical source dataset revision id result without a
        # hidden fallback.
        return DatasetRevisionId("d" * 64)

    @property
    def logical_content_hash(self) -> LogicalContentHash:
        return self._logical_hash

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

    def boundaries(self) -> tuple[ReplayBoundary, ...]:
        return self._boundaries

    # Define canonical source events as one focused operation with an explicit boundary.
    def events(self) -> Iterator[CanonicalEvent]:
        yield from self._events


@pytest.mark.parametrize("observation_slots", [0, 1, 2, 6])
def test_dynamic_and_materialized_streams_match_across_slot_latencies(
    tmp_path: Path,
    # Keep the observation slots input explicit in the test dynamic and materialized
    # streams match across slot latencies contract.
    observation_slots: int,
) -> None:
    # Execute the test dynamic and materialized streams match across slot latencies
    # workflow in explicit, reviewable steps.
    artifacts, events, _, compiled = _compile(
        tmp_path,
        observation_slots=observation_slots,
    )

    with NumpyMmapDeliverySchedule(artifacts, compiled.delivery_schedule_id) as schedule:
        # Keep numpy mmap delivery schedule, artifacts and delivery schedule id active
        # only for the bounded test dynamic and materialized streams match across slot
        # latencies operation.
        assert tuple(schedule.deliveries()) == _dynamic_deliveries(
            events,
            _boundaries(events),
            observation_slots=observation_slots,
        )


# Define test materialized schedule is exactly dynamic scheduler equivalent as one focused
# operation with an explicit boundary.
def test_materialized_schedule_is_exactly_dynamic_scheduler_equivalent(
    tmp_path: Path,
) -> None:
    # Execute the test materialized schedule is exactly dynamic scheduler equivalent
    # workflow in explicit, reviewable steps.
    artifacts, events, replay_pack, compiled = _compile(tmp_path, observation_slots=2)
    expected = _dynamic_deliveries(events, _boundaries(events), observation_slots=2)

    with NumpyMmapDeliverySchedule(artifacts, compiled.delivery_schedule_id) as schedule:
        # Keep numpy mmap delivery schedule, artifacts and delivery schedule id active
        # only for the bounded test materialized schedule is exactly dynamic scheduler
        # equivalent operation.
        assert tuple(schedule.deliveries()) == expected
        assert tuple(schedule.deliveries()) == (
            ScheduledDelivery(_boundaries(events)[3].boundary_ordinal, 0),
            ScheduledDelivery(_boundaries(events)[3].boundary_ordinal, 2),
            ScheduledDelivery(_boundaries(events)[3].boundary_ordinal, 1),
            # Keep the scheduled delivery expectation tied to deliveries, scheduled
            # delivery and boundary ordinal in this scenario.
            ScheduledDelivery(_boundaries(events)[3].boundary_ordinal, 3),
            ScheduledDelivery(_boundaries(events)[5].boundary_ordinal, 4),
            ScheduledDelivery(_boundaries(events)[5].boundary_ordinal, 5),
        )
        assert schedule.replay_pack_id == replay_pack.replay_pack_id
        # Verify schedule.manifest.delivery_count == 6 before this scenario is accepted.
        assert schedule.manifest.delivery_count == 6
        assert schedule.manifest.outside_horizon_count == 2
        assert schedule.manifest.observation_phase == int(SchedulerPhase.OBSERVATION_DELIVERY)
        schedule.require_build(compiled.requested_build)
        arrays = schedule.arrays()
        # Verify the array, isinstance and memmap relationship before this scenario is
        # accepted.
        assert all(
            isinstance(array, np.memmap) and not array.flags.writeable for array in arrays.values()
        )


@pytest.mark.parametrize(
    "execution_mode",
    ("EXOGENOUS_REPLAY", "EXOGENOUS_VIRTUAL_SETTLEMENT"),
)
# Both modes share observation timing even though their sell settlement differs.
def test_sniping_policy_materializes_post_group_zero_delay_observations(
    tmp_path: Path,
    execution_mode: str,
    # Close the test sniping policy materializes post group zero delay observations signature
    # after its explicit inputs.
) -> None:
    # Execute the test sniping policy materializes post group zero delay observations
    # workflow in explicit, reviewable steps.
    artifacts, events, replay_pack, _ = _compile(tmp_path, observation_slots=1)
    compiled = CompileDeliverySchedule(_compiler(artifacts)).execute(
        _sniping_request(replay_pack, execution_mode=execution_mode)
    )

    with NumpyMmapDeliverySchedule(artifacts, compiled.delivery_schedule_id) as schedule:
        # Keep numpy mmap delivery schedule, artifacts and delivery schedule id active
        # only for the bounded test sniping policy materializes post group zero delay
        # observations operation.
        expected = _dynamic_deliveries(events, _boundaries(events), observation_slots=0)
        assert tuple(schedule.deliveries()) == expected
        assert schedule.input_event_count == schedule.delivery_count == len(events)
        assert schedule.outside_horizon_count == 0
        release_boundaries, event_rows = schedule.delivery_columns()
        # Verify the release boundary ordinal, value and release boundaries relationship
        # before this scenario is accepted.
        assert tuple(int(value) for value in release_boundaries) == tuple(
            item.release_boundary_ordinal for item in expected
        )
        assert tuple(int(value) for value in event_rows) == tuple(
            item.event_row_index
            # Pass item explicitly so tuple receives a reviewable event row index and item
            # input in test sniping policy materializes post group zero delay
            # observations.
            for item in expected
            # Complete tuple only after its event row index and item inputs are visible in
            # test sniping policy materializes post group zero delay observations.
        )


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    (
        ("buy_delay_transactions", 499, "exactly 500"),
        # Open the field name and value payload explicitly for parametrize within test
        # sniping policy rejects non v1 fixed latency.
        ("sell_decision_delay_seconds", 3, "exactly 2"),
    ),
)
def test_sniping_policy_rejects_non_v1_fixed_latency(
    tmp_path: Path,
    # Keep the field name input explicit in the test sniping policy rejects non v1 fixed
    # latency contract.
    field_name: str,
    value: int,
    message: str,
) -> None:
    # Execute the test sniping policy rejects non v1 fixed latency workflow in explicit,
    # reviewable steps.
    artifacts, _, replay_pack, _ = _compile(tmp_path, observation_slots=1)
    request = _sniping_request(replay_pack)
    latency = request.component("latency")
    config = json.loads(latency.canonical_config)
    assert isinstance(config, dict)
    # Assemble config[field name] once so the test sniping policy rejects non v1 fixed
    # latency workflow shares one value.
    config[field_name] = value
    components = tuple(
        ResolvedComponent.create(
            role=item.role,
            bundle_id=item.bundle_id,
            # Pass config explicitly so create receives a reviewable role and bundle id
            # input in test sniping policy rejects non v1 fixed latency.
            config=config,
        )
        if item.role == "latency"
        else item
        for item in request.components
        # Complete tuple only after its latency and components inputs are visible in test
        # sniping policy rejects non v1 fixed latency.
    )

    with pytest.raises(DeliveryScheduleCompileError, match=message):
        _compiler(artifacts).compile(replace(request, components=components))


def test_build_key_is_separate_from_delivery_content_identity(tmp_path: Path) -> None:
    # Execute the test build key is separate from delivery content identity workflow in
    # explicit, reviewable steps.
    artifacts, _, replay_pack, first = _compile(
        tmp_path,
        observation_slots=2,
        root_seed=41,
    )
    # Assemble second once so the test build key is separate from delivery content
    # identity workflow shares one value.
    second = _compile_delivery(
        artifacts,
        replay_pack,
        observation_slots=2,
        root_seed=42,
        # Complete _compile_delivery only after its artifacts and replay pack inputs are
        # visible in test build key is separate from delivery content identity.
    )

    assert first.delivery_build_key != second.delivery_build_key
    assert first.delivery_schedule_id == second.delivery_schedule_id
    assert "build" not in first.manifest.identity_document()
    assert "delivery_build_key" not in first.manifest.identity_document()


# Define test reader rejects an independently expected writer identity as one focused
# operation with an explicit boundary.
def test_reader_rejects_an_independently_expected_writer_identity(tmp_path: Path) -> None:
    # Execute the test reader rejects an independently expected writer identity workflow
    # in explicit, reviewable steps.
    artifacts, _, _, compiled = _compile(tmp_path, observation_slots=2)

    with pytest.raises(DeliveryScheduleFormatError, match="writer bundle"):
        # Keep raises, delivery schedule format error and pytest active only for the
        # bounded test reader rejects an independently expected writer identity operation.
        NumpyMmapDeliverySchedule(
            artifacts,
            compiled.delivery_schedule_id,
            build_tools=unit_delivery_build_tools(writer_bundle_id=BundleId("7" * 64)),
        )


# Define test isolated job result reader reconstructs exact delivery result as one focused
# operation with an explicit boundary.
def test_isolated_job_result_reader_reconstructs_exact_delivery_result(
    tmp_path: Path,
) -> None:
    # Execute the test isolated job result reader reconstructs exact delivery result
    # workflow in explicit, reviewable steps.
    artifacts, _, replay_pack, compiled = _compile(tmp_path, observation_slots=2)
    spec = _resolved_spec_for_delivery(replay_pack, compiled)
    command = ResolvedCompileDeliveryScheduleJob(
        spec,
        delivery_physical.COMPILER_VERSION,
        # Complete ResolvedCompileDeliveryScheduleJob only after its compiler version and spec
        # inputs are visible in test isolated job result reader reconstructs exact delivery
        # result.
    )

    read_back = LocalJobResultReader(artifacts).compiled_delivery_schedule(
        command,
        compiled.artifact,
    )

    # Verify read_back == compiled before this scenario is accepted.
    assert read_back == compiled


def test_reader_rejects_seed_config_and_runtime_build_mismatches(tmp_path: Path) -> None:
    # Execute the test reader rejects seed config and runtime build mismatches workflow in
    # explicit, reviewable steps.
    artifacts, _, _, compiled = _compile(tmp_path, observation_slots=2)
    wrong_latency = ResolvedComponent.create(
        role="latency",
        bundle_id=SLOT_LATENCY_MODEL_BUNDLE_ID,
        config={"observation_slots": 1, "order_slots": 0},
        # Complete create only after its latency and observation slots inputs are visible in
        # test reader rejects seed config and runtime build mismatches.
    )
    wrong_components = tuple(
        wrong_latency if item.role == "latency" else item
        for item in compiled.requested_build.components
    )
    # Assemble mismatches once so the test reader rejects seed config and runtime build
    # mismatches workflow shares one value.
    mismatches = (
        replace(compiled.requested_build, root_seed=compiled.requested_build.root_seed + 1),
        replace(compiled.requested_build, components=wrong_components),
        replace(compiled.requested_build, runtime_lock_id=RuntimeLockId("8" * 64)),
    )

    # Acquire numpy mmap delivery schedule, artifacts and delivery schedule id at an
    # explicit test reader rejects seed config and runtime build mismatches context
    # boundary so cleanup remains scoped.
    with NumpyMmapDeliverySchedule(artifacts, compiled.delivery_schedule_id) as schedule:
        # Keep numpy mmap delivery schedule, artifacts and delivery schedule id active
        # only for the bounded test reader rejects seed config and runtime build
        # mismatches operation.
        for expected_build in mismatches:
            # Process mismatches inside the bounded test reader rejects seed config and
            # runtime build mismatches loop.
            with pytest.raises(DeliveryScheduleFormatError, match="build differs"):
                schedule.require_build(expected_build)


def test_compiler_rejects_replay_semantics_layout_and_scheduler_mismatches(
    tmp_path: Path,
) -> None:
    # Execute the test compiler rejects replay semantics layout and scheduler mismatches
    # workflow in explicit, reviewable steps.
    artifacts, _, replay_pack, _ = _compile(tmp_path, observation_slots=2)
    compiler = _compiler(artifacts)
    valid = _request(replay_pack, observation_slots=2)
    with pytest.raises(WorkflowNotImplementedError):
        CompileDeliverySchedule().execute(valid)
    # Assemble wrong scheduler once so the test compiler rejects replay semantics layout
    # and scheduler mismatches workflow shares one value.
    wrong_scheduler = ResolvedComponent.create(
        role="scheduler",
        bundle_id=SCHEDULER_BUNDLE_ID,
        config={"phase_table": "non-canonical"},
    )
    # Assemble scheduler components once so the test compiler rejects replay semantics
    # layout and scheduler mismatches workflow shares one value.
    scheduler_components = tuple(
        wrong_scheduler if item.role == "scheduler" else item for item in valid.components
    )

    mismatches = (
        replace(valid, replay_semantics_id=ContentDigest("1" * 64)),
        # Register valid through replace so the mismatches table remains scannable.
        replace(valid, replay_layout_schema_id=ContentDigest("2" * 64)),
        replace(valid, components=scheduler_components),
        replace(valid, rng_algorithm="another-rng-v1"),
        replace(valid, compiler_version="another-compiler-v1"),
    )
    # Traverse mismatches explicitly so each test compiler rejects replay semantics layout
    # and scheduler mismatches iteration remains traceable.
    for request in mismatches:
        # Process mismatches inside the bounded test compiler rejects replay semantics
        # layout and scheduler mismatches loop.
        with pytest.raises(DeliveryScheduleCompileError):
            compiler.compile(request)


def test_compiler_enforces_bounded_atomic_group(tmp_path: Path) -> None:
    # Execute the test compiler enforces bounded atomic group workflow in explicit,
    # reviewable steps.
    artifacts, _, replay_pack = _compile_replay(tmp_path)
    compiler = LocalNumpyDeliveryScheduleCompiler(
        artifacts,
        runtime_lock_id=RuntimeLockId("9" * 64),
        maximum_group_rows=1,
        # Complete LocalNumpyDeliveryScheduleCompiler only after its 9 and runtime lock id
        # inputs are visible in test compiler enforces bounded atomic group.
    )

    with pytest.raises(DeliveryScheduleCompileError, match="maximum_group_rows"):
        compiler.compile(_request(replay_pack, observation_slots=2))

    recovered = _compiler(artifacts).compile(_request(replay_pack, observation_slots=2))
    assert recovered.delivery_schedule_id
    # Verify the iterdir, staging root and artifacts relationship before this scenario is
    # accepted.
    assert not tuple(artifacts.staging_root.iterdir())


def test_physical_corruption_is_rejected_before_mmap(tmp_path: Path) -> None:
    # Execute the test physical corruption is rejected before mmap workflow in explicit,
    # reviewable steps.
    artifacts, _, _, compiled = _compile(tmp_path, observation_slots=2)
    path = (
        artifacts.data_root
        / "delivery_schedules"
        / compiled.delivery_schedule_id.hex
        # Keep the delivery physical component named inside the path contract.
        / delivery_physical.EVENT_ROW_INDEX
    )
    with path.open("r+b") as stream:
        # Keep open and path active only for the bounded test physical corruption is
        # rejected before mmap operation.
        stream.seek(-1, 2)
        original = stream.read(1)
        stream.seek(-1, 2)
        stream.write(bytes([original[0] ^ 0xFF]))

    with pytest.raises(ArtifactIntegrityError):
        # Invoke NumpyMmapDeliverySchedule for delivery schedule id and artifacts as a
        # visible test physical corruption is rejected before mmap step.
        NumpyMmapDeliverySchedule(artifacts, compiled.delivery_schedule_id)


@pytest.mark.parametrize(
    ("target", "mutate", "message"),
    (
        (
            # Pass delivery physical explicitly so parametrize receives a reviewable
            # target and mutate input in test reader rejects dtype endian and row offset
            # corruption.
            delivery_physical.EVENT_ROW_INDEX,
            lambda value: value.astype("<u4"),
            "dtype/endian mismatch",
        ),
        (
            # Pass delivery physical explicitly so parametrize receives a reviewable
            # target and mutate input in test reader rejects dtype endian and row offset
            # corruption.
            delivery_physical.RELEASE_BOUNDARY_ORDINAL,
            lambda value: value.astype(">u8"),
            "dtype/endian mismatch",
        ),
        (
            # Pass delivery physical explicitly so parametrize receives a reviewable
            # target and mutate input in test reader rejects dtype endian and row offset
            # corruption.
            delivery_physical.EVENT_ROW_INDEX,
            lambda value: _replace_first(value, 99),
            "out of bounds",
        ),
    ),
    # Complete parametrize only after its target and mutate inputs are visible in test reader
    # rejects dtype endian and row offset corruption.
)
def test_reader_rejects_dtype_endian_and_row_offset_corruption(
    tmp_path: Path,
    target: str,
    mutate: Callable[[np.ndarray], np.ndarray],
    # Keep the message input explicit in the test reader rejects dtype endian and row
    # offset corruption contract.
    message: str,
) -> None:
    # Execute the test reader rejects dtype endian and row offset corruption workflow in
    # explicit, reviewable steps.
    artifacts, _, _, compiled = _compile(tmp_path, observation_slots=2)
    malformed = _republish_with_array(
        artifacts,
        compiled.delivery_schedule_id,
        target,
        # Pass mutate explicitly so _republish_with_array receives a reviewable delivery
        # schedule id and artifacts input in test reader rejects dtype endian and row
        # offset corruption.
        mutate,
    )

    with pytest.raises(DeliveryScheduleFormatError, match=message):
        NumpyMmapDeliverySchedule(artifacts, malformed)


def _compile(
    # Keep the tmp path input explicit in the compile contract.
    tmp_path: Path,
    *,
    observation_slots: int,
    root_seed: int = 42,
) -> tuple[
    # Keep the local artifact repository input explicit in the compile contract.
    LocalArtifactRepository,
    tuple[CanonicalEvent, ...],
    CompiledReplayPack,
    CompiledDeliverySchedule,
]:
    # Execute the compile workflow in explicit, reviewable steps.
    artifacts, events, replay_pack = _compile_replay(tmp_path)
    schedule = _compile_delivery(
        artifacts,
        replay_pack,
        observation_slots=observation_slots,
        # Pass root seed explicitly so _compile_delivery receives a reviewable artifacts
        # and replay pack input in compile.
        root_seed=root_seed,
    )
    return artifacts, events, replay_pack, schedule


def _compile_replay(
    tmp_path: Path,
    # Keep the tuple input explicit in the compile replay contract.
) -> tuple[LocalArtifactRepository, tuple[CanonicalEvent, ...], CompiledReplayPack]:
    # Execute the compile replay workflow in explicit, reviewable steps.
    artifacts = LocalArtifactRepository(tmp_path / "var")
    snapshot_id = _publish_snapshot(artifacts)
    events = _events()
    compiler = LocalNumpyReplayPackCompiler(
        artifacts,
        # Keep the requested _checked_source step visible while building compiler.
        lambda requested: _checked_source(requested, snapshot_id, events),
        runtime_lock_id=RuntimeLockId("9" * 64),
    )
    replay_pack = compiler.compile(snapshot_id, replay_physical.COMPILER_VERSION)
    return artifacts, events, replay_pack


# Define compile delivery as one focused operation with an explicit boundary.
def _compile_delivery(
    artifacts: LocalArtifactRepository,
    replay_pack: CompiledReplayPack,
    *,
    observation_slots: int,
    # Keep the root seed input explicit in the compile delivery contract.
    root_seed: int = 42,
) -> CompiledDeliverySchedule:
    # Execute the compile delivery workflow in explicit, reviewable steps.
    result = CompileDeliverySchedule(_compiler(artifacts)).execute(
        _request(
            replay_pack,
            observation_slots=observation_slots,
            root_seed=root_seed,
            # Complete _request only after its replay pack and observation slots inputs are
            # visible in compile delivery.
        )
    )
    assert isinstance(result, CompiledDeliverySchedule)
    return result


def _compiler(artifacts: LocalArtifactRepository) -> LocalNumpyDeliveryScheduleCompiler:
    # Execute the compiler workflow in explicit, reviewable steps.
    return LocalNumpyDeliveryScheduleCompiler(
        artifacts,
        runtime_lock_id=RuntimeLockId("9" * 64),
    )


def _request(
    # Keep the replay pack input explicit in the request contract.
    replay_pack: CompiledReplayPack,
    *,
    observation_slots: int,
    root_seed: int = 42,
) -> CompileDeliveryScheduleRequest:
    # Execute the request workflow in explicit, reviewable steps.
    components = (
        ResolvedComponent.create(
            role="clock",
            bundle_id=_bundle("clock"),
            config={"duration_mapping": "ceil-to-next-boundary"},
            # Complete create only after its clock and duration mapping inputs are visible in
            # request.
        ),
        ResolvedComponent.create(
            role="engine",
            bundle_id=ENGINE_BUNDLE_ID,
            config={"maximum_dynamic_items": 10_000},
            # Complete create only after its engine and maximum dynamic items inputs are
            # visible in request.
        ),
        ResolvedComponent.create(
            role="latency",
            bundle_id=SLOT_LATENCY_MODEL_BUNDLE_ID,
            config={"observation_slots": observation_slots, "order_slots": 0},
            # Complete create only after its latency and observation slots inputs are visible
            # in request.
        ),
        ResolvedComponent.create(
            role="scheduler",
            bundle_id=SCHEDULER_BUNDLE_ID,
            config={"phase_table": "canonical-v1"},
            # Complete create only after its scheduler and phase table inputs are visible in
            # request.
        ),
    )
    return CompileDeliveryScheduleRequest(
        replay_pack_id=replay_pack.replay_pack_id,
        replay_semantics_id=replay_pack.manifest.semantics.replay_semantics_id,
        # Pass replay layout schema id explicitly so CompileDeliveryScheduleRequest
        # receives a reviewable replay pack id and replay semantics id input in request.
        replay_layout_schema_id=replay_pack.manifest.layout.replay_layout_schema_id,
        components=components,
        rng_algorithm=RNG_ALGORITHM,
        root_seed=root_seed,
        compiler_version=delivery_physical.COMPILER_VERSION,
        # Complete CompileDeliveryScheduleRequest only after its replay pack id and replay
        # semantics id inputs are visible in request.
    )


def _sniping_request(
    replay_pack: CompiledReplayPack,
    *,
    execution_mode: str = "EXOGENOUS_REPLAY",
) -> CompileDeliveryScheduleRequest:
    # Execute the sniping request workflow in explicit, reviewable steps.
    components = (
        ResolvedComponent.create(
            role="clock",
            bundle_id=_bundle("sniping-clock"),
            config={
                # Keep block time resolution named so the clock and sniping-clock payload
                # passed to create remains self-describing within sniping request.
                "block_time_resolution": "seconds-v1",
                "contract": "compact-global-transaction-clock-v1",
            },
        ),
        ResolvedComponent.create(
            # Pass role explicitly so create receives a reviewable engine and sniping-
            # engine input in sniping request.
            role="engine",
            bundle_id=_bundle("sniping-engine"),
            config={
                "execution_mode": execution_mode,
                "maximum_dynamic_items": 1_000_000,
                # Keep run contract named so the engine and sniping-engine payload passed
                # to create remains self-describing within sniping request.
                "run_contract": "pumpfun-sniping-run-draft/v3",
            },
        ),
        ResolvedComponent.create(
            role="latency",
            # Register sniping-latency through _bundle so the components table remains
            # scannable.
            bundle_id=_bundle("sniping-latency"),
            config={
                "buy_delay_transactions": 500,
                "sell_decision_delay_seconds": 2,
                "sell_delay_transactions": 1,
                # Close the latency and sniping-latency payload only after all sniping request
                # fields are present.
            },
        ),
        ResolvedComponent.create(
            role="scheduler",
            bundle_id=_bundle("sniping-scheduler"),
            # Pass config explicitly so create receives a reviewable scheduler and
            # sniping-scheduler input in sniping request.
            config={
                "phase_table": "canonical-v1",
                "synthetic_boundary_merge": "historical-synthetic-two-way-merge-v1",
            },
        ),
        # Complete the components group only after its semantic components are visible.
    )
    return CompileDeliveryScheduleRequest(
        replay_pack_id=replay_pack.replay_pack_id,
        replay_semantics_id=replay_pack.manifest.semantics.replay_semantics_id,
        replay_layout_schema_id=replay_pack.manifest.layout.replay_layout_schema_id,
        # Pass components explicitly so CompileDeliveryScheduleRequest receives a
        # reviewable replay pack id and replay semantics id input in sniping request.
        components=components,
        rng_algorithm=RNG_ALGORITHM,
        root_seed=42,
        compiler_version=delivery_physical.COMPILER_VERSION,
    )


# Define resolved spec for delivery as one focused operation with an explicit boundary.
def _resolved_spec_for_delivery(
    replay_pack: CompiledReplayPack,
    compiled: CompiledDeliverySchedule,
) -> ResolvedRunSpec:
    # Execute the resolved spec for delivery workflow in explicit, reviewable steps.
    extra_components = (
        ResolvedComponent.create(
            role="execution",
            bundle_id=_bundle("execution"),
            config={"mode": "SHADOW_STATE_REPLAY"},
            # Complete create only after its execution and mode inputs are visible in resolved
            # spec for delivery.
        ),
        ResolvedComponent.create(
            role="inference",
            bundle_id=_bundle("inference"),
            config=ExactInferencePolicy.disabled().document(),
            # Complete create only after its inference and document inputs are visible in
            # resolved spec for delivery.
        ),
        ResolvedComponent.create(
            role="protocol:reference",
            bundle_id=_bundle("protocol"),
            config={"version": 1},
            # Complete create only after its protocol:reference and protocol inputs are
            # visible in resolved spec for delivery.
        ),
        ResolvedComponent.create(
            role="risk",
            bundle_id=_bundle("risk"),
            config={"version": 1},
            # Complete create only after its risk and version inputs are visible in resolved
            # spec for delivery.
        ),
        ResolvedComponent.create(
            role="strategy",
            bundle_id=_bundle("strategy"),
            config={"version": 1},
            # Complete create only after its strategy and version inputs are visible in
            # resolved spec for delivery.
        ),
        ResolvedComponent.create(
            role="universe",
            bundle_id=_bundle("universe"),
            config={"version": 1},
            # Complete create only after its universe and version inputs are visible in
            # resolved spec for delivery.
        ),
        ResolvedComponent.create(
            role="valuation:price_source",
            bundle_id=_bundle("valuation"),
            config={"version": 1},
            # Complete create only after its valuation:price source and valuation inputs are
            # visible in resolved spec for delivery.
        ),
    )
    manifest = replay_pack.manifest
    return ResolvedRunSpec.create(
        network_id=SOLANA_MAINNET_NETWORK_ID,
        # Pass position schema id explicitly so create receives a reviewable 9 and sol
        # input in resolved spec for delivery.
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        dataset_revision_id=manifest.dataset_revision_id,
        logical_content_hash=manifest.logical_content_hash,
        snapshot_id=manifest.snapshot_id,
        replay_semantics_id=manifest.semantics.replay_semantics_id,
        # Include replay input in the completed resolved spec for delivery result.
        replay_input=ResolvedReplayInput(
            ReplayInputFormat.REPLAY_PACK,
            manifest.layout.replay_layout_schema_id,
            replay_pack.replay_pack_id,
        ),
        # Pass components explicitly so create receives a reviewable 9 and sol input in
        # resolved spec for delivery.
        components=compiled.requested_build.components + extra_components,
        runtime_lock_id=RuntimeLockId("9" * 64),
        initial_portfolio=(AssetBalance(AssetId("SOL"), 1_000),),
        root_seed=compiled.requested_build.root_seed,
    )


# Define dynamic deliveries as one focused operation with an explicit boundary.
def _dynamic_deliveries(
    events: tuple[CanonicalEvent, ...],
    boundaries: tuple[ReplayBoundary, ...],
    *,
    observation_slots: int,
    # Keep the tuple input explicit in the dynamic deliveries contract.
) -> tuple[ScheduledDelivery, ...]:
    # Execute the dynamic deliveries workflow in explicit, reviewable steps.
    slots = tuple(item.slot for item in boundaries)
    ordinals = tuple(item.boundary_ordinal for item in boundaries)
    index_by_ordinal = {
        boundary.boundary_ordinal: index for index, boundary in enumerate(boundaries)
    }
    # Assemble scheduler once so the dynamic deliveries workflow shares one value.
    scheduler: CausalScheduler[int] = CausalScheduler()
    for event_row, event in enumerate(events):
        # Process enumerate(events) inside the bounded dynamic deliveries loop.
        source = event.envelope.boundary_ordinal
        source_index = index_by_ordinal[source]
        target_slot = slots[source_index] + observation_slots
        try:
            # Perform the protected dynamic deliveries operation before explicit failure
            # handling.
            release = first_boundary_at_or_after_slot(
                target_slot=target_slot,
                boundary_slots=slots[source_index:],
                boundary_ordinals=ordinals[source_index:],
            )
        # Translate lookup error through the dynamic deliveries boundary without hiding
        # other errors.
        except LookupError:
            continue
        scheduler.enqueue(
            SchedulerKey(
                release,
                # Pass scheduler phase explicitly so SchedulerKey receives a reviewable
                # observation delivery and hex input in dynamic deliveries.
                SchedulerPhase.OBSERVATION_DELIVERY,
                source,
                event.envelope.stable_causal_id.hex,
            ),
            event_row,
            # Complete enqueue only after its observation delivery and hex inputs are visible
            # in dynamic deliveries.
        )
    result: list[ScheduledDelivery] = []
    for boundary in boundaries:
        # Process boundaries inside the bounded dynamic deliveries loop.
        result.extend(
            ScheduledDelivery(key.release_boundary_ordinal, event_row)
            for key, event_row in scheduler.pop_ready(
                boundary.boundary_ordinal,
                through_phase=SchedulerPhase.OBSERVATION_DELIVERY,
                # Complete pop_ready only after its boundary ordinal and observation delivery
                # inputs are visible in dynamic deliveries.
            )
        )
    return tuple(result)


def _publish_snapshot(artifacts: LocalArtifactRepository) -> SnapshotId:
    # Execute the publish snapshot workflow in explicit, reviewable steps.
    writer = artifacts.stage(
        ArtifactDraft(
            kind=ArtifactKind.SNAPSHOT,
            build_key=ContentDigest("a" * 64),
        )
        # Complete stage only after its a and snapshot inputs are visible in publish snapshot.
    )
    committed = writer.commit(canonical_json_bytes(_snapshot_fidelity_manifest()))
    return SnapshotId(committed.artifact_id.hex)


def _snapshot_fidelity_manifest() -> dict[str, object]:
    return fixture_snapshot_manifest()


# Define checked source as one focused operation with an explicit boundary.
def _checked_source(
    requested: SnapshotId,
    expected: SnapshotId,
    events: tuple[CanonicalEvent, ...],
) -> _CanonicalSource:
    # Execute the checked source workflow in explicit, reviewable steps.
    if requested != expected:
        raise AssertionError("compiler requested another snapshot")
    return _CanonicalSource(events)


def _events() -> tuple[CanonicalEvent, ...]:
    # Execute the events workflow in explicit, reviewable steps.
    return (
        _block(slot=100, tx_count=2, identity=10, stable=50),
        _token(
            slot=100,
            transaction_index=0,
            # Pass event index explicitly into _token within events.
            event_index=0,
            group=1,
            event=1,
            stable=900,
        ),
        # Include token in the completed events result.
        _token(
            slot=100,
            transaction_index=0,
            event_index=1,
            group=1,
            # Pass event explicitly into _token within events.
            event=2,
            stable=100,
        ),
        _token(
            slot=100,
            # Pass transaction index explicitly into _token within events.
            transaction_index=1,
            event_index=0,
            group=2,
            event=3,
            stable=500,
            # Complete _token only after its declared inputs are visible in events.
        ),
        _block(slot=102, tx_count=1, identity=11, stable=150),
        _token(
            slot=102,
            transaction_index=0,
            # Pass event index explicitly into _token within events.
            event_index=0,
            group=3,
            event=4,
            stable=200,
        ),
        # Include slot in the completed events result.
        _block(slot=105, tx_count=1, identity=12, stable=250),
        _token(
            slot=105,
            transaction_index=0,
            event_index=0,
            # Pass group explicitly into _token within events.
            group=4,
            event=5,
            stable=300,
        ),
    )


# Define block as one focused operation with an explicit boundary.
def _block(*, slot: int, tx_count: int, identity: int, stable: int) -> BlockEvent:
    # Execute the block workflow in explicit, reviewable steps.
    return BlockEvent(
        envelope=EventEnvelope(
            position=ChainPosition(
                network_id=SOLANA_MAINNET_NETWORK_ID,
                position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
                # Pass block ordinal explicitly so ChainPosition receives a reviewable
                # solana mainnet network id and block32 transaction32 position schema id
                # input in block.
                block_ordinal=slot,
                transaction_index=-1,
                event_index=0,
            ),
            transaction_group_id=_digest(identity),
            # Include source record id in the completed block result.
            source_record_id=_digest(100 + identity),
            canonical_event_id=_digest(200 + identity),
            stable_causal_id=_digest(stable),
            capability_id=FIXTURE_CAPABILITY_ID,
            protocol="fixture",
            # Pass protocol version explicitly so EventEnvelope receives a reviewable
            # fixture and 1 input in block.
            protocol_version="1",
            ordering_fidelity=OrderingFidelity.INSTRUCTION_EXACT,
        ),
        block_time_ns=slot * 1_000_000_000,
        tx_count=tx_count,
        # Pass block hash explicitly so BlockEvent receives a reviewable fixture and 1
        # input in block.
        block_hash=None,
    )


def _token(
    *,
    slot: int,
    # Keep the transaction index input explicit in the token contract.
    transaction_index: int,
    event_index: int,
    group: int,
    event: int,
    stable: int,
    # Keep the token creation event input explicit in the token contract.
) -> TokenCreationEvent:
    # Execute the token workflow in explicit, reviewable steps.
    return TokenCreationEvent(
        envelope=EventEnvelope(
            position=ChainPosition(
                network_id=SOLANA_MAINNET_NETWORK_ID,
                position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
                # Pass block ordinal explicitly so ChainPosition receives a reviewable
                # solana mainnet network id and block32 transaction32 position schema id
                # input in token.
                block_ordinal=slot,
                transaction_index=transaction_index,
                event_index=event_index,
            ),
            transaction_group_id=_digest(group),
            # Include source record id in the completed token result.
            source_record_id=_digest(100 + event),
            canonical_event_id=_digest(200 + event),
            stable_causal_id=_digest(stable),
            capability_id=FIXTURE_CAPABILITY_ID,
            protocol="fixture",
            # Pass protocol version explicitly so EventEnvelope receives a reviewable
            # fixture and 1 input in token.
            protocol_version="1",
            ordering_fidelity=OrderingFidelity.INSTRUCTION_EXACT,
        ),
        asset_id=AssetId(f"TOKEN-{event}"),
        developer_id=AccountId("creator"),
        # Include creation user id in the completed token result.
        creation_user_id=AccountId("creator"),
        venue_id=VenueId(f"launch:TOKEN-{event}"),
        quote_asset_id=AssetId("SOL"),
        protocol_payload_schema=ProtocolPayloadSchemaId("reference-token-launch-payload-v1"),
        protocol_payload=b"",
        # Pass decimals explicitly so TokenCreationEvent receives a reviewable fixture and
        # 1 input in token.
        decimals=6,
    )


def _boundaries(events: tuple[CanonicalEvent, ...]) -> tuple[ReplayBoundary, ...]:
    # Execute the boundaries workflow in explicit, reviewable steps.
    result: list[ReplayBoundary] = []
    previous: int | None = None
    for event in events:
        # Process events inside the bounded boundaries loop.
        ordinal = event.envelope.boundary_ordinal
        if ordinal != previous:
            # Handle the boundaries ordinal != previous branch as a distinct logical
            # block.
            result.append(ReplayBoundary.from_position(event.envelope.position))
            previous = ordinal
    return tuple(result)


def _bundle(label: str) -> BundleId:
    return BundleId(domain_digest("fixture.bundle.v1", {"label": label}).hex)


# Define digest as one focused operation with an explicit boundary.
def _digest(value: int) -> ContentDigest:
    return ContentDigest(f"{value:064x}")


def _replace_first(value: np.ndarray, replacement: int) -> np.ndarray:
    # Execute the replace first workflow in explicit, reviewable steps.
    result = value.copy()
    result[0] = replacement
    return result


def _republish_with_array(
    artifacts: LocalArtifactRepository,
    # Keep the schedule id input explicit in the republish with array contract.
    schedule_id: DeliveryScheduleId,
    target_path: str,
    mutate: Callable[[np.ndarray], np.ndarray],
) -> DeliveryScheduleId:
    # Execute the republish with array workflow in explicit, reviewable steps.
    handle = artifacts.open_committed(schedule_id)
    try:
        # Perform the protected republish with array operation before explicit failure
        # handling.
        with handle.open_binary("manifest.json") as stream:
            manifest_bytes = stream.read()
        with handle.open_binary("manifest.identity.json") as stream:
            identity_bytes = stream.read()
        manifest = DeliveryScheduleManifest.from_document(json.loads(manifest_bytes))
        # Assemble payloads once so the republish with array workflow shares one value.
        payloads: dict[str, bytes] = {}
        for descriptor in manifest.layout.arrays:
            # Process manifest.layout.arrays inside the bounded republish with array loop.
            with handle.open_binary(descriptor.path) as stream:
                payloads[descriptor.path] = stream.read()
    finally:
        handle.close()

    writer = artifacts.stage(
        # Keep the artifact draft and delivery schedule ArtifactDraft step visible while
        # building writer.
        ArtifactDraft(
            kind=ArtifactKind.DELIVERY_SCHEDULE,
            build_key=manifest.build.delivery_build_key,
            input_artifact_ids=(ReplayPackId(manifest.replay_pack_id.hex),),
        )
        # Complete stage only after its delivery schedule and delivery build key inputs are
        # visible in republish with array.
    )
    try:
        # Perform the protected republish with array operation before explicit failure
        # handling.
        for descriptor in manifest.layout.arrays:
            # Process manifest.layout.arrays inside the bounded republish with array loop.
            with writer.open_binary(descriptor.path) as destination:
                # Keep open binary, path and writer active only for the bounded republish
                # with array operation.
                if descriptor.path == target_path:
                    # Handle the republish with array descriptor.path == target_path
                    # branch as a distinct logical block.
                    original = np.load(
                        io.BytesIO(payloads[descriptor.path]),
                        allow_pickle=False,
                    )
                    np.save(destination, mutate(original), allow_pickle=False)
                # Route all remaining cases through the explicit alternative branch.
                else:
                    # Handle the republish with array complement of descriptor.path ==
                    # target_path explicitly.
                    shutil.copyfileobj(
                        io.BytesIO(payloads[descriptor.path]),
                        destination,
                    )
        committed = writer.commit(
            # Pass manifest bytes explicitly so commit receives a reviewable manifest
            # bytes and identity bytes input in republish with array.
            manifest_bytes,
            identity_manifest_bytes=identity_bytes,
        )
    except BaseException:
        # Translate the BaseException failure through the republish with array boundary.
        writer.abort()
        raise
    return DeliveryScheduleId(committed.artifact_id.hex)
