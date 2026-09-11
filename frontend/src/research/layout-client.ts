import { iterations, layoutInput, layoutPolicy, validateCoordinates } from './layout-core';
import type { DisplayGraph } from './sigma-data';
export type WorkerLike = Pick<Worker, 'postMessage' | 'terminate'> & {onmessage: ((event: MessageEvent<unknown>) => void) | null; onerror: ((event: ErrorEvent) => void) | null; onmessageerror: ((event: MessageEvent<unknown>) => void) | null};
export const createLayoutWorker = (): WorkerLike => new Worker(new URL('./layout.worker.ts', import.meta.url), {type: 'module', name: 'research-layout'});

// Completion, failure and cancellation all retire the private worker before changing React state.
export async function runLayout(graph: DisplayGraph, signal: AbortSignal, progress: (completed: number) => void, makeWorker: () => WorkerLike = createLayoutWorker): Promise<Float32Array> {
  const input = await layoutInput(graph, signal); signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    let worker: WorkerLike;
    try {worker = makeWorker();} catch {reject(new Error('Could not start the graph layout worker.')); return;}
    let done = false;
    const finish = (coordinates?: Float32Array, error?: Error) => {if (done) return; done = true; signal.removeEventListener('abort', abort); worker.onmessage = null; worker.onerror = null; worker.onmessageerror = null; worker.terminate(); if (coordinates) resolve(coordinates); else reject(error);};
    const abort = () => finish(undefined, new DOMException('Graph layout cancelled or timed out.', 'AbortError'));
    signal.addEventListener('abort', abort, {once: true});
    if (signal.aborted) {abort(); return;}
    worker.onerror = event => {event.preventDefault(); finish(undefined, new Error('Graph layout worker failed.'));};
    worker.onmessageerror = () => finish(undefined, new Error('Graph layout worker returned unreadable data.'));
    worker.onmessage = (event: MessageEvent<unknown>) => {
      try {
        const data = event.data as {type?: string; completed?: number; policy?: string; iterations?: number; coordinates?: Float32Array};
        if (data?.type === 'progress' && Number.isInteger(data.completed) && data.completed! >= 0 && data.completed! <= iterations) {progress(data.completed!); return;}
        if (data?.type !== 'done' || data.policy !== layoutPolicy || data.iterations !== iterations || !data.coordinates) throw new Error('Graph layout worker failed.');
        validateCoordinates(data.coordinates, graph.order); finish(data.coordinates);
      } catch {finish(undefined, new Error('Graph layout failed or returned invalid coordinates.'));}
    };
    try {worker.postMessage(input, [input.nodes.buffer, input.edges.buffer]);} catch {finish(undefined, new Error('Could not send the graph to its layout worker.'));}
  });
}
