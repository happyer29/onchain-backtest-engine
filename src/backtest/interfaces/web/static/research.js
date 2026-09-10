"use strict";

// The browser retains one immutable artifact and one bounded table page at a time.
const $ = (selector) => document.querySelector(selector);
const state = {artifact: null, table: null, pair: null, cursor: null, next: null, version: 0};
const pending = new Map();
// Track the last submitted job without replacing unchanged controls on every poll.
let activeJobId = null;
let jobsSignature = "";
const names = {observations: "Исходные наблюдения", activity: "Активность подписантов", pairs: "Пары кошельков", evidence: "Исходные покупки пары"};
const labels = {source_rows: "Наблюдений в снимке", selected_rows: "Строк в выборке", wallets: "Подписантов", pairs: "Пар кошельков", evidence: "Общих токенов у пар"};

// Column sets are fixed display contracts; no source-provided key becomes executable UI.
const columns = {
  observations: ["row_id", "block_ordinal", "transaction_index", "signature", "mint", "side", "signing_wallet", "fee_payer", "quote_amount_atomic"],
  activity: ["signing_wallet", "buy_rows", "sell_rows", "mint_count", "first_block", "last_block", "source_quote_buy_atomic", "source_quote_sell_atomic"],
  pairs: ["row_id", "signer_a", "signer_b", "shared_mints", "a_first", "b_first", "same_transaction"],
  // Each evidence row shows both participants, so a common payer cannot replace either signer.
  evidence: ["mint", "delta_seconds", "left_signature", "right_signature", "left_signing_wallet", "right_signing_wallet", "left_fee_payer", "right_fee_payer", "left_block_ordinal", "right_block_ordinal"]
};

// Source roles and amount units remain visible in the column names.
const headings = {
  row_id: "Строка", block_ordinal: "Блок", transaction_index: "Транзакция", signature: "Подпись транзакции", mint: "Токен", side: "Сторона",
  signing_wallet: "Подписант", fee_payer: "Плательщик комиссии", quote_amount_atomic: "SOL-часть, lamports", buy_rows: "Покупок (строк)", sell_rows: "Продаж (строк)", mint_count: "Токенов",
  first_block: "Первый блок", last_block: "Последний блок", source_quote_buy_atomic: "Покупки: SOL-часть, lamports", source_quote_sell_atomic: "Продажи: SOL-часть, lamports",
  signer_a: "Подписант A", signer_b: "Подписант B", shared_mints: "Общих токенов", a_first: "A раньше", b_first: "B раньше", same_transaction: "Одна транзакция", delta_seconds: "Время B − A, с",
  // Evidence identifies both source transactions and preserves their distinct payer roles.
  left_signature: "Транзакция A", right_signature: "Транзакция B", left_signing_wallet: "Подписант A", right_signing_wallet: "Подписант B",
  left_fee_payer: "Плательщик A", right_fee_payer: "Плательщик B", left_block_ordinal: "Блок A", right_block_ordinal: "Блок B"
};

// All user/source text enters textContent; no raw HTML, external scripts or credentials.
function element(tag, text = "", className = "") {
  const node = document.createElement(tag);
  node.textContent = text;
  node.className = className;
  // Callers receive a text-only node and may add fixed controls explicitly.
  return node;
}

// Known API rejects explain the next action without exposing deployment details.
const errorMessages = {
  RESEARCH_SOURCE_NOT_CONFIGURED: "Источник данных для этого сервера не настроен. Снимок не создан. Запусти сервер с настроенным профилем источника; сохранённые снимки можно анализировать без подключения.",
  RESEARCH_INVALID_FORM: "Проверь значения полей: границы блоков и параметры анализа должны быть целыми числами в допустимых пределах.",
  RESEARCH_RERESOLVE_REQUIRED: "Версия исследовательского рецепта изменилась. Обнови страницу и повтори отправку.",
  // A failed artifact read must not be presented as a valid empty result.
  RESEARCH_ARTIFACT_UNAVAILABLE: "Не удалось проверить выбранный снимок или результат. Проверь его ID и доступность локальных данных."
};

// A command error belongs beside its form; background polling keeps a separate alert.
function showError(error, target = $("#error")) {
  const code = /^[A-Z][A-Z0-9_]{0,95}$/.test(error.message || "") ? error.message : "RESEARCH_REQUEST_FAILED";
  target.textContent = errorMessages[code] || `Запрос не выполнен (${code}). Проверь соединение и параметры запроса.`;
  target.hidden = false;
  // Alert semantics announce failure separately from the form's pending status.
  target.classList.add("error");
  target.setAttribute("role", "alert");
  // Only user-initiated form failures move focus; background polling must not steal it.
  if (target.id !== "error") {
    target.focus({preventScroll: true});
    target.scrollIntoView({block: "nearest"});
  }
}

// The shared transport retains same-origin credentials, CSRF and response bounds.
async function api(path, options = {}) {
  // Requests stay same-origin and have a deadline, including job polling.
  const response = await fetch(path, {...options, credentials: "same-origin", signal: AbortSignal.timeout(15000),
    headers: {"Content-Type": "application/json", ...(options.method ? {"X-Backtest-CSRF": "1"} : {}), ...options.headers}});
  const text = await response.text();
  if (text.length > 2 * 1024 * 1024) throw new Error("RESEARCH_RESPONSE_LIMIT");
  const data = JSON.parse(text);
  // Server errors are codes, never tracebacks or SDK response strings.
  if (!response.ok) throw new Error(data.code || `HTTP_${response.status}`);
  return data;
}

// Disable the originating form until its durable submission outcome is known.
async function submit(form, kind, body) {
  const button = form.querySelector("button");
  const feedback = form.querySelector(".form-feedback");
  const buttonLabel = button.textContent;
  // Sending a command is visible immediately, before a durable job exists.
  button.disabled = true;
  button.textContent = "Отправляем…";
  form.setAttribute("aria-busy", "true");
  feedback.hidden = false;
  feedback.classList.remove("error");
  // Repeated submissions replace the previous outcome with a fresh live status.
  feedback.setAttribute("role", "status");
  feedback.textContent = "Отправляем запрос на создание задачи…";
  $("#error").hidden = true;
  try {
    // An uncertain network response keeps the same idempotency key for a retry.
    const serialized = JSON.stringify(body);
    const intent = kind + serialized;
    if (!pending.has(intent)) pending.set(intent, crypto.randomUUID());
    // A repeated uncertain request carries the exact same semantic form and idempotency key.
    const job = await api(`/api/v1/research/${kind}`, {method: "POST", body: serialized,
      headers: {"Idempotency-Key": pending.get(intent)}});
    // A confirmed new click is a new acquisition intent, even for the same source interval.
    pending.delete(intent);
    activeJobId = job.job_id;
    feedback.textContent = `Задача создана: ${job.job_id}. Статус: ${job.state}. Ход выполнения показан в разделе «Задачи исследования».`;
    $("#job-status").textContent = `${job.job_type}: ${job.state} · ${job.job_id}`;
    // A polling failure does not negate a confirmed durable submission.
    await refreshJobs().catch(showError);
  } catch (error) {
    showError(error, feedback);
  // Restore both forms after rejection, timeout, or confirmed admission.
  } finally {
    button.disabled = false;
    button.textContent = buttonLabel;
    form.removeAttribute("aria-busy");
    // Restoring submission controls does not cancel or change the durable job.
  }
}

// Acquisition is an explicit user action; viewing an old snapshot never triggers it.
$("#prepare-form").addEventListener("submit", (event) => {
  // HTML ranges are convenience validation; the server remains the typed authority.
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  submit(event.currentTarget, "prepare", {from_block: Number(data.get("from_block")),
    to_block: Number(data.get("to_block"))}).catch(showError);
});

// Signer selection comes only from the current form and is validated by the shared resolver.
$("#analyze-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  const wallets = String(data.get("wallets")).trim();
  // Only bounded identifiers and semantic recipe parameters cross this mutation boundary.
  submit(event.currentTarget, "analyze", {snapshot_id: data.get("snapshot_id"),
    window_seconds: Number(data.get("window_seconds")), minimum_shared_mints: Number(data.get("minimum_shared_mints")),
    wallets: wallets ? wallets.split(/\s+/) : []}).catch(showError);
});

// Only one bounded recent-job request may be in flight at once.
let jobsBusy = false;
async function refreshJobs() {
  // One request at a time prevents timer/manual-refresh races and runaway polling.
  if (jobsBusy) return;
  jobsBusy = true;
  try {
    const data = await api("/api/v1/jobs?limit=25");
    const jobs = data.items.filter((job) => ["PREPARE_RESEARCH", "ANALYZE_WALLETS"].includes(job.job_type));
    // A selected job's visible state follows the authoritative controller response.
    const active = jobs.find((job) => job.job_id === activeJobId);
    if (active) $("#job-status").textContent = `${active.job_type}: ${active.state} · ${active.job_id}`;
    // The list is a bounded recent-job view, not an exhaustive catalog.
    const signature = JSON.stringify(jobs);
    if (signature === jobsSignature) return;
    jobsSignature = signature;
    $("#jobs").replaceChildren(...jobs.map(jobRow));
    if (!jobs.length) $("#jobs").append(element("p", "Среди последних 25 задач исследований пока нет.", "hint"));
  // Early unchanged-state returns also release the polling guard.
  } finally {
    jobsBusy = false;
  }
}

// Actions are chosen from durable job state, without assuming submission means success.
function jobRow(job) {
  const row = element("div", "", "job");
  row.append(element("span", job.job_type === "PREPARE_RESEARCH" ? "Снимок" : "Анализ"), element("code", job.job_id), element("span", job.state));
  // Successful jobs resolve through the verified receipt-bound artifact query.
  if (job.state === "SUCCEEDED") {
    const button = element("button", "Открыть", "secondary");
    button.addEventListener("click", () => openJob(job.job_id).catch(showError));
    row.append(button);
  } else if (["QUEUED", "STARTING", "RUNNING"].includes(job.state)) {
    // Cancellation uses the existing durable command and never just hides a job locally.
    const button = element("button", "Отменить", "secondary");
    button.addEventListener("click", () => api(`/api/v1/jobs/${encodeURIComponent(job.job_id)}/cancel`, {method: "POST"}).then(refreshJobs).catch(showError));
    row.append(button);
  }
  // Failed or terminal jobs remain visible even when they offer no further action here.
  return row;
}

async function openJob(jobId) {
  // A database row alone cannot navigate the user to missing or corrupt result bytes.
  const data = await api(`/api/v1/research/jobs/${encodeURIComponent(jobId)}/result`);
  await openArtifact(data.artifact_id);
}

// Exact content IDs, not source paths or mutable aliases, select the retained result.
async function openArtifact(id) {
  if (!/^[0-9a-f]{64}$/.test(id)) throw new Error("RESEARCH_INVALID_ARTIFACT_ID");
  const version = ++state.version;
  $("#error").hidden = true;
  $("#result").hidden = true;
  // Release the previous page before resolving a different immutable artifact.
  ResearchGraph.clear();
  // Keep the previous view hidden until its replacement manifest is verified by the server.
  const summary = await api(`/api/v1/research/${id}`);
  // A slower request must never overwrite a more recently selected artifact.
  if (version !== state.version) return;
  Object.assign(state, {artifact: id, pair: null, cursor: null, next: null});
  $("#artifact-id").value = id;
  history.replaceState(null, "", `/research?artifact=${id}`);
  const snapshot = summary.kind === "RESEARCH_SNAPSHOT";
  // Selecting a snapshot fills the analysis form without auto-running another job.
  if (snapshot) $("[name=snapshot_id]").value = id;
  else {
    // Reopened results show their actual recipe, rather than the form's initial defaults.
    $("[name=snapshot_id]").value = summary.analysis.snapshot_id;
    $("[name=window_seconds]").value = summary.analysis.window_seconds;
    $("[name=minimum_shared_mints]").value = summary.analysis.minimum_shared_mints;
    $("[name=wallets]").value = summary.analysis.wallets.join("\n");
  }
  // The displayed range remains the source's authoritative half-open block interval.
  $("#result-title").textContent = snapshot ? "Наблюдения сохранены" : "Связи в наблюдаемой выборке";
  $("#scope").textContent = `${summary.dataset.network_id} · ${summary.dataset.source_id} · ` +
    `[${summary.dataset.from_block_ordinal}, ${summary.dataset.to_block_ordinal})`;
  // Include semantic filters alongside the data scope so results remain interpretable.
  if (!snapshot) $("#scope").textContent += ` · окно ≤ ${summary.analysis.window_seconds} с · минимум ${summary.analysis.minimum_shared_mints} токенов · ` +
    (summary.analysis.wallets.length ? `${summary.analysis.wallets.length} выбранных подписантов` : "все наблюдаемые подписанты");
  $("#lineage").href = `/api/v1/lineage/${id}`;
  // These counts refer to the whole immutable result, independently of page navigation.
  $("#metrics").replaceChildren(...Object.entries(labels).map(([key, label]) => {
    const card = element("div", "", "metric");
    card.append(element("strong", summary.counts[key]), element("span", label));
    return card;
  }));
  // A snapshot exposes source rows; derived tables belong only to a completed result.
  const tables = snapshot ? ["observations"] : ["pairs", "activity"];
  // Tabs select fixed typed tables, never files or query strings supplied by an artifact.
  $("#tabs").replaceChildren(...tables.map((table) => {
    const button = element("button", names[table], "secondary");
    button.dataset.table = table;
    button.addEventListener("click", () => selectTable(table).catch(showError));
    return button;
    // Replacing tabs resets controls to the selected artifact's supported table roles.
  }));
  $("#result").hidden = false;
  await selectTable(tables[0]);
}

// Selecting a new table changes the view only; it never recalculates analytical results.
async function selectTable(table, pair = null) {
  // Changing table or evidence pair resets cursor scope before issuing the next GET.
  Object.assign(state, {table, pair, cursor: null, next: null});
  await loadPage(null);
}

// Versioning drops late page responses after the user has changed the selected view.
async function loadPage(cursor) {
  const version = ++state.version;
  const {artifact, table, pair} = state;
  // Retire old evidence callbacks while the replacement page is being verified.
  ResearchGraph.clear("Загружаем текущую страницу…");
  $("#graph-next-page").disabled = true;
  const query = new URLSearchParams({limit: "25"});
  if (cursor) query.set("cursor", cursor);
  // Evidence requests name one pair ordinal in the exact selected result.
  if (pair !== null) query.set("pair", pair);
  $("#next-page").disabled = true;
  const page = await api(`/api/v1/research/${artifact}/rows/${table}?${query}`);
  if (version !== state.version) return;
  Object.assign(state, {cursor, next: page.next_cursor});
  // Only the current response owns table state and navigation controls.
  $("#table-title").textContent = names[table] + (pair === null ? "" : ` · пара ${pair}`);
  renderRows(page.rows, table);
  $("#next-page").disabled = !page.next_cursor;
  $("#graph-panel").hidden = table !== "pairs";
  // Canvas and table drilldown share the same exact result-local pair ordinal.
  if (table === "pairs") ResearchGraph.render(page.rows, (rowId) => {
    selectTable("evidence", rowId).catch(showError);
  });
  $("#graph-next-page").disabled = !page.next_cursor;
  // Selected tabs stay keyboard navigable and announce their active state.
  for (const button of $("#tabs").children) button.setAttribute("aria-pressed", String(button.dataset.table === table));
}

// Rebuild only the bounded current table page, with no hidden full-result DOM.
function renderRows(rows, table) {
  const root = $("#rows");
  root.replaceChildren();
  if (!rows.length) {
    // Empty results can be valid, but never carry invented evidence or graph nodes.
    root.append(element("caption", "На этой странице нет строк. Проверь окно, порог и выбранные кошельки."));
    return;
  }
  const header = element("tr");
  for (const key of columns[table]) header.append(element("th", headings[key] || key));
  // The pair action is distinct from the observed scalar fields.
  if (table === "pairs") header.append(element("th", "Доказательства"));
  root.append(header);
  for (const row of rows) {
    const tr = element("tr");
    for (const key of columns[table]) {
      // Values remain decimal strings; large atomic amounts never pass through Number.
      const value = row[key];
      const cell = element("td", value);
      cell.title = value;
      tr.append(cell);
    }
    // Evidence navigation uses the pair ordinal carried by this exact result row.
    if (table === "pairs") {
      // A pair selects its own bounded evidence page with exact source-row references.
      const button = element("button", "Покупки →", "secondary");
      button.addEventListener("click", () => selectTable("evidence", row.row_id).catch(showError));
      const cell = element("td");
      cell.append(button);
      tr.append(cell);
      // The completed cell contains an action, while its source fields stay plain text.
    }
    root.append(tr);
  }
}

// Manual navigation uses the exact server cursor; view changes discard old continuations.
$("#open-form").addEventListener("submit", (event) => {event.preventDefault(); openArtifact($("#artifact-id").value.trim()).catch(showError);});
$("#first-page").addEventListener("click", () => loadPage(null).catch(showError));
$("#next-page").addEventListener("click", () => loadPage(state.next).catch(showError));
// Graph pagination shares the table cursor without loading hidden pages or recalculating pairs.
$("#graph-first-page").addEventListener("click", () => loadPage(null).catch(showError));
$("#graph-next-page").addEventListener("click", () => loadPage(state.next).catch(showError));
$("#refresh-jobs").addEventListener("click", () => refreshJobs().catch(showError));

// Poll only a bounded recent-job list, pause while hidden, and let users reopen exact artifacts.
refreshJobs().catch(showError);
setInterval(() => {if (!document.hidden) refreshJobs().catch(showError);}, 5000);
const initial = new URLSearchParams(location.search).get("artifact");
if (initial) openArtifact(initial).catch(showError);
