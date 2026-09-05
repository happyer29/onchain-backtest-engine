"""Strategy plugin boundary without storage or transport knowledge."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from backtest.application.models import StrategyRequirements


# Keep the event view contract and validation rules together.
@runtime_checkable
class EventView(Protocol):
    @property
    def boundary_ordinal(self) -> int: ...

    @property
    # Define event view event kind as one focused operation with an explicit boundary.
    def event_kind(self) -> str: ...


@runtime_checkable
class StrategyContext(Protocol):
    @property
    def current_boundary_ordinal(self) -> int: ...


# Apply runtime checkable semantics to the following intent contract.
@runtime_checkable
class Intent(Protocol):
    @property
    def intent_kind(self) -> str: ...


# Keep the strategy contract and validation rules together.
@runtime_checkable
class Strategy(Protocol):
    def requirements(self) -> StrategyRequirements: ...

    def on_event(self, event: EventView, ctx: StrategyContext) -> Iterable[Intent]: ...


__all__ = ["EventView", "Intent", "Strategy", "StrategyContext"]
