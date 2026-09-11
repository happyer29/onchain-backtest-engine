import { Component, useEffect, useRef, useState, type ReactNode } from 'react';
import { SigmaContainer, useSigma } from '@react-sigma/core';
import type Sigma from 'sigma';
import type { Settings } from 'sigma/settings';
import type { CameraState } from 'sigma/types';
import type { ViewBounds } from './navigation';
import type { DisplayFilter, DisplayGraph, EdgeData, NodeData } from './sigma-data';

// Sigma's default hover uses a white background; the shared theme needs its own readable label.
const drawHover: Settings<NodeData, EdgeData>['defaultDrawNodeHover'] = (context, data, settings) => {
  const dark = document.documentElement.dataset.theme === 'dark';
  context.save(); context.font = `600 ${settings.labelSize}px ${settings.labelFont}`;
  context.fillStyle = dark ? '#e3976b' : '#b9673d'; context.beginPath(); context.arc(data.x,data.y,data.size+3,0,Math.PI*2);context.fill();
  context.fillStyle = data.color;context.beginPath();context.arc(data.x,data.y,data.size,0,Math.PI*2);context.fill();
  if (typeof data.label === 'string') {const x=data.x+data.size+7,y=data.y-10,w=context.measureText(data.label).width+12;context.fillStyle=dark?'#15191d':'#fffcf8';context.fillRect(x,y,w,23);context.fillStyle=dark?'#e5e6e3':'#342e29';context.fillText(data.label,x+6,y+16);}
  context.restore();
};
const settings: Partial<Settings<NodeData, EdgeData>> = {allowInvalidContainer: false, defaultDrawNodeHover: drawHover, enableEdgeEvents: true, renderEdgeLabels: true, labelDensity: .12, labelGridCellSize: 90, labelRenderedSizeThreshold: 9, labelSize: 12, labelFont: 'Inter, sans-serif', defaultEdgeType: 'line', minCameraRatio: .02, maxCameraRatio: 8, stagePadding: 45, zIndex: true};
export type RendererHandle = { sigma: Sigma<NodeData, EdgeData>; graph: DisplayGraph };
type Props = { graph: DisplayGraph; filter: DisplayFilter; focus: string | null; pair: string | null; camera?: CameraState; bounds?: ViewBounds; onReady: (handle: RendererHandle) => void; onNode: (key: string) => void; onEdge: (key: string) => void; onClear: () => void; onCamera: (camera: CameraState) => void; onFailure: (message: string) => void };

// WebGL errors are local to the graph. The verified table and purchase drilldown remain mounted.
class RendererBoundary extends Component<{children: ReactNode; onFailure: (message: string) => void}, {failed: boolean}> {
  state = {failed: false};
  static getDerivedStateFromError() {return {failed: true};}
  componentDidCatch() {this.props.onFailure('WebGL graph rendering is unavailable. Check hardware acceleration and retry; tables and original purchases remain available.');}
  render() {return this.state.failed ? null : this.props.children;}
}
export default function SigmaView(props: Props) {
  return <RendererBoundary onFailure={props.onFailure}><SigmaContainer graph={props.graph} settings={settings} className="research-sigma"><Bindings {...props} /></SigmaContainer></RendererBoundary>;
}
function Bindings(props: Props) {
  const sigma = useSigma<NodeData, EdgeData>();
  const current = useRef(props); current.current = props;
  const [hover, setHover] = useState<string | null>(null), [dark, setDark] = useState(document.documentElement.dataset.theme === 'dark');
  useEffect(() => {
    const observer = new MutationObserver(() => setDark(document.documentElement.dataset.theme === 'dark'));
    observer.observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme']});return () => observer.disconnect();
  }, []);
  useEffect(() => {
    const graph = current.current.graph;
    if (current.current.bounds) sigma.setCustomBBox(current.current.bounds);
    if (current.current.camera) sigma.getCamera().setState(current.current.camera);
    let dragged: string | null = null, moved = false;
    const down: Parameters<typeof sigma.on<'downNode'>>[1] = event => {dragged = event.node; moved = false; if (!sigma.getCustomBBox()) sigma.setCustomBBox(sigma.getBBox());};
    const move: (event: import('sigma/types').MouseCoords) => void = event => {
      if (!dragged) return;
      moved = true; const point = sigma.viewportToGraph(event); graph.mergeNodeAttributes(dragged, point); event.preventSigmaDefault(); event.original.preventDefault(); event.original.stopPropagation();
    };
    const up = () => {dragged = null;};
    const clickNode: Parameters<typeof sigma.on<'clickNode'>>[1] = event => {if (!moved) current.current.onNode(event.node); moved = false;};
    const clickEdge: Parameters<typeof sigma.on<'clickEdge'>>[1] = event => current.current.onEdge(event.edge);
    const clear = () => {if (!moved) current.current.onClear(); moved = false;};
    const enter: Parameters<typeof sigma.on<'enterNode'>>[1] = event => setHover(event.node);
    const leave = () => setHover(null);
    const camera = (state: CameraState) => current.current.onCamera(state);
    const lost = (event: Event) => {event.preventDefault(); current.current.onFailure('The WebGL context was lost. Retry this graph view; the result is still available.');};
    sigma.on('downNode', down); sigma.on('clickNode', clickNode); sigma.on('clickEdge', clickEdge); sigma.on('clickStage', clear); sigma.on('enterNode', enter); sigma.on('leaveNode', leave);
    sigma.getMouseCaptor().on('mousemovebody', move); sigma.getMouseCaptor().on('mouseup', up); sigma.getCamera().on('updated', camera);
    const canvases = Object.values(sigma.getCanvases()); canvases.forEach(canvas => canvas.addEventListener('webglcontextlost', lost));
    // A successful first paint, not just constructed graph data, completes the current projection.
    sigma.refresh(); current.current.onReady({sigma, graph}); camera(sigma.getCamera().getState());
    return () => {sigma.off('downNode', down); sigma.off('clickNode', clickNode); sigma.off('clickEdge', clickEdge); sigma.off('clickStage', clear); sigma.off('enterNode', enter); sigma.off('leaveNode', leave); sigma.getMouseCaptor().off('mousemovebody', move); sigma.getMouseCaptor().off('mouseup', up); sigma.getCamera().off('updated', camera); canvases.forEach(canvas => canvas.removeEventListener('webglcontextlost', lost));};
  }, [sigma]);
  useEffect(() => {
    const {graph, filter, pair} = props, focus = hover ?? props.focus;
    const emphasis = new Set<string>(), selectedEdge = pair && graph.hasEdge(pair) ? pair : null;
    if (focus && graph.hasNode(focus)) {emphasis.add(focus); graph.forEachEdge(focus, (_, edge, source, target) => {const shown = edge.link ? (filter.links.get(edge.link.key) ?? 0) : filter.matches[edge.index!]; if (shown) {emphasis.add(source); emphasis.add(target);}});}
    else if (selectedEdge) graph.extremities(selectedEdge).forEach(key => emphasis.add(key));
    sigma.setSetting('labelColor', {color: dark ? '#e5e6e3' : '#342e29'});
    sigma.setSetting('nodeReducer', (key, data) => ({...data, color: emphasis.size && !emphasis.has(key) ? (dark ? '#3c454a' : '#d6d0c8') : data.color, highlighted: key === focus || (selectedEdge !== null && emphasis.has(key)), forceLabel: key === focus || (selectedEdge !== null && emphasis.has(key)), zIndex: emphasis.has(key) ? 1 : 0}));
    sigma.setSetting('edgeReducer', (key, data) => {
      const count = data.link ? (filter.links.get(data.link.key) ?? 0) : filter.matches[data.index!];
      const selected = key === selectedEdge, connected = focus ? graph.hasExtremity(key, focus) : selected;
      return {...data, hidden: !count, size: selected ? 2.5 : data.link ? .5 + Math.log2(1 + count) * .25 : data.size, color: selected || (focus && connected) ? (dark ? '#e3976b' : '#b9673d') : emphasis.size ? (dark ? '#2a3533' : '#e7e2da') : dark ? '#344641' : '#b6c4ba', label: selected ? String(data.link ? count : data.weight) : null, forceLabel: selected, zIndex: selected ? 1 : 0};
    });
  }, [sigma, props.graph, props.filter, props.focus, props.pair, hover, dark]);
  return null;
}
