"""Typed, traversal-safe paths inside the configured local data root.

Paths are infrastructure metadata: callers build them from already resolved
identifiers, but the paths themselves never participate in logical identity.
This module intentionally performs no artifact discovery; manifests remain the
only source of referenced files.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backtest.domain.identifiers import (
    ArtifactId,
    # Include attempt id so the identifiers dependency remains explicit.
    AttemptId,
    CapabilityId,
    DeliveryScheduleId,
    ExecutionAttemptId,
    FeatureSetId,
    # Include identifier so the identifiers dependency remains explicit.
    Identifier,
    LogicalContentHash,
    LogicalRunId,
    ModelBundleId,
    PredictionSetId,
    # Include replay pack id so the identifiers dependency remains explicit.
    ReplayPackId,
    SnapshotId,
    SourceId,
)
from backtest.domain.time import SlotRange


# Keep the unsafe data root identifier error contract and validation rules together.
class UnsafeDataRootIdentifierError(ValueError):
    """Raised when an opaque identifier cannot be represented by one path segment."""


def _segment(identifier: Identifier | str, *, label: str) -> str:
    # Execute the segment workflow in explicit, reviewable steps.
    value = identifier.value if isinstance(identifier, Identifier) else identifier
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string or Identifier")
    if (
        not value
        # Keep value visible while evaluating the value, strip and encode guard.
        or value in {".", ".."}
        or value != value.strip()
        or "/" in value
        or "\\" in value
        or "\x00" in value
        # Keep len visible while evaluating the value, strip and encode guard.
        or len(value.encode("utf-8")) > 240
        or any(ord(character) < 32 for character in value)
    ):
        raise UnsafeDataRootIdentifierError(f"{label} is not a safe path segment")
    return value


# Apply dataclass semantics to the following data root layout contract.
@dataclass(frozen=True, slots=True)
class DataRootLayout:
    """Canonical local paths for the single-host deployment profile."""

    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", self.root.resolve())

    @property
    def catalog_directory(self) -> Path:
        # Return the completed data root layout catalog directory result without a hidden
        # fallback.
        return self.root / "catalog"

    @property
    def catalog_database(self) -> Path:
        return self.catalog_directory / "catalog.sqlite"

    @property
    # Define data root layout locks directory as one focused operation with an explicit
    # boundary.
    def locks_directory(self) -> Path:
        return self.root / "locks"

    def lock(self, name: str) -> Path:
        return self.locks_directory / f"{_segment(name, label='lock name')}.lock"

    @property
    # Define data root layout controller lock as one focused operation with an explicit
    # boundary.
    def controller_lock(self) -> Path:
        return self.lock("controller")

    @property
    def writer_lock(self) -> Path:
        return self.lock("writer")

    # Apply property semantics to the following data root layout publication lock
    # contract.
    @property
    def publication_lock(self) -> Path:
        return self.lock("publication")

    @property
    def retention_lock(self) -> Path:
        # Return the completed data root layout retention lock result without a hidden
        # fallback.
        return self.lock("retention")

    def run_lock(self, execution_attempt_id: ExecutionAttemptId) -> Path:
        return self.lock(f"run-{execution_attempt_id.hex}")

    @property
    def staging_directory(self) -> Path:
        # Return the completed data root layout staging directory result without a hidden
        # fallback.
        return self.root / "staging"

    def staging_attempt(self, attempt_id: AttemptId) -> Path:
        return self.staging_directory / _segment(attempt_id, label="attempt ID")

    @property
    def job_receipts_directory(self) -> Path:
        # Return the completed data root layout job receipts directory result without a
        # hidden fallback.
        return self.root / "job_receipts"

    def job_receipt(self, attempt_id: AttemptId) -> Path:
        return self.job_receipts_directory / (f"{_segment(attempt_id, label='attempt ID')}.json")

    @property
    def raw_cache_directory(self) -> Path:
        # Return the completed data root layout raw cache directory result without a
        # hidden fallback.
        return self.root / "cache" / "raw"

    def raw_shard(
        self,
        source_id: SourceId,
        capability_id: CapabilityId,
        # Keep the slot range input explicit in the raw shard contract.
        slot_range: SlotRange,
    ) -> Path:
        # Execute the data root layout raw shard workflow in explicit, reviewable steps.
        shard = f"{slot_range.from_slot:020d}-{slot_range.to_slot:020d}"
        return (
            self.raw_cache_directory
            / _segment(source_id, label="source ID")
            / _segment(capability_id, label="capability ID")
            # Include shard in the completed data root layout raw shard result.
            / shard
        )

    @property
    def canonical_directory(self) -> Path:
        return self.root / "canonical"

    # Define data root layout canonical distribution as one focused operation with an
    # explicit boundary.
    def canonical_distribution(
        self,
        logical_content_hash: LogicalContentHash,
        distribution_id: ArtifactId,
    ) -> Path:
        # Return the completed data root layout canonical distribution result without a
        # hidden fallback.
        return self.canonical_directory / logical_content_hash.hex / distribution_id.hex

    @property
    def snapshots_directory(self) -> Path:
        return self.root / "snapshots"

    def snapshot(self, snapshot_id: SnapshotId) -> Path:
        # Return the completed data root layout snapshot result without a hidden fallback.
        return self.snapshots_directory / snapshot_id.hex

    @property
    def replay_directory(self) -> Path:
        return self.root / "replay"

    def replay_pack(self, snapshot_id: SnapshotId, replay_pack_id: ReplayPackId) -> Path:
        # Return the completed data root layout replay pack result without a hidden
        # fallback.
        return self.replay_directory / snapshot_id.hex / replay_pack_id.hex

    @property
    def delivery_schedules_directory(self) -> Path:
        return self.root / "delivery_schedules"

    def delivery_schedule(self, schedule_id: DeliveryScheduleId) -> Path:
        # Return the completed data root layout delivery schedule result without a hidden
        # fallback.
        return self.delivery_schedules_directory / schedule_id.hex

    @property
    def features_directory(self) -> Path:
        return self.root / "features"

    def feature_set(self, feature_set_id: FeatureSetId) -> Path:
        # Return the completed data root layout feature set result without a hidden
        # fallback.
        return self.features_directory / feature_set_id.hex

    @property
    def predictions_directory(self) -> Path:
        return self.root / "predictions"

    def prediction_set(self, prediction_set_id: PredictionSetId) -> Path:
        # Return the completed data root layout prediction set result without a hidden
        # fallback.
        return self.predictions_directory / prediction_set_id.hex

    @property
    def models_directory(self) -> Path:
        return self.root / "models"

    def model_bundle(self, model_bundle_id: ModelBundleId) -> Path:
        # Return the completed data root layout model bundle result without a hidden
        # fallback.
        return self.models_directory / model_bundle_id.hex

    @property
    def pins_directory(self) -> Path:
        return self.root / "pins"

    def pin(self, pin_id: Identifier) -> Path:
        # Return the completed data root layout pin result without a hidden fallback.
        return self.pins_directory / f"{_segment(pin_id, label='pin ID')}.json"

    @property
    def runs_directory(self) -> Path:
        return self.root / "runs"

    def run_attempt(
        # Keep the remaining run attempt inputs visible at the data root layout run
        # attempt boundary.
        self,
        logical_run_id: LogicalRunId,
        execution_attempt_id: ExecutionAttemptId,
    ) -> Path:
        return self.runs_directory / logical_run_id.hex / execution_attempt_id.hex

    # Apply property semantics to the following data root layout temporary directory
    # contract.
    @property
    def temporary_directory(self) -> Path:
        return self.root / "tmp"

    @property
    def trash_directory(self) -> Path:
        # Return the completed data root layout trash directory result without a hidden
        # fallback.
        return self.root / "trash"

    def ensure_foundation(self) -> None:
        """Create only the stable top-level directories, never artifact leaves."""

        directories = (
            self.catalog_directory,
            self.locks_directory,
            self.staging_directory,
            self.job_receipts_directory,
            # Keep the self component named inside the directories contract.
            self.raw_cache_directory,
            self.canonical_directory,
            self.snapshots_directory,
            self.replay_directory,
            self.delivery_schedules_directory,
            # Keep the self component named inside the directories contract.
            self.features_directory,
            self.predictions_directory,
            self.models_directory,
            self.pins_directory,
            self.runs_directory,
            # Keep the self component named inside the directories contract.
            self.temporary_directory,
            self.trash_directory,
        )
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)


# Bind all once as an explicit module-level contract.
__all__ = ["DataRootLayout", "UnsafeDataRootIdentifierError"]
