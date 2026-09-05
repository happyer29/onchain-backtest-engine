"""Resolve the exact physical replay input declared by ResolvedRunSpec."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.adapters.columnar.arrow import CanonicalParquetReplaySource

# Import canonical at the visible module dependency boundary.
from backtest.adapters.columnar.arrow.canonical import canonical_writer_bundle_id
from backtest.adapters.columnar.numpy import NumpyMmapReplaySource
from backtest.adapters.columnar.numpy.compiler import unit_replay_build_tools
from backtest.application.build_tool_roles import CANONICAL_WRITER_ROLE
from backtest.application.code_bundles import (
    # Include pinned code bundle identity so the code bundles dependency remains explicit.
    PinnedCodeBundleIdentity,
    PinnedCodeBundleSet,
)
from backtest.application.run_specs import ReplayInputFormat, ResolvedRunSpec
from backtest.domain.identifiers import BundleId

# Import replay at the visible module dependency boundary.
from backtest.engine.replay import HistoricalEventSource


# Keep the local replay source factory contract and validation rules together.
class LocalReplaySourceFactory:
    def __init__(
        self,
        artifacts: LocalArtifactRepository,
        *,
        # Keep the parquet memory limit mb input explicit in the init contract.
        parquet_memory_limit_mb: int = 1_024,
        threads: int = 1,
        expected_projector_bundle_id: BundleId | None = None,
        build_tools: PinnedCodeBundleSet | None = None,
    ) -> None:
        # Execute the local replay source factory init workflow in explicit, reviewable
        # steps.
        self._artifacts = artifacts
        self._memory_limit_mb = parquet_memory_limit_mb
        self._threads = threads
        self._expected_projector_bundle_id = expected_projector_bundle_id
        self._build_tools = build_tools or _unit_replay_factory_tools()

    # Apply contextmanager semantics to the following local replay source factory open
    # resolved contract.
    @contextmanager
    def open_resolved(self, spec: ResolvedRunSpec) -> Iterator[HistoricalEventSource]:
        # Execute the local replay source factory open resolved workflow in explicit,
        # reviewable steps.
        if spec.replay_input.format is ReplayInputFormat.CANONICAL_PARQUET:
            # Handle the local replay source factory open resolved format, canonical
            # parquet and replay input condition as a distinct block.
            parquet_source = CanonicalParquetReplaySource(
                self._artifacts,
                spec.snapshot_id,
                duckdb_memory_limit_mb=self._memory_limit_mb,
                threads=self._threads,
                # Pass expected projector bundle id explicitly so
                # CanonicalParquetReplaySource receives a reviewable artifacts and
                # snapshot id input in local replay source factory open resolved.
                expected_projector_bundle_id=self._expected_projector_bundle_id,
                build_tools=self._build_tools,
            )
            yield parquet_source
            return
        # Assemble replay pack id once so the local replay source factory open resolved
        # workflow shares one value.
        replay_pack_id = spec.replay_input.replay_pack_id
        layout_id = spec.replay_input.replay_layout_schema_id
        if replay_pack_id is None or layout_id is None:  # guarded by ResolvedReplayInput
            raise ValueError("ReplayPack input is missing exact physical identities")
        with NumpyMmapReplaySource(
            self._artifacts,
            replay_pack_id,
            build_tools=self._build_tools,
            # Complete NumpyMmapReplaySource only after its artifacts and build tools inputs
            # are visible in local replay source factory open resolved.
        ) as mmap_source:
            # Keep numpy mmap replay source, artifacts and replay pack id active only for
            # the bounded local replay source factory open resolved operation.
            if mmap_source.snapshot_id != spec.snapshot_id:
                raise ValueError("ReplayPack was not derived from the resolved snapshot")
            if mmap_source.replay_layout_schema_id != layout_id:
                raise ValueError("ReplayPack layout differs from ResolvedRunSpec")
            yield mmap_source


# Define unit replay factory tools as one focused operation with an explicit boundary.
def _unit_replay_factory_tools() -> PinnedCodeBundleSet:
    # Execute the unit replay factory tools workflow in explicit, reviewable steps.
    identities = [*unit_replay_build_tools().identities]
    identities.append(
        PinnedCodeBundleIdentity.for_unit_tests(
            CANONICAL_WRITER_ROLE,
            canonical_writer_bundle_id(),
            # Complete for_unit_tests only after its canonical writer bundle id and canonical
            # writer role inputs are visible in unit replay factory tools.
        )
    )
    return PinnedCodeBundleSet(tuple(sorted(identities, key=lambda item: item.role)))


__all__ = ["LocalReplaySourceFactory"]
