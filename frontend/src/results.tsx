import { t, useLocale, localeTag } from './i18n';
import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { ArrowLeft, ArrowUpRight, ShieldCheck, RefreshCw } from 'lucide-react';
import { api, errorText, queryClient } from './api';
// All strategies use these same view contracts, cards, charts and tables.
import { digestSchema, parseAnalytics, parseChart, parseDashboard, parsePage, parseSummary, type Cursor, type Entry, type Summary } from './result-contracts';
import { atomic, familyLabel, label, shortId } from './format';
import { Badge, Button, Card, Empty, Failure, Loading, Overlay, PageTitle, Pager, TabPanel, Tabs } from './ui';
import { DataTable, type TableColumn } from './table';
import { resultRatios } from './ratios';

// Heavy charts load only when a result view needs them, keeping the overview shell small.
const DistributionChart = lazy(() => import('./charts').then(module => ({ default: module.DistributionChart })));
const AmountChart = lazy(() => import('./charts').then(module => ({ default: module.AmountChart })));
const MarketHistoryChart = lazy(() => import('./charts').then(module => ({ default: module.MarketHistoryChart })));
const tabs: [string, string][] = [['overview', "Overview"], ['entries', "Entries"], ['exits', "Exits"], ['trades', "Trades"], ['verification', "Verification"]];

// Exact run identity owns the entire result selection and its independent query lifetimes.
export function StrategyResults({ runId, demo = false }: { runId: string; demo?: boolean }) {
  const locale = useLocale();
  const valid = digestSchema.safeParse(runId).success;
  const [tab, setTab] = useState('overview');
  const [selected, setSelected] = useState<Entry | null>(null);
  const [page, setPage] = useState<{ after: Cursor | null; trail: (Cursor | null)[]; index: number }>({ after: null, trail: [], index: 0 });
  // Summary and current page have separate cache entries: the first page is not retained forever.
  const summary = useQuery({ queryKey: ['strategy-summary', runId], enabled: false,
    queryFn: async ({ signal }) => parseSummary(await api(`/api/v1/run-artifacts/${runId}/strategy-summary`, { signal }), runId) });
  // Initial paint binds summary and rows in one response before granting either display authority.
  const entries = useQuery({ queryKey: ['entries', runId, page.after], enabled: valid, queryFn: async ({ signal }) => {
    if (page.after === null && !queryClient.getQueryData(['strategy-summary', runId])) {
      const response = parseDashboard(await api(`/api/v1/run-artifacts/${runId}/strategy-dashboard?limit=25`, { signal }), runId);
      signal.throwIfAborted();
      // An aborted old navigation cannot seed the new selection through a late transport response.
      queryClient.setQueryData(['strategy-summary', runId], response.summary);
      return response.entries;
    }
    // Cursor navigation requests only one bounded page, without reloading global metadata.
    const query = new URLSearchParams({ limit: '25' });
    if (page.after) { query.set('after_target_boundary_ordinal', page.after.target_boundary_ordinal); query.set('after_roundtrip_id', page.after.roundtrip_id); }
    return parsePage(await api(`/api/v1/run-artifacts/${runId}/entries?${query}`, { signal }), page.after);
  } });
  // Optional audit scan admission cannot hide independently available verified scalar metadata.
  useEffect(() => { if (valid && entries.isError && !summary.data) void summary.refetch(); }, [valid, entries.isError, summary.data, summary.refetch]);
  const analytics = useQuery({ queryKey: ['analytics', runId], enabled: valid && !!summary.data,
    queryFn: async ({ signal }) => parseAnalytics(await api(`/api/v1/run-artifacts/${runId}/analytics`, { signal }), runId) });
  const groups = Object.fromEntries(analytics.data?.distributions.map(group => [group.key, group]) ?? []);
  const metrics = Object.fromEntries(summary.data?.metrics.map(metric => [metric.key, metric.value]) ?? []);
  // Page-local sort/search keeps the canonical cursor order intact on the server.
  const columns = useMemo<TableColumn<Entry>[]>(() => [
    { id: 'asset', title: t("Token / entry"), value: row => row.asset_id, render: row => <button className="table-link" onClick={() => setSelected(row)}><strong>{row.asset_id ? shortId(row.asset_id, 10) : shortId(row.entry_id)}</strong><small>{row.actor_role === 'creator' ? t("Creator") : row.actor_role === 'signing_wallet' ? t("Wallet") : t("Order")} {row.actor_id ? shortId(row.actor_id) : ''}</small></button> },
    { id: 'boundary', title: t("Signal position"), value: row => BigInt(row.boundary_ordinal), render: row => <code>{row.boundary_ordinal}</code> },
    { id: 'status', title: t("Result"), value: row => row.status, render: row => <Badge tone={row.status === 'CLOSED' || row.status === 'FILLED' ? 'positive' : ''}>{row.status}</Badge> },
    // Exact integer comparison is essential for monetary sorting, including negative values.
    { id: 'pnl', title: t("Realized PnL"), value: row => row.realized_cash_pnl_atomic === null ? null : BigInt(row.realized_cash_pnl_atomic), render: row => <span className="money" title={`${row.realized_cash_pnl_atomic ?? t("Unavailable")} atomic`}>{atomic(row.realized_cash_pnl_atomic)}{row.realized_cash_pnl_atomic !== null && ' SOL'}</span> },
    { id: 'attempts', title: t("Attempts"), value: row => row.attempts.length, render: row => row.attempts.length },
    { id: 'details', title: '', render: row => <Button aria-label={t("Details {0}", [row.asset_id ?? row.entry_id])} onClick={() => setSelected(row)}><ArrowUpRight size={16} /></Button> },
  ], [locale]);
  // Invalid route IDs render no prior run data and never reach an API query.
  if (!valid) return <Failure message={t("An exact SHA-256 artifact ID is required for this result.")} />;
  return <><Link to="/runs" className="back-link"><ArrowLeft size={15} /> {t("All runs")}</Link>
    <PageTitle eyebrow={summary.data ? familyLabel(summary.data.family) : t("Run analytics")} title={t("Strategy results")}><Button onClick={() => { void entries.refetch(); void analytics.refetch(); }}><RefreshCw size={15} /> {t("Refresh")}</Button></PageTitle>
    {summary.data && <div className="result-identity"><Badge tone="positive"><ShieldCheck size={13} /> {t(demo ? "Test result · prepared offline" : "Verified result")}</Badge><code title={runId}>{shortId(runId, 14)}</code><span>{summary.data.network_id}</span></div>}
    {/* This assumption remains visible on every tab and alongside each trade detail. */}
    {summary.data?.execution_mode === 'EXOGENOUS_VIRTUAL_SETTLEMENT' && <div className="notice synthetic"><strong>{t("Synthetic execution model")}</strong><p>{t("Some proceeds may come from a virtual SOL source and may be reused by the wallet. This result does not prove that such a sale could execute on-chain.")}</p></div>}
    {entries.isError && <Failure message={errorText(entries.error)} retry={() => void entries.refetch()} />}
    {summary.isError && <Failure message={errorText(summary.error)} retry={() => void summary.refetch()} />}
    {!summary.data && !entries.isError && <Loading />}
    {/* The headline and every tab retain the same accounting and availability vocabulary. */}
    {summary.data && <><div className="metrics-grid">{['realized_cash_pnl_atomic', 'economic_pnl_atomic', 'entry_count', 'closed_position_count'].map(key => <MetricCard key={key} name={key} summary={summary.data!} />)}</div>
      <Tabs value={tab} onChange={setTab} tabs={tabs}>
        <TabPanel value="overview"><div className="section-intro"><h2>{t("The complete run")}</h2><span>{t("Totals across the result")}</span></div>
          <Card><h3>{t("Ratios and coverage")}</h3><div className="fact-grid">{resultRatios(summary.data!).map(ratio => <Fact key={ratio.name} name={ratio.name} value={ratio.value} title={ratio.detail} />)}</div><p className="subtle">{t("Ratios use the whole-run summary. Hover over a value to see its denominator.")}</p></Card>
          {/* Global distributions have their own admitted scan; fee cards use stored scalar totals. */}
          <Suspense fallback={<Loading />}><div className="charts-grid"><DistributionChart title={t("Entry outcomes")} group={groups.entry_outcomes} donut /><DistributionChart title={t("Realized outcomes")} group={groups.realized_pnl} donut /></div>
            <div className="charts-grid"><AmountChart title={t("Fees")} items={[
              { label: t("Protocol"), value: metrics.protocol_fee_paid_atomic ?? null }, { label: t("Creator"), value: metrics.creator_fee_paid_atomic ?? null },
              { label: t("Network"), value: metrics.network_base_fee_paid_atomic ?? null }, { label: 'Priority', value: metrics.network_priority_fee_paid_atomic ?? null },
            ]} /><AmountChart title={t("Sell funding sources")} items={[{ label: t("Reserves"), value: metrics.venue_funded_sell_atomic ?? null }, { label: t("Synthetic"), value: metrics.synthetic_funded_sell_atomic ?? null }]} /></div></Suspense>
          {/* Full valuation, locked deposits and cashback remain separate accounting facts. */}
          <Card><div className="card-heading"><h3>{t("Valuation, accounts and cashback")}</h3><Badge>{metrics.valuation_status ?? t("Not applicable")}</Badge></div><div className="fact-grid">{['valued_economic_pnl_subtotal_atomic', 'unvalued_open_position_count', 'account_deposit_paid_atomic', 'account_deposit_refunded_atomic', 'account_deposit_locked_atomic', 'cashback_receivable_atomic'].map(key => <MetricFact key={key} name={key} summary={summary.data!} />)}</div></Card>
        </TabPanel>
        {/* Entry and exit analytics share layouts; only verified distributions vary by strategy. */}
        <TabPanel value="entries"><div className="section-intro"><h2>{t("Entry analytics")}</h2><span>{t("Signals, attempts and quote quality")}</span></div><Suspense fallback={<Loading />}><div className="charts-grid"><DistributionChart title={t("Entry outcomes")} group={groups.entry_outcomes} /><DistributionChart title="Reference → landing" group={groups.quote_slippage} /></div><DistributionChart title={t("Rejection and failure reasons")} group={groups.failure_reasons} /></Suspense><p className="subtle">{t("Reference and landing comparisons include attempts with both quotes. A quote does not imply a fill.")}</p></TabPanel>
        <TabPanel value="exits"><div className="section-intro"><h2>{t("Exit analytics")}</h2><span>{t("Decision reasons and actual attempts")}</span></div><Suspense fallback={<Loading />}><div className="charts-grid"><DistributionChart title={t("Exit reasons")} group={groups.exit_reasons} /><DistributionChart title={t("Position states")} group={groups.position_outcomes} /></div><DistributionChart title={t("All attempt outcomes")} group={groups.attempt_outcomes} /></Suspense></TabPanel>
        <TabPanel value="trades"><Card><div className="card-heading"><h3>{t("Entries and trades")}</h3><span>{t("25 records per page")}</span></div>{entries.isFetching ? <Loading /> : <DataTable rows={entries.data?.items ?? []} columns={columns} name={t("Entries and trades")} searchText={row => `${row.asset_id} ${row.actor_id} ${row.status} ${row.entry_id}`} />}
          <Pager index={page.index} count={entries.data?.items.length ?? 0} busy={entries.isFetching} previous={page.trail.length ? () => setPage(old => ({ after: old.trail.at(-1) ?? null, trail: old.trail.slice(0, -1), index: old.index - 1 })) : undefined} next={entries.data?.next_cursor ? () => setPage(old => ({ after: entries.data!.next_cursor, trail: [...old.trail, old.after].slice(-128), index: old.index + 1 })) : undefined} />
        </Card></TabPanel>
        {/* Exact IDs and the complete scalar set remain inspectable without raw artifact downloads. */}
        <TabPanel value="verification"><Card><h3>{t("Identity and reproducibility")}</h3><div className="fact-grid"><Fact name={t("Result artifact")} value={runId} /><Fact name={t("Logical run")} value={summary.data.logical_run_id} /><Fact name="Canonical result hash" value={summary.data.canonical_result_hash} /><Fact name="Audit hash" value={summary.data.audit_hash} /><Fact name="Execution mode" value={summary.data.execution_mode} /><Fact name={t("Position schema")} value={summary.data.position_schema_id} /></div><Button asChild><Link to={`/artifacts/${runId}`}>{t("Open manifest and lineage")} <ArrowUpRight size={16} /></Link></Button></Card><Card><h3>{t("All stored metrics")}</h3><div className="fact-grid">{summary.data.metrics.map(metric => <MetricFact key={metric.key} name={metric.key} summary={summary.data!} />)}</div></Card></TabPanel>
      </Tabs>
      {analytics.isFetching && <p className="subtle" role="status">{t("Loading whole-run analytics…")}</p>}
      {analytics.isError && <Failure message={t("Additional analytics: {0}", [errorText(analytics.error)])} retry={() => void analytics.refetch()} />}
    </>}
    {/* A separate keyed overlay releases its history request on close or selection change. */}
    {selected && <EntryDetail key={`${runId}:${selected.entry_id}`} runId={runId} entry={selected} synthetic={summary.data?.execution_mode === 'EXOGENOUS_VIRTUAL_SETTLEMENT'} onClose={() => setSelected(null)} />}
  </>;
}

// Headline cards retain explicit unavailable and inapplicable states alongside the displayed unit.
function MetricCard({ name, summary }: { name: string; summary: Summary }) {
  useLocale();
  const metric = summary.metrics.find(item => item.key === name);
  const value = metric?.value ?? null;
  return <Card className="metric-card"><span>{label(name)}</span><strong className={value && /^-/.test(value) ? 'negative-text' : ''} title={value ?? t("No value")}>{value === null ? '—' : metric?.unit === 'atomic' ? atomic(value) : BigInt(value).toLocaleString(localeTag())}</strong><small>{metric?.availability === 'NOT_APPLICABLE' ? t("Not applicable to this strategy") : value === null ? t("Full valuation unavailable") : metric?.unit === 'atomic' ? t("SOL · exact amounts in details") : t("Whole run")}</small></Card>;
}
// Detailed scalar facts expose exact values in tooltips while using compact human formatting.
function MetricFact({ name, summary }: { name: string; summary: Summary }) {
  useLocale();
  const metric = summary.metrics.find(item => item.key === name);
  const text = metric?.value == null ? metric?.availability === 'NOT_APPLICABLE' ? t("Not applicable") : t("Unavailable") : metric.unit === 'atomic' ? `${atomic(metric.value)} SOL` : metric.value;
  return <Fact name={label(name)} value={text} title={metric?.value ?? undefined} />;
}
// Shared facts render text, never artifact-controlled markup.
export function Fact({ name, value, title }: { name: string; value: string; title?: string }) {
  useLocale(); return <div className="fact"><span>{name}</span><strong title={title}>{value}</strong></div>; }

// One selected entry binds the bounded historical query and all actual execution attempts.
export function EntryDetail({ runId, entry, synthetic = false, onClose }: { runId: string; entry: Entry; synthetic?: boolean; onClose: () => void }) {
  useLocale();
  const chart = useQuery({ queryKey: ['entry-chart', runId, entry.entry_id, entry.boundary_ordinal], enabled: entry.chart_availability === 'AVAILABLE',
    queryFn: async ({ signal }) => parseChart(await api(`/api/v1/run-artifacts/${runId}/entries/${entry.entry_id}/chart?boundary_ordinal=${entry.boundary_ordinal}`, { signal }), runId, entry) });
  return <Overlay title={entry.asset_id ?? shortId(entry.entry_id)} onClose={onClose}><div className="result-identity"><Badge>{entry.status}</Badge><code>{shortId(entry.entry_id, 14)}</code></div>
    {synthetic && <div className="synthetic-warning">{t("Synthetic mode: virtual SOL funding at sale. The result is not executable on-chain.")}</div>}
    {chart.isFetching && <Loading />}{chart.isError && <Failure message={errorText(chart.error)} retry={() => void chart.refetch()} />}
    {entry.chart_availability !== 'AVAILABLE' && <Card><Empty title={t("Historical chart unavailable")} detail={t("The result lacks the verified data required for this chart type.")} /></Card>}
    {/* Chart availability is independent of stored result detail; a failed scan never erases evidence. */}
    {chart.data && <Suspense fallback={<Loading />}><MarketHistoryChart chart={chart.data} /></Suspense>}
    {/* Every attempt is a separate row so retries and pre-submit failures remain inspectable. */}
    <Card><h3>{t("Signal → decision → fill")}</h3><div className="attempt-timeline"><div><span className="timeline-dot signal" /><strong>{t("Signal")}</strong><code>{entry.boundary_ordinal}</code></div>{entry.attempts.map(attempt => <div key={attempt.number}><span className={`timeline-dot ${attempt.status === 'FILLED' ? 'filled' : 'failed'}`} /><strong>{attempt.side} {t("· attempt")} {attempt.number}</strong><Badge>{attempt.status}</Badge><small>{t("Decision:")} {attempt.decision_boundary}</small><small>{t("Fill:")} {attempt.landing_boundary ?? t("Not submitted")}</small>{attempt.failure_code && <small>{attempt.failure_code}</small>}</div>)}</div></Card>
    <Card><h3>{t("Quotes and outcomes")}</h3><div className="table-scroll"><table><thead><tr><th>{t("Attempt")}</th><th>Reference out, atomic</th><th>Landing out, atomic</th><th>Minimum out, atomic</th><th>{t("Result")}</th></tr></thead><tbody>{entry.attempts.map(attempt => <tr key={attempt.number}><td>{attempt.side} {attempt.number}</td><td>{attempt.reference_out_atomic ?? '—'}</td><td>{attempt.landing_out_atomic ?? '—'}</td><td>{attempt.minimum_out_atomic ?? '—'}</td><td>{attempt.failure_code ?? attempt.status}</td></tr>)}</tbody></table></div></Card>
    {/* The original family detail remains available without projecting away strategy-specific fields. */}
    <Card><h3>{t("Stored entry data")}</h3><FactTree value={entry.details} /></Card>
  </Overlay>;
}

// Bounded metadata is inspected with disclosure nodes rather than an editable JSON surface.
export function FactTree({ value, depth = 0 }: { value: unknown; depth?: number }) {
  useLocale();
  if (value === null || value === undefined) return <span className="subtle">{t("Unavailable")}</span>;
  if (typeof value !== 'object') return <code className="breakable">{String(value)}</code>;
  if (depth > 12) return <span>{t("Presentation depth reached")}</span>;
  const entries = Object.entries(value);
  // Native disclosure keeps detailed canonical evidence accessible without a JSON editor.
  return <div className="fact-tree">{entries.map(([key, item]) => typeof item === 'object' && item !== null ? <details key={key}><summary>{label(key)}{Array.isArray(item) ? ` · ${item.length}` : ''}</summary><FactTree value={item} depth={depth + 1} /></details> : <div className="tree-value" key={key}><span>{label(key)}</span><FactTree value={item} depth={depth + 1} /></div>)}</div>;
}
