"""Persist a secret-free source inspection as an immutable artifact."""

from __future__ import annotations

from dataclasses import dataclass

from backtest.application.models import (
    ArtifactDraft,
    ArtifactKind,
    # Include committed artifact so the models dependency remains explicit.
    CommittedArtifact,
    SourceInspection,
)
from backtest.application.ports.artifacts import ArtifactRepository
from backtest.application.source_inspection_document import (
    # Include source inspection build key so the source inspection document dependency
    # remains explicit.
    source_inspection_build_key,
    source_inspection_manifest,
    source_inspection_payload,
)
from backtest.application.use_cases.inspect_source import InspectSource, InspectSourceRequest


# Keep the stored source inspection contract and validation rules together.
@dataclass(frozen=True, slots=True)
class StoredSourceInspection:
    inspection: SourceInspection
    artifact: CommittedArtifact


class StoreSourceInspection:
    """Run inspection, then atomically publish its machine-readable record."""

    def __init__(self, inspect_source: InspectSource, artifacts: ArtifactRepository) -> None:
        # Execute the store source inspection init workflow in explicit, reviewable steps.
        self._inspect_source = inspect_source
        self._artifacts = artifacts

    def execute(self, request: InspectSourceRequest) -> StoredSourceInspection:
        # Execute the store source inspection execute workflow in explicit, reviewable
        # steps.
        inspection = self._inspect_source.execute(request)
        inspection_bytes = source_inspection_payload(inspection)
        manifest_bytes = source_inspection_manifest(inspection)
        writer = self._artifacts.stage(
            ArtifactDraft(
                # Pass kind explicitly so ArtifactDraft receives a reviewable source
                # inspection and source inspection build key input in store source
                # inspection execute.
                kind=ArtifactKind.SOURCE_INSPECTION,
                build_key=source_inspection_build_key(inspection),
            )
        )
        try:
            # Perform the protected store source inspection execute operation before
            # explicit failure handling.
            with writer.open_binary("inspection.json") as stream:
                stream.write(inspection_bytes)
            artifact = writer.commit(manifest_bytes)
        except BaseException:
            # Translate the BaseException failure through the store source inspection
            # execute boundary.
            writer.abort()
            raise
        return StoredSourceInspection(inspection=inspection, artifact=artifact)


__all__ = ["StoreSourceInspection", "StoredSourceInspection"]
