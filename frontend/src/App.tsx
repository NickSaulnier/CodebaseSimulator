import { useCallback, useEffect, useState } from "react";
import {
  AppBar,
  Box,
  Button,
  Chip,
  Drawer,
  LinearProgress,
  Paper,
  Stack,
  TextField,
  Toolbar,
  Typography,
} from "@mui/material";
import ReactFlow, {
  Background,
  Controls,
  Edge,
  MiniMap,
  Node,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  ConnectionMode,
} from "reactflow";
import "reactflow/dist/style.css";

import * as api from "./api";
import { layoutDagre } from "./layoutGraph";

const kindColor = (k: string, impacted: boolean) => {
  if (impacted) return "#c62828";
  if (k === "function") return "#1565c0";
  if (k === "class") return "#6a1b9a";
  if (k === "module") return "#2e7d32";
  return "#616161";
};

function toFlow(
  rawNodes: api.GraphNode[],
  rawEdges: api.GraphEdge[],
  impacted: Set<string>,
): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = rawNodes.map((n) => ({
    id: n.id,
    position: { x: 0, y: 0 },
    type: "default",
    data: {
      label: `${n.name}`,
      sub: n.filePath?.split("/").pop() ?? "",
      kind: n.kind,
      confidence: n.confidence ?? "certain",
    },
    style: {
      background: kindColor(n.kind, impacted.has(n.id)),
      color: "#fff",
      border: n.confidence === "inferred" ? "2px dashed #ffab40" : "1px solid #444",
      fontSize: 12,
      padding: 8,
      borderRadius: 6,
      minWidth: 120,
    },
  }));
  const edges: Edge[] = rawEdges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    label: e.kind + (e.label ? ` ${e.label}` : ""),
    animated: e.kind === "CALLS",
    style: { stroke: e.confidence === "inferred" ? "#888" : "#bbb" },
  }));
  const laid = layoutDagre(nodes, edges);
  return { nodes: laid, edges };
}

function GraphView() {
  const [rootPath, setRootPath] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [graph, setGraph] = useState<{ nodes: api.GraphNode[]; edges: api.GraphEdge[] } | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Awaited<ReturnType<typeof api.getNodeDetail>> | null>(null);
  const [impactIds, setImpactIds] = useState<Set<string>>(new Set());
  const [traceDepth, setTraceDepth] = useState("12");
  const [traceResult, setTraceResult] = useState<string>("");
  const [nlQ, setNlQ] = useState("");
  const [nlAns, setNlAns] = useState("");

  const loadLayout = useCallback(
    (g: { nodes: api.GraphNode[]; edges: api.GraphEdge[] }, impacted: Set<string>) => {
      const { nodes: n, edges: e } = toFlow(g.nodes, g.edges, impacted);
      setNodes(n);
      setEdges(e);
    },
    [setEdges, setNodes],
  );

  const runAnalyze = async () => {
    setError(null);
    setLoading(true);
    try {
      const data = await api.analyze(rootPath);
      setGraph(data);
      setImpactIds(new Set());
      loadLayout(data, new Set());
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  };

  const onSelect = useCallback(
    async (_: React.MouseEvent, node: Node) => {
      setSelected(node.id);
      try {
        const d = await api.getNodeDetail(node.id);
        setDetail(d);
      } catch {
        setDetail(null);
      }
    },
    [],
  );

  const runImpact = async () => {
    if (!selected) return;
    setError(null);
    try {
      const { impactedNodeIds } = await api.impact(selected);
      const s = new Set(impactedNodeIds);
      setImpactIds(s);
      if (graph) loadLayout(graph, s);
    } catch (e) {
      setError(String(e));
    }
  };

  const runTrace = async () => {
    if (!selected) return;
    setError(null);
    try {
      const t = await api.trace(selected, Math.min(200, Math.max(1, parseInt(traceDepth, 10) || 12)));
      setTraceResult(
        `Paths: ${t.paths.length} (truncated=${t.truncated}, cycles skipped=${t.cyclesSkipped})\n` +
          t.paths.map((p, i) => `${i + 1}. ${p.join(" → ")}`).join("\n"),
      );
    } catch (e) {
      setError(String(e));
    }
  };

  const runNl = async () => {
    setError(null);
    try {
      const r = await api.nlQuery(nlQ, selected, true);
      setNlAns(r.answer);
    } catch (e) {
      setNlAns(String(e));
    }
  };

  const exportSnap = () => {
    if (!graph) return;
    const blob = new Blob([JSON.stringify(graph, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "graph-snapshot.json";
    a.click();
  };

  const importSnap = async (file: File) => {
    try {
      const text = await file.text();
      const data = JSON.parse(text) as { nodes: api.GraphNode[]; edges: api.GraphEdge[] };
      await api.saveSnapshot(data);
      setGraph(data);
      setImpactIds(new Set());
      loadLayout(data, new Set());
    } catch (e) {
      setError(String(e));
    }
  };

  useEffect(() => {
    api
      .getGraph()
      .then((g) => {
        setGraph(g);
        loadLayout(g, new Set());
      })
      .catch(() => {
        /* no graph yet */
      });
  }, [loadLayout]);

  return (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <AppBar position="static" color="default" elevation={1}>
        <Toolbar variant="dense" sx={{ gap: 2, flexWrap: "wrap" }}>
          <Typography variant="h6" sx={{ mr: 2 }}>
            Codebase Simulator
          </Typography>
          <TextField
            size="small"
            label="Repo root path"
            value={rootPath}
            onChange={(e) => setRootPath(e.target.value)}
            sx={{ minWidth: 280 }}
          />
          <Button variant="contained" onClick={runAnalyze} disabled={loading || !rootPath}>
            Analyze
          </Button>
          <Button onClick={runImpact} disabled={!selected}>
            Impact
          </Button>
          <TextField
            size="small"
            label="Trace depth"
            value={traceDepth}
            onChange={(e) => setTraceDepth(e.target.value)}
            sx={{ width: 100 }}
          />
          <Button onClick={runTrace} disabled={!selected}>
            Trace
          </Button>
          <Button onClick={exportSnap} disabled={!graph}>
            Export JSON
          </Button>
          <Button component="label">
            Import JSON
            <input
              type="file"
              accept="application/json"
              hidden
              onChange={(e) => e.target.files?.[0] && importSnap(e.target.files[0])}
            />
          </Button>
        </Toolbar>
        {loading && <LinearProgress />}
      </AppBar>

      <Box sx={{ flex: 1, display: "flex", minHeight: 0 }}>
        <Box sx={{ flex: 1, position: "relative" }}>
          {error && (
            <Typography color="error" sx={{ position: "absolute", top: 8, left: 8, zIndex: 10 }}>
              {error}
            </Typography>
          )}
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={onSelect}
            fitView
            connectionMode={ConnectionMode.Loose}
          >
            <Background />
            <Controls />
            <MiniMap />
          </ReactFlow>
        </Box>

        <Drawer variant="permanent" anchor="right" open PaperProps={{ sx: { width: 400, boxSizing: "border-box" } }}>
          <Toolbar />
          <Stack spacing={2} sx={{ p: 2 }}>
            {impactIds.size > 0 && (
            <Chip color="error" size="small" label={`Impacted highlight: ${impactIds.size} nodes`} />
          )}
          <Typography variant="subtitle2">Node detail</Typography>
            {detail ? (
              <>
                <Chip size="small" label={detail.node.kind} />
                <Typography variant="body2" fontWeight="bold">
                  {detail.node.name}
                </Typography>
                <Typography variant="caption" color="text.secondary" sx={{ wordBreak: "break-all" }}>
                  {detail.node.filePath}
                </Typography>
                <Typography variant="caption">Confidence: {detail.node.confidence ?? "certain"}</Typography>
                <Paper variant="outlined" sx={{ p: 1, maxHeight: 160, overflow: "auto" }}>
                  <Typography component="pre" variant="caption" sx={{ whiteSpace: "pre-wrap", m: 0 }}>
                    {detail.snippet ?? "No snippet"}
                  </Typography>
                </Paper>
                <Typography variant="caption">Callers ({detail.callers.length})</Typography>
                <Stack direction="row" flexWrap="wrap" gap={0.5}>
                  {detail.callers.map((c) => (
                    <Chip key={c.id} size="small" label={c.name} variant="outlined" />
                  ))}
                </Stack>
                <Typography variant="caption">Callees ({detail.callees.length})</Typography>
                <Stack direction="row" flexWrap="wrap" gap={0.5}>
                  {detail.callees.map((c) => (
                    <Chip key={c.id} size="small" label={c.name} variant="outlined" />
                  ))}
                </Stack>
              </>
            ) : (
              <Typography variant="body2" color="text.secondary">
                Select a node
              </Typography>
            )}

            <Typography variant="subtitle2">Trace (from selected)</Typography>
            <Paper variant="outlined" sx={{ p: 1, maxHeight: 200, overflow: "auto" }}>
              <Typography component="pre" variant="caption" sx={{ whiteSpace: "pre-wrap", m: 0 }}>
                {traceResult || "Run Trace after selecting an entry node"}
              </Typography>
            </Paper>

            <Typography variant="subtitle2">Ask Ollama (structured context)</Typography>
            <TextField
              fullWidth
              size="small"
              multiline
              minRows={2}
              placeholder="What breaks if I change this?"
              value={nlQ}
              onChange={(e) => setNlQ(e.target.value)}
            />
            <Button variant="outlined" onClick={runNl} disabled={!nlQ}>
              Query
            </Button>
            <Paper variant="outlined" sx={{ p: 1, maxHeight: 200, overflow: "auto" }}>
              <Typography variant="caption" sx={{ whiteSpace: "pre-wrap" }}>
                {nlAns || "—"}
              </Typography>
            </Paper>
          </Stack>
        </Drawer>
      </Box>
    </Box>
  );
}

export default function App() {
  return (
    <ReactFlowProvider>
      <GraphView />
    </ReactFlowProvider>
  );
}
