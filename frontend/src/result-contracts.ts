import { t } from './i18n';
import { z } from 'zod';
import { ApiError } from './api';
import { resultRatios } from './ratios';

// Bounded decimal strings are the shared API contract for money and exact chain coordinates.
const integer = z.string().regex(/^-?(?:0|[1-9]\d*)$/).max(40);
const unsigned = integer.refine(value => BigInt(value) >= 0n);
export const digestSchema = z.string().regex(/^[0-9a-f]{64}$/);
const availability = z.enum(['AVAILABLE', 'UNAVAILABLE', 'NOT_APPLICABLE']);

// Shared scalars declare availability independently of units and display labels.
const metricSchema = z.object({ key: z.string().max(96), value: z.string().max(128).nullable(),
  unit: z.enum(['atomic', 'count', 'text']), availability }).strict();
const attemptSchema = z.object({ side: z.enum(['BUY', 'SELL', 'ENTRY']), number: z.number().int().min(0).max(4),
  status: z.enum(['FILLED', 'FAILED', 'REJECTED']), decision_boundary: unsigned, landing_boundary: unsigned.nullable(),
  // These outputs describe separate causal quotes, not interchangeable realized proceeds.
  reference_out_atomic: unsigned.nullable(), landing_out_atomic: unsigned.nullable(), minimum_out_atomic: unsigned.nullable(),
  failure_code: z.string().max(256).nullable() }).strict();

export const entrySchema = z.object({ entry_id: digestSchema, boundary_ordinal: unsigned,
  signal_event_id: digestSchema.nullable(), asset_id: z.string().nullable(), quote_asset_id: z.string().nullable(),
  actor_role: z.enum(['creator', 'signing_wallet']).nullable(), actor_id: z.string().nullable(), status: z.string(),
  // A nullable result is never replaced by zero when the position cannot be valued.
  exit_reason: z.string().nullable(), realized_cash_pnl_atomic: integer.nullable(), economic_pnl_atomic: integer.nullable(),
  valuation_status: z.string(), attempts: z.array(attemptSchema).max(5), chart_availability: availability,
  details: z.record(z.unknown()) }).strict().superRefine((entry, context) => {
    let previous = -1;
    // A quote cannot masquerade as a fill, and a rejected order has no actual landing.
    for (const attempt of entry.attempts) {
      const invalid = attempt.number <= previous || (attempt.status === 'REJECTED') !== (attempt.landing_boundary === null) || (attempt.status === 'FILLED') !== (attempt.failure_code === null);
      if (invalid) context.addIssue({ code: 'custom', message: t("Inconsistent attempt outcome") });
      previous = attempt.number;
    }
  });
export type Entry = z.infer<typeof entrySchema>;

// Composite continuation preserves the exact server order across page-local table operations.
const cursorSchema = z.object({ target_boundary_ordinal: unsigned, roundtrip_id: digestSchema }).strict();
export type Cursor = z.infer<typeof cursorSchema>;
export const entryPageSchema = z.object({ items: z.array(entrySchema).max(200), next_cursor: cursorSchema.nullable() }).strict();
export type EntryPage = z.infer<typeof entryPageSchema>;
// Bounded provenance accompanies every family without transporting an executable RunSpec.
export const summarySchema = z.object({ run_artifact_id: digestSchema, logical_run_id: digestSchema,
  family: z.enum(['PUMPFUN_SNIPING', 'PUMPFUN_COPY_BUY', 'FIRST_SWAP']), network_id: z.string(), position_schema_id: z.string(),
  execution_mode: z.string(), canonical_result_hash: digestSchema, audit_hash: digestSchema, metrics: z.array(metricSchema).max(128) }).strict();
export type Summary = z.infer<typeof summarySchema>;

// Whole-run distributions are a separate versioned contract from the initial bounded page.
const dashboardSchema = z.object({ contract_schema: z.literal('strategy-results/v1'), summary: summarySchema, entries: entryPageSchema }).strict();
export const analyticsSchema = z.object({ contract_schema: z.literal('strategy-analytics/v1'), run_artifact_id: digestSchema,
  entry_count: unsigned, distributions: z.array(z.object({ key: z.string(), population: z.string(), total: unsigned,
    items: z.array(z.object({ label: z.string().max(256), count: unsigned }).strict()).max(256) }).strict()).max(16) }).strict();
export type Analytics = z.infer<typeof analyticsSchema>;

// Verify summary authority before it can seed the immutable run cache.
export function parseSummary(raw: unknown, runId: string): Summary {
  const value = summarySchema.parse(raw);
  if (value.run_artifact_id !== runId || new Set(value.metrics.map(item => item.key)).size !== value.metrics.length) throw invalid();
  for (const metric of value.metrics) {
    if ((metric.value === null) !== (metric.availability !== 'AVAILABLE')) throw invalid();
    // Signed PnL is allowed; counts, deposits, fees and funding cannot be negative.
    if (metric.value !== null && metric.unit !== 'text') {
      if (metric.unit === 'count' || /fee_paid|deposit_|funded_sell|gross_sell_settlement|cashback_receivable/.test(metric.key)) unsigned.parse(metric.value);
      else integer.parse(metric.value);
    }
  }
  // Settlement funding is a decomposition of gross payout, never of PnL.
  const metrics = Object.fromEntries(value.metrics.map(item => [item.key, item.value]));
  const gross = metrics.gross_sell_settlement_atomic, venue = metrics.venue_funded_sell_atomic, synthetic = metrics.synthetic_funded_sell_atomic;
  if (gross != null && venue != null && synthetic != null && BigInt(gross) !== BigInt(venue) + BigInt(synthetic)) throw invalid();
  resultRatios(value);
  return value;
}

// A page cannot skip unseen entries, repeat rows or exceed the requested limit.
export function parsePage(raw: unknown, after: Cursor | null, limit = 25): EntryPage {
  const page = entryPageSchema.parse(raw);
  if (page.items.length > limit) throw invalid();
  let previous = after ? `${after.target_boundary_ordinal.padStart(20, '0')}:${after.roundtrip_id}` : '';
  // Padded UInt64 coordinates preserve numeric ordering without Number coercion.
  for (const entry of page.items) {
    const key = `${entry.boundary_ordinal.padStart(20, '0')}:${entry.entry_id}`;
    if (key <= previous || BigInt(entry.boundary_ordinal) >= 1n << 64n) throw invalid();
    previous = key;
  }
  // A continuation cursor identifies the last returned row, never an unseen position.
  if (page.next_cursor) {
    const last = page.items.at(-1);
    if (!last || last.entry_id !== page.next_cursor.roundtrip_id || last.boundary_ordinal !== page.next_cursor.target_boundary_ordinal) throw invalid();
  }
  return page;
}

// Validate both halves before exposing the first response to the component.
export function parseDashboard(raw: unknown, runId: string) {
  const value = dashboardSchema.parse(raw);
  return { summary: parseSummary(value.summary, runId), entries: parsePage(value.entries, null) };
}
// A distribution is complete only when distinct category counts reconcile to its denominator.
export function parseAnalytics(raw: unknown, runId: string): Analytics {
  const value = analyticsSchema.parse(raw);
  if (value.run_artifact_id !== runId || new Set(value.distributions.map(group => group.key)).size !== value.distributions.length) throw invalid();
  for (const group of value.distributions) {
    if (new Set(group.items.map(item => item.label)).size !== group.items.length) throw invalid();
    if (group.items.reduce((sum, item) => sum + BigInt(item.count), 0n) !== BigInt(group.total)) throw invalid();
  }
  return value;
}

// History coordinates are complete transaction boundaries, not instruction-level synthetic times.
const positionSchema = z.object({ network_id: z.string(), position_schema_id: z.string(),
  block_ordinal: z.number().int().min(0).max(2 ** 32 - 1), transaction_index: z.number().int().min(-1).max(2 ** 32 - 2),
  event_index: z.number().int().nullable().optional(), boundary_ordinal: unsigned }).strict();
const pointSchema = z.object({ position: positionSchema, block_time_ns: unsigned, market_cap_atomic: unsigned,
  lifecycle: z.enum(['ACTIVE', 'COMPLETED', 'MIGRATED']) }).strict();
// Actual attempts remain distinct from source observations and from non-executable quotes.
const markerSchema = z.object({ kind: z.enum(['SIGNAL', 'BUY', 'SELL']), status: z.enum(['OBSERVED_SOURCE', 'FILLED', 'FAILED', 'REJECTED']),
  attempt: z.number().int().min(0).max(4).nullable(), point: pointSchema, failure_code: z.string().nullable() }).strict();
// Static size limits match the bounded post-run history port.
const chartSchema = z.object({ contract_schema: z.literal('strategy-market-cap/v1'), run_artifact_id: digestSchema,
  entry_id: digestSchema, snapshot_id: digestSchema, asset_id: z.string(), quote_asset_id: z.literal('SOL'),
  market_cap_policy: z.literal('post-transaction-total-supply-market-cap-lamports-floor/v1'),
  points: z.array(pointSchema).min(1).max(4000), markers: z.array(markerSchema).min(1).max(6) }).strict();
export type MarketChart = z.infer<typeof chartSchema>;

// Run, entry and pair binding prevents stale or substituted history from gaining authority.
export function parseChart(raw: unknown, runId: string, entry: Entry): MarketChart {
  const chart = chartSchema.parse(raw);
  if (chart.run_artifact_id !== runId || chart.entry_id !== entry.entry_id || chart.asset_id !== entry.asset_id || chart.quote_asset_id !== entry.quote_asset_id) throw invalid();
  // The leading marker must be the exact stored signal before attempt correspondence is checked.
  const signal = chart.markers[0];
  if (signal.kind !== 'SIGNAL' || signal.status !== 'OBSERVED_SOURCE' || signal.attempt !== null || signal.failure_code !== null || signal.point.position.boundary_ordinal !== entry.boundary_ordinal) throw invalid();
  if (chart.markers.length !== entry.attempts.length + 1) throw invalid();
  // Marker coordinates and outcomes must match the selected result, even during rapid token changes.
  chart.markers.slice(1).forEach((marker, index) => {
    const attempt = entry.attempts[index];
    if (marker.kind !== attempt.side || marker.attempt !== attempt.number || marker.status !== attempt.status || marker.failure_code !== attempt.failure_code) throw invalid();
    if (marker.point.position.boundary_ordinal !== (attempt.landing_boundary ?? attempt.decision_boundary)) throw invalid();
    if (marker.status === 'FILLED' && marker.point.lifecycle !== 'ACTIVE') throw invalid();
  });
  // Source times may repeat, but complete transaction boundaries must increase strictly.
  let prior = -1n, time = -1n, inactive = false;
  for (const point of chart.points) {
    const boundary = BigInt(point.position.boundary_ordinal), nextTime = BigInt(point.block_time_ns);
    if (boundary <= prior || nextTime < time) throw invalid();
    if (inactive && point.lifecycle === 'ACTIVE') throw invalid();
    // Once the original curve becomes terminal, later history cannot revive that market.
    inactive = point.lifecycle !== 'ACTIVE';
    prior = boundary; time = nextTime;
  }
  // Every retained point and marker must share the same bounded historical coordinate space.
  const first = chart.points[0], last = chart.points.at(-1)!;
  for (const point of [...chart.points, ...chart.markers.map(marker => marker.point)]) {
    // Retain the original UInt64/Int64/UInt128 bounds before any browser date or axis formatting.
    if (BigInt(point.position.boundary_ordinal) >= 1n << 64n || BigInt(point.block_time_ns) >= 1n << 63n || BigInt(point.market_cap_atomic) >= 1n << 128n) throw invalid();
    if (point.position.network_id !== first.position.network_id || point.position.position_schema_id !== first.position.position_schema_id || point.position.event_index != null) throw invalid();
    if (BigInt(point.position.boundary_ordinal) < BigInt(first.position.boundary_ordinal) || BigInt(point.position.boundary_ordinal) > BigInt(last.position.boundary_ordinal)) throw invalid();
  }
  return chart;
}

function invalid() { return new ApiError('INVALID_RESULT_RESPONSE', t("Result data failed consistency validation.")); }
