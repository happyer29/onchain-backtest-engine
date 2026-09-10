"use strict";

// Three reversible projections share one complete checked model and at most one Cytoscape instance.
const ResearchHierarchy = (() => {
  const find = (selector) => document.querySelector(selector);
  const colours = ["#9de0cb", "#f1ce79", "#84b6f4", "#dc9cdb", "#efac82", "#9dc78d", "#ada5f1", "#7fd0df"];
  let active = null;
  // Group colours are navigational hints, never unique owner identities or statistical classes.
  const colour = (group) => colours[group % colours.length];
  const style = [
    {selector: "node", style: {"background-color": "data(colour)", width: "data(size)", height: "data(size)",
      label: "data(label)", color: "#e6edf5", "font-size": 11, "text-valign": "bottom", "text-margin-y": 8,
      "text-wrap": "wrap", "text-background-color": "#10171f", "text-background-opacity": 0.85}},
    // Suppressing dense pair labels leaves their exact counts in the inspector on demand.
    {selector: "edge", style: {width: "data(width)", "line-color": "#568d83", "curve-style": "straight", opacity: 0.5}},
    {selector: "node.centre", style: {"border-width": 4, "border-color": "#fff1c7", width: 38, height: 38}},
    {selector: ":selected", style: {"line-color": "#f1ce79", "border-color": "#fff1c7", "border-width": 3, opacity: 1}}
  ];

  // Every identity is inserted as inert text, including full addresses and source-provided counts.
  function text(tag, value, className = "") {
    const element = document.createElement(tag);
    element.textContent = value;
    // Only CSS classes are supplied by this module; public text never becomes markup.
    element.className = className;
    return element;
  }

  // Inspector lists have fifty controls per page while their backing arrays remain complete.
  function paged(title, items, itemButton, render, offset = 0) {
    const list = text("div", "", "graph-neighbours"), controls = text("div", "", "pagination");
    items.slice(offset, offset + 50).forEach((item) => list.append(itemButton(item)));
    const caption = items.length ? `${offset + 1}–${Math.min(offset + 50, items.length)} из ${items.length}` : "0";
    // Both directions remain available; a high-degree wallet or large group is never sampled.
    for (const [label, next] of [["←", offset - 50], ["→", offset + 50]]) {
      const button = text("button", label, "secondary");
      button.disabled = next < 0 || next >= items.length;
      // The next page is local to this list, independent of API and table cursors.
      button.addEventListener("click", () => render(next));
      controls.append(button);
    }
    return [text("p", `${title}: ${caption}`, "hint"), list, controls];
  }

  // Repeated creates replace ownership; static toolbar handlers below always consult the active view.
  function create(model, onEvidence) {
    let graph = null, pending = null, version = 0, controller = null;
    let current = {kind: "overview", key: null}, disposed = false;
    let projection = null;
    // Only the latest projection may mount its renderer, modify details or resolve a drilldown action.
    const live = () => !disposed && active === api;
    const groupName = (id) => `Группа ${id + 1}`;
    const button = (label, callback) => {
      // Capture the projection revision so detached inspector buttons become inert.
      const item = text("button", label, "secondary"), revision = version;
      item.addEventListener("click", () => {if (live() && revision === version) return callback();});
      return item;
    };

    // Exact pair rows are reused from the checked result; group aggregates never invent an evidence row.
    function pairDetails(index) {
      const row = model.rows[index];
      if (graph) {graph.elements().unselect(); graph.getElementById(`pair:${row.row_id}`).select();}
      find("#graph-selection").replaceChildren(text("h4", `Пара ${row.row_id}`),
        text("p", row.signer_a, "wallet-address"), text("p", "↔"), text("p", row.signer_b, "wallet-address"),
        // Direction retains its observation meaning; it is not interpreted as a leader score.
        text("p", `Общих токенов: ${row.shared_mints}`),
        text("p", `A раньше: ${row.a_first} · B раньше: ${row.b_first} · одна транзакция: ${row.same_transaction}`, "hint"),
        button("Окружение A", () => go("wallet", row.signer_a)), button("Окружение B", () => go("wallet", row.signer_b)),
        button("Открыть исходные покупки →", () => onEvidence(row.row_id)));
    }

    // Crossing and internal lists use the same bounded exact-pair inspector as the canvas edges.
    function pairs(title, indices, offset = 0) {
      const make = (index) => {
        const row = model.rows[index];
        return button(`${row.signer_a} ↔ ${row.signer_b} · ${row.shared_mints} токенов`, () => pairDetails(index));
      };
      // Replacing the inspector bounds live controls without shortening the underlying pair list.
      find("#graph-selection").replaceChildren(text("h4", title),
        ...paged("Пары", indices, make, (next) => pairs(title, indices, next), offset));
    }

    // Both endpoints of an overview edge offer navigation, while every crossing pair remains reachable.
    function crossing(link, offset = 0) {
      pairs(`${groupName(link.a)} ↔ ${groupName(link.b)} · ${link.indices.length} пар`, link.indices, offset);
      find("#graph-selection").append(button(`Открыть ${groupName(link.a)}`, () => go("group", link.a)));
      find("#graph-selection").append(button(`Открыть ${groupName(link.b)}`, () => go("group", link.b)));
    }

    // The overview list exposes every visual group, including tiny and disconnected groups.
    function overviewDetails(offset = 0) {
      const make = (group) => button(`${groupName(group.id)} · ${group.members.length} кошельков · ${group.internal.length} внутренних пар`, () => go("group", group.id));
      find("#graph-selection").replaceChildren(text("h4", "1 / Все группы"),
        // The count and page controls distinguish collapsed overview edges from exact pairs.
        text("p", "Нажми группу, чтобы раскрыть кошельки. Линия между группами объединяет пары кошельков.", "hint"),
        ...paged("Группы", model.groups, make, overviewDetails, offset));
    }

    // A group also offers a keyboard path to every member, without filtering the global search.
    function groupWallets(id, offset = 0) {
      const group = model.groups[id];
      // The list follows canonical membership and opens complete global neighbourhoods.
      const make = (node) => button(model.wallets[node], () => go("wallet", model.wallets[node]));
      find("#graph-selection").replaceChildren(text("h4", `${groupName(id)}: кошельки`),
        ...paged("Кошельки", group.members, make, (next) => groupWallets(id, next), offset));
    }

    // External counts are visible alongside the complete induced group, not silently excluded from it.
    function groupDetails(id, offset = 0) {
      const group = model.groups[id], outside = group.links.reduce((sum, link) => sum + link.indices.length, 0);
      const make = (link) => button(`${groupName(link.a === id ? link.b : link.a)} · ${link.indices.length} пар`, () => crossing(link));
      find("#graph-selection").replaceChildren(text("h4", `2 / ${groupName(id)}`),
        text("p", `${group.members.length} кошельков · ${group.internal.length} внутренних пар · ${outside} пар с другими группами`),
        // Listing internal pairs makes every edge accessible even when canvas lines overlap.
        button("Все кошельки группы", () => groupWallets(id)),
        button("Все внутренние пары", () => pairs(`${groupName(id)}: внутренние пары`, group.internal)),
        ...paged("Связи с группами", group.links, make, (next) => groupDetails(id, next), offset));
    }

    // Native neighbour actions cover the wallet's global incident set, including other visual groups.
    function walletDetails(wallet, offset = 0) {
      const node = model.lookup.get(wallet), edges = model.adjacent[node];
      const make = (index) => {
        // Neighbour rows carry their own exact ordinal and the other wallet’s visual group.
        const other = model.left[index] === node ? model.right[index] : model.left[index];
        return button(`${model.wallets[other]} · ${groupName(model.groupOf[other])} · ${model.rows[index].shared_mints} токенов`, () => pairDetails(index));
      };
      // Full addresses remain readable even when canvas labels are abbreviated.
      find("#graph-selection").replaceChildren(text("h4", "3 / Окружение кошелька"),
        text("p", wallet, "wallet-address"), text("p", `Связей во всём результате: ${edges.length}`),
        ...paged("Соседи", edges, make, (next) => walletDetails(wallet, next), offset));
    }

    // Reset preserves the current navigation level and restores its own complete inspector.
    function reset() {
      if (graph) graph.elements().unselect();
      if (current.kind === "overview") overviewDetails();
      // Group reset restores external links; wallet reset restores global adjacency.
      else if (current.kind === "group") groupDetails(current.key);
      else walletDetails(current.key);
    }

    // View counters explicitly distinguish exact pairs, collapsed edges and optional neighbour pairs.
    function describe() {
      const {kind, key} = current;
      find("#graph-overview").setAttribute("aria-current", kind === "overview" ? "step" : "false");
      find("#graph-parent-group").hidden = kind === "overview";
      const group = kind === "wallet" ? model.groupOf[model.lookup.get(key)] : key;
      // A wallet reached by global search still has a reversible route to its own visual group.
      find("#graph-parent-group").textContent = group === null ? "2 / Группа" : `2 / ${groupName(group)}`;
      find("#graph-parent-group").setAttribute("aria-current", kind === "group" ? "step" : "false");
      find("#graph-wallet-level").hidden = kind !== "wallet";
      find("#graph-neighbour-option").hidden = kind !== "wallet";
      // Overview counters reconcile every original pair exactly once across disjoint categories.
      const summary = kind === "overview"
        ? `${model.groups.length} групп · ${model.wallets.length} кошельков. ${model.internal} пар внутри + ${model.external} между группами = ${model.rows.length}. Линий между группами: ${model.links.length}.`
        : kind === "group" ? `${groupName(key)}: ${projection.members.length} кошельков · все ${projection.indices.length} внутренних пар. Внешние связи доступны справа.`
          : `Все ${projection.incident} связей кошелька · ${projection.members.length - 1} соседей. Между соседями: ${projection.extra}; ${find("#graph-neighbour-links").checked ? "показаны" : "скрыты переключателем"}.`;
      // Replace counters only when the corresponding complete projection is ready.
      find("#graph-view-status").textContent = summary;
      find("#graph-selection-status").textContent = "";
      reset();
    }

    // Overview nodes represent complete groups; group and wallet views represent actual full addresses.
    function nodeElements() {
      if (current.kind === "overview") return model.groups.map((group) => ({data: {
        id: `group:${group.id}`, group: group.id, colour: colour(group.id), size: 24 + Math.log2(1 + group.members.length) * 5,
        label: model.groups.length <= 150 ? `Гр. ${group.id + 1}` : ""}}));
      return projection.members.map((node) => ({data: {id: `wallet:${model.wallets[node]}`, wallet: model.wallets[node],
        // Dense local views use colour and interaction; full labels always remain available in the inspector.
        group: model.groupOf[node], colour: colour(model.groupOf[node]), size: 20,
        label: projection.members.length <= 60 || node === projection.centre ? `${model.wallets[node].slice(0, 5)}…${model.wallets[node].slice(-4)}` : ""},
        classes: node === projection.centre ? "centre" : ""}));
    }

    // Aggregated widths describe pair counts; individual widths describe shared-mint counts.
    function edgeElement(item) {
      if (current.kind === "overview") return {data: {id: `groups:${item.key}`, source: `group:${item.a}`,
        target: `group:${item.b}`, link: item, width: 1 + Math.log2(1 + item.indices.length) / 2}};
      const row = model.rows[item];
      return {data: {id: `pair:${row.row_id}`, source: `wallet:${row.signer_a}`, target: `wallet:${row.signer_b}`,
        // Exact row indices remain local pointers; row_id strings are used unchanged for API evidence.
        index: item, width: projection.indices.length > 1000 ? 1 : 1 + Math.log2(1 + Number(row.shared_mints)) / 2}};
    }

    // Finite geometric rings handle large views without force iterations over thousands of wallets.
    function arrange() {
      if (!graph) return;
      const isWallet = current.kind === "wallet", centre = isWallet ? `wallet:${current.key}` : null;
      const nodes = graph.nodes().toArray().sort((a, b) => {
        // Reserve the centre for the selected wallet before sorting the remaining neighbours.
        if (a.id() === centre) return -1;
        if (b.id() === centre) return 1;
        // Wallet neighbours are adjacent by group; other views put highly connected nodes nearer the centre.
        if (isWallet && a.data("group") !== b.data("group")) return a.data("group") - b.data("group");
        return b.degree() - a.degree() || (a.id() < b.id() ? -1 : 1);
      });
      let offset = 1, ring = 1;
      if (nodes.length) nodes[0].position({x: 0, y: 0});
      // Rings have increasing capacity and fixed spacing; no stochastic layout enters research identity.
      while (offset < nodes.length) {
        const count = Math.min(ring * 12, nodes.length - offset), radius = ring * 120;
        for (let index = 0; index < count; index++) {
          // Equal angular spacing separates adjacent nodes without pretending distance is a metric.
          const angle = index * Math.PI * 2 / count;
          nodes[offset + index].position({x: radius * Math.cos(angle), y: radius * Math.sin(angle)});
        }
        offset += count; ring++;
      }
      // Reuse the already shipped finite force layout only for small group/overview projections.
      if (!isWallet && nodes.length <= 150 && graph.edges().length <= 1000) {
        graph.layout({name: "cose", randomize: false, animate: false, padding: 48,
          nodeRepulsion: () => 18000, idealEdgeLength: () => 160, numIter: 400}).run();
      }
      // Fit includes every projected node after either bounded layout path.
      graph.fit(graph.nodes(), 48);
    }

    // Each navigation has its own finite deadline and retires both stale construction and callbacks.
    async function go(kind, key = null, initialSignal = null) {
      const revision = ++version;
      if (controller) controller.abort();
      const task = new AbortController();
      controller = task;
      // Initial construction also remains under the loader's total 180-second budget.
      const signal = AbortSignal.any([task.signal, AbortSignal.timeout(30000), ...(initialSignal ? [initialSignal] : [])]);
      const owned = () => live() && version === revision;
      if (graph) graph.destroy();
      if (pending) pending.destroy();
      graph = null; pending = null;
      // Remove stale canvas DOM after retiring both mounted and pending instances.
      find("#graph").replaceChildren();
      // Pending counters never describe a partially mounted projection as complete.
      current = {kind, key};
      find("#graph-view-status").textContent = "Строим выбранный уровень…";
      find("#graph-selection").replaceChildren();
      find("#graph-view-cancel").hidden = false;
      let candidate = null;
      // The pending candidate is private until all projection checks have passed.
      try {
        await ResearchGraphModel.checkpoint(signal, owned);
        projection = kind === "wallet" ? await ResearchGraphModel.neighbourhood(model, key, find("#graph-neighbour-links").checked, signal, owned)
          : kind === "group" ? {members: model.groups[key].members, indices: model.groups[key].internal} : null;
        // Construction is headless until every node and exact projected edge has been admitted.
        candidate = cytoscape({headless: true, styleEnabled: true, elements: [], style,
          layout: {name: "preset"}, minZoom: 0.005, maxZoom: 4, pixelRatio: 1, boxSelectionEnabled: false});
        pending = candidate;
        candidate.add(nodeElements());
        const edges = kind === "overview" ? model.links : projection.indices;
        // Yield between bounded edge batches so a new navigation can replace construction.
        for (let offset = 0; offset < edges.length; offset += 1000) {
          await ResearchGraphModel.checkpoint(signal, owned);
          candidate.add(edges.slice(offset, offset + 1000).map(edgeElement));
        }
        // Ownership is rechecked even for empty projections and after the final yielded edge batch.
        signal.throwIfAborted();
        if (!owned()) throw new DOMException("Graph replaced", "AbortError");
        graph = candidate;
        pending = null;
        arrange();
        // A synchronous layout cannot extend the permitted projection lifetime unnoticed.
        signal.throwIfAborted();
        // Mount exactly one completed projection, then install interactions tied to this revision.
        graph.mount(find("#graph"));
        graph.fit(graph.nodes(), 48);
        graph.on("tap", "node", (event) => {
          if (!owned()) return;
          return kind === "overview" ? go("group", event.target.data("group")) : go("wallet", event.target.data("wallet"));
        // Node actions navigate; edge actions inspect exact pairs or their complete aggregate.
        });
        graph.on("tap", "edge", (event) => {
          if (!owned()) return;
          return kind === "overview" ? crossing(event.target.data("link")) : pairDetails(event.target.data("index"));
        });
        // Zoom state stays usable through wheel, buttons and projection replacement.
        graph.on("zoom", () => {if (owned()) find("#graph-zoom").textContent = `${Math.round(graph.zoom() * 100)}%`;});
        describe();
        if (kind === "wallet") graph.getElementById(`wallet:${key}`).select();
        find("#graph-zoom").textContent = `${Math.round(graph.zoom() * 100)}%`;
      // Any failed candidate is destroyed even when a newer navigation already owns the UI.
      } catch (error) {
        if (candidate) candidate.destroy();
        if (pending === candidate) pending = null;
        if (!owned()) return;
        graph = null;
        // Keep the complete model for retry or other navigation; never retain a failed partial canvas.
        find("#graph-view-status").textContent = signal.aborted ? "Построение вида отменено или истекло время. Выбери уровень повторно."
          : "Не удалось построить вид. Выбери уровень повторно.";
        if (initialSignal) throw error;
      // Only the current navigation can retire its cancellation control.
      } finally {
        if (owned()) {controller = null; find("#graph-view-cancel").hidden = true;}
      }
    }

    // Destroy invalidates awaited operations before releasing the current projection and model closure.
    function destroy() {
      disposed = true; version++;
      if (controller) controller.abort();
      if (graph) graph.destroy();
      if (pending) pending.destroy();
      // Clear both renderer references before relinquishing the active controller.
      graph = null; pending = null;
      if (active === api) active = null;
    }
    // Static controls delegate to this single replaceable owner; no handler accumulates across reloads.
    const api = {core: () => graph, go, reset, arrange, destroy, cancel: () => controller?.abort(),
      wallet: (wallet) => wallet ? go("wallet", wallet) : reset(),
      group: () => go("group", current.kind === "wallet" ? model.groupOf[model.lookup.get(current.key)] : current.key),
      toggle: () => {if (current.kind === "wallet") return go("wallet", current.key);}};
    // Expose this owner only after its navigation and cleanup closures are ready.
    active = api;
    return api;
  }
  // Breadcrumb and optional-neighbour controls change only the local projection of checked pair data.
  find("#graph-overview").addEventListener("click", () => active?.go("overview"));
  find("#graph-parent-group").addEventListener("click", () => active?.group());
  find("#graph-neighbour-links").addEventListener("change", () => active?.toggle());
  find("#graph-view-cancel").addEventListener("click", () => active?.cancel());
  // Public construction is the only entry point for accepting a complete checked model.
  return {create};
})();
