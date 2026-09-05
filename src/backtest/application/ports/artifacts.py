"""Outbound port for committed local artifacts."""

from __future__ import annotations

from typing import IO, Protocol, runtime_checkable

from backtest.application.models import ArtifactDraft, CommittedArtifact
from backtest.domain.identifiers import ArtifactId


# Keep the artifact writer contract and validation rules together.
@runtime_checkable
class ArtifactWriter(Protocol):
    @property
    def draft(self) -> ArtifactDraft: ...

    def open_binary(self, relative_name: str) -> IO[bytes]: ...

    # Define artifact writer commit as one focused operation with an explicit boundary.
    def commit(
        self,
        manifest_bytes: bytes,
        *,
        identity_manifest_bytes: bytes | None = None,
        # Keep the committed artifact step explicit within the artifact writer commit
        # workflow.
    ) -> CommittedArtifact: ...

    def abort(self) -> None: ...


# Keep the artifact handle contract and validation rules together.
@runtime_checkable
class ArtifactHandle(Protocol):
    @property
    def descriptor(self) -> CommittedArtifact: ...

    def open_binary(self, relative_name: str) -> IO[bytes]: ...

    # Define artifact handle close as one focused operation with an explicit boundary.
    def close(self) -> None: ...


# Keep the artifact repository contract and validation rules together.
@runtime_checkable
class ArtifactRepository(Protocol):
    def stage(self, spec: ArtifactDraft) -> ArtifactWriter: ...

    def open_committed(self, artifact_id: ArtifactId) -> ArtifactHandle: ...


__all__ = ["ArtifactHandle", "ArtifactRepository", "ArtifactWriter"]
