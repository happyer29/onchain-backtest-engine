"""Manually requeue a failed or interrupted immutable job command."""

from __future__ import annotations

from dataclasses import dataclass

from backtest.application.models import JobRecord
from backtest.application.ports.jobs import JobRetryQueue
from backtest.domain.identifiers import JobId


# Apply dataclass semantics to the following retry job request contract.
@dataclass(frozen=True, slots=True)
class RetryJobRequest:
    job_id: JobId


# Keep the retry job contract and validation rules together.
class RetryJob:
    def __init__(self, queue: JobRetryQueue) -> None:
        self._queue = queue

    def execute(self, request: RetryJobRequest) -> JobRecord:
        return self._queue.request_retry(request.job_id)


# Bind all once as an explicit module-level contract.
__all__ = ["RetryJob", "RetryJobRequest"]
