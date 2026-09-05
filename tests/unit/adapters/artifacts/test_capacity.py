# Declare this module's dependencies and contracts before execution.
from pathlib import Path

from backtest.adapters.artifacts.localfs.capacity import LocalDiskCapacityProbe


def test_probe_uses_nearest_existing_parent(tmp_path: Path) -> None:
    # Execute the test probe uses nearest existing parent workflow in explicit, reviewable
    # steps.
    capacity = LocalDiskCapacityProbe(tmp_path / "not-created" / "var").capacity()

    assert capacity.free_bytes > 0
