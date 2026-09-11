import { t, useLocale } from './i18n';
import { useMemo } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Background, Controls, ReactFlow } from '@xyflow/react';
import dagre from '@dagrejs/dagre';
import '@xyflow/react/dist/style.css';
// Graph inputs are bounded verified metadata, never a filesystem listing.
import type { Schema } from './api';
import { shortId } from './format';
import { Card, Failure } from './ui';

export function LineageGraph({ data }: { data: Schema<'ArtifactLineageResponse'> }) {
  useLocale();
  const navigate = useNavigate();
  const layout = useMemo(() => {
    const ids = new Set(data.artifacts.map(item => item.artifact_id));
    // Refuse incomplete or oversized graphs rather than drawing misleading edges.
    if (ids.size !== data.artifacts.length || ids.size > 1000 || data.edges.length > 1000 || !ids.has(data.root_artifact_id)) return null;
    if (data.edges.some(edge => !ids.has(edge.input_artifact_id) || !ids.has(edge.output_artifact_id))) return null;
    const graph = new dagre.graphlib.Graph().setGraph({ rankdir: 'LR', nodesep: 30, ranksep: 70 }).setDefaultEdgeLabel(() => ({}));
    for (const item of data.artifacts) graph.setNode(item.artifact_id, { width: 220, height: 65 });
    // Inputs point to derived outputs; layout cannot invent dependencies.
    for (const edge of data.edges) graph.setEdge(edge.input_artifact_id, edge.output_artifact_id);
    dagre.layout(graph);
    return { nodes: data.artifacts.map(item => ({ id: item.artifact_id, position: { x: graph.node(item.artifact_id).x - 110, y: graph.node(item.artifact_id).y - 32.5 }, data: { label: `${item.kind} · ${shortId(item.artifact_id)}` }, className: item.artifact_id === data.root_artifact_id ? 'lineage-root' : '' })),
      edges: data.edges.map(edge => ({ id: `${edge.input_artifact_id}:${edge.output_artifact_id}`, source: edge.input_artifact_id, target: edge.output_artifact_id })) };
  }, [data]);
  // A parallel linked text list keeps every exact identity keyboard-accessible.
  if (!layout) return <Failure message={t("Invalid or oversized dependency graph.")} />;
  return <Card><h3>{t("Lineage graph")}</h3><p className="subtle">{t("From input artifacts to the result. Select a node to open it.")}</p><div className="lineage-canvas"><ReactFlow nodes={layout.nodes} edges={layout.edges} fitView nodesDraggable={false} nodesConnectable={false} onNodeClick={(_, node) => navigate(`/artifacts/${node.id}`)}><Background /><Controls showInteractive={false} /></ReactFlow></div>
    <details><summary>{t("All artifacts and dependencies ·")} {data.artifacts.length}</summary><ul className="lineage-list">{data.artifacts.map(item => <li key={item.artifact_id}><Link to={`/artifacts/${item.artifact_id}`}>{item.kind} · {item.artifact_id}</Link><small>{t("Inputs:")} {item.input_artifact_ids.join(', ') || t("none")}</small></li>)}</ul></details></Card>;
}
