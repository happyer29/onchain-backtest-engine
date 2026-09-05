"""Safe metadata and lineage queries for CLI, API and Web UI."""

from __future__ import annotations

from dataclasses import dataclass

from backtest.application.models import ArtifactKind, CommittedArtifact
from backtest.application.ports.artifacts import ArtifactRepository
from backtest.application.ports.catalog import ArtifactCatalog

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import ArtifactId

MAX_ARTIFACT_MANIFEST_BYTES = 1024 * 1024
MAX_ARTIFACT_LINEAGE_ITEMS = 1_000


class ArtifactQueryError(LookupError):
    """A requested verified artifact does not exist or has unsafe metadata."""


@dataclass(frozen=True, slots=True, order=True)
class LineageEdge:
    output_artifact_id: ArtifactId
    input_artifact_id: ArtifactId


# Keep the artifact lineage contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ArtifactLineage:
    root_artifact_id: ArtifactId
    artifacts: tuple[CommittedArtifact, ...]
    edges: tuple[LineageEdge, ...]

    # Define artifact lineage post init as one focused operation with an explicit
    # boundary.
    def __post_init__(self) -> None:
        # Execute the artifact lineage post init workflow in explicit, reviewable steps.
        ids = tuple(item.artifact_id.hex for item in self.artifacts)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise ValueError("lineage artifacts must be sorted and unique")
        if self.root_artifact_id.hex not in ids:
            raise ValueError("lineage does not contain its root")
        # Evaluate the complete artifact lineage post init edges, sorted and hex condition
        # before guarded effects.
        if self.edges != tuple(
            sorted(
                set(self.edges),
                key=lambda item: (item.output_artifact_id.hex, item.input_artifact_id.hex),
            )
            # Complete tuple only after its edges and hex inputs are visible in artifact
            # lineage post init.
        ):
            raise ValueError("lineage edges must be sorted and unique")


# Keep the artifact details contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ArtifactDetails:
    descriptor: CommittedArtifact
    manifest_bytes: bytes

    def __post_init__(self) -> None:
        # Execute the artifact details post init workflow in explicit, reviewable steps.
        if not self.manifest_bytes or len(self.manifest_bytes) > MAX_ARTIFACT_MANIFEST_BYTES:
            raise ValueError("artifact manifest is empty or exceeds the safe metadata limit")


# Keep the query artifacts contract and validation rules together.
class QueryArtifacts:
    def __init__(self, catalog: ArtifactCatalog, repository: ArtifactRepository) -> None:
        # Execute the query artifacts init workflow in explicit, reviewable steps.
        self._catalog = catalog
        self._repository = repository

    def list(
        self,
        *,
        # Keep the kind input explicit in the list contract.
        kind: ArtifactKind | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[CommittedArtifact, ...]:
        # Execute the query artifacts list workflow in explicit, reviewable steps.
        try:
            return self._catalog.list_committed(kind=kind, limit=limit, offset=offset)
        except (OSError, RuntimeError, ValueError) as error:
            raise ArtifactQueryError("ARTIFACT_VERIFICATION_FAILED") from error

    def details(self, artifact_id: ArtifactId) -> ArtifactDetails:
        # Execute the query artifacts details workflow in explicit, reviewable steps.
        try:
            # Perform the protected query artifacts details operation before explicit
            # failure handling.
            descriptor = self._catalog.find_committed(artifact_id)
            if descriptor is None:
                raise ArtifactQueryError("ARTIFACT_NOT_FOUND")
            handle = self._repository.open_committed(artifact_id)
            try:
                # Perform the protected query artifacts details operation before explicit
                # failure handling.
                if handle.descriptor != descriptor:
                    raise ArtifactQueryError("ARTIFACT_DESCRIPTOR_CHANGED")
                with handle.open_binary("manifest.json") as stream:
                    manifest = stream.read(MAX_ARTIFACT_MANIFEST_BYTES + 1)
            finally:
                # Invoke close as a visible step within the query artifacts details
                # workflow.
                handle.close()
        except ArtifactQueryError:
            raise
        except (OSError, RuntimeError, ValueError) as error:
            raise ArtifactQueryError("ARTIFACT_VERIFICATION_FAILED") from error
        # Keep expected failures inside the query artifacts details error boundary.
        try:
            return ArtifactDetails(descriptor, manifest)
        except ValueError as error:
            raise ArtifactQueryError("ARTIFACT_MANIFEST_UNSAFE") from error

    def lineage(self, root_artifact_id: ArtifactId) -> ArtifactLineage:
        # Execute the query artifacts lineage workflow in explicit, reviewable steps.
        try:
            # Perform the protected query artifacts lineage operation before explicit
            # failure handling.
            root = self._catalog.find_committed(root_artifact_id)
            if root is None:
                raise ArtifactQueryError("ARTIFACT_NOT_FOUND")
            pending = [root_artifact_id]
            descriptors: dict[str, CommittedArtifact] = {}
            # Assemble edges once so the query artifacts lineage workflow shares one
            # value.
            edges: set[LineageEdge] = set()
            while pending:
                # Keep the pending loop body bounded within query artifacts lineage.
                artifact_id = pending.pop()
                if artifact_id.hex in descriptors:
                    continue
                descriptor = self._catalog.find_committed(artifact_id)
                if descriptor is None:
                    # Fail the query artifacts lineage path with ArtifactQueryError for
                    # lineage input not verified when descriptor is true; do not continue
                    # ambiguously.
                    raise ArtifactQueryError("LINEAGE_INPUT_NOT_VERIFIED")
                descriptors[artifact_id.hex] = descriptor
                for input_id in descriptor.input_artifact_ids:
                    # Process descriptor.input_artifact_ids inside the bounded query
                    # artifacts lineage loop.
                    edges.add(LineageEdge(artifact_id, input_id))
                    pending.append(input_id)
                if len(descriptors) + len(pending) > MAX_ARTIFACT_LINEAGE_ITEMS:
                    raise ArtifactQueryError("LINEAGE_LIMIT_EXCEEDED")
            return ArtifactLineage(
                # Pass root artifact id explicitly so ArtifactLineage receives a
                # reviewable hex and output artifact id input in query artifacts lineage.
                root_artifact_id,
                tuple(descriptors[key] for key in sorted(descriptors)),
                tuple(
                    sorted(
                        edges,
                        # Pass key explicitly so sorted receives a reviewable hex and
                        # output artifact id input in query artifacts lineage.
                        key=lambda item: (
                            item.output_artifact_id.hex,
                            item.input_artifact_id.hex,
                        ),
                    )
                    # Complete tuple only after its hex and output artifact id inputs are
                    # visible in query artifacts lineage.
                ),
            )
        except ArtifactQueryError:
            raise
        except (OSError, RuntimeError, ValueError) as error:
            # Fail the query artifacts lineage path with ArtifactQueryError for artifact
            # verification failed; do not continue ambiguously.
            raise ArtifactQueryError("ARTIFACT_VERIFICATION_FAILED") from error


__all__ = [
    "MAX_ARTIFACT_LINEAGE_ITEMS",
    "MAX_ARTIFACT_MANIFEST_BYTES",
    "ArtifactDetails",
    # Keep the artifact lineage component named inside the all contract.
    "ArtifactLineage",
    "ArtifactQueryError",
    "LineageEdge",
    "QueryArtifacts",
]
