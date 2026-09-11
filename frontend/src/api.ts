import { t } from './i18n';
import { QueryClient } from '@tanstack/react-query';
import { parse, stringify } from 'lossless-json';
import type { components } from './generated/api';

// Requests and responses retain every integer digit, including resolved execution inputs.
export type Json = null | boolean | string | number | bigint | Json[] | { [key: string]: Json };
export type Schema<K extends keyof components['schemas']> = components['schemas'][K];
export class ApiError extends Error {
  constructor(public code: string, message: string, public status = 0) { super(message); }
}

// Loopback remains usable offline; immutable queries do not refetch on focus or reconnect.
export const queryClient = new QueryClient({ defaultOptions: {
  queries: { retry: false, staleTime: Infinity, gcTime: 0, networkMode: 'always',
    refetchOnWindowFocus: false, refetchOnReconnect: false, refetchOnMount: false },
  mutations: { retry: false, networkMode: 'always' },
} });

export function decode(text: string): unknown {
  // Unsafe integers become BigInt before JSON.parse could round the resolved specification.
  return parse(text, undefined, { parseNumber: (value: string) => {
    const number = Number(value);
    return /^-?\d+$/.test(value) && !Number.isSafeInteger(number) ? BigInt(value) : number;
  } });
}

// Lossless serialization carries resolved integers back to the API without canonicalization in React.
export function encode(value: unknown): string {
  const body = stringify(value);
  if (typeof body !== 'string') throw new ApiError('INVALID_JSON', t("The command contains no data."));
  return body;
}

// A fixed transport centralizes security, size limits and cancellation for every screen.
export async function api<T>(path: string, options: { signal?: AbortSignal; body?: unknown; method?: 'GET' | 'POST'; key?: string } = {}): Promise<T> {
  // Only fixed same-origin API paths are accepted by the client transport.
  if (!path.startsWith('/api/v1/') || path.includes('://')) throw new ApiError('INVALID_PATH', t("Invalid API address."));
  const timeout = AbortSignal.timeout(15_000);
  const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout;
  const headers: Record<string, string> = { Accept: 'application/json' };
  // Session cookies stay HttpOnly; mutations carry the same existing CSRF contract.
  if (options.method === 'POST') headers['X-Backtest-CSRF'] = '1';
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (options.key) headers['Idempotency-Key'] = options.key;
  const body = options.body === undefined ? undefined : encode(options.body);
  if (body && new TextEncoder().encode(body).length > 2 * 1024 ** 2) throw new ApiError('REQUEST_TOO_LARGE', t("The command exceeds the interface limit."));
  // Browser-managed cookies remain same-origin and never become serializable application state.
  const response = await fetch(path, { method: options.method ?? 'GET', headers, signal,
    body, credentials: 'same-origin' });
  // Bound transport before parsing so metadata cannot become an arbitrary history download.
  const text = await readBounded(response);
  const value = decode(text) as { code?: unknown; message?: unknown } | null;
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new ApiError('INVALID_RESPONSE', t("The API returned an invalid response."));
  if (!response.ok) throw new ApiError(typeof value.code === 'string' ? value.code : 'REQUEST_FAILED', typeof value.message === 'string' ? value.message : t("The request could not be completed."), response.status);
  return value as T;
}

export function digest(): string {
  // Physical attempt and idempotency identities are allocated once per intentional submission.
  return Array.from(crypto.getRandomValues(new Uint8Array(32)), byte => byte.toString(16).padStart(2, '0')).join('');
}

// Timeouts have a stable user message; server errors have already passed the safe API boundary.
export function errorText(error: unknown): string {
  if (error instanceof DOMException && error.name === 'TimeoutError') return t("The request timed out. Please try again.");
  return error instanceof Error ? t(error.message) : t("Could not load data.");
}


// Streaming enforces the response ceiling before allocating the complete UTF-8 document.
async function readBounded(response: Response): Promise<string> {
  const reader = response.body?.getReader();
  if (!reader) throw new ApiError('INVALID_RESPONSE', t("The API returned an empty response."));
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    // Stop reading as soon as the byte budget is crossed, before allocating decoded JSON.
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.length;
      if (total > 2 * 1024 ** 2) { await reader.cancel(); throw new ApiError('RESPONSE_TOO_LARGE', t("The response exceeds the interface limit.")); }
      // Retain only admitted chunks; cancellation above releases the over-budget response.
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  // One final allocation decodes strict UTF-8 after the bounded stream has completed.
  const body = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.length; }
  return new TextDecoder('utf-8', { fatal: true }).decode(body);
}
