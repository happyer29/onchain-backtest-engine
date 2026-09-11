import cytoscape, { type Core, type ElementDefinition, type StylesheetJson } from 'cytoscape';
import algorithms from './research-graph-model';
import type { Model, Projection, View } from './types';

// This adapter owns canvas objects only. All controls, inspectors and navigation belong to React.
const colours = ['#4c9e88','#b7843b','#608dca','#bb76b5','#c48663','#749d65','#9584cf','#4b9fad'];
export const graphStyle: StylesheetJson = [
  {selector: 'node', style: {'background-color': 'data(colour)', width: 'data(size)', height: 'data(size)', label: 'data(label)', color: '#dce8ed', 'font-size': 11, 'text-valign': 'bottom', 'text-margin-y': 8, 'text-background-color': '#18212b', 'text-background-opacity': 0.9}},
  {selector: 'edge', style: {width: 'data(width)', 'line-color': '#728d87', 'curve-style': 'straight', opacity: 0.5}},
  {selector: 'edge.page-pair', style: {label: 'data(shared)', color: '#dce8ed', 'font-size': 10, 'text-background-color': '#18212b', 'text-background-opacity': 1, 'text-background-padding': '3px'}},
  {selector: '.muted', style: {opacity: 0.16}},
  {selector: 'node.centre', style: {'border-width': 4, 'border-color': '#e5af60', width: 38, height: 38}},
  {selector: ':selected', style: {'line-color': '#e5af60', 'border-color': '#e5af60', 'border-width': 3, opacity: 1}},
];
export function arrange(graph: Core, view: View) {
  const centre = view.kind === 'wallet' ? `wallet:${view.key}` : null;
  const nodes = graph.nodes().toArray().sort((a, b) => {
    if (a.id() === centre) return -1;
    if (b.id() === centre) return 1;
    if (centre && a.data('group') !== b.data('group')) return a.data('group') - b.data('group');
    return b.degree() - a.degree() || (a.id() < b.id() ? -1 : 1);
  });
  let offset = 1, ring = 1;
  if (nodes.length) nodes[0].position({x: 0, y: 0});
  while (offset < nodes.length) {
    const count = Math.min(ring * 12, nodes.length - offset), radius = ring * 120;
    for (let index = 0; index < count; index++) {
      const angle = index * Math.PI * 2 / count;
      nodes[offset + index].position({x: radius * Math.cos(angle), y: radius * Math.sin(angle)});
    }
    offset += count; ring++;
  }
  // The proven small-view threshold prevents a force simulation over large projections.
  if (!centre && nodes.length <= 150 && graph.edges().length <= 1000) graph.layout({name: 'cose', randomize: false, animate: false, padding: 48, nodeRepulsion: () => 18000, idealEdgeLength: () => 160, numIter: 400}).run();
  graph.fit(graph.nodes(), 48);
}

// Every projection is complete before mount; replacement/cancellation destroys its private candidate.
export async function buildCanvas(model: Model, view: View, neighbours: boolean, signal: AbortSignal, owned: () => boolean): Promise<{graph: Core; projection: Projection | null}> {
  await algorithms.checkpoint(signal, owned);
  const projection = view.kind === 'wallet' ? await algorithms.neighbourhood(model, view.key, neighbours, signal, owned)
    : view.kind === 'group' ? {members: model.groups[view.key].members, indices: model.groups[view.key].internal}
      : view.kind === 'page' ? {members: model.wallets.map((_, i) => i), indices: model.rows.map((_, i) => i)} : null;
  const nodes: ElementDefinition[] = view.kind === 'overview' ? model.groups.map(group => ({data: {id: `group:${group.id}`, group: group.id, colour: colours[group.id % colours.length], size: 24 + Math.log2(1 + group.members.length) * 5, label: model.groups.length <= 150 ? String(group.id + 1) : ''}}))
    : projection!.members.map(node => ({data: {id: `wallet:${model.wallets[node]}`, wallet: model.wallets[node], group: model.groupOf[node], colour: colours[model.groupOf[node] % colours.length], size: 20, label: projection!.members.length <= 60 || node === projection!.centre ? `${model.wallets[node].slice(0,5)}…${model.wallets[node].slice(-4)}` : ''}, classes: node === projection!.centre ? 'centre' : ''}));
  const graph = cytoscape({headless: true, styleEnabled: true, elements: [], style: graphStyle, layout: {name: 'preset'}, minZoom: 0.005, maxZoom: 4, pixelRatio: 1, boxSelectionEnabled: false});
  try {
    graph.add(nodes);
    const length = view.kind === 'overview' ? model.links.length : projection!.indices.length;
    for (let offset = 0; offset < length; offset += 1000) {
      await algorithms.checkpoint(signal, owned);
      const elements: ElementDefinition[] = view.kind === 'overview' ? model.links.slice(offset, offset + 1000).map(link => ({data: {id: `groups:${link.key}`, source: `group:${link.a}`, target: `group:${link.b}`, link, width: 1 + Math.log2(1 + link.indices.length) / 2}}))
        : projection!.indices.slice(offset, offset + 1000).map(index => { const row = model.rows[index]; return {data: {id: `pair:${row.row_id}`, source: `wallet:${row.signer_a}`, target: `wallet:${row.signer_b}`, index, shared: row.shared_mints, width: projection!.indices.length > 1000 ? 1 : 1 + Math.log2(1 + Number(row.shared_mints)) / 2}, classes: view.kind === 'page' ? 'page-pair' : ''}; });
      graph.add(elements);
    }
    signal.throwIfAborted();
    if (!owned()) throw new DOMException('Graph replaced', 'AbortError');
    arrange(graph, view);
    signal.throwIfAborted();
    return {graph, projection};
  } catch (error) { graph.destroy(); throw error; }
}
