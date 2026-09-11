import { t, useLocale } from './i18n';
import { Component, lazy, Suspense, useEffect, useState, type ErrorInfo, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
// Routing and icons stay in the browser shell; execution remains behind the existing API.
import { QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Link, NavLink, Navigate, Outlet, Route, Routes, useLocation, useParams } from 'react-router-dom';
import { Activity, ArrowUpRight, Boxes, ChartNoAxesCombined, Database, FlaskConical, Layers, LayoutDashboard, Menu, Play, Workflow, X } from 'lucide-react';
// One same-origin application owns navigation, data requests, theme, and all strategy results.
import { queryClient } from './api';
import { Button, Card, Failure, Loading } from './ui';
import './styles.css';
import { SettingsMenu } from './preferences';
const Research = lazy(() => import('./research/page'));
const Workspace = lazy(() => import('./workspace').then(module => ({ default: module.Overview })));
const Jobs = lazy(() => import('./workspace').then(module => ({ default: module.JobsPanel })));
// Separate route chunks keep heavy charts and graph layout out of the initial shell.
const Runs = lazy(() => import('./workspace').then(module => ({ default: module.RunsPanel })));
const Resources = lazy(() => import('./workspace').then(module => ({ default: module.Resources })));
const Artifacts = lazy(() => import('./workspace').then(module => ({ default: module.Artifacts })));
const Results = lazy(() => import('./results').then(module => ({ default: module.StrategyResults })));
const Launch = lazy(() => import('./forms').then(module => ({ default: module.Launch })));
// Forms are ordinary React routes; no legacy markup or event handlers are embedded.
const Data = lazy(() => import('./forms').then(module => ({ default: module.DatasetPreparation })));
const ML = lazy(() => import('./forms').then(module => ({ default: module.MachineLearning })));
const navigation = [ { to: '/research', label: 'On-chain research', icon: Activity }, { to: '/', label: "Overview", icon: LayoutDashboard }, { to: '/runs', label: "Strategy results", icon: ChartNoAxesCombined }, { to: '/launch', label: "Launch strategy", icon: Play }, { to: '/jobs', label: "Job queue", icon: Workflow }, { to: '/data', label: "Prepare data", icon: Database }, { to: '/ml', label: "Models and features", icon: FlaskConical }, { to: '/artifacts', label: "Artifacts and lineage", icon: Layers }, { to: '/resources', label: "Resources", icon: Boxes } ];

// Attribution is shared by every route and keeps the current dashboard open when followed.
function AuthorCredit() {
  return <p className="author-credit">{t('Made by')} <a href="https://github.com/happyer29" target="_blank" rel="noopener noreferrer">happyer29</a></p>;
}

// The shell keeps local navigation and preferences separate from durable execution.
function Shell() {
  useLocale();
  const [menu, setMenu] = useState(false);
  const location = useLocation();
  useEffect(() => { setMenu(false); window.scrollTo(0, 0); }, [location.pathname]);
  // Navigation never clears the durable queue or triggers new execution implicitly.
  return <div className="app-shell"><a className="skip-link" href="#main">{t("Skip to content")}</a><aside className={`sidebar ${menu ? 'is-open' : ''}`}><Link className="brand" to="/"><span><Activity size={24} /></span><div>onchain backtest engine<small>STRATEGY WORKSPACE</small></div></Link>
    <div className="sidebar-label">{t("Workspace")}</div><nav aria-label={t("Main navigation")}>{navigation.map(item => <NavLink key={item.to} to={item.to} end={item.to === '/'}><item.icon size={18} /><span>{t(item.label)}</span></NavLink>)}</nav>
    <div className="sidebar-bottom"><div className="local-badge"><span /> {t("Local execution")}</div><SettingsMenu /><p>{t("Verified data.")}<br />{t("Reproducible results.")}</p><AuthorCredit /></div></aside>
    <div className="main-shell"><header className="topbar"><Button className="menu-button" aria-label={menu ? t("Close menu") : t("Open menu")} aria-expanded={menu} onClick={() => setMenu(!menu)}>{menu ? <X size={19} /> : <Menu size={19} />}</Button><div className="breadcrumb">Workspace <span>/</span> <strong>{t(navigation.find(item => item.to === location.pathname)?.label ?? 'Results and details')}</strong></div><Link to="/launch" className="topbar-action">{t("New run")} <ArrowUpRight size={15} /></Link></header>
      <main id="main" tabIndex={-1}><Boundary key={location.pathname}><Suspense fallback={<Loading />}><Outlet /></Suspense></Boundary></main><footer className="app-footer"><span>BACKTEST / RESEARCH WORKSPACE</span><span>Exact inputs · Deterministic replay</span></footer></div></div>;
}
class Boundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  // Render failures show a safe recovery action without exposing stack traces in product UI.
  componentDidCatch(_error: Error, _info: ErrorInfo) { /* React diagnostics remain available in the developer console. */ }
  render() { return this.state.failed ? <Failure message={t("Could not render this screen. Reload the page to try again.")} retry={() => window.location.reload()} /> : this.props.children; }
}
function ResultRoute() {
  useLocale(); const { runId = '' } = useParams(); return <Results key={runId} runId={runId} />; }
function ArtifactRoute() {
  useLocale(); const { artifactId } = useParams(); return <Artifacts key={artifactId ?? 'lookup'} artifactId={artifactId} />; }
// Historical bookmarks redirect to the common result page while retaining only the exact run ID.
function LegacyResult() {
  useLocale(); const location = useLocation(); const id = new URLSearchParams(location.search).get('run_artifact_id'); return <Navigate replace to={id ? `/runs/${encodeURIComponent(id)}` : '/runs'} />; }
function Application() {
  useLocale();
  return <QueryClientProvider client={queryClient}><BrowserRouter><Routes><Route element={<Shell />}><Route index element={<Workspace />} /><Route path="research" element={<Research />} /><Route path="runs" element={<Runs />} /><Route path="runs/:runId" element={<ResultRoute />} /><Route path="launch" element={<Launch />} /><Route path="jobs" element={<Jobs />} /><Route path="data" element={<Data />} /><Route path="ml" element={<ML />} /><Route path="resources" element={<Resources />} /><Route path="artifacts" element={<ArtifactRoute />} /><Route path="artifacts/:artifactId" element={<ArtifactRoute />} /><Route path="sniping-results" element={<LegacyResult />} /><Route path="copy-results" element={<LegacyResult />} /><Route path="*" element={<Card><h1>{t("Page not found")}</h1><Button asChild><Link to="/">{t("Back to overview")}</Link></Button></Card>} /></Route></Routes></BrowserRouter></QueryClientProvider>;
}
// React alone owns the mounted application tree.
createRoot(document.getElementById('root')!).render(<Application />);
