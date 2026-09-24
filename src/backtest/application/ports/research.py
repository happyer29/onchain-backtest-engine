"""Replaceable acquisition, columnar research and verified-query seams."""

from collections.abc import Callable, Iterator
from typing import Protocol

# Ports exchange immutable application values; native batch types stay in adapters.
from backtest.application.models import CommittedArtifact, JobRecord
from backtest.application.research import (
    ResearchDatasetSpec,
    ResearchTable,
    ResearchTokenMode,
    # These specs carry exact content IDs and fixed recipes, never executable SQL.
    WalletAnalysisSpec,
    WalletObservation,
)

# Port signatures use bounded Python values, never Arrow/DuckDB objects or paths.
from backtest.domain.identifiers import ArtifactId, ContentDigest, JobId

# A source callback is available only while preparing one snapshot, never during analysis.
ResearchModeReader = Callable[[tuple[str, ...]], tuple[ResearchTokenMode, ...]]


class ResearchJobQuery(Protocol):
    """Operational result candidates must still be authenticated against committed bytes."""

    def get_job(self, job_id: JobId) -> JobRecord | None: ...

    def get_successful_result(self, job_id: JobId) -> ArtifactId | None: ...


class ResearchSource(Protocol):
    """Source-only operations over an already resolved bounded acquisition."""

    def inspect(self, spec: ResearchDatasetSpec) -> ContentDigest: ...

    def batches(self, spec: ResearchDatasetSpec) -> Iterator[tuple[WalletObservation, ...]]: ...

    # Classify only the complete bounded set of observed mints, preserving source provenance.
    def modes(
        self, spec: ResearchDatasetSpec, mints: tuple[str, ...]
    ) -> tuple[ResearchTokenMode, ...]: ...


class ResearchStore(Protocol):
    """Publication and local analysis share the existing artifact repository."""

    def publish_snapshot(
        self,
        spec: ResearchDatasetSpec,
        schema_digest: ContentDigest,
        # The source stream is consumed once under hard preparation limits.
        batches: Iterator[tuple[WalletObservation, ...]],
        # V2 publication requires a complete explicit classification source.
        *,
        classify: ResearchModeReader | None = None,
    ) -> CommittedArtifact: ...

    # A complete recipe produces one immutable result; no partial success is returned.
    def analyze(self, spec: WalletAnalysisSpec) -> CommittedArtifact: ...

    def summary(self, artifact_id: ArtifactId) -> dict[str, object]: ...

    # Row ordinals address exact immutable tables, rather than SQL OFFSET scanning.
    def page(
        self,
        artifact_id: ArtifactId,
        table: ResearchTable,
        # Only fixed roles are accepted; the port does not expose arbitrary paths or statements.
        *,
        after: int,
        # Pair scope narrows evidence without changing the global result counts.
        limit: int,
        pair: int | None = None,
    ) -> tuple[dict[str, str], ...]: ...
