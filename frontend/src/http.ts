// The ordinary build always talks to the existing same-origin API, never to demo fixtures.
export const request: typeof fetch = (...args) => fetch(...args);
