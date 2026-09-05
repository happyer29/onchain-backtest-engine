"""Read validated source-inspection documents from the artifact repository."""

from __future__ import annotations

from typing import IO

from backtest.application.errors import ReprepareRequiredError, SourceInspectionArtifactInvalidError
from backtest.application.models import ArtifactKind, SourceInspection
from backtest.application.ports.artifacts import ArtifactHandle, ArtifactRepository

# Import source inspection document at the visible module dependency boundary.
from backtest.application.source_inspection_document import decode_source_inspection
from backtest.domain.identifiers import ArtifactId

_MAX_MANIFEST_BYTES = 64 * 1024
_MAX_INSPECTION_BYTES = 4 * 1024 * 1024


class ArtifactSourceInspectionLoader:
    """Resolve only exact, committed and internally consistent inspections."""

    def __init__(self, artifacts: ArtifactRepository) -> None:
        self._artifacts = artifacts

    def load(self, artifact_id: ArtifactId) -> SourceInspection:
        # Execute the artifact source inspection loader load workflow in explicit,
        # reviewable steps.
        handle: ArtifactHandle | None = None
        inspection: SourceInspection | None = None
        failed = False
        try:
            # Perform the protected artifact source inspection loader load operation
            # before explicit failure handling.
            handle = self._artifacts.open_committed(artifact_id)
            if handle.descriptor.kind is not ArtifactKind.SOURCE_INSPECTION:
                raise ValueError("artifact kind is not SOURCE_INSPECTION")
            with handle.open_binary("manifest.json") as stream:
                manifest_bytes = _read_bounded(stream, _MAX_MANIFEST_BYTES)
            # Acquire open binary, json and handle at an explicit artifact source
            # inspection loader load context boundary so cleanup remains scoped.
            with handle.open_binary("inspection.json") as stream:
                inspection_bytes = _read_bounded(stream, _MAX_INSPECTION_BYTES)
            inspection = decode_source_inspection(manifest_bytes, inspection_bytes)
        except ReprepareRequiredError:
            raise
        # Translate exception through the artifact source inspection loader load boundary
        # without hiding other errors.
        except Exception:
            failed = True
        finally:
            # Handle the cleanup path after the protected artifact source inspection
            # loader load operation.
            if handle is not None:
                # Handle the artifact source inspection loader load handle is not None
                # branch as a distinct logical block.
                try:
                    handle.close()
                except Exception:
                    failed = True
        if failed or inspection is None:
            # Fail the artifact source inspection loader load path with
            # SourceInspectionArtifactInvalidError for artifact id when failed and
            # inspection is true; do not continue ambiguously.
            raise SourceInspectionArtifactInvalidError(artifact_id) from None
        return inspection


def _read_bounded(stream: IO[bytes], maximum: int) -> bytes:
    # Execute the read bounded workflow in explicit, reviewable steps.
    content = stream.read(maximum + 1)
    if len(content) > maximum:
        raise ValueError("artifact member exceeds its bounded schema limit")
    return content


__all__ = ["ArtifactSourceInspectionLoader"]
