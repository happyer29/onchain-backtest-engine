import { UndirectedGraph } from 'graphology';
import algorithms from './research-graph-model';
import type { GroupLink, Model, Projection, View } from './types';

export type NodeData = { x: number; y: number; size: number; color: string; label: string; group: number; wallet?: string; fixed?: boolean };
export type EdgeData = { weight: number; size: number; color: string; index?: number; link?: GroupLink };
export type DisplayGraph = UndirectedGraph<NodeData, EdgeData>;
export type BuiltGraph = { graph: DisplayGraph; projection: Projection | null };
export const colours = ['#4c9e88','#b7843b','#608dca','#bb76b5','#c48663','#749d65','#9584cf','#4b9fad'];
export const viewKey = (view: View, neighbours: boolean) => `${view.kind}:${'key' in view ? view.key : ''}:${view.kind === 'wallet' && neighbours}`;

// The full verified model remains authoritative; the renderer owns exactly one complete projection.
export async function buildDisplayGraph(model: Model, view: View, neighbours: boolean, signal: AbortSignal, owned: () => boolean = () => true): Promise<BuiltGraph> {
  await algorithms.checkpoint(signal, owned);
  const projection = view.kind === 'wallet' ? await algorithms.neighbourhood(model, view.key, neighbours, signal, owned)
    : view.kind === 'group' ? { members: model.groups[view.key].members, indices: model.groups[view.key].internal }
      : view.kind === 'page' ? { members: model.wallets.map((_, i) => i), indices: model.rows.map((_, i) => i) } : null;
  const graph: DisplayGraph = new UndirectedGraph({ allowSelfLoops: false });
  const nodes = view.kind === 'overview' ? model.groups.map(group => ({ id: `group:${group.id}`, group: group.id, label: String(group.id + 1), size: 5 + Math.log2(1 + group.members.length) * 1.5 }))
    : projection!.members.map(node => ({ id: `wallet:${model.wallets[node]}`, wallet: model.wallets[node], group: model.groupOf[node], label: `${model.wallets[node].slice(0,5)}…${model.wallets[node].slice(-4)}`, size: node === projection!.centre ? 12 : 5, fixed: node === projection!.centre }));
  try {
    // Canonical spiral starts are noncoincident and independent of wall clock or random state.
    nodes.forEach((node, i) => {const angle = i * 2.399963229728653; const radius = 10 * Math.sqrt(i + 1); graph.addNode(node.id, {...node, color: colours[node.group % colours.length], x: 'fixed' in node && node.fixed ? 0 : radius * Math.cos(angle), y: 'fixed' in node && node.fixed ? 0 : radius * Math.sin(angle)});});
    const length = projection ? projection.indices.length : model.links.length;
    for (let offset = 0; offset < length; offset += 1000) {
      await algorithms.checkpoint(signal, owned);
      if (projection) for (const index of projection.indices.slice(offset, offset + 1000)) {
        const row = model.rows[index];
        graph.addEdgeWithKey(`pair:${row.row_id}`, `wallet:${row.signer_a}`, `wallet:${row.signer_b}`, {index, weight: model.weight[index], size: .6 + Math.log2(1 + model.weight[index]) * .35, color: '#7b999255'});
      } else for (const link of model.links.slice(offset, offset + 1000)) graph.addEdgeWithKey(`groups:${link.key}`, `group:${link.a}`, `group:${link.b}`, {link, weight: link.indices.length, size: .5 + Math.log2(1 + link.indices.length) * .25, color: '#7b999266'});
    }
    signal.throwIfAborted();
    return {graph, projection};
  } catch (error) {graph.clear(); throw error;}
}

export type DisplayFilter = { minimum: number; matches: Uint8Array; shown: number; internal: number; external: number; groupInternal: Uint32Array; links: Map<string, number> };
// Filtering never repartitions the graph or modifies committed rows and exact evidence ordinals.
export async function filterPairs(model: Model, minimum: number, signal: AbortSignal, owned: () => boolean = () => true): Promise<DisplayFilter> {
  if (!Number.isSafeInteger(minimum) || minimum < 1 || minimum > 2000000) throw new Error('Use a whole number from 1 to 2,000,000.');
  const matches = new Uint8Array(model.rows.length), groupInternal = new Uint32Array(model.groups.length), links = new Map<string, number>();
  let shown = 0, internal = 0, external = 0;
  for (let i = 0; i < matches.length; i++) {
    if (i % 4096 === 0) await algorithms.checkpoint(signal, owned);
    if (model.weight[i] < minimum) continue;
    matches[i] = 1; shown++;
    const a = model.groupOf[model.left[i]], b = model.groupOf[model.right[i]];
    if (a === b) {internal++; groupInternal[a]++;}
    else {external++; const key = `${Math.min(a,b)}:${Math.max(a,b)}`; links.set(key, (links.get(key) ?? 0) + 1);}
  }
  return { minimum, matches, shown, internal, external, groupInternal, links };
}
export const visibleIndices = (indices: number[], filter: DisplayFilter) => indices.filter(index => filter.matches[index] === 1);
