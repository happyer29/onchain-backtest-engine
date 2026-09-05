"""Replaceable compiler seam for derived ReplayPack artifacts."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from backtest.application.replay_packs import CompiledReplayPack
from backtest.domain.identifiers import SnapshotId


# Keep the replay pack compiler contract and validation rules together.
@runtime_checkable
class ReplayPackCompiler(Protocol):
    def compile(
        self,
        snapshot_id: SnapshotId,
        # Keep the compiler version input explicit in the compile contract.
        compiler_version: str,
    ) -> CompiledReplayPack: ...


__all__ = ["ReplayPackCompiler"]
