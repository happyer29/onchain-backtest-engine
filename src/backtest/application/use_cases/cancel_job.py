"""Request durable cancellation through the local job command port."""

from __future__ import annotations

from dataclasses import dataclass

from backtest.application.errors import JobNotFoundError, JobStateConflictError
from backtest.application.models import AttemptState, JobRecord
from backtest.application.ports.jobs import JobQuery, JobQueue

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import JobId

_NON_CANCELLABLE_TERMINAL_STATES = frozenset(
    {
        AttemptState.SUCCEEDED,
        AttemptState.FAILED,
        # Pass attempt state explicitly so frozenset receives a reviewable succeeded and
        # failed input in module.
        AttemptState.INTERRUPTED,
    }
)


@dataclass(frozen=True, slots=True)
class CancelJobRequest:
    # Declare job id explicitly in the cancel job request contract.
    job_id: JobId


# Keep the cancel job contract and validation rules together.
class CancelJob:
    def __init__(self, queue: JobQueue, query: JobQuery) -> None:
        # Execute the cancel job init workflow in explicit, reviewable steps.
        self._queue = queue
        self._query = query

    def execute(self, request: CancelJobRequest) -> JobRecord:
        # Execute the cancel job execute workflow in explicit, reviewable steps.
        current = self._query.get_job(request.job_id)
        if current is None:
            raise JobNotFoundError(request.job_id)
        if current.state is AttemptState.CANCELLED:
            return current
        # Evaluate the complete cancel job execute state, non cancellable terminal states
        # and current condition before guarded effects.
        if current.state in _NON_CANCELLABLE_TERMINAL_STATES:
            raise JobStateConflictError(request.job_id, current.state, "cancel")

        # The port performs the durable compare-and-set.  A concurrent terminal
        # transition must surface as the same stable application conflict.
        self._queue.request_cancel(request.job_id)
        updated = self._query.get_job(request.job_id)
        if updated is None:
            raise JobNotFoundError(request.job_id)
        return updated


# Bind all once as an explicit module-level contract.
__all__ = ["CancelJob", "CancelJobRequest"]
