from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.ai.ollama_client import explain_with_ollama
from app.analyzer.js_ts import analyze_directory
from app.config import settings
from app.graph.store import GraphStore
from app.models import (
    AnalyzeRequest,
    GraphNode,
    ImpactRequest,
    ImpactResponse,
    NLQueryRequest,
    NLQueryResponse,
    TraceRequest,
    TraceResponse,
)
from app.simulator.trace import simulate_paths

app = FastAPI(title="Codebase Execution Simulator", version="0.1.0")

_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_store: GraphStore | None = None


def get_store() -> GraphStore:
    if _store is None:
        raise HTTPException(status_code=400, detail="No graph loaded. POST /api/analyze first.")
    return _store


def _node_summary(n: GraphNode) -> dict[str, Any]:
    return {
        "id": n.id,
        "kind": n.kind.value,
        "name": n.name,
        "filePath": n.file_path,
        "confidence": n.confidence.value,
        "isAsync": n.is_async,
    }


def _read_snippet(file_path: str, span: Any) -> str | None:
    if not file_path or not Path(file_path).is_file():
        return None
    try:
        text = Path(file_path).read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        if span is None:
            return None
        sl = max(1, span.start_line) - 1
        el = min(len(lines), span.end_line)
        chunk = lines[sl:el]
        return "\n".join(chunk)
    except OSError:
        return None


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _read_entry_config(root: Path) -> list[str]:
    p = root / "codebase-simulator.entries.json"
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return list(data.get("entries", []))
    except (OSError, json.JSONDecodeError, TypeError):
        return []


@app.post("/api/analyze")
def api_analyze(body: AnalyzeRequest) -> dict[str, Any]:
    global _store
    root = Path(body.root_path).resolve()
    if not root.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {root}")
    _store = analyze_directory(root)
    out = _store.to_dict()
    out["entriesFromConfig"] = _read_entry_config(root)
    return out


@app.get("/api/graph")
def api_graph() -> dict[str, Any]:
    return get_store().to_dict()


@app.get("/api/node")
def api_node_detail(node_id: str = Query(..., alias="nodeId")) -> dict[str, Any]:
    st = get_store()
    n = st.get_node(node_id)
    if not n:
        raise HTTPException(status_code=404, detail="Node not found")
    snippet = _read_snippet(n.file_path, n.span)
    return {
        "node": n.model_dump(by_alias=True, mode="json"),
        "snippet": snippet,
        "callers": [{"id": x, **_node_summary(st.get_node(x))} for x in st.call_predecessors(node_id) if st.get_node(x)],
        "callees": [{"id": x, **_node_summary(st.get_node(x))} for x in st.call_successors(node_id) if st.get_node(x)],
    }


@app.post("/api/trace", response_model=TraceResponse)
def api_trace(body: TraceRequest) -> TraceResponse:
    st = get_store()
    if st.get_node(body.entry_node_id) is None:
        raise HTTPException(status_code=404, detail="Entry node not found")
    paths, truncated, cyc = simulate_paths(st, body.entry_node_id, body.max_depth)
    return TraceResponse(paths=paths, truncated=truncated, cyclesSkipped=cyc)


@app.post("/api/impact", response_model=ImpactResponse)
def api_impact(body: ImpactRequest) -> ImpactResponse:
    st = get_store()
    if st.get_node(body.node_id) is None:
        raise HTTPException(status_code=404, detail="Node not found")
    impacted, ordered = st.impact_nodes(body.node_id)
    return ImpactResponse(impactedNodeIds=impacted, orderedByDistance=ordered)


@app.post("/api/query/nl", response_model=NLQueryResponse)
async def api_nl(body: NLQueryRequest) -> NLQueryResponse:
    st = get_store()
    ctx: dict[str, Any] = {"question": body.question}
    if body.node_id:
        n = st.get_node(body.node_id)
        if not n:
            raise HTTPException(status_code=404, detail="Node not found")
        ctx["focusNode"] = _node_summary(n)
        ctx["callers"] = [x for x in st.call_predecessors(body.node_id)]
        ctx["callees"] = [x for x in st.call_successors(body.node_id)]
        if body.include_impact:
            impacted, _ = st.impact_nodes(body.node_id)
            ctx["impactTransitiveCallers"] = impacted
    try:
        answer = await explain_with_ollama(body.question, ctx)
    except Exception as e:  # noqa: BLE001
        answer = f"Ollama request failed: {e!s}. Is Ollama running at {settings.ollama_base_url}?"
    return NLQueryResponse(answer=answer, structuredContext=ctx)


@app.get("/api/snapshot")
def api_snapshot_get() -> JSONResponse:
    st = get_store()
    return JSONResponse(content=st.to_dict())


@app.post("/api/snapshot")
def api_snapshot_post(body: dict[str, Any]) -> dict[str, Any]:
    global _store
    try:
        _store = GraphStore.from_dict(body)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid snapshot: {e}") from e
    return {
        "status": "ok",
        "nodeCount": len(_store.nodes()),
        "edgeCount": len(_store.edges()),
    }


@app.get("/api/entries")
def api_entries_hint() -> dict[str, Any]:
    """Hint for Phase 3: optional JSON file listing entry node ids."""
    return {
        "description": "Optional file codebase-simulator.entries.json in repo root: { \"entries\": [\"nodeId\", ...] }",
        "example": {"entries": []},
    }
