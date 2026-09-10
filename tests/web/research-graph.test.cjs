"use strict";

// Exercise the application renderer against the actual pinned graph core, without a browser runtime.
const assert = require("node:assert/strict");
const test = require("node:test");
const vm = require("node:vm");
const {readFileSync} = require("node:fs");
const path = require("node:path");
// Files resolve from this test, independent of the invocation's working directory.
const staticRoot = path.resolve(__dirname, "../../src/backtest/interfaces/web/static");
const librarySource = readFileSync(path.join(staticRoot, "vendor/cytoscape-3.34.3.min.js"), "utf8");
const source = readFileSync(path.join(staticRoot, "research-graph.js"), "utf8");

// This minimal text/control surface is deliberately separate from Cytoscape's real graph operations.
class Control {
  constructor() {
    this.children = [];
    this.events = {};
    this.value = "";
    // Expansion only needs a boolean class toggle; browser geometry is checked in the real smoke.
    this.classList = {toggle: () => true};
  }
  replaceChildren(...children) {this.children = children;}
  append(child) {this.children.push(child);}
  get firstElementChild() {return this.children[0];}
  // Event handlers are invoked through controls, rather than calling private renderer helpers.
  addEventListener(name, fn) {this.events[name] = fn;}
  fire(name) {return this.events[name]({target: this});}
  setAttribute() {}
  querySelectorAll() {return this.children;}
}

// Each test owns a fresh DOM, renderer closure and graph instance.
function harness(withLibrary = true) {
  const controls = new Map();
  const find = (selector) => {
    if (!controls.has(selector)) controls.set(selector, new Control());
    return controls.get(selector);
    // Reusing one control per selector models the static dashboard elements.
  };
  const context = {document: {querySelector: find, createElement: () => new Control()},
    ResizeObserver: class {observe() {}}, console, setTimeout, clearTimeout, DOMException, AbortSignal, AbortController};
  vm.createContext(context);
  // Load library and integration into one realm, matching browser plain-object and array semantics.
  if (withLibrary) {
    vm.runInContext(librarySource, context);
    vm.runInContext(`
      const installedGraph = cytoscape;
      cytoscape = (options) => {
        // Disable only canvas geometry; retain real collections, events, styles and viewport state.
        const core = installedGraph({...options, container: undefined, headless: true, styleEnabled: true});
        core.layout = () => ({run() {}});
        core.mount = () => core;
        core.unmount = () => core;
        // Expose identity only after geometry has been isolated from the real graph collections.
        testCore = core;
        return core;
      };
      // A fresh page instance is exposed only by the test harness, never by product UI.
      var testCore = null;
    `, context);
  }
  // Display indexing and projection modules execute in the same realm as the pinned graph core.
  for (const name of ["research-graph-model.js", "research-hierarchy.js"]) {
    vm.runInContext(readFileSync(path.join(staticRoot, name), "utf8"), context);
  }
  const renderer = vm.runInContext(source + "\nResearchGraph;", context);
  // Tests inspect the real bounded graph while acting through registered UI event handlers.
  return {renderer, find, core: () => context.testCore ?? null};
}

// Pair ordinals and counters deliberately stay strings through selection and evidence navigation.
function pair(id, a = "A", b = "B") {
  return {row_id: id, signer_a: a, signer_b: b, shared_mints: "2",
    a_first: "1", b_first: "0", same_transaction: "1"};
}

// A graph click must resolve to exactly the same immutable pair ordinal as table drilldown.
test("node and edge selection preserve exact pair evidence and complete addresses", (context) => {
  const h = harness();
  context.after(() => h.renderer.clear());
  const opened = [];
  h.renderer.render([pair("9007199254740993"), pair("8", "C", "D")], (id) => opened.push(id));
  // Inspect the complete page before exercising its selection actions.
  const core = h.core();
  // The loaded page is the sole source of nodes, edges and selection relationships.
  assert.equal(core.nodes().length, 4);
  assert.equal(core.edges().length, 2);
  core.getElementById("wallet:A").emit("tap");
  assert.equal(h.find("#graph-wallet").value, "A");
  assert.equal(core.getElementById("wallet:C").hasClass("muted"), true);
  // Neighbour navigation uses the same edge path as a direct canvas tap.
  h.find("#graph-selection").children.find((child) => child.className === "graph-neighbours").children[0].fire("click");
  h.find("#graph-selection").children.at(-1).fire("click");
  assert.deepEqual(opened, ["9007199254740993"]);
  core.getElementById("pair:8").emit("tap");
  // No Number conversion may round an artifact-local ordinal used by an evidence request.
  h.find("#graph-selection").children.at(-1).fire("click");
  assert.deepEqual(opened, ["9007199254740993", "8"]);
  h.renderer.clear();
});

// Native keyboard selection and pointer selection highlight the same current-page neighbours.
test("keyboard selection, reset and zoom clamps share the current renderer", (context) => {
  const h = harness();
  context.after(() => h.renderer.clear());
  h.renderer.render([pair("0"), pair("1", "B", "C")], () => {});
  h.find("#graph-wallet").value = "B";
  // A native change event is the keyboard selection boundary.
  h.find("#graph-wallet").fire("change");
  // Reset removes both native-select state and every muted graph element.
  assert.equal(h.core().getElementById("wallet:B").selected(), true);
  h.find("#graph-clear").fire("click");
  assert.equal(h.core().elements(":selected").length, 0);
  assert.equal(h.find("#graph-wallet").value, "");
  // Repeated button actions cannot exceed either declared viewport zoom bound.
  for (let index = 0; index < 80; index++) h.find("#graph-zoom-in").fire("click");
  assert.equal(h.core().zoom(), 4);
  for (let index = 0; index < 80; index++) h.find("#graph-zoom-out").fire("click");
  // The lower bound is reached after repeated zoom-out requests.
  assert.equal(h.core().zoom(), 0.15);
  h.renderer.clear();
});

// Page replacement and empty pages release the old instance and its address/evidence UI.
test("page replacement destroys old graphs and clears stale selections", (context) => {
  const h = harness();
  context.after(() => h.renderer.clear());
  h.renderer.render([pair("0")], () => {});
  const old = h.core();
  // Select old evidence before replacing the page, so stale selection would be observable.
  old.getElementById("pair:0").emit("tap");
  // The new page cannot retain a node, pair or selectable option from its predecessor.
  h.renderer.render([pair("25", "C", "D")], () => {});
  assert.equal(old.destroyed(), true);
  assert.equal(h.core().getElementById("wallet:A").length, 0);
  assert.deepEqual(h.find("#graph-wallet").children.map((node) => node.value), ["", "C", "D"]);
  const current = h.core();
  // A valid empty page carries an explicit empty state, not a stale network of prior pairs.
  h.renderer.render([], () => {});
  assert.equal(current.destroyed(), true);
  assert.match(h.find("#graph-status").textContent, /Граф пуст/);
  assert.equal(h.find("#graph-wallet").disabled, true);
});

// Bounds reject oversized input instead of silently sampling it; missing assets leave a clear message.
test("graph input is bounded and library absence is explicit", (context) => {
  const h = harness();
  context.after(() => h.renderer.clear());
  h.renderer.render(Array.from({length: 26}, (_, index) => pair(String(index))), () => {});
  assert.equal(h.core(), null);
  // Oversize rejection names the limit instead of presenting a sampled graph.
  assert.match(h.find("#graph-status").textContent, /превышен лимит/);
  // A missing renderer must not create synthetic nodes or prevent access to the evidence table.
  const unavailable = harness(false);
  unavailable.renderer.render([pair("0")], () => {});
  assert.match(unavailable.find("#graph-status").textContent, /не загрузилась/);
  assert.equal(unavailable.find("#graph-wallet").disabled, true);
});

// A full graph has no implicit page cap, and its bounded inspector can reach every exact edge.
test("whole graph retains all edges, searches all wallets and paginates high-degree evidence", async (context) => {
  const h = harness();
  context.after(() => h.renderer.clear());
  const rows = Array.from({length: 123}, (_, i) => pair(String(i), "A", `B${String(i).padStart(3, "0")}`));
  const wallets = ["A", ...rows.map((row) => row.signer_b)], opened = [];
  // The actual Cytoscape model is used, including its adjacency and event implementations.
  await h.renderer.renderWhole({rows, wallets}, (id) => opened.push(id), new AbortController().signal, () => {});
  assert.equal(h.core().nodes().length, 1);
  assert.equal(h.core().edges().length, 0);
  assert.match(h.find("#graph-view-status").textContent, /123 пар внутри \+ 0 между/);
  h.find("#graph-search").value = "B122";
  // Search remains global even while the overview contains only group nodes.
  h.find("#graph-search").fire("input");
  assert.deepEqual(h.find("#graph-wallet").children.map((option) => option.value), ["", "B122"]);
  // The last wallet and pair are outside both the first 25 table rows and first 100 search suggestions.
  h.find("#graph-wallet").value = "B122";
  await h.find("#graph-wallet").fire("change");
  assert.equal(h.core().getElementById("wallet:B122").selected(), true);
  h.find("#graph-wallet").value = "A";
  await h.find("#graph-wallet").fire("change");
  // DOM cardinality is checked separately from the complete graph degree.
  const neighbourButtons = () => h.find("#graph-selection").children.find((node) => node.className === "graph-neighbours").children;
  // All 123 incident edges are represented, while at most 50 neighbour actions are live.
  assert.equal(neighbourButtons().length, 50);
  h.find("#graph-selection").children.at(-1).children[1].fire("click");
  h.find("#graph-selection").children.at(-1).children[1].fire("click");
  assert.equal(neighbourButtons().length, 23);
  await neighbourButtons().at(-1).fire("click");
  // Evidence navigation preserves the result-local row ordinal despite independent inspector pagination.
  h.find("#graph-selection").children.at(-1).fire("click");
  assert.deepEqual(opened, ["122"]);
  await h.find("#graph-clear").fire("click");
  // Inspector reset preserves the complete wallet neighbourhood at level three.
  assert.equal(h.core().edges().length, 123);
  await h.find("#graph-overview").fire("click");
  assert.equal(h.core().nodes().length, 1);
});

// A stale asynchronous build must never overwrite the page graph that replaced it during a yield.
test("whole construction honours cancellation and scope replacement", async (context) => {
  const h = harness();
  context.after(() => h.renderer.clear());
  const controller = new AbortController();
  // An existing page makes early retirement observable before full construction begins.
  h.renderer.render([pair("old")], () => {});
  const old = h.core();
  // The new full-model build retires the prior page before yielding.
  const building = h.renderer.renderWhole({rows: [pair("0")], wallets: ["A", "B"]}, () => {}, controller.signal, () => {});
  // Hold the prior page instance so destruction is verified independently of the new graph.
  // Switching to a normal page destroys the in-progress headless instance before the next batch.
  controller.abort();
  h.renderer.render([pair("25", "C", "D")], () => {});
  await assert.rejects(building, {name: "AbortError"});
  assert.equal(old.destroyed(), true);
  assert.equal(h.core().edges()[0].data("row").row_id, "25");
  // Accepted whole-result bounds do not weaken explicit oversize rejection.
  await assert.rejects(h.renderer.renderWhole({rows: [pair("0")], wallets: Array(5001).fill("A")}, () => {}, controller.signal, () => {}), /лимит/);
});

// A newer focus request or scope replacement retires a yielded display update without stale remounts.
test("whole selection races preserve the latest focus and release replaced instances", async (context) => {
  const h = harness();
  context.after(() => h.renderer.clear());
  const rows = Array.from({length: 80}, (_, i) => pair(String(i), "A", `B${i}`));
  await h.renderer.renderWhole({rows, wallets: ["A", ...rows.map((row) => row.signer_b)]}, () => {}, new AbortController().signal, () => {});
  // Trigger two overlapping focus changes through keyboard controls while the first awaits a style batch.
  h.find("#graph-wallet").value = "B0";
  const first = h.find("#graph-wallet").fire("change");
  h.find("#graph-wallet").value = "B79";
  const last = h.find("#graph-wallet").fire("change");
  await Promise.all([first, last]);
  // Only the final wallet's full incident edge remains visible, without removing any stored edge.
  assert.equal(h.core().getElementById("wallet:B79").selected(), true);
  assert.equal(h.core().edges().filter((edge) => !edge.hasClass("muted")).length, 1);
  assert.equal(h.core().edges().length, 1);
  h.find("#graph-wallet").value = "A";
  await h.find("#graph-wallet").fire("change");
  // Returning to the hub reconstructs all retained pairs, without reloading or sampling.
  assert.equal(h.core().edges().length, 80);
  const old = h.core();
  const clearing = h.find("#graph-overview").fire("click");
  // Replacing the scope during reset cannot reattach the discarded whole model afterward.
  h.renderer.render([pair("25", "C", "D")], () => {});
  await clearing;
  assert.equal(old.destroyed(), true);
  assert.equal(h.core().edges()[0].data("row").row_id, "25");
});

// Groups, cross-group evidence and neighbourhood expansion preserve the same independently known pairs.
test("three levels expose every internal and crossing pair with reversible navigation", async (context) => {
  const h = harness(), opened = [];
  context.after(() => h.renderer.clear());
  const rows = [["A", "B"], ["A", "C"], ["B", "C"], ["C", "D"], ["D", "E"], ["D", "F"], ["E", "F"]]
    .map(([a, b], index) => ({...pair(String(index), a, b), shared_mints: index === 3 ? "1" : "10"}));
  // Two strong triangles are joined by exactly pair 3; their overview must have one aggregate edge.
  await h.renderer.renderWhole({rows, wallets: ["A", "B", "C", "D", "E", "F"]}, (id) => opened.push(id), new AbortController().signal, () => {});
  assert.equal(h.core().nodes().length, 2); assert.equal(h.core().edges().length, 1);
  h.core().edges()[0].emit("tap");
  const list = () => h.find("#graph-selection").children.find((item) => item.className === "graph-neighbours");
  await list().children[0].fire("click");
  // An aggregate drilldown points to an exact pair, not a synthetic group evidence identifier.
  h.find("#graph-selection").children.at(-1).fire("click");
  assert.deepEqual(opened, ["3"]);
  await h.find("#graph-overview").fire("click");
  await list().children[0].fire("click");
  assert.equal(h.core().nodes().length, 3); assert.equal(h.core().edges().length, 3);
  // The group inspector explicitly includes the one pair crossing its boundary.
  assert.match(h.find("#graph-view-status").textContent, /3 внутренних пар/);
  assert.match(h.find("#graph-selection").children[1].textContent, /1 пар с другими группами/);
  h.find("#graph-wallet").value = "C";
  await h.find("#graph-wallet").fire("change");
  assert.equal(h.core().nodes().length, 4); assert.equal(h.core().edges().length, 3);
  // Enabling neighbour pairs adds A–B; toggling back removes only that explicitly optional edge.
  h.find("#graph-neighbour-links").checked = true;
  // The checkbox requests a complete new projection, not an in-place sampled edit.
  await h.find("#graph-neighbour-links").fire("change");
  assert.equal(h.core().edges().length, 4);
  h.find("#graph-neighbour-links").checked = false;
  // The checkbox requests a complete new projection, not an in-place sampled edit.
  await h.find("#graph-neighbour-links").fire("change");
  assert.equal(h.core().edges().length, 3);
  // The group breadcrumb returns to all three internal pairs, then overview still covers both groups.
  await h.find("#graph-parent-group").fire("click");
  assert.equal(h.core().nodes().length, 3);
  await h.find("#graph-overview").fire("click");
  assert.equal(h.core().nodes().length, 2);
});

// A cancelled local projection releases its canvas but retains the verified full model for navigation.
test("projection cancellation can recover without a second download and stale evidence is inert", async (context) => {
  const h = harness(), opened = [];
  context.after(() => h.renderer.clear());
  await h.renderer.renderWhole({rows: [pair("0")], wallets: ["A", "B"]}, (id) => opened.push(id), new AbortController().signal, () => {});
  h.find("#graph-wallet").value = "A";
  // Capture the awaited navigation independently of the cancellation control.
  const pending = h.find("#graph-wallet").fire("change");
  // Cancel while neighbourhood construction is awaiting its next bounded checkpoint.
  h.find("#graph-view-cancel").fire("click");
  await pending;
  assert.match(h.find("#graph-view-status").textContent, /отменено/);
  // A subsequent navigation uses retained exact data and never republishes the cancelled canvas.
  await h.find("#graph-overview").fire("click");
  await h.find("#graph-wallet").fire("change");
  h.core().edges()[0].emit("tap");
  const stale = h.find("#graph-selection").children.at(-1);
  h.renderer.render([pair("25", "C", "D")], () => {});
  // Retired inspector callbacks cannot request purchases against a newly opened artifact or scope.
  stale.fire("click");
  assert.deepEqual(opened, []);
});
