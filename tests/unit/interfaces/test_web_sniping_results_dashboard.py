from __future__ import annotations

from pathlib import Path


def _static_root() -> Path:
    return (
        Path(__file__).resolve().parents[3] / "src" / "backtest" / "interfaces" / "web" / "static"
    )


def test_dashboard_is_separate_source_backed_and_bounded() -> None:
    static = _static_root()
    markup = (static / "sniping-results.html").read_text(encoding="utf-8")
    script = (static / "sniping-results.js").read_text(encoding="utf-8")

    assert "Sniping result" in markup
    assert 'src="/static/sniping-results.js"' in markup
    assert 'id="dashboard-kpis"' in markup
    assert 'id="dashboard-roundtrips-body"' in markup
    for chart_id in (
        "lifecycle-chart",
        "orders-chart",
        "pnl-chart",
        "fees-chart",
        "deposits-chart",
        "settlement-chart",
        "slippage-chart",
    ):
        assert f'id="{chart_id}"' in markup

    assert "const RUN_ARTIFACT_ID = /^[0-9a-f]{64}$/" in script
    assert "const ROUNDTRIP_PAGE_LIMIT = 200" in script
    assert "/api/v1/run-artifacts/${encodedArtifactId}/dashboard" in script
    assert "/api/v1/run-artifacts/${encodeURIComponent(artifactId)}/roundtrips" in script
    assert "const DEFAULT_ROUNDTRIP_PAGE_SIZE = 25" in script
    assert "let currentRoundtripPage = null" in script
    assert "pageStartCursors = [null]" in script
    assert 'params.set("after_target_boundary_ordinal"' in script
    assert 'params.set("after_roundtrip_id"' in script
    assert "page.next_cursor === null" in script
    assert "new AbortController()" in script
    assert "ROUNDTRIP_SORT_FIELDS" in script
    assert 'heading.scope = "row"' in script
    assert 'aria-labelledby="dashboard-trades-heading"' in markup
    assert 'aria-labelledby="dashboard-verification-heading"' in markup

    load_body = script.split("async function loadDashboard", 1)[1].split(
        "async function openArtifactFromInput",
        1,
    )[0]
    # Request ownership must change before an invalid new artifact can throw.
    assert load_body.index("supersedeDashboardRequests()") < load_body.index("RUN_ARTIFACT_ID.test")

    popstate_body = script.split('globalThis.addEventListener("popstate"', 1)[1].split(
        "// Deep links open",
        1,
    )[0]
    assert "supersedeDashboardRequests();\n    showError(error);" in popstate_body

    chart_renderer = script.split("function renderCharts", 1)[1].split(
        "function appendVerificationRow", 1
    )[0]
    assert "fetch(" not in chart_renderer
    assert "roundtrips" not in chart_renderer.casefold()
    assert "summary.protocol_fee_paid_atomic" in chart_renderer
    assert "summary.closed_position_count" in chart_renderer
    assert "summary.favorable_slippage_count" in chart_renderer
    assert "summary.synthetic_funded_sell_atomic" in chart_renderer
    assert "validateSettlementSummary(summary)" in script
    assert "validateRoundtripSettlement(item)" in script
    assert "Sell settlement" in script


def test_dashboard_keeps_atomic_and_partial_valuation_semantics_lossless() -> None:
    script = (_static_root() / "sniping-results.js").read_text(encoding="utf-8")

    assert "BigInt(value)" in script
    assert "LAMPORTS_PER_SOL = 1_000_000_000n" in script
    assert "parseFloat" not in script
    assert "parseInt" not in script
    assert "Number(summary." not in script
    assert "summary.economic_pnl_atomic === null" in script
    assert 'economic === null ? "Недоступно"' in script
    assert "Valued economic subtotal" in script
    assert "account_deposit_paid_atomic" in script
    assert "account_deposit_refunded_atomic" in script
    assert "account_deposit_locked_atomic" in script


def test_dashboard_uses_safe_dom_and_csp_compatible_charts() -> None:
    script = (_static_root() / "sniping-results.js").read_text(encoding="utf-8")

    assert "createElementNS" in script
    assert "textContent" in script
    assert "replaceChildren" in script
    for forbidden in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.cookie",
        "eval(",
        ".style.",
        "https://",
    ):
        assert forbidden not in script
    assert script.count("http://") == 1
    assert 'SVG_NAMESPACE = "http://www.w3.org/2000/svg"' in script
    # Generated SVG names include every plotted label/value pair as a text fallback.
    assert "`${ariaLabel}. ${accessibleValues}`" in script
