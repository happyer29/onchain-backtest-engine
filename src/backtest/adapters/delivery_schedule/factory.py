"""Open and pin the exact materialized observation stream declared by a run."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.adapters.delivery_schedule.numpy.compiler import (
    # Include delivery writer settings digest so the compiler dependency remains explicit.
    DELIVERY_WRITER_SETTINGS_DIGEST,
    unit_delivery_build_tools,
)
from backtest.adapters.delivery_schedule.numpy.layout import COMPILER_VERSION
from backtest.adapters.delivery_schedule.numpy.reader import NumpyMmapDeliverySchedule

# Import build tool roles at the visible module dependency boundary.
from backtest.application.build_tool_roles import (
    DELIVERY_COMPILER_ROLE,
    DELIVERY_WRITER_ROLE,
)
from backtest.application.code_bundles import PinnedCodeBundleSet

# Import delivery schedules at the visible module dependency boundary.
from backtest.application.delivery_schedules import DeliveryBuildManifest
from backtest.application.ports.runs import ResolvedDeliveryScheduleSource
from backtest.application.run_specs import ReplayInputFormat, ResolvedRunSpec
from backtest.engine.rng import RNG_ALGORITHM


class LocalDeliveryScheduleSourceFactory:
    """Resolve one verified schedule and prove its complete derivation contract."""

    def __init__(
        self,
        artifacts: LocalArtifactRepository,
        *,
        build_tools: PinnedCodeBundleSet | None = None,
        # Close the init signature after its explicit inputs.
    ) -> None:
        # Execute the local delivery schedule source factory init workflow in explicit,
        # reviewable steps.
        self._artifacts = artifacts
        self._build_tools = build_tools or unit_delivery_build_tools()

    @contextmanager
    def open_resolved(
        self,
        # Keep the spec input explicit in the open resolved contract.
        spec: ResolvedRunSpec,
    ) -> Iterator[ResolvedDeliveryScheduleSource]:
        # Execute the local delivery schedule source factory open resolved workflow in
        # explicit, reviewable steps.
        schedule_id = spec.delivery_schedule_id
        if schedule_id is None:
            raise ValueError("ResolvedRunSpec does not declare a DeliverySchedule")
        replay_pack_id = spec.replay_input.replay_pack_id
        replay_layout_schema_id = spec.replay_input.replay_layout_schema_id
        # Evaluate the complete local delivery schedule source factory open resolved
        # format, replay pack and replay pack id condition before guarded effects.
        if (
            spec.replay_input.format is not ReplayInputFormat.REPLAY_PACK
            or replay_pack_id is None
            or replay_layout_schema_id is None
        ):
            # Fail the local delivery schedule source factory open resolved path with
            # ValueError for delivery schedule requires one exact replay pack input when
            # format, replay pack and replay pack id is true; do not continue ambiguously.
            raise ValueError("DeliverySchedule requires one exact ReplayPack input")
        expected = DeliveryBuildManifest(
            replay_pack_id=replay_pack_id,
            replay_semantics_id=spec.replay_semantics_id,
            replay_layout_schema_id=replay_layout_schema_id,
            # Keep the component and components tuple step visible while building
            # expected.
            components=tuple(
                component
                for component in spec.components
                if component.role in {"clock", "engine", "latency", "scheduler"}
            ),
            # Pass rng algorithm explicitly so DeliveryBuildManifest receives a reviewable
            # clock and engine input in local delivery schedule source factory open
            # resolved.
            rng_algorithm=RNG_ALGORITHM,
            root_seed=spec.root_seed,
            compiler_bundle_id=self._build_tools.require_current(DELIVERY_COMPILER_ROLE),
            compiler_version=COMPILER_VERSION,
            writer_bundle_id=self._build_tools.require_current(DELIVERY_WRITER_ROLE),
            # Pass runtime lock id explicitly so DeliveryBuildManifest receives a
            # reviewable clock and engine input in local delivery schedule source factory
            # open resolved.
            runtime_lock_id=spec.runtime_lock_id,
            writer_settings_digest=DELIVERY_WRITER_SETTINGS_DIGEST,
        )
        with NumpyMmapDeliverySchedule(
            self._artifacts,
            # Pass schedule id explicitly so NumpyMmapDeliverySchedule receives a
            # reviewable artifacts and build tools input in local delivery schedule source
            # factory open resolved.
            schedule_id,
            build_tools=self._build_tools,
        ) as schedule:
            # Keep numpy mmap delivery schedule, artifacts and schedule id active only for
            # the bounded local delivery schedule source factory open resolved operation.
            schedule.require_build(expected)
            yield schedule


__all__ = ["LocalDeliveryScheduleSourceFactory"]
