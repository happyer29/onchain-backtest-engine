"""Exact physical schema for observation DeliverySchedule NumPy mmap v1."""

from __future__ import annotations

from typing import Final

from backtest.application.delivery_schedules import DeliveryLayoutManifest
from backtest.application.replay_packs import ReplayArrayLayout

COMPILER_VERSION: Final = "numpy-delivery-mmap-v1"

# Bind event row index once as an explicit module-level contract.
EVENT_ROW_INDEX: Final = "schedule/event_row_index.npy"
RELEASE_BOUNDARY_ORDINAL: Final = "schedule/release_boundary_ordinal.npy"


def build_layout(delivery_count: int) -> DeliveryLayoutManifest:
    # Execute the build layout workflow in explicit, reviewable steps.
    if (
        isinstance(delivery_count, bool)
        or not isinstance(delivery_count, int)
        or delivery_count < 0
    ):
        # Fail the build layout path with ValueError for delivery count must be a non-
        # negative integer when isinstance and delivery count is true; do not continue
        # ambiguously.
        raise ValueError("delivery_count must be a non-negative integer")
    arrays = (
        ReplayArrayLayout(
            path=EVENT_ROW_INDEX,
            dtype="<u8",
            # Pass byte order explicitly so ReplayArrayLayout receives a reviewable <u8
            # and little input in build layout.
            byte_order="little",
            shape=(delivery_count,),
            role="delivery.event_row_index",
            overflow_policy="checked-uint64-v1",
        ),
        # Register replay array layout and release boundary ordinal through
        # ReplayArrayLayout so the arrays table remains scannable.
        ReplayArrayLayout(
            path=RELEASE_BOUNDARY_ORDINAL,
            dtype="<u8",
            byte_order="little",
            shape=(delivery_count,),
            # Pass role explicitly so ReplayArrayLayout receives a reviewable <u8 and
            # little input in build layout.
            role="delivery.release_boundary_ordinal",
            overflow_policy="checked-uint64-v1",
        ),
    )
    return DeliveryLayoutManifest(arrays=arrays)


# Bind all once as an explicit module-level contract.
__all__ = [
    "COMPILER_VERSION",
    "EVENT_ROW_INDEX",
    "RELEASE_BOUNDARY_ORDINAL",
    "build_layout",
    # Complete the all group only after its semantic components are visible.
]
