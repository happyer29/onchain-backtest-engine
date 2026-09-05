"""Run-specific projections over the verified artifact catalog."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise

# Run projections compare rebuildable index metadata with exact manifest bytes.
from backtest.application.catalog_models import RunIndexEntry
from backtest.application.models import ArtifactKind, CommittedArtifact
from backtest.application.ports.catalog import RunListCursor, RunMetadataIndex
from backtest.application.run_results import (
    RunComparisonProjection,
    RunPhysicalSettings,
    SuccessfulRunManifest,
    successful_run_manifest_from_bytes,
    # Warning bounds belong to the persisted Run contract, not the UI.
    validate_run_warnings,
)
from backtest.application.run_specs import ReplayContract

# Import query artifacts at the visible module dependency boundary.
from backtest.application.use_cases.query_artifacts import ArtifactQueryError, QueryArtifacts
from backtest.domain.identifiers import ArtifactId, ContentDigest, ExecutionAttemptId, LogicalRunId


class RunIndexQueryError(ArtifactQueryError):
    """The rebuildable Run ordering projection is missing or disagrees with authority."""

    code = "RUN_INDEX_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__(self.code)


# Keep the run summary view contract and validation rules together.
@dataclass(frozen=True, slots=True)
class RunSummaryView:
    run_artifact_id: ArtifactId
    logical_run_id: LogicalRunId
    execution_attempt_id: ExecutionAttemptId
    # Comparison data is bounded metadata; large result rows stay externalized.
    comparison: RunComparisonProjection
    physical_settings: RunPhysicalSettings
    canonicality: ReplayContract
    # Operational time is displayed and indexed but excluded from semantic identity.
    started_at: datetime
    completed_at: datetime
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        """Keep the query projection as strict as the successful Run manifest."""

        if self.canonicality is not ReplayContract.CANONICAL_EXACT:
            raise ValueError("a successful run view must be CANONICAL_EXACT")
        # Both endpoints must expose comparable aware times in chronological order.
        if (
            self.started_at.tzinfo is None
            or self.started_at.utcoffset() is None
            or self.completed_at.tzinfo is None
            # Aware timestamps alone are insufficient if their chronology is invalid.
            or self.completed_at.utcoffset() is None
            or self.completed_at < self.started_at
        ):
            raise ValueError("run view timestamps are invalid")
        validate_run_warnings(self.warnings)

    @property
    def canonical_result_hash(self) -> ContentDigest:
        return self.comparison.canonical_result_hash

    @property
    def audit_hash(self) -> ContentDigest:
        return self.comparison.audit_hash


@dataclass(frozen=True, slots=True)
class RunListPage:
    """One authenticated Run page plus its exclusive continuation key."""

    items: tuple[RunSummaryView, ...]
    next_cursor: RunListCursor | None

    def __post_init__(self) -> None:
        """Keep the application page within the public projection bound."""

        if len(self.items) > 1_000:
            raise ValueError("run page contains more than 1000 records")


# Keep the query runs contract and validation rules together.
class QueryRuns:
    def __init__(self, artifacts: QueryArtifacts, run_index: RunMetadataIndex) -> None:
        self._artifacts = artifacts
        self._run_index = run_index

    def list(self, *, limit: int = 100, offset: int = 0) -> tuple[RunSummaryView, ...]:
        """Return a globally newest-first page and authenticate every selected Run."""

        try:
            entries = self._run_index.list_runs(limit=limit, offset=offset)
        except (OSError, RuntimeError, ValueError) as error:
            raise RunIndexQueryError from error
        return tuple(self._view(item.artifact_id, expected=item) for item in entries)

    def page(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        after: RunListCursor | None = None,
    ) -> RunListPage:
        """Return one stable global page with a verified one-row lookahead."""

        return self._page(
            logical_run_id=None,
            limit=limit,
            offset=offset,
            after=after,
        )

    def get(self, artifact_id: ArtifactId) -> RunSummaryView:
        return self._view(artifact_id)

    def get_logical(
        self,
        logical_run_id: LogicalRunId,
        *,
        # Offset pagination applies only after exact logical-ID filtering.
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[RunSummaryView, ...]:
        """Return one indexed page for a single exact logical experiment."""

        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1_000:
            raise ValueError("run query limit must be an integer between 1 and 1000")
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 10_000:
            raise ValueError("run query offset must be an integer between 0 and 10000")
        # The index filters before pagination, avoiding a scan of unrelated Runs.
        try:
            entries = self._run_index.list_logical_runs(
                logical_run_id,
                limit=limit,
                offset=offset,
            )
        except (OSError, RuntimeError, ValueError) as error:
            raise RunIndexQueryError from error
        return tuple(self._view(item.artifact_id, expected=item) for item in entries)

    def logical_page(
        self,
        logical_run_id: LogicalRunId,
        *,
        limit: int = 50,
        offset: int = 0,
        after: RunListCursor | None = None,
    ) -> RunListPage:
        """Return a stable page scoped to one exact logical experiment."""

        return self._page(
            logical_run_id=logical_run_id,
            limit=limit,
            offset=offset,
            after=after,
        )

    def _page(
        self,
        *,
        logical_run_id: LogicalRunId | None,
        limit: int,
        offset: int,
        after: RunListCursor | None,
    ) -> RunListPage:
        """Validate scope, authenticate lookahead rows, and issue continuation."""

        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1_000:
            raise ValueError("run query limit must be an integer between 1 and 1000")
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 10_000:
            raise ValueError("run query offset must be an integer between 0 and 10000")
        if after is not None and (offset != 0 or after.logical_run_id != logical_run_id):
            raise ValueError("run cursor must match the scope and cannot use offset")
        try:
            # The bounded hidden row proves whether a continuation exists.
            if logical_run_id is None:
                entries = self._run_index.list_runs(
                    limit=limit + 1,
                    offset=offset,
                    after=after,
                )
            else:
                entries = self._run_index.list_logical_runs(
                    logical_run_id,
                    limit=limit + 1,
                    offset=offset,
                    after=after,
                )
        except (OSError, RuntimeError, ValueError) as error:
            raise RunIndexQueryError from error
        if len(entries) > limit + 1:
            raise RunIndexQueryError
        # Every selected index row, including lookahead, is authenticated against bytes.
        views = tuple(self._view(item.artifact_id, expected=item) for item in entries)
        _validate_run_page(entries, logical_run_id=logical_run_id, after=after)
        items = views[:limit]
        next_cursor = None
        # The cursor names the last visible row, never the hidden lookahead row.
        if len(views) > limit:
            last = entries[limit - 1]
            next_cursor = RunListCursor(
                completed_at_ns=last.completed_at_ns,
                artifact_id=last.artifact_id,
                logical_run_id=logical_run_id,
            )
        return RunListPage(items, next_cursor)

    def _view(
        self,
        artifact_id: ArtifactId,
        *,
        # Direct get has no expected row; list queries always provide one.
        expected: RunIndexEntry | None = None,
    ) -> RunSummaryView:
        """Authenticate one selected manifest and compare indexed ordering metadata."""

        details = self._artifacts.details(artifact_id)
        if details.descriptor.kind is not ArtifactKind.RUN:
            raise ArtifactQueryError("ARTIFACT_IS_NOT_A_RUN")
        try:
            manifest = successful_run_manifest_from_bytes(details.manifest_bytes)
            if details.descriptor.input_artifact_ids != manifest.input_artifact_ids:
                raise ValueError("run descriptor input closure differs from its manifest")
            # SQLite is only a projection; selected fields must match authoritative bytes.
            if expected is not None and not _matches_index(expected, details.descriptor, manifest):
                raise RunIndexQueryError
            return RunSummaryView(
                run_artifact_id=details.descriptor.artifact_id,
                logical_run_id=manifest.logical_run_id,
                execution_attempt_id=manifest.execution_attempt_id,
                # Comparison and settings are bounded immutable manifest projections.
                comparison=manifest.comparison,
                physical_settings=manifest.physical_settings,
                # Operational fields remain visible without entering artifact identity.
                canonicality=manifest.canonicality,
                started_at=manifest.started_at,
                completed_at=manifest.completed_at,
                warnings=manifest.warnings,
            )
        except RunIndexQueryError:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise ArtifactQueryError("RUN_MANIFEST_INVALID") from error


def _matches_index(
    expected: RunIndexEntry,
    descriptor: CommittedArtifact,
    manifest: SuccessfulRunManifest,
) -> bool:
    """Compare projection fields without trusting SQLite timestamp or identity values."""

    return (
        expected.artifact_id == descriptor.artifact_id
        and expected.manifest_digest == descriptor.manifest_digest
        and expected.logical_run_id == manifest.logical_run_id
        and expected.execution_attempt_id == manifest.execution_attempt_id
        # Integer UTC epochs avoid accepting alternate timestamp text orderings.
        and expected.started_at_ns == _datetime_epoch_ns(manifest.started_at)
        and expected.completed_at_ns == _datetime_epoch_ns(manifest.completed_at)
    )


def _validate_run_page(
    entries: tuple[RunIndexEntry, ...],
    *,
    logical_run_id: LogicalRunId | None,
    after: RunListCursor | None,
) -> None:
    """Reject adapter output that violates scope or mixed-direction ordering."""

    if logical_run_id is not None and any(
        item.logical_run_id != logical_run_id for item in entries
    ):
        raise RunIndexQueryError
    # Completion descends; an equal-completion artifact ID ascends.
    if any(not _run_entry_follows(left, right) for left, right in pairwise(entries)):
        raise RunIndexQueryError
    if after is None or not entries:
        return
    # The first row must be strictly later in canonical order than the cursor key.
    cursor_entry = entries[0]
    if not (
        cursor_entry.completed_at_ns < after.completed_at_ns
        or (
            cursor_entry.completed_at_ns == after.completed_at_ns
            and cursor_entry.artifact_id.hex > after.artifact_id.hex
        )
    ):
        raise RunIndexQueryError


def _run_entry_follows(left: RunIndexEntry, right: RunIndexEntry) -> bool:
    """Return whether ``right`` follows ``left`` in canonical Run order."""

    if right.completed_at_ns < left.completed_at_ns:
        return True
    return (
        right.completed_at_ns == left.completed_at_ns
        and right.artifact_id.hex > left.artifact_id.hex
    )


def _datetime_epoch_ns(value: datetime) -> int:
    """Convert an aware canonical Run time to exact integer epoch nanoseconds."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Run index timestamp must be timezone-aware")
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = value.astimezone(UTC) - epoch
    # Manifest timestamps have microsecond precision, so this conversion stays exact.
    whole_seconds = delta.days * 86_400 + delta.seconds
    return whole_seconds * 1_000_000_000 + delta.microseconds * 1_000


__all__ = ["QueryRuns", "RunIndexQueryError", "RunListPage", "RunSummaryView"]
