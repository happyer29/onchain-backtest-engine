"""Bounded operational event history for polling/SSE adapters."""

from __future__ import annotations

from backtest.application.errors import JobNotFoundError
from backtest.application.models import JobEventRecord, ListJobEventsRequest
from backtest.application.ports.jobs import JobEventQuery, JobQuery


# Keep the list job events contract and validation rules together.
class ListJobEvents:
    def __init__(self, events: JobEventQuery, jobs: JobQuery) -> None:
        # Execute the list job events init workflow in explicit, reviewable steps.
        self._events = events
        self._jobs = jobs

    def execute(self, request: ListJobEventsRequest) -> tuple[JobEventRecord, ...]:
        # Execute the list job events execute workflow in explicit, reviewable steps.
        if self._jobs.get_job(request.job_id) is None:
            raise JobNotFoundError(request.job_id)
        return self._events.list_job_events(
            request.job_id,
            after_event_id=request.after_event_id,
            # Pass limit explicitly so list_job_events receives a reviewable job id and
            # after event id input in list job events execute.
            limit=request.limit,
        )


__all__ = ["ListJobEvents"]
