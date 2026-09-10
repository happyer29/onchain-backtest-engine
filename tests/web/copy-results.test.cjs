"use strict";

// Run with Node's built-in test runner; no browser or package dependency is required.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
// These tests execute the shipped scripts and control transport completion order explicitly.
const staticRoot = path.resolve(__dirname, "../../src/backtest/interfaces/web/static");
const run = "1".repeat(64), positionId = "2".repeat(64);
const network = "solana:test-fixture", schema = "block32-transaction32-v1";

// A minimal DOM spy records safe text, SVG coordinates and event handlers without HTML parsing.
class Element {
  constructor(tag = "div") {
    this.tag = tag; this.children = []; this.attributes = {}; this.events = {};
    this.textContent = ""; this.value = ""; this.hidden = false; this.open = false;
  }
  // Only APIs used by the packaged page are emulated; innerHTML is intentionally absent.
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(key, handler) { (this.events[key] ||= []).push(handler); }
  showModal() { this.open = true; }
  // Closing invokes the cancellation contract rather than merely hiding pixels.
  close() { this.open = false; this.fire("close"); }
  fire(key) { for (const handler of this.events[key] || []) handler({ preventDefault() {} }); }
}

// Source fixtures retain wide nanoseconds and exact chain coordinates as in the API schema.
function point(tx, cap = "9007199254740993001", lifecycle = "ACTIVE") {
  return { position: { network_id: network, position_schema_id: schema, block_ordinal: 100, transaction_index: tx, event_index: null }, block_time_ns: String(1700000000000000000n + BigInt(tx) * 1000000000n), market_cap_atomic: cap, lifecycle };
}

// Actual entry and exit coordinates are separate from the source signal coordinate.
function fixtures() {
  const signal = point(1), buy = point(3), sell = point(8, "8007199254740993001");
  const attempts = [
    { attempt: "0", side: "BUY", status: "FILLED", landing_position: buy.position, failure_code: null },
    { attempt: "1", side: "SELL", status: "FILLED", landing_position: sell.position, failure_code: null },
  // The fixture keeps its source signal separate from its two actual fills.
  ];
  // The row mirrors only the fields needed by validation and the visible token table.
  const record = { position_id: positionId, asset_id: "TOKEN", quote_asset_id: "SOL", signing_wallet: "LEADER", signal_position: signal.position, attempts, status: "CLOSED", exit_reason: "STOP_LOSS", execution_mode: "EXOGENOUS_REPLAY", realized_cash_pnl_atomic: "-5200" };
  const markers = [{ kind: "SIGNAL", status: "OBSERVED_SOURCE", attempt: null, failure_code: null, point: signal }, { kind: "BUY", status: "FILLED", attempt: 0, failure_code: null, point: buy }, { kind: "SELL", status: "FILLED", attempt: 1, failure_code: null, point: sell }];
  const chart = { contract_schema: "pumpfun-copy-market-cap/v1", market_cap_policy: "post-transaction-total-supply-market-cap-lamports-floor/v1", run_artifact_id: run, position_id: positionId, snapshot_id: "3".repeat(64), asset_id: "TOKEN", quote_asset_id: "SOL", points: [point(0), signal, sell, point(10, "8007199254740993001")], markers };
  return { record, chart };
}

// The fetch spy deliberately ignores abort, simulating a late response already queued for delivery.
function environment() {
  const elements = new Map(), pending = [];
  const get = (id) => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
  get("copy-page-size").value = "25";
  const document = { getElementById: get, createElement: (tag) => new Element(tag), createElementNS: (_, tag) => new Element(tag) };
  // Standard built-ins exercise real BigInt, URL and AbortController semantics.
  const context = vm.createContext({ document, AbortController, URLSearchParams, setTimeout, clearTimeout, location: { search: "" }, history: { replaceState() {} }, fetch: (url, options) => new Promise((resolve) => pending.push({ url, options, resolve })) });
  for (const name of ["copy-market-chart.js", "copy-results.js"]) vm.runInContext(fs.readFileSync(path.join(staticRoot, name), "utf8"), context);
  context.fixture = fixtures();
  vm.runInContext(`runId = "${run}"`, context);
  return { context, get, pending };
// Resolve transport responses manually so arrival order is independent of request order.
}

// Responses preserve asynchronous parsing, so cancellation is tested across both fetch and JSON.
function respond(request, body) {
  request.resolve({ ok: true, json: async () => body });
}

test("wide values and boundary ordinals remain exact; failure markers cannot masquerade as fills", () => {
  // Large lamport values must not pass through Number during formatting.
  const { context } = environment(), helper = context.CopyMarketChart;
  assert.equal(helper.sol("9007199254740993001", 9), "9007199254.740993001");
  assert.equal(helper.sol(null), "Нет оценки");
  assert.equal(helper.boundary(point(1).position), 429496729602n);
  // A response must retain the original recorded attempt outcome, not only its token address.
  const { chart, record } = fixtures();
  assert.equal(helper.validate(chart, run, record), chart);
  chart.markers[1].status = "FAILED";
  assert.throws(() => helper.validate(chart, run, record), /исход/);
});

// Closing the dialog cancels authority as well as network transport.

test("closing a chart aborts its request and ignores a late successful response", async () => {
  const env = environment();
  const completion = vm.runInContext("openChart(fixture.record)", env.context);
  assert.equal(env.pending.length, 1);
  // The modal owns exactly one in-flight request for its selected immutable signal.
  env.get("copy-chart-dialog").close();
  // The caller must reject a superseded success even if transport cancellation arrives too late.
  assert.equal(env.pending[0].options.signal.aborted, true);
  respond(env.pending[0], env.context.fixture.chart);
  await completion;
  assert.equal(env.get("copy-chart-content").hidden, true);
  assert.equal(env.get("copy-market-plot").children.length, 0);
// A cancelled response must not restore hidden content or old plot nodes.
});

test("selecting another token cannot display the older token's late chart", async () => {
  const env = environment(), first = vm.runInContext("openChart(fixture.record)", env.context);
  const secondRecord = structuredClone(env.context.fixture.record);
  // Select another immutable row while the first request is still unresolved.
  secondRecord.asset_id = "SECOND"; secondRecord.position_id = "4".repeat(64);
  env.context.second = secondRecord;
  // Complete the newer chart first, then deliver the stale original chart afterwards.
  const second = vm.runInContext("openChart(second)", env.context);
  const chart = structuredClone(env.context.fixture.chart);
  chart.asset_id = "SECOND"; chart.position_id = secondRecord.position_id;
  respond(env.pending[1], chart); await second;
  assert.equal(env.get("copy-chart-content").hidden, false);
  // The stale response must not restore the first mint or alter the current data authority.
  respond(env.pending[0], env.context.fixture.chart); await first;
  assert.equal(env.get("copy-chart-token").textContent, "SECOND");
  assert.equal(vm.runInContext("chartData.asset_id", env.context), "SECOND");
});

// Invalid run input must clear chart data before showing its validation error.
test("an invalid run selection clears chart authority before input validation", async () => {
  const env = environment(), chartRead = vm.runInContext("openChart(fixture.record)", env.context);
  await vm.runInContext("openRun('invalid')", env.context);
  assert.equal(env.pending[0].options.signal.aborted, true);
  assert.equal(vm.runInContext("runId", env.context), null);
  // The old response must remain invisible after the new selection reports a validation error.
  respond(env.pending[0], env.context.fixture.chart); await chartRead;
  assert.equal(env.get("copy-chart-content").hidden, true);
  assert.equal(env.get("copy-content").hidden, true);
  assert.match(env.get("copy-error").textContent, /64/);
// Terminal history can be inspected without inventing an executable continuation.
});

test("a terminal curve stops the line while later rejections remain explicit events", () => {
  const { context, get } = environment(), data = fixtures().chart;
  data.points = [point(0), point(1), point(5, "9507199254740993001", "MIGRATED"), point(20, "9507199254740993001", "MIGRATED")];
  // The post-migration attempt is a rejection at the last historical state, never a fill.
  data.markers[2] = { ...data.markers[2], status: "REJECTED", failure_code: "CURVE_MIGRATED", point: point(8, "9507199254740993001", "MIGRATED") };
  context.CopyMarketChart.render(data, false);
  const root = get("copy-market-plot").children[0];
  // The path contains only the two historical transitions, not a flat continuation to clock end.
  const plot = root.children.find((item) => item.tag === "g");
  const line = plot.children.find((item) => item.attributes.class === "copy-market-line");
  assert.equal((line.attributes.d.match(/ H /g) || []).length, 2);
  assert.ok(plot.children.some((item) => item.attributes.class === "copy-terminal"));
});
