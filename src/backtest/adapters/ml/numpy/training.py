"""Training-only mmap access to labels.

This module intentionally exposes no engine causal-scalar method.  A label row
can be requested only through the explicitly named training API, together with
the future boundary that was used to construct it.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from types import TracebackType
from typing import Self

# Import repository at the visible module dependency boundary.
from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.adapters.ml.numpy import layout as physical
from backtest.adapters.ml.numpy.reader import (
    NumpyMlArtifactFormatError,
    _bitmap_valid,
    # Include digest so the reader dependency remains explicit.
    _digest,
    _integer,
    _keys,
    _MappedMlArtifact,
    _optional_integer,
    # Include require logical hash so the reader dependency remains explicit.
    _require_logical_hash,
    _semantic,
    _semantic_build,
    _sorted_artifact_ids,
    _source_bound_expected_bundle_id,
    # Include validate bitmap padding so the reader dependency remains explicit.
    _validate_bitmap_padding,
)
from backtest.application.build_tool_roles import ML_LABEL_BUILDER_ROLE
from backtest.application.code_bundles import PinnedCodeBundleSet
from backtest.application.ml_artifacts import (
    # Include ml artifact manifest so the ml artifacts dependency remains explicit.
    MlArtifactManifest,
    MlArtifactSchema,
    MlLogicalStreamHasher,
)
from backtest.application.models import ArtifactKind

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import LabelSetId, SnapshotId, UniverseId


# Keep the training label row contract and validation rules together.
@dataclass(frozen=True, slots=True)
class TrainingLabelRow:
    replay_row_id: int
    effective_boundary_ordinal: int
    future_boundary_used: int
    # Declare value explicitly in the training label row contract.
    value: int | None


class NumpyLabelSetReader:
    """Read labels only inside training/evaluation pipelines."""

    def __init__(
        self,
        artifacts: LocalArtifactRepository,
        label_set_id: LabelSetId,
        *,
        # Keep the build tools input explicit in the init contract.
        build_tools: PinnedCodeBundleSet | None = None,
    ) -> None:
        # Execute the numpy label set reader init workflow in explicit, reviewable steps.
        self._mapped = _MappedMlArtifact(
            artifacts,
            label_set_id,
            expected_kind=ArtifactKind.LABEL_SET,
            expected_schema=MlArtifactSchema.LABEL_SET,
            # Pass build tools explicitly so _MappedMlArtifact receives a reviewable label
            # set and artifacts input in numpy label set reader init.
            build_tools=build_tools,
        )
        try:
            # Perform the protected numpy label set reader init operation before explicit
            # failure handling.
            semantic = _semantic(self._mapped.manifest)
            _keys(
                semantic,
                {
                    "label_builder_bundle_id",
                    # Pass label config digest explicitly so _keys receives a reviewable
                    # label builder bundle id and label config digest input in numpy label
                    # set reader init.
                    "label_config_digest",
                    "label_spec_id",
                    "maximum_future_boundary_used",
                    "snapshot_id",
                    "training_cutoff",
                    # Pass universe id explicitly so _keys receives a reviewable label
                    # builder bundle id and label config digest input in numpy label set
                    # reader init.
                    "universe_id",
                },
                "LabelSet semantic content",
            )
            expected_label_builder = _source_bound_expected_bundle_id(
                # Pass self explicitly so _source_bound_expected_bundle_id receives a
                # reviewable build tools and mapped input in numpy label set reader init.
                self._mapped.build_tools,
                ML_LABEL_BUILDER_ROLE,
            )
            if (
                expected_label_builder is not None
                # Keep semantic visible while evaluating the expected label builder, hex
                # and semantic guard.
                and semantic["label_builder_bundle_id"] != expected_label_builder.hex
            ):
                raise NumpyMlArtifactFormatError("LabelSet builder bundle is unsupported")
            self._snapshot_id = SnapshotId(_digest(semantic, "snapshot_id"))
            self._universe_id = UniverseId(_digest(semantic, "universe_id"))
            # Assemble expected once so the numpy label set reader init workflow shares
            # one value.
            expected = _sorted_artifact_ids((self._snapshot_id, self._universe_id))
            if self._mapped.manifest.build.input_artifact_ids != expected:
                raise NumpyMlArtifactFormatError("LabelSet exact lineage is inconsistent")
            expected_build = dict(semantic)
            expected_build.pop("maximum_future_boundary_used")
            # Evaluate the complete numpy label set reader init expected build, semantic
            # build and manifest condition before guarded effects.
            if _semantic_build(self._mapped.manifest) != expected_build:
                raise NumpyMlArtifactFormatError("LabelSet build/content semantics differ")
            self._training_cutoff = _integer(semantic["training_cutoff"], "training_cutoff")
            count = self._mapped.manifest.row_count
            self._mapped.require_layout(physical.label_layout(count))
            # Invoke _validate_arrays for semantic as a visible numpy label set reader
            # init step.
            self._validate_arrays(semantic)
        except BaseException:
            # Translate the BaseException failure through the numpy label set reader init
            # boundary.
            self.close()
            raise

    @property
    def label_set_id(self) -> LabelSetId:
        return LabelSetId(self._mapped.artifact_id.hex)

    # Apply property semantics to the following numpy label set reader manifest contract.
    @property
    def manifest(self) -> MlArtifactManifest:
        return self._mapped.manifest

    @property
    def snapshot_id(self) -> SnapshotId:
        # Return the completed numpy label set reader snapshot id result without a hidden
        # fallback.
        return self._snapshot_id

    @property
    def universe_id(self) -> UniverseId:
        return self._universe_id

    @property
    # Define numpy label set reader training cutoff as one focused operation with an
    # explicit boundary.
    def training_cutoff(self) -> int:
        return self._training_cutoff

    def row_for_training(self, replay_row_id: int) -> TrainingLabelRow | None:
        # Execute the numpy label set reader row for training workflow in explicit,
        # reviewable steps.
        if replay_row_id < 0:
            raise ValueError("replay row ID must be non-negative")
        row_ids = self._mapped.array(physical.LABEL_ROW_ID)
        position = int(row_ids.searchsorted(replay_row_id, side="left"))
        if position == row_ids.size or int(row_ids[position]) != replay_row_id:
            # Return explicit absence from the numpy label set reader row for training
            # path.
            return None
        return TrainingLabelRow(
            replay_row_id=replay_row_id,
            effective_boundary_ordinal=int(self._mapped.array(physical.LABEL_EFFECTIVE)[position]),
            future_boundary_used=int(self._mapped.array(physical.LABEL_FUTURE_USED)[position]),
            # Pass value explicitly so TrainingLabelRow receives a reviewable array and
            # label effective input in numpy label set reader row for training.
            value=(
                int(self._mapped.array(physical.LABEL_VALUE)[position])
                if _bitmap_valid(self._mapped.array(physical.LABEL_VALIDITY), position)
                else None
            ),
            # Complete TrainingLabelRow only after its array and label effective inputs are
            # visible in numpy label set reader row for training.
        )

    def rows_for_training(self) -> Iterator[TrainingLabelRow]:
        """Iterate the training-only logical stream in canonical row order."""

        for index in range(self._mapped.manifest.row_count):
            # Process range(self._mapped.manifest.row_count) inside the bounded numpy
            # label set reader rows for training loop.
            row = self.row_for_training(int(self._mapped.array(physical.LABEL_ROW_ID)[index]))
            if row is None:  # pragma: no cover - structure checked during open
                raise NumpyMlArtifactFormatError("LabelSet row disappeared during iteration")
            yield row

    def close(self) -> None:
        self._mapped.close()

    def __enter__(self) -> Self:
        # Return the completed numpy label set reader enter result without a hidden
        # fallback.
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        # Keep the traceback input explicit in the exit contract.
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _validate_arrays(self, semantic: dict[str, object]) -> None:
        # Execute the numpy label set reader validate arrays workflow in explicit,
        # reviewable steps.
        count = self._mapped.manifest.row_count
        rows = self._mapped.array(physical.LABEL_ROW_ID)
        effective = self._mapped.array(physical.LABEL_EFFECTIVE)
        future = self._mapped.array(physical.LABEL_FUTURE_USED)
        values = self._mapped.array(physical.LABEL_VALUE)
        # Assemble validity once so the numpy label set reader validate arrays workflow
        # shares one value.
        validity = self._mapped.array(physical.LABEL_VALIDITY)
        _validate_bitmap_padding(validity, count, "label")
        previous = -1
        hasher = MlLogicalStreamHasher(MlArtifactSchema.LABEL_SET)
        for index in range(count):
            # Process range(count) inside the bounded numpy label set reader validate
            # arrays loop.
            row_id = int(rows[index])
            effective_boundary = int(effective[index])
            future_boundary = int(future[index])
            if row_id <= previous:
                raise NumpyMlArtifactFormatError("LabelSet replay row IDs are not unique/sorted")
            # Evaluate the complete numpy label set reader validate arrays effective
            # boundary and training cutoff condition before guarded effects.
            if effective_boundary > self._training_cutoff:
                raise NumpyMlArtifactFormatError("LabelSet includes a post-cutoff effective row")
            if future_boundary < effective_boundary:
                raise NumpyMlArtifactFormatError("LabelSet future boundary precedes its row")
            previous = row_id
            # Assemble value once so the numpy label set reader validate arrays workflow
            # shares one value.
            value = int(values[index]) if _bitmap_valid(validity, index) else None
            hasher.update(
                {
                    "effective_boundary_ordinal": effective_boundary,
                    "future_boundary_used": future_boundary,
                    # Keep replay row id named so the effective boundary ordinal and
                    # future boundary used payload passed to update remains self-
                    # describing within numpy label set reader validate arrays.
                    "replay_row_id": row_id,
                    "value": value,
                }
            )
        maximum = _optional_integer(
            # Pass semantic explicitly so _optional_integer receives a reviewable maximum
            # future boundary used and maximum future boundary input in numpy label set
            # reader validate arrays.
            semantic["maximum_future_boundary_used"],
            "maximum future boundary",
        )
        actual = None if count == 0 else int(future.max())
        if maximum != actual:
            # Fail the numpy label set reader validate arrays path with
            # NumpyMlArtifactFormatError for label set maximum future boundary is
            # inconsistent when maximum and actual is true; do not continue ambiguously.
            raise NumpyMlArtifactFormatError("LabelSet maximum future boundary is inconsistent")
        # Invoke _require_logical_hash for manifest and mapped as a visible numpy label
        # set reader validate arrays step.
        _require_logical_hash(self._mapped.manifest, hasher)


__all__ = ["NumpyLabelSetReader", "TrainingLabelRow"]
