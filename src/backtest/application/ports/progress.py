"""Rate-limited operational progress boundary."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from backtest.application.models import ProgressEvent


@runtime_checkable
class ProgressSink(Protocol):
    # Define progress sink publish as one focused operation with an explicit boundary.
    def publish(self, event: ProgressEvent) -> None: ...


__all__ = ["ProgressSink"]
