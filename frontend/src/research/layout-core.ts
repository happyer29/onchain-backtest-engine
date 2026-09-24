import iterate from 'graphology-layout-forceatlas2/iterate.js';
import type { ForceAtlas2Settings } from 'graphology-layout-forceatlas2';
import type { DisplayGraph } from './sigma-data';
import algorithms from './research-graph-model';

export const layoutPolicy = 'research-forceatlas2-120-v1';
export const iterations = 120;
export type LayoutInput = { nodes: Float32Array; edges: Float32Array };
export type LayoutOutput = { policy: typeof layoutPolicy; coordinates: Float32Array; iterations: number };
export const layoutSettings = (order: number): Required<ForceAtlas2Settings> => ({linLogMode: true, outboundAttractionDistribution: false, adjustSizes: false, edgeWeightInfluence: 1, scalingRatio: 10, strongGravityMode: true, gravity: 1, slowDown: 5, barnesHutOptimize: order > 150, barnesHutTheta: .5});

// Pinned ForceAtlas2 0.10.1 matrices match its public graphToByteArrays contract (10/3 floats).
export async function layoutInput(graph: DisplayGraph, signal: AbortSignal, owned: () => boolean = () => true): Promise<LayoutInput> {
  if (graph.order > 5000 || graph.size > 200000) throw new Error('Graph layout exceeds its budget.');
  const nodes = new Float32Array(graph.order * 10), edges = new Float32Array(graph.size * 3), lookup = new Map<string, number>();
  graph.forEachNode((key, attrs) => {const i = lookup.size * 10; lookup.set(key, i); nodes[i] = attrs.x; nodes[i+1] = attrs.y; nodes[i+6] = 1; nodes[i+7] = 1; nodes[i+8] = attrs.size; nodes[i+9] = attrs.fixed ? 1 : 0;});
  const keys = graph.edges();
  for (let offset = 0; offset < keys.length; offset += 4096) {
    await algorithms.checkpoint(signal, owned);
    for (let i = offset; i < Math.min(keys.length, offset + 4096); i++) {const key = keys[i], a = lookup.get(graph.source(key))!, b = lookup.get(graph.target(key))!, weight = graph.getEdgeAttribute(key, 'weight'); nodes[a+6] += weight; nodes[b+6] += weight; edges[i*3] = a; edges[i*3+1] = b; edges[i*3+2] = weight;}
  }
  return {nodes, edges};
}
export function validateInput(input: LayoutInput) {
  if (!(input.nodes instanceof Float32Array) || !(input.edges instanceof Float32Array) || input.nodes.length % 10 || input.edges.length % 3 || input.nodes.length > 50000 || input.edges.length > 600000 || !input.nodes.every(Number.isFinite) || !input.edges.every(Number.isFinite)) throw new Error('Invalid bounded layout input.');
  for (let i = 0; i < input.edges.length; i += 3) {const a = input.edges[i], b = input.edges[i+1], weight = input.edges[i+2]; if (a < 0 || b < 0 || a % 10 || b % 10 || a >= input.nodes.length || b >= input.nodes.length || a === b || weight < 1) throw new Error('Invalid bounded layout edge.');}
}
// Executed only inside the single owned worker in browsers; node tests compare the public oracle.
export function layoutStep(input: LayoutInput) { iterate(layoutSettings(input.nodes.length / 10), input.nodes, input.edges); }
export function layoutOutput(input: LayoutInput): LayoutOutput {
  const coordinates = new Float32Array(input.nodes.length / 5);
  for (let i = 0; i < coordinates.length / 2; i++) {coordinates[i*2] = input.nodes[i*10]; coordinates[i*2+1] = input.nodes[i*10+1];}
  validateCoordinates(coordinates, input.nodes.length / 10);
  return {policy: layoutPolicy, coordinates, iterations};
}
export function validateCoordinates(coordinates: Float32Array, order: number) {
  if (!(coordinates instanceof Float32Array) || coordinates.length !== order * 2 || !coordinates.every(x => Number.isFinite(x) && Math.abs(x) <= 1e8)) throw new Error('Invalid graph layout coordinates.');
}
export function applyCoordinates(graph: DisplayGraph, coordinates: Float32Array) {
  validateCoordinates(coordinates, graph.order); let i = 0;
  graph.updateEachNodeAttributes((_, attrs) => ({...attrs, x: coordinates[i++], y: coordinates[i++]}), {attributes: ['x','y']});
}
