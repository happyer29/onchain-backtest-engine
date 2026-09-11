import type { GraphData } from './types';
declare const loader: {
  limits: {pairs: number; wallets: number; page: number; responseBytes: number; totalBytes: number; deadline: number};
  load(artifact: string, total: string, signal: AbortSignal, progress: (done: number, total: number, wallets: number) => void): Promise<GraphData>;
};
export default loader;
