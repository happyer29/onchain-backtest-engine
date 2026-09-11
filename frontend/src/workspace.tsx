import { t, useLocale } from './i18n';
import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowUpRight, CheckCircle2, Cpu, Database, HardDrive, Plus, RefreshCw, Workflow } from 'lucide-react';
import { api, digest, errorText, queryClient, type Schema } from './api';
// Operational pages consume bounded metadata and never read execution artifacts directly.
import { dateTime, familyLabel, isoNanoseconds, nanosecondTime, shortId } from './format';
import { Badge, Button, Card, Empty, Failure, Loading, Overlay, PageTitle, Pager } from './ui';
import { DataTable, type TableColumn } from './table';
import { Fact, FactTree } from './results';
import { digestSchema } from './result-contracts';
import comparisonMetrics from './comparison-metrics.json';

// Lineage is an optional heavy view; operational pages load only their own bounded data.
const LineageGraph = lazy(() => import('./lineage').then(module => ({ default: module.LineageGraph })));
const active = new Set(['QUEUED', 'STARTING', 'RUNNING']);
const producing = new Set(['RUN_BACKTEST', 'RUN_SWEEP']);
const watchedRunJobs = new Set<string>();
// A bounded in-memory watcher refreshes results only after observed run-producing completion.
export function recordSubmission(job: Schema<'JobResponse'>) {
  if (producing.has(job.job_type)) watchedRunJobs.add(job.job_id);
  // Keep operational watcher metadata bounded; leaving the page never cancels a job.
  if (watchedRunJobs.size > 128) watchedRunJobs.delete(watchedRunJobs.values().next().value!);
  void queryClient.invalidateQueries({ queryKey: ['jobs'] });
}

// Hidden tabs pause operational polling without changing durable job execution.
export function useVisible() {
  const [visible, setVisible] = useState(document.visibilityState !== 'hidden');
  useEffect(() => { const update = () => setVisible(document.visibilityState !== 'hidden'); document.addEventListener('visibilitychange', update); return () => document.removeEventListener('visibilitychange', update); }, []);
  return visible;
}

// Only the current server page participates in adaptive polling and completion observation.
function useJobs(cursor: string | null, state: string) {
  const visible = useVisible();
  const previous = useRef(new Map<string, string>());
  const query = useQuery<Schema<'JobListResponse'>>({ queryKey: ['jobs', cursor, state], enabled: visible, refetchIntervalInBackground: false,
    refetchInterval: query => !visible ? false : query.state.data?.items.some(job => active.has(job.state)) ? 2000 : 12000,
    queryFn: ({ signal }) => api<Schema<'JobListResponse'>>(`/api/v1/jobs?${new URLSearchParams({ limit: '20', ...(cursor ? { cursor } : {}), ...(state ? { state } : {}) })}`, { signal }) });
  useEffect(() => {
    // Runs refresh only on an observed run-producing success, not on every jobs poll.
    for (const job of query.data?.items ?? []) {
      const before = previous.current.get(job.job_id);
      if (producing.has(job.job_type) && job.state === 'SUCCEEDED' && (watchedRunJobs.has(job.job_id) || (before !== undefined && before !== 'SUCCEEDED'))) {
        watchedRunJobs.delete(job.job_id); void queryClient.invalidateQueries({ queryKey: ['runs'] });
      }
    }
    // Retain one page of prior states, not a growing history of operational jobs.
    previous.current = new Map(query.data?.items.map(job => [job.job_id, job.state]) ?? []);
  }, [query.data]);
  return query;
}

// Immutable results refresh on explicit action or successful jobs, never a continuous timer.
function useRuns(cursor: string | null) {
  return useQuery({ queryKey: ['runs', cursor], queryFn: ({ signal }) => api<Schema<'RunListResponse'>>(`/api/v1/runs?${new URLSearchParams({ limit: '10', ...(cursor ? { cursor } : {}) })}`, { signal }) });
}
// Navigation stores at most 128 opaque cursors, never earlier result pages.
function useCursor() {
  const [page, setPage] = useState<{ cursor: string | null; trail: (string | null)[]; index: number }>({ cursor: null, trail: [], index: 0 });
  return { page, reset: () => setPage({ cursor: null, trail: [], index: 0 }),
    next: (cursor: string) => setPage(old => ({ cursor, trail: [...old.trail, old.cursor].slice(-128), index: old.index + 1 })),
    previous: () => setPage(old => ({ cursor: old.trail.at(-1) ?? null, trail: old.trail.slice(0, -1), index: old.index - 1 })) };
}

// The landing page combines current resources, bounded recent results and the live queue.
export function Overview() {
  useLocale();
  return <><PageTitle eyebrow={t("Workspace")} title={t("Work overview")}><Button asChild tone="primary"><Link to="/launch"><Plus size={17} /> {t("New run")}</Link></Button></PageTitle>
    <div className="welcome-card"><div><Badge>{t("Explore. Verify. Compare.")}</Badge><h2>{t("Every strategy.")}<br />{t("One complete picture.")}</h2><p>{t("Run backtests and explore entries, execution and results in one workspace.")}</p><div className="actions"><Button asChild tone="primary"><Link to="/launch?strategy=sniping">{t("Launch Sniping")} <ArrowUpRight size={16} /></Link></Button><Button asChild><Link to="/launch?strategy=copy">Copy Buy <ArrowUpRight size={16} /></Link></Button></div></div><div className="welcome-symbol" aria-hidden="true"><Workflow size={140} strokeWidth={1} /></div></div>
    <Resources compact /><div className="section-intro"><h2>{t("Latest results")}</h2><Link to="/runs">{t("All runs →")}</Link></div><RunsPanel compact />
    <div className="section-intro"><h2>{t("Job queue")}</h2><Link to="/jobs">{t("Manage queue →")}</Link></div><JobsPanel compact />
  </>;
}

// Selection is independent from the paged queue; its overlay can follow a job leaving the filter.
export function JobsPanel({ compact = false }: { compact?: boolean }) {
  useLocale();
  const paging = useCursor();
  const [state, setState] = useState('');
  const [selected, setSelected] = useState<Schema<'JobResponse'> | null>(null);
  const [failure, setFailure] = useState('');
  // Mutation presentation is local, while admission and state transitions remain API-owned.
  const [busy, setBusy] = useState<string | null>(null);
  const query = useJobs(paging.page.cursor, state);
  // A failed/retried click reuses its idempotency key for the same observed job version.
  const retryKeys = useRef(new Map<string, string>());
  const acting = useRef(false);
  async function action(job: Schema<'JobResponse'>, action: 'cancel' | 'retry') {
    if (acting.current) return;
    acting.current = true;
    setBusy(job.job_id); setFailure('');
    // Synchronous admission closes the double-click gap before React renders disabled controls.
    const identity = `${job.job_id}:${job.state_version}:${action}`;
    const key = retryKeys.current.get(identity) ?? digest(); retryKeys.current.set(identity, key);
    if (retryKeys.current.size > 128) retryKeys.current.delete(retryKeys.current.keys().next().value!);
    // Stable keys preserve retry identity for a specific observed version of the durable job.
    try {
      const receipt = await api<Schema<'JobResponse'>>(`/api/v1/jobs/${job.job_id}/${action}`, { method: 'POST', key });
      recordSubmission(receipt); await query.refetch();
    } catch (error) { setFailure(errorText(error)); } finally { acting.current = false; setBusy(null); }
  }
  // Dates and statuses are display metadata; controls call the existing durable mutations.
  const columns: TableColumn<Schema<'JobResponse'>>[] = [
    { id: 'id', title: t("Job"), value: row => row.job_id, render: row => <button className="table-link" onClick={() => setSelected(row)}><strong>{row.job_type}</strong><small>{shortId(row.job_id)}</small></button> },
    { id: 'state', title: t("Status"), value: row => row.state, render: row => <Badge tone={row.state === 'SUCCEEDED' ? 'positive' : active.has(row.state) ? 'running' : ''}>{row.state}</Badge> },
    { id: 'submitted', title: t("Created"), value: row => BigInt(row.submitted_at_ns), render: row => nanosecondTime(row.submitted_at_ns) },
    { id: 'updated', title: t("Updated"), value: row => BigInt(row.updated_at_ns), render: row => nanosecondTime(row.updated_at_ns) },
    // Mutations always go through durable API operations and their observed server state.
    { id: 'actions', title: '', render: row => <div className="row-actions"><Button onClick={() => setSelected(row)}>{t("Events")}</Button>{active.has(row.state) ? <Button tone="danger" disabled={busy === row.job_id} onClick={() => void action(row, 'cancel')}>{t("Cancel")}</Button> : ['FAILED', 'CANCELLED', 'INTERRUPTED'].includes(row.state) && <Button disabled={busy === row.job_id} onClick={() => void action(row, 'retry')}>{t("Retry")}</Button>}</div> },
  ];
  // Compact overview and full queue share the same response and action behavior.
  return <>{!compact && <PageTitle eyebrow={t("Execution")} title={t("Job queue")}><Button onClick={() => void query.refetch()}><RefreshCw size={15} /> {t("Refresh")}</Button></PageTitle>}
    {failure && <Failure message={failure} />}{query.isError && <Failure message={errorText(query.error)} retry={() => void query.refetch()} />}
    <Card>{!compact && <div className="table-toolbar"><label>{t("State")} <select value={state} onChange={event => { setState(event.target.value); paging.reset(); }}><option value="">{t("All states")}</option>{['QUEUED', 'STARTING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED', 'INTERRUPTED'].map(state => <option key={state}>{state}</option>)}</select></label><small>{t("Updates automatically · paused in hidden tabs")}</small></div>}
      {query.isPending ? <Loading /> : <DataTable rows={query.data?.items ?? []} columns={columns} name={t("Job queue")} searchText={compact ? undefined : row => `${row.job_id} ${row.job_type} ${row.state}`} />}
      {!compact && <Pager index={paging.page.index} busy={query.isFetching} count={query.data?.items.length ?? 0} previous={paging.page.trail.length ? paging.previous : undefined} next={query.data?.next_cursor ? () => paging.next(query.data!.next_cursor!) : undefined} />}
    </Card>{selected && <JobEvents key={selected.job_id} job={selected} onClose={() => setSelected(null)} />}
  </>;
}

// Each event page observes its own durable status so terminal jobs stop polling independently.
export function JobEvents({ job, onClose }: { job: Schema<'JobResponse'>; onClose: () => void }) {
  useLocale();
  const [after, setAfter] = useState('0');
  const visible = useVisible();
  // Read durable state before events, so a terminal observation includes its committed transition.
  const query = useQuery<{ job: Schema<'JobResponse'>; events: Schema<'JobEventListResponse'> }>({ queryKey: ['job-events', job.job_id, after], enabled: visible,
    refetchInterval: query => visible && active.has(query.state.data?.job.state ?? job.state) && (query.state.data?.events.items.length ?? 0) < 50 ? 2000 : false,
    queryFn: async ({ signal }) => {
      const current = await api<Schema<'JobResponse'>>(`/api/v1/jobs/${job.job_id}`, { signal });
      const events = await api<Schema<'JobEventListResponse'>>(`/api/v1/jobs/${job.job_id}/events?after_event_id=${after}&limit=50`, { signal });
      return { job: current, events };
    } });
  // The selected list row can be stale or leave its filter; live state owns the overlay status.
  const events = query.data?.events;
  return <Overlay title={job.job_type} onClose={onClose}><Card><div className="card-heading"><code>{job.job_id}</code><Badge>{query.data?.job.state ?? job.state}</Badge></div>{query.isError && <Failure message={errorText(query.error)} retry={() => void query.refetch()} />}{query.isPending ? <Loading /> : <div className="event-list">{events?.items.map(event => <div key={event.event_id}><CheckCircle2 size={16} /><div><strong>{event.event_type}</strong><small>{nanosecondTime(event.created_at_ns)}</small>{event.progress && <><p>{event.progress.stage} · {event.progress.completed_units ?? '—'} / {event.progress.total_units ?? '—'}</p>{event.progress.total_units && <progress value={Number(event.progress.completed_units ?? 0)} max={Number(event.progress.total_units)} aria-label={event.progress.stage} />}</>}</div><code>v{event.state_version}</code></div>)}</div>}
    <div className="actions"><Button disabled={after === '0'} onClick={() => setAfter('0')}>{t("First page")}</Button><Button disabled={events?.items.length !== 50 || query.isFetching} onClick={() => setAfter(String(events!.items.at(-1)!.event_id))}>{t("Next events")}</Button><Button onClick={() => void query.refetch()}>{t("Refresh")}</Button></div>
  </Card></Overlay>;
}

// Run comparison is confined to already-computed scalars from the selected bounded page.
export function RunsPanel({ compact = false }: { compact?: boolean }) {
  useLocale();
  const paging = useCursor();
  const query = useRuns(paging.page.cursor);
  const [selected, setSelected] = useState<string[]>([]);
  const [metric, setMetric] = useState('canonical_result_hash');
  const [comparison, setComparison] = useState(false);
  // Exact completion timestamps and manifest IDs preserve the server-supplied newest-first order.
  const columns: TableColumn<Schema<'RunSummaryResponse'>>[] = [
    { id: 'select', title: '', render: row => <input type="checkbox" aria-label={t("Select run {0}", [row.run_artifact_id])} checked={selected.includes(row.run_artifact_id)} onChange={event => setSelected(old => event.target.checked ? [...old, row.run_artifact_id] : old.filter(id => id !== row.run_artifact_id))} /> },
    { id: 'id', title: t("Strategy / run"), value: row => row.logical_run_id, render: row => <Link className="table-link" to={`/runs/${row.run_artifact_id}`}><strong>{row.physical_settings.backend.includes('copy') ? familyLabel('PUMPFUN_COPY_BUY') : row.physical_settings.backend.includes('sniping') ? familyLabel('PUMPFUN_SNIPING') : familyLabel('FIRST_SWAP')}</strong><small>{shortId(row.run_artifact_id, 12)}</small></Link> },
    { id: 'started', title: t("Started"), value: row => isoNanoseconds(row.started_at), render: row => dateTime(row.started_at) },
    { id: 'completed', title: t("Completed"), value: row => isoNanoseconds(row.completed_at), render: row => dateTime(row.completed_at) },
    // Evidence stays visible without exposing result tables or treating hashes as event identities.
    { id: 'hash', title: t("Result"), render: row => <code title={row.canonical_result_hash}>{shortId(row.canonical_result_hash)}</code> },
    { id: 'open', title: '', render: row => <Button asChild><Link to={`/runs/${row.run_artifact_id}`}>{t("Results")} <ArrowUpRight size={15} /></Link></Button> },
  ];
  // Selection is cleared on page changes; comparison never downloads an unbounded run history.
  const rows = query.data?.items ?? [];
  const metrics = comparisonMetrics;
  return <>{!compact && <PageTitle eyebrow={t("Research history")} title={t("Strategy runs")}><div className="actions"><Button onClick={() => void query.refetch()}><RefreshCw size={15} /> {t("Refresh")}</Button><Button asChild tone="primary"><Link to="/launch"><Plus size={16} /> {t("New run")}</Link></Button></div></PageTitle>}
    {query.isError && <Failure message={errorText(query.error)} retry={() => void query.refetch()} />}<Card>{query.isPending ? <Loading /> : <DataTable rows={rows} columns={columns} name={t("Strategy runs")} searchText={compact ? undefined : row => `${row.logical_run_id} ${row.run_artifact_id} ${row.canonical_result_hash}`} />}
      {!compact && <><Pager index={paging.page.index} count={rows.length} busy={query.isFetching} previous={paging.page.trail.length ? () => { setSelected([]); paging.previous(); } : undefined} next={query.data?.next_cursor ? () => { setSelected([]); paging.next(query.data!.next_cursor!); } : undefined} /><div className="actions"><label>{t("Metric")} <select value={metric} onChange={event => setMetric(event.target.value)}>{metrics.map(metric => <option key={metric}>{metric}</option>)}</select></label><Button disabled={selected.length < 2} onClick={() => setComparison(true)}>{t("Compare selected ·")} {selected.length}</Button></div></>}
    </Card>{comparison && <Overlay title={t("Run comparison")} onClose={() => setComparison(false)}><Card><h3>{metric}</h3>{rows.filter(row => selected.includes(row.run_artifact_id)).map(row => <div key={row.run_artifact_id}><Fact name={shortId(row.run_artifact_id, 14)} value={String(row.comparison[metric as keyof typeof row.comparison])} /><details><summary>{t("Run assumptions and warnings")}</summary><FactTree value={{ physical_settings: row.physical_settings, canonicality: row.canonicality, warnings: row.warnings }} /></details></div>)}<p className="subtle">{t("Compare stored metrics of the selected runs. Balances are represented by count and digest.")}</p></Card></Overlay>}
  </>;
}

// Resource measurements update slowly and pause while hidden; they are not semantic run inputs.
export function Resources({ compact = false }: { compact?: boolean }) {
  useLocale();
  const visible = useVisible();
  const query = useQuery({ queryKey: ['resources'], enabled: visible, refetchInterval: visible ? 20000 : false,
    queryFn: ({ signal }) => api<Schema<'SystemResourcesResponse'>>('/api/v1/system/resources', { signal }) });
  const data = query.data;
  // Host capacity is a presentation measurement; financial amounts use separate exact formatting.
  const gib = (value: number) => `${(value / 1024 ** 3).toFixed(1)} GiB`;
  return <>{!compact && <PageTitle eyebrow={t("Local execution")} title={t("Resources and limits")}><Button onClick={() => void query.refetch()}><RefreshCw size={15} /> {t("Refresh")}</Button></PageTitle>}
    {query.isError && <Failure message={errorText(query.error)} retry={() => void query.refetch()} />}{query.isPending && <Loading />}
    {data && <div className="resource-grid"><ResourceCard icon={<Cpu size={19} />} title={t("Memory")} value={gib(data.physical_memory_available_bytes)} detail={t("available of {0}", [gib(data.physical_memory_total_bytes)])} used={data.physical_memory_total_bytes - data.physical_memory_available_bytes} total={data.physical_memory_total_bytes} /><ResourceCard icon={<HardDrive size={19} />} title={t("Free disk space")} value={gib(data.disk_free_bytes)} detail={t("of {0}", [gib(data.disk_total_bytes)])} used={data.disk_total_bytes - data.disk_free_bytes} total={data.disk_total_bytes} /><ResourceCard icon={<Workflow size={19} />} title={t("Concurrent runs")} value={String(data.configured_max_parallel_runs)} detail={t("Process budget {0}", [gib(data.configured_aggregate_child_memory_bytes)])} /><ResourceCard icon={<Database size={19} />} title={t("Temporary storage")} value={gib(data.temporary_used_bytes)} detail={t("limit {0}", [gib(data.configured_tmp_quota_bytes)])} used={data.temporary_used_bytes} total={data.configured_tmp_quota_bytes} /></div>}
    {data && !compact && <Card><h3>{t("Measurements and admission settings")}</h3><FactTree value={data} /></Card>}
  </>;
}
// Native progress supplies accessible bounded capacity visualization without inline styles.
function ResourceCard({ icon, title, value, detail, used, total }: { icon: React.ReactNode; title: string; value: string; detail: string; used?: number; total?: number }) {
  useLocale();
  return <Card className="resource-card"><div>{icon}<span>{title}</span></div><strong>{value}</strong><small>{detail}</small>{used !== undefined && total !== undefined && total > 0 && <progress value={used} max={total} aria-label={t("{0}: used", [title])} />}</Card>;
}

// Exact artifact IDs resolve only metadata and verified lineage through the API.
export function Artifacts({ artifactId }: { artifactId?: string }) {
  useLocale();
  const navigate = useNavigate();
  const [input, setInput] = useState(artifactId ?? '');
  const [view, setView] = useState<'manifest' | 'lineage'>('manifest');
  const valid = !!artifactId && digestSchema.safeParse(artifactId).success;
  // Invalid paths never issue requests, and lineage is fetched only when its view is selected.
  const manifest = useQuery({ queryKey: ['artifact', artifactId], enabled: valid,
    queryFn: ({ signal }) => api<Schema<'ArtifactDetailsResponse'>>(`/api/v1/artifacts/${artifactId}`, { signal }) });
  const lineage = useQuery({ queryKey: ['lineage', artifactId], enabled: valid && view === 'lineage',
    queryFn: ({ signal }) => api<Schema<'ArtifactLineageResponse'>>(`/api/v1/lineage/${artifactId}`, { signal }) });
  // An explicit manifest/lineage choice keeps both potentially large metadata views separate.
  return <><PageTitle eyebrow={t("Provenance and integrity")} title={t("Artifacts and lineage")} /><Card><form className="artifact-form" onSubmit={event => { event.preventDefault(); if (digestSchema.safeParse(input.trim()).success) navigate(`/artifacts/${input.trim()}`); }}><label>Artifact ID<input value={input} onChange={event => setInput(event.target.value)} required minLength={64} maxLength={64} pattern="[0-9a-f]{64}" placeholder={t("Exact SHA-256 ID")} /></label><Button tone="primary" type="submit">{t("Open")}</Button></form></Card>
    {artifactId && !valid && <Failure message={t("Invalid artifact ID.")} />}{valid && <><div className="actions"><Button tone={view === 'manifest' ? 'primary' : 'default'} onClick={() => setView('manifest')}>Manifest</Button><Button tone={view === 'lineage' ? 'primary' : 'default'} onClick={() => setView('lineage')}>Lineage</Button></div>
      {manifest.isError && <Failure message={errorText(manifest.error)} retry={() => void manifest.refetch()} />}{manifest.isPending && <Loading />}
      {view === 'manifest' && manifest.data && <Card><div className="card-heading"><h3>{t("Verified metadata")}</h3><Badge tone="positive">Verified</Badge></div><FactTree value={manifest.data} /></Card>}
      {view === 'lineage' && <>{lineage.isError && <Failure message={errorText(lineage.error)} retry={() => void lineage.refetch()} />}{lineage.isPending && <Loading />}{lineage.data && <Suspense fallback={<Loading />}><LineageGraph data={lineage.data} /></Suspense>}</>}
    </>}{!artifactId && <Card><Empty title={t("Open an artifact by ID")} detail={t("Verified metadata and the dependency graph are available here.")} /></Card>}</>;
}
