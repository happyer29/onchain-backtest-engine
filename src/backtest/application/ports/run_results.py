"""Replaceable verified readers for bounded successful-run result queries."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from backtest.application.run_results import SuccessfulRunManifest

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import ArtifactId, ContentDigest
from backtest.domain.roundtrips import RoundTripRecord
from backtest.engine.copytrading_results import CopyPositionRecord

MAX_ROUNDTRIP_PAGE_SIZE = 200


# Keep the round trip cursor contract and validation rules together.
@dataclass(frozen=True, slots=True, order=True)
class RoundTripCursor:
    target_boundary_ordinal: int
    roundtrip_id: ContentDigest

    def __post_init__(self) -> None:
        # Execute the round trip cursor post init workflow in explicit, reviewable steps.
        if (
            isinstance(self.target_boundary_ordinal, bool)
            or not isinstance(self.target_boundary_ordinal, int)
            or not 0 <= self.target_boundary_ordinal < 1 << 64
        ):
            # Fail the round trip cursor post init path with ValueError for round-trip
            # cursor boundary must fit uint64 when isinstance and target boundary ordinal
            # is true; do not continue ambiguously.
            raise ValueError("round-trip cursor boundary must fit UInt64")


# Keep the round trip page contract and validation rules together.
@dataclass(frozen=True, slots=True)
class RoundTripPage:
    items: tuple[RoundTripRecord | CopyPositionRecord, ...]
    next_cursor: RoundTripCursor | None

    def __post_init__(self) -> None:
        # Execute the round trip page post init workflow in explicit, reviewable steps.
        if len(self.items) > MAX_ROUNDTRIP_PAGE_SIZE:
            raise ValueError("round-trip page exceeds the bounded row limit")
        keys = tuple(
            (item.target_position.boundary_ordinal, item.roundtrip_id.hex) for item in self.items
        )
        # Guard this path with keys != tuple(sorted(set(keys))) before applying effects.
        if keys != tuple(sorted(set(keys))):
            raise ValueError("round-trip page rows must be strictly keyset ordered")
        if self.next_cursor is not None:
            # Handle the round trip page post init self.next_cursor is not None branch as
            # a distinct logical block.
            if not self.items:
                raise ValueError("an empty round-trip page cannot carry a next cursor")
            if self.next_cursor != RoundTripCursor(keys[-1][0], self.items[-1].roundtrip_id):
                raise ValueError("round-trip next cursor must identify the final returned row")


# Keep the verified run result reader contract and validation rules together.
@runtime_checkable
class VerifiedRunResultReader(Protocol):
    @property
    def manifest(self) -> SuccessfulRunManifest: ...

    def verify(self) -> None: ...

    # Define verified run result reader roundtrips as one focused operation with an
    # explicit boundary.
    def roundtrips(
        self,
        *,
        after: RoundTripCursor | None,
        limit: int,
        # Keep the round trip page step explicit within the verified run result reader
        # roundtrips workflow.
    ) -> RoundTripPage: ...


# Keep the run result reader factory contract and validation rules together.
@runtime_checkable
class RunResultReaderFactory(Protocol):
    def open_exact(
        self,
        artifact_id: ArtifactId,
        # Keep the abstract context manager step explicit within the run result reader factory
        # open exact workflow.
    ) -> AbstractContextManager[VerifiedRunResultReader]: ...


__all__ = [
    "MAX_ROUNDTRIP_PAGE_SIZE",
    "RoundTripCursor",
    "RoundTripPage",
    # Keep the run result reader factory component named inside the all contract.
    "RunResultReaderFactory",
    "VerifiedRunResultReader",
]
