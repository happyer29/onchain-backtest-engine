"""Outbound ports for source discovery, planning and bounded extraction."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Protocol, runtime_checkable

from backtest.application.models import (
    BoundedSourceEvidenceReceipt,
    # Include bounded source evidence request so the models dependency remains explicit.
    BoundedSourceEvidenceRequest,
    CapabilityDescriptor,
    DatasetSpec,
    DiskCapacity,
    ExtractionRequest,
    # Include source estimate so the models dependency remains explicit.
    SourceEstimate,
    SourceInspection,
    SourceMetadata,
)
from backtest.domain.identifiers import ArtifactId, CapabilityId, ContentDigest, SourceId

# Import time at the visible module dependency boundary.
from backtest.domain.time import BlockRange


@runtime_checkable
class IndexedBatch(Protocol):
    """Adapter-neutral view of one bounded source batch.

    Concrete column buffers intentionally remain adapter-owned.  The future
    normalizer/projector port consumes the concrete implementation without
    forcing Arrow or another third-party type into the application layer.
    """

    @property
    def capability_id(self) -> CapabilityId: ...

    @property
    def covered_range(self) -> BlockRange: ...

    @property
    # Define indexed batch row count as one focused operation with an explicit boundary.
    def row_count(self) -> int: ...

    @property
    def columns(self) -> tuple[str, ...]: ...

    @property
    def rows(self) -> tuple[tuple[Any, ...], ...]: ...

    # Apply property semantics to the following indexed batch query fingerprint contract.
    @property
    def query_fingerprint(self) -> ContentDigest | None: ...


@runtime_checkable
class SourceMetadataReader(Protocol):
    """Read source metadata without creating a local market-data mirror."""

    def inspect_metadata(self, source_id: SourceId) -> SourceMetadata: ...


@runtime_checkable
class BoundedSourceEvidenceReader(Protocol):
    """Run explicit read-only validation queries for one authoritative cut."""

    def inspect_bounded_evidence(
        self,
        request: BoundedSourceEvidenceRequest,
    ) -> tuple[BoundedSourceEvidenceReceipt, ...]: ...


@runtime_checkable
# Keep the capability provider contract and validation rules together.
class CapabilityProvider(Protocol):
    """Resolve logical capabilities, usually from a saved inspection."""

    def list_capabilities(self, source_id: SourceId) -> tuple[CapabilityDescriptor, ...]: ...


@runtime_checkable
class SourceInspectionLoader(Protocol):
    """Open and validate one exact committed source-inspection artifact."""

    def load(self, artifact_id: ArtifactId) -> SourceInspection: ...


@runtime_checkable
class DatasetEstimator(Protocol):
    """Optional metadata-only estimate; it must not extract dataset rows."""

    def estimate(self, spec: DatasetSpec) -> SourceEstimate: ...


@runtime_checkable
class DiskCapacityProbe(Protocol):
    """Report capacity for the configured local data root."""

    def capacity(self) -> DiskCapacity: ...


@runtime_checkable
class SourceReader(CapabilityProvider, Protocol):
    """Stream explicitly planned, bounded shards from a read-only source."""

    def scan(self, request: ExtractionRequest) -> Iterator[IndexedBatch]: ...


__all__ = [
    "BoundedSourceEvidenceReader",
    "CapabilityProvider",
    "DatasetEstimator",
    # Keep the disk capacity probe component named inside the all contract.
    "DiskCapacityProbe",
    "IndexedBatch",
    "SourceInspectionLoader",
    "SourceMetadataReader",
    "SourceReader",
    # Complete the all group only after its semantic components are visible.
]
