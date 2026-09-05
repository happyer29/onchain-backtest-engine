"""Read-only point-in-time scalar overlays exposed to strategies."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


# Keep the causal scalar provider contract and validation rules together.
@runtime_checkable
class CausalScalarProvider(Protocol):
    def value_at(
        self,
        name: str,
        # Keep the entity id input explicit in the value at contract.
        entity_id: int,
        boundary_ordinal: int,
    ) -> int | None: ...


# Keep the empty causal scalar provider contract and validation rules together.
class EmptyCausalScalarProvider:
    def value_at(
        self,
        name: str,
        entity_id: int,
        # Keep the boundary ordinal input explicit in the value at contract.
        boundary_ordinal: int,
    ) -> None:
        # Execute the empty causal scalar provider value at workflow in explicit,
        # reviewable steps.
        del name, entity_id, boundary_ordinal
        return None


class CausalScalarView:
    """A boundary-bound facade that cannot request future state."""

    def __init__(
        self,
        provider: CausalScalarProvider,
        boundary_ordinal: int,
        *,
        # Keep the bound entity id input explicit in the init contract.
        bound_entity_id: int | None = None,
    ) -> None:
        # Execute the causal scalar view init workflow in explicit, reviewable steps.
        if boundary_ordinal < 0:
            raise ValueError("view boundary must be non-negative")
        self._provider = provider
        self._boundary_ordinal = boundary_ordinal
        if bound_entity_id is not None and bound_entity_id < 0:
            # Fail the causal scalar view init path with ValueError for bound entity id
            # must be non-negative when bound entity id is true; do not continue
            # ambiguously.
            raise ValueError("bound entity ID must be non-negative")
        self._bound_entity_id = bound_entity_id

    def value(self, name: str, entity_id: int) -> int | None:
        # Execute the causal scalar view value workflow in explicit, reviewable steps.
        if not name or name != name.strip():
            raise ValueError("scalar name must be non-empty and trimmed")
        if entity_id < 0:
            raise ValueError("entity_id must be non-negative")
        return self._provider.value_at(name, entity_id, self._boundary_ordinal)

    # Define causal scalar view current as one focused operation with an explicit
    # boundary.
    def current(self, name: str) -> int | None:
        """Read the scalar aligned to the current replay event, if one is bound."""

        if self._bound_entity_id is None:
            raise RuntimeError("causal scalar view is not bound to a current event row")
        return self.value(name, self._bound_entity_id)


# Keep the causal scalar row contract and validation rules together.
@dataclass(frozen=True, slots=True, order=True)
class CausalScalarRow:
    name: str
    entity_id: int
    available_boundary_ordinal: int
    # Declare value explicitly in the causal scalar row contract.
    value: int | None

    def __post_init__(self) -> None:
        # Execute the causal scalar row post init workflow in explicit, reviewable steps.
        if not self.name or self.name != self.name.strip():
            raise ValueError("scalar name must be non-empty and trimmed")
        if self.entity_id < 0 or self.available_boundary_ordinal < 0:
            raise ValueError("scalar coordinates must be non-negative")
        if self.value is not None and (
            # Keep isinstance visible while evaluating the value and isinstance guard.
            isinstance(self.value, bool) or not isinstance(self.value, int)
        ):
            raise TypeError("causal scalar values must be integers or None")


class InMemoryCausalScalarProvider:
    """Reference implementation with as-of lookup and no future fallback."""

    def __init__(self, rows: tuple[CausalScalarRow, ...]) -> None:
        # Execute the in memory causal scalar provider init workflow in explicit,
        # reviewable steps.
        ordered = tuple(
            sorted(
                rows,
                key=lambda item: (
                    item.name,
                    # Pass item explicitly so sorted receives a reviewable name and entity
                    # id input in in memory causal scalar provider init.
                    item.entity_id,
                    item.available_boundary_ordinal,
                ),
            )
        )
        # Guard this path with ordered != rows before applying effects.
        if ordered != rows:
            raise ValueError("causal scalar rows must be in canonical order")
        keys = tuple((item.name, item.entity_id, item.available_boundary_ordinal) for item in rows)
        if len(keys) != len(set(keys)):
            raise ValueError("causal scalar coordinates must be unique")
        # Assemble grouped once so the in memory causal scalar provider init workflow
        # shares one value.
        grouped: dict[tuple[str, int], tuple[CausalScalarRow, ...]] = {}
        for row in rows:
            # Process rows inside the bounded in memory causal scalar provider init loop.
            key = (row.name, row.entity_id)
            grouped[key] = (*grouped.get(key, ()), row)
        self._rows = grouped

    def value_at(self, name: str, entity_id: int, boundary_ordinal: int) -> int | None:
        # Execute the in memory causal scalar provider value at workflow in explicit,
        # reviewable steps.
        if boundary_ordinal < 0:
            raise ValueError("decision boundary must be non-negative")
        rows = self._rows.get((name, entity_id), ())
        ordinals = tuple(item.available_boundary_ordinal for item in rows)
        position = bisect_right(ordinals, boundary_ordinal) - 1
        # Return the completed in memory causal scalar provider value at result without a
        # hidden fallback.
        return None if position < 0 else rows[position].value


__all__ = [
    "CausalScalarProvider",
    "CausalScalarRow",
    "CausalScalarView",
    # Keep the empty causal scalar provider component named inside the all contract.
    "EmptyCausalScalarProvider",
    "InMemoryCausalScalarProvider",
]
