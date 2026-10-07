import { Component, lazy, Suspense, useEffect, useState, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { HashRouter, Link, NavLink, Navigate, Outlet, Route, Routes, useLocation, useParams, useSearchParams } from 'react-router-dom';
import { QueryClientProvider, useQuery } from '@tanstack/react-query';
import { Activity, Boxes, ChartNoAxesCombined, Database, FlaskConical, Layers, LayoutDashboard, Menu, Play, Workflow, X } from 'lucide-react';
import { api, errorText, queryClient, type Schema } from '../api';
import { t, useLocale } from '../i18n';
import { SettingsMenu } from '../preferences';
import { Button, Card, Failure, Loading, PageTitle } from '../ui';
import { summary } from '../research/contracts';
import { ResearchMethod } from '../research/method';
import { demoClient } from './transport';
import type { DemoCatalog, HistoricalCatalog, SyntheticCatalog } from './client';
import { StaticPreviewProvider } from '../preview';
import '../styles.css';
import './style.css';

const ResearchResult = lazy(() => import('../research/page').then(module => ({ default: module.ResearchResult })));
const StrategyResults = lazy(() => import('../results').then(module => ({ default: module.StrategyResults })));
const LineageGraph = lazy(() => import('../lineage').then(module => ({ default: module.LineageGraph })));
const WorkspaceOverview = lazy(() => import('../workspace').then(module => ({ default: module.Overview })));
const WorkspaceRuns = lazy(() => import('../workspace').then(module => ({ default: module.RunsPanel })));
const Jobs = lazy(() => import('../workspace').then(module => ({ default: module.JobsPanel })));
const Resources = lazy(() => import('../workspace').then(module => ({ default: module.Resources })));
const Artifacts = lazy(() => import('../workspace').then(module => ({ default: module.Artifacts })));
const Launch = lazy(() => import('../forms').then(module => ({ default: module.Launch })));
const PrepareData = lazy(() => import('../forms').then(module => ({ default: module.DatasetPreparation })));
const Models = lazy(() => import('../forms').then(module => ({ default: module.MachineLearning })));
const ResearchWorkspace = lazy(() => import('../research/page'));
const workspaceNavigation = [
  { to: '/research', label: 'On-chain research', icon: Activity },
  { to: '/', label: 'Overview', icon: LayoutDashboard },
  { to: '/runs', label: 'Strategy results', icon: ChartNoAxesCombined },
  { to: '/launch', label: 'Launch strategy', icon: Play },
  { to: '/jobs', label: 'Job queue', icon: Workflow },
  { to: '/data', label: 'Prepare data', icon: Database },
  { to: '/ml', label: 'Models and features', icon: FlaskConical },
  { to: '/artifacts', label: 'Artifacts and lineage', icon: Layers },
  { to: '/resources', label: 'Resources', icon: Boxes },
  { to: '/dataset', label: 'Published dataset', icon: Database },
];
function useText() { const locale = useLocale(); return (en: string, ru: string) => locale === 'ru' ? ru : en; }
function useCatalog() { return useQuery({ queryKey: ['demo-catalog'], queryFn: () => demoClient.catalog() }); }
function Ready({ children }: { children: (catalog: DemoCatalog) => ReactNode }) {
  const query = useCatalog();
  return query.isError ? <Failure message={errorText(query.error)} retry={() => void query.refetch()} /> : query.data ? children(query.data) : <Loading />;
}

function Layout() {
  const text = useText(), catalog = useCatalog().data, historical = catalog?.synthetic === false;
  const pendingLabel = text('Prepared results', 'Готовые результаты');
  const [menu, setMenu] = useState(false), location = useLocation();
  useEffect(() => { setMenu(false); window.scrollTo(0, 0); }, [location.pathname]);
  return <div className="app-shell">
    <a className="skip-link" href="#main" onClick={event => { event.preventDefault(); document.getElementById('main')?.focus(); }}>{t('Skip to content')}</a>
    <aside className={`sidebar ${menu ? 'is-open' : ''}`}>
      <Link className="brand" to="/"><span><Activity size={24} /></span><div>onchain backtest engine<small>{!catalog ? pendingLabel : historical ? text('VERSION 0.2 · HISTORY', 'ВЕРСИЯ 0.2 · ИСТОРИЯ') : t('INTERACTIVE DEMO')}</small></div></Link>
      <nav aria-label={t('Main navigation')}>
        {historical ? workspaceNavigation.map(item => <NavLink key={item.to} to={item.to} end={item.to === '/'}><item.icon size={18} /><span>{item.label}</span></NavLink>) : <><NavLink to="/" end>{t('Demo overview')}</NavLink>{catalog?.synthetic && <NavLink to="/research">{t('On-chain research')}</NavLink>}<NavLink to="/runs">{t('Strategy results')}</NavLink></>}
      </nav>
      <div className="sidebar-bottom"><SettingsMenu /><p>{historical ? text('Prepared backtests · read only', 'Готовые бэктесты · просмотр') : t('Prepared examples · read only')}</p><p className="author-credit">{t('Made by')} <a href="https://github.com/happyer29" target="_blank" rel="noopener noreferrer">happyer29</a></p></div>
    </aside>
    <div className="main-shell">
      <header className="topbar"><Button className="menu-button" aria-label={t(menu ? 'Close menu' : 'Open menu')} aria-expanded={menu} onClick={() => setMenu(!menu)}>{menu ? <X /> : <Menu />}</Button><span>{!catalog ? pendingLabel : historical ? text('Historical data · version 0.2', 'Исторические данные · версия 0.2') : t('Explore the interface with synthetic examples')}</span></header>
      <div className="demo-banner" role="note"><strong>{!catalog ? pendingLabel : historical ? text('Real history · simulated strategies', 'Реальная история · симуляция стратегий') : t('Demo · test data')}</strong><span>{!catalog ? text('Read-only results, prepared offline.', 'Результаты рассчитаны заранее и доступны для просмотра.') : historical ? 'Explore the complete interface and prepared backtests. Execution is disabled on this static site.' : t('Calculated offline. No live wallets, source connection or new job execution.')}</span></div>
      <main id="main" tabIndex={-1}><Boundary key={location.pathname}><Suspense fallback={<Loading />}><Outlet /></Suspense></Boundary></main>
      <footer className="app-footer">{!catalog ? pendingLabel : historical ? text('OnchainDivers history · simulated results', 'История OnchainDivers · результаты симуляции') : t('Synthetic fixtures · no profitability claim')}</footer>
    </div>
  </div>;
}
class Boundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? <Failure message={t('Could not render this screen. Reload the page to try again.')} retry={() => window.location.reload()} /> : this.props.children; }
}

function RunCards({ catalog }: { catalog: DemoCatalog }) {
  const text = useText();
  return <div className="demo-cards">{catalog.runs.map(run => <Card key={run.id}>
    <h2>{t(run.title)}</h2>
    <p>{catalog.synthetic ? t(run.mode === 'EXOGENOUS_REPLAY' ? 'Inspect an entry and exhausted sell attempts under observed reserves.' : 'Inspect a completed trade with explicitly synthetic sell funding.') : run.mode === 'EXOGENOUS_REPLAY' ? text('Replay using observed reserves. Inspect entries, exit attempts and the resulting positions.', 'Воспроизведение с наблюдаемыми резервами. Изучайте входы, попытки выхода и итоговые позиции.') : text('Virtual settlement may supply synthetic SOL for exits. The result does not establish on-chain executability.', 'Виртуальный расчёт может добавлять синтетический SOL для выходов. Результат не доказывает исполнимость в сети.')}</p>
    <code className="demo-run-id" title={run.id}>{run.id.slice(0, 16)}</code>
    <Button asChild><Link to={`/runs/${run.id}`}>{catalog.synthetic ? t('Open test result') : text('Explore backtest', 'Открыть бэктест')}</Link></Button>
  </Card>)}</div>;
}
function HistoricalOverview({ catalog }: { catalog: HistoricalCatalog }) {
  const text = useText(), locale = useLocale();
  const date = (value: string) => new Intl.DateTimeFormat(locale === 'ru' ? 'ru-RU' : 'en-GB', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }).format(new Date(value));
  return <>
    <PageTitle eyebrow={text(`VERSION ${catalog.version}`, `ВЕРСИЯ ${catalog.version}`)} title={text('Two hours of on-chain history', 'Два часа ончейн-истории')} />
    <p className="intro-text">{text('Explore strategy backtests prepared with the version 0.2 engine on a fixed historical window from OnchainDivers. The market observations are real; the strategy trades are simulated.', 'Изучайте бэктесты, заранее рассчитанные движком версии 0.2 на фиксированном историческом интервале OnchainDivers. Рыночные наблюдения реальны; сделки стратегий смоделированы.')}</p>
    <Card><h2>{text('Published dataset', 'Опубликованный датасет')}</h2>
      <dl className="demo-facts">
        <div><dt>{text('Source', 'Источник')}</dt><dd>{catalog.source.name}</dd></div>
        <div><dt>{text('Window (UTC)', 'Интервал (UTC)')}</dt><dd><time dateTime={catalog.source.start_utc}>{date(catalog.source.start_utc)}</time><span> → </span><time dateTime={catalog.source.end_utc}>{date(catalog.source.end_utc)}</time></dd></div>
        <div><dt>{text('Duration', 'Длительность')}</dt><dd>{text('2 hours · 7,200 seconds', '2 часа · 7 200 секунд')}</dd></div>
        <div><dt>{text('Block range', 'Диапазон блоков')}</dt><dd><code>{catalog.source.from_block_ordinal} → {catalog.source.to_block_ordinal}</code></dd></div>
        <div><dt>{text('Verified snapshots', 'Проверенные снимки')}</dt><dd>{catalog.source.snapshot_ids.length}</dd></div>
        <div><dt>{text('Prepared backtests', 'Готовые бэктесты')}</dt><dd>{catalog.runs.length}</dd></div>
      </dl>
      <details className="demo-snapshots"><summary>{text('Snapshot identities', 'Идентификаторы снимков')}</summary><ul>{catalog.source.snapshot_ids.map(id => <li key={id}><Link to={`/artifacts/${id}`}><code>{id}</code></Link></li>)}</ul></details>
    </Card>
    <div className="section-intro"><h2>{text('Choose a prepared backtest', 'Выберите готовый бэктест')}</h2></div>
    <RunCards catalog={catalog} />
    <Card><h2>{text('What you can explore', 'Что можно изучить')}</h2><p>{text('Open a result to inspect summary metrics, entry and exit analytics, every exported trade, available market charts and artifact lineage. Pagination and chart controls work entirely with the published data.', 'Откройте результат, чтобы изучить метрики, аналитику входов и выходов, все опубликованные сделки, доступные рыночные графики и происхождение артефактов. Страницы таблиц и графики работают на опубликованных данных.')}</p><p>{text('This site presents completed calculations. Changing strategy parameters or preparing another time window requires the local application.', 'Сайт показывает завершённые расчёты. Для изменения параметров стратегии или подготовки другого интервала нужно локальное приложение.')}</p></Card>
  </>;
}
function SyntheticOverview({ catalog }: { catalog: SyntheticCatalog }) {
  return <><PageTitle eyebrow={t('Prepared examples')} title={t('Explore the demo')} /><p className="intro-text">{t('Inspect wallet connections and trace simulated trade outcomes. Every example uses generated test inputs, calculated by the project’s existing Python code.')}</p><Card><h2>{t('Wallet groups and shared purchases')}</h2><p>{t('{0} wallets · {1} pairs in the Non-Mayhem example', [catalog.wallets, catalog.research[0].counts.pairs])}</p><p>{t('Open groups, follow a wallet across groups, filter weaker links and inspect the purchases behind a pair.')}</p><Button asChild tone="primary"><Link to="/research">{t('Open wallet graph')}</Link></Button></Card><div className="section-intro"><h2>{t('Two execution outcomes')}</h2></div><RunCards catalog={catalog} /><Card><h3>{t('About the examples')}</h3><p>{t('The research fixture includes later repeat purchases, Mayhem tokens and missing creation data. Strategy examples show the same small Copy Buy scenario under two execution modes.')}</p><p>{t('Preparing data and running strategies require the local application. This site only displays exported results.')}</p></Card></>;
}
function Overview() { useLocale(); return <Ready>{catalog => catalog.synthetic ? <SyntheticOverview catalog={catalog} /> : <><WorkspaceOverview /><Card><h2>Published historical dataset</h2><p>Explore two hours of OnchainDivers observations and the prepared strategy variants.</p><Button asChild><Link to="/dataset">View dataset and backtests</Link></Button></Card></>}</Ready>; }
function Dataset() { return <Ready>{catalog => catalog.synthetic ? <SyntheticOverview catalog={catalog} /> : <HistoricalOverview catalog={catalog} />}</Ready>; }
function Research() {
  useLocale(); const [params, setParams] = useSearchParams();
  return <Ready>{catalog => catalog.synthetic ? <ResearchView key={params.get('artifact') ?? catalog.research[0].id} catalog={catalog} artifact={params.get('artifact') ?? catalog.research[0].id} select={id => setParams({ artifact: id })} /> : <ResearchWorkspace />}</Ready>;
}
function ResearchView({ catalog, artifact, select }: { catalog: SyntheticCatalog; artifact: string; select: (id: string) => void }) {
  const allowed = [catalog.snapshot, ...catalog.research.map(r => r.id)].includes(artifact);
  const query = useQuery({ queryKey: ['research-summary', artifact], enabled: allowed, queryFn: ({ signal }) => summary(artifact, signal) });
  return <><PageTitle title={t('On-chain research')} eyebrow={t('Synthetic observations')} /><Card><label>{t('Prepared research example')}<select value={artifact} onChange={event => select(event.target.value)}>{catalog.research.map(r => <option value={r.id} key={r.id}>{t(r.mode === 'NON_MAYHEM' ? 'Without Mayhem' : 'All modes')}</option>)}<option value={catalog.snapshot}>{t('Source observations')}</option></select></label><p>{t('This selects a result calculated offline. Display filters below change only visible relationships.')}</p></Card><ResearchMethod />{!allowed ? <Failure message={t('This item is not included in the demo.')} /> : query.isError ? <Failure message={errorText(query.error)} retry={() => void query.refetch()} /> : query.data ? <ResearchResult data={query.data} wholeGraph /> : <Loading />}</>;
}
function Runs() {
  const text = useText();
  return <Ready>{catalog => <>{catalog.synthetic ? <PageTitle title={t('Strategy results')} eyebrow={t('Prepared examples')} /> : <><WorkspaceRuns /><div className="section-intro"><h2>{text('Prepared historical backtests', 'Готовые исторические бэктесты')}</h2></div></>}<RunCards catalog={catalog} /></>}</Ready>;
}
function Run() {
  const { runId = '' } = useParams(); useLocale();
  return <Ready>{catalog => catalog.runs.some(run => run.id === runId) ? <StrategyResults key={runId} runId={runId} demo={catalog.synthetic ? true : 'historical'} /> : <Failure message={t('This item is not included in the demo.')} />}</Ready>;
}
function Provenance() {
  const text = useText(), catalog = useCatalog().data, { artifactId = '' } = useParams();
  const query = useQuery({ queryKey: ['demo-lineage', artifactId], queryFn: ({ signal }) => api<Schema<'ArtifactLineageResponse'>>(`/api/v1/lineage/${artifactId}`, { signal }) });
  return <><PageTitle title={catalog?.synthetic === false ? text('Offline provenance', 'Происхождение данных') : t('Offline provenance')} eyebrow={catalog?.synthetic === false ? text('Historical data and simulated results', 'Исторические данные и результаты симуляции') : t('Synthetic fixtures')} /><p>{catalog?.synthetic === false ? text('Artifact identities and dependencies were verified before export. Follow the links to trace each result to its prepared input snapshots.', 'Идентификаторы артефактов и зависимости проверены перед экспортом. Переходите по ссылкам, чтобы проследить каждый результат до подготовленных входных снимков.') : t('These IDs and dependencies were verified while preparing the test examples. The static site contains presentation exports, not executable artifact files.')}</p>{query.isError ? <Failure message={errorText(query.error)} retry={() => void query.refetch()} /> : query.data ? <LineageGraph data={query.data} /> : <Loading />}</>;
}
function ArtifactPage() {
  const { artifactId } = useParams();
  return <Ready>{catalog => catalog.synthetic ? <Provenance /> : <><Artifacts key={artifactId ?? 'lookup'} artifactId={artifactId} />{!artifactId && <Card><h2>Published artifacts</h2><p>Open a prepared snapshot or result to inspect its public metadata and dependency graph.</p><ul className="demo-snapshots">{catalog.source.snapshot_ids.map(id => <li key={id}><Link to={`/artifacts/${id}`}>Snapshot <code>{id}</code></Link></li>)}{catalog.runs.map(run => <li key={run.id}><Link to={`/artifacts/${run.id}`}>{run.title} <code>{run.id}</code></Link></li>)}</ul></Card>}</>}</Ready>;
}
function PreviewPage({ children }: { children: ReactNode }) {
  return <Ready>{catalog => catalog.synthetic ? <Unavailable /> : children}</Ready>;
}
function LegacyResult() {
  const [params] = useSearchParams(), id = params.get('run_artifact_id');
  return <Navigate replace to={id ? `/runs/${encodeURIComponent(id)}` : '/runs'} />;
}
function Unavailable() {
  const text = useText(), historical = useCatalog().data?.synthetic === false;
  return <Card><h1>{historical ? text('Unavailable on this static site', 'Недоступно на статическом сайте') : t('Unavailable in the demo')}</h1><p>{historical ? text('This site shows prepared historical backtests. New strategy runs require the local application.', 'Сайт показывает готовые исторические бэктесты. Для новых запусков нужно локальное приложение.') : t('Preparing data and running strategies require the local application. This site only displays exported results.')}</p><Button asChild><Link to="/">{t('Back to overview')}</Link></Button></Card>;
}
createRoot(document.getElementById('root')!).render(<QueryClientProvider client={queryClient}><StaticPreviewProvider><HashRouter><Routes><Route element={<Layout />}><Route index element={<Overview />} /><Route path="dataset" element={<Dataset />} /><Route path="research" element={<Research />} /><Route path="runs" element={<Runs />} /><Route path="runs/:runId" element={<Run />} /><Route path="launch" element={<PreviewPage><Launch /></PreviewPage>} /><Route path="jobs" element={<PreviewPage><Jobs /></PreviewPage>} /><Route path="data" element={<PreviewPage><PrepareData /></PreviewPage>} /><Route path="ml" element={<PreviewPage><Models /></PreviewPage>} /><Route path="resources" element={<PreviewPage><Resources /></PreviewPage>} /><Route path="artifacts/:artifactId" element={<ArtifactPage />} /><Route path="artifacts" element={<ArtifactPage />} /><Route path="sniping-results" element={<LegacyResult />} /><Route path="copy-results" element={<LegacyResult />} /><Route path="*" element={<Unavailable />} /></Route></Routes></HashRouter></StaticPreviewProvider></QueryClientProvider>);
