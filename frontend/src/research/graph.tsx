import { useCallback, useEffect, useRef, useState } from 'react';
import type { Core } from 'cytoscape';
import { t, useLocale } from '../i18n';
import { Button, Failure, Loading, Pager } from '../ui';
import { errorText } from '../api';
import loader from './research-graph-load';
import algorithms from './research-graph-model';
import { arrange, buildCanvas } from './canvas';
import type { GroupLink, Model, Pair, Projection, View } from './types';

// Table pages and whole-result loading have separate lifetimes; artifacts always replace both.
export default function ResearchGraph({artifact, total, rows, onEvidence}: {artifact: string; total: string; rows: Pair[] | null; onEvidence: (pair: string) => void}) {
  useLocale();
  const [scope, setScope] = useState<'page' | 'whole'>('page');
  const [attempt, setAttempt] = useState(0);
  return <section className="research-graph-panel" aria-label={t('Wallet relationship graph')}>
    <div className="card-heading"><h2>{t('Wallet relationship graph')}</h2><div className="actions"><Button aria-pressed={scope === 'page'} onClick={() => {setScope('page'); setAttempt(old => old + 1);}}>{t('Current page')}</Button><Button aria-pressed={scope === 'whole'} onClick={() => {setScope('whole'); setAttempt(old => old + 1);}}>{t('Whole result')}</Button></div></div>
    <p className="subtle">{t('Current page: up to 25 pairs / 50 wallets. Whole result: every pair, up to 200,000 pairs / 5,000 participating wallets; loading has a three-minute limit.')}</p>
    {scope === 'whole' ? <GraphLoad key={`${artifact}:whole:${attempt}`} artifact={artifact} total={total} onEvidence={onEvidence} /> : rows ? <GraphLoad key={`${artifact}:page:${rows[0]?.row_id ?? 'empty'}:${attempt}`} rows={rows} onEvidence={onEvidence} /> : <p>{t('Open Wallet pairs to view the current page graph.')}</p>}
    <details><summary>{t('How to navigate the graph')}</summary><p>{t('Whole result opens as groups → wallets in a group → all neighbours of a wallet, including other groups. Search covers every participating wallet. Lists have 50 items per page; search suggestions show the first 100 matches.')}</p><p>{t('A group node size shows its wallet count; a line between groups represents all crossing pairs. Inside a group, one line is one pair and its width reflects shared tokens. Colours and positions are visual aids, not proof of ownership, coordination or measured similarity.')}</p><p>{t('Drag nodes or the background; scroll to zoom. Select a pair to inspect its exact original purchases. Large views use rings; small views use a bounded force layout. Group numbers may change with the research range or parameters.')}</p></details>
  </section>;
}

function GraphLoad({artifact, total, rows, onEvidence}: {artifact?: string; total?: string; rows?: Pair[]; onEvidence: (pair: string) => void}) {
  useLocale();
  const [state, setState] = useState<{model: Model; signal: AbortSignal} | null>(null);
  const [progress, setProgress] = useState('');
  const [failure, setFailure] = useState('');
  const controller = useRef<AbortController | null>(null);
  useEffect(() => {
    const task = new AbortController(); controller.current = task;
    const signal = AbortSignal.any([task.signal, AbortSignal.timeout(loader.limits.deadline)]);
    let live = true;
    void (async () => {
      try {
        if (rows && rows.length > 25) throw new Error('The current page graph exceeds 25 pairs.');
        const data = rows ? {rows, wallets: [...new Set(rows.flatMap(row => [row.signer_a, row.signer_b]))].sort()} : await loader.load(artifact!, total!, signal, (done, count, wallets) => {if (live) setProgress(t('Loading pairs: {0} / {1} · wallets: {2}', [done, count, wallets]));});
        const model = await algorithms.build(data, signal, (done) => {if (live) setProgress(t('Grouping: {0}%', [Math.round(done)]));}, () => live);
        signal.throwIfAborted();
        if (live) setState({model, signal});
      } catch (error) { if (live) setFailure(signal.aborted ? t('Graph loading was cancelled or timed out. Choose the scope again to retry.') : errorText(error)); }
    })();
    return () => {live = false; task.abort(); controller.current = null;};
  }, [artifact, total, rows]);
  if (failure) return <Failure message={failure} />;
  return state ? <Explorer model={state.model} whole={!rows} initialSignal={state.signal} onEvidence={onEvidence} /> : <><Loading /><p role="status">{t(progress)}</p><Button onClick={() => controller.current?.abort()}>{t('Cancel graph loading')}</Button></>;
}

type Selection = {kind: 'default'} | {kind: 'pair'; index: number} | {kind: 'pairs'; title: string; indices: number[]; link?: GroupLink} | {kind: 'members'; group: number} | {kind: 'page-wallet'; wallet: string};
function Explorer({model, whole, initialSignal, onEvidence}: {model: Model; whole: boolean; initialSignal: AbortSignal; onEvidence: (pair: string) => void}) {
  useLocale();
  const [view, setView] = useState<View>({kind: whole ? 'overview' : 'page'});
  const [selection, setSelection] = useState<Selection>({kind: 'default'});
  const [neighbours, setNeighbours] = useState(false);
  const [projection, setProjection] = useState<Projection | null>(null);
  const [ready, setReady] = useState(false), [failure, setFailure] = useState('');
  const [search, setSearch] = useState(''), [expanded, setExpanded] = useState(false), [zoom, setZoom] = useState(0);
  const container = useRef<HTMLDivElement>(null), graph = useRef<Core | null>(null);
  const controller = useRef<AbortController | null>(null), firstSignal = useRef<AbortSignal | null>(initialSignal);
  const go = useCallback((next: View) => {setView(next); setSelection({kind: 'default'});}, []);
  const selectPair = useCallback((index: number) => {
    const current = graph.current, edge = current?.getElementById(`pair:${model.rows[index].row_id}`);
    current?.elements().unselect().removeClass('muted'); edge?.select();
    if (view.kind === 'page' && current && edge) current.elements().difference(edge.union(edge.connectedNodes())).addClass('muted');
    setSelection({kind: 'pair', index});
  }, [model, view.kind]);
  const selectWallet = useCallback((wallet: string) => {
    if (whole) {go({kind: 'wallet', key: wallet}); return;}
    const current = graph.current, node = current?.getElementById(`wallet:${wallet}`);
    current?.elements().unselect().removeClass('muted');
    if (current && node) {current.elements().difference(node.closedNeighborhood()).addClass('muted'); node.select();}
    setSelection({kind: 'page-wallet', wallet});
  }, [whole, go]);
  useEffect(() => {
    const task = new AbortController(); controller.current = task;
    const signal = AbortSignal.any([task.signal, AbortSignal.timeout(30000), ...(firstSignal.current ? [firstSignal.current] : [])]);
    let live = true, candidate: Core | null = null;
    setReady(false); setFailure(''); setProjection(null);
    void buildCanvas(model, view, neighbours, signal, () => live).then(result => {
      candidate = result.graph;
      if (!live) { candidate.destroy(); return; }
      graph.current = candidate; candidate.mount(container.current!); candidate.fit(candidate.nodes(), 48);
      candidate.on('tap', 'node', event => {
        if (!live) return;
        if (view.kind === 'overview') go({kind: 'group', key: event.target.data('group')});
        else selectWallet(event.target.data('wallet'));
      });
      candidate.on('tap', 'edge', event => {
        if (!live) return;
        if (view.kind === 'overview') { const link = event.target.data('link') as GroupLink; setSelection({kind: 'pairs', title: t('Group {0} ↔ group {1}', [link.a + 1, link.b + 1]), indices: link.indices, link}); }
        else selectPair(event.target.data('index'));
      });
      candidate.on('zoom', () => {if (live && candidate) setZoom(Math.round(candidate.zoom() * 100));});
      setZoom(Math.round(candidate.zoom() * 100)); setProjection(result.projection); setReady(true); firstSignal.current = null;
    }).catch(error => {if (live) setFailure(signal.aborted ? t('View construction was cancelled or timed out. Select a level again.') : errorText(error));});
    return () => {live = false; task.abort(); candidate?.destroy(); graph.current = null;};
  }, [model, view, neighbours, go, selectPair, selectWallet]);
  // Native ResizeObserver follows responsive expansion without retaining a second canvas.
  useEffect(() => {const observer = new ResizeObserver(() => {graph.current?.resize(); graph.current?.fit(undefined, 48);}); if (container.current) observer.observe(container.current); return () => observer.disconnect();}, []);
  const matches = model.wallets.filter(wallet => wallet.includes(search));
  const parent = view.kind === 'wallet' ? model.groupOf[model.lookup.get(view.key)!] : view.kind === 'group' ? view.key : null;
  const describe = view.kind === 'overview' ? t('{0} groups · {1} wallets. {2} internal + {3} crossing = {4} pairs. {5} lines between groups.', [model.groups.length, model.wallets.length, model.internal, model.external, model.rows.length, model.links.length])
    : view.kind === 'group' ? t('Group {0}: {1} wallets · all {2} internal pairs. External links are listed in the inspector.', [view.key + 1, projection?.members.length, projection?.indices.length])
      : view.kind === 'wallet' ? t('All {0} incident pairs · {1} neighbours. {2} pairs between neighbours: {3}.', [projection?.incident, (projection?.members.length ?? 1) - 1, projection?.extra, t(neighbours ? 'shown' : 'hidden')])
        : t('Current page: all {0} pairs · {1} wallets.', [model.rows.length, model.wallets.length]);
  return <div className={expanded ? 'research-explorer expanded' : 'research-explorer'}>
    <div className="actions"><Button disabled={!ready} aria-label={t('Zoom in graph')} onClick={() => graph.current?.zoom(Math.min(4, graph.current.zoom() * 1.25))}>＋</Button><Button disabled={!ready} aria-label={t('Zoom out graph')} onClick={() => graph.current?.zoom(Math.max(0.005, graph.current.zoom() / 1.25))}>−</Button><output>{ready ? `${zoom}%` : '—'}</output><Button disabled={!ready} onClick={() => graph.current?.fit(undefined, 48)}>{t('Fit graph')}</Button><Button disabled={!ready} onClick={() => {if (graph.current) arrange(graph.current, view);}}>{t('Reset layout')}</Button><Button aria-pressed={expanded} onClick={() => setExpanded(old => !old)}>{t(expanded ? 'Collapse graph' : 'Expand graph')}</Button></div>
    {whole && <nav className="actions" aria-label={t('Graph levels')}><Button aria-current={view.kind === 'overview' ? 'step' : undefined} onClick={() => go({kind: 'overview'})}>{t('1 / All groups')}</Button>{parent !== null && <Button aria-current={view.kind === 'group' ? 'step' : undefined} onClick={() => go({kind: 'group', key: parent})}>{t('2 / Group {0}', [parent + 1])}</Button>}{view.kind === 'wallet' && <span>{t('3 / Wallet neighbourhood')}</span>}</nav>}
    {!ready && !failure && <div role="status">{t('Building the selected graph level…')} <Button onClick={() => controller.current?.abort()}>{t('Cancel view construction')}</Button></div>}
    {failure && <Failure message={failure} retry={() => go({...view})} />}
    {ready && <p className="notice" role="status" data-testid="graph-counts">{describe}</p>}
    {whole && <p className="subtle">{model.policy} · {t('Passes: {0} / 20 · {1}', [model.passes, t(model.stable ? 'converged' : 'pass limit reached')])}. {t('Approximate visual grouping; no ownership or strategy signal is inferred.')}</p>}
    {view.kind === 'wallet' && <label className="checkbox-field"><input type="checkbox" checked={neighbours} onChange={event => {setNeighbours(event.target.checked); setSelection({kind: 'default'});}} />{t('Show links between neighbours')}</label>}
    <div className="research-graph-workspace"><div ref={container} className="research-canvas" role="img" aria-label={t('Co-purchase graph; keyboard search and lists are beside it')} />
      <aside className="research-inspector" aria-label={t('Selected graph element')}><label>{t('Find a wallet in the graph')}<input type="search" maxLength={44} value={search} onChange={event => setSearch(event.target.value)} disabled={!ready} /></label><p className="subtle">{t('{0} matches; showing up to 100. Addresses are case-sensitive.', [matches.length])}</p>
        <label>{t('Select wallet')}<select value="" disabled={!ready} onChange={event => {if (!event.target.value) return; selectWallet(event.target.value);}}><option value="">{t('Choose a wallet…')}</option>{matches.slice(0,100).map(wallet => <option key={wallet}>{wallet}</option>)}</select></label>
        <Button disabled={!ready} onClick={() => {graph.current?.elements().unselect().removeClass('muted'); setSelection({kind: 'default'});}}>{t('Clear selection')}</Button>
        {ready && <Inspector key={`${view.kind}:${"key" in view ? view.key : ""}:${selection.kind}:${"index" in selection ? selection.index : "title" in selection ? selection.title : "wallet" in selection ? selection.wallet : ""}`} model={model} view={view} selection={selection} select={setSelection} go={go} selectPair={selectPair} onEvidence={onEvidence} />}
      </aside></div>
  </div>;
}

function List({title, indices, label, onSelect}: {title: string; indices: number[]; label: (index: number) => string; onSelect: (index: number) => void}) {
  const [page, setPage] = useState(0);
  return <><h4>{t(title)} · {indices.length}</h4><div className="research-list">{indices.slice(page * 50, (page + 1) * 50).map(index => <Button key={index} onClick={() => onSelect(index)}>{label(index)}</Button>)}</div><Pager index={page} count={indices.slice(page * 50, (page + 1) * 50).length} busy={false} previous={page ? () => setPage(old => old - 1) : undefined} next={(page + 1) * 50 < indices.length ? () => setPage(old => old + 1) : undefined} /></>;
}
function Inspector({model, view, selection, select, go, selectPair, onEvidence}: {model: Model; view: View; selection: Selection; select: (selection: Selection) => void; go: (view: View) => void; selectPair: (index: number) => void; onEvidence: (pair: string) => void}) {
  if (selection.kind === 'pair') {const row = model.rows[selection.index]; return <><h4>{t('Pair {0}', [row.row_id])}</h4><p className="wallet-address">{row.signer_a} ↔ {row.signer_b}</p><p>{t('Shared tokens: {0} · A earlier: {1} · B earlier: {2} · same transaction: {3}', [row.shared_mints, row.a_first, row.b_first, row.same_transaction])}</p>{view.kind !== 'page' && <div className="actions"><Button onClick={() => go({kind: 'wallet', key: row.signer_a})}>{t('Neighbourhood A')}</Button><Button onClick={() => go({kind: 'wallet', key: row.signer_b})}>{t('Neighbourhood B')}</Button></div>}<Button tone="primary" onClick={() => onEvidence(row.row_id)}>{t('Open original purchases')}</Button></>;}
  const pairs = (indices: number[], title: string) => <List title={title} indices={indices} label={index => {const row = model.rows[index]; return `${row.signer_a} ↔ ${row.signer_b} · ${row.shared_mints}`;}} onSelect={selectPair} />;
  if (selection.kind === 'pairs') return <>{pairs(selection.indices, selection.title)}{selection.link && [selection.link.a, selection.link.b].map(key => <Button key={key} onClick={() => go({kind: 'group', key})}>{t('Open group {0}', [key + 1])}</Button>)}</>;
  if (selection.kind === 'members') return <List title="Group wallets" indices={model.groups[selection.group].members} label={index => model.wallets[index]} onSelect={index => go({kind: 'wallet', key: model.wallets[index]})} />;
  if (view.kind === 'wallet' || selection.kind === 'page-wallet') {const wallet = selection.kind === 'page-wallet' ? selection.wallet : view.kind === 'wallet' ? view.key : '';return <><h4>{t('Wallet neighbourhood')}</h4><p className="wallet-address">{wallet}</p>{pairs(model.adjacent[model.lookup.get(wallet)!], view.kind === 'page' ? 'Incident pairs on this page' : 'All incident pairs')}</>;}
  if (view.kind === 'group') { const group = model.groups[view.key]; return <><h4>{t('Group {0}', [view.key + 1])}</h4><p>{t('{0} wallets · {1} internal pairs · {2} external pairs', [group.members.length, group.internal.length, group.links.reduce((sum, link) => sum + link.indices.length, 0)])}</p><Button onClick={() => select({kind: 'members', group: view.key})}>{t('All wallets in group')}</Button><Button onClick={() => select({kind: 'pairs', title: t('Internal pairs'), indices: group.internal})}>{t('All internal pairs')}</Button><List title="Links to groups" indices={group.links.map((_, index) => index)} label={index => {const link = group.links[index]; return t('Group {0} · {1} pairs', [(link.a === view.key ? link.b : link.a) + 1, link.indices.length]);}} onSelect={index => {const link = group.links[index]; select({kind: 'pairs', title: t('Crossing pairs'), indices: link.indices, link});}} /></>; }
  if (view.kind === 'page') return pairs(model.rows.map((_, index) => index), 'Pairs on this page');
  return <List title="All groups" indices={model.groups.map(group => group.id)} label={index => {const group = model.groups[index]; return t('Group {0} · {1} wallets · {2} internal pairs', [index + 1, group.members.length, group.internal.length]);}} onSelect={key => go({kind: 'group', key})} />;
}
