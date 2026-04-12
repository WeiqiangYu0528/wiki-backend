# MkDocs AI Backend

Agentic backend for the MkDocs Chatbox Widget. Provides a conversational AI assistant that can search, read, and propose changes to documentation across multiple wiki namespaces.

## Architecture

```
Chat UI → FastAPI Backend → LangGraph Agent
                              ↓
              Search Orchestrator v2 (parallel hybrid)
              ├── Meilisearch (BM25 + vector)
              ├── ChromaDB (deep semantic, nomic-embed-text 768d)
              └── Symbol Search (tree-sitter AST)
                              ↓
              Merge → Dedup → Jaccard Rerank → Budget Trim
                              ↓
              Context Engine (assemble / compact)
              ├── Token Budget (category-based allocation)
              ├── Memory Manager (SQLite FTS5)
              └── Context Compactor (tool output pruning)
                              ↓
              Observability (OTEL → Jaeger + Prometheus + Grafana)
```

## Core Components

- **Search Orchestrator** (`search/orchestrator.py`): Parallel hybrid search across Meilisearch, ChromaDB, and symbol index. Merges, deduplicates, and reranks results.
- **Context Engine** (`context_engine/`): Manages prompt assembly with token budgeting. Injects memories, compacts history, enforces context limits.
- **Memory Manager** (`memory/`): Persistent memory using SQLite FTS5. Stores agent decisions, user preferences, and search patterns.
- **Search Cache** (`search/cache.py`): L1 in-memory LRU + L2 SQLite persistent cache for search results.
- **Embedding Cache** (`search/embedding_cache.py`): Persistent SQLite cache for embeddings. Never re-embeds the same text+model.
- **Reranker** (`search/reranker.py`): Jaccard token-overlap reranker with weighted scoring.

## Setup

### Prerequisites
- Python 3.11+
- Docker + Docker Compose
- Ollama (for local embeddings)

### Quick Start

```bash
# Start all services
docker compose up -d

# Pull the embedding model
docker compose exec ollama ollama pull nomic-embed-text

# The backend is available at http://localhost:8001
```

### Local Development

```bash
cd backend
uv sync
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8001
```

### Environment Variables

Copy `.env.example` to `.env` and configure:
- `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` / `QWEN_API_KEY` — LLM provider keys
- `OLLAMA_BASE_URL` — Ollama server URL (default: http://localhost:11434)
- `OLLAMA_EMBED_MODEL` — Embedding model (default: nomic-embed-text)
- `MEILISEARCH_URL` — Meilisearch URL (default: http://localhost:7700)

## Testing

```bash
cd backend
uv run python -m pytest tests/ -v
```

## Docker Services

| Service | Port | Purpose |
|---------|------|---------|
| backend | 8001 | FastAPI application |
| ollama | 11434 | Local embedding model |
| meilisearch | 7700 | Hybrid search engine |
| otel-collector | 4317/4318 | OpenTelemetry collector |
| jaeger | 16686 | Distributed tracing UI |
| prometheus | 9090 | Metrics storage |
| grafana | 19999 | Dashboards |

## Limitations

- Meilisearch vector store is experimental (v1.12)
- Context compression is pruning-only (LLM summarization planned for Phase 2)
- Memory uses FTS5 keyword matching only (embedding similarity planned)
- No cross-repo search planning yet

## Future Improvements

- LLM summarization plugin for context compactor
- Embedding-based memory retrieval
- MMR diversity enforcement in reranker
- Temporal decay for search results
- Cross-repo search planning
- Task-centric memory (learn from past successes)
