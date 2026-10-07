import { webcrypto } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { decode, type Schema } from '../api';
import { validateRunContract } from '../forms';
import { parseAnalytics, parseChart, parseDashboard, parsePage, parseSummary, type Cursor } from '../result-contracts';
import { createDemoClient, routeKey } from './client';

// This gate exercises real exported responses when available; ordinary UI tests need no corpus.
const directory = path.resolve(process.cwd(), 'demo-data');
const manifestFile = path.join(directory, 'manifest.json');
const schema = existsSync(manifestFile) ? JSON.parse(readFileSync(manifestFile, 'utf8')).schema : null;
const base = new URL('https://historical-corpus.test/demo-data/');

describe.skipIf(schema === null || schema === 'backtest.static-demo/v1')('prepared historical corpus contracts', () => {
  it('validates every result page and chart against the same contracts used by the browser', async () => {
    // jsdom supplies the UI locale environment; Node supplies the browser-compatible digest API.
    vi.stubGlobal('crypto', webcrypto);
    try {
      const fetcher: typeof fetch = async input => {
        const url = new URL(String(input));
        if (!url.href.startsWith(base.href)) throw new Error('Corpus test attempted an external request.');
        const relative = url.pathname.slice(base.pathname.length);
        if (!/^(?:manifest\.json|responses\/[0-9a-f]{64}\.json)$/.test(relative)) throw new Error('Unexpected corpus path.');
        return new Response(new Uint8Array(readFileSync(path.join(directory, relative))));
      };
      const digest = readFileSync(path.join(directory, 'manifest.sha256'), 'utf8').trim();
      const client = createDemoClient(base, digest, fetcher), catalog = await client.catalog();
      if (catalog.synthetic) throw new Error('Expected the historical corpus selected for this test.');
      const visited = new Set<string>();
      async function read(route: string) {
        const key = routeKey(route), record = catalog.responses[key];
        expect(record, `Missing response ${key}`).toBeDefined();
        const response = await client.request(route);
        expect(response.status, key).toBe('status' in record ? record.status ?? 200 : 200);
        visited.add(key);
        return { status: response.status, body: decode(await response.text()) };
      }
      async function parsed<T>(route: string, parse: (raw: unknown) => T): Promise<T> {
        const response = await read(route);
        expect(response.status, route).toBe(200);
        try { return parse(response.body); }
        catch (error) { throw new Error(`Historical corpus contract failed for ${route}`, { cause: error }); }
      }
      for (const run of catalog.runs) {
        const prefix = `/api/v1/run-artifacts/${run.id}`;
        const summary = await parsed(prefix + '/strategy-summary', raw => parseSummary(raw, run.id));
        expect(parseSummary(run.summary, run.id)).toEqual(summary);
        expect(summary.execution_mode).toBe(run.mode);
        const dashboard = await parsed(prefix + '/strategy-dashboard?limit=25', raw => parseDashboard(raw, run.id));
        expect(dashboard.summary).toEqual(summary);
        const analytics = await parsed(prefix + '/analytics', raw => parseAnalytics(raw, run.id));
        const entryIds = new Set<string>(), cursors = new Set<string>();
        let cursor: Cursor | null = null, count = 0;
        while (true) {
          const query = new URLSearchParams({ limit: '25' });
          if (cursor) {
            query.set('after_target_boundary_ordinal', cursor.target_boundary_ordinal);
            query.set('after_roundtrip_id', cursor.roundtrip_id);
          }
          const route = prefix + '/entries?' + query.toString();
          expect(cursors.has(route), 'Repeated result cursor').toBe(false);
          cursors.add(route);
          const entries = await parsed(route, raw => parsePage(raw, cursor));
          if (cursor === null) expect(entries).toEqual(dashboard.entries);
          for (const entry of entries.items) {
            expect(entryIds.has(entry.entry_id), 'Repeated result entry').toBe(false);
            entryIds.add(entry.entry_id); count++;
            if (entry.chart_availability !== 'AVAILABLE') continue;
            const chartRoute = prefix + `/entries/${entry.entry_id}/chart?boundary_ordinal=${entry.boundary_ordinal}`;
            const response = await read(chartRoute);
            if (response.status === 200) {
              let chart;
              try { chart = parseChart(response.body, run.id, entry); }
              catch (error) { throw new Error(`Historical corpus chart contract failed for ${chartRoute}`, { cause: error }); }
              expect(catalog.source.snapshot_ids).toContain(chart.snapshot_id);
            } else {
              const error = response.body as { code?: unknown; message?: unknown };
              expect([`${404}:MARKET_CHART_UNAVAILABLE`, `${422}:MARKET_CHART_LIMIT_EXCEEDED`]).toContain(`${response.status}:${error.code}`);
              expect(typeof error.message).toBe('string');
              expect(error.message).not.toBe('');
            }
          }
          cursor = entries.next_cursor;
          if (cursor === null) break;
          expect(cursors.size).toBeLessThan(8192);
        }
        expect(BigInt(count), run.id).toBe(BigInt(analytics.entry_count));
        const total = summary.metrics.find(metric => metric.key === 'entry_count');
        expect(total?.availability).toBe('AVAILABLE');
        expect(total?.value).toBe(String(count));
      }
      // Preview forms use the same versioned contracts as the operational application.
      const runContracts = await parsed('/api/v1/run-contracts', raw => raw as Schema<'RunContractListResponse'>);
      for (const family of ['sniping', 'copy'] as const) expect(() => validateRunContract(runContracts, family)).not.toThrow();
      const ml = await parsed('/api/v1/ml/reference-contract', raw => raw as Schema<'ReferenceMlContractResponse'>);
      expect(ml.compiler_version).not.toBe('');
      expect(ml.supported_feature_names.length).toBeGreaterThan(0);
      expect(new Set(ml.supported_feature_names).size).toBe(ml.supported_feature_names.length);
      for (const [key, value] of Object.entries(ml)) if (key.endsWith('_id') || key.endsWith('_digest')) expect(value, key).toMatch(/^[0-9a-f]{64}$/);
      // The workspace list includes only selected completed runs, across all bounded pages.
      const listedRuns = new Set<string>(), runCursors = new Set<string>();
      let runCursor: string | null = null;
      do {
        const query = new URLSearchParams({ limit: '10' });
        if (runCursor !== null) query.set('cursor', runCursor);
        const route = '/api/v1/runs?' + query.toString();
        expect(runCursors.has(route)).toBe(false); runCursors.add(route);
        const list = await parsed(route, raw => raw as Schema<'RunListResponse'>);
        expect(list.items.length).toBeLessThanOrEqual(10);
        for (const run of list.items) {
          expect(listedRuns.has(run.run_artifact_id)).toBe(false);
          listedRuns.add(run.run_artifact_id);
          expect(catalog.runs.some(selected => selected.id === run.run_artifact_id)).toBe(true);
          expect(run.canonical_result_hash).toMatch(/^[0-9a-f]{64}$/);
          expect(Number.isFinite(Date.parse(run.completed_at))).toBe(true);
        }
        runCursor = list.next_cursor ?? null;
        expect(runCursors.size).toBeLessThanOrEqual(2);
      } while (runCursor !== null);
      expect([...listedRuns].sort()).toEqual(catalog.runs.map(run => run.id).sort());
      expect(catalog.runs.every(run => !/[\u0400-\u04ff]/.test(run.title))).toBe(true);
      // All remaining published requests must be complete, clickable lineage exports.
      for (const route of Object.keys(catalog.responses)) {
        if (visited.has(route)) continue;
        expect(route).toMatch(/^\/api\/v1\/lineage\/[0-9a-f]{64}$/);
        const response = await read(route);
        expect(response.status, route).toBe(200);
        const lineage = response.body as { root_artifact_id: string; artifacts: { artifact_id: string }[] };
        expect(lineage.root_artifact_id).toBe(route.split('/').at(-1));
        expect(lineage.artifacts.some(artifact => artifact.artifact_id === lineage.root_artifact_id)).toBe(true);
        for (const artifact of lineage.artifacts) expect(catalog.responses).toHaveProperty(`/api/v1/lineage/${artifact.artifact_id}`);
      }
      for (const snapshot of catalog.source.snapshot_ids) expect(visited.has(`/api/v1/lineage/${snapshot}`)).toBe(true);
      expect(visited.size).toBe(Object.keys(catalog.responses).length);
    } finally { vi.unstubAllGlobals(); }
  }, 120000);
});
