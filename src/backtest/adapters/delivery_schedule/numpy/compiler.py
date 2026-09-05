"""Bounded deterministic compiler for materialized observation deliveries."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Mapping

# Import dataclasses at the visible module dependency boundary.
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
import numpy.typing as npt

# Import repository at the visible module dependency boundary.
from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.adapters.columnar.numpy import layout as replay_physical
from backtest.adapters.columnar.numpy.compiler import unit_replay_build_tools
from backtest.adapters.columnar.numpy.reader import NumpyMmapReplaySource
from backtest.adapters.delivery_schedule.numpy import layout as physical

# Import policy at the visible module dependency boundary.
from backtest.adapters.delivery_schedule.numpy.policy import (
    DeliveryObservationPolicyError,
    resolve_observation_policy,
)
from backtest.application.build_tool_roles import (
    # Include delivery compiler role so the build tool roles dependency remains explicit.
    DELIVERY_COMPILER_ROLE,
    DELIVERY_WRITER_ROLE,
)
from backtest.application.code_bundles import (
    PinnedCodeBundleIdentity,
    # Include pinned code bundle set so the code bundles dependency remains explicit.
    PinnedCodeBundleSet,
)
from backtest.application.delivery_schedules import (
    CompiledDeliverySchedule,
    CompileDeliveryScheduleRequest,
    # Include delivery build manifest so the delivery schedules dependency remains
    # explicit.
    DeliveryBuildManifest,
    DeliveryScheduleManifest,
    DeliveryStreamHasher,
    ScheduledDelivery,
)

# Import models at the visible module dependency boundary.
from backtest.application.models import ArtifactDraft, ArtifactKind
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.domain.identifiers import (
    BundleId,
    ContentDigest,
    # Include delivery schedule id so the identifiers dependency remains explicit.
    DeliveryScheduleId,
    RuntimeLockId,
)
from backtest.engine.rng import RNG_ALGORITHM, KeyedRng
from backtest.engine.scheduler import SchedulerPhase

# Bind uint64 max once as an explicit module-level contract.
UINT64_MAX: Final = (1 << 64) - 1

DELIVERY_COMPILER_BUNDLE_ID: Final = BundleId(
    domain_digest(
        "backtest.numpy-delivery-compiler-bundle.v1",
        {
            # Keep compiler version named so the v1 and compiler version payload passed to
            # domain_digest remains self-describing within module.
            "compiler_version": physical.COMPILER_VERSION,
            "observation_policies": [
                "pumpfun-sniping-post-group-observation-v1",
                "slot-latency-v1",
            ],
            # Keep ordering named so the v1 and compiler version payload passed to
            # domain_digest remains self-describing within module.
            "ordering": "release-source-stable-v1",
            "passes": 2,
        },
    ).hex
)
# Bind delivery writer bundle id once as an explicit module-level contract.
DELIVERY_WRITER_BUNDLE_ID: Final = BundleId(
    domain_digest(
        "backtest.numpy-delivery-writer-bundle.v1",
        {
            "container": "numpy-npy-v1",
            # Keep event reference named so the v1 and container payload passed to
            # domain_digest remains self-describing within module.
            "event_reference": "replay-pack-row-index-v1",
            "numeric_byte_order": "little",
        },
    ).hex
)
# Bind delivery writer settings digest once as an explicit module-level contract.
DELIVERY_WRITER_SETTINGS_DIGEST: Final = domain_digest(
    "backtest.numpy-delivery-writer-settings.v1",
    {
        "allow_pickle": False,
        "array_order": "C",
        # Keep event row index dtype named so the v1 and allow pickle payload passed to
        # domain_digest remains self-describing within module.
        "event_row_index_dtype": "<u8",
        "release_boundary_ordinal_dtype": "<u8",
    },
)


class DeliveryScheduleCompileError(RuntimeError):
    """Resolved inputs cannot be compiled without changing scheduler semantics."""


@dataclass(frozen=True, slots=True)
class _ScanSummary:
    input_event_count: int
    delivery_count: int
    outside_horizon_count: int


# Keep the local numpy delivery schedule compiler contract and validation rules together.
class LocalNumpyDeliveryScheduleCompiler:
    """Compile one verified ReplayPack into a strict two-column mmap stream."""

    def __init__(
        self,
        artifacts: LocalArtifactRepository,
        *,
        runtime_lock_id: RuntimeLockId,
        # Keep the maximum group rows input explicit in the init contract.
        maximum_group_rows: int = 65_536,
        compiler_bundle_id: BundleId | None = None,
        writer_bundle_id: BundleId | None = None,
        build_tools: PinnedCodeBundleSet | None = None,
    ) -> None:
        # Execute the local numpy delivery schedule compiler init workflow in explicit,
        # reviewable steps.
        if (
            isinstance(maximum_group_rows, bool)
            or not isinstance(maximum_group_rows, int)
            or maximum_group_rows <= 0
        ):
            # Fail the local numpy delivery schedule compiler init path with ValueError
            # for maximum group rows must be a positive integer when isinstance and
            # maximum group rows is true; do not continue ambiguously.
            raise ValueError("maximum_group_rows must be a positive integer")
        self._artifacts = artifacts
        self._runtime_lock_id = runtime_lock_id
        self._build_tools = build_tools or unit_delivery_build_tools(
            compiler_bundle_id=compiler_bundle_id,
            # Pass writer bundle id explicitly so unit_delivery_build_tools receives a
            # reviewable compiler bundle id and writer bundle id input in local numpy
            # delivery schedule compiler init.
            writer_bundle_id=writer_bundle_id,
        )
        self._compiler_bundle_id = self._build_tools.require_current(DELIVERY_COMPILER_ROLE)
        self._writer_bundle_id = self._build_tools.require_current(DELIVERY_WRITER_ROLE)
        self._maximum_group_rows = maximum_group_rows
        # Assemble self tmp root once so the local numpy delivery schedule compiler init
        # workflow shares one value.
        self._tmp_root = artifacts.data_root / "tmp" / "delivery-schedules"
        self._tmp_root.mkdir(parents=True, exist_ok=True)

    def compile(
        self,
        request: CompileDeliveryScheduleRequest,
        # Keep the compiled delivery schedule input explicit in the compile contract.
    ) -> CompiledDeliverySchedule:
        # Execute the local numpy delivery schedule compiler compile workflow in explicit,
        # reviewable steps.
        self._require_current_tools()
        observation_block_delay = _validate_request(request)
        build = DeliveryBuildManifest(
            replay_pack_id=request.replay_pack_id,
            replay_semantics_id=request.replay_semantics_id,
            # Pass replay layout schema id explicitly so DeliveryBuildManifest receives a
            # reviewable replay pack id and replay semantics id input in local numpy
            # delivery schedule compiler compile.
            replay_layout_schema_id=request.replay_layout_schema_id,
            components=request.components,
            rng_algorithm=request.rng_algorithm,
            root_seed=request.root_seed,
            compiler_bundle_id=self._compiler_bundle_id,
            # Pass compiler version explicitly so DeliveryBuildManifest receives a
            # reviewable replay pack id and replay semantics id input in local numpy
            # delivery schedule compiler compile.
            compiler_version=request.compiler_version,
            writer_bundle_id=self._writer_bundle_id,
            runtime_lock_id=self._runtime_lock_id,
            writer_settings_digest=DELIVERY_WRITER_SETTINGS_DIGEST,
        )
        # Assemble writer once so the local numpy delivery schedule compiler compile
        # workflow shares one value.
        writer = self._artifacts.stage(
            ArtifactDraft(
                kind=ArtifactKind.DELIVERY_SCHEDULE,
                build_key=build.delivery_build_key,
                input_artifact_ids=(request.replay_pack_id,),
                # Complete ArtifactDraft only after its delivery schedule and delivery build
                # key inputs are visible in local numpy delivery schedule compiler compile.
            )
        )
        temporary_root: Path | None = None
        try:
            # Perform the protected local numpy delivery schedule compiler compile
            # operation before explicit failure handling.
            temporary_root = Path(tempfile.mkdtemp(prefix="schedule-", dir=self._tmp_root))
            with NumpyMmapReplaySource(
                self._artifacts,
                request.replay_pack_id,
                build_tools=self._build_tools,
                # Complete NumpyMmapReplaySource only after its artifacts and replay pack id
                # inputs are visible in local numpy delivery schedule compiler compile.
            ) as replay:
                # Keep numpy mmap replay source, artifacts and replay pack id active only
                # for the bounded local numpy delivery schedule compiler compile
                # operation.
                _validate_replay_contract(replay, request)
                arrays = replay.arrays()
                summary = _scan_groups(
                    arrays,
                    observation_blocks=observation_block_delay,
                    # Pass maximum group rows explicitly so _scan_groups receives a
                    # reviewable maximum group rows and arrays input in local numpy
                    # delivery schedule compiler compile.
                    maximum_group_rows=self._maximum_group_rows,
                )
                layout = physical.build_layout(summary.delivery_count)
                logical_hash = _materialize_arrays(
                    temporary_root,
                    # Pass arrays explicitly so _materialize_arrays receives a reviewable
                    # maximum group rows and temporary root input in local numpy delivery
                    # schedule compiler compile.
                    arrays,
                    summary,
                    observation_blocks=observation_block_delay,
                    maximum_group_rows=self._maximum_group_rows,
                )
                # Assemble manifest once so the local numpy delivery schedule compiler
                # compile workflow shares one value.
                manifest = DeliveryScheduleManifest(
                    replay_pack_id=request.replay_pack_id,
                    replay_semantics_id=request.replay_semantics_id,
                    replay_layout_schema_id=request.replay_layout_schema_id,
                    network_id=replay.network_id,
                    # Pass position schema id explicitly so DeliveryScheduleManifest
                    # receives a reviewable replay pack id and replay semantics id input
                    # in local numpy delivery schedule compiler compile.
                    position_schema_id=replay.position_schema_id,
                    decision_range=replay.decision_range,
                    logical_delivery_stream_hash=logical_hash,
                    input_event_count=summary.input_event_count,
                    delivery_count=summary.delivery_count,
                    # Pass outside horizon count explicitly so DeliveryScheduleManifest
                    # receives a reviewable replay pack id and replay semantics id input
                    # in local numpy delivery schedule compiler compile.
                    outside_horizon_count=summary.outside_horizon_count,
                    layout=layout,
                    build=build,
                    observation_phase=int(SchedulerPhase.OBSERVATION_DELIVERY),
                )
                # Traverse manifest.layout.arrays explicitly so each local numpy delivery
                # schedule compiler compile iteration remains traceable.
                for descriptor in manifest.layout.arrays:
                    # Process manifest.layout.arrays inside the bounded local numpy
                    # delivery schedule compiler compile loop.
                    with (
                        (temporary_root / descriptor.path).open("rb") as source,
                        writer.open_binary(descriptor.path) as destination,
                    ):
                        shutil.copyfileobj(source, destination, length=1024 * 1024)
                # Assemble committed once so the local numpy delivery schedule compiler
                # compile workflow shares one value.
                committed = writer.commit(
                    canonical_json_bytes(manifest.document()),
                    identity_manifest_bytes=canonical_json_bytes(manifest.identity_document()),
                )
        except BaseException:
            # Translate the BaseException failure through the local numpy delivery
            # schedule compiler compile boundary.
            writer.abort()
            raise
        finally:
            # Handle the cleanup path after the protected local numpy delivery schedule
            # compiler compile operation.
            if temporary_root is not None:
                shutil.rmtree(temporary_root, ignore_errors=True)
        schedule_id = DeliveryScheduleId(committed.artifact_id.hex)
        return CompiledDeliverySchedule(
            artifact=committed,
            # Pass delivery schedule id explicitly so CompiledDeliverySchedule receives a
            # reviewable read committed manifest and committed input in local numpy
            # delivery schedule compiler compile.
            delivery_schedule_id=schedule_id,
            manifest=self._read_committed_manifest(schedule_id),
            requested_build=build,
        )

    def _read_committed_manifest(
        # Keep the remaining read committed manifest inputs visible at the local numpy
        # delivery schedule compiler read committed manifest boundary.
        self,
        schedule_id: DeliveryScheduleId,
    ) -> DeliveryScheduleManifest:
        # Execute the local numpy delivery schedule compiler read committed manifest
        # workflow in explicit, reviewable steps.
        handle = self._artifacts.open_committed(schedule_id)
        try:
            # Perform the protected local numpy delivery schedule compiler read committed
            # manifest operation before explicit failure handling.
            with handle.open_binary("manifest.json") as stream:
                value = json.loads(stream.read())
        finally:
            handle.close()
        try:
            # Return the completed local numpy delivery schedule compiler read committed
            # manifest result without a hidden fallback.
            return DeliveryScheduleManifest.from_document(value)
        except (TypeError, ValueError) as error:  # pragma: no cover - compiler authored it
            raise DeliveryScheduleCompileError(
                "committed DeliverySchedule manifest is invalid"
            ) from error

    def _require_current_tools(self) -> None:
        # Execute the local numpy delivery schedule compiler require current tools
        # workflow in explicit, reviewable steps.
        if (
            self._build_tools.require_current(DELIVERY_COMPILER_ROLE) != self._compiler_bundle_id
            or self._build_tools.require_current(DELIVERY_WRITER_ROLE) != self._writer_bundle_id
        ):
            raise DeliveryScheduleCompileError("DeliverySchedule build tool identity changed")


# Define unit delivery build tools as one focused operation with an explicit boundary.
def unit_delivery_build_tools(
    *,
    compiler_bundle_id: BundleId | None = None,
    writer_bundle_id: BundleId | None = None,
) -> PinnedCodeBundleSet:
    """Return fixed identities only for isolated adapter tests."""

    identities = [*unit_replay_build_tools().identities]
    identities.extend(
        (
            PinnedCodeBundleIdentity.for_unit_tests(
                DELIVERY_COMPILER_ROLE,
                # Pass delivery compiler bundle id explicitly so for_unit_tests receives a
                # reviewable delivery compiler role and delivery compiler bundle id input
                # in unit delivery build tools.
                DELIVERY_COMPILER_BUNDLE_ID if compiler_bundle_id is None else compiler_bundle_id,
            ),
            PinnedCodeBundleIdentity.for_unit_tests(
                DELIVERY_WRITER_ROLE,
                DELIVERY_WRITER_BUNDLE_ID if writer_bundle_id is None else writer_bundle_id,
                # Complete for_unit_tests only after its delivery writer role and delivery
                # writer bundle id inputs are visible in unit delivery build tools.
            ),
        )
    )
    return PinnedCodeBundleSet(tuple(sorted(identities, key=lambda item: item.role)))


def _validate_request(request: CompileDeliveryScheduleRequest) -> int:
    # Execute the validate request workflow in explicit, reviewable steps.
    if request.compiler_version != physical.COMPILER_VERSION:
        # Handle the validate request compiler version, request and physical condition as
        # a distinct block.
        raise DeliveryScheduleCompileError(
            f"compiler version must be {physical.COMPILER_VERSION!r}"
        )
    if request.rng_algorithm != RNG_ALGORITHM:
        raise DeliveryScheduleCompileError(f"RNG algorithm must be {RNG_ALGORITHM!r}")
    # Invoke KeyedRng for root seed and request as a visible validate request step.
    KeyedRng(request.root_seed)
    if any(component.api_version != 1 for component in request.components):
        raise DeliveryScheduleCompileError("delivery component API version is unsupported")
    try:
        policy = resolve_observation_policy(request.components)
    # Translate delivery observation policy error through the validate request boundary
    # without hiding other errors.
    except DeliveryObservationPolicyError as error:
        raise DeliveryScheduleCompileError(str(error)) from error
    return policy.block_delay


def _validate_replay_contract(
    replay: NumpyMmapReplaySource,
    # Keep the request input explicit in the validate replay contract contract.
    request: CompileDeliveryScheduleRequest,
) -> None:
    # Execute the validate replay contract workflow in explicit, reviewable steps.
    if replay.replay_pack_id != request.replay_pack_id:
        raise DeliveryScheduleCompileError("opened ReplayPack identity changed")
    if replay.replay_semantics_id != request.replay_semantics_id:
        raise DeliveryScheduleCompileError("ReplayPack semantics differ from request")
    if replay.replay_layout_schema_id != request.replay_layout_schema_id:
        # Fail the validate replay contract path with DeliveryScheduleCompileError for
        # replay pack layout differs from request when replay layout schema id, replay and
        # request is true; do not continue ambiguously.
        raise DeliveryScheduleCompileError("ReplayPack layout differs from request")


def _scan_groups(
    arrays: Mapping[str, npt.NDArray[np.generic]],
    *,
    observation_blocks: int,
    # Keep the maximum group rows input explicit in the scan groups contract.
    maximum_group_rows: int,
) -> _ScanSummary:
    # Execute the scan groups workflow in explicit, reviewable steps.
    group_offsets = arrays[replay_physical.GROUP_OFFSETS]
    boundary_ordinals = arrays[replay_physical.BOUNDARY_ORDINAL]
    boundary_blocks = arrays[replay_physical.BOUNDARY_BLOCK_ORDINAL]
    source_boundaries = arrays[replay_physical.ENVELOPE_BOUNDARY_ORDINAL]
    event_count = int(source_boundaries.size)
    # Guard this path with event_count > UINT64_MAX before applying effects.
    if event_count > UINT64_MAX:
        raise DeliveryScheduleCompileError("ReplayPack event row index exceeds UInt64")
    if any(
        int(boundary_blocks[index]) > int(boundary_blocks[index + 1])
        for index in range(boundary_blocks.size - 1)
        # Complete any only after its size and int inputs are visible in scan groups.
    ):
        raise DeliveryScheduleCompileError("ReplayPack boundary slots are not monotone")
    if group_offsets.size != boundary_ordinals.size + 1:
        # Handle the scan groups size, group offsets and boundary ordinals condition as a
        # distinct block.
        raise DeliveryScheduleCompileError(
            "ReplayPack must contain exactly one atomic group per boundary"
        )
    delivery_count = 0
    outside_horizon_count = 0
    # Assemble release index once so the scan groups workflow shares one value.
    release_index = 0
    for group_index in range(group_offsets.size - 1):
        # Process range(group_offsets.size - 1) inside the bounded scan groups loop.
        start = int(group_offsets[group_index])
        stop = int(group_offsets[group_index + 1])
        _validate_group(
            source_boundaries,
            boundary_ordinals,
            # Pass group index explicitly so _validate_group receives a reviewable source
            # boundaries and boundary ordinals input in scan groups.
            group_index,
            start,
            stop,
            maximum_group_rows,
        )
        # Assemble release index once so the scan groups workflow shares one value.
        release_index = _next_release_index(
            boundary_blocks,
            group_index,
            observation_blocks,
            release_index,
            # Complete _next_release_index only after its boundary blocks and group index
            # inputs are visible in scan groups.
        )
        if release_index >= boundary_ordinals.size:
            outside_horizon_count += stop - start
        else:
            delivery_count += stop - start
    # Return the completed scan groups result without a hidden fallback.
    return _ScanSummary(event_count, delivery_count, outside_horizon_count)


def _validate_group(
    source_boundaries: npt.NDArray[np.generic],
    boundary_ordinals: npt.NDArray[np.generic],
    group_index: int,
    # Keep the start input explicit in the validate group contract.
    start: int,
    stop: int,
    maximum_group_rows: int,
) -> None:
    # Execute the validate group workflow in explicit, reviewable steps.
    if stop <= start or stop - start > maximum_group_rows:
        # Handle the validate group stop, start and maximum group rows condition as a
        # distinct block.
        raise DeliveryScheduleCompileError(
            "ReplayPack atomic group is empty or exceeds maximum_group_rows"
        )
    source = int(boundary_ordinals[group_index])
    if np.any(source_boundaries[start:stop] != source):
        # Handle the validate group any, np and source condition as a distinct block.
        raise DeliveryScheduleCompileError(
            "ReplayPack group does not match its unique source boundary"
        )


def _next_release_index(
    boundary_blocks: npt.NDArray[np.generic],
    # Keep the source index input explicit in the next release index contract.
    source_index: int,
    observation_blocks: int,
    previous_release_index: int,
) -> int:
    # Execute the next release index workflow in explicit, reviewable steps.
    target_block = int(boundary_blocks[source_index]) + observation_blocks
    candidate = max(source_index, previous_release_index)
    while candidate < boundary_blocks.size and int(boundary_blocks[candidate]) < target_block:
        candidate += 1
    return candidate


# Define materialize arrays as one focused operation with an explicit boundary.
def _materialize_arrays(
    root: Path,
    arrays: Mapping[str, npt.NDArray[np.generic]],
    summary: _ScanSummary,
    *,
    # Keep the observation blocks input explicit in the materialize arrays contract.
    observation_blocks: int,
    maximum_group_rows: int,
) -> ContentDigest:
    # Execute the materialize arrays workflow in explicit, reviewable steps.
    group_offsets = arrays[replay_physical.GROUP_OFFSETS]
    boundary_ordinals = arrays[replay_physical.BOUNDARY_ORDINAL]
    boundary_blocks = arrays[replay_physical.BOUNDARY_BLOCK_ORDINAL]
    source_boundaries = arrays[replay_physical.ENVELOPE_BOUNDARY_ORDINAL]
    stable_ids = arrays[replay_physical.ENVELOPE_STABLE_CAUSAL_ID]
    # Invoke mkdir as a visible step within the materialize arrays workflow.
    root.joinpath("schedule").mkdir(parents=True, exist_ok=True)
    row_indexes = np.lib.format.open_memmap(
        root / physical.EVENT_ROW_INDEX,
        mode="w+",
        dtype=np.dtype("<u8"),
        # Pass shape explicitly so open_memmap receives a reviewable w+ and <u8 input in
        # materialize arrays.
        shape=(summary.delivery_count,),
        fortran_order=False,
    )
    release_ordinals = np.lib.format.open_memmap(
        root / physical.RELEASE_BOUNDARY_ORDINAL,
        # Pass mode explicitly so open_memmap receives a reviewable w+ and <u8 input in
        # materialize arrays.
        mode="w+",
        dtype=np.dtype("<u8"),
        shape=(summary.delivery_count,),
        fortran_order=False,
    )
    # Assemble stream hasher once so the materialize arrays workflow shares one value.
    stream_hasher = DeliveryStreamHasher()
    write_index = 0
    previous_key: tuple[int, int, bytes] | None = None
    release_index = 0
    try:
        # Perform the protected materialize arrays operation before explicit failure
        # handling.
        for group_index in range(group_offsets.size - 1):
            # Process range(group_offsets.size - 1) inside the bounded materialize arrays
            # loop.
            start = int(group_offsets[group_index])
            stop = int(group_offsets[group_index + 1])
            _validate_group(
                source_boundaries,
                boundary_ordinals,
                # Pass group index explicitly so _validate_group receives a reviewable
                # source boundaries and boundary ordinals input in materialize arrays.
                group_index,
                start,
                stop,
                maximum_group_rows,
            )
            # Assemble release index once so the materialize arrays workflow shares one
            # value.
            release_index = _next_release_index(
                boundary_blocks,
                group_index,
                observation_blocks,
                release_index,
                # Complete _next_release_index only after its boundary blocks and group index
                # inputs are visible in materialize arrays.
            )
            if release_index >= boundary_ordinals.size:
                continue
            release = int(boundary_ordinals[release_index])
            source = int(boundary_ordinals[group_index])
            # Assemble ordered rows once so the materialize arrays workflow shares one
            # value.
            ordered_rows = sorted(
                range(start, stop),
                key=lambda row: stable_ids[row].tobytes(),
            )
            for event_row_index in ordered_rows:
                # Process ordered_rows inside the bounded materialize arrays loop.
                stable_raw = stable_ids[event_row_index].tobytes()
                key = (release, source, stable_raw)
                if previous_key is not None and key <= previous_key:
                    # Handle the materialize arrays previous key and key condition as a
                    # distinct block.
                    raise DeliveryScheduleCompileError(
                        "delivery scheduler keys collide or are not strictly ordered"
                    )
                previous_key = key
                row_indexes[write_index] = event_row_index
                # Assemble release ordinals[write index] once so the materialize arrays
                # workflow shares one value.
                release_ordinals[write_index] = release
                stream_hasher.update(
                    ScheduledDelivery(release, event_row_index),
                    source_boundary_ordinal=source,
                    stable_causal_id=ContentDigest(stable_raw.hex()),
                    # Complete update only after its hex and scheduled delivery inputs are
                    # visible in materialize arrays.
                )
                write_index += 1
        if write_index != summary.delivery_count:
            raise DeliveryScheduleCompileError("delivery count changed between passes")
        row_indexes.flush()
        # Invoke flush as a visible step within the materialize arrays workflow.
        release_ordinals.flush()
    finally:
        # Handle the cleanup path after the protected materialize arrays operation.
        del row_indexes
        del release_ordinals
    return stream_hasher.digest()


__all__ = [
    "DELIVERY_COMPILER_BUNDLE_ID",
    # Keep the delivery writer bundle id component named inside the all contract.
    "DELIVERY_WRITER_BUNDLE_ID",
    "DELIVERY_WRITER_SETTINGS_DIGEST",
    "DeliveryScheduleCompileError",
    "LocalNumpyDeliveryScheduleCompiler",
    "unit_delivery_build_tools",
    # Complete the all group only after its semantic components are visible.
]
