"use strict";

// A complete bounded display index; no research output, source access or persistent group identity.
const ResearchGraphModel = (() => {
  const policy = "local-modularity-20-v1";
  const pause = () => new Promise((resolve) => setTimeout(resolve, 0));
  // Every expensive phase yields to cancellation and scope replacement before continuing.
  async function checkpoint(signal, owned) {
    await pause();
    signal.throwIfAborted();
    if (!owned()) throw new DOMException("Graph replaced", "AbortError");
  }

  // The local-moving stage maximizes a weighted modularity increment, not an ownership likelihood.
  async function partition(model, signal, owned, progress) {
    const {wallets, adjacent, left, right, weight, strength} = model;
    const membership = Int32Array.from(wallets, (_, index) => index);
    const totals = strength.slice(), mass = strength.reduce((sum, value) => sum + value, 0);
    let passes = 0, stable = false;
    // Fixed canonical visitation and strict improvements make display grouping repeatable without RNG.
    for (; passes < 20 && !stable; passes++) {
      let moves = 0;
      for (let node = 0; node < wallets.length; node++) {
        if (node % 64 === 0) await checkpoint(signal, owned);
        const previous = membership[node], weights = new Map();
        // Remove this wallet's strength before evaluating insertion into its neighbouring groups.
        totals[previous] -= strength[node];
        for (const edge of adjacent[node]) {
          const other = left[edge] === node ? right[edge] : left[edge];
          // Candidate groups are examined by canonical index, avoiding Map insertion-order ties.
          const group = membership[other];
          weights.set(group, (weights.get(group) || 0) + weight[edge]);
        }
        // Isolated display nodes retain their own group; ordinary result wallets have positive degree.
        const score = (group) => (weights.get(group) || 0) - (mass ? strength[node] * totals[group] / mass : 0);
        let best = previous, gain = score(previous);
        // Reinsert the full wallet strength even when it stays in its previous group.
        for (const group of [...weights.keys()].sort((a, b) => a - b)) {
          const candidate = score(group);
          if (candidate > gain + 1e-9) {best = group; gain = candidate;}
        }
        // Equal gains retain the previous group, or the first canonical strictly better candidate.
        membership[node] = best;
        totals[best] += strength[node];
        if (best !== previous) moves++;
      }
      // Publish sweep metadata together with the membership actually used for display.
      stable = moves === 0;
      progress(20 + (passes + 1) * 3, 100);
    }
    // Hitting the sweep bound yields a labelled heuristic, never a false convergence claim.
    return {membership, passes, stable};
  }

  // Every original pair enters exactly one internal bucket or one crossing bucket.
  async function groupIndex(model, partitioned, signal, owned) {
    const buckets = new Map();
    partitioned.membership.forEach((group, node) => {
      // Append each canonical wallet once, including disconnected singletons.
      if (!buckets.has(group)) buckets.set(group, []);
      buckets.get(group).push(node);
    });
    // Size-first numbering makes the overview useful; canonical first addresses break size ties.
    const members = [...buckets.values()].sort((a, b) => b.length - a.length || a[0] - b[0]);
    const groups = members.map((nodes, id) => ({id, members: nodes, internal: [], links: []}));
    const groupOf = new Uint16Array(model.wallets.length), crossing = new Map();
    groups.forEach((group) => group.members.forEach((node) => {groupOf[node] = group.id;}));
    // Compact numeric indices retain the exact server row objects separately for evidence navigation.
    for (let edge = 0; edge < model.rows.length; edge++) {
      if (edge % 4096 === 0) await checkpoint(signal, owned);
      const a = groupOf[model.left[edge]], b = groupOf[model.right[edge]];
      if (a === b) {groups[a].internal.push(edge); continue;}
      const low = Math.min(a, b), high = Math.max(a, b), key = `${low}:${high}`;
      // Crossing lists are shared by their two groups, never counted twice in the overview total.
      if (!crossing.has(key)) crossing.set(key, {key, a: low, b: high, indices: []});
      crossing.get(key).indices.push(edge);
    }
    const links = [...crossing.values()].sort((a, b) => a.a - b.a || a.b - b.b);
    links.forEach((link) => {groups[link.a].links.push(link); groups[link.b].links.push(link);});
    // Refuse an inconsistent display instead of calling a partial aggregate the complete result.
    const internal = groups.reduce((sum, group) => sum + group.internal.length, 0);
    const external = links.reduce((sum, link) => sum + link.indices.length, 0);
    if (internal + external !== model.rows.length) throw new Error("Не сошлись счётчики групп графа.");
    return {groups, groupOf, links, internal, external, passes: partitioned.passes, stable: partitioned.stable};
  }

  // The loader has verified scope, ordinals and pair counts; this boundary also guards local allocation.
  async function build(data, signal, progress = () => {}, owned = () => true) {
    if (data.rows.length > 200000 || data.wallets.length > 5000) throw new Error("Превышен лимит полного графа.");
    await checkpoint(signal, owned);
    const wallets = [...data.wallets].sort(), rows = data.rows.slice();
    const lookup = new Map(wallets.map((wallet, index) => [wallet, index]));
    // Numeric endpoints and adjacency lists avoid keeping the full result as heavyweight canvas objects.
    const left = new Uint16Array(rows.length), right = new Uint16Array(rows.length);
    const weight = new Float64Array(rows.length), strength = new Float64Array(wallets.length);
    const adjacent = Array.from(wallets, () => []);
    if (lookup.size !== wallets.length) throw new Error("Повтор кошелька в модели графа.");
    // Copy only the row array; accepted immutable row objects remain authoritative display evidence.
    for (let edge = 0; edge < rows.length; edge++) {
      if (edge % 4096 === 0) {await checkpoint(signal, owned); progress(rows.length ? edge / rows.length * 20 : 20, 100);}
      const row = rows[edge], a = lookup.get(row.signer_a), b = lookup.get(row.signer_b);
      const value = Number(row.shared_mints);
      // A display bug must not turn an unknown endpoint or invalid weight into a synthetic node.
      if (a === undefined || b === undefined || a === b || !Number.isSafeInteger(value) || value < 1 || value > 2000000) {
        throw new Error("Некорректная пара в модели графа.");
      }
      left[edge] = a; right[edge] = b; weight[edge] = value;
      adjacent[a].push(edge); adjacent[b].push(edge);
      // Positive integer weights remain exactly representable within the admitted pair and mint caps.
      strength[a] += value; strength[b] += value;
    }
    const model = {rows, wallets, lookup, left, right, weight, strength, adjacent};
    const partitioned = await partition(model, signal, owned, progress);
    const grouped = await groupIndex(model, partitioned, signal, owned);
    // Group numbers and sweep statistics are view-local; no serialized research identity is created.
    progress(100, 100);
    return {...model, ...grouped, policy};
  }

  // Wallet focus always uses global adjacency, including links outside its displayed visual group.
  async function neighbourhood(model, wallet, includeNeighbours, signal, owned = () => true) {
    const centre = model.lookup.get(wallet);
    if (centre === undefined) throw new Error("Кошелёк отсутствует в результате.");
    const members = new Set([centre]), incident = model.adjacent[centre];
    incident.forEach((edge) => {members.add(model.left[edge]); members.add(model.right[edge]);});
    // Count all neighbour-to-neighbour pairs even when the explicit display toggle is off.
    const indices = incident.slice();
    let extra = 0;
    // Finish indexing before reporting a completed grouped model.
    for (let edge = 0; edge < model.rows.length; edge++) {
      if (edge % 4096 === 0) await checkpoint(signal, owned);
      const a = model.left[edge], b = model.right[edge];
      if (a === centre || b === centre || !members.has(a) || !members.has(b)) continue;
      // Each optional pair is included exactly once, independently of the centre's own incident list.
      extra++;
      if (includeNeighbours) indices.push(edge);
    }
    return {members: [...members].sort((a, b) => a - b), indices, centre, extra, incident: incident.length};
  }
  // Export pure display operations without exposing a source, storage or execution dependency.
  return {build, neighbourhood, checkpoint, policy};
})();

export default ResearchGraphModel;
