import { iterations, layoutOutput, layoutStep, validateInput, type LayoutInput } from './layout-core';

// A statically bundled same-origin worker; no Blob, eval, network or graph-result persistence.
self.onmessage = (event: MessageEvent<LayoutInput>) => {
  try {
    const input = event.data; validateInput(input);
    for (let i = 0; i < iterations; i++) {layoutStep(input); if ((i+1) % 12 === 0) self.postMessage({type: 'progress', completed: i+1});}
    const result = layoutOutput(input);
    self.postMessage({type: 'done', ...result}, {transfer: [result.coordinates.buffer]});
  } catch {self.postMessage({type: 'error'});}
};
