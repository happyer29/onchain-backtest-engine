"use strict";

// Independent weighted fixtures exercise grouping coverage, not just the shape of the implementation.
const assert = require("node:assert/strict"), test = require("node:test");
const {readFileSync} = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const source = readFileSync(path.resolve(__dirname, "../../src/backtest/interfaces/web/static/research-graph-model.js"), "utf8");
const model = vm.runInNewContext(source + "\nResearchGraphModel;", {setTimeout, DOMException});
// Two tight triangles joined by a weak bridge are specified without consulting calculated memberships.
const fixture = () => ({wallets: ["A", "B", "C", "D", "E", "F", "Z"], rows:
  [["A", "B", 10], ["A", "C", 10], ["B", "C", 10], ["C", "D", 1], ["D", "E", 10], ["D", "F", 10], ["E", "F", 10]]
    .map(([signer_a, signer_b, weight], index) => ({row_id: String(index), signer_a, signer_b, shared_mints: String(weight)}))});
const signal = () => new AbortController().signal;

// Every node and pair must be accounted for, including the isolated singleton and the weak bridge.
test("weighted groups reconcile disjoint internal and crossing pairs with all wallets", async () => {
  const data = fixture(), result = await model.build(data, signal());
  assert.deepEqual(Array.from(result.groups, (group) => Array.from(group.members, (node) => result.wallets[node])), [["A", "B", "C"], ["D", "E", "F"], ["Z"]]);
  assert.equal(result.internal, 6);
  assert.equal(result.external, 1);
  // Each original ordinal appears exactly once across the disjoint overview buckets.
  const indices = [...result.groups.flatMap((group) => group.internal), ...result.links.flatMap((link) => link.indices)];
  assert.deepEqual(Array.from(indices).sort((a, b) => a - b), [0, 1, 2, 3, 4, 5, 6]);
  assert.equal(result.links[0].indices[0], 3);
  assert.equal(result.stable, true);
  assert.ok(result.passes <= 20);
  // Releasing a loader's temporary array must not discard the accepted complete display index.
  data.rows.length = 0;
  assert.equal(result.rows.length, 7);
});

// Canonical visitation and tie handling are invariant to incoming wallet and row array order.
test("presentation groups are deterministic for reordered equivalent input", async () => {
  const first = fixture(), second = fixture();
  second.wallets.reverse(); second.rows.reverse();
  const a = await model.build(first, signal()), b = await model.build(second, signal());
  assert.deepEqual(Array.from(a.groupOf), Array.from(b.groupOf));
  // Input transport order cannot change when deterministic local moves finish.
  assert.equal(a.passes, b.passes);
  // The exact ordinal set is preserved even when the transport array has a different order in this fixture.
  assert.deepEqual(Array.from(a.rows, (row) => row.row_id).sort(), Array.from(b.rows, (row) => row.row_id).sort());
});

// The bridge wallet's view contains the opposite group's wallet plus all optional neighbour pairs.
test("wallet focus crosses groups and the optional induced neighbourhood adds every extra edge", async () => {
  const result = await model.build(fixture(), signal());
  const base = await model.neighbourhood(result, "C", false, signal());
  // Adding neighbour pairs must not change the node set or the centre’s incident set.
  const expanded = await model.neighbourhood(result, "C", true, signal());
  assert.deepEqual(Array.from(base.members, (node) => result.wallets[node]), ["A", "B", "C", "D"]);
  // C has three direct pairs; A–B is the one additional pair between its neighbours.
  assert.deepEqual(Array.from(base.indices).sort((a, b) => a - b), [1, 2, 3]);
  assert.deepEqual(Array.from(expanded.indices).sort((a, b) => a - b), [0, 1, 2, 3]);
  assert.equal(base.extra, 1); assert.equal(expanded.incident, 3);
  await assert.rejects(model.neighbourhood(result, "missing", false, signal()), /отсутствует/);
});

// Empty data is empty; malformed input and resource excesses never yield a plausible partial hierarchy.
test("empty graphs and local allocation bounds have explicit semantics", async () => {
  const empty = await model.build({rows: [], wallets: []}, signal());
  assert.equal(empty.groups.length, 0); assert.equal(empty.internal + empty.external, 0);
  await assert.rejects(model.build({rows: Array(200001), wallets: []}, signal()), /лимит/);
  await assert.rejects(model.build({rows: [], wallets: Array(5001)}, signal()), /лимит/);
  // Invalid endpoints, weights and duplicate nodes reject the whole model before grouping.
  for (const mutate of [(data) => {data.rows[0].signer_a = "missing";}, (data) => {data.rows[0].shared_mints = "NaN";}, (data) => {data.wallets.push("A");}]) {
    const data = fixture(); mutate(data);
    await assert.rejects(model.build(data, signal()), /Некорректная|Повтор/);
  }
});

// A cancellation or scope replacement during a yielded phase cannot publish a completed display model.
test("build and neighbourhood scans honour abort and ownership retirement", async () => {
  const controller = new AbortController(), building = model.build(fixture(), controller.signal);
  controller.abort();
  await assert.rejects(building, {name: "AbortError"});
  await assert.rejects(model.build(fixture(), signal(), () => {}, () => false), {name: "AbortError"});
  // Cancellation during grouping, after endpoint indexing, exercises the later bounded checkpoints too.
  const later = new AbortController();
  await assert.rejects(model.build(fixture(), later.signal, (done) => {if (done >= 20) later.abort();}), {name: "AbortError"});
  const result = await model.build(fixture(), signal());
  await assert.rejects(model.neighbourhood(result, "C", true, signal(), () => false), {name: "AbortError"});
});
