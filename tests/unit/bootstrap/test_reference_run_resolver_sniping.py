# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository

# Import bootstrap at the visible module dependency boundary.
from backtest.bootstrap import reference_run_resolver as resolver_module
from backtest.bootstrap.reference_run_resolver import ReferenceRunSpecResolver
from backtest.domain.identifiers import BundleId, RuntimeLockId


def test_reference_resolver_forwards_projector_identity_to_default_sniping_resolver(
    tmp_path: Path,
    # Keep the monkeypatch input explicit in the test reference resolver forwards
    # projector identity to default sniping resolver contract.
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test reference resolver forwards projector identity to default sniping
    # resolver workflow in explicit, reviewable steps.
    expected = BundleId("a" * 64)
    captured: dict[str, Any] = {}

    class _StubSnipingResolver:
        pass

    def capture(*args: object, **kwargs: object) -> _StubSnipingResolver:
        # Execute the capture workflow in explicit, reviewable steps.
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _StubSnipingResolver()

    monkeypatch.setattr(resolver_module, "PumpfunSnipingRunSpecResolver", capture)
    artifacts = LocalArtifactRepository(tmp_path / "var")

    # Invoke ReferenceRunSpecResolver for 9 and runtime lock id as a visible test
    # reference resolver forwards projector identity to default sniping resolver step.
    ReferenceRunSpecResolver(
        artifacts,
        RuntimeLockId("9" * 64),
        parquet_memory_limit_mb=256,
        threads=1,
        # Pass expected projector bundle id explicitly so ReferenceRunSpecResolver
        # receives a reviewable 9 and runtime lock id input in test reference resolver
        # forwards projector identity to default sniping resolver.
        expected_projector_bundle_id=expected,
    )

    assert captured["args"][:2] == (artifacts, RuntimeLockId("9" * 64))
    assert captured["kwargs"]["expected_projector_bundle_id"] == expected
