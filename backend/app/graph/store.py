from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import networkx as nx

from app.models import Confidence, EdgeKind, GraphEdge, GraphNode, GraphPayload, NodeKind


def _edge_id(source: str, target: str, kind: EdgeKind, label: str | None = None) -> str:
    base = f"{source}|{kind.value}|{target}"
    if label:
        base += f"|{label}"
    return base


class GraphStore:
    """In-memory directed graph with reverse index for callers / impact."""

    def __init__(self) -> None:
        self._g = nx.MultiDiGraph()
        self._nodes: dict[str, GraphNode] = {}

    def clear(self) -> None:
        self._g.clear()
        self._nodes.clear()

    def add_node(self, node: GraphNode) -> None:
        self._nodes[node.id] = node
        if not self._g.has_node(node.id):
            self._g.add_node(node.id, payload=node)

    def add_edge(
        self,
        source: str,
        target: str,
        kind: EdgeKind,
        confidence: Confidence = Confidence.CERTAIN,
        label: str | None = None,
    ) -> GraphEdge:
        eid = _edge_id(source, target, kind, label)
        if self._g.has_edge(source, target, key=eid):
            eid = f"{eid}:{uuid.uuid4().hex[:8]}"
        edge = GraphEdge(
            id=eid,
            source=source,
            target=target,
            kind=kind,
            confidence=confidence,
            label=label,
        )
        self._g.add_edge(source, target, key=edge.id, kind=kind.value, edge=edge)
        return edge

    def get_node(self, node_id: str) -> GraphNode | None:
        return self._nodes.get(node_id)

    def nodes(self) -> list[GraphNode]:
        return list(self._nodes.values())

    def edges(self) -> list[GraphEdge]:
        out: list[GraphEdge] = []
        for _u, _v, _key, data in self._g.edges(keys=True, data=True):
            e = data.get("edge")
            if isinstance(e, GraphEdge):
                out.append(e)
        return out

    def call_successors(self, node_id: str) -> list[str]:
        succ: list[str] = []
        for _u, v, _k, data in self._g.out_edges(node_id, keys=True, data=True):
            if data.get("kind") == EdgeKind.CALLS.value:
                succ.append(v)
        return succ

    def call_predecessors(self, node_id: str) -> list[str]:
        pred: list[str] = []
        for u, _v, _k, data in self._g.in_edges(node_id, keys=True, data=True):
            if data.get("kind") == EdgeKind.CALLS.value:
                pred.append(u)
        return pred

    def impact_nodes(self, node_id: str) -> tuple[list[str], list[str]]:
        """Nodes that transitively call node_id (call-graph ancestors)."""
        impacted: set[str] = set()
        order: list[str] = []
        stack = list(self.call_predecessors(node_id))
        while stack:
            pred = stack.pop()
            if pred in impacted:
                continue
            impacted.add(pred)
            order.append(pred)
            stack.extend(self.call_predecessors(pred))
        return list(impacted), order

    def to_payload(self) -> GraphPayload:
        return GraphPayload(nodes=self.nodes(), edges=self.edges())

    def to_dict(self) -> dict[str, Any]:
        p = self.to_payload()
        return {
            "nodes": [n.model_dump(by_alias=True, mode="json") for n in p.nodes],
            "edges": [e.model_dump(by_alias=True, mode="json") for e in p.edges],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GraphStore:
        store = cls()
        for raw in data.get("nodes", []):
            store.add_node(GraphNode.model_validate(raw))
        for raw in data.get("edges", []):
            e = GraphEdge.model_validate(raw)
            store._g.add_edge(
                e.source,
                e.target,
                key=e.id,
                kind=e.kind.value,
                edge=e,
            )
        return store

    def save_json(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load_json(cls, path: Path) -> GraphStore:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)


def ensure_module_node(store: GraphStore, file_path: str) -> str:
    """One module node per file."""
    norm = file_path.replace("\\", "/")
    mid = f"module::{norm}"
    if store.get_node(mid):
        return mid
    store.add_node(
        GraphNode(
            id=mid,
            kind=NodeKind.MODULE,
            name=Path(norm).name,
            filePath=norm,
        )
    )
    return mid
