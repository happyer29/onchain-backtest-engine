import { z } from 'zod';

const id = z.string().regex(/^[0-9a-f]{64}$/);
const decimal = z.string().regex(/^(0|[1-9][0-9]*)$/);
const responseRecord = z.object({
  file: z.string().regex(/^responses\/[0-9a-f]{64}\.json$/),
  bytes: z.number().int().positive().max(2 * 1024 ** 2),
  sha256: id,
}).strict();
const catalogSchema = z.object({
  schema: z.literal('backtest.static-demo/v1'),
  recipe: z.literal('synthetic-wallet-groups-and-copy-outcomes/v1'),
  synthetic: z.literal(true),
  wallets: z.number().int().min(1).max(100),
  snapshot: id,
  research: z.array(z.object({
    id, mode: z.enum(['NON_MAYHEM', 'ALL']), counts: z.record(decimal),
  }).strict()).length(2),
  runs: z.array(z.object({
    id, mode: z.enum(['EXOGENOUS_REPLAY', 'EXOGENOUS_VIRTUAL_SETTLEMENT']),
    title: z.string().max(100), summary: z.unknown(),
  }).strict()).length(2),
  response_bytes: z.number().int().positive().max(16 * 1024 ** 2),
  responses: z.record(responseRecord),
}).strict();
export type DemoCatalog = z.infer<typeof catalogSchema>;
const failure = (code: string, status: number) => new Response(JSON.stringify({
  code,
  message: code === 'DEMO_READ_ONLY'
    ? 'This demo only reads prepared examples. New jobs are unavailable.'
    : 'This item is not included in the demo.',
}), { status, headers: { 'Content-Type': 'application/json' } });

export function routeKey(path: string): string {
  if (!path.startsWith('/api/v1/') || /[#\\\s]/.test(path) || path.includes('://') || path.includes('..')) {
    throw new Error('Invalid demo request.');
  }
  const parsed = new URL(path, 'https://demo.invalid');
  if (parsed.origin !== 'https://demo.invalid' || [...parsed.searchParams.keys()].some(key => parsed.searchParams.getAll(key).length !== 1)) {
    throw new Error('Invalid demo request.');
  }
  parsed.searchParams.sort();
  return parsed.pathname + (parsed.searchParams.size ? '?' + parsed.searchParams.toString() : '');
}

async function bounded(response: Response, maximum: number): Promise<Uint8Array<ArrayBuffer>> {
  if (!response.ok || !response.body) throw new Error('Demo data is unavailable. Reload to retry.');
  const reader = response.body.getReader(), chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const part = await reader.read();
      if (part.done) break;
      size += part.value.length;
      if (size > maximum) throw new Error('Demo data exceeds its size limit.');
      chunks.push(part.value);
    }
  } finally {
    await reader.cancel();
    reader.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  return bytes;
}

async function verify(bytes: Uint8Array<ArrayBuffer>, digest: string) {
  const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), b => b.toString(16).padStart(2, '0')).join('');
  if (hash !== digest) throw new Error('Demo data integrity check failed. Reload to retry.');
}

// A closed static transport has no operational URL, session or API fallback.
export function createDemoClient(base: URL, manifestDigest: string, fetcher: typeof fetch = fetch) {
  id.parse(manifestDigest);
  let catalogPromise: Promise<DemoCatalog> | null = null;
  function catalog(): Promise<DemoCatalog> {
    if (!catalogPromise) catalogPromise = (async () => {
      const bytes = await bounded(await fetcher(new URL('manifest.json', base), {
        credentials: 'omit', signal: AbortSignal.timeout(15000),
      }), 1024 ** 2);
      await verify(bytes, manifestDigest);
      const value = catalogSchema.parse(JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)));
      const entries = Object.entries(value.responses);
      if (entries.length > 2048 || entries.reduce((sum, [, record]) => sum + record.bytes, 0) !== value.response_bytes) {
        throw new Error('Invalid demo corpus bounds.');
      }
      for (const [key, record] of entries) {
        if (routeKey(key) !== key || record.file !== `responses/${record.sha256}.json`) throw new Error('Invalid demo response mapping.');
      }
      for (const example of value.research) {
        if (BigInt(example.counts.pairs) > 1000n) throw new Error('Demo graph exceeds its bounds.');
      }
      return value;
    })().catch(error => { catalogPromise = null; throw error; });
    return catalogPromise;
  }
  const request: typeof fetch = async (input, options = {}) => {
    if ((options.method ?? 'GET') !== 'GET' || options.body != null) return failure('DEMO_READ_ONLY', 405);
    if (typeof input !== 'string') return failure('DEMO_UNKNOWN_REQUEST', 404);
    let key: string;
    try { key = routeKey(input); } catch { return failure('DEMO_UNKNOWN_REQUEST', 404); }
    options.signal?.throwIfAborted();
    const data = await catalog();
    options.signal?.throwIfAborted();
    if (!Object.hasOwn(data.responses, key)) return failure('DEMO_UNKNOWN_REQUEST', 404);
    const record = data.responses[key];
    const signal = options.signal ? AbortSignal.any([options.signal, AbortSignal.timeout(15000)]) : AbortSignal.timeout(15000);
    const bytes = await bounded(await fetcher(new URL(record.file, base), { credentials: 'omit', signal }), record.bytes);
    signal.throwIfAborted();
    if (bytes.length !== record.bytes) throw new Error('Demo response length does not match its manifest.');
    await verify(bytes, record.sha256);
    signal.throwIfAborted();
    return new Response(bytes, { headers: { 'Content-Type': 'application/json' } });
  };
  return { catalog, request };
}
