import type { GraphData, Model, Projection } from './types';
declare const model: {
  policy: string;
  checkpoint(signal: AbortSignal, owned: () => boolean): Promise<void>;
  build(data: GraphData, signal: AbortSignal, progress?: (done: number, total: number) => void, owned?: () => boolean): Promise<Model>;
  neighbourhood(model: Model, wallet: string, includeNeighbours: boolean, signal: AbortSignal, owned?: () => boolean): Promise<Projection>;
};
export default model;
