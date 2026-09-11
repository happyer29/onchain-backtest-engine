import { Component, type ReactNode, lazy, Suspense, useCallback, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import { t, useLocale } from '../i18n';
import { Button, Card, Failure, Loading, PageTitle, Pager, Tabs, TabPanel } from '../ui';
import { DataTable, type TableColumn } from '../table';
import { FactTree } from '../results';
import { JobsPanel } from '../workspace';
import { ResearchForms } from './forms';
import { ResearchMethod } from './method';
import { columns, headings, page, researchError, summary, tableNames, type Summary, type Table } from './contracts';
import type { Pair, Row } from './types';
const Graph = lazy(() => import('./graph'));

// Historical exact-artifact bookmarks enter the one shared React shell unchanged.
export default function Research() {
  useLocale();
  const [params, setParams] = useSearchParams(), [input, setInput] = useState(params.get('artifact') ?? '');
  const id = params.get('artifact'), jobId = params.get('job');
  const invalid = id !== null && !/^[0-9a-f]{64}$/.test(id);
  const query = useQuery({queryKey:['research-summary', id, jobId], enabled: !invalid && Boolean(id || jobId), queryFn: async ({signal}) => {
    const selected = id ?? (await api<{artifact_id: string}>(`/api/v1/research/jobs/${encodeURIComponent(jobId!)}/result`, {signal})).artifact_id;
    if (!/^[0-9a-f]{64}$/.test(selected)) throw new Error('Invalid research artifact ID.');
    return summary(selected, signal);
  }});
  const data = query.data;
  return <><PageTitle eyebrow={t('From observation to hypothesis')} title={t('On-chain research')} /><p className="intro-text">{t('Who buys together? Explore signer activity and shared first purchases of Pump.fun tokens. Every relationship can be traced to the observed trades.')}</p>
    <ResearchForms summary={data} /><ResearchMethod />
    <Card><h2>{t('Open saved research')}</h2><form className="research-open" onSubmit={event => {event.preventDefault(); setParams({artifact:input});}}><label>{t('Snapshot or result ID')}<input required pattern="[0-9a-f]{64}" maxLength={64} value={input} onChange={event => setInput(event.target.value)} /></label><Button tone="primary">{t('Open')}</Button></form></Card>
    {invalid && <Failure message={t('Invalid research artifact ID.')} />}{query.isError && <Failure message={researchError(query.error)} retry={() => void query.refetch()} />}{(id || jobId) && !invalid && query.isPending && <Loading />}
    {data && <Result key={data.artifact_id} data={data} />}
    <div className="section-intro"><h2>{t('Research jobs')}</h2><Link to="/jobs">{t('Manage queue →')}</Link></div><JobsPanel researchOnly />
  </>;
}
function Result({data}: {data: Summary}) {
  const snapshot = data.kind === 'RESEARCH_SNAPSHOT';
  const [selection, setSelection] = useState<{table: Table; pair: string | null}>({table:snapshot ? 'observations' : 'pairs',pair:null});
  const [rows, setRows] = useState<Pair[] | null>(null);
  const tableRef = useRef<HTMLDivElement>(null);
  const select = useCallback((table: Table, pair: string | null = null) => {setSelection({table,pair}); setRows(null);}, []);
  const evidence = useCallback((pair: string) => {select('evidence',pair); tableRef.current?.scrollIntoView({block:'start'});}, [select]);
  const onRows = useCallback((rows: Row[] | null) => setRows(rows as Pair[] | null), []);
  const tables: Table[] = snapshot ? (data.dataset.schema === 'research-dataset-spec/v2' ? ['observations','token_modes'] : ['observations']) : ['pairs','activity'];
  if (Object.keys(data.data_issue_counts).length) tables.push('data_issues');
  if (selection.table === 'evidence') tables.push('evidence');
  const labels: Record<string,string> = {source_rows:'Snapshot observations',selected_rows:'Selected rows',wallets:'Signers',pairs:'Wallet pairs',evidence:'Shared tokens across pairs'};
  return <Card><div className="card-heading"><h2>{t(snapshot ? 'Saved observations' : 'Relationships in this sample')}</h2><Button asChild><Link to={`/artifacts/${data.artifact_id}`}>{t('Open manifest and lineage')}</Link></Button></div><code className="wallet-address">{data.artifact_id}</code><p className="subtle">{data.dataset.network_id} · {data.dataset.source_id} · [{data.dataset.from_block_ordinal}, {data.dataset.to_block_ordinal})</p>
    {data.analysis && <p className="notice">{t('Committed analysis: window ≤ {0} seconds · minimum {1} tokens · {2}', [data.analysis.window_seconds,data.analysis.minimum_shared_mints,t(data.analysis.wallets.length ? '{0} selected signers' : 'all observed signers',[data.analysis.wallets.length])])} · {t(data.analysis.mode === 'NON_MAYHEM' ? 'Without Mayhem' : 'All modes')}</p>}
    <div className="research-metrics">{Object.entries(labels).filter(([key]) => key in data.counts).map(([key,label]) => <div key={key}><strong>{data.counts[key]}</strong><span>{t(label)}</span></div>)}</div><ModeScope data={data} />
    {BigInt(data.data_issue_counts.mints ?? '0') > 0n && <div className="research-warning" role="status"><strong>{t('Token data is incomplete')}</strong><p>{t('{0} tokens have no creation transaction signature. {1} observations are skipped during analysis in both modes; source swaps remain in the snapshot.',[data.data_issue_counts.mints,String(BigInt(data.data_issue_counts.non_mayhem_rows ?? '0')+BigInt(data.data_issue_counts.mayhem_rows ?? '0'))])}</p><Button onClick={() => {select('data_issues');tableRef.current?.scrollIntoView({block:'start'});}}>{t('Show affected tokens')}</Button></div>}
    <p className="subtle">{t('Market completeness, finality and historical availability: UNKNOWN. A relationship is an observation, not proof of a shared owner or a strategy signal.')}</p>
    {!snapshot && <GraphBoundary key={data.artifact_id}><Suspense fallback={<Loading />}><Graph artifact={data.artifact_id} total={data.counts.pairs} rows={selection.table === 'pairs' ? rows : null} onEvidence={evidence} /></Suspense></GraphBoundary>}
    <div ref={tableRef}><Tabs value={selection.table} onChange={table => select(table as Table)} tabs={tables.map(table => [table,tableNames[table]])}><TabPanel value={selection.table}><ResearchTable key={`${selection.table}:${selection.pair}`} artifact={data.artifact_id} table={selection.table} pair={selection.pair} onRows={selection.table === 'pairs' ? onRows : undefined} onEvidence={evidence} /></TabPanel></Tabs></div>
    <details><summary>{t('Observation quality and exact recipe')}</summary><FactTree value={{quality:data.quality,analysis:data.analysis}} /></details>
  </Card>;
}
function ModeScope({data}: {data: Summary}) {
  const c = data.mode_counts;
  if (!Object.keys(c).length) return <p className="notice">{t('Legacy snapshot: token modes were not classified. This saved result includes all modes.')}</p>;
  return <div className="research-mode-scope"><p>{t(data.kind === 'RESEARCH_SNAPSHOT' ? 'Classification of the full snapshot.' : 'Classification before filtering, among selected signers.')}</p><p>{t('Ordinary: {0} tokens / {1} rows; Mayhem: {2} / {3}; unknown: {4} / {5}.',[c.non_mayhem_mints,c.non_mayhem_rows,c.mayhem_mints,c.mayhem_rows,c.unknown_mints,c.unknown_rows])}</p>{data.analysis && <p>{t(data.analysis.mode === 'NON_MAYHEM' ? 'Mayhem and unknown modes are excluded. Pair counts and thresholds use only ordinary tokens without reported data issues.' : 'All mode categories participate, except tokens with reported data issues.')}</p>}</div>;
}
// Sorting is page-local and retains wide atomic amounts as exact integers.
const numericColumns = new Set(['row_id','block_ordinal','transaction_index','quote_amount_atomic','source_rows','observation_rows','buy_rows','sell_rows','mint_count','first_block','last_block','source_quote_buy_atomic','source_quote_sell_atomic','shared_mints','a_first','b_first','same_transaction','delta_seconds','left_block_ordinal','right_block_ordinal']);
function ResearchTable({artifact,table,pair,onRows,onEvidence}: {artifact:string; table:Table; pair:string|null; onRows?: (rows:Row[]|null)=>void; onEvidence:(pair:string)=>void}) {
  const [paging,setPaging] = useState<{cursor:string|null; trail:(string|null)[]; index:number}>({cursor:null,trail:[],index:0});
  const query = useQuery({queryKey:['research-page',artifact,table,pair,paging.cursor],queryFn:async ({signal}) => {const result=await page(artifact,table,paging.cursor,pair,signal); signal.throwIfAborted(); onRows?.(result.rows); return result;}});
  const display: TableColumn<Row>[] = columns[table].map(key => ({id:key,title:t(headings[key]),value:row=>numericColumns.has(key) && /^-?\d+$/.test(row[key] ?? '') ? BigInt(row[key]) : row[key],render:row=><span className="research-cell">{row[key] ?? '—'}</span>}));
  if (table === 'pairs') display.push({id:'evidence',title:t('Evidence'),render:row=><Button onClick={()=>onEvidence(row.row_id)}>{t('Original purchases for pair {0}',[row.row_id])}</Button>});
  return <><h3>{t(tableNames[table])}{pair!==null && ` · ${t('Pair {0}',[pair])}`}</h3>{query.isError && <Failure message={researchError(query.error)} retry={()=>void query.refetch()} />}{query.isPending ? <Loading /> : <DataTable name={t(tableNames[table])} rows={query.data?.rows ?? []} columns={display} />}
    <Pager index={paging.index} count={query.data?.rows.length ?? 0} busy={query.isFetching} previous={paging.trail.length ? ()=>{onRows?.(null);setPaging(old=>({cursor:old.trail.at(-1)!,trail:old.trail.slice(0,-1),index:old.index-1}));} : undefined} next={query.data?.next_cursor ? ()=>{onRows?.(null);setPaging(old=>({cursor:query.data!.next_cursor,trail:[...old.trail,old.cursor].slice(-128),index:old.index+1}));} : undefined} />
    <p className="subtle">{t('The table shows one page of 25 rows. Whole-result graph loading is independent of table pagination. All atomic amounts retain their exact lamport digits.')}</p>
  </>;
}

// Optional graph failures cannot hide verified tables, warnings or purchase evidence.
export class GraphBoundary extends Component<{children: ReactNode}, {failed: boolean}> {
  state = {failed: false};
  static getDerivedStateFromError() {return {failed: true};}
  render() {return this.state.failed ? <Failure message={t('The graph renderer is unavailable. Reload the page; original purchases remain available in the table.')} /> : this.props.children;}
}
