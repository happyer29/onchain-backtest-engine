import { useCallback, useEffect, useRef, useState } from 'react';
import type { CameraState } from 'sigma/types';
import { t, useLocale } from '../i18n';
import { Button, Failure, Loading, Pager } from '../ui';
import { errorText } from '../api';
import loader from './research-graph-load';
import algorithms from './research-graph-model';
import SigmaView, { type RendererHandle } from './sigma-view';
import { buildDisplayGraph, filterPairs, visibleIndices, viewKey, type BuiltGraph, type DisplayFilter } from './sigma-data';
import { applyCoordinates } from './layout-core';
import { runLayout } from './layout-client';
import { ViewMemory, type ViewBounds } from './navigation';
import type { GroupLink, Model, Pair, View } from './types';

// Table pages and whole-result loading have separate lifetimes; artifacts always replace both.
export default function ResearchGraph({artifact, total, rows, onEvidence}: {artifact: string; total: string; rows: Pair[] | null; onEvidence: (pair: string) => void}) {
  useLocale();
  const [scope, setScope] = useState<'page' | 'whole'>('page');
  const [attempt, setAttempt] = useState(0);
  return <section className="research-graph-panel" aria-label={t('Wallet relationship graph')}>
    <div className="card-heading"><h2>{t('Wallet relationship graph')}</h2><div className="actions"><Button aria-pressed={scope === 'page'} onClick={() => {setScope('page'); setAttempt(old => old + 1);}}>{t('Current page')}</Button><Button aria-pressed={scope === 'whole'} onClick={() => {setScope('whole'); setAttempt(old => old + 1);}}>{t('Whole result')}</Button></div></div>
    <p className="subtle">{t('Current page: up to 25 pairs / 50 wallets. Whole result: every pair, up to 200,000 pairs / 5,000 participating wallets; loading has a three-minute limit.')}</p>
    {scope === 'whole' ? <GraphLoad key={`${artifact}:whole:${attempt}`} artifact={artifact} total={total} onEvidence={onEvidence} /> : rows ? <GraphLoad key={`${artifact}:page:${rows[0]?.row_id ?? 'empty'}:${attempt}`} rows={rows} onEvidence={onEvidence} /> : <p>{t('Open Wallet pairs to view the current page graph.')}</p>}
    <details><summary>{t('How to navigate the graph')}</summary><p>{t('Whole result opens as groups → wallets in a group → all neighbours of a wallet, including other groups. Search covers every participating wallet. Lists have 50 items per page; search suggestions show the first 100 matches.')}</p><p>{t('A group node size shows its wallet count; a line between groups represents all crossing pairs. Inside a group, one line is one pair and its width reflects shared tokens. Colours and positions are visual aids, not proof of ownership, coordination or measured similarity.')}</p><p>{t('Drag nodes or the background; scroll to zoom. Labels appear as you approach. Select a pair to inspect its exact original purchases. Layout follows relationships using a bounded worker calculation. Group numbers may change with the research range or parameters.')}</p></details>
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
  const [view, setView] = useState<View>({kind: whole ? 'overview' : 'page'}), [attempt, setAttempt] = useState(0);
  const [selection, setSelection] = useState<Selection>({kind: 'default'}), [neighbours, setNeighbours] = useState(false);
  const [built, setBuilt] = useState<(BuiltGraph & {camera?: CameraState; bounds?: ViewBounds; key: string}) | null>(null);
  const [mountedReady, setReady] = useState(false), [failure, setFailure] = useState(''), [layoutProgress, setLayoutProgress] = useState(0);
  const [search, setSearch] = useState(''), [expanded, setExpanded] = useState(false), [zoom, setZoom] = useState(0);
  const [filter, setFilter] = useState<DisplayFilter | null>(null), [minimum, setMinimum] = useState(1), [minimumText, setMinimumText] = useState('1'), [filterError, setFilterError] = useState('');
  const [history, setHistory] = useState<{view: View; neighbours: boolean}[]>([]), [restored, setRestored] = useState(false);
  const wrapper = useRef<HTMLDivElement>(null), renderer = useRef<RendererHandle | null>(null), memory = useRef(new ViewMemory());
  const controller = useRef<AbortController | null>(null), firstSignal = useRef<AbortSignal | null>(initialSignal);
  const key = viewKey(view, neighbours);
  const sceneKey = `${key}:${attempt}`, ready = mountedReady && built?.key === sceneKey;
  const remember = () => {const handle = renderer.current; if (handle && ready) memory.current.save(key, handle.graph, handle.sigma.getCamera().getState(), handle.sigma.getCustomBBox() ?? handle.sigma.getBBox());};
  const go = (next: View) => {remember(); if (viewKey(next, neighbours) !== key) setHistory(old => [...old, {view, neighbours}].slice(-16)); setView(next); setSelection({kind: 'default'});};
  const back = () => {if (!history.length) return; remember(); setView(history[history.length-1].view); setNeighbours(history[history.length-1].neighbours); setHistory(old => old.slice(0,-1)); setSelection({kind:'default'});};
  const selectPair = (index: number) => setSelection({kind:'pair', index});
  const selectWallet = (wallet: string) => {if (whole) go({kind:'wallet', key:wallet}); else setSelection({kind:'page-wallet',wallet});};
  useEffect(() => {
    const task = new AbortController(); let live = true;
    void filterPairs(model, minimum, AbortSignal.any([task.signal, AbortSignal.timeout(30000)]), () => live).then(result => {if (live) {setFilter(result); setFilterError('');}}).catch(error => {if (live) setFilterError(errorText(error));});
    return () => {live = false; task.abort();};
  }, [model, minimum]);
  useEffect(() => {
    const task = new AbortController(); controller.current = task;
    const signal = AbortSignal.any([task.signal, AbortSignal.timeout(30000), ...(firstSignal.current ? [firstSignal.current] : [])]);
    let live = true, candidate: BuiltGraph | null = null, completed = false;
    setReady(false); setFailure(''); setBuilt(null); setLayoutProgress(0); setRestored(false); renderer.current = null;
    const abort = () => {if (live && !completed) {setBuilt(null); setFailure(t('View construction was cancelled or timed out. Select a level again.'));}};
    signal.addEventListener('abort', abort, {once:true});
    void (async () => {
      try {
        candidate = await buildDisplayGraph(model, view, neighbours, signal, () => live);
        const saved = memory.current.read(key, candidate.graph.order);
        const coordinates = saved?.coordinates ?? await runLayout(candidate.graph, signal, value => {if (live) setLayoutProgress(value);});
        signal.throwIfAborted(); if (!live) return;
        applyCoordinates(candidate.graph, coordinates);
        setRestored(Boolean(saved)); setBuilt({...candidate, camera:saved?.camera, bounds:saved?.bounds, key:`${key}:${attempt}`});
      } catch (error) {if (live) setFailure(signal.aborted ? t('View construction was cancelled or timed out. Select a level again.') : errorText(error));}
    })();
    // Mark mounting completion through the current generation, keeping the deadline active until then.
    const mountDone = () => {completed = true; signal.removeEventListener('abort', abort);};
    mounted.current = mountDone;
    return () => {live = false; signal.removeEventListener('abort', abort); task.abort(); candidate?.graph.clear(); renderer.current = null;};
  }, [model, key, attempt]);
  const mounted = useRef<() => void>(() => {});
  useEffect(() => () => memory.current.clear(), []);
  const mount = useCallback((handle: RendererHandle) => {renderer.current = handle; mounted.current(); firstSignal.current = null; setReady(true);}, []);
  const fail = useCallback((message: string) => {controller.current?.abort(); renderer.current = null; setReady(false); setBuilt(null); setFailure(t(message));}, []);
  const matches = model.wallets.filter(wallet => wallet.includes(search));
  const parent = view.kind === 'wallet' ? model.groupOf[model.lookup.get(view.key)!] : view.kind === 'group' ? view.key : null;
  const projection = built?.key === sceneKey ? built.projection : null;
  const shownInView = filter ? projection ? visibleIndices(projection.indices,filter).length : filter.shown : 0;
  const totalInView = projection?.indices.length ?? model.rows.length;
  const describe = view.kind === 'overview' ? t('{0} groups · {1} wallets. {2} internal + {3} crossing = {4} pairs. {5} lines between groups.', [model.groups.length, model.wallets.length, model.internal, model.external, model.rows.length, filter?.links.size ?? model.links.length])
    : view.kind === 'group' ? t('Group {0}: {1} wallets · all {2} internal pairs. External links are listed in the inspector.', [view.key+1,projection?.members.length,projection?.indices.length])
      : view.kind === 'wallet' ? t('All {0} incident pairs · {1} neighbours. {2} pairs between neighbours: {3}.', [projection?.incident,(projection?.members.length ?? 1)-1,projection?.extra,t(neighbours?'shown':'hidden')])
        : t('Current page: all {0} pairs · {1} wallets.', [model.rows.length,model.wallets.length]);
  const focus = selection.kind === 'page-wallet' ? `wallet:${selection.wallet}` : view.kind === 'wallet' && selection.kind !== 'pair' ? `wallet:${view.key}` : null;
  const fullscreen = async () => {try {if (document.fullscreenElement) await document.exitFullscreen(); else await wrapper.current?.requestFullscreen();} catch {setFilterError(t('Fullscreen is unavailable in this browser. Use Expand graph instead.'));}};
  return <div ref={wrapper} className={expanded ? 'research-explorer expanded' : 'research-explorer'}>
    <div className="actions"><Button disabled={!ready} aria-label={t('Zoom in graph')} onClick={() => {const camera=renderer.current?.sigma.getCamera(); if(camera) camera.setState({ratio:camera.ratio/1.25});}}>＋</Button><Button disabled={!ready} aria-label={t('Zoom out graph')} onClick={() => {const camera=renderer.current?.sigma.getCamera(); if(camera) camera.setState({ratio:camera.ratio*1.25});}}>−</Button><output data-testid="graph-zoom">{ready?`${zoom}%`:'—'}</output><Button disabled={!ready} onClick={() => renderer.current?.sigma.getCamera().setState({x:.5,y:.5,ratio:1,angle:0})}>{t('Fit graph')}</Button><Button disabled={!ready} onClick={() => {memory.current.forget(key);setAttempt(old=>old+1);}}>{t('Reset layout')}</Button><Button aria-pressed={expanded} onClick={() => setExpanded(old=>!old)}>{t(expanded?'Collapse graph':'Expand graph')}</Button><Button onClick={fullscreen}>{t('Fullscreen')}</Button></div>
    <div className="research-filter"><label>{t('Show pairs with at least this many shared tokens')}<input type="number" min="1" max="2000000" step="1" value={minimumText} onChange={event=>setMinimumText(event.target.value)} /></label><Button disabled={minimum!==filter?.minimum} onClick={()=>{const value=Number(minimumText);if(!/^\d+$/.test(minimumText)||!Number.isSafeInteger(value)||value<1||value>2000000){setFilterError(t('Use a whole number from 1 to 2,000,000.'));return;}setSelection({kind:'default'});setMinimum(value);setFilterError('');}}>{t('Apply display filter')}</Button><Button onClick={()=>{setMinimum(1);setMinimumText('1');setSelection({kind:'default'});setFilterError('');}}>{t('Show every pair')}</Button></div>
    <p className="subtle">{t('This filter changes only visible relationships. Groups, wallets, saved analysis and tables stay the same. Search includes wallets whose links are hidden.')}</p>
    {filterError && <Failure message={filterError} />}
    {filter && <p className="notice" data-testid="graph-filter-counts">{t('Entire loaded scope: {0} shown + {1} hidden = {2} pairs. Display threshold: {3} shared tokens.',[filter.shown,model.rows.length-filter.shown,model.rows.length,filter.minimum])}{view.kind==='overview' && ` ${t('Visible pairs: {0} internal + {1} crossing.',[filter.internal,filter.external])}`}</p>}
    {minimum!==filter?.minimum && <p role="status">{t('Applying display filter…')}</p>}
    <nav className="actions" aria-label={t('Graph levels')}><Button disabled={!history.length} onClick={back}>{t('Back to previous view')}</Button>{whole && <><Button aria-current={view.kind==='overview'?'step':undefined} onClick={()=>go({kind:'overview'})}>{t('1 / All groups')}</Button>{parent!==null && <Button aria-current={view.kind==='group'?'step':undefined} onClick={()=>go({kind:'group',key:parent})}>{t('2 / Group {0}',[parent+1])}</Button>}{view.kind==='wallet' && <span>{t('3 / Wallet neighbourhood')}</span>}</>}</nav>
    {!ready && !failure && <div role="status">{t('Building the selected graph level…')} {t('Layout: {0} / 120',[layoutProgress])} <Button onClick={()=>controller.current?.abort()}>{t('Cancel view construction')}</Button></div>}
    {failure && <Failure message={failure} retry={()=>setAttempt(old=>old+1)} />}
    {ready && <><p className="notice" role="status" data-testid="graph-counts">{describe}</p><p className="subtle" data-testid="graph-view-filter">{t('This view: {0} shown + {1} hidden = {2} pairs.',[shownInView,totalInView-shownInView,totalInView])} {t(restored?'Saved positions and camera restored.':'New layout; up to eight views retain their positions and camera.')}</p></>}
    {whole && <p className="subtle">{model.policy} · {t('Passes: {0} / 20 · {1}',[model.passes,t(model.stable?'converged':'pass limit reached')])}. {t('Approximate visual grouping; no ownership or strategy signal is inferred.')}</p>}
    {view.kind==='wallet' && <label className="checkbox-field"><input type="checkbox" checked={neighbours} onChange={event=>{remember();setNeighbours(event.target.checked);setSelection({kind:'default'});}} />{t('Show links between neighbours')}</label>}
    <div className="research-graph-workspace"><div className="research-canvas" role="img" aria-label={t('Co-purchase graph; keyboard search and lists are beside it')}>
      {built && built.key === sceneKey && filter && !failure && <SigmaView key={built.key} graph={built.graph} filter={filter} camera={built.camera} bounds={built.bounds} focus={focus} pair={selection.kind==='pair'?`pair:${model.rows[selection.index].row_id}`:null} onReady={mount} onFailure={fail} onCamera={camera=>setZoom(Math.round(100/camera.ratio))} onClear={()=>setSelection({kind:'default'})} onNode={node=>{if(view.kind==='overview')go({kind:'group',key:built.graph.getNodeAttribute(node,'group')});else selectWallet(built.graph.getNodeAttribute(node,'wallet')!);}} onEdge={edge=>{const attrs=built.graph.getEdgeAttributes(edge);if(attrs.link)setSelection({kind:'pairs',title:t('Group {0} ↔ group {1}',[attrs.link.a+1,attrs.link.b+1]),indices:attrs.link.indices,link:attrs.link});else selectPair(attrs.index!);}} />}
    </div><aside className="research-inspector" aria-label={t('Selected graph element')}><label>{t('Find a wallet in the graph')}<input type="search" maxLength={44} value={search} onChange={event=>setSearch(event.target.value)} disabled={!ready} /></label><p className="subtle">{t('{0} matches; showing up to 100. Addresses are case-sensitive.',[matches.length])}</p><label>{t('Select wallet')}<select value="" disabled={!ready} onChange={event=>{if(event.target.value)selectWallet(event.target.value);}}><option value="">{t('Choose a wallet…')}</option>{matches.slice(0,100).map(wallet=><option key={wallet}>{wallet}</option>)}</select></label><Button disabled={!ready} onClick={()=>setSelection({kind:'default'})}>{t('Clear selection')}</Button>
      {ready && filter && <Inspector key={`${key}:${filter.minimum}:${selection.kind}:${'index' in selection?selection.index:'title' in selection?selection.title:'wallet' in selection?selection.wallet:''}`} model={model} filter={filter} view={view} selection={selection} select={setSelection} go={go} selectPair={selectPair} onEvidence={onEvidence} />}
    </aside></div>
  </div>;
}

function List({title, indices, label, onSelect}: {title: string; indices: number[]; label: (index: number) => string; onSelect: (index: number) => void}) {
  const [page, setPage] = useState(0);
  return <><h4>{t(title)} · {indices.length}</h4><div className="research-list">{indices.slice(page * 50, (page + 1) * 50).map(index => <Button key={index} onClick={() => onSelect(index)}>{label(index)}</Button>)}</div><Pager index={page} count={indices.slice(page * 50, (page + 1) * 50).length} busy={false} previous={page ? () => setPage(old => old - 1) : undefined} next={(page + 1) * 50 < indices.length ? () => setPage(old => old + 1) : undefined} /></>;
}
function Inspector({model, filter, view, selection, select, go, selectPair, onEvidence}: {model: Model; filter: DisplayFilter; view: View; selection: Selection; select: (selection: Selection) => void; go: (view: View) => void; selectPair: (index: number) => void; onEvidence: (pair: string) => void}) {
  if (selection.kind === 'pair') {const row = model.rows[selection.index]; return <><h4>{t('Pair {0}', [row.row_id])}</h4><p className="wallet-address">{row.signer_a} ↔ {row.signer_b}</p><p>{t('Shared tokens: {0} · A earlier: {1} · B earlier: {2} · same transaction: {3}', [row.shared_mints, row.a_first, row.b_first, row.same_transaction])}</p>{view.kind !== 'page' && <div className="actions"><Button onClick={() => go({kind: 'wallet', key: row.signer_a})}>{t('Neighbourhood A')}</Button><Button onClick={() => go({kind: 'wallet', key: row.signer_b})}>{t('Neighbourhood B')}</Button></div>}<Button tone="primary" onClick={() => onEvidence(row.row_id)}>{t('Open original purchases')}</Button></>;}
  const pairs = (indices: number[], title: string) => <List title={title} indices={visibleIndices(indices,filter)} label={index => {const row = model.rows[index]; return `${row.signer_a} ↔ ${row.signer_b} · ${row.shared_mints}`;}} onSelect={selectPair} />;
  if (selection.kind === 'pairs') return <>{pairs(selection.indices, selection.title)}{selection.link && [selection.link.a, selection.link.b].map(key => <Button key={key} onClick={() => go({kind: 'group', key})}>{t('Open group {0}', [key + 1])}</Button>)}</>;
  if (selection.kind === 'members') return <List title="Group wallets" indices={model.groups[selection.group].members} label={index => model.wallets[index]} onSelect={index => go({kind: 'wallet', key: model.wallets[index]})} />;
  if (view.kind === 'wallet' || selection.kind === 'page-wallet') {const wallet = selection.kind === 'page-wallet' ? selection.wallet : view.kind === 'wallet' ? view.key : '';return <><h4>{t('Wallet neighbourhood')}</h4><p className="wallet-address">{wallet}</p>{pairs(model.adjacent[model.lookup.get(wallet)!], view.kind === 'page' ? 'Incident pairs on this page' : 'All incident pairs')}</>;}
  if (view.kind === 'group') { const group = model.groups[view.key]; return <><h4>{t('Group {0}', [view.key + 1])}</h4><p>{t('{0} wallets · {1} internal pairs · {2} external pairs', [group.members.length, filter.groupInternal[group.id], group.links.reduce((sum, link) => sum + (filter.links.get(link.key)??0), 0)])}</p><Button onClick={() => select({kind: 'members', group: view.key})}>{t('All wallets in group')}</Button><Button onClick={() => select({kind: 'pairs', title: t('Internal pairs'), indices: group.internal})}>{t('All internal pairs')}</Button><List title="Links to groups" indices={group.links.map((_, index) => index)} label={index => {const link = group.links[index]; return t('Group {0} · {1} pairs', [(link.a === view.key ? link.b : link.a) + 1, filter.links.get(link.key)??0]);}} onSelect={index => {const link = group.links[index]; select({kind: 'pairs', title: t('Crossing pairs'), indices: link.indices, link});}} /></>; }
  if (view.kind === 'page') return pairs(model.rows.map((_, index) => index), 'Pairs on this page');
  return <List title="All groups" indices={model.groups.map(group => group.id)} label={index => {const group = model.groups[index]; return t('Group {0} · {1} wallets · {2} internal pairs', [index + 1, group.members.length, filter.groupInternal[group.id]]);}} onSelect={key => go({kind: 'group', key})} />;
}
