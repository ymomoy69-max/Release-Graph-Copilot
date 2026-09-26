import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  MarkerType,
  useEdgesState,
  useNodesState,
  type Node,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { api, type GraphPayload, type GraphNode } from "../api";

const STATUS: Record<string, { bg: string; border: string; label: string }> = {
  broken: { bg: "#FEF2F2", border: "#DC2626", label: "Problem" },
  warning: { bg: "#FFFBEB", border: "#F59E0B", label: "Warning" },
  at_risk: { bg: "#FFF7ED", border: "#F59E0B", label: "Feels it" },
  updated: { bg: "#F0F6FF", border: "#2663EB", label: "Updated" },
  ok: { bg: "#F9FAFB", border: "#BDD0F9", label: "OK" },
};

function layout(raw: GraphNode[]): { x: number; y: number }[] {
  const byRank = new Map<number, GraphNode[]>();
  for (const n of raw) {
    const r = n.rank ?? 0;
    const list = byRank.get(r) || [];
    list.push(n);
    byRank.set(r, list);
  }
  const pos = new Map<string, { x: number; y: number }>();
  for (const [rank, list] of [...byRank.entries()].sort((a, b) => a[0] - b[0])) {
    list.forEach((n, i) => {
      pos.set(n.id, { x: rank * 250 + 24, y: i * 108 + 24 });
    });
  }
  return raw.map((n) => pos.get(n.id) || { x: 0, y: 0 });
}

export default function GraphPage({ projectId }: { projectId: number }) {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [graph, setGraph] = useState<GraphPayload | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    setErr("");
    api
      .graph(projectId)
      .then((g) => {
        setGraph(g);
        const positions = layout(g.nodes);
        const n: Node[] = g.nodes.map((node, i) => {
          const st = STATUS[node.status || "ok"] || STATUS.ok;
          return {
            id: node.id,
            data: { ...node, type: "service" },
            position: positions[i],
            style: {
              background: st.bg,
              border: `2px solid ${st.border}`,
              color: "#0E172A",
              borderRadius: 10,
              padding: 10,
              fontSize: 12,
              width: 200,
              fontWeight: node.status === "broken" ? 650 : 500,
            },
          };
        });
        const e: Edge[] = g.edges.map((edge) => ({
          id: edge.id,
          source: edge.source,
          target: edge.target,
          label: edge.broken ? "breaking" : undefined,
          animated: Boolean(edge.broken),
          style: edge.broken
            ? { stroke: "#DC2626", strokeWidth: 2.6 }
            : { stroke: "#BDD0F9", strokeWidth: 1.4 },
          labelStyle: { fill: "#DC2626", fontSize: 10, fontWeight: 700 },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: edge.broken ? "#DC2626" : "#BDD0F9",
            width: 16,
            height: 16,
          },
        }));
        setNodes(n);
        setEdges(e);
        const firstBroken = g.nodes.find((x) => x.status === "broken") || g.nodes.find((x) => x.status === "warning");
        setPicked(firstBroken?.id || g.nodes[0]?.id || null);
      })
      .catch((e) => setErr(e instanceof Error ? e.message : "Graph failed"));
  }, [projectId, setNodes, setEdges]);

  const selected = useMemo(
    () => graph?.nodes.find((n) => n.id === picked) || null,
    [graph, picked],
  );
  const selectedLink = useMemo(() => {
    if (!graph || !picked) return graph?.broken_links[0] || null;
    const name = picked.replace(/^service:/, "");
    return (
      graph.broken_links.find((l) => l.to === name || l.from === name) || graph.broken_links[0] || null
    );
  }, [graph, picked]);

  const onNodeClick = useCallback((_: unknown, node: Node) => {
    setPicked(node.id);
  }, []);

  const onEdgeClick = useCallback((_: unknown, edge: Edge) => {
    setPicked(edge.target);
  }, []);

  if (err) return <p className="error">{err}</p>;

  return (
    <>
      <div className="page-head">
        <div>
          <h2>Release Graph</h2>
          <p className="muted">
            Arrows mean “this service calls that one”. A red arrow is the link that breaks if the
            box it points to fails.
          </p>
        </div>
      </div>

      {graph && (
        <div className={`graph-banner ${graph.broken_links.length ? "nogo" : "go"}`}>
          <strong>{graph.broken_links.length ? "What is breaking" : "All links look healthy"}</strong>
          <p style={{ margin: "0.3rem 0 0" }}>{graph.summary}</p>
        </div>
      )}

      <div className="legend">
        <span><i className="swatch" style={{ background: "#DC2626" }} /> problem</span>
        <span><i className="swatch" style={{ background: "#F59E0B" }} /> feels it</span>
        <span><i className="swatch" style={{ background: "#2663EB" }} /> updated last ship</span>
        <span><i className="swatch" style={{ background: "#BDD0F9" }} /> ok</span>
        <span className="muted">Red arrow = breaking link</span>
      </div>

      <div className="graph-wrap">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={onNodeClick}
          onEdgeClick={onEdgeClick}
          fitView
          colorMode="light"
        >
          <Background color="#BDD0F9" gap={18} />
          <Controls />
          <MiniMap
            style={{ background: "#F9FAFB" }}
            nodeColor={(n) => (STATUS[String((n.data as GraphNode).status || "ok")] || STATUS.ok).border}
          />
        </ReactFlow>
      </div>

      <div className="graph-story">
        <div className="card">
          <h3>What is breaking</h3>
          {selectedLink ? (
            <>
              <p className="graph-link">
                <strong>{selectedLink.from}</strong>
                <span className="muted"> calls </span>
                <strong>{selectedLink.to}</strong>
              </p>
              <p style={{ margin: "0.4rem 0 0" }}>{selectedLink.why}</p>
              {selected?.file && (
                <p className="muted" style={{ margin: "0.35rem 0 0" }}>
                  {selected.file}
                  {selected.line ? `:${selected.line}` : ""}
                </p>
              )}
            </>
          ) : selected ? (
            <p style={{ margin: "0.4rem 0 0" }}>{selected.headline || "No engine finding on this box."}</p>
          ) : (
            <p className="muted">Scan a workspace, then click a box or a red arrow.</p>
          )}
        </div>
        <div className="card">
          <h3>What can be affected</h3>
          {selected ? (
            <>
              <p style={{ margin: "0.4rem 0 0" }}>{selected.if_breaks}</p>
              <p className="muted" style={{ margin: "0.4rem 0 0" }}>
                {(selected.affects || []).join(" → ") || selected.label}
              </p>
            </>
          ) : selectedLink ? (
            <p style={{ margin: "0.4rem 0 0" }}>{selectedLink.if_breaks}</p>
          ) : (
            <p className="muted">Click a red box to see who depends on it.</p>
          )}
        </div>
        <div className="card">
          <h3>What would change</h3>
          {selected ? (
            <p style={{ margin: "0.4rem 0 0" }}>{selected.would_change}</p>
          ) : selectedLink ? (
            <p style={{ margin: "0.4rem 0 0" }}>{selectedLink.would_change}</p>
          ) : (
            <p className="muted">A short note on the blast radius if you fix or ignore it.</p>
          )}
        </div>
        <div className="card">
          <h3>What was updated</h3>
          {selected?.updated ? (
            <>
              <p style={{ margin: "0.4rem 0 0" }}>
                <strong>{selected.updated.service}</strong>
                {selected.updated.version ? ` · ${selected.updated.version}` : ""}
              </p>
              <p style={{ margin: "0.35rem 0 0" }}>{selected.updated.functionality}</p>
              {(selected.updated.also || []).map((m) => (
                <p key={m} className="muted" style={{ margin: "0.2rem 0 0" }}>{m}</p>
              ))}
            </>
          ) : graph?.updates?.length ? (
            graph.updates.slice(0, 3).map((u) => (
              <p key={u.service} style={{ margin: "0.4rem 0 0" }}>
                <strong>{u.service}</strong> — {u.functionality}
              </p>
            ))
          ) : (
            <p className="muted">No last-ship notes stored for this project yet.</p>
          )}
        </div>
      </div>
    </>
  );
}
