"""Allowlisted, bounded reference row builders for the Phase-6 vertical slice.

These builders are deliberately declarative.  Queue payloads can select only
the exact bundle/config/spec IDs exported here; they can never name a Python
callable, module or filesystem path.  Every iterator streams over verified
read-only mmap inputs and therefore keeps memory bounded by the publishers'
external spill policy.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import ExitStack
from typing import Final

import numpy as np

# Import typing at the visible module dependency boundary.
import numpy.typing as npt

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.adapters.columnar.numpy import layout as replay_physical
from backtest.adapters.columnar.numpy.reader import NumpyMmapReplaySource
from backtest.adapters.ml.numpy.reader import NumpyFeatureSetProvider, NumpyUniverseReader

# Import toolchain at the visible module dependency boundary.
from backtest.adapters.ml.numpy.toolchain import (
    UNIT_FEATURE_BUILDER_BUNDLE_ID,
    UNIT_LABEL_BUILDER_BUNDLE_ID,
    UNIT_UNIVERSE_BUILDER_BUNDLE_ID,
    unit_ml_build_tools,
    # Close the toolchain import after its required symbols are visible.
)
from backtest.application.build_tool_roles import (
    ML_FEATURE_BUILDER_ROLE,
    ML_LABEL_BUILDER_ROLE,
    ML_UNIVERSE_BUILDER_ROLE,
    # Close the build tool roles import after its required symbols are visible.
)
from backtest.application.code_bundles import PinnedCodeBundleSet
from backtest.application.ml_artifacts import (
    FeatureOverlayRow,
    LabelOverlayRow,
    # Include universe membership row so the ml artifacts dependency remains explicit.
    UniverseMembershipRow,
)
from backtest.application.ml_contracts import FeatureSpec, NullPolicy
from backtest.application.ml_job_commands import (
    ResolvedBuildFeaturesJob,
    # Include resolved build labels job so the ml job commands dependency remains
    # explicit.
    ResolvedBuildLabelsJob,
    ResolvedBuildUniverseJob,
)
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import ArtifactId, BundleId, RuntimeLockId

# Bind reference feature builder bundle id once as an explicit module-level contract.
REFERENCE_FEATURE_BUILDER_BUNDLE_ID: Final = BundleId(UNIT_FEATURE_BUILDER_BUNDLE_ID.hex)
REFERENCE_ALL_ROWS_UNIVERSE_BUNDLE_ID: Final = BundleId(UNIT_UNIVERSE_BUILDER_BUNDLE_ID.hex)
REFERENCE_ALL_ROWS_UNIVERSE_SPEC_ID: Final = domain_digest(
    "backtest.reference-universe-spec.v1",
    {"entity": "replay_row_id", "membership": "one-boundary-at-feature-availability"},
    # Complete domain_digest only after its v1 and entity inputs are visible in module.
)
REFERENCE_ALL_ROWS_UNIVERSE_CONFIG_DIGEST: Final = domain_digest(
    "backtest.reference-universe-builder-config.v1", {}
)
REFERENCE_HORIZON_LABEL_BUILDER_BUNDLE_ID: Final = BundleId(UNIT_LABEL_BUILDER_BUNDLE_ID.hex)
# Bind reference horizon label spec id once as an explicit module-level contract.
REFERENCE_HORIZON_LABEL_SPEC_ID: Final = domain_digest(
    "backtest.reference-label-spec.v1",
    {"target": "eligible_until-minus-eligible_from", "unit": "boundary"},
)
REFERENCE_HORIZON_LABEL_CONFIG_DIGEST: Final = domain_digest(
    # Pass version tag explicitly so domain_digest receives a reviewable v1 input in
    # module.
    "backtest.reference-label-builder-config.v1",
    {},
)

_EFFECTIVE_TIME_SEMANTICS: Final = "replay-event-boundary-v1"
_AVAILABLE_TIME_SEMANTICS: Final = "event-boundary-plus-warmup-v1"
# Bind int64 max once as an explicit module-level contract.
_INT64_MAX: Final = (1 << 63) - 1
# Bind uint64 max once as an explicit module-level contract.
_UINT64_MAX: Final = (1 << 64) - 1

_FEATURE_ARRAYS: Final[dict[str, tuple[str, str | None]]] = {
    "event_boundary_ordinal": (replay_physical.ENVELOPE_BOUNDARY_ORDINAL, None),
    "event_index": (
        replay_physical.ENVELOPE_EVENT_INDEX,
        # Keep the replay physical component named inside the feature arrays contract.
        replay_physical.ENVELOPE_EVENT_INDEX_VALID,
    ),
    "event_kind_code": (replay_physical.ENVELOPE_EVENT_KIND_CODE, None),
    "event_slot": (replay_physical.ENVELOPE_SLOT, None),
    "source_boundary_ordinal": (replay_physical.ENVELOPE_BOUNDARY_ORDINAL, None),
    # Keep the transaction index component named inside the feature arrays contract.
    "transaction_index": (replay_physical.ENVELOPE_TRANSACTION_INDEX, None),
}
REFERENCE_FEATURE_NAMES: Final = tuple(sorted(_FEATURE_ARRAYS))


class ReferenceMlBuilderError(RuntimeError):
    """A resolved job did not select the installed exact reference builder."""


class LocalReferenceMlRowBuilders:
    """Produce deterministic feature/universe/label rows from committed inputs."""

    def __init__(
        self,
        artifacts: LocalArtifactRepository,
        *,
        runtime_lock_id: RuntimeLockId,
        # Keep the build tools input explicit in the init contract.
        build_tools: PinnedCodeBundleSet | None = None,
    ) -> None:
        # Execute the local reference ml row builders init workflow in explicit,
        # reviewable steps.
        self._artifacts = artifacts
        self._runtime_lock_id = runtime_lock_id
        self._build_tools = build_tools or unit_ml_build_tools()
        self._feature_builder_bundle_id = self._build_tools.require_current(ML_FEATURE_BUILDER_ROLE)
        self._universe_builder_bundle_id = self._build_tools.require_current(
            # Pass ml universe builder role explicitly so require_current receives a
            # reviewable ml universe builder role input in local reference ml row builders
            # init.
            ML_UNIVERSE_BUILDER_ROLE
        )
        self._label_builder_bundle_id = self._build_tools.require_current(ML_LABEL_BUILDER_ROLE)

    def feature_rows(
        self,
        # Keep the command input explicit in the feature rows contract.
        command: ResolvedBuildFeaturesJob,
    ) -> Iterator[FeatureOverlayRow]:
        # Execute the local reference ml row builders feature rows workflow in explicit,
        # reviewable steps.
        self._require_current(ML_FEATURE_BUILDER_ROLE, self._feature_builder_bundle_id)
        self._validate_feature_specs(command.feature_specs)
        if command.input_feature_set_ids:
            # Handle the local reference ml row builders feature rows
            # command.input_feature_set_ids branch as a distinct logical block.
            raise ReferenceMlBuilderError(
                "reference feature builder v1 does not accept derived FeatureSet inputs"
            )
        with NumpyMmapReplaySource(
            self._artifacts,
            # Pass command explicitly so NumpyMmapReplaySource receives a reviewable
            # artifacts and replay pack id input in local reference ml row builders
            # feature rows.
            command.replay_pack_id,
            build_tools=self._build_tools,
        ) as replay:
            # Keep numpy mmap replay source, artifacts and replay pack id active only for
            # the bounded local reference ml row builders feature rows operation.
            if replay.replay_semantics_id != command.replay_semantics_id:
                raise ReferenceMlBuilderError("feature job ReplayPack semantics changed")
            if replay.replay_layout_schema_id != command.replay_layout_schema_id:
                raise ReferenceMlBuilderError("feature job ReplayPack layout changed")
            arrays = replay.arrays()
            # Assemble effective once so the local reference ml row builders feature rows
            # workflow shares one value.
            effective = arrays[replay_physical.ENVELOPE_BOUNDARY_ORDINAL]
            for row_id in range(replay.manifest.event_count):
                # Process range(replay.manifest.event_count) inside the bounded local
                # reference ml row builders feature rows loop.
                boundary = int(effective[row_id])
                available = max(boundary + spec.warmup_boundaries for spec in command.feature_specs)
                if available > _UINT64_MAX:
                    raise ReferenceMlBuilderError("feature availability overflows uint64")
                yield FeatureOverlayRow(
                    # Pass replay row id explicitly so FeatureOverlayRow receives a
                    # reviewable feature value and feature specs input in local reference
                    # ml row builders feature rows.
                    replay_row_id=row_id,
                    available_boundary_ordinal=available,
                    values=tuple(
                        self._feature_value(spec, arrays, row_id) for spec in command.feature_specs
                    ),
                    # Complete FeatureOverlayRow only after its feature value and feature
                    # specs inputs are visible in local reference ml row builders feature
                    # rows.
                )

    def universe_rows(
        self,
        command: ResolvedBuildUniverseJob,
    ) -> Iterator[UniverseMembershipRow]:
        # Execute the local reference ml row builders universe rows workflow in explicit,
        # reviewable steps.
        self._require_current(ML_UNIVERSE_BUILDER_ROLE, self._universe_builder_bundle_id)
        if command.builder_bundle_id != self._universe_builder_bundle_id:
            raise ReferenceMlBuilderError("universe builder bundle is not installed")
        if command.builder_config_digest != REFERENCE_ALL_ROWS_UNIVERSE_CONFIG_DIGEST:
            raise ReferenceMlBuilderError("universe builder config is unsupported")
        # Evaluate the complete local reference ml row builders universe rows universe
        # spec id, reference all rows universe spec id and command condition before
        # guarded effects.
        if command.universe_spec_id != REFERENCE_ALL_ROWS_UNIVERSE_SPEC_ID:
            raise ReferenceMlBuilderError("universe specification is unsupported")
        if not command.input_feature_set_ids:
            raise ReferenceMlBuilderError("reference universe requires a FeatureSet input")
        with ExitStack() as stack:
            # Keep exit stack active only for the bounded local reference ml row builders
            # universe rows operation.
            features = tuple(
                stack.enter_context(
                    NumpyFeatureSetProvider(
                        self._artifacts,
                        feature_id,
                        # Pass build tools explicitly so NumpyFeatureSetProvider receives
                        # a reviewable artifacts and build tools input in local reference
                        # ml row builders universe rows.
                        build_tools=self._build_tools,
                    )
                )
                for feature_id in command.input_feature_set_ids
            )
            # Assemble first once so the local reference ml row builders universe rows
            # workflow shares one value.
            first = features[0]
            if any(feature.snapshot_id != command.snapshot_id for feature in features):
                raise ReferenceMlBuilderError("universe inputs belong to another snapshot")
            if any(
                feature.replay_pack_id != first.replay_pack_id
                # Pass feature explicitly so any receives a reviewable replay pack id and
                # row count input in local reference ml row builders universe rows.
                or feature.manifest.row_count != first.manifest.row_count
                for feature in features
            ):
                raise ReferenceMlBuilderError("universe FeatureSets are not row-aligned")
            for row_id in range(first.manifest.row_count):
                # Process range(first.manifest.row_count) inside the bounded local
                # reference ml row builders universe rows loop.
                available = max(feature.available_boundary_for_row(row_id) for feature in features)
                if available >= _UINT64_MAX:
                    raise ReferenceMlBuilderError("universe interval overflows uint64")
                yield UniverseMembershipRow(
                    entity_id=row_id,
                    # Pass eligible from explicitly so UniverseMembershipRow receives a
                    # reviewable row id and available input in local reference ml row
                    # builders universe rows.
                    eligible_from=available,
                    eligible_until=available + 1,
                    input_available_boundary=available,
                )

    def label_rows(
        # Keep the remaining label rows inputs visible at the local reference ml row
        # builders label rows boundary.
        self,
        command: ResolvedBuildLabelsJob,
    ) -> Iterator[LabelOverlayRow]:
        # Execute the local reference ml row builders label rows workflow in explicit,
        # reviewable steps.
        self._require_current(ML_LABEL_BUILDER_ROLE, self._label_builder_bundle_id)
        if command.label_builder_bundle_id != self._label_builder_bundle_id:
            raise ReferenceMlBuilderError("label builder bundle is not installed")
        if command.label_config_digest != REFERENCE_HORIZON_LABEL_CONFIG_DIGEST:
            raise ReferenceMlBuilderError("label builder config is unsupported")
        # Evaluate the complete local reference ml row builders label rows label spec id,
        # reference horizon label spec id and command condition before guarded effects.
        if command.label_spec_id != REFERENCE_HORIZON_LABEL_SPEC_ID:
            raise ReferenceMlBuilderError("label specification is unsupported")
        with NumpyUniverseReader(
            self._artifacts,
            ArtifactId(command.universe_id.hex),
            # Pass build tools explicitly so NumpyUniverseReader receives a reviewable
            # artifacts and hex input in local reference ml row builders label rows.
            build_tools=self._build_tools,
        ) as universe:
            # Keep numpy universe reader, artifacts and artifact id active only for the
            # bounded local reference ml row builders label rows operation.
            if universe.snapshot_id != command.snapshot_id:
                raise ReferenceMlBuilderError("label universe belongs to another snapshot")
            for membership in universe.memberships_for_offline_builder():
                # Process memberships for offline builder and universe inside the bounded
                # local reference ml row builders label rows loop.
                if membership.eligible_until > command.training_cutoff:
                    continue
                yield LabelOverlayRow(
                    replay_row_id=membership.entity_id,
                    effective_boundary_ordinal=membership.eligible_from,
                    # Pass future boundary used explicitly so LabelOverlayRow receives a
                    # reviewable entity id and eligible from input in local reference ml
                    # row builders label rows.
                    future_boundary_used=membership.eligible_until,
                    value=membership.eligible_until - membership.eligible_from,
                )

    def _validate_feature_specs(self, specs: tuple[FeatureSpec, ...]) -> None:
        # Execute the local reference ml row builders validate feature specs workflow in
        # explicit, reviewable steps.
        for spec in specs:
            # Process specs inside the bounded local reference ml row builders validate
            # feature specs loop.
            expected = _FEATURE_ARRAYS.get(spec.name)
            if expected is None:
                raise ReferenceMlBuilderError(f"feature {spec.name!r} is not installed")
            _, validity_name = expected
            if spec.entity_key != "replay_row_id":
                # Fail the local reference ml row builders validate feature specs path
                # with ReferenceMlBuilderError for reference features align to replay row
                # id when entity key, replay row id and spec is true; do not continue
                # ambiguously.
                raise ReferenceMlBuilderError("reference features align to replay_row_id")
            if spec.input_ids:
                raise ReferenceMlBuilderError("reference features have no hidden inputs")
            if spec.effective_time_semantics != _EFFECTIVE_TIME_SEMANTICS:
                raise ReferenceMlBuilderError("feature effective-time semantics are unsupported")
            # Evaluate the complete local reference ml row builders validate feature specs
            # available time semantics and spec condition before guarded effects.
            if spec.available_time_semantics != _AVAILABLE_TIME_SEMANTICS:
                raise ReferenceMlBuilderError("feature availability semantics are unsupported")
            if spec.dtype != "<i8":
                raise ReferenceMlBuilderError("reference features require little-endian int64")
            expected_null = NullPolicy.EXPLICIT_BITMAP if validity_name else NullPolicy.FORBID
            # Guard this path with spec.null_policy is not expected_null before applying
            # effects.
            if spec.null_policy is not expected_null:
                raise ReferenceMlBuilderError("feature null policy differs from its source array")
            if spec.code_bundle_id != self._feature_builder_bundle_id:
                raise ReferenceMlBuilderError("feature code bundle is not installed")
            if spec.runtime_lock_id != self._runtime_lock_id:
                # Fail the local reference ml row builders validate feature specs path
                # with ReferenceMlBuilderError for feature runtime lock differs from this
                # child when runtime lock id and spec is true; do not continue
                # ambiguously.
                raise ReferenceMlBuilderError("feature runtime lock differs from this child")

    def _require_current(self, role: str, expected: BundleId) -> None:
        # Execute the local reference ml row builders require current workflow in
        # explicit, reviewable steps.
        if self._build_tools.require_current(role) != expected:
            raise ReferenceMlBuilderError("reference ML builder identity changed")

    @staticmethod
    def _feature_value(
        spec: FeatureSpec,
        # Keep the arrays input explicit in the feature value contract.
        arrays: Mapping[str, npt.NDArray[np.generic]],
        row_id: int,
    ) -> int | None:
        # Execute the local reference ml row builders feature value workflow in explicit,
        # reviewable steps.
        array_name, validity_name = _FEATURE_ARRAYS[spec.name]
        if validity_name is not None and not _bitmap_valid(arrays[validity_name], row_id):
            return None
        value = int(arrays[array_name][row_id])
        if not -(1 << 63) <= value <= _INT64_MAX:
            # Fail the local reference ml row builders feature value path with
            # ReferenceMlBuilderError for feature value overflows int64 when value and
            # int64 max is true; do not continue ambiguously.
            raise ReferenceMlBuilderError("feature value overflows int64")
        return value


def _bitmap_valid(bitmap: npt.NDArray[np.generic], index: int) -> bool:
    return bool(int(bitmap[index // 8]) & (1 << (index % 8)))


__all__ = [
    # Keep the reference all rows universe bundle id component named inside the all
    # contract.
    "REFERENCE_ALL_ROWS_UNIVERSE_BUNDLE_ID",
    "REFERENCE_ALL_ROWS_UNIVERSE_CONFIG_DIGEST",
    "REFERENCE_ALL_ROWS_UNIVERSE_SPEC_ID",
    "REFERENCE_FEATURE_BUILDER_BUNDLE_ID",
    "REFERENCE_FEATURE_NAMES",
    # Keep the reference horizon label builder bundle id component named inside the all
    # contract.
    "REFERENCE_HORIZON_LABEL_BUILDER_BUNDLE_ID",
    "REFERENCE_HORIZON_LABEL_CONFIG_DIGEST",
    "REFERENCE_HORIZON_LABEL_SPEC_ID",
    "LocalReferenceMlRowBuilders",
    "ReferenceMlBuilderError",
    # Complete the all group only after its semantic components are visible.
]
