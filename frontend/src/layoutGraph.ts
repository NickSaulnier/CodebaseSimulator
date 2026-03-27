import dagre from "dagre";
import { Edge, Node } from "reactflow";

const g = new dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));

/** Approximate box for default React Flow node label (12px monospace-ish). */
export function estimateNodeBox(label: string): { width: number; height: number } {
  const charW = 7.4;
  const padX = 36;
  const padY = 22;
  const lineH = 18;
  const maxW = 400;
  const minW = 120;
  const innerMax = maxW - padX;
  const charsPerLine = Math.max(8, Math.floor(innerMax / charW));

  if (label.length <= charsPerLine) {
    const w = Math.min(maxW, Math.max(minW, Math.ceil(label.length * charW + padX)));
    return { width: w, height: 46 };
  }

  const lines = Math.ceil(label.length / charsPerLine);
  return { width: maxW, height: Math.max(46, lines * lineH + padY) };
}

export function layoutDagre(
  nodes: Node[],
  edges: Edge[],
  opts: { direction: "TB" | "LR" } = { direction: "TB" },
): Node[] {
  g.setGraph({ rankdir: opts.direction, ranksep: 88, nodesep: 48 });
  nodes.forEach((n) => {
    const w = typeof n.width === "number" ? n.width : 180;
    const h = typeof n.height === "number" ? n.height : 44;
    g.setNode(n.id, { width: w, height: h });
  });
  edges.forEach((e) => {
    g.setEdge(e.source, e.target);
  });
  dagre.layout(g);
  return nodes.map((n) => {
    const pos = g.node(n.id);
    const w = typeof n.width === "number" ? n.width : 180;
    const h = typeof n.height === "number" ? n.height : 44;
    return {
      ...n,
      position: { x: pos.x - w / 2, y: pos.y - h / 2 },
    };
  });
}
