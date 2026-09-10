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
  fire(name) {this.events[name]({target: this});}
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
    ResizeObserver: class {observe() {}}, console, setTimeout, clearTimeout};
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
        testCore = core;
        return core;
      };
      // A fresh page instance is exposed only by the test harness, never by product UI.
      var testCore = null;
    `, context);
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
  h.find("#graph-selection").children.at(-1).children[0].fire("click");
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
