declare module 'graphology-layout-forceatlas2/iterate.js' {
  import type { ForceAtlas2Settings } from 'graphology-layout-forceatlas2';
  export default function iterate(settings: Required<ForceAtlas2Settings>, nodes: Float32Array, edges: Float32Array): unknown;
}
