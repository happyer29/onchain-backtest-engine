"use strict";

// Exercise transport and completeness boundaries without a browser, source credentials or new dependencies.
const assert = require("node:assert/strict"), test = require("node:test");
const vm = require("node:vm"), {readFileSync} = require("node:fs"), path = require("node:path");
const source = readFileSync(path.resolve(__dirname, "../../frontend/src/research/research-graph-load.js"), "utf8").replace(/export default [^;]+;/, "");
const artifact = "a".repeat(64), signal = () => new AbortController().signal;
// Base58 fixture addresses have real API shapes and lexical ordering, but no external meaning.
function address(value) {
  const alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
  let encoded = "";
  do {encoded = alphabet[value % 58] + encoded; value = Math.floor(value / 58);} while (value);
  // Fixed width makes lexical signer ordering independent from variable-length integer encoding.
  return encoded.padStart(32, "1");
}

// All rows have an independently chosen two-mint direction/tie reconciliation.
function pair(index) {
  return {row_id: String(index), signer_a: address(0), signer_b: address(index + 1),
    shared_mints: "2", a_first: "1", b_first: "0", same_transaction: "1"};
}
function harness(fetch = () => {throw new Error("Unexpected network");}) {
  // Built-in stream and abort primitives exercise the same deadlines and byte reader as the browser.
  const context = {AbortSignal, URLSearchParams, TextDecoder, fetch};
  return vm.runInNewContext(source + "\nResearchGraphLoad;", context);
}

// The test server requires the previous opaque cursor and includes final-empty continuation semantics.
function pages(total, change = (page) => page) {
  let offset = 0;
  return async (url) => {
    const query = new URL(url, "http://127.0.0.1").searchParams;
    assert.equal(query.get("limit"), "200");
    // The client must forward exactly the preceding server cursor, not invent its own offset.
    assert.equal(query.get("cursor"), offset ? `opaque-${offset}` : null);
    const start = offset, end = Math.min(offset + 200, total);
    offset = end;
    // Test mutations preserve the normal cursor protocol unless that exact invariant is under test.
    return change({artifact_id: artifact, table: "pairs", rows: Array.from({length: end - start}, (_, n) => pair(start + n)),
      next_cursor: end - start === 200 ? `opaque-${offset}` : null}, start);
  };
}

// A successful loader includes all rows beyond the initial table page and proves cursor exhaustion.
test("whole loading follows exact cursors and checks empty final pages and zero results", async () => {
  const h = harness(), progress = [];
  const result = await h.load(artifact, "400", signal(), (...counts) => progress.push(counts), pages(400));
  assert.equal(result.rows.length, 400);
  assert.equal(result.wallets.length, 401);
  // The last full page is not prematurely treated as an exhausted cursor.
  assert.deepEqual(progress.map((counts) => counts[0]), [200, 400, 400]);
  const empty = await h.load(artifact, "0", signal(), () => {}, pages(0));
  assert.equal(empty.rows.length, 0);
});

// Corrupt scope, ordinals and incomplete/excess data must never become a complete graph.
for (const [name, change] of [
  ["artifact", (p) => ({...p, artifact_id: "b".repeat(64)})],
  ["table", (p) => ({...p, table: "activity"})],
  ["missing row", (p) => ({...p, rows: p.rows.slice(1)})],
  // Ordinal checks protect against both duplicates and gaps under the same immutable artifact.
  ["duplicate ordinal", (p) => ({...p, rows: [p.rows[0], p.rows[0]]})],
  ["out of order", (p) => ({...p, rows: [...p.rows].reverse()})],
  ["duplicate pair", (p) => ({...p, rows: [p.rows[0], {...p.rows[0], row_id: "1"}]})],
  ["bad reconciliation", (p) => ({...p, rows: [{...p.rows[0], shared_mints: "3"}]})],
  // A cursor cannot continue after a short page, escape scope, or loop indefinitely.
  ["short continuing page", (p) => ({...p, next_cursor: "again"})],
  ["missing cursor", (p) => ({...p, next_cursor: undefined})],
  ["bad address", (p) => ({...p, rows: [{...p.rows[0], signer_a: "<script>"}]})]
]) {
  // Each malformed response owns an isolated loader and cannot contaminate another test.
  test(`rejects ${name}`, async () => {
    const h = harness();
    // The failure itself is the contract; no invalid partial array is returned to any renderer.
    await assert.rejects(h.load(artifact, "2", signal(), () => {}, pages(2, change)));
  });
}

// Both byte admission and cardinality admission are explicit errors rather than a sampled success.
test("rejects pair and wallet limits, undercounts, oversized pages and looping cursors", async () => {
  const h = harness();
  await assert.rejects(h.load(artifact, "200001", signal(), () => {}), /200 000/);
  await assert.rejects(h.load(artifact, "5000", signal(), () => {}, pages(5000)), /5 000/);
  await assert.rejects(h.load(artifact, "3", signal(), () => {}, pages(2)), /не все пары/);
  // Metadata undercounts cannot silently reduce the read to a prefix.
  await assert.rejects(h.load(artifact, "1", signal(), () => {}, pages(2)), /Число пар/);
  const large = async () => ({artifact_id: artifact, table: "pairs", rows: Array.from({length: 201}, (_, n) => pair(n)), next_cursor: null});
  await assert.rejects(h.load(artifact, "201", signal(), () => {}, large), /Число пар/);
  // A repeated cursor after valid contiguous rows is independently rejected before a third request.
  await assert.rejects(h.load(artifact, "400", signal(), () => {}, pages(400, (p, start) => ({...p, next_cursor: start ? "opaque-200" : p.next_cursor}))), /продолжение/);
});

// Cancellation during an in-flight page cannot report progress or return late rows to a replacement view.
test("aborted loading discards a late successful response", async () => {
  const h = harness(), controller = new AbortController(), progress = [];
  let finish;
  const pending = h.load(artifact, "1", controller.signal, (n) => progress.push(n), () => new Promise((resolve) => {finish = resolve;}));
  controller.abort();
  // A mock server may still respond after abort; the post-read check remains mandatory.
  finish({artifact_id: artifact, table: "pairs", rows: [pair(0)], next_cursor: null});
  await assert.rejects(pending, {name: "AbortError"});
  assert.deepEqual(progress, []);
});

// A synthetic streamed response exercises incremental byte accounting and response cancellation.
test("streaming enforces response and cumulative byte limits before parsing", async () => {
  let cancelled = 0;
  const oversize = () => new Response(new ReadableStream({
    start(control) {control.enqueue(new Uint8Array(2 * 1024 * 1024 + 1));},
    // Cancellation confirms that oversized unfinished streams release their reader.
    cancel() {cancelled++;}
  }));
  // The reader stops without waiting for an oversized response body to finish.
  await assert.rejects(harness(oversize).load(artifact, "0", signal(), () => {}), /байтах/);
  assert.equal(cancelled, 1);
  const next = pages(13200);
  // Use repeated valid wallet combinations so the byte cap is reached before the wallet cap.
  let ordinal = 0;
  const many = async (url) => {
    const p = await next(url);
    p.rows = p.rows.map((row) => ({...row, signer_a: address(1 + Math.floor(ordinal / 1000)), signer_b: address(100 + ordinal++ % 1000)}));
    // Whitespace consumes transport bytes but does not inflate analytical wallet cardinality.
    return new Response(JSON.stringify(p).padEnd(2 * 1024 * 1024, " "));
  };
  // Each response individually fits, but the 65th must reject the complete 128 MiB transfer.
  await assert.rejects(harness(many).load(artifact, "13200", signal(), () => {}), /байтах/);
});

// Variable-length full addresses are ordered as tuples, not delimiter-concatenated strings.
test("accepts a lexically ordered signer prefix without misordering the tuple", async () => {
  const h = harness(), prefix = "2".repeat(32);
  const rows = [{...pair(0), signer_a: prefix, signer_b: "z".repeat(32)},
    {...pair(1), signer_a: prefix + "1", signer_b: "z".repeat(32)}];
  const read = async () => ({artifact_id: artifact, table: "pairs", rows, next_cursor: null});
  // The shorter signer sorts first, irrespective of what delimiter might otherwise follow it.
  const result = await h.load(artifact, "2", signal(), () => {}, read);
  assert.equal(result.rows.length, 2);
});
