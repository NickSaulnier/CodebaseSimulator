# AI Codebase Execution Simulator

A hybrid static analyzer, graph-based execution modeler, and visualization UI with optional Ollama-powered explanations.

## Structure

- `backend/` — FastAPI, Tree-sitter (JavaScript/TypeScript), graph store, trace simulator, **ChromaDB RAG** (code embeddings), Ollama client
- `frontend/` — Vite, React, TypeScript, React Flow, MUI

## Prerequisites

- Python 3.11+
- Node.js 20+
- [Ollama](https://ollama.com/) (optional, for natural-language explanations)

## Ollama

1. Install Ollama and pull a model, e.g. `ollama pull llama3.2`
2. Set environment variables (optional):

```text
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3.2
```

Optional: in a repo root, add `codebase-simulator.entries.json` with `{ "entries": ["nodeId", ...] }` to document entry-point node ids (returned in analyze response as `entriesFromConfig`).

The backend uses these when calling `/api/query/nl`.

**Troubleshooting:** If you see `404` on `POST /api/chat`, Ollama is usually reachable but the **model is not installed** (Ollama uses HTTP 404 for “model not found”). Run `ollama pull <OLLAMA_MODEL>` or set `OLLAMA_MODEL` to a tag you already have (`ollama list`).

## RAG (ChromaDB)

On **Analyze**, the backend chunks JS/TS sources (same discovery as the graph), embeds them with [sentence-transformers](https://www.sbert.net/) (`all-MiniLM-L6-v2` by default), and stores vectors in a **persistent Chroma** database under `backend/.chroma` (configurable via `CHROMA_PERSIST_DIR`).

Natural-language questions (`POST /api/query/nl`) **retrieve** the top similar chunks and pass them to Ollama **together** with the call-graph JSON. Set `useRag: false` in the request body to use only the graph. Set `RAG_ENABLED=false` to disable indexing and retrieval.

Environment (optional):

```text
CHROMA_PERSIST_DIR=.chroma
RAG_EMBEDDING_MODEL=all-MiniLM-L6-v2
RAG_CHUNK_LINES=55
RAG_CHUNK_OVERLAP_LINES=10
RAG_TOP_K=8
RAG_ENABLED=true
```

First run downloads the embedding model. On Windows, stop the backend (`uvicorn`) before `pip install` if you see file-lock errors.

## Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

CLI (analyze only):

```bash
python -m app.cli analyze C:\path\to\repo --json
```

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Open the URL shown (typically `http://127.0.0.1:5173`). The dev server proxies `/api` to the backend on port 8000.

## API overview

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/analyze` | Analyze a directory; returns graph JSON |
| GET | `/api/graph` | Last analyzed graph |
| POST | `/api/trace` | Bounded call trace from an entry node |
| POST | `/api/impact` | Reverse call graph impact set |
| POST | `/api/query/nl` | Explain structured graph context via Ollama |
| GET | `/api/snapshot` | Export graph snapshot |
| POST | `/api/snapshot` | Load graph snapshot |

## License

MIT
