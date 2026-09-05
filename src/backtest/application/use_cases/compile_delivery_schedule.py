"""Compile an optional materialized observation-delivery stream."""

from __future__ import annotations

from backtest.application.delivery_schedules import (
    CompiledDeliverySchedule,
    CompileDeliveryScheduleRequest,
)

# Import errors at the visible module dependency boundary.
from backtest.application.errors import WorkflowNotImplementedError
from backtest.application.ports.delivery_schedule import DeliveryScheduleCompiler


# Keep the compile delivery schedule contract and validation rules together.
class CompileDeliverySchedule:
    def __init__(self, compiler: DeliveryScheduleCompiler | None = None) -> None:
        self._compiler = compiler

    def execute(
        self,
        # Keep the request input explicit in the execute contract.
        request: CompileDeliveryScheduleRequest,
    ) -> CompiledDeliverySchedule:
        # Execute the compile delivery schedule execute workflow in explicit, reviewable
        # steps.
        if self._compiler is None:
            # Handle the compile delivery schedule execute self._compiler is None branch
            # as a distinct logical block.
            raise WorkflowNotImplementedError(
                "compile-delivery-schedule",
                required_architecture_sections=(20, 21, 25),
            )
        return self._compiler.compile(request)


# Bind all once as an explicit module-level contract.
__all__ = ["CompileDeliverySchedule", "CompileDeliveryScheduleRequest"]
