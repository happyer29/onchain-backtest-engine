"""React comparison vocabulary stays synchronized with the application-owned allowlist.

Interaction/order/cancellation checks moved to frontend/src/*.test.tsx and Playwright.
"""

import json
from pathlib import Path

from backtest.application.run_results import RunComparisonMetric


def test_react_comparison_uses_the_complete_closed_metric_allowlist() -> None:
    """Adding a metric to either side requires a deliberate synchronized UI contract change."""
    root = Path(__file__).parents[3]
    metrics = json.loads((root / "frontend/src/comparison-metrics.json").read_text())
    assert len(metrics) == len(set(metrics))
    assert set(metrics) == {metric.value for metric in RunComparisonMetric}


def test_react_types_are_generated_from_the_current_api_contract(tmp_path: Path) -> None:
    """Schema drift cannot silently desynchronize Python DTOs and typed React clients."""
    import test_api as fixture

    root = Path(__file__).parents[3]
    stored = json.loads((root / "frontend/src/generated/openapi.json").read_text())
    current = fixture._client(tmp_path).app.openapi()
    # Compare the normative transport surface; test/default server title is identical.
    assert stored["components"] == current["components"]
    assert stored["paths"] == current["paths"]
