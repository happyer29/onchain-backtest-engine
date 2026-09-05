"""Resolver seam from a typed draft to an immutable executable specification."""

from __future__ import annotations

from typing import Protocol

from backtest.application.run_drafts import RunDraft
from backtest.application.run_specs import ResolvedRunSpec


class RunSpecResolver(Protocol):
    # Define run spec resolver resolve as one focused operation with an explicit boundary.
    def resolve(self, draft: RunDraft) -> ResolvedRunSpec: ...


__all__ = ["RunSpecResolver"]
