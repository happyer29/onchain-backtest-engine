"""Replaceable compiler seam for materialized observation delivery streams."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from backtest.application.delivery_schedules import (
    CompiledDeliverySchedule,
    CompileDeliveryScheduleRequest,
    # Close the delivery schedules import after its required symbols are visible.
)


# Keep the delivery schedule compiler contract and validation rules together.
@runtime_checkable
class DeliveryScheduleCompiler(Protocol):
    def compile(
        self,
        request: CompileDeliveryScheduleRequest,
        # Keep the compiled delivery schedule step explicit within the delivery schedule
        # compiler compile workflow.
    ) -> CompiledDeliverySchedule: ...


__all__ = ["DeliveryScheduleCompiler"]
