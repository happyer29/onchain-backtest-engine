"""Compile one verified canonical snapshot into a derived ReplayPack."""

from __future__ import annotations

from dataclasses import dataclass

from backtest.application.errors import WorkflowNotImplementedError
from backtest.application.ports.replay_pack import ReplayPackCompiler
from backtest.application.replay_packs import CompiledReplayPack

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import SnapshotId


# Keep the compile replay request contract and validation rules together.
@dataclass(frozen=True, slots=True)
class CompileReplayRequest:
    snapshot_id: SnapshotId
    compiler_version: str

    def __post_init__(self) -> None:
        # Execute the compile replay request post init workflow in explicit, reviewable
        # steps.
        if not self.compiler_version or self.compiler_version != self.compiler_version.strip():
            raise ValueError("compiler_version must be non-empty and trimmed")


class CompileReplay:
    """Application orchestration with an explicit fail-closed unwired state."""

    def __init__(self, compiler: ReplayPackCompiler | None = None) -> None:
        self._compiler = compiler

    def execute(self, request: CompileReplayRequest) -> CompiledReplayPack:
        # Execute the compile replay execute workflow in explicit, reviewable steps.
        if self._compiler is None:
            # Handle the compile replay execute self._compiler is None branch as a
            # distinct logical block.
            raise WorkflowNotImplementedError(
                "compile-replay",
                required_architecture_sections=(14, 15, 18, 19),
            )
        return self._compiler.compile(request.snapshot_id, request.compiler_version)


# Bind all once as an explicit module-level contract.
__all__ = ["CompileReplay", "CompileReplayRequest"]
