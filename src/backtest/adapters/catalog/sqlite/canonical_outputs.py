"""Project verified canonical child outputs into the rebuildable shard ledger."""

from __future__ import annotations

import json
from typing import cast

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.adapters.catalog.sqlite.shard_ledger import SQLiteShardLedger

# Import canonical data at the visible module dependency boundary.
from backtest.application.canonical_data import EffectiveSourceBoundary, SourceBoundary
from backtest.application.models import ArtifactKind, CommittedArtifact
from backtest.application.source_ledger import CommittedShardRevision
from backtest.domain.hashing import canonical_json_bytes

_MAX_MANIFEST_BYTES = 2 * 1024 * 1024


# Keep the canonical output index error contract and validation rules together.
class CanonicalOutputIndexError(RuntimeError):
    """A canonical output cannot be projected without weakening verification."""


class SQLiteCanonicalOutputObserver:
    """Record immutable revisions only after filesystem and receipt verification."""

    def __init__(
        self,
        artifacts: LocalArtifactRepository,
        shard_ledger: SQLiteShardLedger,
    ) -> None:
        # Execute the sqlite canonical output observer init workflow in explicit,
        # reviewable steps.
        self._artifacts = artifacts
        self._shard_ledger = shard_ledger

    def observe(self, outputs: tuple[CommittedArtifact, ...]) -> None:
        # Execute the sqlite canonical output observer observe workflow in explicit,
        # reviewable steps.
        for artifact in outputs:
            # Process outputs inside the bounded sqlite canonical output observer observe
            # loop.
            if artifact.kind is not ArtifactKind.CANONICAL_DISTRIBUTION:
                continue
            boundary = self._verified_boundary(artifact)
            self._shard_ledger.record_revision(CommittedShardRevision(artifact, boundary))

    def _verified_boundary(self, artifact: CommittedArtifact) -> SourceBoundary:
        # Execute the sqlite canonical output observer verified boundary workflow in
        # explicit, reviewable steps.
        handle = self._artifacts.open_committed(artifact.artifact_id)
        try:
            # Perform the protected sqlite canonical output observer verified boundary
            # operation before explicit failure handling.
            if handle.descriptor != artifact:
                # Handle the sqlite canonical output observer verified boundary
                # handle.descriptor != artifact branch as a distinct logical block.
                raise CanonicalOutputIndexError(
                    "canonical output descriptor changed before ledger projection"
                )
            with handle.open_binary("manifest.json") as stream:
                payload = stream.read(_MAX_MANIFEST_BYTES + 1)
        # Complete the required cleanup regardless of the protected outcome.
        finally:
            handle.close()
        if len(payload) > _MAX_MANIFEST_BYTES:
            raise CanonicalOutputIndexError("canonical output manifest exceeds its size limit")
        try:
            # Perform the protected sqlite canonical output observer verified boundary
            # operation before explicit failure handling.
            value = json.loads(payload)
            if canonical_json_bytes(value) != payload or not isinstance(value, dict):
                raise ValueError
            manifest = cast(dict[str, object], value)
            if manifest.get("artifact_schema") != "canonical-distribution/v5":
                # Fail the sqlite canonical output observer verified boundary path with
                # ValueError when get, artifact schema and manifest is true; do not
                # continue ambiguously.
                raise ValueError
            boundary = EffectiveSourceBoundary.from_document(manifest.get("source_boundary"))
            if (
                manifest.get("capability_id") != boundary.source_boundary.capability_id.value
                or manifest.get("event_kind") != boundary.event_kind.name
                # Evaluate the complete sqlite canonical output observer verified boundary
                # value, name and get condition before guarded effects.
            ):
                raise ValueError
        except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
            # Translate the type error, value error and unicode decode error failure
            # through the sqlite canonical output observer verified boundary boundary.
            raise CanonicalOutputIndexError(
                "canonical output manifest cannot enter the shard ledger"
            ) from error
        return boundary.source_boundary


__all__ = ["CanonicalOutputIndexError", "SQLiteCanonicalOutputObserver"]
