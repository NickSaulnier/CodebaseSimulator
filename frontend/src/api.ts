const API = "/api";

export type GraphNode = {
  id: string;
  kind: string;
  name: string;
  filePath: string;
  confidence?: string;
  isAsync?: boolean;
  span?: {
    startLine: number;
    endLine: number;
  };
};

export type GraphEdge = {
  id: string;
  source: string;
  target: string;
  kind: string;
  confidence?: string;
  label?: string | null;
};

export async function analyze(rootPath: string): Promise<{ nodes: GraphNode[]; edges: GraphEdge[] }> {
  const r = await fetch(`${API}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rootPath }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function getGraph(): Promise<{ nodes: GraphNode[]; edges: GraphEdge[] }> {
  const r = await fetch(`${API}/graph`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function getNodeDetail(nodeId: string) {
  const u = new URL(`${API}/node`, window.location.origin);
  u.searchParams.set("nodeId", nodeId);
  const r = await fetch(u.toString());
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{
    node: GraphNode;
    snippet: string | null;
    callers: { id: string; name: string; kind: string; filePath: string }[];
    callees: { id: string; name: string; kind: string; filePath: string }[];
  }>;
}

export async function impact(nodeId: string): Promise<{ impactedNodeIds: string[] }> {
  const r = await fetch(`${API}/impact`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ nodeId }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function trace(entryNodeId: string, maxDepth: number) {
  const r = await fetch(`${API}/trace`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ entryNodeId, maxDepth }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ paths: string[][]; truncated: boolean; cyclesSkipped: number }>;
}

export async function nlQuery(
  question: string,
  nodeId: string | null,
  includeImpact: boolean,
  useRag = true,
) {
  const r = await fetch(`${API}/query/nl`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, nodeId, includeImpact, useRag }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ answer: string; structuredContext: unknown }>;
}

export async function saveSnapshot(data: object) {
  const r = await fetch(`${API}/snapshot`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function loadSnapshotFromServer(): Promise<object> {
  const r = await fetch(`${API}/snapshot`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
