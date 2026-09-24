"""Controller-side recovery of durable canonical shard indexes."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

# Filesystem commits are authoritative; SQLite canonical indexes are rebuildable projections.
from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.adapters.artifacts.localfs.scanner import LocalCommittedArtifactScanner
from backtest.adapters.catalog.sqlite.artifact_catalog import SQLiteArtifactCatalog
from backtest.adapters.catalog.sqlite.canonical_outputs import (
    # Reconciliation repairs indexes without changing immutable artifact content.
    CanonicalOutputIndexError,
    SQLiteCanonicalOutputObserver,
)
from backtest.application.models import ArtifactKind, CommittedArtifact, JobRecord, JobType

# Submit resolution and queue mutations remain application-owned contracts.
from backtest.application.ports.job_resolution import PrepareDatasetJobResolver
from backtest.application.ports.jobs import JobQueue
from backtest.application.use_cases.research import ResearchUseCases
from backtest.application.use_cases.submit_job import SubmitJob, SubmitJobRequest

# The controller lock wraps reconciliation without weakening the global publication lock order.
from backtest.runtime.file_locks import FileLock, LockMode


class CanonicalShardIndexReconciler:
    """Rebuild missing canonical indexes from verified filesystem authority.

    The outer writer lock serializes this controller-side recovery with artifact
    publishers.  Candidate discovery still goes through ``open_committed``, so
    directory names and markers alone never authorize a shard for reuse.
    """

    def __init__(
        self,
        artifacts: LocalArtifactRepository,
        catalog: SQLiteArtifactCatalog,
        observer: SQLiteCanonicalOutputObserver,
    ) -> None:
        self._artifacts = artifacts
        self._catalog = catalog
        self._observer = observer

    @contextmanager
    def reconciled_submission(self) -> Iterator[tuple[CommittedArtifact, ...]]:
        """Protect verified reuse selection until its job is durably queued.

        ``backup-cut`` precedes the normal writer/retention/publication order so
        the SQLite job row and selected filesystem inputs belong to one safe
        retention interval.  The caller must enqueue before leaving this scope.
        """

        with (
            FileLock(self._artifacts.locks_root / "backup-cut.lock", mode=LockMode.SHARED),
            FileLock(self._artifacts.locks_root / "writer.lock", mode=LockMode.EXCLUSIVE),
            FileLock(self._artifacts.locks_root / "retention.lock", mode=LockMode.SHARED),
        ):
            distributions = self._reconcile_locked()
            yield distributions

    def reconcile(self) -> tuple[CommittedArtifact, ...]:
        """Idempotently project every verified canonical distribution into SQLite."""

        with self.reconciled_submission() as distributions:
            return distributions

    def _reconcile_locked(self) -> tuple[CommittedArtifact, ...]:
        discovered = LocalCommittedArtifactScanner(self._artifacts).scan()
        by_id = {artifact.artifact_id.hex: artifact for artifact in discovered}
        distributions = tuple(
            artifact
            for artifact in discovered
            if artifact.kind is ArtifactKind.CANONICAL_DISTRIBUTION
        )
        source_inputs = self._source_inspection_inputs(distributions, by_id)
        for source_input in source_inputs:
            self._catalog.index_committed(source_input)
        for distribution in distributions:
            self._catalog.index_committed(distribution)
        self._observer.observe(distributions)
        return distributions

    @staticmethod
    def _source_inspection_inputs(
        distributions: tuple[CommittedArtifact, ...],
        discovered: dict[str, CommittedArtifact],
    ) -> tuple[CommittedArtifact, ...]:
        inputs: dict[str, CommittedArtifact] = {}
        for distribution in distributions:
            if len(distribution.input_artifact_ids) != 1:
                raise CanonicalOutputIndexError(
                    "canonical distribution must reference one source inspection"
                )
            input_id = distribution.input_artifact_ids[0]
            source_input = discovered.get(input_id.hex)
            if source_input is None or source_input.kind is not ArtifactKind.SOURCE_INSPECTION:
                raise CanonicalOutputIndexError(
                    "canonical distribution source inspection is not verified"
                )
            inputs[source_input.artifact_id.hex] = source_input
        return tuple(inputs[key] for key in sorted(inputs))


class ReconciledPrepareDatasetSubmitJob(SubmitJob):
    """Reconcile and retain orphan shards through durable prepare submission."""

    def __init__(
        self,
        queue: JobQueue,
        delegate: PrepareDatasetJobResolver,
        reconciler: CanonicalShardIndexReconciler,
        # All other job types keep the same exact-input checks in the shared submitter.
        research: ResearchUseCases | None = None,
    ) -> None:
        # Delegate every non-prepare workflow through the same exact-input resolver.
        super().__init__(queue, delegate, research)
        self._reconciler = reconciler

    # Only canonical dataset preparation requires shard-index reconciliation.
    def execute(self, request: SubmitJobRequest) -> JobRecord:
        if request.job_type is not JobType.PREPARE_DATASET:
            return super().execute(request)
        with self._reconciler.reconciled_submission():
            # Hold reconciliation authority until the resolved job becomes durable.
            return super().execute(request)


__all__ = ["CanonicalShardIndexReconciler", "ReconciledPrepareDatasetSubmitJob"]
