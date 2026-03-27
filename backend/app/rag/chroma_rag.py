"""
ChromaDB-backed RAG: chunk analyzed source files, embed with sentence-transformers,
retrieve top-k for NL questions, merge with graph context for Ollama.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from app.analyzer.js_ts import discover_files
from app.config import settings

logger = logging.getLogger(__name__)

try:
    import chromadb
    from chromadb.utils import embedding_functions
except ImportError:
    chromadb = None  # type: ignore[assignment]
    embedding_functions = None  # type: ignore[assignment]

_ef: Any = None
_client: Any = None


def rag_available() -> bool:
    return chromadb is not None and embedding_functions is not None


def _project_collection_name(root: Path) -> str:
    h = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:24]
    return f"codebase_{h}"


def _get_embedding_function() -> Any:
    global _ef
    if not rag_available():
        raise RuntimeError("chromadb / sentence-transformers not installed")
    if _ef is None:
        _ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=settings.rag_embedding_model,
        )
    return _ef


def _get_client() -> Any:
    global _client
    if not rag_available():
        raise RuntimeError("chromadb not installed")
    if _client is None:
        base = Path(settings.chroma_persist_dir)
        if not base.is_absolute():
            base = Path.cwd() / base
        base.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(base.resolve()))
    return _client


def _chunk_text(
    rel_path: str,
    lines: list[str],
) -> list[tuple[str, dict[str, Any]]]:
    """Return (chunk_text, metadata) per chunk."""
    size = max(10, settings.rag_chunk_lines)
    overlap = max(0, min(settings.rag_chunk_overlap_lines, size - 1))
    step = max(1, size - overlap)
    out: list[tuple[str, dict[str, Any]]] = []
    i = 0
    part = 0
    while i < len(lines):
        end = min(i + size, len(lines))
        block = lines[i:end]
        start_line = i + 1
        end_line = end
        text = "\n".join(block)
        if text.strip():
            meta: dict[str, Any] = {
                "file_path": rel_path,
                "start_line": start_line,
                "end_line": end_line,
                "part": part,
            }
            out.append((text, meta))
            part += 1
        i += step
    if not out and lines:
        out.append(("\n".join(lines), {"file_path": rel_path, "start_line": 1, "end_line": len(lines), "part": 0}))
    return out


def _extra_rag_files(root: Path) -> list[Path]:
    """Optional high-value files at repo root."""
    extra: list[Path] = []
    for name in ("README.md", "package.json", "tsconfig.json"):
        p = root / name
        if p.is_file():
            extra.append(p.resolve())
    return extra


def index_codebase(root: Path) -> dict[str, Any]:
    """
    Build / replace Chroma collection for this root. Uses same file discovery as the static analyzer
    plus README/package.json when present.
    """
    if not settings.rag_enabled:
        return {"status": "skipped", "reason": "rag_enabled=false"}
    if not rag_available():
        return {
            "status": "skipped",
            "reason": "Install RAG deps: pip install chromadb sentence-transformers",
        }

    root = root.resolve()
    name = _project_collection_name(root)
    client = _get_client()
    ef = _get_embedding_function()

    try:
        client.delete_collection(name)
    except Exception:  # noqa: BLE001
        pass

    collection = client.create_collection(name=name, embedding_function=ef, metadata={"root": str(root)})

    files = list(dict.fromkeys(discover_files(root) + _extra_rag_files(root)))
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict[str, Any]] = []

    for fp in files:
        try:
            rel = str(fp.resolve().relative_to(root)).replace("\\", "/")
        except ValueError:
            rel = fp.name
        try:
            raw = fp.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            logger.warning("RAG skip file %s: %s", fp, e)
            continue
        line_list = raw.splitlines()
        for text, meta in _chunk_text(rel, line_list):
            cid = hashlib.sha256(f"{root}:{rel}:{meta['start_line']}:{meta['part']}".encode()).hexdigest()[:32]
            ids.append(cid)
            documents.append(text)
            metadatas.append(meta)

    if ids:
        collection.add(ids=ids, documents=documents, metadatas=metadatas)

    return {
        "status": "ok",
        "collection": name,
        "filesIndexed": len(files),
        "chunks": len(ids),
        "root": str(root),
    }


def retrieve_for_query(root: Path, question: str, k: int | None = None) -> list[dict[str, Any]]:
    """Return ranked chunks with text, file path, line range, and distance."""
    if not settings.rag_enabled or not rag_available():
        return []

    k = k if k is not None else settings.rag_top_k
    root = root.resolve()
    name = _project_collection_name(root)
    client = _get_client()
    ef = _get_embedding_function()

    try:
        collection = client.get_collection(name=name, embedding_function=ef)
    except Exception as e:  # noqa: BLE001
        logger.warning("RAG collection missing: %s", e)
        return []

    n = min(max(1, k), 50)
    res = collection.query(query_texts=[question], n_results=n)
    out: list[dict[str, Any]] = []
    ids_list = res.get("ids") or [[]]
    docs_list = res.get("documents") or [[]]
    meta_list = res.get("metadatas") or [[]]
    dist_list = res.get("distances") or [[]]

    ids0 = ids_list[0] if ids_list else []
    docs0 = docs_list[0] if docs_list else []
    meta0 = meta_list[0] if meta_list else []
    dist0 = dist_list[0] if dist_list else []

    for i, cid in enumerate(ids0):
        doc = docs0[i] if i < len(docs0) else ""
        meta = dict(meta0[i]) if i < len(meta0) and meta0[i] else {}
        dist = dist0[i] if i < len(dist0) else None
        out.append(
            {
                "id": cid,
                "text": doc,
                "filePath": meta.get("file_path", ""),
                "startLine": meta.get("start_line"),
                "endLine": meta.get("end_line"),
                "distance": dist,
            }
        )
    return out
