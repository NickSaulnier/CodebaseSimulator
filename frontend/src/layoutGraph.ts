import dagre from "dagre";
import { Edge, Node } from "reactflow";

const g = new dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));

export function layoutDagre(
  nodes: Node[],
  edges: Edge[],
  opts: { direction: "TB" | "LR" } = { direction: "TB" },
): Node[] {
  g.setGraph({ rankdir: opts.direction, ranksep: 80, nodesep: 40 });
  nodes.forEach((n) => {
    g.setNode(n.id, { width: 180, height: 44 });
  });
  edges.forEach((e) => {
    g.setEdge(e.source, e.target);
  });
  dagre.layout(g);
  return nodes.map((n) => {
    const pos = g.node(n.id);
    return {
      ...n,
      position: { x: pos.x - 90, y: pos.y - 22 },
    };
  });
}
