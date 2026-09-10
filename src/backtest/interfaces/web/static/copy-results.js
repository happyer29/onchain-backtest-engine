"use strict";

// Each view owns an independent abort controller and monotonically increasing generation.
const C = globalThis.CopyMarketChart;
const el = (id) => document.getElementById(id);
const digest = /^[0-9a-f]{64}$/;
let generation = 0, request = null, runId = null, pageIndex = 0;
let cursors = [null], nextCursor = null, rows = [], total = "0";
// Chart authority is invalidated whenever the run, visible page or selected signal changes.
let chartGeneration = 0, chartRequest = null, chartData = null;
const dialog = el("copy-chart-dialog");
const statusLabels = { CLOSED: "Закрыта", EXHAUSTED: "Попытки исчерпаны", BUY_FAILED: "Покупка не исполнена", BUY_REJECTED: "Покупка отклонена" };
const exitLabels = { TAKE_PROFIT: "Тейк-профит", STOP_LOSS: "Стоп-лосс", MAXIMUM_HOLD: "Лимит времени" };
const attemptLabels = { FILLED: "Исполнена", FAILED: "Не исполнена", REJECTED: "Отклонена" };

// GETs share the existing same-origin session and a finite transport deadline.
async function api(path, signal) {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; cancel(); }, 15000);
  // An already superseded request must not begin a new transport operation.
  if (signal.aborted) cancel();
  else signal.addEventListener("abort", cancel, { once: true });
  try {
    const response = await fetch(path, { credentials: "same-origin", headers: { Accept: "application/json" }, signal: controller.signal });
    const body = await response.json();
    // The server publishes closed errors; rendering them as text prevents HTML injection.
    if (!response.ok) throw new Error(body.message || `Не удалось прочитать результат (HTTP ${response.status})`);
    return body;
  } catch (error) {
    if (timedOut) throw new Error("Локальный API не ответил за 15 секунд");
    throw error;
  // Cleanup applies equally to malformed responses, timeouts and normal completion.
  } finally {
    clearTimeout(timer);
    signal.removeEventListener("abort", cancel);
  }
}

// The DOM accepts only text nodes and fixed classes, including mint and wallet addresses.
function node(tag, text = "", className = "") {
  const item = document.createElement(tag);
  item.textContent = text;
  item.className = className;
  return item;
// The returned node has no HTML interpretation or event attributes supplied by data.
}

// Missing values stay explicit instead of being coerced to zero by number conversion.
function card(label, value, note) {
  const item = node("div", "", "dashboard-kpi");
  item.append(node("span", label, "dashboard-kpi-label"), node("strong", value, "dashboard-kpi-value"), node("span", note, "dashboard-kpi-note"));
  return item;
}

// Only a copy-specific combined summary may establish run identity for this page.
function validateDashboard(data, id) {
  if (data.summary?.contract_schema !== "pumpfun-copy-run-summary/v1" || data.summary.run_artifact_id !== id) {
    throw new Error("Выберите результат Pump.fun Copy Buy");
  }
  const summary = data.summary.summary;
  // Only the two admitted execution modes have a meaningful result interpretation.
  if (!["EXOGENOUS_REPLAY", "EXOGENOUS_VIRTUAL_SETTLEMENT"].includes(summary.execution_mode)) throw new Error("Неизвестный режим исполнения");
  // All whole-run totals are decimal strings, except the explicitly nullable full PnL.
  for (const [key, value] of Object.entries(summary.totals)) {
    if (key === "valuation_status" || (key === "economic_pnl_atomic" && value === null)) continue;
    C.integer(value);
  }
  validatePage(data.roundtrips);
  // First-page validation must finish before the summary establishes view authority.
  return data;
}

// Paging accepts only a bounded schema-homogeneous response with a valid composite cursor.
function validatePage(page) {
  const limit = Number(el("copy-page-size").value);
  if (!Array.isArray(page.items) || page.items.length > limit) throw new Error("Некорректная страница сигналов");
  for (const item of page.items) {
    if (item.contract_schema !== "pumpfun-copy-position/v1" || !digest.test(item.record?.position_id)) throw new Error("Некорректный сигнал");
    // The chart button needs the original leader signal and at most five actual attempts.
    const record = item.record;
    if (record.quote_asset_id !== "SOL" || !Array.isArray(record.attempts) || !record.attempts.length || record.attempts.length > 5) throw new Error("Некорректные попытки сигнала");
    if (C.boundary(record.signal_position) < 0n) throw new Error("Некорректная координата сигнала");
    if (!Object.hasOwn(statusLabels, record.status)) throw new Error("Неизвестный исход позиции");
  }
  // The opaque cursor remains lossless through decimal text and never becomes an offset.
  if (page.next_cursor !== null) {
    const cursor = page.next_cursor;
    if (!digest.test(cursor?.roundtrip_id) || C.integer(cursor.target_boundary_ordinal) < 0n) throw new Error("Некорректный курсор страницы");
  }
  return page;
// A null cursor explicitly marks the end of this bounded page sequence.
}

// Summary cards describe the population and units independently of visible signal rows.
function renderSummary(summary) {
  const t = summary.totals;
  total = t.position_count;
  el("copy-kpis").replaceChildren(
    card("Сигналы", total, "Уникальные токены за прогон"),
    // Each card uses its own full-run definition rather than an inferred total.
    card("Куплено", t.filled_buy_count, "Фактически исполненные покупки"),
    // Closed and exhausted positions are disjoint outcomes of successful entries.
    card("Закрыто", t.closed_position_count, "Фактически исполненные продажи"),
    card("Без выхода", t.exhausted_position_count, "Четыре попытки исчерпаны"),
    card("Реализованный PnL", `${C.sol(t.realized_cash_pnl_atomic)} SOL`, "Закрытые позиции и комиссии неудачных входов"),
    card("Полный экономический PnL", t.economic_pnl_atomic === null ? "Нет полной оценки" : `${C.sol(t.economic_pnl_atomic)} SOL`, `Оценка: ${t.valuation_status}`),
  );
  // Synthetic settlement is explicitly labelled and never described as executable on chain.
  const synthetic = summary.execution_mode === "EXOGENOUS_VIRTUAL_SETTLEMENT";
  el("copy-mode").textContent = synthetic ? "Синтетическое исполнение · не исполнимо on-chain" : "Исторические резервы · EXOGENOUS_REPLAY";
  el("copy-mode").className = `badge ${synthetic ? "warning" : ""}`;
  el("copy-valuation").textContent = t.economic_pnl_atomic === null ? `Неполная оценка: ${t.unvalued_open_position_count} открытых позиций без котировки. Известная часть экономического PnL: ${C.sol(t.valued_economic_pnl_subtotal_atomic)} SOL; она не является итоговым PnL.` : "Все позиции оценены. Денежный поток отдельно отражает комиссии и заблокированные депозиты.";
  // Failed and pre-submit rejected entries retain their independent meanings.
  C.bars("copy-outcomes", [
    ["Сигналы", t.position_count], ["Покупки исполнены", t.filled_buy_count],
    ["Покупки не исполнены", t.failed_buy_count], ["Покупки отклонены", t.rejected_buy_count],
    ["Позиции закрыты", t.closed_position_count], ["Без выхода", t.exhausted_position_count],
  ]);
  // Nullable full PnL is a labelled gap; spendable cash is never presented as profit.
  C.bars("copy-finances", [
    ["Реализованный PnL", t.realized_cash_pnl_atomic], ["Денежный поток", t.quote_cashflow_atomic],
    ["Полный эконом. PnL", t.economic_pnl_atomic], ["Заблокировано rent", t.account_deposit_locked_atomic],
    // Cashback is receivable; synthetic funding is separately disclosed wallet funding.
    ["Cashback к получению", t.cashback_receivable_atomic], ["Синтетическое SOL", t.synthetic_funded_sell_atomic],
  ], true);
}

// Each token gets a chart button bound to its recorded position, not to arbitrary search text.
function signalRow(record) {
  const row = node("tr"), token = node("td");
  const address = node("strong", record.asset_id, "mono copy-token-address");
  token.append(address, node("small", record.signing_wallet, "mono copy-token-address"));
  row.append(token, node("td", `${record.signal_position.block_ordinal} / ${record.signal_position.transaction_index}`, "mono"));
  // Entry status comes from attempt zero; a later sell cannot imply that a failed buy filled.
  const buy = record.attempts[0], buyCell = node("td", attemptLabels[buy.status] || buy.status);
  if (buy.failure_code) buyCell.append(node("small", buy.failure_code, "copy-token-address"));
  const exit = node("td", statusLabels[record.status]);
  const sells = record.attempts.filter((attempt) => attempt.side === "SELL").length;
  exit.append(node("small", `${exitLabels[record.exit_reason] || "—"} · ${sells}/4`));
  // Financial cells preserve null as unavailable, and show precise lamports on hover.
  const pnl = node("td", C.sol(record.realized_cash_pnl_atomic), "mono");
  pnl.title = record.realized_cash_pnl_atomic === null ? "Нет реализованного PnL" : `${record.realized_cash_pnl_atomic} lamports`;
  const action = node("td"), button = node("button", "График", "secondary");
  button.type = "button";
  // A human-readable full token address remains available to assistive technology.
  button.setAttribute("aria-label", `График маркеткапа ${record.asset_id}`);
  button.addEventListener("click", () => openChart(record));
  action.append(button);
  row.append(buyCell, exit, pnl, action);
  return row;
// Attach the action to this row only after its immutable selector has been captured.
}

// Filtering is local to the current page and cannot alter whole-run chart denominators.
function renderRows() {
  const filter = el("copy-filter").value.trim().toLowerCase();
  const visible = rows.filter((record) => `${record.asset_id} ${record.signing_wallet} ${record.status} ${statusLabels[record.status]}`.toLowerCase().includes(filter));
  el("copy-rows").replaceChildren(...visible.map(signalRow));
  if (!visible.length) {
    // A local text filter can legitimately hide all rows without changing run totals.
    const row = node("tr"), cell = node("td", "На этой странице нет подходящих сигналов.");
    // Keep an empty filter result inside the existing table semantics.
    cell.colSpan = 6;
    row.append(cell);
    el("copy-rows").append(row);
  }
  el("copy-page-label").textContent = `Страница ${pageIndex + 1} · показано ${visible.length} из ${rows.length} · всего ${total}`;
// Page population and whole-run population remain separately labelled.
}

// Request completion only re-enables controls for the currently selected run generation.
function navigation(busy) {
  el("copy-prev").disabled = busy || pageIndex === 0;
  el("copy-next").disabled = busy || nextCursor === null;
  el("copy-page-size").disabled = busy;
  el("copy-table").setAttribute("aria-busy", String(busy));
// Assistive technology receives the same request state as disabled navigation controls.
}

// Invalidating a chart clears its bytes immediately, including after a failed new run selection.
function invalidateChart(close = true) {
  chartGeneration += 1;
  chartRequest?.abort();
  chartRequest = null;
  chartData = null;
  // Old token prices and markers disappear before another asynchronous request begins.
  el("copy-chart-content").hidden = true;
  el("copy-market-plot").replaceChildren();
  el("copy-chart-events").replaceChildren();
  if (close && dialog.open) dialog.close();
}

// Summary and first page commit together only after their exact run ID validates.
async function openRun(id) {
  const version = ++generation;
  request?.abort();
  const controller = new AbortController();
  request = controller;
  // Reset identity before validating input, so invalid input cannot retain old authority.
  invalidateChart();
  runId = null; rows = []; cursors = [null]; pageIndex = 0; nextCursor = null;
  el("copy-content").hidden = true;
  el("copy-error").hidden = true;
  el("copy-status").textContent = "Загрузка…";
  // Controls remain unavailable while the new artifact has no verified identity.
  navigation(true);
  try {
    if (!digest.test(id)) throw new Error("Run artifact ID должен содержать 64 строчных hex-символа");
    const limit = el("copy-page-size").value;
    const result = await api(`/api/v1/run-artifacts/${id}/dashboard?limit=${limit}`, controller.signal);
    // Late responses are checked before any data can replace the visible run.
    if (version !== generation || controller.signal.aborted) return;
    // Render only after the complete response passes identity and schema checks.
    validateDashboard(result, id);
    renderSummary(result.summary.summary);
    rows = result.roundtrips.items.map((item) => item.record);
    nextCursor = result.roundtrips.next_cursor;
    runId = id;
    // A page render uses the new row collection and next cursor atomically.
    renderRows();
    // The address bar shares this exact immutable result rather than a mutable latest alias.
    history.replaceState(null, "", `/copy-results?run_artifact_id=${id}`);
    el("copy-content").hidden = false;
    el("copy-status").textContent = "Результат загружен";
  } catch (error) {
    // Only the active generation may surface an error or release request ownership.
    if (version === generation && !controller.signal.aborted) showError(error);
  } finally {
    if (version === generation) { request = null; navigation(false); }
  }
}

// A page change keeps the same authenticated run identity.

// A page transition drops chart authority; a failed request preserves the previous valid page.
async function openPage(index) {
  if (!runId || request !== null) return;
  const id = runId, version = ++generation, controller = new AbortController();
  request = controller;
  invalidateChart();
  // First-page null and later exact cursors keep pagination independent of source row counts.
  const cursor = cursors[index], params = new URLSearchParams({ limit: el("copy-page-size").value });
  if (cursor) {
    params.set("after_target_boundary_ordinal", cursor.target_boundary_ordinal);
    params.set("after_roundtrip_id", cursor.roundtrip_id);
  }
  // Pagination reads one requested page; it does not walk the complete result table.
  navigation(true);
  el("copy-error").hidden = true;
  try {
    const result = await api(`/api/v1/run-artifacts/${id}/roundtrips?${params}`, controller.signal);
    // Validate the response before committing its navigation cursor.
    if (version !== generation || controller.signal.aborted || id !== runId) return;
    validatePage(result);
    rows = result.items.map((item) => item.record);
    // Cursor history updates only after a successful page response.
    pageIndex = index;
    nextCursor = result.next_cursor;
    renderRows();
  } catch (error) {
    if (version === generation && !controller.signal.aborted) showError(error);
  // A failed page fetch leaves the last verified page available for retry.
  } finally {
    if (version === generation) { request = null; navigation(false); }
  }
}

// Public errors are rendered as text and do not change run selection.

// Safe errors preserve the failed selection and never silently choose another result artifact.
function showError(error) {
  el("copy-error").textContent = error.message;
  el("copy-error").hidden = false;
  el("copy-status").textContent = "Ошибка чтения";
}

// Only one explicitly selected signal can own an in-flight market history response.
async function openChart(record) {
  invalidateChart(false);
  if (!runId) return;
  const version = chartGeneration, id = runId, controller = new AbortController();
  chartRequest = controller;
  // A new token starts with an empty plot and an explicit loading state.
  el("copy-chart-token").textContent = record.asset_id;
  el("copy-chart-status").textContent = "Читаю проверенную историю…";
  if (!dialog.open) dialog.showModal();
  try {
    const key = C.boundary(record.signal_position).toString();
    // The chart selector contains the exact source signal boundary and position ID.
    const result = await api(`/api/v1/run-artifacts/${id}/copy-positions/${record.position_id}/market-cap?signal_boundary_ordinal=${key}`, controller.signal);
    if (version !== chartGeneration || id !== runId || controller.signal.aborted || !dialog.open) return;
    // The plot's identity is bound to the exact record that opened this dialog.
    chartData = C.validate(result, id, record);
    C.render(chartData);
    renderEvents(chartData);
    el("copy-chart-source").textContent = `Snapshot: ${chartData.snapshot_id} · Каноническая история этого прогона`;
    // The original execution mode remains visible inside the modal, including synthetic exits.
    el("copy-chart-status").textContent = `${statusLabels[record.status]} · ${exitLabels[record.exit_reason] || "Без триггера выхода"}${record.execution_mode === "EXOGENOUS_VIRTUAL_SETTLEMENT" ? " · Синтетическое исполнение, не on-chain" : ""}`;
    el("copy-chart-detail").textContent = "Выберите точку на графике или событие ниже. Цифры на графике соответствуют событиям в таблице.";
    el("copy-chart-content").hidden = false;
  // Keep failures scoped to the current token; a newer chart owns its own loading state.
  } catch (error) {
    if (version === chartGeneration && !controller.signal.aborted) el("copy-chart-status").textContent = error.message;
  } finally {
    if (version === chartGeneration) chartRequest = null;
  }
// Request ownership is released only by the matching chart generation.
}

// The event table is the accessible alternative for overlapping same-second markers.
function renderEvents(data) {
  el("copy-chart-events").replaceChildren();
  data.markers.forEach((marker, index) => {
    const point = marker.point, row = node("tr"), action = node("td");
    const button = node("button", `${index + 1}. ${C.markerLabel(marker)}`, "secondary");
    // Table buttons offer precise inspection even when same-second SVG markers overlap.
    button.type = "button";
    // Clicking the table changes only inspection text; it never moves the underlying marker.
    button.addEventListener("click", () => C.describe(point, C.markerLabel(marker)));
    action.append(button);
    row.append(action, node("td", C.time(point.block_time_ns, true)), node("td", `${point.position.block_ordinal} / ${point.position.transaction_index}`, "mono"));
    row.append(node("td", C.sol(point.market_cap_atomic, 9), "mono"), node("td", marker.failure_code || (marker.kind === "SIGNAL" ? "Покупка лидера" : "Исполнено")));
    el("copy-chart-events").append(row);
  // The event row retains the original failure reason alongside its market-cap ordinate.
  });
}

// Manual navigation never starts an eager traversal of all positions or token histories.
el("copy-run-form").addEventListener("submit", (event) => { event.preventDefault(); openRun(el("copy-run-id").value.trim()); });
el("copy-filter").addEventListener("input", renderRows);
el("copy-prev").addEventListener("click", () => openPage(pageIndex - 1));
el("copy-next").addEventListener("click", () => { cursors[pageIndex + 1] = nextCursor; openPage(pageIndex + 1); });
el("copy-page-size").addEventListener("change", () => { if (runId) openRun(runId); });
// Closing the native modal invalidates even a response already queued for delivery.
el("copy-chart-close").addEventListener("click", () => dialog.close());
dialog.addEventListener("close", () => invalidateChart(false));
el("copy-chart-trade").addEventListener("click", () => { if (chartData) C.render(chartData, true); });
el("copy-chart-all").addEventListener("click", () => { if (chartData) C.render(chartData, false); });
// A bookmarked exact result is opened once; no polling or default latest artifact is used.
const initialId = new URLSearchParams(location.search).get("run_artifact_id");
if (initialId !== null) { el("copy-run-id").value = initialId; openRun(initialId); }
