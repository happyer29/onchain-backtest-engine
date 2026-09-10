// Cache stable DOM anchors once; dynamic result rows are created separately below.
const health = document.querySelector("#health");
const jobsBody = document.querySelector("#jobs-body");
const rowTemplate = document.querySelector("#job-row-template");
const resourcesResult = document.querySelector("#resources-result");
const runsBody = document.querySelector("#runs-body");

// Result panels and contract controls are shared by the typed form workflows.
const runsResult = document.querySelector("#runs-result");
const runComparisonMetric = document.querySelector("#run-comparison-metric");
const prepareButton = document.querySelector("#prepare-dataset");
const mlContractStatus = document.querySelector("#ml-contract-status");
const snipingContractStatus = document.querySelector("#sniping-contract-status");

// The compact Sniping view keeps its own bounded navigation state.
const snipingExecutionMode = document.querySelector("#sniping-execution-mode");
const snipingExecutionWarning = document.querySelector("#sniping-execution-warning");
const snipingRoundtripsBody = document.querySelector("#sniping-roundtrips-body");
const snipingPreviousPage = document.querySelector("#sniping-previous-page");
const snipingNextPage = document.querySelector("#sniping-next-page");

// Bind bounded-page controls once; event handlers never query arbitrary selectors.
const snipingSummaryCards = document.querySelector("#sniping-summary-cards");
const snipingPageLabel = document.querySelector("#sniping-page-label");
const snipingPageSort = document.querySelector("#sniping-page-sort");
const snipingPageSortDirection = document.querySelector("#sniping-page-sort-direction");

// Keep list page sizes below API limits and browser-memory pressure.
const JOBS_PAGE_SIZE = 20;
const RUNS_PAGE_SIZE = 10;
const SNIPING_PAGE_SIZE = 25;
// Active work stays responsive; idle telemetry deliberately backs off.
const ACTIVE_JOB_POLL_MS = 2000;
const IDLE_JOB_POLL_MS = 12000;
const RESOURCE_POLL_MS = 20000;
const API_TIMEOUT_MS = 15000;
const RUN_PRODUCING_JOB_TYPES = new Set(["RUN_BACKTEST", "RUN_SWEEP"]);
// Only these closed physical backends publish the Sniping result contract.
const PUMPFUN_SNIPING_BACKENDS = new Set([
  "reference-pumpfun-sniping-v1",
  "numpy-mmap-pumpfun-sniping-v1",
  "reference-pumpfun-copy-buy-v1",
]);

// Resolved form contracts are transient UI state, never execution authority.
let resolvedDatasetPlan = null;
let mlContract = null;
// Discovery responses stay separate from selected result-artifact state.
let snipingContract = null;
// Copy discovery does not inherit Sniping timing or launch semantics.
let copyContract = null;
let snipingRunArtifactId = null;
// A cursor stack supports previous/next without retaining prior result rows.
let snipingPageCursors = [null];
let snipingPageIndex = 0;
let snipingNextCursor = null;
let snipingPageItems = [];
let snipingSortDirection = "desc";
// Generation and abort state prevent a stale page from replacing a newer selection.
let snipingLoadGeneration = 0;
let snipingRequestController = null;

// Keep result comparison and bounded job-event state independent from sniping pages.
let lastRuns = [];
let activeEventsJobId = null;
// Event history is already server-bounded and is independent from list pagination.
let activeEventsCursor = 0;
let activeEventsHistory = [];
// One selected-job request owns the cursor until its guarded commit completes.
let activeEventsGeneration = 0;
let activeEventsRequestController = null;
let activeEventsRequestPromise = null;
// List state retains one row page plus tiny server-issued cursor histories.
let jobsPageIndex = 0;
let jobsPageItems = [];
let jobsHasNext = false;
let jobsPageCursors = [null];
let jobsNextCursor = null;
let jobsSortDirection = "desc";
// Run selection is page-local but survives a current-page resort.
let runsPageIndex = 0;
let runsPageItems = [];
let runsHasNext = false;
let runsPageCursors = [null];
let runsNextCursor = null;
let runsSortDirection = "desc";
let selectedRunIds = new Set();

// Fingerprints avoid replacing live DOM nodes when a poll returns unchanged data.
let jobsRenderFingerprint = null;
let runsRenderFingerprint = null;
let previousJobStates = new Map();
// Request flags serialize each bounded list without blocking unrelated panels.
let jobsInitialized = false;
let jobsRequestInFlight = false;
let jobsLatestRefreshPending = false;
// A pending flag coalesces a completion-triggered run refresh with an in-flight read.
let runsRequestInFlight = false;
let runsRefreshPending = false;
let watchedRunJobIds = new Set();
let jobPollTimer = null;
let resourcePollTimer = null;

// All browser requests share timeout, same-origin credentials, and safe error parsing.
async function api(path, options = {}) {
  const { headers = {}, signal: sourceSignal = null, ...requestOptions } = options;
  // Only mutations receive the same-origin CSRF marker expected by the controller.
  const method = (requestOptions.method || "GET").toUpperCase();
  const mutationHeaders = ["GET", "HEAD", "OPTIONS"].includes(method)
    ? {}
    : { "X-Backtest-CSRF": "1" };
  // A suspended local controller must not leave every control waiting forever.
  const controller = new AbortController();
  let timedOut = false;
  // Record deadline ownership so caller cancellation is not mislabeled as a timeout.
  const timeoutId = globalThis.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, API_TIMEOUT_MS);

  // Forward caller cancellation while preserving the common request deadline.
  const forwardAbort = () => controller.abort();
  if (sourceSignal?.aborted) forwardAbort();
  else sourceSignal?.addEventListener("abort", forwardAbort, { once: true });
  // Keep transport state local so cleanup runs for fetch and body-decoding failures.
  let response;
  let body;
  try {
    // Same-origin credentials and a JSON-only accept header define the read boundary.
    response = await fetch(path, {
      ...requestOptions,
      credentials: "same-origin",
      headers: { Accept: "application/json", ...mutationHeaders, ...headers },
      // One combined signal enforces both the common deadline and caller supersession.
      signal: controller.signal,
    });
    try {
      body = await response.json();
    } catch (error) {
      // Preserve timeout/caller abort while tolerating a non-JSON error response.
      if (controller.signal.aborted) throw error;
      body = {};
    }
    // A non-JSON successful body is handled later as an empty typed object.
  } catch (error) {
    // Translate only a deadline owned by this helper into the stable Russian message.
    if (timedOut) throw new Error("Локальный API не ответил за 15 секунд");
    throw error;
  } finally {
    // Release both timer and forwarded listener for every terminal request path.
    globalThis.clearTimeout(timeoutId);
    sourceSignal?.removeEventListener("abort", forwardAbort);
  }
  // API errors remain text-only and never inject response markup into the page.
  if (!response.ok) {
    throw new Error(body.message || body.detail || `HTTP ${response.status}`);
  }
  return body;
}

// Render command output safely in the preformatted result panels.
function showResult(element, value, isError = false) {
  element.hidden = false;
  element.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  element.classList.toggle("error", isError);
}

// Idempotency keys are random request identifiers, not semantic run identity.
function randomDigest() {
  const bytes = new Uint8Array(32);
  globalThis.crypto.getRandomValues(bytes);
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

// Form parsing helpers keep validation at the browser boundary for faster feedback.
function valuesOf(form) {
  return new FormData(form);
}

// Required text is trimmed once before it enters any typed request payload.
function textField(form, name) {
  const raw = valuesOf(form).get(name);
  if (typeof raw !== "string" || !raw.trim()) {
    throw new Error(`${name}: поле обязательно`);
  }
  // Canonical whitespace never becomes part of an artifact or profile identity.
  return raw.trim();
}

// Optional identifiers use null, never an ambiguous empty string, on the wire.
function optionalText(values, name) {
  const value = values.get(name);
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

// JSON numeric fields are restricted to exact JavaScript-safe non-negative integers.
function integerField(form, name) {
  const raw = valuesOf(form).get(name);
  if (typeof raw !== "string" || !/^\d+$/.test(raw)) {
    throw new Error(`${name}: ожидается целое неотрицательное число`);
  }
  // Reject precision loss before converting canonical decimal text to Number.
  const value = Number(raw);
  if (!Number.isSafeInteger(value)) {
    throw new Error(`${name}: число выходит за безопасный диапазон UI`);
  }
  // The typed API receives the validated integral Number unchanged.
  return value;
}

// Atomic amounts remain canonical decimal strings and are validated through BigInt.
function atomicDecimalField(form, name, { positive = false } = {}) {
  const raw = valuesOf(form).get(name);
  if (typeof raw !== "string" || !/^(0|[1-9]\d*)$/.test(raw)) {
    throw new Error(`${name}: ожидается canonical unsigned decimal string`);
  }
  // BigInt proves positivity without narrowing money to a floating-point value.
  const value = BigInt(raw);
  if (positive && value === 0n) throw new Error(`${name}: значение должно быть положительным`);
  return value.toString(10);
}

// Sweep seeds preserve input order while rejecting unsafe or duplicate values.
function integerList(form, name) {
  const values = textField(form, name)
    .split(",")
    .map((item) => Number(item.trim()));
  // Every seed must survive exact JSON Number transport.
  if (values.some((value) => !Number.isSafeInteger(value) || value < 0)) {
    throw new Error(`${name}: ожидается список неотрицательных целых чисел`);
  }
  // Duplicate seeds would describe the same logical sweep member twice.
  if (new Set(values).size !== values.length) {
    throw new Error(`${name}: значения должны быть уникальны`);
  }
  // The validated array can now be embedded directly into the typed sweep request.
  return values;
}

// Artifact lists accept only unique exact SHA-256 identities in canonical order.
function idList(values, name) {
  const value = values.get(name);
  if (typeof value !== "string" || !value.trim()) return [];
  const result = value
    .split(",")
    // Normalize human-entered separators before validating content identities.
    .map((item) => item.trim())
    // Empty comma-separated entries carry no identity and are discarded explicitly.
    .filter(Boolean)
    .sort();
  if (result.some((item) => !/^[0-9a-f]{64}$/.test(item))) {
    throw new Error(`${name}: нужны exact lowercase SHA-256 IDs`);
  }
  // Sorting above makes duplicate detection independent from entry order.
  if (new Set(result).size !== result.length) {
    throw new Error(`${name}: IDs должны быть уникальны`);
  }
  return result;
}

// Capability columns are a required, unique, canonicalized token list.
function tokenList(values, name) {
  const raw = values.get(name);
  if (typeof raw !== "string") return [];
  const result = raw.split(",").map((item) => item.trim()).filter(Boolean).sort();
  // Empty or repeated columns would make the acquisition requirement ambiguous.
  if (result.length === 0 || new Set(result).size !== result.length) {
    throw new Error(`${name}: значения обязательны и должны быть уникальны`);
  }
  // Stable ordering keeps otherwise equivalent plan requests byte-consistent.
  return result;
}

// Build the closed FirstSwap draft without copying transport or physical settings into it.
function runDraft(form, rootSeed = null) {
  const values = valuesOf(form);
  const soldAsset = textField(form, "sold_asset_id");
  return {
    // Replay inputs are exact artifact identities selected by the operator.
    snapshot_id: textField(form, "snapshot_id"),
    replay_pack_id: optionalText(values, "replay_pack_id"),
    delivery_schedule_id: optionalText(values, "delivery_schedule_id"),
    // Venue and asset fields define the strategy's typed trading pair.
    pool_id: textField(form, "pool_id"),
    sold_asset_id: soldAsset,
    bought_asset_id: textField(form, "bought_asset_id"),
    // Order amounts and fees remain integer domain inputs.
    amount_in_atomic: integerField(form, "amount_in_atomic"),
    minimum_amount_out_atomic: integerField(form, "minimum_amount_out_atomic"),
    fee_bps: integerField(form, "fee_bps"),
    // Execution delays and limits are semantic draft fields, not UI timing knobs.
    execution_mode: values.get("execution_mode"),
    maximum_order_input_atomic: integerField(form, "maximum_order_input_atomic"),
    observation_slots: integerField(form, "observation_slots"),
    order_slots: integerField(form, "order_slots"),
    // The initial portfolio carries the same asset selected as order input.
    initial_portfolio: [
      { asset_id: soldAsset, amount_atomic: integerField(form, "initial_balance_atomic") },
    ],
    root_seed: rootSeed === null ? integerField(form, "root_seed") : rootSeed,
    maximum_dynamic_items: 1000000,
    // ML dependencies remain exact optional inputs with explicit inference policy.
    feature_set_ids: idList(values, "feature_set_ids"),
    model_schedule_id: optionalText(values, "model_schedule_id"),
    prediction_set_ids: idList(values, "prediction_set_ids"),
    inference_mode: values.get("inference_mode"),
    // Prediction naming and availability delay stay separate from artifact identities.
    prediction_name: optionalText(values, "prediction_name"),
    inference_missing_policy: values.get("inference_missing_policy"),
    inference_delay_boundaries: integerField(form, "inference_delay_boundaries"),
  };
}

// Materialize one side-specific Solana network-fee profile from typed form fields.
function solanaFeeProfile(form, side) {
  return {
    // Version and effective interval identify which fee rules apply.
    profile_id: textField(form, `${side}_fee_profile_id`),
    formula_version: textField(form, `${side}_fee_formula_version`),
    transaction_format: textField(form, `${side}_transaction_format`),
    effective_from_unix_s: integerField(form, `${side}_fee_effective_from`),
    effective_until_unix_s: integerField(form, `${side}_fee_effective_until`),
    // Signature and compute inputs determine exact base and priority fees.
    charged_signature_count: integerField(form, `${side}_signature_count`),
    lamports_per_signature: atomicDecimalField(form, `${side}_lamports_per_signature`, {
      positive: true,
    }),
    // Priority fee calculation uses the exact CU limit and micro-lamport price.
    compute_unit_limit: integerField(form, `${side}_compute_unit_limit`),
    // Micro-lamports remain decimal text until the resolver performs integer math.
    micro_lamports_per_compute_unit: atomicDecimalField(
      form,
      `${side}_micro_lamports_per_cu`,
    ),
    // The returned object is a complete side-specific profile, not a partial override.
  };
}

// Build only the strict Sniping v3 semantic draft discovered from the API contract.
function pumpfunSnipingDraft(form) {
  if (snipingContract === null) throw new Error("Sniping contract ещё не загружен");
  const values = valuesOf(form);
  return {
    // Exact local inputs identify the prepared single-network replay closure.
    contract_schema: snipingContract.schema,
    dataset_revision_id: textField(form, "dataset_revision_id"),
    snapshot_id: textField(form, "snapshot_id"),
    replay_pack_id: optionalText(values, "replay_pack_id"),
    delivery_schedule_id: optionalText(values, "delivery_schedule_id"),
    // Cash, budget, slippage, and latency are canonical strategy inputs.
    initial_sol_balance_lamports: atomicDecimalField(form, "initial_sol_balance_lamports"),
    gross_buy_budget_lamports: atomicDecimalField(form, "gross_buy_budget_lamports", {
      positive: true,
    }),
    // Buy and sell limits are independent, even when the form displays equal defaults.
    buy_slippage_bps: integerField(form, "buy_slippage_bps"),
    sell_slippage_bps: integerField(form, "sell_slippage_bps"),
    execution_mode: values.get("execution_mode"),
    sell_delay_transactions: integerField(form, "sell_delay_transactions"),
    // Wallet profile version and effective interval pin account lifecycle semantics.
    wallet_account_profile: {
      schema: "pumpfun-solana-wallet-account-profile/v2",
      profile_id: textField(form, "wallet_profile_id"),
      // Initial UVA state and effective interval are resolved as one profile.
      initial_uva_state: values.get("wallet_mode"),
      effective_from_unix_s: integerField(form, "wallet_effective_from"),
      effective_until_unix_s: integerField(form, "wallet_effective_until"),
      account_costs: [
        // The wallet-scoped UVA is distinct from each position's token account.
        {
          requirement_schema_id: "pumpfun-user-volume-accumulator-v1",
          deposit_lamports: atomicDecimalField(form, "uva_rent_lamports", { positive: true }),
        },
        // Legacy and Token-2022 ATAs retain separate rent requirements.
        {
          requirement_schema_id: "solana-associated-token-account-legacy-v1",
          // Legacy ATA rent must remain a positive atomic lamport amount.
          deposit_lamports: atomicDecimalField(form, "legacy_ata_rent_lamports", {
            positive: true,
          }),
        },
        // Immutable-owner Token-2022 accounts use their own requirement identity.
        {
          requirement_schema_id:
            "solana-associated-token-account-token-2022-immutable-owner-v1",
          // Token-2022 may require a different account size and deposit.
          deposit_lamports: atomicDecimalField(form, "token_2022_ata_rent_lamports", {
            positive: true,
          }),
          // Resolver validates this deposit against the selected effective profile.
        },
      ],
    },
    // Pump fee math is versioned and effective-dated independently from network fees.
    pump_fee_profile: {
      profile_id: textField(form, "pump_profile_id"),
      program_version: textField(form, "pump_program_version"),
      buy_formula_version: textField(form, "pump_buy_formula_version"),
      sell_formula_version: textField(form, "pump_sell_formula_version"),
      // Both fee components are supplied as integer basis points.
      effective_from_unix_s: integerField(form, "pump_effective_from"),
      effective_until_unix_s: integerField(form, "pump_effective_until"),
      protocol_fee_bps: integerField(form, "pump_protocol_fee_bps"),
      creator_fee_bps: integerField(form, "pump_creator_fee_bps"),
    },
    // Buy and sell can use different immutable Solana fee profiles.
    buy_solana_fee_profile: solanaFeeProfile(form, "buy"),
    sell_solana_fee_profile: solanaFeeProfile(form, "sell"),
    root_seed: atomicDecimalField(form, "root_seed"),
  };
}

// Copy adds only its typed inputs; shared financial profiles keep one form implementation.
function pumpfunStrategyDraft(form) {
  const draft = pumpfunSnipingDraft(form);
  if (document.querySelector("#pumpfun-strategy").value !== "copy") return draft;
  if (copyContract === null) throw new Error("Copy Buy contract недоступен");
  // A copy snapshot must carry signer history; a Sniping schedule cannot be reused.
  delete draft.delivery_schedule_id;
  draft.contract_schema = copyContract.schema;
  draft.signing_wallets = textField(form, "signing_wallets").split(/\s+/).filter(Boolean);
  const names = ["take_profit_bps", "stop_loss_bps", "maximum_hold_seconds",
    "observation_delay_transactions", "buy_delay_transactions"];
  // API validates the complete policy and canonicalizes the bounded wallet set.
  for (const name of names) draft[name] = integerField(form, name);
  return draft;
}

// Changing strategy switches only the controls admitted by that discovered contract.
function configurePumpfunStrategy() {
  const copy = document.querySelector("#pumpfun-strategy").value === "copy";
  const fields = document.querySelector("#copy-buy-fields");
  fields.hidden = !copy;
  fields.disabled = !copy;
  // A materialized Sniping schedule is outside the copy v1 execution contract.
  const form = document.querySelector("#sniping-form");
  const schedule = form.elements.namedItem("delivery_schedule_id");
  schedule.disabled = copy;
  schedule.closest("label").hidden = copy;
  // Only the readable reference backend is admitted for copy v1.
  const backend = form.elements.namedItem("run_backend");
  const choices = copy ? ["reference-pumpfun-copy-buy-v1"]
    : ["reference-pumpfun-sniping-v1", "numpy-mmap-pumpfun-sniping-v1"];
  backend.replaceChildren(...choices.map((name) => new Option(name, name)));
  const contract = copy ? copyContract : snipingContract;
  // Do not enable a stale form when discovery is missing or its fixed policy changed.
  if (copy && (!contract || contract.fixed_semantics.maximum_sell_attempts !== "4"
      || contract.fixed_semantics.sell_retry_seconds !== "2"
      || contract.fixed_semantics.mint_entry_limit !== "1")) {
    throw new Error("Copy Buy contract несовместим");
  }
  // Mode selection is still constrained by the discovered closed execution contract.
  if (contract) configureSnipingExecutionModes(contract);
  snipingContractStatus.textContent = copy ? "Copy Buy v1" : "Sniping v3";
  // Explain behavioral rules without exposing internal scheduler or storage details.
  document.querySelector("#pumpfun-strategy-notice").textContent = copy
    ? "Копируем BUY по signing_wallet. Один вход в токен за прогон, даже после отказа покупки. TP/SL по цене без комиссий; максимум 4 продажи с повтором через 2 секунды после отказа."
    : "Sniping: cooldown 600 секунд, покупка через 500 транзакций, решение о продаже через 2 секунды после исполнения.";
}

// Strategy selection remains local until the normal resolve-and-submit action.
document.querySelector("#pumpfun-strategy").addEventListener("change", () => {
  try { configurePumpfunStrategy(); }
  catch (error) { showResult(document.querySelector("#sniping-result"), error.message, true); }
});

// Physical settings describe an attempt and never enter logical strategy identity.
function runPhysicalSettings(form) {
  const backend = valuesOf(form).get("run_backend");
  // Only implementations wired by bootstrap can be selected from static UI.
  const supportedBackends = new Set([
    "reference-python-v1",
    "numpy-mmap-first-swap-exact-v1",
    // Pump.fun has separate readable-oracle and admitted mmap implementations.
    "reference-pumpfun-sniping-v1",
    "numpy-mmap-pumpfun-sniping-v1",
    "reference-pumpfun-copy-buy-v1",
  ]);
  // A closed backend list prevents the browser from supplying an import path.
  if (!supportedBackends.has(backend)) throw new Error("run_backend: backend не поддерживается");
  const readerReadahead = integerField(form, "reader_readahead");
  // Readahead is restricted to the physical profiles tested by the engine.
  if (![1, 2, 4].includes(readerReadahead)) {
    throw new Error("reader_readahead: допустимы только 1, 2 или 4");
  }
  return {
    // Reader and buffer values are passed separately from the resolved semantic spec.
    schema: "backtest.run-physical-settings/v2",
    backend,
    reader_batch_rows: integerField(form, "reader_batch_rows"),
    // These values affect throughput only and remain attempt provenance.
    reader_readahead: readerReadahead,
    output_buffer_rows: integerField(form, "output_buffer_rows"),
    threads: integerField(form, "run_threads"),
  };
}

// Submit an already resolved generic job through the durable queue endpoint.
async function submitResolvedJob(jobType, payload) {
  // The body contains no unresolved aliases or browser-supplied executable input.
  return api("/api/v1/jobs", {
    method: "POST",
    // Fresh idempotency distinguishes an intentional UI submission from a retry click.
    headers: { "Content-Type": "application/json", "Idempotency-Key": randomDigest() },
    body: JSON.stringify({ job_type: jobType, payload }),
  });
}

// Submit one typed ML command with a fresh request-level idempotency key.
async function submitTypedMl(endpoint, payload) {
  // Static form bindings choose the typed endpoint; operators cannot override it.
  return api(endpoint, {
    method: "POST",
    // All typed ML commands use JSON plus request-level idempotency.
    headers: { "Content-Type": "application/json", "Idempotency-Key": randomDigest() },
    body: JSON.stringify(payload),
  });
}

async function submitTypedBacktest(payload) {
  // The dedicated endpoint validates physical settings against the resolved run.
  const job = await api("/api/v1/backtests", {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": randomDigest() },
    body: JSON.stringify(payload),
  });
  // Remember UI-submitted runs even if they finish before their first queue poll.
  watchedRunJobIds.add(job.job_id);
  return job;
}

function requireMlContract() {
  // No ML request is built before discovery pins the reference compiler contract.
  if (mlContract === null) throw new Error("Reference ML contract ещё не загружен");
  return mlContract;
}

async function refreshHealth() {
  // Health failures update only their live region and never block other startup reads.
  try {
    const data = await api("/api/v1/health");
    health.textContent = `${data.status} · ${data.profile}`;
    health.className = "status ok";
  } catch (error) {
    // Keep a degraded controller visible without hiding usable static forms.
    health.textContent = `API недоступен · ${error.message}`;
    health.className = "status error";
  }
}

async function refreshMlContract() {
  // Discovery owns the exact feature names exposed by the selection control.
  try {
    mlContract = await api("/api/v1/ml/reference-contract");
    const select = document.querySelector("#ml-feature-name");
    select.replaceChildren();
    // Each discovered name becomes text-only option content.
    for (const name of mlContract.supported_feature_names) {
      const option = document.createElement("option");
      option.value = name;
      // Discovery strings are rendered as text and cannot inject option markup.
      option.textContent = name;
      select.append(option);
    }
    // The visible status ties the form to its discovered compiler version.
    mlContractStatus.textContent = `exact · ${mlContract.compiler_version}`;
    mlContractStatus.className = "status ok";
  } catch (error) {
    // A missing contract disables semantic confidence without inventing defaults.
    mlContractStatus.textContent = `ML contract недоступен · ${error.message}`;
    mlContractStatus.className = "status error";
  }
}

function updateSnipingExecutionWarning() {
  // Keep the warning persistent whenever the explicitly synthetic mode is selected.
  snipingExecutionWarning.hidden =
    snipingExecutionMode.value !== "EXOGENOUS_VIRTUAL_SETTLEMENT";
}

function configureSnipingExecutionModes(contract) {
  // Discovery, rather than static markup, owns the selectable enum values.
  const field = contract.editable_fields.find((item) => item.name === "execution_mode");
  if (!field || field.kind !== "CLOSED_ENUM" || field.required !== true) {
    throw new Error("execution_mode discovery field несовместим");
  }
  const expected = ["EXOGENOUS_REPLAY", "EXOGENOUS_VIRTUAL_SETTLEMENT"];
  // Future or reordered values require a reviewed UI contract update.
  if (JSON.stringify(field.enum_values) !== JSON.stringify(expected)) {
    throw new Error("execution_mode enum несовместим");
  }
  const previous = snipingExecutionMode.value;
  snipingExecutionMode.replaceChildren();
  // Preserve a user's valid choice across discovery refreshes.
  for (const value of field.enum_values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    // Append only values that passed the closed discovery guard above.
    snipingExecutionMode.append(option);
  }
  // Restore only a still-supported choice; otherwise use the contract's first value.
  snipingExecutionMode.value = field.enum_values.includes(previous)
    ? previous
    : field.enum_values[0];
  snipingExecutionMode.disabled = false;
  // Apply warning visibility after the restored/default choice is finalized.
  updateSnipingExecutionWarning();
}

async function refreshSnipingContract() {
  // Select the one supported Sniping schema from bounded contract discovery.
  try {
    const response = await api("/api/v1/run-contracts");
    copyContract = response.items.find(
      (item) => item.schema === "pumpfun-copy-buy-run-draft/v1",
    ) ?? null;
    // Exact schema match prevents a legacy draft from reaching the v3 form.
    const contract = response.items.find(
      (item) => item.schema === "pumpfun-sniping-run-draft/v3",
    );
    if (!contract) throw new Error("pumpfun-sniping-run-draft/v3 отсутствует");
    // Fixed timing and asset semantics must match the UI's read-only explanation.
    const expected = {
      buy_delay_transactions: "500",
      cooldown_seconds: "600",
      // SOL-only sell-all semantics are not editable browser policy.
      quote_asset: "SOL",
      sell_all: "true",
      sell_decision_delay_seconds: "2",
    };
    // Any drift fails the form closed instead of silently changing strategy behavior.
    for (const [name, value] of Object.entries(expected)) {
      if (contract.fixed_semantics[name] !== value) {
        throw new Error(`несовместимая fixed semantics: ${name}`);
      }
    }
    // Enable the mode control only after the complete contract passes validation.
    configureSnipingExecutionModes(contract);
    snipingContract = contract;
    snipingContractStatus.textContent = "v3 · selectable exact settlement";
    snipingContractStatus.className = "status ok";
    configurePumpfunStrategy();
  } catch (error) {
    // Failed discovery removes stale contract state and disables execution submission.
    snipingContract = null;
    snipingExecutionMode.disabled = true;
    // Hide a mode-specific warning once no validated mode can be selected.
    snipingExecutionWarning.hidden = true;
    snipingContractStatus.textContent = `Contract недоступен · ${error.message}`;
    // Error tone makes the fail-closed form state visible to the operator.
    snipingContractStatus.className = "status error";
  }
}

async function refreshRunPhysicalSettings() {
  // Host defaults populate attempt-only controls without entering the strategy draft.
  const settings = await api("/api/v1/run-physical-settings");
  const form = document.querySelector("#backtest-form");
  // Populate every physical control from one coherent controller response.
  form.elements.namedItem("run_backend").value = settings.backend;
  form.elements.namedItem("reader_batch_rows").value = String(settings.reader_batch_rows);
  form.elements.namedItem("reader_readahead").value = String(settings.reader_readahead);
  form.elements.namedItem("output_buffer_rows").value = String(settings.output_buffer_rows);
  // Sequential execution remains visible even when the host has many cores.
  form.elements.namedItem("run_threads").value = String(settings.threads);
}

// Cancel keeps the button disabled unless the server rejects the state transition.
async function cancelJob(jobId, button) {
  button.disabled = true;
  try {
    // The encoded job ID is the only path input accepted by this mutation.
    await api(`/api/v1/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
    await refreshJobs();
  } catch (error) {
    // A failed cancellation remains retryable from the same visible row.
    window.alert(`Не удалось отменить job: ${error.message}`);
    button.disabled = false;
  }
}

// Retry delegates attempt isolation to the durable job use case.
async function retryJob(jobId, button) {
  button.disabled = true;
  try {
    // Server-side retry creates the new isolated attempt under CAS protection.
    await api(`/api/v1/jobs/${encodeURIComponent(jobId)}/retry`, { method: "POST" });
    await refreshJobs();
  } catch (error) {
    // Preserve the action when retry fails before a replacement attempt is accepted.
    window.alert(`Не удалось повторить job: ${error.message}`);
    button.disabled = false;
  }
}

// Commit one event page only while its selection, generation and cursor still match.
async function requestJobEventsPage(jobId, generation, cursor, controller, result) {
  try {
    // The API page is bounded independently from the rolling browser history.
    const page = await api(
      `/api/v1/jobs/${encodeURIComponent(jobId)}/events` +
        `?after_event_id=${cursor}&limit=200`,
      { signal: controller.signal },
    );
    // Superseded reads cannot append into a newly selected job or cursor window.
    const ownsSelection = activeEventsJobId === jobId && activeEventsGeneration === generation;
    const ownsCursor = activeEventsCursor === cursor && activeEventsRequestController === controller;
    if (!ownsSelection || !ownsCursor) return;
    const additions = page.items.filter((item) => item.event_id > cursor);
    if (additions.length > 0) {
      // Advance from the final returned ID, then cap retained events at 200.
      activeEventsCursor = additions.at(-1).event_id;
      activeEventsHistory = [...activeEventsHistory, ...additions].slice(-200);
    }
    showResult(result, { items: activeEventsHistory });
  } catch (error) {
    // An intentional supersession is silent; only the current request owns errors.
    if (controller.signal.aborted || activeEventsGeneration !== generation) return;
    showResult(result, error.message, true);
  } finally {
    // A stale request must not clear ownership installed by a newer selection.
    if (activeEventsRequestController === controller) {
      activeEventsRequestController = null;
      activeEventsRequestPromise = null;
      // The next refresh may now advance from the cursor committed above.
    }
  }
}

// Event history follows one selected job and retains at most the latest 200 entries.
async function showJobEvents(jobId) {
  const result = document.querySelector("#job-events-result");
  // Simultaneous poll/manual reads of one cursor share the same network operation.
  if (activeEventsJobId === jobId && activeEventsRequestPromise !== null) {
    return activeEventsRequestPromise;
  }
  if (activeEventsJobId !== jobId) {
    // Abort the prior selection before resetting its bounded cursor and visible history.
    activeEventsRequestController?.abort();
    activeEventsJobId = jobId;
    activeEventsCursor = 0;
    activeEventsHistory = [];
    // Remove the prior job's visible history at the same selection boundary.
    showResult(result, { items: activeEventsHistory });
  }
  // Capture all commit guards before dispatching this selected-job request.
  const generation = ++activeEventsGeneration;
  const cursor = activeEventsCursor;
  const controller = new AbortController();
  activeEventsRequestController = controller;
  // Store the shared promise before any caller can request this cursor again.
  activeEventsRequestPromise = requestJobEventsPage(jobId, generation, cursor, controller, result);
  return activeEventsRequestPromise;
}

// Empty and error states occupy the full table width without injecting markup.
function renderTableMessage(body, message, columns) {
  body.replaceChildren();
  const row = document.createElement("tr");
  // A single spanning cell preserves valid table structure for assistive technology.
  const cell = document.createElement("td");
  cell.colSpan = columns;
  cell.className = "empty";
  // Text-only rendering keeps server error messages inert.
  cell.textContent = message;
  row.append(cell);
  body.append(row);
}

// Render operational nanoseconds without converting atomic source values prematurely.
function formatNanosecondTimestamp(value) {
  if (typeof value !== "string" || !/^\d+$/.test(value)) return "—";
  const milliseconds = BigInt(value) / 1000000n;
  return new Date(Number(milliseconds)).toLocaleString("ru-RU");
}

// Run timestamps are typed ISO instants supplied by the API projection.
function formatIsoTimestamp(value) {
  if (typeof value !== "string") return "—";
  const milliseconds = Date.parse(value);
  return Number.isFinite(milliseconds) ? new Date(milliseconds).toLocaleString("ru-RU") : "—";
}

// Return a stable ordering sign without locale-dependent mutation of source rows.
function compareText(left, right) {
  return String(left ?? "").localeCompare(String(right ?? ""), "ru");
}

// Unsigned decimal comparison avoids precision loss for nanoseconds and boundaries.
function compareUnsignedDecimal(left, right) {
  const leftValue = BigInt(left);
  const rightValue = BigInt(right);
  // Atomic integers must retain exact ordering beyond Number.MAX_SAFE_INTEGER.
  if (leftValue < rightValue) return -1;
  if (leftValue > rightValue) return 1;
  // Equal atomic values defer to the caller's stable identity tie-breaker.
  return 0;
}

// BigInt also preserves exact ordering for canonical signed PnL strings.
function compareAtomicDecimal(left, right) {
  const leftValue = BigInt(left);
  const rightValue = BigInt(right);
  // Comparators return only an ordering sign and never subtract unbounded integers.
  if (leftValue < rightValue) return -1;
  if (leftValue > rightValue) return 1;
  return 0;
}

// Keep unavailable analytical values after measured values in either direction.
function compareNullableAtomic(left, right, direction) {
  if (left === null && right === null) return 0;
  // sortBoundedPage applies direction afterward, so invert null order for DESC here.
  if (left === null) return direction === "asc" ? 1 : -1;
  if (right === null) return direction === "asc" ? -1 : 1;
  return compareAtomicDecimal(left, right);
}

// Parse an offset-bearing ISO instant without discarding its fractional-second precision.
function isoTimestampNanoseconds(value) {
  if (typeof value !== "string") return null;
  const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})$/.exec(value);
  if (match === null) return null;
  // Date parses only the whole-second timezone component; BigInt preserves the fraction.
  const milliseconds = Date.parse(`${match[1]}${match[3]}`);
  if (!Number.isFinite(milliseconds)) return null;
  const fraction = (match[2] || "").padEnd(9, "0");
  return BigInt(milliseconds) * 1000000n + BigInt(fraction || "0");
}

// ISO timestamps are compared exactly only for alternate page-local presentation order.
function compareIsoTimestamp(left, right) {
  const leftValue = isoTimestampNanoseconds(left);
  const rightValue = isoTimestampNanoseconds(right);
  // Invalid values tie so the exact identifier provides deterministic fallback order.
  if (leftValue === null || rightValue === null) return 0;
  if (leftValue < rightValue) return -1;
  if (leftValue > rightValue) return 1;
  return 0;
}

// Apply a closed comparator to a defensive copy of one already bounded page.
function sortBoundedPage(items, key, direction, comparators, identity) {
  const comparator = comparators[key];
  if (!comparator) throw new Error(`Неподдерживаемая сортировка: ${key}`);
  const sign = direction === "asc" ? 1 : -1;
  // Copy the page because transport order remains the newest-first pagination authority.
  return [...items].sort((left, right) => {
    const primary = comparator(left, right);
    return primary === 0 ? compareText(identity(left), identity(right)) : primary * sign;
  });
}

// Job sorting never changes the server's global submitted-time page boundaries.
function sortedJobs() {
  const comparators = {
    submitted_at: (left, right) => compareUnsignedDecimal(left.submitted_at_ns, right.submitted_at_ns),
    updated_at: (left, right) => compareUnsignedDecimal(left.updated_at_ns, right.updated_at_ns),
    // Text fields use locale ordering only inside the already fetched page.
    job_type: (left, right) => compareText(left.job_type, right.job_type),
    state: (left, right) => compareText(left.state, right.state),
    job_id: (left, right) => compareText(left.job_id, right.job_id),
  };
  // The select is a closed, local allowlist; no property path comes from the server.
  const key = document.querySelector("#jobs-sort").value;
  // Default order is already globally canonical, including submitted-time job-ID ties.
  if (key === "submitted_at" && jobsSortDirection === "desc") return [...jobsPageItems];
  return sortBoundedPage(jobsPageItems, key, jobsSortDirection, comparators, (job) => job.job_id);
}

// Render a fingerprinted job page so unchanged polling does not churn controls or focus.
function renderJobs() {
  const jobs = sortedJobs();
  const sortKey = document.querySelector("#jobs-sort").value;
  const fingerprint = JSON.stringify([jobsPageIndex, sortKey, jobsSortDirection, jobs]);
  // Preserve buttons and focus when an adaptive poll returns byte-equivalent rows.
  if (fingerprint === jobsRenderFingerprint) return;
  jobsRenderFingerprint = fingerprint;
  jobsBody.replaceChildren();
  if (jobs.length === 0) {
    // An empty bounded page gets an explicit table state instead of stale rows.
    renderTableMessage(jobsBody, "Очередь пока пуста", 7);
    return;
  }
  // Build each row from the inert template and attach actions to its exact job ID.
  for (const job of jobs) {
    const row = rowTemplate.content.firstElementChild.cloneNode(true);
    // Identifiers and server-owned enums are rendered only through textContent.
    row.querySelector(".job-id").textContent = job.job_id;
    row.querySelector(".job-type").textContent = job.job_type;
    const state = row.querySelector(".job-state");
    state.textContent = job.state;
    state.classList.add(job.state.toLowerCase());
    // Submission time is operational display data and never enters run identity.
    const submittedAt = row.querySelector(".job-submitted-at");
    submittedAt.textContent = formatNanosecondTimestamp(job.submitted_at_ns);
    submittedAt.title = job.submitted_at_ns;
    const updatedAt = row.querySelector(".job-updated-at");
    // Updated time makes the corresponding page-local sort directly inspectable.
    updatedAt.textContent = formatNanosecondTimestamp(job.updated_at_ns);
    updatedAt.title = job.updated_at_ns;
    // State version helps diagnose controller transitions without exposing job payloads.
    row.querySelector(".job-version").textContent = job.state_version;
    const cancel = row.querySelector(".cancel-job");
    const terminal = ["SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED"].includes(job.state);
    // Terminal state controls both cancel visibility and later retry eligibility.
    cancel.hidden = terminal;
    cancel.addEventListener("click", () => cancelJob(job.job_id, cancel));

    // Retry is offered only for recoverable terminal states defined by the API workflow.
    const retry = row.querySelector(".retry-job");
    retry.hidden = !["FAILED", "INTERRUPTED"].includes(job.state);
    retry.addEventListener("click", () => retryJob(job.job_id, retry));
    row.querySelector(".show-events").addEventListener("click", () => showJobEvents(job.job_id));
    // Append only after all row text and event handlers are complete.
    jobsBody.append(row);
  }
}

// Reflect lookahead-derived navigation without requesting an unbounded total count.
function updateJobsPagination() {
  document.querySelector("#jobs-previous-page").disabled = jobsPageIndex === 0;
  document.querySelector("#jobs-next-page").disabled = !jobsHasNext;
  // Live keyset pages have no stable absolute row number after newer inserts.
  const rowCount = jobsPageItems.length;
  document.querySelector("#jobs-page-label").textContent =
    `Страница ${jobsPageIndex + 1} · строк: ${rowCount} · глобально: сначала новые`;
}

// Detect newly successful run-producing jobs while bounding polling observation state.
function rememberJobStates(jobs) {
  let completedBacktest = false;
  for (const job of jobs) {
    const previous = previousJobStates.get(job.job_id);
    // Separate known transitions, explicit watches, and externally observed completions.
    const observedTransition = previous !== undefined && previous !== "SUCCEEDED";
    const watchedCompletion = watchedRunJobIds.has(job.job_id);
    // Historical pages must not masquerade as newly completed external work.
    const newlyObserved = jobsPageIndex === 0 && jobsInitialized && previous === undefined;
    // Refresh once for transitions and externally submitted jobs first seen as complete.
    if (observedTransition || watchedCompletion || newlyObserved) {
      completedBacktest ||=
        RUN_PRODUCING_JOB_TYPES.has(job.job_type) && job.state === "SUCCEEDED";
    }
    // Terminal jobs no longer need a dedicated completion watch entry.
    if (["SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED"].includes(job.state)) {
      watchedRunJobIds.delete(job.job_id);
    }
    // Delete-before-set preserves insertion order for the bounded oldest-entry eviction.
    previousJobStates.delete(job.job_id);
    previousJobStates.set(job.job_id, job.state);
  }
  // Bound operational observation state independently from queue history size.
  while (previousJobStates.size > 200) {
    previousJobStates.delete(previousJobStates.keys().next().value);
  }
  jobsInitialized = true;
  // The caller refreshes immutable runs only when a relevant completion was observed.
  return completedBacktest;
}

// Validate one closed list response before its rows or continuation enter UI state.
function validateListPage(page, limit, label) {
  const keys = page && typeof page === "object" ? Object.keys(page).sort() : [];
  if (keys.join(",") !== "items,next_cursor" || !Array.isArray(page.items)) {
    throw new Error(`API вернул некорректную страницу ${label}`);
  }
  if (page.items.length > limit) {
    throw new Error(`API превысил лимит страницы ${label}`);
  }
  // The browser treats the token as opaque and only enforces its transport envelope.
  if (page.next_cursor !== null && !/^[A-Za-z0-9_-]{1,512}$/.test(page.next_cursor)) {
    throw new Error(`API вернул некорректный cursor ${label}`);
  }
  return page;
}

// Build a bounded keyset request without interpreting the server-owned cursor.
function listPagePath(path, limit, cursor) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (cursor !== null) params.set("cursor", cursor);
  return `${path}?${params.toString()}`;
}

// Fetch one globally newest-first job page and its stable continuation.
async function refreshJobs(navigation = null) {
  if (jobsRequestInFlight) return;
  jobsRequestInFlight = true;
  // Navigation stays provisional until the requested page has validated successfully.
  const sourcePageIndex = jobsPageIndex;
  const sourceCursor = jobsPageCursors[sourcePageIndex];
  const requestedPageIndex = navigation?.pageIndex ?? sourcePageIndex;
  const requestedCursor = navigation?.cursor ?? sourceCursor;
  // Mark the table busy without replacing its last useful page during the read.
  jobsBody.closest("table").setAttribute("aria-busy", "true");
  try {
    if (requestedCursor === undefined) throw new Error("Неизвестная страница jobs");
    const data = validateListPage(
      await api(listPagePath("/api/v1/jobs", JOBS_PAGE_SIZE, requestedCursor)),
      JOBS_PAGE_SIZE,
      "jobs",
    );
    // A page-one reset or another owner invalidates this provisional navigation.
    if (jobsPageIndex !== sourcePageIndex || jobsPageCursors[sourcePageIndex] !== sourceCursor) {
      return false;
    }
    if (navigation !== null) {
      // Commit the new page key only after its bounded response has passed validation.
      jobsPageIndex = requestedPageIndex;
      jobsPageCursors = jobsPageCursors.slice(0, requestedPageIndex);
      jobsPageCursors[requestedPageIndex] = requestedCursor;
    }
    jobsHasNext = data.next_cursor !== null;
    jobsNextCursor = data.next_cursor;
    jobsPageItems = data.items;
    // A refreshed page invalidates only forward branches, never prior cursor keys.
    jobsPageCursors = jobsPageCursors.slice(0, requestedPageIndex + 1);
    // Commit list and navigation state from the same bounded response.
    renderJobs();
    updateJobsPagination();
    if (rememberJobStates(jobsPageItems)) void refreshRuns({ resetPage: true });
    if (activeEventsJobId !== null) await showJobEvents(activeEventsJobId);
    return true;
  } catch (error) {
    // Failed navigation leaves the prior page coordinates authoritative.
    jobsRenderFingerprint = null;
    renderTableMessage(jobsBody, error.message, 7);
    updateJobsPagination();
    return false;
  } finally {
    // Release request ownership before deciding whether a coalesced refresh must run.
    jobsRequestInFlight = false;
    jobsBody.closest("table").setAttribute("aria-busy", "false");
    // Coalesce a submit-triggered page-one refresh that arrived during this request.
    if (jobsLatestRefreshPending) {
      jobsLatestRefreshPending = false;
      void refreshLatestJobs();
    } else if (jobPollTimer !== null) {
      // A manual refresh can change active/idle cadence before the old timer fires.
      scheduleJobPolling();
    }
  }
}

// Redirect observation to page one after a newly submitted durable job.
function refreshLatestJobs() {
  jobsPageIndex = 0;
  jobsPageCursors = [null];
  jobsNextCursor = null;
  jobsRenderFingerprint = null;
  // Defer exactly one page-one refresh when the current page request still owns state.
  if (jobsRequestInFlight) {
    jobsLatestRefreshPending = true;
    return Promise.resolve();
  }
  // Newly submitted work is always visible on the globally newest page.
  return refreshJobs();
}

// Refresh host telemetry independently from jobs, runs, and immutable result reads.
async function refreshResources() {
  try {
    showResult(resourcesResult, await api("/api/v1/system/resources"));
  } catch (error) {
    // Telemetry failure stays local and cannot stop the jobs or runs workflows.
    showResult(resourcesResult, error.message, true);
  }
}

// Build artifact actions without accepting markup or executable paths from data.
function artifactActionButton(label, artifactId, action) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary";
  button.textContent = label;
  // The exact artifact ID is closed over rather than read from mutable row markup.
  button.addEventListener("click", () => showArtifact(artifactId, action));
  return button;
}

// Alternate run sorts reorder only a page globally selected by completion time.
function sortedRuns() {
  const comparators = {
    completed_at: (left, right) => compareIsoTimestamp(left.completed_at, right.completed_at),
    started_at: (left, right) => compareIsoTimestamp(left.started_at, right.started_at),
    // Hash and identity sorting never causes a broader artifact query.
    logical_run_id: (left, right) => compareText(left.logical_run_id, right.logical_run_id),
    result_hash: (left, right) => compareText(left.canonical_result_hash, right.canonical_result_hash),
  };
  // Keep the allowlisted projection separate from costly global artifact traversal.
  const key = document.querySelector("#runs-sort").value;
  // Preserve exact server ordering instead of narrowing completion fractions in-browser.
  if (key === "completed_at" && runsSortDirection === "desc") return [...runsPageItems];
  return sortBoundedPage(runsPageItems, key, runsSortDirection, comparators, (run) => run.run_artifact_id);
}

// Render one verified run page while preserving selection for local re-sorts.
function renderRuns() {
  const runs = sortedRuns();
  const sortKey = document.querySelector("#runs-sort").value;
  const fingerprint = JSON.stringify([runsPageIndex, sortKey, runsSortDirection, runs]);
  // Do not reset checked comparisons when a manual refresh yields unchanged rows.
  if (fingerprint === runsRenderFingerprint) return;
  runsRenderFingerprint = fingerprint;
  lastRuns = runs;
  runsBody.replaceChildren();
  if (runs.length === 0) {
    // An empty bounded page gets an explicit table state instead of stale rows.
    renderTableMessage(runsBody, "Committed runs пока нет", 7);
    return;
  }
  // Each comparison row remains bound to one immutable Run artifact identity.
  for (const run of runs) {
    const row = document.createElement("tr");
    // Comparison selection is identified by the exact immutable Run artifact ID.
    const selection = document.createElement("input");
    selection.type = "checkbox";
    selection.className = "run-selection";
    selection.value = run.run_artifact_id;
    selection.checked = selectedRunIds.has(run.run_artifact_id);
    // An explicit accessible name prevents a visually empty checkbox header from hiding intent.
    selection.setAttribute("aria-label", `Выбрать run ${run.run_artifact_id}`);
    // Keep page-local comparison selection stable while sorting the same rows.
    selection.addEventListener("change", () => {
      if (selection.checked) selectedRunIds.add(selection.value);
      else selectedRunIds.delete(selection.value);
    });
    // Checkbox placement remains separate from the completion-time data cell.
    const selectionCell = document.createElement("td");
    selectionCell.append(selection);
    const startedAt = document.createElement("td");
    // Started time is shown because it is an explicit page-local sort option.
    startedAt.textContent = formatIsoTimestamp(run.started_at);
    startedAt.title = run.started_at;
    // Completion is the authoritative global page-order timestamp.
    const completedAt = document.createElement("td");
    completedAt.textContent = formatIsoTimestamp(run.completed_at);
    completedAt.title = run.completed_at;

    // Long identities remain available in full through cell text/title and safe DOM APIs.
    const logical = document.createElement("td");
    logical.className = "mono";
    logical.textContent = run.logical_run_id;
    const resultHash = document.createElement("td");
    // Canonical result and audit hashes stay separate for comparison and diagnosis.
    resultHash.className = "mono compact-hash";
    resultHash.textContent = run.canonical_result_hash;
    const auditHash = document.createElement("td");
    auditHash.className = "mono compact-hash";
    auditHash.textContent = run.audit_hash;

    // Metadata and dashboard actions stay bound to this exact verified artifact.
    const actions = document.createElement("td");
    actions.className = "row-actions";
    // A typed physical backend decides whether the Sniping result contract exists.
    if (PUMPFUN_SNIPING_BACKENDS.has(run.physical_settings.backend)) {
      const copy = run.physical_settings.backend === "reference-pumpfun-copy-buy-v1";
      actions.append(copy ? copyResultActionButton(run.run_artifact_id)
        : snipingResultActionButton(run.run_artifact_id));
    }
    // Manifest and lineage remain valid for every exact committed Run artifact.
    actions.append(
      artifactActionButton("Manifest", run.run_artifact_id, "manifest"),
      artifactActionButton("Lineage", run.run_artifact_id, "lineage"),
    );
    // Commit the completed row in one append to reduce intermediate DOM work.
    row.append(selectionCell, startedAt, completedAt, logical, resultHash, auditHash, actions);
    runsBody.append(row);
  }
}

// Display global completion ordering and the bounded cursor journey together.
function updateRunsPagination() {
  document.querySelector("#runs-previous-page").disabled = runsPageIndex === 0;
  document.querySelector("#runs-next-page").disabled = !runsHasNext;
  // Live keyset continuations deliberately make no unstable global ordinal claim.
  const rowCount = runsPageItems.length;
  document.querySelector("#runs-page-label").textContent =
    `Страница ${runsPageIndex + 1} · строк: ${rowCount} · глобально: сначала новые по завершению`;
}

// Fetch a small manifest-verified run page without polling immutable results repeatedly.
async function refreshRuns({ resetPage = false, navigation = null } = {}) {
  if (runsRequestInFlight) {
    // Only a reset request needs to survive coalescing with the active read.
    runsRefreshPending ||= resetPage;
    return;
  }
  // Resetting drops page-local comparison state before reading the newest page.
  if (resetPage) {
    runsPageIndex = 0;
    runsPageCursors = [null];
    runsNextCursor = null;
    selectedRunIds = new Set();
    runsRenderFingerprint = null;
  }
  // Navigation coordinates remain provisional until the selected manifests verify.
  const sourcePageIndex = runsPageIndex;
  const sourceCursor = runsPageCursors[sourcePageIndex];
  const requestedPageIndex = navigation?.pageIndex ?? sourcePageIndex;
  const requestedCursor = navigation?.cursor ?? sourceCursor;
  // Busy state spans the full verified read and render transaction.
  runsRequestInFlight = true;
  runsBody.closest("table").setAttribute("aria-busy", "true");
  try {
    if (requestedCursor === undefined) throw new Error("Неизвестная страница runs");
    const data = validateListPage(
      await api(listPagePath("/api/v1/runs", RUNS_PAGE_SIZE, requestedCursor)),
      RUNS_PAGE_SIZE,
      "runs",
    );
    // A pending reset or another owner invalidates this provisional navigation.
    if (runsPageIndex !== sourcePageIndex || runsPageCursors[sourcePageIndex] !== sourceCursor) {
      return false;
    }
    if (runsRefreshPending) return false;
    if (navigation !== null) {
      // Page index and cursor history change atomically with the verified rows.
      runsPageIndex = requestedPageIndex;
      runsPageCursors = runsPageCursors.slice(0, requestedPageIndex);
      runsPageCursors[requestedPageIndex] = requestedCursor;
      selectedRunIds = new Set();
    }
    runsHasNext = data.next_cursor !== null;
    runsNextCursor = data.next_cursor;
    runsPageItems = data.items;
    // Only tiny backward cursor keys survive; prior row pages are never cached.
    runsPageCursors = runsPageCursors.slice(0, requestedPageIndex + 1);
    renderRuns();
    // Navigation derives from the same response as the visible rows.
    updateRunsPagination();
    return true;
  } catch (error) {
    runsRenderFingerprint = null;
    renderTableMessage(runsBody, error.message, 7);
    updateRunsPagination();
    // The finally block still releases request and accessibility state after errors.
    return false;
  } finally {
    // Clear table busy state before starting any pending page-one refresh.
    runsRequestInFlight = false;
    runsBody.closest("table").setAttribute("aria-busy", "false");
    // A completion refresh observed in flight restarts once at globally newest page.
    if (runsRefreshPending) {
      runsRefreshPending = false;
      void refreshRuns({ resetPage: true });
    }
    // Immutable run results need no recurring timer once pending work is drained.
  }
}

// Render the compact viewer's bounded scalar summary without loading result tables.
function renderSnipingSummary(summary) {
  if (summary.contract_schema === "pumpfun-copy-run-summary/v1") {
    renderCopySummary(summary.summary);
    return;
  }
  const values = [
    // Contract and execution context explain how the displayed result was produced.
    ["Summary schema", summary.summary_schema_id],
    ["Execution mode", summary.execution_mode],
    ["Settlement policy", summary.settlement_policy_id],
    ["Targets", summary.target_count],
    ["Closed", summary.closed_position_count],
    // Position and valuation counts distinguish realized from incomplete economics.
    ["Open", summary.open_position_count],
    ["Valuation", summary.valuation_status],
    ["Unvalued open", summary.unvalued_open_position_count],
    // Realized, valued subtotal, and full economic PnL are intentionally separate.
    ["Realized PnL", summary.realized_cash_pnl_atomic],
    ["Valued economic subtotal", summary.valued_economic_pnl_subtotal_atomic],
    ["Economic PnL", atomicText(summary.economic_pnl_atomic)],
    ["Cashback receivable", summary.cashback_receivable_atomic],
    // Venue and network fee components remain separately auditable.
    ["Protocol fees paid", summary.protocol_fee_paid_atomic],
    ["Creator fees paid", summary.creator_fee_paid_atomic],
    ["Network base fees paid", summary.network_base_fee_paid_atomic],
    // Priority fees precede account deposit cashflows in the compact summary.
    ["Network priority fees paid", summary.network_priority_fee_paid_atomic],
    ["Account deposits paid", summary.account_deposit_paid_atomic],
    ["Account deposits refunded", summary.account_deposit_refunded_atomic],
    // Locked deposits and slippage outcomes explain unrealized or failed exits.
    ["Account deposits locked", summary.account_deposit_locked_atomic],
    ["Favorable slippage", summary.favorable_slippage_count],
    ["Adverse slippage", summary.adverse_slippage_count],
    // Buy and sell limit failures remain side-specific execution outcomes.
    ["Buy slippage failures", summary.buy_slippage_failure_count],
    ["Sell slippage failures", summary.sell_slippage_failure_count],
    ["Filled sells", atomicText(summary.filled_sell_count)],
    // Settlement funding exposes synthetic liquidity separately from venue reserves.
    ["Venue-funded sells", atomicText(summary.venue_funded_sell_atomic)],
    ["Synthetic-funded sells", atomicText(summary.synthetic_funded_sell_atomic)],
    ["Result hash", summary.canonical_result_hash],
  ];
  renderSummaryCards(values);
}

// Shared cards preserve exact decimal strings and use only text nodes.
function renderSummaryCards(values) {
  snipingSummaryCards.replaceChildren();
  // Cards use text-only DOM nodes and retain exact values in their title.
  for (const [label, value] of values) {
    const card = document.createElement("dl");
    card.className = "summary-card";
    const term = document.createElement("dt");
    term.textContent = label;
    // The description may visually truncate but remains available without coercion.
    const description = document.createElement("dd");
    description.title = String(value);
    description.textContent = String(value);
    // Append the complete definition pair before publishing the card.
    card.append(term, description);
    snipingSummaryCards.append(card);
  }
}

// Copy summaries expose retry outcomes and qualified economics without invented launch fields.
function renderCopySummary(summary) {
  const totals = summary.totals;
  const values = [["Strategy", "Pump.fun Copy Buy"], ["Execution mode", summary.execution_mode]];
  const counts = {
    position_count: "Entry signals", filled_buy_count: "Filled buys", failed_buy_count: "Failed buys",
    rejected_buy_count: "Rejected buys", closed_position_count: "Closed positions",
    // Exhaustion is an open position, even after all four sale attempts have been consumed.
    exhausted_position_count: "Open: four attempts exhausted", sell_attempt_count: "Sell attempts",
    failed_sell_count: "Failed sell landings", rejected_sell_count: "Rejected sells",
    unvalued_open_position_count: "Open positions without valuation", valuation_status: "Valuation",
  };
  // Keep unvalued inventory visible alongside completed and failed entry counts.
  for (const [name, label] of Object.entries(counts)) values.push([label, totals[name]]);
  // Monetary cards name SOL explicitly and preserve every lamport using integer formatting.
  const amounts = {
    quote_cashflow_atomic: "Wallet cash change", realized_cash_pnl_atomic: "Realized cash PnL",
    economic_pnl_atomic: "Full economic PnL", valued_economic_pnl_subtotal_atomic: "Valued subtotal",
    cashback_receivable_atomic: "Cashback receivable", account_deposit_locked_atomic: "Locked deposits",
    // Paid fees and released account deposits remain separate from price-trigger thresholds.
    protocol_fee_paid_atomic: "Protocol fees", creator_fee_paid_atomic: "Creator fees",
    network_base_fee_paid_atomic: "Network base fees", network_priority_fee_paid_atomic: "Priority fees",
    account_deposit_paid_atomic: "Deposits paid", account_deposit_refunded_atomic: "Deposits refunded",
    venue_funded_sell_atomic: "Settled venue funding", synthetic_funded_sell_atomic: "Settled synthetic funding",
  };
  // Financial values remain lossless even above JavaScript safe-integer limits.
  for (const [name, label] of Object.entries(amounts)) values.push([`${label}, SOL`, copySol(totals[name])]);
  // A virtual result must retain the same prominent synthetic-funding qualification.
  if (summary.execution_mode === "EXOGENOUS_VIRTUAL_SETTLEMENT") {
    values.unshift(["Модель", "Синтетическая ликвидность; не on-chain исполнение"]);
  }
  // The hash identifies verified normalized output rather than the physical attempt.
  values.push(["Result hash", summary.comparison.canonical_result_hash]);
  renderSummaryCards(values);
}

// Display exact native atomic amounts without floating-point rounding or a false zero mark.
function copySol(value) {
  if (value === null || value === undefined) return "Недоступно";
  const amount = BigInt(value), magnitude = amount < 0n ? -amount : amount;
  const digits = magnitude.toString().padStart(10, "0");
  return `${amount < 0n ? "−" : ""}${digits.slice(0, -9)}.${digits.slice(-9)}`;
}

// Keep the bounded copy page in canonical source order, with every retry visible.
function renderCopyPositions(items) {
  snipingRoundtripsBody.replaceChildren();
  for (const envelope of items) {
    const item = envelope.record;
    const row = document.createElement("tr");
    const buy = item.attempts[0];
    // Execution status qualifies quote evidence and distinguishes free rejects from landings.
    const attemptLines = (attempt) => [
      `#${attempt.attempt} ${attempt.status} ${attempt.failure_code ?? ""}`,
      `quote=${atomicText(attempt.landing_quote?.amount_out_atomic)}`,
      `block=${attempt.decision_position.block_ordinal} tx=${attempt.decision_position.transaction_index}`,
    ];
    // Entry is ordinal zero; the remaining bounded records are the four possible exits.
    const sells = item.attempts.slice(1);
    // Each rendered column retains the same financial meaning as the shared result table.
    const columns = [
      [`block=${item.signal_position.block_ordinal} tx=${item.signal_position.transaction_index}`],
      [item.asset_id, item.signing_wallet], [item.status, item.exit_reason ?? ""],
      attemptLines(buy), sells.flatMap(attemptLines),
      // Potential quote shortfalls are labelled separately from actual settled summary funding.
      sells.map((a) => `#${a.attempt} potential shortfall=${atomicText(a.landing_quote?.liquidity?.synthetic_shortfall_atomic)}`),
      item.attempts.map((a) => `#${a.attempt} paid=${atomicSum([a.protocol_fee_paid_atomic, a.creator_fee_paid_atomic, a.network_base_fee_paid_atomic, a.network_priority_fee_paid_atomic])}`),
      item.account_components.map((a) => `paid=${a.paid_atomic} refund=${a.refunded_atomic} locked=${a.locked_delta_atomic}`),
      // Open cashflow remains visible even when realized round-trip PnL is absent.
      [item.cashback_receivable_atomic], [`cashflow=${item.quote_cashflow_atomic}`, `realized=${atomicText(item.realized_cash_pnl_atomic)}`],
      [atomicText(item.economic_pnl_atomic)], [item.mtm_status, atomicText(item.mtm_liquidation_value_atomic)],
    ];
    // Text-only cells prevent artifact content from becoming executable browser markup.
    for (const lines of columns) row.append(snipingDetailCell(lines));
    snipingRoundtripsBody.append(row);
  }
}

// Sum nullable atomic display values exactly; absent components contribute zero.
function atomicSum(values) {
  return values.reduce(
    (total, value) => total + BigInt(value === null || value === undefined ? "0" : String(value)),
    0n,
    // Convert once after exact reduction so callers receive canonical decimal text.
  ).toString(10);
}

// Combine the four paid fee components for one landed order leg.
function legFees(leg) {
  if (!leg) return "0";
  return atomicSum([
    leg.protocol_fee_atomic,
    leg.creator_fee_atomic,
    // Network components are charged independently from Pump venue fees.
    leg.network_base_fee_atomic,
    // Priority fee remains distinct in details even though this helper totals it.
    leg.network_priority_fee_atomic,
  ]);
}

// Preserve null as visibly unavailable rather than silently presenting zero.
function atomicText(value) {
  return value === null || value === undefined ? "—" : String(value);
}

// Multi-line exact details share one safe monospace table-cell renderer.
function snipingDetailCell(lines) {
  const cell = document.createElement("td");
  cell.className = "mono sniping-detail";
  cell.textContent = lines.join("\n");
  // CSS preserves line breaks; no HTML interpolation is needed.
  return cell;
}

// Quote details retain reference, limit, landing, and signed slippage independently.
function legQuoteLines(leg) {
  if (!leg) {
    return ["in=—", "reference=—", "minimum=—", "landing=—", "delta=—", "failure=—"];
  }
  // Amount-in and reference quote establish the decision-time baseline.
  return [
    `in=${atomicText(leg.amount_in_atomic)}`,
    `reference=${atomicText(leg.reference_out_atomic)}`,
    `minimum=${atomicText(leg.minimum_out_atomic)}`,
    // Landing and failure fields distinguish successful movement from rejection.
    `landing=${atomicText(leg.landing_out_atomic)}`,
    `delta=${atomicText(leg.signed_slippage_atomic)}`,
    `failure=${atomicText(leg.failure_code)}`,
  ];
}

// Prefix side-specific fee lines so buy and sell remain distinguishable in one cell.
function legFeeLines(label, leg) {
  if (!leg) return [`${label}: none`];
  // Preserve every component before adding the derived side total.
  return [
    `${label}.protocol=${atomicText(leg.protocol_fee_atomic)}`,
    `${label}.creator=${atomicText(leg.creator_fee_atomic)}`,
    `${label}.network_base=${atomicText(leg.network_base_fee_atomic)}`,
    // The total is derived locally from the same exact four displayed components.
    `${label}.network_priority=${atomicText(leg.network_priority_fee_atomic)}`,
    `${label}.total=${legFees(leg)}`,
  ];
}

// Expand the bounded account component contract without flattening lifecycle semantics.
function accountAndRentLines(item) {
  const lines = [
    `profile=${item.account_profile_id}`,
    `acquired=${item.acquired_token_amount_atomic}`,
  ];
  // Components are bounded by the strict roundtrip result schema.
  for (const component of item.account_components) {
    // Render the exact bounded v3 component array without numeric coercion.
    lines.push(
      `${component.scope}.${component.requirement_schema_id}`,
      `lifecycle=${component.lifecycle}`,
      // Reservation, paid, released, refunded, and locked values must stay distinct.
      `maximum=${component.maximum_reserved_atomic}`,
      `paid=${component.paid_atomic}`,
      `released=${component.released_atomic}`,
      // Refund and locked delta reconcile the component's terminal lifecycle.
      `refunded=${component.refunded_atomic}`,
      `locked=${component.locked_delta_atomic}`,
    );
  }
  // Return one flattened display list while the source DTO stays structured.
  return lines;
}

// Show modeled demand, observed reserves, and actual funding as separate facts.
function sellLiquidityLines(item) {
  const landing = item.sell_landing_liquidity;
  return [
    `schema=${item.result_schema_id}`,
    `mode=${item.execution_mode}`,
    // Policy and required output identify the landing-side solvency model.
    `policy=${landing ? landing.policy_id : "—"}`,
    `landing_required=${landing ? landing.required_output_atomic : "—"}`,
    // Potential shortfall is not the same metric as actually settled synthetic funding.
    `observed_real=${landing ? landing.observed_available_output_atomic : "—"}`,
    `shortfall=${landing ? landing.synthetic_shortfall_atomic : "—"}`,
    `venue_funded=${atomicText(item.settled_venue_funded_atomic)}`,
    `synthetic_funded=${atomicText(item.settled_synthetic_funded_atomic)}`,
    // Settled funding is shown even when potential landing evidence is unavailable.
  ];
}

// Sort only the retained compact page through an explicit field allowlist.
function sortedSnipingRoundtrips() {
  const comparators = {
    // Target time and boundary use exact unsigned decimal ordering.
    target_time: (left, right) => compareUnsignedDecimal(
      left.target_time_ns,
      right.target_time_ns,
    ),
    // Boundary order remains available when several targets share a block timestamp.
    target: (left, right) => compareUnsignedDecimal(
      left.target_position.boundary_ordinal,
      right.target_position.boundary_ordinal,
    ),
    // Identity and lifecycle fields are sorted as bounded display text.
    status: (left, right) => compareText(left.status, right.status),
    asset: (left, right) => compareText(left.asset_id, right.asset_id),
    developer: (left, right) => compareText(left.developer_id, right.developer_id),
    // Monetary result fields are canonical signed decimal strings.
    realized_pnl: (left, right) => compareNullableAtomic(
      left.realized_cash_pnl_atomic,
      right.realized_cash_pnl_atomic,
      snipingSortDirection,
    ),
    // Missing economics stays distinct from a measured zero and sorts last.
    economic_pnl: (left, right) => compareNullableAtomic(
      left.economic_pnl_atomic,
      right.economic_pnl_atomic,
      snipingSortDirection,
    ),
  };
  // Comparator selection and exact tie-break identity are passed together.
  return sortBoundedPage(
    snipingPageItems,
    snipingPageSort.value,
    snipingSortDirection,
    // Local comparators and the exact roundtrip ID define deterministic ties.
    comparators,
    (item) => item.roundtrip_id,
  );
}

// Replace the compact table with exactly one page of validated round trips.
function renderSnipingRoundtrips() {
  const copy = snipingPageItems[0]?.contract_schema === "pumpfun-copy-position/v1";
  snipingPageSort.disabled = copy;
  snipingPageSortDirection.disabled = copy;
  // Copy keeps source order until a dedicated comparator contract is admitted.
  if (copy) { renderCopyPositions(snipingPageItems); return; }
  const items = sortedSnipingRoundtrips();
  // Only one bounded page exists in the DOM at any time.
  snipingRoundtripsBody.replaceChildren();
  if (items.length === 0) {
    renderTableMessage(snipingRoundtripsBody, "В run нет target-сделок", 12);
    return;
  }
  // Every page row is constructed from one strictly decoded roundtrip DTO.
  for (const item of items) {
    const row = document.createElement("tr");
    const target = document.createElement("td");
    // Target cell makes both human time and exact causal boundary visible.
    target.className = "mono";
    // Time is locale-formatted while the boundary stays exact decimal text.
    target.textContent = [
      formatNanosecondTimestamp(item.target_time_ns),
      `boundary=${item.target_position.boundary_ordinal}`,
    ].join("\n");
    const identity = document.createElement("td");
    // Full asset/developer identities remain in title and text, with CSS-only truncation.
    identity.className = "mono compact-hash";
    identity.title = `${item.asset_id} · ${item.developer_id}`;
    identity.textContent = `${item.asset_id} · ${item.developer_id}`;
    const state = document.createElement("td");
    state.textContent = item.status;
    // Quote and liquidity cells preserve component-level execution evidence.
    const buyQuote = snipingDetailCell(legQuoteLines(item.buy));
    const sellQuote = snipingDetailCell(legQuoteLines(item.sell));
    const sellLiquidity = snipingDetailCell(sellLiquidityLines(item));
    // Combined fees are derived from the same side components shown above them.
    const fees = snipingDetailCell([
      ...legFeeLines("buy", item.buy),
      ...legFeeLines("sell", item.sell),
      `combined=${atomicSum([legFees(item.buy), legFees(item.sell)])}`,
    ]);
    // Account, cashback, and PnL columns remain separate accounting views.
    const accountRent = snipingDetailCell(accountAndRentLines(item));
    const cashback = snipingDetailCell([
      `receivable=${atomicText(item.cashback_receivable_atomic)}`,
    ]);
    // Realized and economic PnL must not be collapsed into one ambiguous number.
    const realized = snipingDetailCell([
      `cash=${atomicText(item.realized_cash_pnl_atomic)}`,
    ]);
    // Economic PnL may remain unavailable when open-position valuation is incomplete.
    const economic = snipingDetailCell([
      `total=${atomicText(item.economic_pnl_atomic)}`,
    ]);
    // MTM fields explain the remaining open-position value when cash PnL is absent.
    const mtm = snipingDetailCell([
      `status=${item.mtm_status}`,
      `liquidation=${atomicText(item.mtm_liquidation_value_atomic)}`,
      // MTM cash PnL remains separate from liquidation value.
      `cash_pnl=${atomicText(item.mtm_cash_pnl_atomic)}`,
    ]);
    // Append the complete row once so live regions never observe partial columns.
    row.append(
      target,
      identity,
      state,
      buyQuote,
      // Execution evidence columns precede accounting result columns.
      sellQuote,
      sellLiquidity,
      fees,
      accountRent,
      // Financial outcome columns follow lifecycle and cost evidence.
      cashback,
      realized,
      economic,
      mtm,
    );
    // Only the current bounded page contributes rows to the DOM.
    snipingRoundtripsBody.append(row);
  }
}

// Compact navigation exposes range and fixed page size without an unbounded count query.
function updateSnipingPagination() {
  snipingPreviousPage.disabled = snipingPageIndex === 0;
  snipingNextPage.disabled = snipingNextCursor === null;
  // Range labels use retained row count and never request a full-result count.
  const first = snipingPageItems.length === 0 ? 0 : snipingPageIndex * SNIPING_PAGE_SIZE + 1;
  const last = snipingPageItems.length === 0
    ? 0
    : snipingPageIndex * SNIPING_PAGE_SIZE + snipingPageItems.length;
  // Make the one-page browser-memory bound visible to the operator.
  snipingPageLabel.textContent =
    `Страница ${snipingPageIndex + 1} · сделки ${first}–${last} · по ${SNIPING_PAGE_SIZE}`;
}

// Validate both row count and composite cursor before page state can commit.
function validateSnipingPage(page) {
  // The compact viewer follows the same one-page browser memory bound as the dashboard.
  if (!page || !Array.isArray(page.items) || page.items.length > SNIPING_PAGE_SIZE) {
    throw new Error("API вернул некорректную bounded-страницу roundtrips");
  }
  if (page.next_cursor === null) return page;

  // A continuation is accepted only in the canonical UInt64-plus-digest shape.
  const cursor = page.next_cursor;
  if (
    !cursor
    || typeof cursor.target_boundary_ordinal !== "string"
    // Canonical unsigned spelling prevents equivalent cursor aliases.
    || !/^(0|[1-9][0-9]*)$/.test(cursor.target_boundary_ordinal)
  ) {
    throw new Error("API вернул некорректный cursor roundtrips");
  }
  const boundary = BigInt(cursor.target_boundary_ordinal);
  // Scheduler boundaries must fit the declared UInt64 position contract.
  if (boundary < 0n || boundary >= (1n << 64n)) {
    throw new Error("API вернул cursor вне UInt64");
  }
  // Cursor identity uses the same lowercase SHA-256 shape as roundtrip IDs.
  if (!/^[0-9a-f]{64}$/.test(String(cursor.roundtrip_id))) {
    throw new Error("API вернул некорректный cursor roundtrips");
  }
  return page;
}

// Superseded compact-view requests are expected control flow, not visible errors.
function isRequestAbort(error) {
  return error instanceof DOMException && error.name === "AbortError";
}

// Load one later compact page for the currently selected immutable artifact.
async function loadSnipingRoundtrips() {
  if (snipingRunArtifactId === null) return;
  const artifactId = snipingRunArtifactId;
  // Snapshot page index and generation so a later selection can invalidate this response.
  const requestedPageIndex = snipingPageIndex;
  const generation = snipingLoadGeneration;
  const params = new URLSearchParams({ limit: String(SNIPING_PAGE_SIZE) });
  // The stored cursor is the sole authority for continuing the immutable result table.
  const pageCursor = snipingPageCursors[requestedPageIndex];
  if (pageCursor !== null) {
    params.set("after_target_boundary_ordinal", String(pageCursor.target_boundary_ordinal));
    params.set("after_roundtrip_id", pageCursor.roundtrip_id);
  }
  // Abort the previous compact-viewer read before starting a newer navigation request.
  if (snipingRequestController !== null) snipingRequestController.abort();
  const controller = new AbortController();
  snipingRequestController = controller;
  // Busy state belongs to this exact request generation.
  snipingRoundtripsBody.closest("table").setAttribute("aria-busy", "true");
  let page;
  try {
    // Fetch and validate before replacing the currently visible page.
    page = validateSnipingPage(await api(
      `/api/v1/run-artifacts/${encodeURIComponent(artifactId)}/roundtrips?${params}`,
      { signal: controller.signal },
    ));
  } finally {
    // Only the newest request owns the shared loading indicator.
    if (snipingRequestController === controller) {
      snipingRequestController = null;
      snipingRoundtripsBody.closest("table").setAttribute("aria-busy", "false");
    }
  }

  // A stale response cannot cross artifact or page boundaries in the compact viewer.
  if (
    generation !== snipingLoadGeneration
    || artifactId !== snipingRunArtifactId
    || requestedPageIndex !== snipingPageIndex
  ) return;
  // Commit rows and continuation together to avoid mismatched arrow state.
  snipingPageItems = page.items;
  snipingNextCursor = page.next_cursor;
  // Rendering and arrow state derive from the same committed page.
  renderSnipingRoundtrips();
  updateSnipingPagination();
}

// Open summary and first page atomically for a newly selected exact Run artifact.
async function openSnipingResult(runArtifactId) {
  const errorResult = document.querySelector("#sniping-results-error");
  const generation = ++snipingLoadGeneration;
  // Opening a new artifact invalidates any current page request immediately.
  if (snipingRequestController !== null) snipingRequestController.abort();
  const controller = new AbortController();
  snipingRequestController = controller;

  // Clear navigation authority until one combined response proves the selected run.
  snipingRunArtifactId = null;
  snipingPageCursors = [null];
  snipingPageIndex = 0;
  snipingNextCursor = null;
  // Drop previous artifact rows before starting the combined first read.
  snipingPageItems = [];
  snipingSummaryCards.replaceChildren();
  // Visible rows must never retain the identity of a previously selected Run.
  renderTableMessage(snipingRoundtripsBody, "Загрузка результата…", 12);
  updateSnipingPagination();
  snipingPreviousPage.disabled = true;
  snipingNextPage.disabled = true;
  // Keep the table empty and marked busy until the exact artifact validates.
  snipingRoundtripsBody.closest("table").setAttribute("aria-busy", "true");
  errorResult.hidden = true;
  let dashboard;
  try {
    // One endpoint returns summary and first bounded page under one verified reader.
    dashboard = await api(
      `/api/v1/run-artifacts/${encodeURIComponent(runArtifactId)}/dashboard?limit=${SNIPING_PAGE_SIZE}`,
      { signal: controller.signal },
    );
  } finally {
    // A superseded artifact request must not clear the current request's busy state.
    if (snipingRequestController === controller) {
      snipingRequestController = null;
      snipingRoundtripsBody.closest("table").setAttribute("aria-busy", "false");
    }
  }
  // Ignore any response superseded by a newer artifact selection.
  if (generation !== snipingLoadGeneration || controller.signal.aborted) return;

  // Commit summary and first page together so mixed-run UI state is impossible.
  if (dashboard.summary.run_artifact_id !== runArtifactId) {
    throw new Error("API вернул summary другого Run artifact");
  }
  const page = validateSnipingPage(dashboard.roundtrips);
  snipingRunArtifactId = runArtifactId;
  // Summary and page state commit only after their exact artifact identity matches.
  snipingPageItems = page.items;
  snipingNextCursor = page.next_cursor;
  renderSnipingSummary(dashboard.summary);
  // Page rows and navigation become visible from this same combined response.
  renderSnipingRoundtrips();
  updateSnipingPagination();
}

// Open the copy-specific signal dashboard bound to one immutable result artifact.
function copyResultActionButton(runArtifactId) {
  const button = document.createElement("a");
  button.className = "button-link secondary";
  button.textContent = "Copy Buy result";
  button.href = `/copy-results?run_artifact_id=${encodeURIComponent(runArtifactId)}`;
  // The result tab receives no opener authority and cannot submit a new run on navigation.
  button.target = "_blank";
  button.rel = "noopener noreferrer";
  return button;
}

// Open the dedicated dashboard in an isolated tab bound to the exact Run artifact.
function snipingResultActionButton(runArtifactId) {
  const button = document.createElement("a");
  button.className = "button-link secondary";
  button.textContent = "Sniping result";
  // Query parameter carries only the content-addressed artifact ID.
  button.href = `/sniping-results?run_artifact_id=${encodeURIComponent(runArtifactId)}`;
  button.target = "_blank";
  // Prevent the new tab from receiving an opener capability.
  button.rel = "noopener noreferrer";
  return button;
}

// Query bounded manifest or lineage metadata through their dedicated API routes.
async function showArtifact(artifactId, action) {
  const result = document.querySelector("#artifact-result");
  const form = document.querySelector("#artifact-form");
  form.elements.artifact_id.value = artifactId;
  const prefix = action === "lineage" ? "/api/v1/lineage/" : "/api/v1/artifacts/";
  // Artifact IDs remain URL-encoded text and never become filesystem paths.
  try {
    showResult(result, await api(`${prefix}${encodeURIComponent(artifactId)}`));
  } catch (error) {
    // Metadata read failures remain inside the artifact result panel.
    showResult(result, error.message, true);
  }
}

// Fast polling is needed only when a visible-page job has not reached terminal state.
function hasActiveJobs() {
  const terminal = new Set(["SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED"]);
  // Only visible-page activity needs the fast operational refresh cadence.
  return jobsPageItems.some((job) => !terminal.has(job.state));
}

// Self-schedule adaptive polling so slow responses never overlap themselves.
function scheduleJobPolling({ immediate = false } = {}) {
  if (jobPollTimer !== null) globalThis.clearTimeout(jobPollTimer);
  if (document.hidden) return;
  const delay = immediate ? 0 : hasActiveJobs() ? ACTIVE_JOB_POLL_MS : IDLE_JOB_POLL_MS;
  // Self-scheduling prevents overlapping requests when the server is slow.
  jobPollTimer = globalThis.setTimeout(async () => {
    jobPollTimer = null;
    await refreshJobs();
    // Re-evaluate active/idle cadence from the newly received page.
    scheduleJobPolling();
  }, delay);
}

// Resource polling uses a slower independent timer and pauses with the hidden tab.
function scheduleResourcePolling({ immediate = false } = {}) {
  if (resourcePollTimer !== null) globalThis.clearTimeout(resourcePollTimer);
  if (document.hidden) return;
  // Resource telemetry has no reason to compete with artifact queries every two seconds.
  resourcePollTimer = globalThis.setTimeout(async () => {
    await refreshResources();
    scheduleResourcePolling();
  }, immediate ? 0 : RESOURCE_POLL_MS);
}

// Keep textual and assistive direction state synchronized for all local sorts.
function updateSortDirection(button, direction, newestLabel = false) {
  const descending = direction === "desc";
  button.setAttribute("aria-pressed", String(descending));
  // Accessible label names the currently applied order without relying on the arrow.
  button.setAttribute(
    "aria-label",
    descending ? "Сортировать по убыванию" : "Сортировать по возрастанию",
  );
  // Date defaults use operator-friendly wording while other fields use generic direction.
  if (newestLabel && direction === "desc") {
    button.textContent = "Сначала новые ↓";
    return;
  }
  // Use words as well as arrows for accessible, unambiguous sort direction.
  button.textContent = direction === "asc" ? "По возрастанию ↑" : "По убыванию ↓";
}

document.querySelector("#refresh-jobs").addEventListener("click", refreshJobs);
document.querySelector("#refresh-runs").addEventListener("click", refreshRuns);

// Changing a job sort reorders only the retained page and avoids another API read.
document.querySelector("#jobs-sort").addEventListener("change", () => {
  const button = document.querySelector("#jobs-sort-direction");
  const newestLabel = document.querySelector("#jobs-sort").value === "submitted_at";
  updateSortDirection(button, jobsSortDirection, newestLabel);
  jobsRenderFingerprint = null;
  // Force one local render because the row data itself is unchanged.
  renderJobs();
});

// Direction toggle retains the job page and reverses only its local comparator.
document.querySelector("#jobs-sort-direction").addEventListener("click", (event) => {
  jobsSortDirection = jobsSortDirection === "asc" ? "desc" : "asc";
  updateSortDirection(event.currentTarget, jobsSortDirection);
  jobsRenderFingerprint = null;
  // Rebuild only job rows; server page selection and cursor remain unchanged.
  renderJobs();
});

document.querySelector("#jobs-previous-page").addEventListener("click", async () => {
  if (jobsRequestInFlight || jobsPageIndex === 0) return;
  const targetPageIndex = jobsPageIndex - 1;
  const targetCursor = jobsPageCursors[targetPageIndex];
  // Freeze arrows until the requested bounded page has replaced the old one.
  document.querySelector("#jobs-previous-page").disabled = true;
  document.querySelector("#jobs-next-page").disabled = true;
  jobsRenderFingerprint = null;
  await refreshJobs({ pageIndex: targetPageIndex, cursor: targetCursor });
  // Reset adaptive cadence after explicit operator navigation.
  scheduleJobPolling();
});

document.querySelector("#jobs-next-page").addEventListener("click", async () => {
  if (jobsRequestInFlight || !jobsHasNext || jobsNextCursor === null) return;
  const targetPageIndex = jobsPageIndex + 1;
  const targetCursor = jobsNextCursor;
  // Freeze arrows until the requested bounded page has replaced the old one.
  document.querySelector("#jobs-previous-page").disabled = true;
  document.querySelector("#jobs-next-page").disabled = true;
  jobsRenderFingerprint = null;
  await refreshJobs({ pageIndex: targetPageIndex, cursor: targetCursor });
  // Explicit navigation starts a fresh active/idle polling interval.
  scheduleJobPolling();
});

// Run sort changes never request or merge rows from another completion-time page.
document.querySelector("#runs-sort").addEventListener("change", () => {
  const button = document.querySelector("#runs-sort-direction");
  const newestLabel = document.querySelector("#runs-sort").value === "completed_at";
  updateSortDirection(button, runsSortDirection, newestLabel);
  runsRenderFingerprint = null;
  // Re-rendering preserves exact-artifact comparison selection on this page.
  renderRuns();
});

// Direction toggle preserves the completion-ordered page selected by the server.
document.querySelector("#runs-sort-direction").addEventListener("click", (event) => {
  runsSortDirection = runsSortDirection === "asc" ? "desc" : "asc";
  updateSortDirection(event.currentTarget, runsSortDirection);
  runsRenderFingerprint = null;
  // Resort only retained verified runs without reopening their artifacts.
  renderRuns();
});

document.querySelector("#runs-previous-page").addEventListener("click", async () => {
  if (runsRequestInFlight || runsPageIndex === 0) return;
  const targetPageIndex = runsPageIndex - 1;
  const targetCursor = runsPageCursors[targetPageIndex];
  // Run comparisons remain scoped to the page whose rows are currently visible.
  document.querySelector("#runs-previous-page").disabled = true;
  document.querySelector("#runs-next-page").disabled = true;
  // Comparison selection cannot span rows that are no longer loaded.
  runsRenderFingerprint = null;
  await refreshRuns({ navigation: { pageIndex: targetPageIndex, cursor: targetCursor } });
});

// Forward navigation requests the next globally completion-ordered run page.
document.querySelector("#runs-next-page").addEventListener("click", async () => {
  if (runsRequestInFlight || !runsHasNext || runsNextCursor === null) return;
  const targetPageIndex = runsPageIndex + 1;
  const targetCursor = runsNextCursor;
  // Run comparisons remain scoped to the page whose rows are currently visible.
  document.querySelector("#runs-previous-page").disabled = true;
  document.querySelector("#runs-next-page").disabled = true;
  // The next response wholly replaces the current page and its comparison state.
  runsRenderFingerprint = null;
  await refreshRuns({ navigation: { pageIndex: targetPageIndex, cursor: targetCursor } });
});

// Source inspection populates only matching identity fields in the dataset planner.
document.querySelector("#inspect-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const result = document.querySelector("#inspect-result");
  const button = form.querySelector("button");
  // Disable duplicate inspection while the bounded source read is active.
  button.disabled = true;
  try {
    const sourceId = encodeURIComponent(textField(form, "source_id"));
    // Source ID is encoded as one path segment and cannot inject a route.
    const data = await api(`/api/v1/sources/${sourceId}/inspect`, { method: "POST" });
    showResult(result, data);
    const plan = document.querySelector("#dataset-plan-form");
    // Copy proven source/network identity instead of asking for manual re-entry.
    plan.elements.source_id.value = data.source_id;
    plan.elements.source_inspection_artifact_id.value = data.artifact_id;
    plan.elements.network_id.value = data.network_id;
    plan.elements.position_schema_id.value = data.position_schema_id;
    if (data.capabilities.length > 0) {
      // Seed the planner with the first discovered capability and its mandatory columns.
      plan.elements.capability_id.value = data.capabilities[0].capability_id;
      plan.elements.columns.value = data.capabilities[0].mandatory_columns.join(",");
    }
  } catch (error) {
    // Inspection response errors never populate planner identity fields.
    showResult(result, error.message, true);
  } finally {
    // Inspection failure remains retryable without reloading the page.
    button.disabled = false;
  }
});

// Dataset planning sends one bounded requirement, budget, and query envelope.
document.querySelector("#dataset-plan-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  // Byte conversion constants remain local to the plan-request builder.
  const result = document.querySelector("#dataset-plan-result");
  const gib = 1024 ** 3;
  const mib = 1024 ** 2;
  // Invalidate any prior plan before evaluating new form inputs.
  prepareButton.disabled = true;
  resolvedDatasetPlan = null;
  try {
    const values = valuesOf(form);
    const data = await api("/api/v1/datasets/plan", {
      // The planner receives typed JSON; it performs no extraction itself.
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        // Inspection artifact binds the logical source to its proven capabilities.
        source_id: textField(form, "source_id"),
        source_inspection_artifact_id: textField(form, "source_inspection_artifact_id"),
        network_id: textField(form, "network_id"),
        // Typed half-open block range and settlement inputs define acquisition scope.
        position_schema_id: textField(form, "position_schema_id"),
        from_block_ordinal: integerField(form, "from_block_ordinal"),
        to_block_ordinal: integerField(form, "to_block_ordinal"),
        // Warmup and tail extend reads without creating extra decision targets.
        warmup_blocks: integerField(form, "warmup_blocks"),
        settlement_tail_blocks: integerField(form, "settlement_tail_blocks"),
        max_shard_blocks: integerField(form, "max_shard_blocks"),
        requested_days: null,
        // This form expresses one explicit strategy capability requirement.
        requirements: [{
          origin: "STRATEGY",
          origin_id: "local-ui-reference-strategy",
          // Capability and its canonical column list stay coupled in one requirement.
          capability_id: textField(form, "capability_id"),
          columns: tokenList(values, "columns"),
        }],
        budget: {
          // Convert operator-friendly GiB limits into exact API byte counts.
          max_remote_bytes: integerField(form, "max_remote_gib") * gib,
          max_local_bytes: integerField(form, "max_local_gib") * gib,
          // Duration, temporary reserve, and low-watermark complete admission limits.
          max_days: integerField(form, "max_days"),
          temporary_reserve_bytes: gib,
          disk_low_watermark_bytes: gib,
        },
        // Query safeguards remain fixed except for the admitted memory ceiling.
        query: {
          max_execution_seconds: 900,
          max_memory_bytes: integerField(form, "query_memory_mib") * mib,
          // Hard result-row ceiling prevents an accidental unbounded source response.
          max_result_rows: 10000000,
        },
        request_remote_estimate: false,
      }),
    });
    // Only an accepted resolved plan may enable the separate prepare action.
    resolvedDatasetPlan = data.resolved_plan;
    prepareButton.disabled = data.budget.status === "REJECTED";
    showResult(result, data);
  } catch (error) {
    // Keep prepare disabled when planning or browser-side validation fails.
    showResult(result, error.message, true);
  }
});

// Queue the exact resolved plan rather than rebuilding it during prepare submission.
prepareButton.addEventListener("click", async () => {
  const result = document.querySelector("#dataset-plan-result");
  if (resolvedDatasetPlan === null) return;
  prepareButton.disabled = true;
  try {
    // PREPARE_DATASET enters the same durable job path as other heavy work.
    const job = await submitResolvedJob("PREPARE_DATASET", {
      plan: resolvedDatasetPlan,
      schema: "backtest.prepare-dataset-job/v1",
    });
    // Durable receipt is displayed before refreshing the queue page.
    showResult(result, job);
    await refreshLatestJobs();
  } catch (error) {
    // Submission failure restores the action because no job owns the plan yet.
    showResult(result, error.message, true);
    prepareButton.disabled = false;
  }
});

// Resolve and submit either one FirstSwap run or a seed sweep through typed endpoints.
document.querySelector("#backtest-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  // Submitter data distinguishes run from sweep while sharing validated fields.
  const result = document.querySelector("#backtest-result");
  const button = event.submitter;
  const action = button?.dataset.action || "run";
  // Disable both submit choices so one form cannot launch overlapping resolutions.
  for (const candidate of form.querySelectorAll("button")) candidate.disabled = true;
  try {
    let job;
    if (action === "sweep") {
      const seeds = integerList(form, "sweep_seeds");
      // Resolve all sweep members before one durable RUN_SWEEP submission.
      const resolved = await api("/api/v1/sweep-specs/resolve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          entries: seeds.map((seed) => ({
            // Attempt nonce and physical settings remain unique per sweep member.
            draft: runDraft(form, seed),
            attempt_nonce: randomDigest(),
            physical_settings: runPhysicalSettings(form),
          })),
          // Comparison contract remains a closed scalar metric allowlist.
          comparison_metrics: ["canonical_result_hash"],
        }),
      });
      // Queue only the immutable resolved sweep contract returned by the API.
      job = await submitResolvedJob("RUN_SWEEP", {
        resolved_sweep_spec: resolved.resolved_sweep_spec,
        schema: "backtest.sweep-job/v2",
      });
      // A sweep can publish new Run artifacts and needs the same completion refresh.
      watchedRunJobIds.add(job.job_id);
    } else {
      // A single run resolves semantic identity before physical attempt submission.
      const resolved = await api("/api/v1/run-specs/resolve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // The form draft contains semantic fields only.
        body: JSON.stringify(runDraft(form)),
      });
      job = await submitTypedBacktest({
        // Attempt nonce prevents accidental reuse of physical attempt provenance.
        attempt_nonce: randomDigest(),
        physical_settings: runPhysicalSettings(form),
        resolved_run_spec: resolved.resolved_spec,
      });
    }
    // Show the durable job receipt and redirect the queue view to its newest page.
    showResult(result, job);
    await refreshLatestJobs();
  } catch (error) {
    showResult(result, error.message, true);
  } finally {
    // Both run and sweep actions become available after submission settles.
    for (const candidate of form.querySelectorAll("button")) candidate.disabled = false;
  }
});

// Resolve the strict discovered Sniping draft before submitting its physical attempt.
document.querySelector("#sniping-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const result = document.querySelector("#sniping-result");
  const button = form.querySelector("button[type='submit']");
  // One form submission owns the button until resolve and enqueue both finish.
  button.disabled = true;
  try {
    const resolved = await api("/api/v1/run-specs/resolve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // Draft construction validates atomic text before this request begins.
      body: JSON.stringify(pumpfunStrategyDraft(form)),
    });
    // Physical settings stay outside the resolved semantic spec by contract.
    const job = await submitTypedBacktest({
      attempt_nonce: randomDigest(),
      physical_settings: runPhysicalSettings(form),
      resolved_run_spec: resolved.resolved_spec,
    });
    // Receipt precedes the independent newest-job refresh.
    showResult(result, job);
    await refreshLatestJobs();
  } catch (error) {
    // The safe API message remains local to this strategy form.
    showResult(result, error.message, true);
  } finally {
    button.disabled = false;
  }
});

// The compact viewer accepts only an exact Run artifact ID from its typed form.
document.querySelector("#sniping-results-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const errorResult = document.querySelector("#sniping-results-error");
  try {
    // Initial open uses the combined summary-plus-first-page projection.
    await openSnipingResult(textField(form, "run_artifact_id"));
  } catch (error) {
    // Superseded opens stay silent; actionable failures appear in the result panel.
    if (!isRequestAbort(error)) showResult(errorResult, error.message, true);
  }
});

// Backward compact navigation re-fetches by stored keyset cursor, never cached rows.
snipingPreviousPage.addEventListener("click", async () => {
  if (snipingPageIndex === 0) return;
  const previousIndex = snipingPageIndex;
  const generation = snipingLoadGeneration;
  snipingPageIndex = previousIndex - 1;
  // Disable both arrows until the prior cursor page validates.
  snipingPreviousPage.disabled = true;
  snipingNextPage.disabled = true;
  // Keep the prior rows visible until the requested cursor page validates.
  const errorResult = document.querySelector("#sniping-results-error");
  try {
    await loadSnipingRoundtrips();
  } catch (error) {
    // Supersession by another artifact is expected and needs no rollback.
    if (isRequestAbort(error)) return;
    // Roll back only if a newer artifact load has not replaced this navigation state.
    if (generation === snipingLoadGeneration && snipingPageIndex === previousIndex - 1) {
      snipingPageIndex = previousIndex;
      updateSnipingPagination();
      // Preserve verified rows while surfacing this navigation failure.
      showResult(errorResult, error.message, true);
    }
  }
});

// Forward compact navigation advances only through the server-issued continuation.
snipingNextPage.addEventListener("click", async () => {
  if (snipingNextCursor === null) return;
  const previousIndex = snipingPageIndex;
  const generation = snipingLoadGeneration;
  // Discard stale forward cursors when navigation branches from an earlier page.
  snipingPageCursors = snipingPageCursors.slice(0, snipingPageIndex + 1);
  snipingPageCursors.push(snipingNextCursor);
  snipingPageIndex += 1;
  // Navigation state advances optimistically but rows remain until validation succeeds.
  snipingPreviousPage.disabled = true;
  snipingNextPage.disabled = true;
  // Keep the prior rows visible until the requested cursor page validates.
  const errorResult = document.querySelector("#sniping-results-error");
  try {
    await loadSnipingRoundtrips();
  } catch (error) {
    // A newer artifact request owns state after an abort and must not be overwritten.
    if (isRequestAbort(error)) return;
    // Preserve a newer load while rolling back only this failed forward navigation.
    if (generation === snipingLoadGeneration && snipingPageIndex === previousIndex + 1) {
      snipingPageCursors.pop();
      snipingPageIndex = previousIndex;
      // Restore arrow state from the last verified cursor and page.
      updateSnipingPagination();
      showResult(errorResult, error.message, true);
    }
  }
});

// Changing sort field is a synchronous operation over the one retained page.
snipingPageSort.addEventListener("change", renderSnipingRoundtrips);
snipingPageSortDirection.addEventListener("click", () => {
  snipingSortDirection = snipingSortDirection === "asc" ? "desc" : "asc";
  updateSortDirection(snipingPageSortDirection, snipingSortDirection);
  // Compact sorting is synchronous because only 25 retained rows are reordered.
  renderSnipingRoundtrips();
});

// Bind typed ML lifecycle forms to one shared durable submission/error pattern.
function bindMlForm(selector, endpoint, payloadFactory) {
  document.querySelector(selector).addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    // Locate controls inside the bound form so handlers cannot cross workflow panels.
    const result = form.querySelector(".result");
    const button = form.querySelector("button");
    // The button remains owned until submission and newest-page refresh settle.
    button.disabled = true;
    try {
      const job = await submitTypedMl(endpoint, payloadFactory(form, requireMlContract()));
      showResult(result, job);
      // Newly submitted ML work is immediately visible in the global job order.
      await refreshLatestJobs();
    } catch (error) {
      showResult(result, error.message, true);
    } finally {
      // Submission failure leaves the same typed form available for correction.
      button.disabled = false;
    }
    // Each bound form retains its own result panel and button lifecycle.
  });
}

bindMlForm("#ml-features-form", "/api/v1/ml/features", (form, contract) => {
  const name = textField(form, "feature_name");
  return {
    // Replay identity pins the exact event stream consumed by feature compilation.
    spec_version: 1,
    replay_pack_id: textField(form, "replay_pack_id"),
    replay_semantics_id: textField(form, "replay_semantics_id"),
    replay_layout_schema_id: textField(form, "replay_layout_schema_id"),
    feature_specs: [{
      // The selected field becomes one versioned point-in-time feature specification.
      name,
      version: 1,
      entity_key: "replay_row_id",
      input_ids: [],
      effective_time_semantics: "replay-event-boundary-v1",
      // Availability semantics and warmup prevent future information leakage.
      available_time_semantics: "event-boundary-plus-warmup-v1",
      warmup_boundaries: integerField(form, "warmup_boundaries"),
      dtype: "<i8",
      // Null policy depends only on the supported feature's canonical representation.
      null_policy: name === "event_index" ? "EXPLICIT_BITMAP" : "FORBID",
      code_bundle_id: contract.feature_builder_bundle_id,
      runtime_lock_id: contract.runtime_lock_id,
    }],
    // The reference compiler contract supplies code/runtime identity, not the browser.
    input_feature_set_ids: [],
    compiler_version: contract.compiler_version,
  };
});

// Universe construction pins snapshot, input features, and discovered builder identity.
bindMlForm("#ml-universe-form", "/api/v1/ml/universes", (form, contract) => ({
  spec_version: 1,
  snapshot_id: textField(form, "snapshot_id"),
  universe_spec_id: contract.universe_spec_id,
  // Feature dependencies are canonicalized exact artifact IDs.
  input_feature_set_ids: idList(valuesOf(form), "feature_set_ids"),
  builder_bundle_id: contract.universe_builder_bundle_id,
  // Config and compiler digests keep this selection reproducible.
  builder_config_digest: contract.universe_config_digest,
  compiler_version: contract.compiler_version,
}));

// Label construction binds its universe and cutoff to the discovered safe builder.
bindMlForm("#ml-labels-form", "/api/v1/ml/labels", (form, contract) => ({
  spec_version: 1,
  snapshot_id: textField(form, "snapshot_id"),
  universe_id: textField(form, "universe_id"),
  label_spec_id: contract.label_spec_id,
  // Builder and config identities are contract-owned immutable inputs.
  label_builder_bundle_id: contract.label_builder_bundle_id,
  label_config_digest: contract.label_config_digest,
  training_cutoff: integerField(form, "training_cutoff"),
  compiler_version: contract.compiler_version,
}));

// Training request keeps data split, runtime, and calibration identities explicit.
bindMlForm("#ml-train-form", "/api/v1/ml/models/train", (form, contract) => ({
  spec_version: 1,
  training_spec: {
    feature_set_ids: idList(valuesOf(form), "feature_set_ids"),
    // Label and universe identities bind the training population.
    label_set_id: textField(form, "label_set_id"),
    universe_id: textField(form, "universe_id"),
    // Ordered train/validation intervals include explicit purge and embargo gaps.
    split: {
      train_from: integerField(form, "train_from"),
      train_until: integerField(form, "train_until"),
      validation_from: integerField(form, "validation_from"),
      validation_until: integerField(form, "validation_until"),
      // Purge and embargo protect temporal separation around the validation cut.
      purge_boundaries: integerField(form, "purge_boundaries"),
      embargo_boundaries: integerField(form, "embargo_boundaries"),
    },
    // Hyperparameters and root seeds make estimator fitting reproducible.
    hyperparameter_digest: textField(form, "hyperparameter_digest"),
    root_seeds: integerList(form, "root_seeds"),
    training_cutoff: integerField(form, "training_cutoff"),
    // Modeled availability and runtime identity constrain causal model use.
    modeled_available_boundary: integerField(form, "modeled_available_boundary"),
    trainer_bundle_id: contract.trainer_bundle_id,
    runtime_lock_id: contract.runtime_lock_id,
  },
  // Feature schema and preprocessing digests pin the trained input representation.
  feature_schema_digest: textField(form, "feature_schema_digest"),
  preprocessing_digest: textField(form, "preprocessing_digest"),
  // Post-processing identities and exact framework complete model reproducibility.
  calibration_digest: textField(form, "calibration_digest"),
  ridge_lambda: integerField(form, "ridge_lambda"),
  framework: contract.trainer_framework,
  // This reference workflow exposes only canonical exact training.
  canonicality: "CANONICAL_EXACT",
  compiler_version: contract.compiler_version,
}));

// Model schedule exposes one bounded causal eligibility interval in this UI slice.
bindMlForm("#ml-schedule-form", "/api/v1/ml/model-schedules", (form, contract) => ({
  spec_version: 1,
  schedule: {
    entries: [{
      eligible_from: integerField(form, "eligible_from"),
      // Eligibility is half-open and independent from modeled availability.
      eligible_until: integerField(form, "eligible_until"),
      // Bundle cutoff and availability jointly prevent premature model selection.
      model_bundle_id: textField(form, "model_bundle_id"),
      training_cutoff: integerField(form, "training_cutoff"),
      model_available_boundary: integerField(form, "model_available_boundary"),
      availability_basis: "modeled-training-completion-v1",
    }],
    // Absence of fallback makes gaps fail closed instead of choosing another model.
    fallback_model_bundle_id: null,
  },
  // Exact canonicality and compiler identity are fixed, not free-form inputs.
  canonicality: "CANONICAL_EXACT",
  compiler_version: contract.compiler_version,
}));

// Prediction materialization binds replay, features, schedule, and missing-value policy.
bindMlForm("#ml-predict-form", "/api/v1/ml/predictions", (form, contract) => ({
  spec_version: 1,
  replay_pack_id: textField(form, "replay_pack_id"),
  replay_semantics_id: textField(form, "replay_semantics_id"),
  replay_layout_schema_id: textField(form, "replay_layout_schema_id"),
  // Exact feature/model artifacts define the frozen inference dependency closure.
  feature_set_ids: idList(valuesOf(form), "feature_set_ids"),
  model_schedule_id: textField(form, "model_schedule_id"),
  model_bundle_ids: idList(valuesOf(form), "model_bundle_ids"),
  prediction_name: textField(form, "prediction_name"),
  inference_delay_boundaries: integerField(form, "inference_delay_boundaries"),
  // Missing policy and compiler canonicality remain explicit execution semantics.
  missing_policy: valuesOf(form).get("missing_policy"),
  canonicality: "CANONICAL_EXACT",
  compiler_version: contract.compiler_version,
}));

// Manifest and lineage buttons share one exact-artifact metadata form.
document.querySelector("#artifact-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  // Submitter action is restricted to manifest or lineage buttons in this form.
  await showArtifact(
    textField(event.currentTarget, "artifact_id"),
    event.submitter?.dataset.action || "manifest",
  );
});

// Compare only selected rows currently held in the bounded run page.
document.querySelector("#compare-runs").addEventListener("click", () => {
  const selected = new Set(
    Array.from(document.querySelectorAll(".run-selection:checked"), (item) => item.value),
  );
  const runs = lastRuns.filter((run) => selected.has(run.run_artifact_id));
  // Two verified runs are the minimum meaningful comparison set.
  if (runs.length < 2) {
    showResult(runsResult, "Выберите минимум два committed run", true);
    return;
  }
  // Read the metric only after the selection count is valid.
  const metric = runComparisonMetric.value;
  let compared;
  // The allowlisted metric must be present in every selected typed projection.
  try {
    compared = runs.map((run) => {
      if (!run.comparison || !Object.hasOwn(run.comparison, metric)) {
        throw new Error(`Run response не содержит typed metric ${metric}`);
      }
      // Projection carries exact logical and physical provenance for interpretation.
      return {
        // Artifact, logical run, and attempt IDs remain separately visible.
        run_artifact_id: run.run_artifact_id,
        logical_run_id: run.logical_run_id,
        execution_attempt_id: run.execution_attempt_id,
        value: run.comparison[metric],
        canonicality: run.canonicality,
        // Physical settings explain performance differences without changing semantics.
        physical_settings: run.physical_settings,
        // Bounded warnings remain explanatory metadata, never comparison input.
        warnings: run.warnings,
      };
    });
  } catch (error) {
    // One missing typed metric invalidates the whole comparison set.
    showResult(runsResult, error.message, true);
    return;
  }
  // Equality uses canonical JSON representation of already typed scalar metrics.
  // Result panel receives one closed comparison document.
  showResult(runsResult, {
    metric,
    // Equality concerns only the selected metric, not physical attempt metadata.
    identical: new Set(compared.map((item) => JSON.stringify(item.value))).size === 1,
    runs: compared,
  });
});

// Visibility owns only polling timers and never changes durable job execution.
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    globalThis.clearTimeout(jobPollTimer);
    globalThis.clearTimeout(resourcePollTimer);
    // Hidden tabs perform no background polling work.
    return;
  }
  // Resume only lightweight operational reads when the tab becomes visible.
  scheduleJobPolling({ immediate: true });
  scheduleResourcePolling({ immediate: true });
});
// Mode changes immediately update the persistent synthetic-liquidity warning.
snipingExecutionMode.addEventListener("change", updateSnipingExecutionWarning);

// Start independent bounded polling before any one startup endpoint can delay the UI.
scheduleJobPolling({ immediate: true });
scheduleResourcePolling({ immediate: true });
globalThis.setTimeout(() => void refreshRuns(), 0);

// Populate static form contracts concurrently; each API read owns its fixed timeout.
await Promise.all([
  refreshHealth(),
  refreshRunPhysicalSettings(),
  // Strategy and ML discovery remain independent even if one request rejects.
  refreshSnipingContract(),
  refreshMlContract(),
  // The aggregate exposes one concise startup failure through the health status.
]).catch((error) => {
  health.textContent = `Инициализация UI неполна · ${error.message}`;
  health.className = "status error";
});
