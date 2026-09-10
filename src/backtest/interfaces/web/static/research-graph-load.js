"use strict";

// This display-only reader follows server cursors over one verified, immutable pair table.
const ResearchGraphLoad = (() => {
  const limits = Object.freeze({pairs: 200000, wallets: 5000, page: 200,
    responseBytes: 2 * 1024 * 1024, totalBytes: 128 * 1024 * 1024, deadline: 180000});
  const fail = (message) => {throw new Error(message);};
  // Only schema-valid positive or zero decimal strings enter bounded counter conversions.
  function count(value) {
    if (typeof value !== "string" || !/^(0|[1-9][0-9]{0,15})$/.test(value)) fail("Некорректный счётчик результата.");
    const parsed = Number(value);
    if (!Number.isSafeInteger(parsed)) fail("Счётчик результата вне допустимого диапазона.");
    // Numeric conversion is restricted to admitted display counts, never source atomic amounts.
    return parsed;
  }

  // Enforce byte bounds while streaming, before retaining or parsing an oversized response.
  async function readPage(url, signal, budget) {
    const requestSignal = AbortSignal.any([signal, AbortSignal.timeout(15000)]);
    const response = await fetch(url, {credentials: "same-origin", signal: requestSignal});
    if (!response.ok || !response.body) fail("Не удалось прочитать проверенные пары. Повтори загрузку.");
    const reader = response.body.getReader();
    // A decoder carries split UTF-8 sequences without inflating the accounting into character counts.
    const decoder = new TextDecoder();
    let text = "", bytes = 0;
    try {
      while (true) {
        const part = await reader.read();
        // Cancellation is also checked between chunks when the response has already reached the browser.
        requestSignal.throwIfAborted();
        if (part.done) break;
        bytes += part.value.byteLength;
        budget.bytes += part.value.byteLength;
        if (bytes > limits.responseBytes || budget.bytes > limits.totalBytes) fail("Превышен лимит загрузки графа в байтах.");
        // Retain at most one bounded JSON response in addition to the checked graph rows.
        text += decoder.decode(part.value, {stream: true});
      }
      return JSON.parse(text + decoder.decode());
    } finally {
      // Cancel unread bytes after every failure; no detached response continues consuming resources.
      await reader.cancel();
      reader.releaseLock();
    }
  }

  // A contiguous result-local ordinal proves no page was omitted, repeated or reordered in transit.
  function acceptRow(row, ordinal, wallets, previous) {
    if (!row || row.row_id !== String(ordinal)) fail("Нарушен порядок пар: полный граф не построен.");
    const address = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;
    if (!address.test(row.signer_a) || !address.test(row.signer_b) || row.signer_a >= row.signer_b) fail("Некорректная пара кошельков.");
    // The committed pair table is lexical; a duplicate pair under a new ordinal is also invalid.
    const backwards = previous !== null && (row.signer_a < previous.signer_a ||
      (row.signer_a === previous.signer_a && row.signer_b <= previous.signer_b));
    if (backwards) fail("Пары повторяются или нарушен порядок результата.");
    // Tuple comparison preserves lexical ordering even when one full address prefixes another.
    const shared = count(row.shared_mints);
    if (!shared || count(row.a_first) + count(row.b_first) + count(row.same_transaction) !== shared) fail("Не сходятся счётчики пары.");
    // Wallet admission counts only pair participants, not the broader activity summary.
    wallets.add(row.signer_a);
    wallets.add(row.signer_b);
    if (wallets.size > limits.wallets) fail("В результате больше 5 000 связанных кошельков. Полный граф не построен.");
    return row;
  }

  // Fetches stay sequential and follow opaque server cursors; no fabricated offset or SQL is accepted.
  async function load(artifact, total, signal, progress, read = readPage) {
    if (!/^[0-9a-f]{64}$/.test(artifact)) fail("Некорректный ID результата.");
    const expected = count(total);
    if (expected > limits.pairs) fail("В результате больше 200 000 связей. Полный граф не построен.");
    const rows = [], wallets = new Set(), cursors = new Set(), budget = {bytes: 0};
    // Even a zero summary is checked against the actual exhausted table; it is never a synthetic empty graph.
    let cursor = null, previous = null;
    do {
      signal.throwIfAborted();
      const query = new URLSearchParams({limit: String(limits.page)});
      if (cursor !== null) query.set("cursor", cursor);
      // Only a content-addressed pair page from the selected same-origin result may populate the graph.
      const page = await read(`/api/v1/research/${artifact}/rows/pairs?${query}`, signal, budget);
      signal.throwIfAborted();
      if (page.artifact_id !== artifact || page.table !== "pairs" || !Array.isArray(page.rows)) fail("Ответ относится к другому результату.");
      if (page.rows.length > limits.page || rows.length + page.rows.length > expected) fail("Число пар не совпадает с итогом анализа.");
      // Validate a full page before reporting it as loaded; no partial data is declared complete.
      for (const row of page.rows) {
        previous = acceptRow(row, rows.length, wallets, previous);
        rows.push(row);
      }
      cursor = page.next_cursor;
      // A nonterminal page must make full bounded progress and present a new scope-bound cursor.
      if (cursor !== null) {
        if (typeof cursor !== "string" || !cursor.length || cursor.length > 1024 || cursors.has(cursor) || page.rows.length !== limits.page) fail("Некорректное продолжение таблицы пар.");
        cursors.add(cursor);
      }
      progress(rows.length, expected, wallets.size);
    // The last full page may require one final empty request to prove cursor exhaustion.
    } while (cursor !== null);
    if (rows.length !== expected) fail("Загружены не все пары результата. Повтори загрузку.");
    return {rows, wallets: [...wallets].sort(), bytes: budget.bytes};
  }
  // The caller owns one overall deadline spanning both loading and incremental canvas construction.
  return {load, limits};
})();
