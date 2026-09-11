import { describe, expect, it } from 'vitest';
import { parseAnalytics, parseChart, parseDashboard, parsePage, parseSummary } from './result-contracts';
import { analyticsFixture, chartFixture, entryFixture, point, runId, summaryFixture } from './test-fixtures';
import { marketViewport } from './chart-view';
// These tests replace the retired copy/sniping scripts at the shared result boundary.
it('retains exact chart money and binds own markers to their recorded outcomes', () => {
  const entry = entryFixture(), chart = chartFixture(entry);
  expect(parseChart(chart, runId, entry).points[0].market_cap_atomic).toBe('9007199254740993001');
  chart.markers[1].status = 'FAILED'; expect(() => parseChart(chart, runId, entry)).toThrow();
});
it.each(['entry_id', 'run_artifact_id', 'asset_id'] as const)('rejects cross-selection chart %s', key => {
  const chart = chartFixture(); chart[key] = key === 'asset_id' ? 'OTHER' : 'f'.repeat(64);
  expect(() => parseChart(chart, runId, entryFixture())).toThrow();
});
it('rejects backward clocks, duplicate boundaries and active-state resurrection', () => {
  const chart = chartFixture(); chart.points[1].block_time_ns = '1';
  expect(() => parseChart(chart, runId, entryFixture())).toThrow();
  chart.points = [point(0), point(0)]; expect(() => parseChart(chart, runId, entryFixture())).toThrow();
  // A terminal market cannot become active again in the same canonical curve history.
  chart.points = [point(0), point(1, 'MIGRATED'), point(10)]; expect(() => parseChart(chart, runId, entryFixture())).toThrow();
});
it('keeps a post-migration rejected sell distinct from an executable fill', () => {
  const entry = entryFixture(), chart = chartFixture();
  Object.assign(entry.attempts[1], { status: 'REJECTED', landing_boundary: null, failure_code: 'CURVE_MIGRATED' });
  chart.points = [point(0), point(1), point(5, 'MIGRATED'), point(10, 'MIGRATED')];
  // The marker uses its actual decision boundary, never its expected landing.
  chart.markers[2] = { kind: 'SELL', status: 'REJECTED', attempt: 1, failure_code: 'CURVE_MIGRATED', point: point(8, 'MIGRATED') };
  expect(parseChart(chart, runId, entry).markers[2].status).toBe('REJECTED');
});
describe('summary and pagination completeness', () => {
  it('preserves null valuation and independently rejects incoherent funding', () => {
    const summary = summaryFixture(); expect(parseSummary(summary, runId).metrics[3].value).toBeNull();
    summary.metrics.push(...['gross_sell_settlement_atomic', 'venue_funded_sell_atomic', 'synthetic_funded_sell_atomic'].map((key, index) => ({ key, value: String(index + 1), unit: 'atomic' as const, availability: 'AVAILABLE' as const })));
    expect(() => parseSummary(summary, runId)).toThrow();
  });
  it('rejects duplicate/regressing rows and a cursor that skips an unseen row', () => {
    const entry = entryFixture();
    expect(parsePage({ items: [entry], next_cursor: null }, null).items).toHaveLength(1);
    expect(() => parsePage({ items: [entry, entry], next_cursor: null }, null)).toThrow();
    // Cursor continuation is exactly the composite key of the last visible entry.
    expect(() => parsePage({ items: [entry], next_cursor: { target_boundary_ordinal: entry.boundary_ordinal, roundtrip_id: 'f'.repeat(64) } }, null)).toThrow();
    expect(() => parsePage({ items: [entry], next_cursor: null }, { target_boundary_ordinal: entry.boundary_ordinal, roundtrip_id: entry.entry_id })).toThrow();
  });
  it('rejects oversized pages, false fills and invented zero valuation', () => {
    const entry = entryFixture(); entry.attempts[0].landing_boundary = null;
    expect(() => parsePage({ items: [entry], next_cursor: null }, null)).toThrow();
    const summary = summaryFixture(); summary.metrics[3].value = '0'; expect(() => parseSummary(summary, runId)).toThrow();
    expect(() => parsePage({ items: [entryFixture()], next_cursor: null }, null, 0)).toThrow();
  });
  it.each(['PUMPFUN_SNIPING', 'PUMPFUN_COPY_BUY', 'FIRST_SWAP'] as const)('uses the same dashboard structure for %s', family => {
    const result = parseDashboard({ contract_schema: 'strategy-results/v1', summary: summaryFixture(family), entries: { items: [], next_cursor: null } }, runId);
    expect(result.summary.family).toBe(family);
  });
  it('rejects partial or duplicate analytical distributions', () => {
    const data = analyticsFixture(); expect(parseAnalytics(data, runId).entry_count).toBe('1');
    data.distributions[0].items[0].count = '2'; expect(() => parseAnalytics(data, runId)).toThrow();
    const duplicate = analyticsFixture(); duplicate.distributions.push(duplicate.distributions[0]); expect(() => parseAnalytics(duplicate, runId)).toThrow();
  });
});

it('rejects invalid summary subset ratios without rounding or hiding valuation gaps', () => {
  const summary = summaryFixture();
  summary.metrics.push({ key: 'open_position_count', value: '1', unit: 'count', availability: 'AVAILABLE' }, { key: 'unvalued_open_position_count', value: '2', unit: 'count', availability: 'AVAILABLE' });
  expect(() => parseSummary(summary, runId)).toThrow();
  // Negative fees and impossible closed/buy proportions remain invalid under the common UI.
  const fees = summaryFixture(); fees.metrics[4].value = '-1'; expect(() => parseSummary(fees, runId)).toThrow();
  const closed = summaryFixture(); closed.metrics.push({ key: 'filled_buy_count', value: '0', unit: 'count', availability: 'AVAILABLE' }); expect(() => parseSummary(closed, runId)).toThrow();
});

it('draws tiny changes above Number precision and never continues the curve after migration', () => {
  const chart = chartFixture();
  chart.points = [point(0), point(1), point(5, 'MIGRATED'), point(10, 'MIGRATED')];
  chart.points.forEach((item, index) => { item.market_cap_atomic = String(9007199254740993001n + BigInt(index)); });
  chart.markers.forEach(marker => { marker.point.market_cap_atomic = '9007199254740993001'; });
  // Subtract the exact baseline before Number conversion so adjacent atomic units remain visible.
  const view = marketViewport(chart, false);
  expect(view.data).toHaveLength(3);
  expect(view.data[1].y).toBeGreaterThan(view.data[0].y);
  expect(view.rank.has(chart.markers[2].point.position.boundary_ordinal)).toBe(true);
});
it('restricts local trade zoom to retained surrounding states without modifying the fetched history', () => {
  const chart = chartFixture();
  chart.points = Array.from({ length: 20 }, (_, index) => ({ ...point(index), block_time_ns: String(BigInt(index) * 10_000_000_000n) }));
  chart.markers.forEach((marker, index) => { marker.point = chart.points[8 + index]; });
  const view = marketViewport(chart, true);
  // One surrounding point on each side preserves the original step-series context.
  expect(view.data.length).toBeLessThan(chart.points.length);
  expect(view.data.every(item => chart.points.some(point => point.position === item.position))).toBe(true);
  expect(chart.points).toHaveLength(20);
});
it.each(['block_time_ns', 'market_cap_atomic'] as const)('rejects out-of-contract chart %s before formatting', key => {
  const chart = chartFixture(); chart.points[0][key] = String(1n << (key === 'block_time_ns' ? 63n : 128n));
  expect(() => parseChart(chart, runId, entryFixture())).toThrow();
});
