"""Infrastructure-neutral helpers shared by concrete source adapters.

The application port intentionally does not prescribe a row or column-buffer
representation.  ``SourceBatch`` is the small reference representation used by
the in-memory adapter and the first ClickHouse vertical slice.  A future Arrow
batch can implement the same port without changing application or domain code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backtest.domain.identifiers import CapabilityId, ContentDigest
from backtest.domain.time import BlockRange


# Keep the source adapter error contract and validation rules together.
class SourceAdapterError(RuntimeError):
    """A public, credential-free adapter failure.

    The original driver exception is deliberately not chained.  Driver errors
    can contain a request URL, credentials or rendered query parameters.
    """

    def __init__(self, operation: str, query_id: str | None = None) -> None:
        # Execute the source adapter error init workflow in explicit, reviewable steps.
        self.operation = operation
        self.query_id = query_id
        suffix = f" (query_id={query_id})" if query_id is not None else ""
        super().__init__(f"Source {operation} failed{suffix}; driver details were suppressed.")


@dataclass(frozen=True, slots=True)
# Keep the source batch contract and validation rules together.
class SourceBatch:
    """A bounded immutable row batch owned by the adapter layer."""

    capability_id: CapabilityId
    covered_range: BlockRange
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    query_fingerprint: ContentDigest | None = None

    # Define source batch post init as one focused operation with an explicit boundary.
    def __post_init__(self) -> None:
        # Execute the source batch post init workflow in explicit, reviewable steps.
        if not self.columns:
            raise ValueError("a source batch must have at least one column")
        if len(set(self.columns)) != len(self.columns):
            raise ValueError("source batch columns must be unique")
        width = len(self.columns)
        # Evaluate the complete source batch post init width, row and rows condition
        # before guarded effects.
        if any(len(row) != width for row in self.rows):
            raise ValueError("source batch row width does not match columns")

    @property
    def row_count(self) -> int:
        return len(self.rows)


# Bind all once as an explicit module-level contract.
__all__ = ["SourceAdapterError", "SourceBatch"]
