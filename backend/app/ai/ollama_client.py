from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import settings


def _ollama_error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
        err = body.get("error")
        if isinstance(err, str) and err.strip():
            return err.strip()
    except (ValueError, json.JSONDecodeError, TypeError):
        pass
    text = (response.text or "").strip()
    return text[:800] if text else "(empty response body)"


def _format_ollama_failure(response: httpx.Response) -> str:
    """Ollama returns 404 for unknown models on POST /api/chat (not a missing route)."""
    msg = _ollama_error_message(response)
    model = settings.ollama_model
    hint = ""
    if response.status_code == 404:
        hint = (
            f" This usually means the model `{model}` is not installed. "
            f"Run: ollama pull {model}"
        )
        if "not found" not in msg.lower():
            hint += " (Ollama uses HTTP 404 for missing models.)"
    elif response.status_code >= 500:
        hint = " Check that the Ollama service is healthy."
    return f"Ollama returned {response.status_code}: {msg}.{hint}"


async def explain_with_ollama(
    question: str,
    structured_context: dict[str, Any],
    rag_chunks: list[dict[str, Any]] | None = None,
) -> str:
    """
    Ask Ollama to answer using graph JSON plus optional RAG code excerpts from ChromaDB.
    """
    rag_block = ""
    if rag_chunks:
        parts: list[str] = []
        for i, ch in enumerate(rag_chunks, 1):
            fp = ch.get("filePath") or ""
            sl = ch.get("startLine")
            el = ch.get("endLine")
            txt = ch.get("text") or ""
            parts.append(f"[{i}] {fp} (lines {sl}-{el})\n{txt}")
        rag_block = (
            "The following excerpts were retrieved from the analyzed codebase (vector similarity).\n"
            "Use them for implementation details; use the JSON below for call relationships.\n\n"
            + "\n\n---\n\n".join(parts)
            + "\n\n"
        )
    system = (
        "You are a code analysis assistant. You combine (1) retrieved source code excerpts "
        "when provided and (2) static call-graph JSON. Prefer citing file paths and line ranges "
        "when referencing code. Do not invent symbols that contradict the given graph or excerpts."
    )
    user = (
        f"{rag_block}"
        f"Question: {question}\n\n"
        f"Structured graph context (JSON):\n{json.dumps(structured_context, indent=2)}"
    )
    url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
    payload = {
        "model": settings.ollama_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(url, json=payload)
    except httpx.ConnectError as e:
        return (
            f"Cannot connect to Ollama at {settings.ollama_base_url}. "
            f"Start the Ollama application or run `ollama serve`. ({e})"
        )
    if r.status_code != 200:
        return _format_ollama_failure(r)
    data = r.json()
    msg = data.get("message") or {}
    content = msg.get("content") or data.get("response") or ""
    return (content or "No response from Ollama.").strip()


def explain_with_ollama_sync(
    question: str,
    structured_context: dict[str, Any],
    rag_chunks: list[dict[str, Any]] | None = None,
) -> str:
    rag_block = ""
    if rag_chunks:
        parts = []
        for i, ch in enumerate(rag_chunks, 1):
            fp = ch.get("filePath") or ""
            sl = ch.get("startLine")
            el = ch.get("endLine")
            txt = ch.get("text") or ""
            parts.append(f"[{i}] {fp} (lines {sl}-{el})\n{txt}")
        rag_block = (
            "The following excerpts were retrieved from the analyzed codebase (vector similarity).\n"
            "Use them for implementation details; use the JSON below for call relationships.\n\n"
            + "\n\n---\n\n".join(parts)
            + "\n\n"
        )
    system = (
        "You are a code analysis assistant. You combine retrieved source excerpts and "
        "static call-graph JSON. Prefer citing file paths and line ranges when referencing code."
    )
    user = (
        f"{rag_block}"
        f"Question: {question}\n\n"
        f"Structured graph context (JSON):\n{json.dumps(structured_context, indent=2)}"
    )
    url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
    payload = {
        "model": settings.ollama_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
    }
    try:
        with httpx.Client(timeout=120.0) as client:
            r = client.post(url, json=payload)
    except httpx.ConnectError as e:
        return (
            f"Cannot connect to Ollama at {settings.ollama_base_url}. "
            f"Start the Ollama application or run `ollama serve`. ({e})"
        )
    if r.status_code != 200:
        return _format_ollama_failure(r)
    data = r.json()
    msg = data.get("message") or {}
    content = msg.get("content") or data.get("response") or ""
    return (content or "No response from Ollama.").strip()
