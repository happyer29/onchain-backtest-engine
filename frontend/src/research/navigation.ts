import type { CameraState } from 'sigma/types';
import type { DisplayGraph } from './sigma-data';
export type ViewBounds = {x: [number, number]; y: [number, number]};
export type SavedView = {coordinates: Float32Array; camera: CameraState; bounds?: ViewBounds};

// Scope-local LRU retains coordinates/camera only, never eight graphs or copied edge relations.
export class ViewMemory {
  private views = new Map<string, SavedView>();
  get size() {return this.views.size;}
  read(key: string, order: number): SavedView | undefined {const view = this.views.get(key); if (!view || view.coordinates.length !== order * 2) return; this.views.delete(key); this.views.set(key, view); return view;}
  save(key: string, graph: DisplayGraph, camera: CameraState, bounds?: ViewBounds) {
    if (graph.order > 5000) throw new Error('Graph navigation exceeds its budget.');
    const coordinates = new Float32Array(graph.order * 2); let i = 0;
    graph.forEachNode((_, attrs) => {coordinates[i++] = attrs.x; coordinates[i++] = attrs.y;});
    this.views.delete(key); this.views.set(key, {coordinates, camera: {...camera}, bounds: bounds ? {x:[...bounds.x],y:[...bounds.y]} : undefined});
    while (this.views.size > 8) this.views.delete(this.views.keys().next().value!);
  }
  forget(key: string) {this.views.delete(key);}
  clear() {this.views.clear();}
}
