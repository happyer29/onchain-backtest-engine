"""Resolve one typed convenience draft into an immutable executable RunSpec."""

from __future__ import annotations

from backtest.application.ports.run_resolver import RunSpecResolver
from backtest.application.run_drafts import RunDraft
from backtest.application.run_specs import ResolvedRunSpec


# Keep the resolve run spec contract and validation rules together.
class ResolveRunSpec:
    def __init__(self, resolver: RunSpecResolver) -> None:
        self._resolver = resolver

    def execute(self, draft: RunDraft) -> ResolvedRunSpec:
        return self._resolver.resolve(draft)


# Bind all once as an explicit module-level contract.
__all__ = ["ResolveRunSpec"]
