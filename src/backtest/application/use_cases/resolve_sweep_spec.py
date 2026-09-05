"""Resolve typed run drafts into one immutable independent-run sweep."""

from __future__ import annotations

from dataclasses import dataclass

from backtest.application.ports.run_resolver import RunSpecResolver
from backtest.application.run_drafts import ReferenceRunDraft
from backtest.application.run_results import RunPhysicalSettings

# Import sweeps at the visible module dependency boundary.
from backtest.application.sweeps import ResolvedSweepSpec, SweepEntry
from backtest.domain.identifiers import ContentDigest


# Keep the sweep draft entry contract and validation rules together.
@dataclass(frozen=True, slots=True)
class SweepDraftEntry:
    draft: ReferenceRunDraft
    attempt_nonce: ContentDigest
    physical_settings: RunPhysicalSettings


# Keep the resolve sweep spec contract and validation rules together.
class ResolveSweepSpec:
    def __init__(self, resolver: RunSpecResolver) -> None:
        self._resolver = resolver

    def execute(
        self,
        # Keep the entries input explicit in the execute contract.
        entries: tuple[SweepDraftEntry, ...],
        *,
        comparison_metrics: tuple[str, ...] = (),
    ) -> ResolvedSweepSpec:
        # Execute the resolve sweep spec execute workflow in explicit, reviewable steps.
        if not entries:
            raise ValueError("a sweep draft requires at least one entry")
        resolved = tuple(
            SweepEntry(
                self._resolver.resolve(item.draft),
                # Pass item explicitly so SweepEntry receives a reviewable resolve and
                # draft input in resolve sweep spec execute.
                item.attempt_nonce,
                item.physical_settings,
            )
            for item in entries
        )
        # Return the completed resolve sweep spec execute result without a hidden
        # fallback.
        return ResolvedSweepSpec.create(resolved, comparison_metrics=comparison_metrics)


__all__ = ["ResolveSweepSpec", "SweepDraftEntry"]
