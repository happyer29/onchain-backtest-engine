"use strict";

const SVG_NAMESPACE = "http://www.w3.org/2000/svg";
const RUN_ARTIFACT_ID = /^[0-9a-f]{64}$/;
const SIGNED_DECIMAL = /^(0|-?[1-9][0-9]*)$/;
const UNSIGNED_DECIMAL = /^(0|[1-9][0-9]*)$/;

// Keep integer money and bounded transport limits explicit at the browser boundary.
const LAMPORTS_PER_SOL = 1_000_000_000n;
const ROUNDTRIP_PAGE_LIMIT = 200;
const DEFAULT_ROUNDTRIP_PAGE_SIZE = 25;
const ALLOWED_PAGE_SIZES = new Set([25, 50, 100, ROUNDTRIP_PAGE_LIMIT]);
const API_TIMEOUT_MS = 15000;

// Client sorting is page-local and restricted to fields rendered in the table.
const ROUNDTRIP_SORT_FIELDS = new Set([
  "TARGET_TIME",
  "TARGET_BOUNDARY",
  "STATUS",
  "ASSET",
  // Keep identity and integer-money options explicit rather than accepting arbitrary keys.
  "DEVELOPER",
  "PNL",
  "TOTAL_FEES",
]);

// Schema constants make legacy capability differences visible instead of inferred.
const SUMMARY_V2 = "pumpfun-sniping-run-summary/v2";
const SUMMARY_V3 = "pumpfun-sniping-run-summary/v3";
const ROUNDTRIP_V3 = "pumpfun-roundtrips/v3";
const ROUNDTRIP_V4 = "pumpfun-roundtrips/v4";

// Settlement policy is selected only from the two engine modes allowed by the contract.
const STRICT_MODE = "EXOGENOUS_REPLAY";
const VIRTUAL_MODE = "EXOGENOUS_VIRTUAL_SETTLEMENT";
// Each execution mode maps to the only settlement policy its evidence may claim.
const SETTLEMENT_POLICIES = new Map([
  [STRICT_MODE, "real-reserve-capped-v1"],
  [VIRTUAL_MODE, "virtual-reserve-output-with-explicit-synthetic-shortfall-v1"],
]);

// Cache stable document roots once; subsequent renders replace only their children.
const dashboardStatus = document.querySelector("#dashboard-status");
const dashboardForm = document.querySelector("#dashboard-run-form");
const artifactInput = document.querySelector("#dashboard-run-artifact-id");
const dashboardError = document.querySelector("#dashboard-error");
const dashboardPrompt = document.querySelector("#dashboard-prompt");
// Content roots are replaced independently so status and errors remain visible.
const dashboardContent = document.querySelector("#dashboard-content");
const dashboardKpis = document.querySelector("#dashboard-kpis");
const dashboardNotices = document.querySelector("#dashboard-data-notices");
const dashboardAnalytics = document.querySelector("#dashboard-analytics");

// Summary badges and verification rows are populated only from the typed API response.
const valuationBadge = document.querySelector("#valuation-badge");
const executionModeBadge = document.querySelector("#execution-mode-badge");
const verificationBody = document.querySelector("#dashboard-verification-body");
const roundtripsBody = document.querySelector("#dashboard-roundtrips-body");

// These controls operate only on the one bounded page held by the browser.
const tradeSearch = document.querySelector("#trade-search");
const tradeStatusFilter = document.querySelector("#trade-status-filter");
const tradeSortField = document.querySelector("#trade-sort-field");
const tradeSortDirection = document.querySelector("#trade-sort-direction");
const tradePageSize = document.querySelector("#trade-page-size");

// Cursor navigation stays separate from page-local filtering and sorting state.
const previousPageButton = document.querySelector("#previous-page");
const nextPageButton = document.querySelector("#next-page");
const pageLabel = document.querySelector("#page-label");
const loadedCount = document.querySelector("#loaded-count");

const countFormatter = new Intl.NumberFormat("ru-RU");
// Artifact and summary state change together only after a verified response.
let currentArtifactId = null;
let currentSummary = null;

// The only retained row payload is the visible page; history stores tiny cursors only.
let currentRoundtripPage = null;
let pageStartCursors = [null];
let currentPageIndex = -1;
let currentPageSize = DEFAULT_ROUNDTRIP_PAGE_SIZE;

// Default sort answers the most common question: newest targets on this page first.
let currentSortField = "TARGET_TIME";
let sortDescending = true;
let loadGeneration = 0;
let pageGeneration = 0;
let pageRequestInFlight = false;

// Abort superseded network work and debounce page-local search rendering.
let activeRequestController = null;
let searchDebounceTimer = null;

// Create text-only HTML nodes for safe, compact render helpers.
function element(tagName, className = "", text = null) {
  const node = document.createElement(tagName);
  // Use DOM properties exclusively; API text is never interpreted as HTML.
  if (className) node.className = className;
  if (text !== null) node.textContent = text;
  return node;
}

// Create SVG nodes while preserving the SVG namespace and accessibility attributes.
function svgElement(tagName, attributes = {}) {
  const node = document.createElementNS(SVG_NAMESPACE, tagName);
  // Chart callers provide a fixed attribute map rather than markup fragments.
  for (const [name, value] of Object.entries(attributes)) {
    node.setAttribute(name, String(value));
  }
  return node;
}

// Read one same-origin JSON resource with a shared deadline and caller cancellation.
async function api(path, { signal = undefined } = {}) {
  // Bound every read even when the local controller becomes suspended or unhealthy.
  const controller = new AbortController();
  let timedOut = false;
  // Local reads have a fixed upper bound so the UI can recover from a stalled server.
  const timeoutId = globalThis.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, API_TIMEOUT_MS);

  // A newer dashboard generation can still cancel before the common deadline.
  const forwardAbort = () => controller.abort();
  if (signal?.aborted) forwardAbort();
  else signal?.addEventListener("abort", forwardAbort, { once: true });
  let response;
  let body;
  // The same abort signal bounds both transport and response parsing.
  try {
    response = await fetch(path, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      // Only this composed controller reaches fetch, avoiding competing signals.
      signal: controller.signal,
    });
    // Parse success and error bodies through one bounded JSON path.
    try {
      body = await response.json();
    } catch (error) {
      // Preserve timeout/caller abort while tolerating a non-JSON error response.
      if (controller.signal.aborted) throw error;
      body = {};
    }
  } catch (error) {
    // Distinguish the stable timeout message from caller-driven cancellation.
    if (timedOut) throw new Error("Локальный API не ответил за 15 секунд");
    throw error;
  } finally {
    // Listener cleanup prevents a settled request retaining its parent controller.
    globalThis.clearTimeout(timeoutId);
    signal?.removeEventListener("abort", forwardAbort);
  }

  // Error bodies are bounded by the API and remain text-only in the DOM.
  if (!response.ok) {
    throw new Error(body.message || body.detail || `HTTP ${response.status}`);
  }
  return body;
}

// Parse one required integer amount without ever passing through Number.
function canonicalAtomic(value, { signed = true } = {}) {
  // API atomic values must remain canonical decimal strings until BigInt parsing.
  if (typeof value !== "string") {
    throw new Error("API вернул atomic amount не в виде decimal string");
  }
  const pattern = signed ? SIGNED_DECIMAL : UNSIGNED_DECIMAL;
  // Canonical syntax prevents ambiguous signs, leading zeroes, and float coercion.
  if (!pattern.test(value)) {
    throw new Error("API вернул неканонический atomic amount");
  }
  return BigInt(value);
}

// Preserve nullable financial semantics while reusing strict integer validation.
function optionalAtomic(value, options = {}) {
  // Null denotes unavailable evidence and is not coerced into a monetary zero.
  return value === null ? null : canonicalAtomic(value, options);
}

// Admit only finite, non-negative counters that JavaScript represents exactly.
function assertCount(value) {
  // Count formatting is allowed only inside JavaScript's exact integer range.
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new Error("API вернул счётчик вне безопасного диапазона UI");
  }
  return value;
}

// Prove summary schema, execution policy, and funding totals before rendering.
function validateSettlementSummary(summary) {
  // Mode and policy are a closed pair defined by the execution contract.
  const expectedPolicy = SETTLEMENT_POLICIES.get(summary.execution_mode);
  if (!expectedPolicy || summary.settlement_policy_id !== expectedPolicy) {
    throw new Error("API вернул несовместимые execution mode и settlement policy");
  }
  // Only versions with an explicit compatibility path are rendered.
  if (![SUMMARY_V2, SUMMARY_V3].includes(summary.summary_schema_id)) {
    throw new Error("API вернул неподдерживаемую schema сводки");
  }
  // These six fields form one all-or-none settlement capability group.
  const fields = [
    "filled_sell_count",
    "real_liquidity_sufficient_filled_sell_count",
    "synthetic_liquidity_used_sell_count",
    // Monetary settlement fields must have the same schema-level availability.
    "gross_sell_settlement_atomic",
    "venue_funded_sell_atomic",
    "synthetic_funded_sell_atomic",
  ];
  // Legacy v2 must expose absence explicitly instead of fabricated zero values.
  if (summary.summary_schema_id === SUMMARY_V2) {
    if (fields.some((field) => summary[field] !== null)) {
      throw new Error("Legacy summary/v2 не должна имитировать settlement evidence");
    }
    // No newer reconciliation applies when all v3-only fields are absent.
    return;
  }
  // Summary v3 requires the complete classification before any ratio is rendered.
  if (fields.some((field) => summary[field] === null)) {
    throw new Error("Summary/v3 не содержит обязательную settlement evidence");
  }
  // Count classification is validated before monetary funding totals.
  const filled = assertCount(summary.filled_sell_count);
  const real = assertCount(summary.real_liquidity_sufficient_filled_sell_count);
  const synthetic = assertCount(summary.synthetic_liquidity_used_sell_count);
  // Filled sell classifications must partition the closed-position population.
  if (filled !== summary.closed_position_count || filled !== real + synthetic) {
    throw new Error("Классификация sell settlement не сходится со сводкой");
  }
  const gross = canonicalAtomic(summary.gross_sell_settlement_atomic, { signed: false });
  const venue = canonicalAtomic(summary.venue_funded_sell_atomic, { signed: false });
  // Funding reconciliation stays in exact integer lamports.
  const syntheticAmount = canonicalAtomic(summary.synthetic_funded_sell_atomic, {
    signed: false,
  });
  // Gross settlement must equal its observed and synthetic funding sources.
  if (gross !== venue + syntheticAmount) {
    throw new Error("Sell settlement не сходится по источникам ликвидности");
  }
  // Strict historical replay can never claim synthetic proceeds.
  if (summary.execution_mode === STRICT_MODE && (synthetic !== 0 || syntheticAmount !== 0n)) {
    throw new Error("Strict replay не может использовать synthetic liquidity");
  }
}

// Format one validated counter for the Russian-language UI.
function formatCount(value) {
  // Locale formatting follows validation so rounded scientific notation cannot appear.
  return countFormatter.format(assertCount(value));
}

// Convert integer lamports into an exact human-readable SOL amount.
function formatSolValue(value) {
  // Keep the sign separate so division and modulo operate on a positive amount.
  const amount = typeof value === "bigint" ? value : canonicalAtomic(value);
  const negative = amount < 0n;
  const absolute = negative ? -amount : amount;
  const whole = absolute / LAMPORTS_PER_SOL;
  const fraction = (absolute % LAMPORTS_PER_SOL).toString(10).padStart(9, "0");
  // Display omits insignificant zeroes while retaining exact input in details.
  const trimmedFraction = fraction.replace(/0+$/, "");
  const decimal = trimmedFraction ? `${whole}.${trimmedFraction}` : whole.toString(10);
  return `${negative ? "−" : ""}${decimal} SOL`;
}

// Format nullable SOL without confusing missing valuation with a zero balance.
function formatOptionalSol(value) {
  // Missing valuation remains visibly unavailable rather than becoming zero SOL.
  const amount = optionalAtomic(value);
  return amount === null ? "Недоступно" : formatSolValue(amount);
}

// Shorten long content identities only in their visible label.
function shortId(value) {
  // Compact labels retain both identity ends; full text remains in title attributes.
  const text = String(value);
  return text.length <= 18 ? text : `${text.slice(0, 9)}…${text.slice(-7)}`;
}

// Sum optional atomic components while retaining arbitrary integer precision.
function sumAtomic(values) {
  // All fee/deposit aggregation uses BigInt and intentionally ignores absent legs.
  return values.reduce((total, value) => {
    if (value === null || value === undefined) return total;
    return total + canonicalAtomic(String(value));
  }, 0n);
}

// Convert a validated display counter for exact ratio arithmetic.
function countAsBigInt(value) {
  // Validate counts before converting so ratio arithmetic never accepts unsafe Numbers.
  return BigInt(String(assertCount(value)));
}

// Render bounded subset ratios to two decimal percentage places using BigInt.
function formatRatio(numerator, denominator) {
  // A zero denominator is undefined and must not be presented as a measured zero.
  if (denominator === 0n) return null;
  if (numerator < 0n || denominator < 0n) {
    throw new Error("Коэффициент не может использовать отрицательные значения");
  }
  // Ratios represent subsets, so an over-full numerator signals inconsistent data.
  if (numerator > denominator) {
    throw new Error("Числитель коэффициента превышает его знаменатель");
  }

  // Scale to hundredths of a percent and round half-up using integer arithmetic.
  const hundredths = (numerator * 10_000n + denominator / 2n) / denominator;
  const whole = hundredths / 100n;
  const fraction = (hundredths % 100n).toString(10).padStart(2, "0");
  return `${whole.toString(10)},${fraction}%`;
}

// Build one derived card through safe DOM nodes shared by every ratio.
function renderAnalyticsCard(card) {
  // Each ratio card carries an explicit denominator definition next to its value.
  const article = element("article", `dashboard-analytic ${card.tone}`);
  const label = element("span", "dashboard-kpi-label", card.label);
  const value = element("strong", "dashboard-analytic-value", card.value);
  const note = element("span", "dashboard-kpi-note", card.note);

  // Append once so assistive live regions do not observe half-built cards.
  article.append(label, value, note);
  dashboardAnalytics.append(article);
}

// Derive high-signal ratios without requesting or iterating the roundtrip table.
function renderAnalytics(summary) {
  // Count ratios are derived from the whole-run summary, never from the visible page.
  const targetCount = countAsBigInt(summary.target_count);
  const acceptedBuys = countAsBigInt(summary.accepted_buy_count);
  const closedPositions = countAsBigInt(summary.closed_position_count);
  const openPositions = countAsBigInt(summary.open_position_count);
  const unvaluedOpen = countAsBigInt(summary.unvalued_open_position_count);

  // Fee composition uses exact lamports and keeps network fees distinct from venue fees.
  const venueFees = sumAtomic([
    summary.protocol_fee_paid_atomic,
    summary.creator_fee_paid_atomic,
  ]);

  // Network fee share is reconciled against the same exact paid-fee denominator.
  const networkFees = sumAtomic([
    summary.network_base_fee_paid_atomic,
    summary.network_priority_fee_paid_atomic,
  ]);
  const totalFees = venueFees + networkFees;

  // Legacy summary/v2 has no settlement classification, so its ratio stays unavailable.
  const grossSettlement = optionalAtomic(summary.gross_sell_settlement_atomic, {
    signed: false,
  });

  // Synthetic funding remains unavailable—not zero—for legacy summary/v2.
  const syntheticFunding = optionalAtomic(summary.synthetic_funded_sell_atomic, {
    signed: false,
  });

  // Reject inconsistent valuation counts instead of clamping an invalid ratio.
  if (unvaluedOpen > openPositions) {
    throw new Error("Число неоценённых позиций превышает число открытых");
  }
  const valuedOpen = openPositions - unvaluedOpen;

  // Strategy conversion, closure, valuation, and fee ratios share integer formatting.
  const acceptance = formatRatio(acceptedBuys, targetCount);
  const closeRate = formatRatio(closedPositions, acceptedBuys);
  const valuationCoverage = formatRatio(valuedOpen, openPositions);
  const venueFeeShare = formatRatio(venueFees, totalFees);

  // Settlement ratio is capability-aware and cannot invent evidence for summary/v2.
  const syntheticShare =
    grossSettlement === null || syntheticFunding === null
      ? null
      : formatRatio(syntheticFunding, grossSettlement);

  // Labels state numerator and denominator so cards remain auditable without tooltips.
  const cards = [
    // Acceptance measures how many targets reached an accepted buy attempt.
    {
      label: "Buy acceptance",
      value: acceptance ?? "—",
      // The note exposes the exact count operands behind the rounded percentage.
      note: `${acceptedBuys} accepted buys / ${targetCount} targets`,
      tone: "neutral",
    },
    // Closure measures completed roundtrips against accepted buy attempts.
    {
      label: "Close rate",
      value: closeRate ?? "—",
      // Failed buys remain in the accepted-buy denominator by explicit definition.
      note: `${closedPositions} closed / ${acceptedBuys} accepted buys`,
      tone: "neutral",
    },
    // Valuation coverage makes partial open-position MTM immediately visible.
    {
      label: "Valuation coverage",
      value: valuationCoverage ?? "—",
      // Coverage concerns open positions because closed PnL is already realized.
      note: `${valuedOpen} valued / ${openPositions} open positions`,
      tone: unvaluedOpen > 0n ? "warning" : "positive",
    },
    // Fee mix distinguishes venue economics from Solana transaction costs.
    {
      label: "Venue share of paid fees",
      value: venueFeeShare ?? "—",
      // Pump protocol plus creator fees form the venue component of all paid fees.
      note: `${venueFees} venue / ${totalFees} total lamports`,
      tone: "neutral",
    },
    // Settlement mix highlights proceeds unavailable from observed real reserves.
    {
      label: "Synthetic sell funding share",
      value: syntheticShare ?? "—",
      // Legacy artifacts get a capability message instead of a fabricated percentage.
      note:
        grossSettlement === null || syntheticFunding === null
          ? "Недоступно для legacy summary/v2"
          : `${syntheticFunding} synthetic / ${grossSettlement} gross lamports`,
      // Synthetic funding is a warning because it is not on-chain executable liquidity.
      tone: syntheticFunding !== null && syntheticFunding > 0n ? "warning" : "positive",
    },
  ];

  // Replace the whole card strip atomically to avoid partial reactive updates.
  dashboardAnalytics.replaceChildren();
  for (const card of cards) renderAnalyticsCard(card);
}

// Publish a compact global load state through the existing live region.
function setStatus(text, tone = "") {
  dashboardStatus.className = tone ? `status ${tone}` : "status";
  dashboardStatus.textContent = text;
}

// Clear stale error text before a new verified interaction begins.
function hideError() {
  dashboardError.hidden = true;
  dashboardError.textContent = "";
}

// Replace the dashboard with one safe, user-readable fatal load error.
function showError(error) {
  dashboardContent.hidden = true;
  dashboardPrompt.hidden = true;
  roundtripsBody.closest("table").setAttribute("aria-busy", "false");
  // Error content always enters through textContent, never server-provided markup.
  dashboardError.hidden = false;
  dashboardError.textContent = error instanceof Error ? error.message : String(error);
  setStatus("Не удалось открыть результат", "error");
}

// Map signed financial outcomes to the dashboard's semantic color vocabulary.
function metricTone(value) {
  if (value === null || value === 0n) return "neutral";
  return value > 0n ? "positive" : "negative";
}

// Build whole-run headline metrics from the validated bounded summary.
function renderKpis(summary) {
  // PnL cards preserve the distinction between realized, partial, and full economics.
  const realized = canonicalAtomic(summary.realized_cash_pnl_atomic);
  const valuedSubtotal = canonicalAtomic(summary.valued_economic_pnl_subtotal_atomic);
  const economic = optionalAtomic(summary.economic_pnl_atomic);
  // Paid fees combine venue and network components without counting rent deposits.
  const feesPaid = sumAtomic([
    summary.protocol_fee_paid_atomic,
    summary.creator_fee_paid_atomic,
    // Network components complete paid fees but exclude refundable deposits.
    summary.network_base_fee_paid_atomic,
    summary.network_priority_fee_paid_atomic,
  ]);
  // Cashback and synthetic settlement stay outside the paid-fee total.
  const cashback = canonicalAtomic(summary.cashback_receivable_atomic, { signed: false });
  const syntheticSettlement = optionalAtomic(summary.synthetic_funded_sell_atomic, {
    signed: false,
  });

  // Card order leads with execution context, then economics, flow, and liquidity risk.
  const cards = [
    // Mode is a headline caveat because virtual settlement is not on-chain executable.
    {
      label: "Execution mode",
      value: summary.execution_mode,
      // Policy ID names the exact solvency semantics behind the mode.
      note: summary.settlement_policy_id,
      tone: summary.execution_mode === VIRTUAL_MODE ? "warning" : "neutral",
    },
    // Realized cash PnL is derived from closed ledger cashflows.
    {
      label: "Realized cash PnL",
      value: formatSolValue(realized),
      // Exact lamports remain visible for ledger reconciliation.
      note: `${summary.realized_cash_pnl_atomic} lamports`,
      tone: metricTone(realized),
    },
    // Full economic PnL stays unavailable when any required valuation is missing.
    {
      label: "Economic PnL",
      value: economic === null ? "Недоступно" : formatSolValue(economic),
      // Missing full valuation gets an explanation instead of a numeric substitute.
      note:
        economic === null
          ? "Не подменяется частичной оценкой"
          : `${summary.economic_pnl_atomic} lamports`,
      // Missing economics is a warning even when the valued subtotal exists.
      tone: economic === null ? "warning" : metricTone(economic),
    },
    // The subtotal communicates measured value without impersonating full economic PnL.
    {
      label: "Valued economic subtotal",
      value: formatSolValue(valuedSubtotal),
      // Note limits the subtotal to positions with an available liquidation quote.
      note: "Только позиции, для которых доступна оценка",
      tone: metricTone(valuedSubtotal),
    },
    // Fee total keeps its exact atomic amount alongside the readable SOL value.
    {
      label: "Оплаченные комиссии",
      value: formatSolValue(feesPaid),
      // Exact total states that both venue and network components are included.
      note: `${feesPaid.toString(10)} lamports · venue + network`,
      tone: "neutral",
    },
    // Target volume is paired with cooldown suppression to explain funnel entry.
    {
      label: "Targets",
      value: formatCount(summary.target_count),
      // Cooldown count explains targets that could not produce an accepted buy.
      note: `${formatCount(summary.cooldown_skipped_count)} пропущено cooldown`,
      tone: "neutral",
    },
    // Accepted buys are paired with landed failures rather than hidden in conversion.
    {
      label: "Accepted buys",
      value: formatCount(summary.accepted_buy_count),
      // Failure count remains adjacent to its accepted-attempt denominator.
      note: `${formatCount(summary.failed_buy_count)} buy failures`,
      tone: "neutral",
    },
    // Position state makes unresolved exposure visible in the first viewport.
    {
      label: "Позиции",
      value: `${formatCount(summary.closed_position_count)} / ${formatCount(summary.open_position_count)}`,
      // Explicit labels prevent the two compact counts being read in reverse.
      note: "closed / open",
      tone: summary.open_position_count > 0 ? "warning" : "positive",
    },
    // Cashback remains a non-spendable receivable instead of wallet cash.
    {
      label: "Cashback receivable",
      value: formatSolValue(cashback),
      // The note prevents receivable from being mistaken for spendable balance.
      note: "Отдельный non-spendable receivable",
      tone: "neutral",
    },
    // Synthetic proceeds are capability-aware and highlighted when actually used.
    {
      label: "Synthetic sell funding",
      value:
        syntheticSettlement === null ? "Недоступно для summary/v2" : formatSolValue(syntheticSettlement),
      // Trade count is shown only when the schema exposes funding classification.
      note:
        summary.synthetic_liquidity_used_sell_count === null
          ? "Legacy result без funding classification"
          : `${formatCount(summary.synthetic_liquidity_used_sell_count)} filled sells`,
      // Actual positive synthetic funding receives the warning treatment.
      tone: syntheticSettlement !== null && syntheticSettlement > 0n ? "warning" : "neutral",
    },
  ];

  // Replace the strip once, then construct cards only from text-safe primitives.
  dashboardKpis.replaceChildren();
  for (const card of cards) {
    const article = element("article", `dashboard-kpi ${card.tone}`);
    const label = element("span", "dashboard-kpi-label", card.label);
    // Value and note remain separate elements for responsive visual hierarchy.
    const value = element("strong", "dashboard-kpi-value", card.value);
    const note = element("span", "dashboard-kpi-note", card.note);
    // Append a complete card so assistive live regions do not see partial contents.
    article.append(label, value, note);
    dashboardKpis.append(article);
  }
}

// Render only caveats that materially affect interpretation or reconciliation.
function renderNotices(summary) {
  dashboardNotices.replaceChildren();
  // Virtual settlement must remain prominently labeled as synthetic liquidity.
  if (summary.execution_mode === VIRTUAL_MODE) {
    const notice = element("p", "dashboard-notice warning");
    // Explain both the quote basis and source of the non-observed proceeds.
    notice.textContent =
      "Синтетический режим: sell оценивается по историческим virtual reserves, а " +
      "дефицит observed real SOL покрывается внешним synthetic source. Такая выплата " +
      "не является on-chain исполнимой ликвидностью.";
    // Notice sits above charts so synthetic interpretation precedes the metrics.
    dashboardNotices.append(notice);
  }
  // Legacy schema cannot provide the newer venue-versus-synthetic classification.
  if (summary.summary_schema_id === SUMMARY_V2) {
    const notice = element("p", "dashboard-notice warning");
    // Capability absence is stated directly rather than inferred from empty charts.
    notice.textContent =
      "Legacy summary/v2: точная классификация venue/synthetic funding в этом artifact отсутствует.";
    dashboardNotices.append(notice);
  }
  // Partial valuation explains why the economic total is intentionally absent.
  if (summary.economic_pnl_atomic === null) {
    const notice = element("p", "dashboard-notice warning");
    // The unvalued position count quantifies the missing economic coverage.
    notice.textContent =
      `Полная economic PnL недоступна: без оценки осталось ` +
      `${formatCount(summary.unvalued_open_position_count)} открытых позиций. ` +
      "Valued economic subtotal выше относится только к оценённой части.";
    // Partial subtotal remains usable only with this explicit coverage warning.
    dashboardNotices.append(notice);
  }

  // Account totals are validated even when no notice is otherwise necessary.
  const paid = canonicalAtomic(summary.account_deposit_paid_atomic, { signed: false });
  const refunded = canonicalAtomic(summary.account_deposit_refunded_atomic, { signed: false });
  const locked = canonicalAtomic(summary.account_deposit_locked_atomic, { signed: false });
  // Paid deposits must partition exactly into returned and still-locked balances.
  if (paid !== refunded + locked) {
    const notice = element("p", "dashboard-notice error");
    // A failed accounting identity is shown as an error-level data caveat.
    notice.textContent =
      "Account deposit reconciliation не сходится: paid не равен refunded + locked.";
    dashboardNotices.append(notice);
  }
}

// Scale a positive BigInt into SVG pixels while keeping non-zero bars visible.
function horizontalBarWidth(value, maximum, width) {
  if (maximum === 0n || value === 0n) return 0n;
  const scaled = (value * BigInt(width)) / maximum;
  return scaled === 0n ? 1n : scaled;
}

// Render one magnitude chart from whole-summary rows without external chart code.
function renderHorizontalChart(containerId, rows, ariaLabel) {
  const container = document.querySelector(`#${containerId}`);
  const maximum = rows.reduce((current, row) => (row.value > current ? row.value : current), 0n);
  // Screen readers receive the same bounded label/value evidence as sighted users.
  const accessibleValues = rows.map((row) => `${row.label}: ${row.display}`).join("; ");
  // Fixed row geometry makes height deterministic for every bounded metric list.
  const rowHeight = 48;
  const height = rows.length * rowHeight + 24;
  const svg = svgElement("svg", {
    class: "chart-svg",
    viewBox: `0 0 820 ${height}`,
    // Native image semantics give the generated chart an accessible name.
    role: "img",
    "aria-label": `${ariaLabel}. ${accessibleValues}`,
  });

  rows.forEach((row, index) => {
    // Labels and bars share a row baseline derived only from their stable index.
    const y = index * rowHeight + 10;
    const label = svgElement("text", { class: "chart-label", x: 8, y: y + 17 });
    label.textContent = row.label;
    // Background track provides a common visual denominator for all rows.
    const track = svgElement("rect", {
      class: "chart-track",
      x: 250,
      y,
      // All tracks share one scale and rounded visual geometry.
      width: 330,
      height: 20,
      rx: 7,
    });
    // Foreground bar encodes the row's exact share of the maximum.
    const bar = svgElement("rect", {
      class: `chart-bar ${row.tone}`,
      x: 250,
      y,
      // Integer scaling avoids precision loss for large atomic values.
      width: horizontalBarWidth(row.value, maximum, 330).toString(10),
      height: 20,
      rx: 7,
    });
    // Numeric label carries the readable value independently of bar length.
    const value = svgElement("text", { class: "chart-value", x: 598, y: y + 17 });
    value.textContent = row.display;
    // A native title exposes the same formatted value to pointer users.
    const title = svgElement("title");
    title.textContent = `${row.label}: ${row.display}`;
    bar.append(title);
    svg.append(label, track, bar, value);
  });
  // Swap the completed SVG into the card in one DOM operation.
  container.replaceChildren(svg);
}

// Render signed values around a fixed zero axis with unavailable rows preserved.
function renderSignedChart(containerId, rows, ariaLabel) {
  const container = document.querySelector(`#${containerId}`);
  // Include unavailable markers as well as measured values in the text alternative.
  const accessibleValues = rows.map((row) => `${row.label}: ${row.display}`).join("; ");
  // Missing values do not influence the shared magnitude scale.
  const magnitudes = rows
    .filter((row) => row.value !== null)
    .map((row) => (row.value < 0n ? -row.value : row.value));
  // Scaling uses the largest absolute measured value across both signs.
  const maximum = magnitudes.reduce((current, value) => (value > current ? value : current), 0n);
  const rowHeight = 48;
  const height = rows.length * rowHeight + 24;
  // The zero axis reserves equal horizontal space for gains and losses.
  const center = 450n;
  const halfWidth = 180n;
  const svg = svgElement("svg", {
    class: "chart-svg",
    viewBox: `0 0 860 ${height}`,
    // The supplied label describes the chart as a single accessible image.
    role: "img",
    "aria-label": `${ariaLabel}. ${accessibleValues}`,
  });
  // A single central axis anchors all signed rows to the same zero coordinate.
  const axis = svgElement("line", {
    class: "chart-zero-axis",
    x1: center.toString(10),
    y1: 2,
    // The axis spans every row but stays inside the SVG viewport.
    x2: center.toString(10),
    y2: height - 6,
  });
  svg.append(axis);

  rows.forEach((row, index) => {
    // Every signed row reserves label, plot, and formatted-value columns.
    const y = index * rowHeight + 10;
    const label = svgElement("text", { class: "chart-label", x: 8, y: y + 17 });
    label.textContent = row.label;
    // Symmetric track shows the available range on both sides of zero.
    const track = svgElement("rect", {
      class: "chart-track",
      x: center - halfWidth,
      y,
      // Fixed track width keeps every signed row on one comparable scale.
      width: halfWidth * 2n,
      height: 20,
      rx: 7,
    });
    // Text value is outside the plot so short bars remain readable.
    const value = svgElement("text", { class: "chart-value", x: 648, y: y + 17 });
    value.textContent = row.display;
    svg.append(label, track);

    // A missing metric keeps its textual placeholder but has no quantitative bar.
    if (row.value !== null) {
      // Only measured values receive a bar; unavailable values retain their label.
      const magnitude = row.value < 0n ? -row.value : row.value;
      const width = horizontalBarWidth(magnitude, maximum, Number(halfWidth));
      const x = row.value < 0n ? center - width : center;
      // Bar origin communicates sign while width communicates absolute magnitude.
      const bar = svgElement("rect", {
        class: `chart-bar ${row.value < 0n ? "negative" : "positive"}`,
        x: x.toString(10),
        y,
        // BigInt width and origin keep the bar exact until SVG string conversion.
        width: width.toString(10),
        height: 20,
        rx: 7,
      });
      // Tooltip text mirrors the visible value without exposing raw markup.
      const title = svgElement("title");
      title.textContent = `${row.label}: ${row.display}`;
      bar.append(title);
      svg.append(bar);
    }
    // Formatted text remains visible for both measured and unavailable rows.
    svg.append(value);
  });
  // Commit the complete signed chart without intermediate render states.
  container.replaceChildren(svg);
}

// Normalize an exact integer counter into the common chart-row contract.
function countRow(label, value, tone) {
  const count = assertCount(value);
  return { label, value: BigInt(String(count)), display: formatCount(count), tone };
}

// Normalize an unsigned atomic amount into the common chart-row contract.
function atomicRow(label, value, tone) {
  const amount = canonicalAtomic(value, { signed: false });
  return { label, value: amount, display: formatSolValue(amount), tone };
}

// Populate every summary chart from one already reconciled run summary.
function renderCharts(summary) {
  // Lifecycle chart presents the target-to-position funnel in causal order.
  renderHorizontalChart(
    "lifecycle-chart",
    [
      countRow("Targets", summary.target_count, "primary"),
      countRow("Cooldown skipped", summary.cooldown_skipped_count, "muted"),
      // Buy acceptance separates attempted execution from later fill outcomes.
      countRow("Accepted buys", summary.accepted_buy_count, "info"),
      countRow("Failed buys", summary.failed_buy_count, "danger"),
      countRow("Closed", summary.closed_position_count, "positive"),
      countRow("Open", summary.open_position_count, "warning"),
    ],
    // Accessible name clarifies that rows use the whole-run summary.
    "Состояния стратегии по полной сводке run",
  );
  // Order chart separates pre-submit rejection from landed execution outcomes.
  renderHorizontalChart(
    "orders-chart",
    // Accepted and rejected are decisions; filled and failed are landed outcomes.
    [
      countRow("Accepted", summary.accepted_order_count, "primary"),
      countRow("Rejected", summary.rejected_order_count, "warning"),
      // Landed outcomes partition orders that passed the acceptance stage.
      countRow("Filled", summary.filled_order_count, "positive"),
      countRow("Failed", summary.failed_order_count, "danger"),
    ],
    // Accessible name explains the two-stage order outcome funnel.
    "Accepted и rejected ордеры, затем filled и failed исходы accepted ордеров",
  );

  const economic = optionalAtomic(summary.economic_pnl_atomic);
  // Signed chart keeps realized, valued subtotal, and complete economics distinct.
  renderSignedChart(
    "pnl-chart",
    // All three rows share the same signed SOL scale around zero.
    [
      {
        label: "Realized cash PnL",
        value: canonicalAtomic(summary.realized_cash_pnl_atomic),
        // Readable SOL is derived from the same exact atomic source value.
        display: formatSolValue(summary.realized_cash_pnl_atomic),
      },
      // Partial valuation is displayed explicitly even when full economics is absent.
      {
        label: "Valued economic subtotal",
        value: canonicalAtomic(summary.valued_economic_pnl_subtotal_atomic),
        // Subtotal remains a measured value even when full economic PnL is absent.
        display: formatSolValue(summary.valued_economic_pnl_subtotal_atomic),
      },
      // Null remains an unavailable full-run result rather than a zero bar.
      {
        label: "Economic PnL",
        value: economic,
        // Unavailable full economics stays explicit in the chart value label.
        display: economic === null ? "Недоступно" : formatSolValue(economic),
      },
    ],
    // Accessible name states both sign and SOL units for assistive users.
    "Signed PnL в SOL по полной сводке run",
  );
  // Fee chart preserves protocol, creator, base, and priority components.
  renderHorizontalChart(
    "fees-chart",
    // Fee components use one scale to reveal their relative cost contribution.
    [
      atomicRow("Pump protocol", summary.protocol_fee_paid_atomic, "primary"),
      atomicRow("Creator", summary.creator_fee_paid_atomic, "info"),
      // Network cost remains visually distinct from Pump fee recipients.
      atomicRow("Network base", summary.network_base_fee_paid_atomic, "warning"),
      atomicRow("Network priority", summary.network_priority_fee_paid_atomic, "muted"),
    ],
    // Accessible name identifies paid fees rather than reserved cash.
    "Оплаченные комиссии в SOL по полной сводке run",
  );
  // Deposit chart makes returned and still-locked rent reconcile with paid rent.
  renderHorizontalChart(
    "deposits-chart",
    // Paid is compared directly with its refunded and locked disposition.
    [
      atomicRow("Paid", summary.account_deposit_paid_atomic, "primary"),
      atomicRow("Refunded", summary.account_deposit_refunded_atomic, "positive"),
      atomicRow("Locked", summary.account_deposit_locked_atomic, "warning"),
    ],
    // Accessible name distinguishes account deposits from trading fees.
    "Account deposits и rent в SOL по полной сводке run",
  );
  const settlementContainer = document.querySelector("#settlement-chart");
  // Settlement source is schema-gated because summary/v2 has no classification.
  if (summary.venue_funded_sell_atomic === null) {
    settlementContainer.replaceChildren(
      element("p", "notice", "Недоступно для legacy summary/v2"),
    );
  } else {
    // Summary/v3 compares observed venue funding against explicit synthetic funding.
    renderHorizontalChart(
      "settlement-chart",
      // Two funding sources partition the gross filled-sell settlement.
      [
        atomicRow("Venue-funded", summary.venue_funded_sell_atomic, "positive"),
        atomicRow("Synthetic-funded", summary.synthetic_funded_sell_atomic, "warning"),
      ],
      // Accessible name communicates that both bars partition gross settlement.
      "Источники gross sell settlement в SOL",
    );
  }
  // Slippage chart distinguishes price movement from explicit limit failures.
  renderHorizontalChart(
    "slippage-chart",
    // Favorable/adverse movement and hard limit failures remain separate outcomes.
    [
      countRow("Favorable landing", summary.favorable_slippage_count, "positive"),
      countRow("Adverse landing", summary.adverse_slippage_count, "warning"),
      // Limit failures remain separate from successfully landed price movement.
      countRow("Buy limit failure", summary.buy_slippage_failure_count, "danger"),
      countRow("Sell limit failure", summary.sell_slippage_failure_count, "danger"),
    ],
    // Accessible name frames the values as landing outcomes and limit failures.
    "Slippage outcomes по полной сводке run",
  );
}

// Append one label/value provenance row without permitting HTML interpretation.
function appendVerificationRow(label, value) {
  const row = element("tr");
  const heading = element("th", "verification-label", label);
  const data = element("td", "mono verification-value", String(value));
  // The first cell identifies its value for assistive table navigation.
  heading.scope = "row";
  data.title = String(value);
  // Row scope and full-value title keep long hashes usable in a compact table.
  row.append(heading, data);
  verificationBody.append(row);
}

// Expose bounded identity, lineage, counts, and settlement evidence for audit.
function renderVerification(summary) {
  const rows = [
    // Identity rows distinguish artifact, semantic run, and physical attempt.
    ["Run artifact ID", summary.run_artifact_id],
    ["Logical run ID", summary.logical_run_id],
    ["Execution attempt ID", summary.execution_attempt_id],
    ["Summary schema", summary.summary_schema_id],
    // Execution rows state the exact settlement and network contracts.
    ["Execution mode", summary.execution_mode],
    ["Settlement policy", summary.settlement_policy_id],
    ["Network", summary.network_id],
    ["Position schema", summary.position_schema_id],
    // Result digests let the operator verify every published output family.
    ["Canonical result hash", summary.canonical_result_hash],
    ["Audit hash", summary.audit_hash],
    ["Ledger hash", summary.ledger_hash],
    ["Fill hash", summary.fill_hash],
    // External table digests bind the unbounded rows omitted from the manifest.
    ["Roundtrip digest", summary.roundtrip_digest],
    ["Final balances digest", summary.final_balances_digest],
    ["Historical groups", formatCount(summary.historical_group_count)],
    ["Historical events", formatCount(summary.historical_event_count)],
    // Execution counters reconcile replay input, delivery, ledger, and fills.
    ["Delivered events", formatCount(summary.delivered_event_count)],
    ["Ledger transactions", formatCount(summary.ledger_transaction_count)],
    ["Fills", formatCount(summary.fill_count)],
    ["Roundtrips", formatCount(summary.roundtrip_count)],
    // Publication counters and settlement totals remain capability-aware.
    ["Final balances", formatCount(summary.final_balances_count)],
    ["Filled sells", summary.filled_sell_count ?? "Недоступно"],
    ["Venue-funded sell", summary.venue_funded_sell_atomic ?? "Недоступно"],
    ["Synthetic-funded sell", summary.synthetic_funded_sell_atomic ?? "Недоступно"],
  ];
  // Replace the verification table only after the complete row model exists.
  verificationBody.replaceChildren();
  for (const [label, value] of rows) appendVerificationRow(label, value);
}

// Render all coordinates of one chain position in a single audit-friendly line.
function positionSummary(position) {
  if (position === null) return "—";
  const event = position.event_index === null ? "—" : String(position.event_index);
  // Boundary remains first because it is the scheduler's canonical hot-path order.
  return (
    `boundary ${position.boundary_ordinal} · block ${position.block_ordinal} · ` +
    `tx ${position.transaction_index} · event ${event}`
  );
}

// Format canonical epoch nanoseconds without unsafe Number conversion.
function formatTargetTime(value) {
  const nanoseconds = canonicalAtomic(value, { signed: false });
  const milliseconds = nanoseconds / 1_000_000n;
  // Values beyond Date's safe numeric input remain exact nanoseconds.
  if (milliseconds > BigInt(Number.MAX_SAFE_INTEGER)) return `${value} ns`;
  const timestamp = new Date(Number(milliseconds));
  return Number.isNaN(timestamp.getTime()) ? `${value} ns` : timestamp.toISOString();
}

// Append one definition-list pair while preserving the full exact value.
function appendDetailRow(list, label, value) {
  const term = element("dt", "detail-term", label);
  // Full value remains selectable and available as a hover title.
  const description = element("dd", "detail-value mono", String(value));
  description.title = String(value);
  list.append(term, description);
}

// Build an expandable cell whose collapsed label answers the common question.
function detailsBlock(summaryText, rows) {
  const details = element("details", "cell-details");
  const summary = element("summary", "cell-details-summary", summaryText);
  const list = element("dl", "cell-detail-list");
  // Detail rows are bounded by fixed schema projections for one result record.
  for (const [label, value] of rows) appendDetailRow(list, label, value);
  details.append(summary, list);
  return details;
}

// Render one buy or sell leg with exact quote, landing, fee, and failure data.
function legCell(leg) {
  const cell = element("td", "dashboard-detail-cell");
  // A missing leg is an expected lifecycle state and receives a compact placeholder.
  if (leg === null) {
    cell.append(element("span", "muted-text", "Не создана"));
    return cell;
  }
  // The collapsed label prioritizes terminal failure or observed landing output.
  const summary = leg.failure_code
    ? `Ошибка: ${leg.failure_code}`
    : leg.landing_out_atomic === null
      ? "Без landing output"
      : `Landed ${shortId(leg.landing_out_atomic)} atomic`;
  // Expanded rows follow causal state, quote evidence, fees, then failure.
  const rows = [
    // Causal coordinates show where the decision and landing occurred.
    ["Side", leg.side],
    ["Decision", positionSummary(leg.decision_position)],
    ["Landing", positionSummary(leg.landing_position)],
    ["Amount in, atomic", leg.amount_in_atomic ?? "—"],
    // Quote rows preserve reference, limit, landed output, and exact slippage.
    ["Reference out, atomic", leg.reference_out_atomic],
    ["Minimum out, atomic", leg.minimum_out_atomic],
    ["Landing out, atomic", leg.landing_out_atomic ?? "—"],
    ["Signed slippage, atomic", leg.signed_slippage_atomic ?? "—"],
    // Venue and network fees remain separate atomic components.
    ["Protocol fee, lamports", leg.protocol_fee_atomic],
    ["Creator fee, lamports", leg.creator_fee_atomic],
    ["Network base fee, lamports", leg.network_base_fee_atomic],
    ["Network priority fee, lamports", leg.network_priority_fee_atomic],
    // Failure remains explicit even when the leg has no landing output.
    ["Failure", leg.failure_code ?? "—"],
  ];
  cell.append(detailsBlock(summary, rows));
  return cell;
}

// Sum all paid fee components for one optional order leg.
function legFeeTotal(leg) {
  if (leg === null) return 0n;
  return sumAtomic([
    leg.protocol_fee_atomic,
    leg.creator_fee_atomic,
    // Network fees are paid independently of Pump program success semantics.
    leg.network_base_fee_atomic,
    leg.network_priority_fee_atomic,
  ]);
}

// Render buy, sell, and combined fee totals for one roundtrip.
function feesCell(item) {
  const buyTotal = legFeeTotal(item.buy);
  const sellTotal = legFeeTotal(item.sell);
  const total = buyTotal + sellTotal;
  // The collapsed value is readable SOL; details retain exact lamports by side.
  const cell = element("td", "dashboard-detail-cell");
  cell.append(
    detailsBlock(formatSolValue(total), [
      ["Buy total", `${formatSolValue(buyTotal)} · ${buyTotal} lamports`],
      ["Sell total", `${formatSolValue(sellTotal)} · ${sellTotal} lamports`],
      // Combined must equal the same two exact side totals shown above.
      ["Combined", `${formatSolValue(total)} · ${total} lamports`],
    ]),
  );
  return cell;
}

// Render mode-specific account deposits and lifecycle components for one mint.
function accountCell(item) {
  const components = Array.isArray(item.account_components) ? item.account_components : [];
  const paid = sumAtomic(components.map((component) => component.paid_atomic));
  const refunded = sumAtomic(components.map((component) => component.refunded_atomic));
  // Locked delta is retained separately from paid and refunded cash movements.
  const locked = sumAtomic(components.map((component) => component.locked_delta_atomic));
  const rows = [
    // Top-level rows summarize the profile, acquired token amount, and cash totals.
    ["Profile", item.account_profile_id],
    ["Acquired token, atomic", item.acquired_token_amount_atomic],
    ["Paid", `${formatSolValue(paid)} · ${paid} lamports`],
    // Refunded and locked amounts partition each account's retained deposit state.
    ["Refunded", `${formatSolValue(refunded)} · ${refunded} lamports`],
    ["Locked delta", `${formatSolValue(locked)} · ${locked} lamports`],
  ];
  // Component details explain wallet-scoped and mint-scoped account lifecycles.
  components.forEach((component, index) => {
    const prefix = `Component ${index + 1}`;
    // Each component retains schema, ownership scope, and lifecycle identity.
    rows.push(
      [`${prefix} schema`, component.requirement_schema_id],
      [`${prefix} scope`, component.scope],
      [`${prefix} lifecycle`, component.lifecycle],
      // Atomic cash fields permit direct component-to-summary reconciliation.
      [`${prefix} paid`, component.paid_atomic],
      [`${prefix} refunded`, component.refunded_atomic],
      [`${prefix} locked`, component.locked_delta_atomic],
    );
  });
  // Only the component count and locked total appear in the collapsed cell.
  const cell = element("td", "dashboard-detail-cell");
  cell.append(detailsBlock(`${components.length} components · ${formatSolValue(locked)} locked`, rows));
  return cell;
}

// Validate one liquidity observation and return its fixed detail-row projection.
function liquidityEvidenceRows(prefix, evidence) {
  if (evidence === null) return [[prefix, "—"]];
  const required = canonicalAtomic(evidence.required_output_atomic, { signed: false });
  // Observed availability and required output share the evidence asset.
  const observed = canonicalAtomic(evidence.observed_available_output_atomic, {
    signed: false,
  });
  // Shortfall is exact positive unmet output, never a negative or inferred float.
  const shortfall = canonicalAtomic(evidence.synthetic_shortfall_atomic, { signed: false });
  if (required > observed ? required - observed !== shortfall : shortfall !== 0n) {
    throw new Error("API вернул несогласованную liquidity evidence");
  }
  return [
    // Policy and asset identify the units and solvency rule for these amounts.
    [`${prefix} policy`, evidence.policy_id],
    [`${prefix} asset`, evidence.asset_id],
    [`${prefix} required`, evidence.required_output_atomic],
    // Observed and synthetic components explain the reference or landing constraint.
    [`${prefix} observed real`, evidence.observed_available_output_atomic],
    [`${prefix} synthetic shortfall`, evidence.synthetic_shortfall_atomic],
  ];
}

// Enforce roundtrip schema and settlement funding invariants before display.
function validateRoundtripSettlement(item) {
  const expectedPolicy = SETTLEMENT_POLICIES.get(item.execution_mode);
  if (!expectedPolicy) throw new Error("API вернул неизвестный execution mode сделки");
  // Legacy v3 is valid only as strict replay with every new evidence field absent.
  if (item.result_schema_id === ROUNDTRIP_V3) {
    if (
      item.execution_mode !== STRICT_MODE ||
      item.sell_reference_liquidity !== null ||
      item.sell_landing_liquidity !== null ||
      // MTM is part of the same all-absent legacy evidence group.
      item.mtm_liquidity !== null ||
      // Settlement amounts cannot appear without the v4 classification contract.
      item.settled_venue_funded_atomic !== null ||
      item.settled_synthetic_funded_atomic !== null
    ) {
      throw new Error("Legacy roundtrip/v3 не может имитировать settlement evidence");
    }
    // Valid legacy rows need no v4 settlement reconciliation.
    return;
  }
  if (item.result_schema_id !== ROUNDTRIP_V4) {
    throw new Error("API вернул неподдерживаемую schema сделки");
  }
  // Every available evidence point must use the policy implied by execution mode.
  for (const evidence of [
    item.sell_reference_liquidity,
    item.sell_landing_liquidity,
    item.mtm_liquidity,
  ]) {
    // Null is allowed for lifecycle stages where that quote never existed.
    if (evidence !== null && evidence.policy_id !== expectedPolicy) {
      throw new Error("Liquidity policy сделки не совпадает с execution mode");
    }
    // Strict mode also rejects policy-consistent evidence with non-zero shortfall.
    if (
      item.execution_mode === STRICT_MODE &&
      evidence !== null &&
      // Strict replay rejects even a reference-only synthetic shortfall claim.
      canonicalAtomic(evidence.synthetic_shortfall_atomic, { signed: false }) !== 0n
    ) {
      throw new Error("Strict replay не может иметь synthetic shortfall");
    }
  }
  // Settled funding fields are mandatory unsigned amounts in roundtrip/v4.
  const venue = canonicalAtomic(item.settled_venue_funded_atomic, { signed: false });
  const synthetic = canonicalAtomic(item.settled_synthetic_funded_atomic, {
    signed: false,
  });
  // Strict mode accepts only fully venue-funded successful settlement.
  if (item.execution_mode === STRICT_MODE && synthetic !== 0n) {
    throw new Error("Strict replay не может иметь synthetic settlement");
  }
  // A closed sell must reconcile exactly to the landing-required gross output.
  if (item.status === "CLOSED") {
    if (item.sell_landing_liquidity === null) {
      throw new Error("Закрытая сделка не содержит landing liquidity evidence");
    }
    // Landing requirement is the authoritative gross output for a filled sell.
    const required = canonicalAtomic(item.sell_landing_liquidity.required_output_atomic, {
      signed: false,
    });
    // Venue and synthetic postings partition all proceeds delivered to the wallet.
    if (venue + synthetic !== required) {
      throw new Error("Funding закрытой сделки не сходится с gross sell output");
    }
  } else if (venue !== 0n || synthetic !== 0n) {
    // Any funding on an unclosed position would contradict ledger settlement.
    throw new Error("Незакрытая сделка не может иметь sell settlement");
  }
}

// Render settlement funding and three causal liquidity checkpoints for one trade.
function liquidityCell(item) {
  validateRoundtripSettlement(item);
  const cell = element("td", "dashboard-detail-cell");
  // Legacy artifacts remain readable but explicitly lack the newer evidence.
  if (item.result_schema_id === ROUNDTRIP_V3) {
    cell.append(element("span", "muted-text", "Legacy v3 · нет evidence"));
    return cell;
  }
  // Roundtrip/v4 exposes exact actually settled venue and synthetic components.
  const venue = canonicalAtomic(item.settled_venue_funded_atomic, { signed: false });
  const synthetic = canonicalAtomic(item.settled_synthetic_funded_atomic, {
    signed: false,
  });
  const rows = [
    // Identity and settled funding lead the expanded evidence view.
    ["Result schema", item.result_schema_id],
    ["Execution mode", item.execution_mode],
    ["Venue-funded settlement", item.settled_venue_funded_atomic],
    ["Synthetic-funded settlement", item.settled_synthetic_funded_atomic],
    // Reference, landing, and MTM evidence retain their distinct causal times.
    ...liquidityEvidenceRows("Reference", item.sell_reference_liquidity),
    ...liquidityEvidenceRows("Landing", item.sell_landing_liquidity),
    ...liquidityEvidenceRows("MTM", item.mtm_liquidity),
  ];
  // Synthetic funding takes precedence in the collapsed warning summary.
  const summary = synthetic > 0n
    ? `${formatSolValue(synthetic)} synthetic`
    : `${formatSolValue(venue)} venue`;
  // Expandable details retain every validated funding and liquidity component.
  cell.append(detailsBlock(summary, rows));
  return cell;
}

// Render the most decision-relevant PnL with all valuation states available on expand.
function pnlCell(item) {
  const realized = optionalAtomic(item.realized_cash_pnl_atomic);
  const economic = optionalAtomic(item.economic_pnl_atomic);
  const mtm = optionalAtomic(item.mtm_cash_pnl_atomic);
  // Visible precedence matches realized cash, then full economics, then open MTM.
  const visible = realized ?? economic ?? mtm;
  const cell = element("td", "dashboard-detail-cell");
  const rows = [
    ["Realized cash PnL", formatOptionalSol(item.realized_cash_pnl_atomic)],
    ["Economic PnL", formatOptionalSol(item.economic_pnl_atomic)],
    // MTM status qualifies both liquidation value and derived cash PnL.
    ["MTM status", item.mtm_status],
    ["MTM liquidation value", formatOptionalSol(item.mtm_liquidation_value_atomic)],
    ["MTM cash PnL", formatOptionalSol(item.mtm_cash_pnl_atomic)],
    // Cashback is shown separately because it is not spendable wallet cash.
    ["Cashback receivable", formatSolValue(item.cashback_receivable_atomic)],
  ];
  cell.append(detailsBlock(visible === null ? "PnL недоступна" : formatSolValue(visible), rows));
  return cell;
}

// Map lifecycle outcomes to a compact semantic badge tone.
function statusTone(status) {
  if (status === "CLOSED") return "succeeded";
  if (status === "COOLDOWN_SKIPPED") return "muted";
  // Any explicit failure or rejection is visually grouped as unsuccessful.
  if (status.includes("FAILED") || status.includes("REJECTED")) return "failed";
  return "running";
}

// Construct one dense but expandable roundtrip row from a typed result record.
function roundtripRow(item) {
  const row = element("tr");

  const target = element("td", "dashboard-detail-cell");
  // Target details preserve exact causal coordinates and stable identities.
  target.append(
    detailsBlock(formatTargetTime(item.target_time_ns), [
      ["Boundary", item.target_position.boundary_ordinal],
      ["Block ordinal", item.target_position.block_ordinal],
      ["Transaction index", item.target_position.transaction_index],
      // Event index may be absent at a transaction boundary.
      ["Event index", item.target_position.event_index ?? "—"],
      ["Target event ID", item.target_event_id],
      ["Roundtrip ID", item.roundtrip_id],
    ]),
  );

  // Long asset and developer identities truncate visually but remain in titles.
  const identity = element("td", "dashboard-identity-cell");
  const asset = element("strong", "mono compact-identity", shortId(item.asset_id));
  asset.title = item.asset_id;
  const developer = element("span", "mono compact-identity", shortId(item.developer_id));
  // Venue remains visible as context below the two primary identities.
  developer.title = item.developer_id;
  const venue = element("span", "muted-text", item.venue_id);
  identity.append(asset, developer, venue);

  const status = element("td");
  // Badge tone supplements, but never replaces, the explicit status text.
  status.append(element("span", `badge ${statusTone(item.status)}`, item.status));

  // Column order mirrors the fixed table headings in sniping-results.html.
  row.append(
    target,
    identity,
    status,
    // Buy and sell cells expose their own causal quote and landing evidence.
    legCell(item.buy),
    legCell(item.sell),
    liquidityCell(item),
    // Financial detail columns remain independently expandable.
    feesCell(item),
    accountCell(item),
    pnlCell(item),
  );
  // Return a complete row so the table never observes a partially populated trade.
  return row;
}

// Expose the single retained bounded page or an explicit unloaded state.
function currentPage() {
  return currentPageIndex < 0 ? null : currentRoundtripPage;
}

// Rebuild the status allowlist from only the page currently held in memory.
function renderStatusOptions(items) {
  // Preserve a still-valid selection while rebuilding values from this page only.
  const selected = tradeStatusFilter.value;
  const statuses = [...new Set(items.map((item) => item.status))].sort();
  tradeStatusFilter.replaceChildren(element("option", "", "Все статусы"));
  tradeStatusFilter.firstElementChild.value = "ALL";

  // A typed option is built with textContent; source strings never become markup.
  for (const status of statuses) {
    const option = element("option", "", status);
    option.value = status;
    tradeStatusFilter.append(option);
  }

  // A status absent from the new page falls back to the explicit unfiltered option.
  tradeStatusFilter.value = statuses.includes(selected) ? selected : "ALL";
}

// Select the same PnL precedence that the visible result cell communicates.
function visibleRoundtripPnl(item) {
  // Match the value shown in the PnL cell: realized, then economic, then MTM.
  return (
    optionalAtomic(item.realized_cash_pnl_atomic) ??
    optionalAtomic(item.economic_pnl_atomic) ??
    optionalAtomic(item.mtm_cash_pnl_atomic)
    // End only after each supported PnL fallback has been considered.
  );
}

// Project one allowlisted comparable value from a roundtrip row.
function roundtripSortValue(item) {
  // Only these explicit fields can influence client-side ordering.
  if (currentSortField === "TARGET_TIME") {
    return canonicalAtomic(item.target_time_ns, { signed: false });
  }

  // Boundary sorting uses the packed canonical position value as an integer.
  if (currentSortField === "TARGET_BOUNDARY") {
    return canonicalAtomic(item.target_position.boundary_ordinal, { signed: false });
  }

  // Status is an opaque enumerated label rather than a user-provided object key.
  if (currentSortField === "STATUS") return String(item.status);

  // Identities remain opaque strings and are compared without interpretation.
  if (currentSortField === "ASSET") return String(item.asset_id);
  if (currentSortField === "DEVELOPER") return String(item.developer_id);
  // Analytical numeric fields reuse the exact value shown by their table cells.
  if (currentSortField === "PNL") return visibleRoundtripPnl(item);
  if (currentSortField === "TOTAL_FEES") {
    return legFeeTotal(item.buy) + legFeeTotal(item.sell);
  }

  // A manipulated select must fail closed instead of indexing arbitrary response data.
  throw new Error("Выбрана неразрешённая сортировка");
}

// Compare strings or BigInts while keeping missing analytical values last.
function compareValues(left, right) {
  // Null means unavailable and always remains after measured values in either direction.
  if (left === null && right === null) return 0;
  if (left === null) return 1;
  if (right === null) return -1;

  // Both operands now have the same accessor-defined scalar type.
  if (left === right) return 0;
  return left < right ? -1 : 1;
}

// Order one page reactively with stable position and identity tie-breakers.
function compareRoundtrips(left, right) {
  // Apply requested direction only to the selected measured field.
  const leftValue = roundtripSortValue(left);
  const rightValue = roundtripSortValue(right);
  let comparison = compareValues(leftValue, rightValue);
  if (leftValue !== null && rightValue !== null && sortDescending) comparison = -comparison;

  // Stable identity tie-breakers prevent rows from jumping across reactive renders.
  if (comparison !== 0) return comparison;
  const leftBoundary = canonicalAtomic(left.target_position.boundary_ordinal, {
    signed: false,
  });

  // Boundary comparison is exact UInt64-style BigInt, never floating point.
  const rightBoundary = canonicalAtomic(right.target_position.boundary_ordinal, {
    signed: false,
  });

  const boundaryComparison = compareValues(leftBoundary, rightBoundary);
  if (boundaryComparison !== 0) return boundaryComparison;

  // Digest identity is the final deterministic order when positions coincide.
  return compareValues(String(left.roundtrip_id), String(right.roundtrip_id));
}

// Apply the explicitly page-local search, status filter, and ordering pipeline.
function filteredAndSortedRoundtrips(items) {
  // Search text and status are deliberately scoped to this one server page.
  const query = tradeSearch.value.trim().toLocaleLowerCase("ru");
  const status = tradeStatusFilter.value;
  const filtered = items.filter((item) => {
    if (status !== "ALL" && item.status !== status) return false;
    if (!query) return true;

    // Search only non-sensitive public result identifiers already present in the row.
    return [item.asset_id, item.developer_id, item.roundtrip_id, item.target_event_id]
      .join(" ")
      .toLocaleLowerCase("ru")
      .includes(query);
  });

  // Sorting mutates only the defensive page copy supplied by the caller.
  return filtered.sort(compareRoundtrips);
}

// Render the one current page without modifying full-run cards or charts.
function renderRoundtripTable({ refreshStatuses = false } = {}) {
  // Replace only the bounded table body; summary charts remain untouched.
  const page = currentPage();
  roundtripsBody.replaceChildren();
  if (page === null || currentSummary === null) return;
  if (refreshStatuses) renderStatusOptions(page.items);
  const items = filteredAndSortedRoundtrips([...page.items]);

  // Empty filter results get one explicit row rather than a blank table.
  if (items.length === 0) {
    const row = element("tr");
    const cell = element("td", "empty", "На текущей странице нет подходящих сделок");
    cell.colSpan = 9;
    row.append(cell);

    // Replace an empty result set with one accessible table message.
    roundtripsBody.append(row);
  } else {
    for (const item of items) roundtripsBody.append(roundtripRow(item));
  }

  // Counts distinguish visible filtered rows, the current page, and the whole run.
  const totalRows = assertCount(currentSummary.roundtrip_count);
  const totalPages = Math.max(1, Math.ceil(totalRows / currentPageSize));
  pageLabel.textContent = `Страница ${currentPageIndex + 1} из ${totalPages}`;

  // The visible count changes with local filters while full-run count does not.
  loadedCount.textContent =
    `Показано ${formatCount(items.length)} из ${formatCount(page.items.length)} на странице · ` +
    `${formatCount(totalRows)} roundtrips`;
  // Navigation availability follows request ownership and the server cursor.
  previousPageButton.disabled = pageRequestInFlight || currentPageIndex === 0;
  nextPageButton.disabled = pageRequestInFlight || page.next_cursor === null;
}

// Enforce the frontend half of the bounded keyset page contract.
function validateRoundtripPage(page, limit) {
  // A malformed or oversized response must never expand the browser memory envelope.
  if (!page || !Array.isArray(page.items) || page.items.length > limit) {
    throw new Error("API вернул некорректную bounded-страницу roundtrips");
  }
  if (page.next_cursor === null) return page;

  // Cursor components remain canonical atomic boundary plus exact digest identity.
  const cursor = page.next_cursor;
  if (typeof cursor !== "object") {
    throw new Error("API вернул некорректный cursor roundtrips");
  }
  // Both cursor coordinates are canonical before they can enter URL parameters.
  canonicalAtomic(cursor.target_boundary_ordinal, { signed: false });
  if (!RUN_ARTIFACT_ID.test(String(cursor.roundtrip_id))) {
    throw new Error("API вернул некорректный cursor roundtrips");
  }

  // Return the same typed page so callers retain no duplicate row collection.
  return page;
}

// Fetch one exact keyset page using only typed query parameters.
async function fetchRoundtripPage(artifactId, cursor, limit, signal) {
  // Keyset cursor preserves bounded reads and avoids offset scans in result artifacts.
  const params = new URLSearchParams({ limit: String(limit) });
  if (cursor !== null) {
    params.set("after_target_boundary_ordinal", String(cursor.target_boundary_ordinal));
    params.set("after_roundtrip_id", String(cursor.roundtrip_id));
  }

  // The path contains only the validated content-addressed artifact ID.
  const page = await api(
    `/api/v1/run-artifacts/${encodeURIComponent(artifactId)}/roundtrips?${params.toString()}`,
    { signal },
  );

  // Validate before this page can replace the currently rendered rows.
  return validateRoundtripPage(page, limit);
}

// Render every whole-run surface from one already validated summary response.
function renderSummary(summary) {
  // Validate and render whole-run facts before deriving any visual ratios.
  validateSettlementSummary(summary);
  renderKpis(summary);
  renderAnalytics(summary);
  renderNotices(summary);

  // Charts and verification expose the same summary without additional requests.
  renderCharts(summary);
  renderVerification(summary);

  // Capability badges surface partial valuation and synthetic execution prominently.
  valuationBadge.textContent = summary.valuation_status;
  valuationBadge.className =
    summary.valuation_status === "COMPLETE" ? "badge succeeded" : "badge warning";
  // Execution badge warns whenever settlement can use synthetic liquidity.
  executionModeBadge.textContent = summary.execution_mode;
  executionModeBadge.className =
    summary.execution_mode === VIRTUAL_MODE ? "badge warning" : "badge succeeded";
}

// Transfer dashboard ownership before parsing or validating a new selection.
function supersedeDashboardRequests() {
  const generation = ++loadGeneration;
  pageGeneration += 1;
  pageRequestInFlight = false;
  // Aborting before validation prevents an older valid response from winning a race.
  if (activeRequestController !== null) activeRequestController.abort();
  activeRequestController = null;
  return generation;
}

// Open one exact result through the combined summary and first-page projection.
async function loadDashboard(artifactId) {
  // Every attempted selection owns a new generation, including an invalid one.
  const generation = supersedeDashboardRequests();
  // Reject anything except the exact content-addressed run identifier before transport.
  if (!RUN_ARTIFACT_ID.test(artifactId)) {
    throw new Error("Run artifact ID должен содержать ровно 64 lowercase hex символа");
  }

  // This controller owns only the newest artifact generation.
  const controller = new AbortController();
  activeRequestController = controller;

  // Reset visible navigation state while one combined summary + first-page read runs.
  hideError();
  dashboardPrompt.hidden = true;
  dashboardContent.hidden = true;
  roundtripsBody.closest("table").setAttribute("aria-busy", "true");
  setStatus("Загружаю проверенный результат…");
  // Cursor navigation remains inert while no verified page is active.
  previousPageButton.disabled = true;

  // Both arrows stay disabled until the first page proves its cursor state.
  nextPageButton.disabled = true;

  // The combined endpoint avoids reopening and revalidating the artifact twice initially.
  const encodedArtifactId = encodeURIComponent(artifactId);
  const params = new URLSearchParams({ limit: String(currentPageSize) });
  let dashboard;
  try {
    // Request body-free GET keeps the dashboard within the read-only control-plane path.
    dashboard = await api(
      `/api/v1/run-artifacts/${encodedArtifactId}/dashboard?${params.toString()}`,
      { signal: controller.signal },
    );
  } finally {
    // Do not retain a settled AbortController past the network portion of this load.
    if (activeRequestController === controller) activeRequestController = null;
  }
  if (generation !== loadGeneration || controller.signal.aborted) return;

  // Cross-check response identity before committing any payload to page state.
  const summary = dashboard.summary;
  if (summary.run_artifact_id !== artifactId) {
    throw new Error("API вернул summary другого Run artifact");
  }
  const firstPage = validateRoundtripPage(dashboard.roundtrips, currentPageSize);

  // Retain only the visible rows; cursor history contains no result records.
  currentArtifactId = artifactId;
  currentSummary = summary;
  currentRoundtripPage = firstPage;
  pageStartCursors = [null];
  currentPageIndex = 0;

  // Filters reset because they are explicitly scoped to the newly loaded page.
  tradeSearch.value = "";
  tradeStatusFilter.value = "ALL";

  // A new artifact always opens newest-first with the selected bounded page size.
  currentSortField = "TARGET_TIME";
  sortDescending = true;
  tradeSortField.value = currentSortField;
  updateSortDirectionButton();

  // Reveal only after cards, charts, and the bounded page all reconcile.
  renderSummary(summary);
  renderRoundtripTable({ refreshStatuses: true });
  roundtripsBody.closest("table").setAttribute("aria-busy", "false");
  // Content becomes visible only after every summary and page render succeeds.
  dashboardContent.hidden = false;
  setStatus("Результат проверен и открыт", "ok");
}

// Resolve a typed form ID and optionally reflect it in browser history.
async function openArtifactFromInput({ updateHistory = true } = {}) {
  const artifactId = artifactInput.value.trim();
  if (!RUN_ARTIFACT_ID.test(artifactId)) {
    // Invalid input still supersedes an older valid request before surfacing its error.
    supersedeDashboardRequests();
    throw new Error("Run artifact ID должен содержать ровно 64 lowercase hex символа");
  }
  // History records only exact artifact IDs, never page cursors or row payloads.
  if (updateHistory) {
    const url = new URL("/sniping-results", globalThis.location.origin);
    url.searchParams.set("run_artifact_id", artifactId);
    // Push retains a navigable run selection without triggering a page reload.
    globalThis.history.pushState({}, "", url);
  }
  await loadDashboard(artifactId);
}

// Keep visual text and accessible pressed state synchronized for sort direction.
function updateSortDirectionButton() {
  // Text and pressed state expose direction without relying on arrow shape alone.
  tradeSortDirection.textContent = sortDescending
    ? "↓ По убыванию"
    : "↑ По возрастанию";
  tradeSortDirection.setAttribute("aria-pressed", String(sortDescending));
}

// Surface page errors without discarding the last verified summary and page.
function showPageError(error) {
  // Keep the last valid page visible while reporting a recoverable navigation failure.
  dashboardError.hidden = false;
  dashboardError.textContent = error instanceof Error ? error.message : String(error);
  setStatus("Ошибка страницы сделок", "error");
}

// Replace one bounded page using a stale-safe, abortable keyset request.
async function navigateToPage(
  targetIndex,
  cursor,
  { supersede = false, pageSize = currentPageSize } = {},
) {
  // One in-flight page request at a time prevents races from repeated arrow clicks.
  if (currentArtifactId === null || (pageRequestInFlight && !supersede)) return;
  const artifactId = currentArtifactId;
  const generation = ++pageGeneration;
  if (activeRequestController !== null) activeRequestController.abort();

  // The new controller supersedes any page-size request that has become stale.
  const controller = new AbortController();

  // Busy state is committed before transport so arrows cannot race the request.
  activeRequestController = controller;
  pageRequestInFlight = true;
  roundtripsBody.closest("table").setAttribute("aria-busy", "true");
  let committed = false;
  hideError();

  // Rendering here disables both arrows while preserving the current rows.
  renderRoundtripTable();
  setStatus("Загружаю bounded-страницу…");

  try {
    // Fetch exactly one page from the immutable artifact at its keyset start cursor.
    const page = await fetchRoundtripPage(
      artifactId,
      cursor,
      pageSize,
      // AbortSignal prevents an obsolete page response from consuming more browser work.
      controller.signal,
    );

    // A superseded response cannot commit even when it eventually resolves.
    if (generation !== pageGeneration || controller.signal.aborted) return;

    // Commit the new page atomically and discard all rows from the previous page.
    currentRoundtripPage = page;
    currentPageIndex = targetIndex;
    currentPageSize = pageSize;
    tradeSearch.value = "";

    // Status options are rebuilt after resetting the prior page-local selection.
    tradeStatusFilter.value = "ALL";
    committed = true;
    setStatus("Страница сделок открыта", "ok");
  } catch (error) {
    // Abort is an expected result of opening another run or changing page size.
    if (!(error instanceof DOMException && error.name === "AbortError")) {
      showPageError(error);
    }
  } finally {
    // Only the latest request may restore controls and render its page.
    if (generation === pageGeneration) {
      pageRequestInFlight = false;
      roundtripsBody.closest("table").setAttribute("aria-busy", "false");
      renderRoundtripTable({ refreshStatuses: true });
    }

    // Never clear a newer controller installed by a superseding request.
    if (activeRequestController === controller) activeRequestController = null;
  }
  return committed;
}

// Advance from the current page using only its server-issued continuation cursor.
async function nextPage() {
  // The server-provided cursor is the sole authority for the following page.
  const page = currentPage();
  if (page === null || page.next_cursor === null) return;
  const targetIndex = currentPageIndex + 1;

  // Cursor history is truncated on every new branch and contains no row payloads.
  pageStartCursors[targetIndex] = page.next_cursor;
  pageStartCursors.length = targetIndex + 1;
  await navigateToPage(targetIndex, page.next_cursor);
}

// Move backward by re-fetching the prior keyset start rather than caching its rows.
async function previousPage() {
  // Re-fetch the prior page from its tiny stored start cursor; prior rows are not cached.
  if (currentPageIndex <= 0) return;
  const targetIndex = currentPageIndex - 1;
  const cursor = pageStartCursors[targetIndex];
  await navigateToPage(targetIndex, cursor);
}

// Rebase cursor navigation when the user changes the bounded page size.
async function resetPageWindow(pageSize) {
  // A page-size change invalidates later cursors only after the new first page commits.
  if (currentArtifactId === null) return;
  const committed = await navigateToPage(0, null, { supersede: true, pageSize });
  if (committed) {
    // Successful rebase invalidates every cursor from the previous page geometry.
    pageStartCursors = [null];
    tradePageSize.value = String(pageSize);
  } else if (tradePageSize.value === String(pageSize)) {
    // Keep the selector consistent with the last verified page after a failed request.
    tradePageSize.value = String(currentPageSize);
  }
}

// Read a single exact artifact identity from the dashboard URL.
function artifactIdFromLocation() {
  const params = new URLSearchParams(globalThis.location.search);
  const values = params.getAll("run_artifact_id");
  // Duplicate parameters are ambiguous and therefore rejected before transport.
  if (values.length > 1) {
    throw new Error("В URL должен быть только один Run artifact ID");
  }
  // Missing parameter selects the empty prompt; validation happens before loading.
  return values.length === 0 ? null : values[0].trim();
}

// Recognize only browser-standard aborts produced by the dashboard controllers.
function isAbortError(error) {
  // Superseded requests are expected control flow, not user-visible failures.
  return error instanceof DOMException && error.name === "AbortError";
}

// Hide expected aborts and delegate only actionable failures to the full error view.
function handleDashboardLoadError(error) {
  // Only genuine load errors replace the dashboard with an error state.
  if (!isAbortError(error)) showError(error);
}

// Coalesce rapid keystrokes before rebuilding rows with nested detail controls.
function scheduleSearchRender() {
  // Debouncing avoids rebuilding a detail-heavy table for every fast keystroke.
  if (searchDebounceTimer !== null) globalThis.clearTimeout(searchDebounceTimer);
  searchDebounceTimer = globalThis.setTimeout(() => {
    searchDebounceTimer = null;
    renderRoundtripTable();
  }, 180);

  // The timer handle remains the only retained debounce state.
}

// Apply one safe page-local comparator selected by the user.
function applySelectedSort() {
  // Select values are still checked against an explicit allowlist at runtime.
  const field = tradeSortField.value;
  if (!ROUNDTRIP_SORT_FIELDS.has(field)) {
    tradeSortField.value = currentSortField;
    showPageError(new Error("Выбрана неразрешённая сортировка"));

    // Do not render until the select is restored to its last valid field.
    return;
  }

  // Reactive sort changes only DOM order for the current page.
  currentSortField = field;
  hideError();
  renderRoundtripTable();
  setStatus("Страница отсортирована локально", "ok");
}

// Validate a user-selected page size before issuing another bounded request.
function applySelectedPageSize() {
  // Page-size options remain bounded by the API maximum even if the DOM is modified.
  const size = Number(tradePageSize.value);
  if (!Number.isSafeInteger(size) || !ALLOWED_PAGE_SIZES.has(size)) {
    tradePageSize.value = String(currentPageSize);
    showPageError(new Error("Выбран неразрешённый размер страницы"));

    // Keep the current page unchanged when the DOM value is outside the allowlist.
    return;
  }

  // Reset to the first keyset page; the new size commits only with its verified response.
  void resetPageWindow(size);
}

dashboardForm.addEventListener("submit", (event) => {
  // Disable duplicate form submits until the selected artifact has resolved.
  event.preventDefault();
  const button = dashboardForm.querySelector("button[type='submit']");
  button.disabled = true;
  // Re-enable submission after success, typed failure, timeout, or supersession.
  openArtifactFromInput()
    .catch(handleDashboardLoadError)
    // Button ownership ends after every terminal promise outcome.
    .finally(() => {
      button.disabled = false;
    });
});

// Navigation loads one page on demand and never appends rows from prior pages.
nextPageButton.addEventListener("click", () => void nextPage());
previousPageButton.addEventListener("click", () => void previousPage());
tradeSearch.addEventListener("input", scheduleSearchRender);
tradeStatusFilter.addEventListener("change", () => renderRoundtripTable());
tradeSortField.addEventListener("change", applySelectedSort);

// Direction and size changes update the current page without an unbounded read.
tradeSortDirection.addEventListener("click", () => {
  sortDescending = !sortDescending;
  updateSortDirectionButton();
  renderRoundtripTable();

  // Direction changes are immediate because no network request is needed.
  hideError();
  setStatus("Страница отсортирована локально", "ok");
});

// Page size changes trigger a fresh first-page request, not a client-side slice.
tradePageSize.addEventListener("change", applySelectedPageSize);

// Back/forward navigation replaces the selected artifact without retaining its rows.
globalThis.addEventListener("popstate", () => {
  try {
    const artifactId = artifactIdFromLocation();
    if (artifactId === null) {
      // Abort the previous artifact and discard its single retained page.
      supersedeDashboardRequests();
      // Artifact and summary ownership end together when the URL has no run ID.
      currentArtifactId = null;
      currentSummary = null;

      // Return to the empty prompt without preserving result rows in memory.
      currentRoundtripPage = null;
      pageStartCursors = [null];
      currentPageIndex = -1;
      roundtripsBody.closest("table").setAttribute("aria-busy", "false");
      // Empty state hides verified content before exposing the prompt again.
      dashboardContent.hidden = true;
      dashboardPrompt.hidden = false;
      // Error and status surfaces return to their neutral empty-state values.
      hideError();
      setStatus("Ожидаю Run artifact ID");
      return;
    }
    // A non-empty history entry follows the same validated load path as the form.
    artifactInput.value = artifactId;
    loadDashboard(artifactId).catch(handleDashboardLoadError);
  } catch (error) {
    // URL parsing errors cannot preserve a trustworthy prior selection.
    supersedeDashboardRequests();
    showError(error);
  }
});

// Deep links open the exact artifact through the same combined bounded endpoint.
try {
  const initialArtifactId = artifactIdFromLocation();
  // Initial empty URLs keep the prompt; exact IDs begin one bounded load.
  if (initialArtifactId !== null) {
    artifactInput.value = initialArtifactId;
    loadDashboard(initialArtifactId).catch(handleDashboardLoadError);
  }
} catch (error) {
  // Malformed deep links use the same safe error surface as request failures.
  showError(error);
}
