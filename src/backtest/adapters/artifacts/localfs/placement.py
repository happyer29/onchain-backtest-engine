"""Manifest-derived physical placement for committed local artifacts.

The configured data-root path is operational metadata and never participates in
content identity.  The relative placement below is nevertheless strict: the
identity manifest supplies every grouping key that is not the artifact ID.
Directory enumeration may use these shapes to find candidates, but only the
repository's full descriptor/manifest/hash verification grants authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath

from backtest.application.models import ArtifactKind
from backtest.domain.identifiers import ArtifactId, ContentDigest


class ArtifactPlacementError(ValueError):
    """An artifact identity cannot be placed in the normative local layout."""


_SUBDIRECTORIES: Mapping[ArtifactKind, str] = {
    ArtifactKind.SOURCE_INSPECTION: "source-inspections",
    ArtifactKind.CANONICAL_DISTRIBUTION: "canonical",
    ArtifactKind.SNAPSHOT: "snapshots",
    ArtifactKind.REPLAY_PACK: "replay",
    ArtifactKind.DELIVERY_SCHEDULE: "delivery_schedules",
    ArtifactKind.FEATURE_SET: "features",
    ArtifactKind.LABEL_SET: "labels",
    ArtifactKind.UNIVERSE: "universes",
    ArtifactKind.MODEL_BUNDLE: "models",
    ArtifactKind.MODEL_SCHEDULE: "model-schedules",
    ArtifactKind.PREDICTION_SET: "predictions",
    ArtifactKind.STRATEGY_BUNDLE: "strategies",
    ArtifactKind.SWEEP: "sweeps",
    ArtifactKind.BENCHMARK: "benchmarks",
    ArtifactKind.RUN: "runs",
}

_TWO_LEVEL_KINDS = frozenset(
    {
        ArtifactKind.CANONICAL_DISTRIBUTION,
        ArtifactKind.REPLAY_PACK,
        ArtifactKind.RUN,
    }
)


def artifact_subdirectory(kind: ArtifactKind) -> str:
    """Return the single canonical top-level directory for an artifact kind."""

    return _SUBDIRECTORIES[kind]


def artifact_relative_path(
    kind: ArtifactKind,
    artifact_id: ArtifactId,
    identity_manifest: Mapping[str, object],
) -> PurePosixPath:
    """Resolve the exact normative path from already-authenticated identity data."""

    top = artifact_subdirectory(kind)
    if kind is ArtifactKind.CANONICAL_DISTRIBUTION:
        logical_content_hash = _digest_field(
            identity_manifest,
            "logical_content_hash",
            label="canonical logical content hash",
        )
        return PurePosixPath(top, logical_content_hash, artifact_id.hex)
    if kind is ArtifactKind.REPLAY_PACK:
        snapshot_id = _digest_field(
            identity_manifest,
            "snapshot_id",
            label="ReplayPack snapshot ID",
        )
        return PurePosixPath(top, snapshot_id, artifact_id.hex)
    if kind is ArtifactKind.RUN:
        logical_run_id = _digest_field(
            identity_manifest,
            "logical_run_id",
            label="logical run ID",
        )
        execution_attempt_id = _digest_field(
            identity_manifest,
            "execution_attempt_id",
            label="execution attempt ID",
        )
        return PurePosixPath(top, logical_run_id, execution_attempt_id)
    return PurePosixPath(top, artifact_id.hex)


def validate_artifact_relative_shape(
    kind: ArtifactKind,
    artifact_id: ArtifactId,
    relative_path: str,
) -> PurePosixPath:
    """Validate a backup/materialization path without trusting it as authority."""

    path = PurePosixPath(relative_path)
    if path.is_absolute() or path.as_posix() != relative_path:
        raise ArtifactPlacementError("artifact relative path is not canonical")
    expected_length = 3 if kind in _TWO_LEVEL_KINDS else 2
    if len(path.parts) != expected_length or path.parts[0] != artifact_subdirectory(kind):
        raise ArtifactPlacementError("artifact relative path has the wrong layout shape")
    for segment in path.parts[1:]:
        _canonical_digest(segment, label="artifact path segment")
    if kind is not ArtifactKind.RUN and path.parts[-1] != artifact_id.hex:
        raise ArtifactPlacementError("artifact ID does not match its relative path")
    return path


def artifact_path_depth(kind: ArtifactKind) -> int:
    """Return the number of digest segments below the kind directory."""

    return 2 if kind in _TWO_LEVEL_KINDS else 1


def artifact_leaf_names_artifact_id(kind: ArtifactKind) -> bool:
    """Return whether candidate lookup can filter directly by the leaf name."""

    return kind is not ArtifactKind.RUN


def is_canonical_digest_segment(value: str) -> bool:
    """Return whether ``value`` is a plain lowercase SHA-256 path segment."""

    try:
        _canonical_digest(value, label="artifact path segment")
    except ArtifactPlacementError:
        return False
    return True


def _digest_field(
    document: Mapping[str, object],
    field: str,
    *,
    label: str,
) -> str:
    value = document.get(field)
    if not isinstance(value, str):
        raise ArtifactPlacementError(f"{label} is missing from artifact identity")
    return _canonical_digest(value, label=label)


def _canonical_digest(value: str, *, label: str) -> str:
    try:
        digest = ContentDigest(value)
    except (TypeError, ValueError) as error:
        raise ArtifactPlacementError(f"{label} is not a SHA-256 digest") from error
    if digest.value != digest.hex:
        raise ArtifactPlacementError(f"{label} must not use a display prefix")
    return digest.hex


__all__ = [
    "ArtifactPlacementError",
    "artifact_leaf_names_artifact_id",
    "artifact_path_depth",
    "artifact_relative_path",
    "artifact_subdirectory",
    "is_canonical_digest_segment",
    "validate_artifact_relative_shape",
]
