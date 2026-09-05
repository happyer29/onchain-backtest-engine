"""Adapter-neutral typed replay boundary."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable


# Keep the boundary reader contract and validation rules together.
@runtime_checkable
class BoundaryReader(Protocol):
    @property
    def boundary_count(self) -> int: ...

    def boundary_ordinal(self, index: int) -> int: ...


# Keep the event batch contract and validation rules together.
@runtime_checkable
class EventBatch(Protocol):
    @property
    def row_count(self) -> int: ...

    @property
    # Define event batch first boundary ordinal as one focused operation with an explicit
    # boundary.
    def first_boundary_ordinal(self) -> int: ...

    @property
    def last_boundary_ordinal(self) -> int: ...


# Keep the replay source contract and validation rules together.
@runtime_checkable
class ReplaySource(Protocol):
    def boundaries(self) -> BoundaryReader: ...

    def event_batches(self) -> Iterator[EventBatch]: ...


__all__ = ["BoundaryReader", "EventBatch", "ReplaySource"]
