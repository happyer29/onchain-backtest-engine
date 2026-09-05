# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

# Import pytest at the visible module dependency boundary.
import pytest

import backtest.bootstrap.supervisor as supervisor_module
from backtest.application.supervisor import HostResourceBudget
from backtest.bootstrap.config import PathSettings, Settings
from backtest.bootstrap.container import RuntimeContainer

# Import host resources at the visible module dependency boundary.
from backtest.runtime.host_resources import HostMemoryMeasurement


def test_supervisor_keeps_control_plane_available_with_zero_child_memory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test supervisor keeps control plane available with zero child memory
    # workflow in explicit, reviewable steps.
    data_root = tmp_path / "var"
    config_path = tmp_path / "local.toml"
    config_path.write_text("[paths]\ndata_root = 'var'\n", encoding="utf-8")
    settings = Settings(paths=PathSettings(data_root=data_root))
    container = cast(
        # Pass runtime container explicitly so cast receives a reviewable simple namespace
        # and mock input in test supervisor keeps control plane available with zero child
        # memory.
        RuntimeContainer,
        SimpleNamespace(
            settings=settings,
            artifacts=SimpleNamespace(data_root=data_root),
            catalog=Mock(),
            # Keep the mock Mock step visible while building container.
            jobs=Mock(),
        ),
    )
    gibibyte = 1024**3
    monkeypatch.setattr(
        # Pass supervisor module explicitly so setattr receives a reviewable measure host
        # memory and host memory measurement input in test supervisor keeps control plane
        # available with zero child memory.
        supervisor_module,
        "measure_host_memory",
        lambda: HostMemoryMeasurement(
            total_physical_bytes=16 * gibibyte,
            available_physical_bytes=1 * gibibyte,
            # Pass controller private rss bytes explicitly so HostMemoryMeasurement
            # receives a reviewable gibibyte input in test supervisor keeps control plane
            # available with zero child memory.
            controller_private_rss_bytes=64 * 1024**2,
        ),
    )
    captured: list[HostResourceBudget] = []

    def build_admission(budget: HostResourceBudget, **_: Any) -> Mock:
        # Execute the build admission workflow in explicit, reviewable steps.
        captured.append(budget)
        return Mock()

    monkeypatch.setattr(supervisor_module, "LocalAdmissionController", build_admission)
    authority = SimpleNamespace(
        instance_id="11111111-1111-4111-8111-111111111111",
        # Keep the mock Mock step visible while building authority.
        assert_held=Mock(),
    )

    built = supervisor_module.build_single_host_supervisor(
        container,
        authority=authority,
        # Pass config path explicitly so build_single_host_supervisor receives a
        # reviewable container and authority input in test supervisor keeps control plane
        # available with zero child memory.
        config_path=config_path,
        capabilities_file=None,
        working_directory=tmp_path,
    )

    assert built is not None
    # Verify len(captured) == 1 before this scenario is accepted.
    assert len(captured) == 1
    assert captured[0].private_memory_bytes == 0
    assert captured[0].max_children == settings.resources.max_parallel_runs
    assert captured[0].max_builders == 1
    assert captured[0].max_runs == settings.resources.max_parallel_runs
