"use strict";

// This renderer receives one verified API page; it never fetches or calculates research data.
const ResearchGraph = (() => {
  const find = (selector) => document.querySelector(selector);
  let graph = null;
  let openEvidence = null;
  // Node positions and edge width are display settings, excluded from analytical identity.
  const styles = [
    {selector: "node", style: {"background-color": "#9de0cb", width: 24, height: 24,
      label: "data(label)", color: "#e6edf5", "font-size": 11, "text-valign": "top", "text-margin-y": -9}},
    {selector: "edge", style: {width: "data(width)", "line-color": "#568d83", "curve-style": "bezier",
      label: "data(shared)", color: "#c3ded7", "font-size": 10, "text-background-color": "#10171f",
      // Opaque label backgrounds keep exact shared-mint counters readable over crossings.
      "text-background-opacity": 1, "text-background-padding": "3px", "overlay-padding": "10px"}},
    {selector: ".muted", style: {opacity: 0.16}},
    {selector: ":selected", style: {"background-color": "#f1ce79", "line-color": "#f1ce79",
      "border-color": "#fff1c7", "border-width": 2, color: "#fff1c7"}}
  ];

  // Public addresses and all evidence labels are text, never markup or selector expressions.
  function textNode(tag, text, className = "") {
    const node = document.createElement(tag);
    node.textContent = text;
    node.className = className;
    // Keep the public-key text inert even when it contains markup-like characters.
    return node;
  }

  // Prefixing identifiers separates public addresses from result-local pair ordinals.
  function elements(rows, wallets) {
    const nodes = wallets.map((wallet) => ({data: {id: `wallet:${wallet}`, wallet,
      label: `${wallet.slice(0, 5)}…${wallet.slice(-4)}`}}));
    const edges = rows.map((row) => ({data: {id: `pair:${row.row_id}`, source: `wallet:${row.signer_a}`,
      target: `wallet:${row.signer_b}`, shared: row.shared_mints, row,
      // Only bounded counters pass through Number, solely for a logarithmic display width.
      width: 1 + Math.log2(1 + Number(row.shared_mints))}}));
    return [...nodes, ...edges];
  }

  // Keyboard and pointer actions use this same bounded selection state.
  function resetSelection() {
    if (graph) graph.elements().unselect().removeClass("muted");
    find("#graph-wallet").value = "";
    find("#graph-selection").replaceChildren(textNode("p", "Выбери узел или связь на графе.", "hint"));
  }

  // Destroy the previous renderer before replacing the artifact, table or page.
  function clear(message = "") {
    if (graph) graph.destroy();
    graph = null;
    openEvidence = null;
    find("#graph").replaceChildren();
    // Disabling old controls prevents stale pair callbacks while another request is in flight.
    for (const button of find("#graph-controls").querySelectorAll("button")) button.disabled = true;
    find("#graph-wallet").replaceChildren(textNode("option", "Выбери кошелёк…"));
    find("#graph-wallet").firstElementChild.value = "";
    find("#graph-wallet").disabled = true;
    find("#graph-clear").disabled = true;
    // Counters describe only a completed current page, never the previous graph during loading.
    find("#graph-zoom").textContent = "—";
    find("#graph-status").textContent = message;
    resetSelection();
  }

  // Evidence remains tied to the exact row ordinal supplied by the active result page.
  function showPair(row) {
    const edge = graph.getElementById(`pair:${row.row_id}`);
    graph.elements().unselect().removeClass("muted");
    graph.elements().difference(edge.union(edge.connectedNodes())).addClass("muted");
    edge.select();
    // Full signer identities are displayed without treating A or B as a trading leader.
    find("#graph-wallet").value = "";
    const button = textNode("button", "Открыть исходные покупки →");
    button.addEventListener("click", () => openEvidence(row.row_id));
    find("#graph-selection").replaceChildren(textNode("h4", `Пара ${row.row_id}`),
      textNode("p", row.signer_a, "wallet-address"), textNode("p", "↔"),
      // Counts and roles retain their server-provided meanings and exact string representation.
      textNode("p", row.signer_b, "wallet-address"),
      textNode("p", `Общих токенов: ${row.shared_mints}`),
      textNode("p", `A раньше: ${row.a_first} · B раньше: ${row.b_first} · одна транзакция: ${row.same_transaction}`, "hint"),
      button);
  }

  // Neighbour highlighting is explicitly limited to relationships present on this page.
  function showWallet(wallet) {
    if (!graph || !wallet) {resetSelection(); return;}
    const node = graph.getElementById(`wallet:${wallet}`);
    graph.elements().unselect().removeClass("muted");
    graph.elements().difference(node.closedNeighborhood()).addClass("muted");
    // Selecting an address does not change analysis filters or request any additional pairs.
    node.select();
    find("#graph-wallet").value = wallet;
    const edges = node.connectedEdges();
    const list = textNode("div", "", "graph-neighbours");
    for (const edge of edges) {
      // Each neighbour action selects the same exact pair as clicking its visible canvas edge.
      const row = edge.data("row");
      const other = row.signer_a === wallet ? row.signer_b : row.signer_a;
      const button = textNode("button", `${other} · общих токенов: ${row.shared_mints}`, "secondary");
      button.addEventListener("click", () => showPair(row));
      // Append only the bounded current-page neighbour action.
      list.append(button);
    }
    // The local relationship count must not look like the wallet's degree across the entire result.
    find("#graph-selection").replaceChildren(textNode("h4", "Подписант"),
      textNode("p", wallet, "wallet-address"), textNode("p", `Связей на этой странице: ${edges.length}`), list);
  }

  // Starting from a circle avoids overlapping initial coordinates; layout is presentation only.
  function arrange() {
    if (!graph) return;
    graph.layout({name: "circle", padding: 48, animate: false}).run();
    // The finite force layout spreads neighbours without introducing a clustering calculation.
    graph.layout({name: "cose", randomize: false, animate: false, padding: 48,
      nodeRepulsion: () => 9000, idealEdgeLength: () => 100, numIter: 400}).run();
  }

  // Only a successfully loaded, bounded pair page can create interactive canvas elements.
  function render(rows, onEvidence) {
    clear();
    if (!rows.length) {find("#graph-status").textContent = "На этой странице нет пар. Граф пуст."; return;}
    if (rows.length > 25) {find("#graph-status").textContent = "Граф не построен: превышен лимит 25 пар."; return;}
    if (typeof cytoscape !== "function") {
      // The evidence table remains available when the separately packaged library cannot load.
      find("#graph-status").textContent = "Библиотека графа не загрузилась. Обнови страницу; покупки доступны в таблице ниже.";
      return;
    }
    const wallets = [...new Set(rows.flatMap((row) => [row.signer_a, row.signer_b]))].sort();
    // Rendering uses no network plugins, analytics, HTML labels or unbounded background layout.
    graph = cytoscape({container: find("#graph"), elements: elements(rows, wallets), style: styles,
      layout: {name: "preset"}, minZoom: 0.15, maxZoom: 4, pixelRatio: 1, boxSelectionEnabled: false});
    openEvidence = onEvidence;
    graph.on("tap", "node", (event) => showWallet(event.target.data("wallet")));
    graph.on("tap", "edge", (event) => showPair(event.target.data("row")));
    // Background taps reset highlighting without changing the current page or data selection.
    graph.on("tap", (event) => {if (event.target === graph) resetSelection();});
    graph.on("zoom", () => {find("#graph-zoom").textContent = `${Math.round(graph.zoom() * 100)}%`;});
    for (const wallet of wallets) {
      const option = textNode("option", wallet);
      option.value = wallet;
      // The native select exposes complete addresses to keyboard and assistive-technology users.
      find("#graph-wallet").append(option);
    }
    find("#graph-wallet").disabled = false;
    find("#graph-clear").disabled = false;
    // Controls are enabled only after the renderer and exact-page evidence callback are installed.
    for (const button of find("#graph-controls").querySelectorAll("button")) button.disabled = false;
    find("#graph-status").textContent = `На странице: ${rows.length} пар · ${wallets.length} кошельков. Граф совпадает с таблицей ниже.`;
    arrange();
    find("#graph-zoom").textContent = `${Math.round(graph.zoom() * 100)}%`;
  }

  // Clamp explicit zoom actions and keep the viewport centre stable.
  function zoom(factor) {
    if (!graph) return;
    const level = Math.max(graph.minZoom(), Math.min(graph.maxZoom(), graph.zoom() * factor));
    graph.zoom({level, renderedPosition: {x: graph.width() / 2, y: graph.height() / 2}});
  }

  // Bind controls once; every later page replaces only the bounded renderer instance.
  find("#graph-zoom-in").addEventListener("click", () => zoom(1.25));
  find("#graph-zoom-out").addEventListener("click", () => zoom(0.8));
  find("#graph-fit").addEventListener("click", () => {if (graph) graph.fit(undefined, 48);});
  find("#graph-reset").addEventListener("click", arrange);
  find("#graph-wallet").addEventListener("change", (event) => showWallet(event.target.value));
  // Clearing or expanding is a reversible display action, never a new analysis request.
  find("#graph-clear").addEventListener("click", resetSelection);
  find("#graph-expand").addEventListener("click", () => {
    const expanded = find("#graph-panel").classList.toggle("graph-expanded");
    find("#graph-expand").setAttribute("aria-pressed", String(expanded));
    find("#graph-expand").textContent = expanded ? "Свернуть граф" : "Развернуть граф";
    // Fit after the CSS size change so long addresses and controls remain on the page.
    if (graph) {graph.resize(); graph.fit(undefined, 48);}
  });
  const observer = new ResizeObserver(() => {if (graph) graph.resize();});
  observer.observe(find("#graph"));
  // No DOM reference or selected pair from a previous page survives clear().
  return {render, clear};
})();
