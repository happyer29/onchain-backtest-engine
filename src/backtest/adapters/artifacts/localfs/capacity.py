"""Local data-root disk-capacity probe."""

from __future__ import annotations

import shutil
from pathlib import Path

from backtest.application.models import DiskCapacity


# Keep the local disk capacity probe contract and validation rules together.
class LocalDiskCapacityProbe:
    def __init__(self, data_root: Path) -> None:
        self._data_root = data_root

    def capacity(self) -> DiskCapacity:
        # Execute the local disk capacity probe capacity workflow in explicit, reviewable
        # steps.
        probe = self._data_root
        while not probe.exists():
            # Keep the not probe.exists() loop body bounded within local disk capacity
            # probe capacity.
            parent = probe.parent
            if parent == probe:
                raise FileNotFoundError(self._data_root)
            probe = parent
        return DiskCapacity(free_bytes=shutil.disk_usage(probe).free)


# Bind all once as an explicit module-level contract.
__all__ = ["LocalDiskCapacityProbe"]
