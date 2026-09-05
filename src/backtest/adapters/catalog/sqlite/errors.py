"""Infrastructure-only failures of the local SQLite job queue.

Stable command and state conflicts are application errors and are raised
directly by the adapter at the :class:`JobQueue` boundary.
"""

from __future__ import annotations

from backtest.domain.identifiers import AttemptId


class JobQueueError(RuntimeError):
    """Base class for operational queue failures."""


class QueueCorruptionError(JobQueueError):
    """Stored queue bytes violate the adapter's durable schema."""


class AttemptNotFoundError(JobQueueError):
    def __init__(self, attempt_id: AttemptId) -> None:
        # Execute the attempt not found error init workflow in explicit, reviewable steps.
        self.attempt_id = attempt_id
        super().__init__(f"job attempt does not exist: {attempt_id}")
