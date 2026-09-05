"""Static contract checks for bounded run comparison and list navigation."""

from __future__ import annotations

import re
from pathlib import Path

from backtest.application.run_results import RunComparisonMetric


def _static_root() -> Path:
    # Resolve packaged assets exactly as the API static-file mount does.
    return Path(__file__).parents[3] / "src" / "backtest" / "interfaces" / "web" / "static"


def test_web_ui_compares_the_closed_metric_allowlist_with_safe_text_rendering() -> None:
    # Compare the markup allowlist with the domain enum to prevent silent UI drift.
    script = (_static_root() / "app.js").read_text(encoding="utf-8")
    page = (_static_root() / "index.html").read_text(encoding="utf-8")

    metric_select = page.split('<select id="run-comparison-metric">', 1)[1].split("</select>", 1)[0]
    option_values = re.findall(r'<option value="([^"]+)">', metric_select)
    assert set(option_values) == {metric.value for metric in RunComparisonMetric}
    # Every metric appears once and result data reaches only safe text DOM sinks.
    assert len(option_values) == len(RunComparisonMetric)
    assert "run.comparison[metric]" in script
    assert "physical_settings: run.physical_settings" in script
    assert "canonicality: run.canonicality" in script
    assert "warnings: run.warnings" in script
    # Equality serialization and every DOM sink remain inert and deterministic.
    assert "JSON.stringify(item.value)" in script
    assert ".textContent" in script
    assert ".innerHTML" not in script
    assert "insertAdjacentHTML" not in script
    assert ".outerHTML" not in script


# Verify bounded list interaction separately from comparison metric rendering.
def test_web_ui_uses_bounded_reactive_date_first_lists() -> None:
    script = (_static_root() / "app.js").read_text(encoding="utf-8")
    page = (_static_root() / "index.html").read_text(encoding="utf-8")

    # Each list fetches only its visible page; the server owns the lookahead cursor.
    assert "const JOBS_PAGE_SIZE = 20" in script
    assert "const RUNS_PAGE_SIZE = 10" in script
    assert 'listPagePath("/api/v1/jobs", JOBS_PAGE_SIZE, requestedCursor)' in script
    assert 'listPagePath("/api/v1/runs", RUNS_PAGE_SIZE, requestedCursor)' in script
    assert "limit=${JOBS_PAGE_SIZE + 1}&offset=${offset}" not in script
    # Both list types expose explicit keyset page navigation controls.
    assert 'id="jobs-previous-page"' in page
    assert 'id="jobs-next-page"' in page
    assert "let jobsPageCursors = [null]" in script
    assert "let runsPageCursors = [null]" in script
    assert "jobsPageCursors[requestedPageIndex] = requestedCursor" in script
    assert "runsPageCursors[requestedPageIndex] = requestedCursor" in script

    # Page coordinates commit only after transport validation, so a failed arrow rolls back.
    jobs_refresh = script.split("async function refreshJobs", 1)[1].split(
        "// Redirect observation to page one", 1
    )[0]
    assert jobs_refresh.index("await api(") < jobs_refresh.index(
        "jobsPageIndex = requestedPageIndex"
    )
    assert (
        "jobsPageIndex = targetPageIndex"
        not in script.split('document.querySelector("#jobs-next-page")', 1)[1].split(
            "// Run sort changes", 1
        )[0]
    )

    # Dates are the default order and wording distinguishes submit from completion time.
    assert '<option value="submitted_at">Дата создания</option>' in page
    assert '<option value="completed_at">Дата завершения</option>' in page
    assert "глобально: сначала новые по завершению" in script
    assert "строк: ${rowCount}" in script
    assert 'class="job-updated-at"' in page
    assert "<th>Запущен</th>" in page

    # Slow reads are bounded and operational polling starts independently.
    assert "const API_TIMEOUT_MS = 15000" in script
    assert "scheduleJobPolling({ immediate: true })" in script
    assert "scheduleResourcePolling({ immediate: true })" in script
    assert 'selection.setAttribute("aria-label"' in script
    # Visiting historical job pages cannot masquerade as a new successful backtest.
    assert "jobsPageIndex === 0 && jobsInitialized" in script
    # FirstSwap and other Run contracts never receive a broken Sniping dashboard link.
    assert "PUMPFUN_SNIPING_BACKENDS.has(run.physical_settings.backend)" in script


# Verify that browser presentation cannot weaken the API's complete ordering contract.
def test_default_list_sorts_preserve_exact_server_page_order() -> None:
    script = (_static_root() / "app.js").read_text(encoding="utf-8")
    jobs_sorter = script.split("function sortedJobs()", 1)[1].split(
        "// Render a fingerprinted job page", 1
    )[0]
    # Submitted-time DESC keeps the API's job_id DESC tie-breaker unchanged.
    job_default = 'key === "submitted_at" && jobsSortDirection === "desc"'
    assert job_default in jobs_sorter
    assert "return [...jobsPageItems]" in jobs_sorter

    # Completion-time DESC keeps exact server fractions and artifact-ID ties unchanged.
    runs_sorter = script.split("function sortedRuns()", 1)[1].split(
        "// Render one verified run page", 1
    )[0]
    run_default = 'key === "completed_at" && runsSortDirection === "desc"'
    # The defensive copy proves the default path avoids any local comparator.
    assert run_default in runs_sorter
    assert "return [...runsPageItems]" in runs_sorter
    # Alternate date sorts preserve fractional seconds instead of narrowing to milliseconds.
    exact_iso = script.split("function isoTimestampNanoseconds", 1)[1].split(
        "// Apply a closed comparator", 1
    )[0]
    assert "BigInt(milliseconds) * 1000000n" in exact_iso
    assert "Date.parse(left)" not in exact_iso


# Verify single-flight and stale-response guards for the bounded event-history cursor.
def test_job_event_history_coalesces_same_cursor_and_rejects_stale_commits() -> None:
    script = (_static_root() / "app.js").read_text(encoding="utf-8")
    events = script.split("// Commit one event page", 1)[1].split("// Empty and error states", 1)[0]
    # Manual and polling refreshes reuse one active promise for the selected job.
    assert "activeEventsRequestPromise !== null" in events
    assert "return activeEventsRequestPromise" in events
    assert "activeEventsRequestController?.abort()" in events
    # A response may commit only against the generation and cursor it requested.
    assert "activeEventsGeneration === generation" in events
    assert "activeEventsCursor === cursor" in events
    assert "activeEventsRequestController === controller" in events
    assert "{ signal: controller.signal }" in events


def test_compact_sniping_view_clears_prior_identity_and_keeps_null_pnl_distinct() -> None:
    """A failed new selection cannot display old rows or coerce missing PnL to zero."""

    script = (_static_root() / "app.js").read_text(encoding="utf-8")
    open_result = script.split("async function openSnipingResult", 1)[1].split(
        "// Query bounded manifest", 1
    )[0]
    # Both scalar summary and table rows disappear before the new artifact request.
    assert "snipingSummaryCards.replaceChildren()" in open_result
    assert 'renderTableMessage(snipingRoundtripsBody, "Загрузка результата…", 12)' in open_result
    # Missing economics is ordered after measured values and never becomes a fake zero.
    assert "function compareNullableAtomic" in script
    assert 'left.economic_pnl_atomic ?? "0"' not in script
    assert 'left.realized_cash_pnl_atomic ?? "0"' not in script
