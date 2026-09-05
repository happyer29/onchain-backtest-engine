"""Controller-side resolution of public prepare commands."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from backtest.application.job_commands import (
    PrepareDatasetJobDraft,
    ResolvedPrepareDatasetJob,
    # Close the job commands import after its required symbols are visible.
)


@runtime_checkable
class PrepareDatasetJobResolver(Protocol):
    """Select exact reusable inputs before a command crosses the queue port."""

    def resolve(self, draft: PrepareDatasetJobDraft) -> ResolvedPrepareDatasetJob: ...


__all__ = ["PrepareDatasetJobResolver"]
