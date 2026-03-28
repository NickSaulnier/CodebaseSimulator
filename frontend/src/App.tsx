import { useCallback, useEffect, useState, type CSSProperties } from "react";
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
import { estimateNodeBox, layoutDagre } from "./layoutGraph";

const kindColor = (k: string, impacted: boolean) => {
  if (impacted) return "#c62828";
  if (k === "function") return "#1565c0";
  if (k === "class") return "#6a1b9a";
  if (k === "module") return "#2e7d32";
  return "#616161";
};

function selectedNodeChrome(selected: boolean): Pick<CSSProperties, "outline" | "outlineOffset" | "boxShadow" | "zIndex"> {
  if (selected) {
    return {
      outline: "3px solid #ffca28",
      outlineOffset: 2,
      boxShadow: "0 0 20px rgba(255, 202, 40, 0.55)",
      zIndex: 1000,
    };
  }
  return { outline: "none", outlineOffset: 0, boxShadow: "none", zIndex: "auto" };
}

function applySelectionToNode(node: Node, selectedId: string | null): Node {
  const isSel = selectedId !== null && node.id === selectedId;
  return {
    ...node,
    selected: isSel,
    style: {
      ...(node.style as CSSProperties),
      ...selectedNodeChrome(isSel),
    },
  };
}

function toFlow(
  rawNodes: api.GraphNode[],
  rawEdges: api.GraphEdge[],
  impacted: Set<string>,
  selectedId: string | null,
): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = rawNodes.map((n) => {
    const label = `${n.name}`;
    const { width, height } = estimateNodeBox(label);
    const isSel = selectedId !== null && n.id === selectedId;
    return {
      id: n.id,
      position: { x: 0, y: 0 },
      type: "default",
      width,
      height,
      selected: isSel,
      data: {
        label,
        sub: n.filePath?.split("/").pop() ?? "",
        kind: n.kind,
        confidence: n.confidence ?? "certain",
      },
      style: {
        background: kindColor(n.kind, impacted.has(n.id)),
        color: "#fff",
        border: n.confidence === "inferred" ? "2px dashed #ffab40" : "1px solid #444",
        fontSize: 12,
        padding: "10px 14px",
        borderRadius: 6,
        width,
        minWidth: width,
        minHeight: height,
        maxWidth: width,
        boxSizing: "border-box" as const,
        whiteSpace: "normal" as const,
        wordBreak: "break-all" as const,
        textAlign: "center" as const,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        ...selectedNodeChrome(isSel),
      },
    };
  });
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
  const [loadingAnalyze, setLoadingAnalyze] = useState(false);
  const [loadingGraphBootstrap, setLoadingGraphBootstrap] = useState(true);
  const [loadingImport, setLoadingImport] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [loadingImpact, setLoadingImpact] = useState(false);
  const [loadingTrace, setLoadingTrace] = useState(false);
  const [loadingNl, setLoadingNl] = useState(false);
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
  const [nlRagCount, setNlRagCount] = useState<number | null>(null);

  const loadLayout = useCallback(
    (g: { nodes: api.GraphNode[]; edges: api.GraphEdge[] }, impacted: Set<string>) => {
      const validSel = selected && g.nodes.some((x) => x.id === selected) ? selected : null;
      const { nodes: n, edges: e } = toFlow(g.nodes, g.edges, impacted, validSel);
      setNodes(n);
      setEdges(e);
    },
    [setEdges, setNodes, selected],
  );

  const runAnalyze = async () => {
    setError(null);
    setLoadingAnalyze(true);
    try {
      const data = await api.analyze(rootPath);
      setGraph(data);
      setImpactIds(new Set());
      loadLayout(data, new Set());
    } catch (err) {
      setError(String(err));
    } finally {
      setLoadingAnalyze(false);
    }
  };

  const onSelect = useCallback(
    async (_: React.MouseEvent, node: Node) => {
      setSelected(node.id);
      setNodes((nds) => nds.map((n) => applySelectionToNode(n, node.id)));
      setLoadingDetail(true);
      try {
        const d = await api.getNodeDetail(node.id);
        setDetail(d);
      } catch {
        setDetail(null);
      } finally {
        setLoadingDetail(false);
      }
    },
    [setNodes],
  );

  const onPaneClick = useCallback(() => {
    setSelected(null);
    setNodes((nds) => nds.map((n) => applySelectionToNode(n, null)));
    setDetail(null);
  }, [setNodes]);

  const runImpact = async () => {
    if (!selected) return;
    setError(null);
    setLoadingImpact(true);
    try {
      const { impactedNodeIds } = await api.impact(selected);
      const s = new Set(impactedNodeIds);
      setImpactIds(s);
      if (graph) loadLayout(graph, s);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoadingImpact(false);
    }
  };

  const runTrace = async () => {
    if (!selected) return;
    setError(null);
    setLoadingTrace(true);
    try {
      const t = await api.trace(selected, Math.min(200, Math.max(1, parseInt(traceDepth, 10) || 12)));
      setTraceResult(
        `Paths: ${t.paths.length} (truncated=${t.truncated}, cycles skipped=${t.cyclesSkipped})\n` +
          t.paths.map((p, i) => `${i + 1}. ${p.join(" → ")}`).join("\n"),
      );
    } catch (e) {
      setError(String(e));
    } finally {
      setLoadingTrace(false);
    }
  };

  const runNl = async () => {
    setError(null);
    setNlRagCount(null);
    setLoadingNl(true);
    try {
      const r = await api.nlQuery(nlQ, selected, true, true);
      setNlAns(r.answer);
      const sc = r.structuredContext as { ragRetrieval?: unknown[] } | undefined;
      const n = sc?.ragRetrieval?.length;
      setNlRagCount(typeof n === "number" ? n : null);
    } catch (e) {
      setNlAns(String(e));
    } finally {
      setLoadingNl(false);
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
    setError(null);
    setLoadingImport(true);
    try {
      const text = await file.text();
      const data = JSON.parse(text) as { nodes: api.GraphNode[]; edges: api.GraphEdge[] };
      await api.saveSnapshot(data);
      setGraph(data);
      setImpactIds(new Set());
      loadLayout(data, new Set());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoadingImport(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    setLoadingGraphBootstrap(true);
    api
      .getGraph()
      .then((g) => {
        if (!cancelled) {
          setGraph(g);
          loadLayout(g, new Set());
        }
      })
      .catch(() => {
        /* no graph yet */
      })
      .finally(() => {
        if (!cancelled) setLoadingGraphBootstrap(false);
      });
    return () => {
      cancelled = true;
    };
  }, [loadLayout]);

  /** App bar: user-triggered / long requests (bootstrap uses graph-area bar only). */
  const appBarBusy =
    loadingAnalyze || loadingImport || loadingImpact || loadingTrace || loadingNl;

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
          <Button variant="contained" onClick={runAnalyze} disabled={loadingAnalyze || !rootPath}>
            Analyze
          </Button>
          <Button onClick={runImpact} disabled={!selected || loadingImpact}>
            Impact
          </Button>
          <TextField
            size="small"
            label="Trace depth"
            value={traceDepth}
            onChange={(e) => setTraceDepth(e.target.value)}
            sx={{ width: 100 }}
          />
          <Button onClick={runTrace} disabled={!selected || loadingTrace}>
            Trace
          </Button>
          <Button onClick={exportSnap} disabled={!graph}>
            Export JSON
          </Button>
          <Button component="label" disabled={loadingImport}>
            {loadingImport ? "Importing…" : "Import JSON"}
            <input
              type="file"
              accept="application/json"
              hidden
              disabled={loadingImport}
              onChange={(e) => e.target.files?.[0] && importSnap(e.target.files[0])}
            />
          </Button>
        </Toolbar>
        {appBarBusy && <LinearProgress color="primary" />}
      </AppBar>

      <Box sx={{ flex: 1, display: "flex", minHeight: 0 }}>
        <Box sx={{ flex: 1, position: "relative" }}>
          {loadingGraphBootstrap && (
            <LinearProgress
              sx={{ position: "absolute", top: 0, left: 0, right: 0, zIndex: 5 }}
              color="secondary"
            />
          )}
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
            onPaneClick={onPaneClick}
            fitView
            minZoom={0.05}
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
            {loadingDetail && <LinearProgress sx={{ borderRadius: 1 }} />}
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
            {loadingTrace && <LinearProgress sx={{ borderRadius: 1 }} />}
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
            <Button variant="outlined" onClick={runNl} disabled={!nlQ || loadingNl}>
              {loadingNl ? "Querying…" : "Query"}
            </Button>
            {loadingNl && <LinearProgress sx={{ borderRadius: 1 }} />}
            {nlRagCount !== null && (
              <Typography variant="caption" color="text.secondary">
                Chroma RAG chunks used: {nlRagCount}
              </Typography>
            )}
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
