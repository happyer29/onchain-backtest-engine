"""Bounded read-only job queries for CLI and Control API adapters."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from backtest.application.errors import JobNotFoundError
from backtest.application.models import AttemptState, JobRecord, ListJobsRequest
from backtest.application.ports.jobs import JobListCursor, JobQuery

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import JobId


@dataclass(frozen=True, slots=True)
class GetJobRequest:
    job_id: JobId


@dataclass(frozen=True, slots=True)
class JobListPage:
    """One bounded page plus an exclusive server-issued continuation key."""

    items: tuple[JobRecord, ...]
    next_cursor: JobListCursor | None

    def __post_init__(self) -> None:
        """Keep application output inside the public job-page bound."""

        if len(self.items) > 1_000:
            raise ValueError("job page contains more than 1000 records")


# Keep the get job contract and validation rules together.
class GetJob:
    def __init__(self, query: JobQuery) -> None:
        self._query = query

    def execute(self, request: GetJobRequest) -> JobRecord:
        # Execute the get job execute workflow in explicit, reviewable steps.
        record = self._query.get_job(request.job_id)
        if record is None:
            raise JobNotFoundError(request.job_id)
        return record


# Keep the list jobs contract and validation rules together.
class ListJobs:
    def __init__(self, query: JobQuery) -> None:
        self._query = query

    def execute(self, request: ListJobsRequest) -> tuple[JobRecord, ...]:
        # Execute the list jobs execute workflow in explicit, reviewable steps.
        return self._query.list_jobs(
            state=request.state,
            limit=request.limit,
            offset=request.offset,
        )

    def page(
        self,
        *,
        state: AttemptState | None,
        limit: int,
        offset: int = 0,
        after: JobListCursor | None = None,
    ) -> JobListPage:
        """Read a stable keyset page while retaining a bounded offset fallback."""

        # Reuse the external list bounds before requesting one internal lookahead row.
        request = ListJobsRequest(state=state, limit=limit, offset=offset)
        if after is not None and (offset != 0 or after.state is not state):
            raise ValueError("job cursor must match the filter and cannot use offset")
        records = self._query.list_jobs(
            state=request.state,
            limit=request.limit + 1,
            offset=request.offset,
            # The adapter compares only this typed key, never client-provided SQL.
            after=after,
        )
        if len(records) > request.limit + 1:
            raise ValueError("job query returned more than its bounded lookahead")
        # Verify the port preserved both filtering and canonical newest-first order.
        _validate_job_page(records, state=state, after=after)
        items = records[: request.limit]
        next_cursor = None
        # A hidden lookahead row proves that another page exists.
        if len(records) > request.limit:
            last = items[-1]
            next_cursor = JobListCursor(state, last.submitted_at_ns, last.job_id)
        return JobListPage(items, next_cursor)


def _validate_job_page(
    records: tuple[JobRecord, ...],
    *,
    state: AttemptState | None,
    after: JobListCursor | None,
) -> None:
    """Fail closed if a query adapter violates filter or cursor ordering."""

    if state is not None and any(record.state is not state for record in records):
        raise ValueError("job query returned a record outside the state filter")
    keys = tuple((record.submitted_at_ns, record.job_id.value) for record in records)
    # Both tuple fields are descending in the canonical job-list order.
    if any(left <= right for left, right in pairwise(keys)):
        raise ValueError("job query did not preserve canonical newest-first order")
    if after is None or not keys:
        return
    # An exclusive cursor cannot repeat or move before its prior boundary.
    cursor_key = (after.submitted_at_ns, after.job_id.value)
    if keys[0] >= cursor_key:
        raise ValueError("job query did not resume strictly after the cursor")


# Bind all once as an explicit module-level contract.
__all__ = ["GetJob", "GetJobRequest", "JobListPage", "ListJobs"]
