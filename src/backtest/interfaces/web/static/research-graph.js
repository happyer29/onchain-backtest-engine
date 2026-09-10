"use strict";

// This renderer receives checked display rows; it never fetches or calculates research data.
const ResearchGraph = (() => {
  const find = (selector) => document.querySelector(selector);
  let graph = null;
  let openEvidence = null;
  let whole = false, walletsInGraph = [];
  // In-flight display selection cannot remount a graph after replacement.
  let selectionVersion = 0;
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

  // Dense whole-result views avoid per-edge labels and expensive curved-edge geometry.
  const wholeStyles = [...styles,
    {selector: "node", style: {label: "", width: 18, height: 18}},
    {selector: "edge", style: {label: "", width: 1, "curve-style": "straight", "overlay-opacity": 0}},
    {selector: ".muted", style: {display: "none"}}
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

  // Large selection changes yield between style batches without redrawing the dense graph each time.
  async function focusWhole(keep, selected) {
    const owned = graph, version = ++selectionVersion;
    const hide = owned.elements().difference(keep).filter((item) => !item.hasClass("muted"));
    const show = keep.filter((item) => item.hasClass("muted"));
    owned.elements(":selected").unselect();
    // Detaching the canvas avoids a full-edge repaint after every bounded styling batch.
    const detach = hide.length + show.length > 1000 || !owned.container();
    if (detach) owned.unmount();
    find("#graph-selection-status").textContent = "Обновляем выделение…";
    // Apply only changed visibility, retaining unchanged neighbours during subsequent selections.
    for (const [items, muted] of [[hide, true], [show, false]]) {
      for (let index = 0; index < items.length; index += 1000) {
        await new Promise((resolve) => setTimeout(resolve, 0));
        // Mode changes and newer selections may retire this operation during any yield.
        if (graph !== owned || version !== selectionVersion) return;
        owned.batch(() => items.slice(index, index + 1000).toggleClass("muted", muted));
      }
    }
    if (graph !== owned || version !== selectionVersion) return;
    // Mount only the latest complete selection; the retained edge model is never sampled or deleted.
    if (detach) owned.mount(find("#graph"));
    if (selected) selected.select();
    owned.fit(keep.nodes(), 48);
    find("#graph-selection-status").textContent = selected ? "Видны все связи выбранного элемента. Остальные скрыты до снятия выделения." : "Виден весь загруженный граф.";
  }

  // Small-page selection stays synchronous, while the complete model uses cancellable display batches.
  function focus(keep, selected = null) {
    if (whole) return focusWhole(keep, selected);
    graph.elements().unselect().removeClass("muted");
    graph.elements().difference(keep).addClass("muted");
    // Selection keeps exact pair/node identity; muted neighbours remain retained in the model.
    if (selected) selected.select();
  }

  // Keyboard and pointer actions use the same complete adjacency set in either display scope.
  function resetSelection() {
    find("#graph-wallet").value = "";
    find("#graph-selection").replaceChildren(textNode("p", "Выбери узел или связь на графе.", "hint"));
    if (graph) return focus(graph.elements());
  }

  // Destroy the previous renderer before replacing its scope or exact artifact.
  function clear(message = "") {
    selectionVersion++;
    if (graph) graph.destroy();
    graph = null;
    // Discard the prior scope before exposing any new address or progress controls.
    openEvidence = null;
    whole = false;
    walletsInGraph = [];
    // Searches never retain addresses from a discarded display scope.
    find("#graph-search").value = "";
    find("#graph-search").disabled = true;
    find("#graph-search-status").textContent = "";
    find("#graph-selection-status").textContent = "";
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

  // Evidence remains tied to the exact row ordinal supplied by the active immutable result.
  function showPair(row) {
    const edge = graph.getElementById(`pair:${row.row_id}`);

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
    // Exact evidence becomes available immediately while the canvas updates its display selection.
    return focus(edge.union(edge.connectedNodes()), edge);
  }

  // Inspector pagination limits DOM, while selection includes every incident edge in the loaded scope.
  function neighbourList(wallet, edges, offset) {
    const list = textNode("div", "", "graph-neighbours");
    for (const edge of edges.slice(offset, offset + 50)) {
      const row = edge.data("row");
      const other = row.signer_a === wallet ? row.signer_b : row.signer_a;
      // Exact pair ordinals survive inspector pagination independently of the data table.
      const button = textNode("button", `${other} · общих токенов: ${row.shared_mints}`, "secondary");
      button.addEventListener("click", () => showPair(row));
      list.append(button);
    }
    const more = textNode("div", "", "pagination");
    // Both directions are bounded and expose the exact range rather than silently capping neighbours.
    for (const [label, next] of [["←", offset - 50], ["→", offset + 50]]) {
      const button = textNode("button", label, "secondary");
      button.disabled = next < 0 || next >= edges.length;
      button.addEventListener("click", () => inspectWallet(wallet, edges, next));
      // Pagination controls refer only to this wallet and its current immutable adjacency collection.
      more.append(button);
    }
    // Every neighbour can be reached while no more than fifty action nodes exist at once.
    return [textNode("p", `Соседи ${offset + 1}–${Math.min(offset + 50, edges.length)} из ${edges.length}`, "hint"), list, more];
  }

  // The inspector labels its universe explicitly, including when the canvas is focused on one wallet.
  function inspectWallet(wallet, edges, offset = 0) {
    find("#graph-selection").replaceChildren(textNode("h4", "Подписант"),
      textNode("p", wallet, "wallet-address"),
      textNode("p", `Связей ${whole ? "во всём результате" : "на этой странице"}: ${edges.length}`),
      // The range indicator distinguishes the inspector page from the wallet’s complete degree.
      ...neighbourList(wallet, edges, offset));
  }

  // Whole-result focus hides unrelated elements only until selection is cleared; no data is removed.
  function showWallet(wallet) {
    if (!graph || !wallet) {resetSelection(); return;}
    const node = graph.getElementById(`wallet:${wallet}`);
    if (!node.length) return;
    find("#graph-wallet").value = wallet;
    // The original pair data stays in the graph, while the bounded inspector merely references it.
    inspectWallet(wallet, node.connectedEdges());
    return focus(node.closedNeighborhood(), node);
  }

  // Search scans at most 5000 local addresses; only a hundred matching options enter the DOM.
  function searchWallets() {
    const query = find("#graph-search").value.trim();
    const matches = walletsInGraph.filter((wallet) => wallet.includes(query));
    const options = [textNode("option", "Выбери кошелёк…")];
    options[0].value = "";
    // A visible count distinguishes the bounded suggestion list from the complete graph and search.
    for (const wallet of matches.slice(0, 100)) {
      const option = textNode("option", wallet);
      option.value = wallet;
      options.push(option);
    }
    // A new query replaces suggestions without changing the graph or analysis parameters.
    find("#graph-wallet").replaceChildren(...options);
    // Substring matching is case-sensitive because public-key identity is case-sensitive.
    find("#graph-search-status").textContent = matches.length > 100
      ? `Найдено ${matches.length}. В списке первые 100; уточни адрес. Регистр учитывается.`
      : `Найдено кошельков: ${matches.length}. Регистр учитывается.`;
  }

  // Starting from a circle avoids overlapping initial coordinates; layout is presentation only.
  function arrange() {
    if (!graph) return;
    if (whole) {
      // A fixed grid is O(wallets), so no force iterations scale with the full edge set.
      graph.nodes().layout({name: "grid", padding: 48, animate: false, spacingFactor: 1.5}).run();
      graph.fit(graph.nodes(), 48);
      return;
    }
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
    // Populate accessible search only after every page element is present.
    walletsInGraph = wallets;
    searchWallets();
    find("#graph-search").disabled = false;
    find("#graph-wallet").disabled = false;
    find("#graph-clear").disabled = false;
    // Controls are enabled only after the renderer and exact-page evidence callback are installed.
    for (const button of find("#graph-controls").querySelectorAll("button")) button.disabled = false;
    find("#graph-status").textContent = `На странице: ${rows.length} пар · ${wallets.length} кошельков. Граф совпадает с таблицей ниже.`;
    arrange();
    find("#graph-zoom").textContent = `${Math.round(graph.zoom() * 100)}%`;
  }

  // Build a checked whole result without attaching partially loaded data to a visible canvas.
  async function renderWhole(data, onEvidence, signal, progress) {
    clear();
    if (typeof cytoscape !== "function") throw new Error("Библиотека графа не загрузилась. Обнови страницу.");
    if (data.rows.length > 200000 || data.wallets.length > 5000) throw new Error("Превышен лимит полного графа.");
    whole = true;
    // A verified empty result needs no canvas or synthetic placeholder nodes.
    if (!data.rows.length) {
      find("#graph-status").textContent = "Весь результат: 0 из 0 связей · 0 кошельков. Граф пуст.";
      return;
    }
    // A headless instance retains the graph in bounded chunks and mounts only after complete admission.
    const owned = cytoscape({headless: true, styleEnabled: true, elements: [], style: wholeStyles,
      layout: {name: "preset"}, minZoom: 0.005, maxZoom: 4, pixelRatio: 1,
      boxSelectionEnabled: false, textureOnViewport: true});
    graph = owned;
    owned.add(elements([], data.wallets));
    // Yield before each finite batch so cancellation and replacement can retire this exact instance.
    for (let index = 0; index < data.rows.length; index += 1000) {
      await new Promise((resolve) => setTimeout(resolve, 0));
      signal.throwIfAborted();
      if (graph !== owned) throw new DOMException("Graph replaced", "AbortError");
      owned.add(elements(data.rows.slice(index, index + 1000), []));
      // Progress concerns construction, independently of the already verified download count.
      progress(Math.min(index + 1000, data.rows.length), data.rows.length);
    }
    signal.throwIfAborted();
    if (graph !== owned) throw new DOMException("Graph replaced", "AbortError");
    owned.mount(find("#graph"));
    // Only a complete mounted instance gets live controls and an exact-result evidence callback.
    openEvidence = onEvidence;
    walletsInGraph = data.wallets;
    owned.on("tap", "node", (event) => showWallet(event.target.data("wallet")));
    owned.on("tap", "edge", (event) => showPair(event.target.data("row")));
    owned.on("tap", (event) => {if (event.target === owned) resetSelection();});
    // Zoom state is visible for pointer, touch and keyboard interactions alike.
    owned.on("zoom", () => {find("#graph-zoom").textContent = `${Math.round(owned.zoom() * 100)}%`;});
    searchWallets();
    find("#graph-search").disabled = false;
    find("#graph-wallet").disabled = false;
    find("#graph-clear").disabled = false;
    // The bounded grid positions all nodes; edges remain the exact full relationship set.
    for (const button of find("#graph-controls").querySelectorAll("button")) button.disabled = false;
    arrange();
    signal.throwIfAborted();
    find("#graph-status").textContent = `Весь результат: ${data.rows.length} из ${data.rows.length} связей · ${data.wallets.length} кошельков. Загрузка завершена, без усечения.`;
  }

  // Clamp explicit zoom actions and keep the viewport centre stable.
  function zoom(factor) {
    if (!graph) return;
    const level = Math.max(graph.minZoom(), Math.min(graph.maxZoom(), graph.zoom() * factor));
    graph.zoom({level, renderedPosition: {x: graph.width() / 2, y: graph.height() / 2}});
  }

  // Bind controls once; each action uses the currently owned bounded renderer instance.
  find("#graph-zoom-in").addEventListener("click", () => zoom(1.25));
  find("#graph-zoom-out").addEventListener("click", () => zoom(0.8));
  find("#graph-fit").addEventListener("click", () => {if (graph) graph.fit(whole ? graph.nodes(":visible") : undefined, 48);});
  find("#graph-reset").addEventListener("click", arrange);
  find("#graph-wallet").addEventListener("change", (event) => showWallet(event.target.value));
  // Clearing or expanding is a reversible display action, never a new analysis request.
  find("#graph-search").addEventListener("input", searchWallets);
  find("#graph-clear").addEventListener("click", resetSelection);
  find("#graph-expand").addEventListener("click", () => {
    const expanded = find("#graph-panel").classList.toggle("graph-expanded");
    // Announce expansion independently of the selected analytical scope.
    find("#graph-expand").setAttribute("aria-pressed", String(expanded));
    find("#graph-expand").textContent = expanded ? "Свернуть граф" : "Развернуть граф";
    // Fit after the CSS size change so long addresses and controls remain on the page.
    if (graph) {graph.resize(); graph.fit(whole ? graph.nodes(":visible") : undefined, 48);}
  });
  const observer = new ResizeObserver(() => {if (graph) graph.resize();});
  observer.observe(find("#graph"));
  // No DOM reference or selected pair from a previous page survives clear().
  return {render, renderWhole, clear};
})();
