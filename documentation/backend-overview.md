# Backend Overview

## Purpose

The wiki agent backend is an AI-powered knowledge assistant that serves as the
intelligence layer for an MkDocs-based wiki system. It enables natural-language
search and interaction across multiple wiki namespaces — claude-code, deepagents,
opencode, openclaw, autogen, and hermes-agent — through a conversational chat
interface embedded in MkDocs Material pages.

The backend receives user queries from a frontend chat widget ("Axiom"), routes
them through a LangGraph ReAct agent equipped with search and file-reading tools,
and returns contextual answers grounded in the wiki content.

---

## Tech Stack

| Layer              | Technology                                    |
|--------------------|-----------------------------------------------|
| **Runtime**        | Python 3.14, FastAPI, uvicorn                 |
| **Agent**          | LangGraph (`create_react_agent`)              |
| **LLM Routing**    | ChatOpenAI adapter → OpenAI / DeepSeek / Qwen / Ollama |
| **Search**         | Hybrid: Meilisearch BM25+vector, ChromaDB semantic, ripgrep lexical |
| **Embeddings**     | Ollama `nomic-embed-text` (768 dimensions)    |
| **Memory**         | SQLite FTS5                                   |
| **Cache**          | Multi-level: L1 in-memory LRU + L2 SQLite     |
| **Auth**           | JWT (HS256) + optional TOTP MFA               |
| **Observability**  | OpenTelemetry → OTEL Collector → Jaeger (traces) + Prometheus → Grafana (metrics) |
| **Frontend**       | MkDocs Material + embedded JS chat widget     |
| **Infrastructure** | Docker Compose (8 services)                   |

---

## Project Structure

```
backend/
├── main.py                        # FastAPI app, all HTTP endpoints
├── agent.py                       # LangGraph agent, tools, model routing, system prompt (~725 lines)
├── security.py                    # Pydantic Settings, JWT creation/validation, auth helpers
├── proposals.py                   # Document change proposal management
├── git_workflow.py                # Git operations for approved proposals
├── search/                        # Search package
│   ├── __init__.py
│   ├── orchestrator.py            # Main SearchOrchestrator: parallel dispatch, dedup, rerank
│   ├── lexical.py                 # Ripgrep-based full-text search
│   ├── semantic.py                # ChromaDB vector search
│   ├── meilisearch_client.py      # Meilisearch BM25 + vector hybrid search
│   ├── reranker.py                # Jaccard similarity reranking
│   ├── cache.py                   # L1 LRU + L2 SQLite search cache
│   ├── embedding_cache.py         # SQLite embedding cache (immutable)
│   ├── indexer.py                 # Document indexing for Meilisearch and ChromaDB
│   ├── symbols.py                 # Code symbol search (class/function extraction)
│   ├── registry.py                # Repo/namespace registry and URL-to-repo mapping
│   └── chunker.py                 # Document chunking for indexing
├── context_engine/                # Context assembly pipeline
│   ├── __init__.py
│   ├── engine.py                  # Main ContextEngine: assembles final message list
│   ├── budget.py                  # Token budget calculator (128K, 6 slices)
│   └── compactor.py               # History compaction (prune old tool outputs)
├── memory/                        # Conversational memory
│   ├── __init__.py
│   ├── base.py                    # Abstract memory interface
│   └── sqlite_memory.py           # SQLite FTS5 implementation
├── observability/                 # Telemetry
│   ├── __init__.py
│   ├── tracing.py                 # OTEL TracerProvider + BatchSpanProcessor setup
│   ├── metrics.py                 # OTEL MeterProvider + counter/histogram definitions
│   ├── tokens.py                  # Token counting utilities for LLM calls
│   ├── trace_store.py             # SQLite RequestTraceStore (per-request summaries)
│   └── config.py                  # Observability configuration
├── tests/                         # Test suite (114 tests across 14 files)
│   ├── conftest.py                # Shared fixtures
│   ├── test_agent.py
│   ├── test_main.py
│   ├── test_search_orchestrator.py
│   ├── test_cache.py
│   ├── test_context_engine.py
│   ├── test_memory.py
│   ├── test_observability.py
│   └── ...                        # Additional test files
├── data/                          # Runtime data (SQLite databases)
│   ├── cache.db
│   └── memory.db
├── pyproject.toml                 # Dependencies (managed with uv)
└── Dockerfile                     # Python 3.14-slim + uv

docs/
├── javascripts/
│   └── chatbox.js                 # Frontend chat widget ("Axiom")
├── ...                            # MkDocs wiki content

docker-compose.yml                 # All 8 services
mkdocs.yml                         # MkDocs configuration
```

---

## Key Design Decisions

### 1. LangGraph ReAct Agent

The system uses LangGraph's `create_react_agent` rather than a simple
prompt-and-respond pattern. This allows the agent to reason about which tools to
invoke, chain multiple tool calls, and produce answers grounded in retrieved
content. The agent has access to five tools: `search_knowledge_base`,
`read_workspace_file`, `read_source_file`, `list_wiki_pages`, and
`propose_doc_change`.

### 2. Hybrid Search

No single search strategy covers all query types. The system classifies queries
into three categories — symbol, concept, exact — and dispatches to different
search backends accordingly:

- **Meilisearch** handles BM25 keyword + vector similarity across wiki and code
  documents. It is the primary search backend.
- **ChromaDB** provides pure semantic search for concept queries where keyword
  matching is insufficient.
- **Ripgrep** serves as a fast lexical fallback for exact pattern matching and
  when Meilisearch is unavailable.

### 3. Multi-Level Caching

Search results are cached at two levels to minimize redundant computation:

- **L1**: In-process `OrderedDict` LRU (200 entries) for sub-millisecond hits.
- **L2**: SQLite with TTL (3600s) for persistence across restarts.

Embedding vectors are cached separately in SQLite with no TTL since embeddings
for the same text are immutable.

### 4. Token Budget Management

The context engine enforces a 128K token budget split across six categories:
system prompt (3%), memory (5%), history (35%), search results (25%), output
reserve (30%), and safety margin (2%). This prevents context window overflow
and ensures the LLM always has room to generate a response.

### 5. Model Routing via ChatOpenAI

All LLM providers are accessed through the `ChatOpenAI` adapter by varying the
`base_url`. This means switching from Ollama to DeepSeek to OpenAI requires
only changing an environment variable, not rewriting integration code.

### 6. Observability-First

Every request is traced end-to-end via OpenTelemetry. Spans cover the full
lifecycle: HTTP request → agent reasoning → tool calls → search → LLM calls.
Metrics (counters, histograms) are exported to Prometheus and visualized in
Grafana. A SQLite `RequestTraceStore` provides a queryable audit log.

---

## Quickstart

### Prerequisites

- Docker and Docker Compose
- At least 8 GB RAM (Ollama needs ~3.6 GB for the embedding model)
- Ports 8001, 7700, 11434, 16686, 9090, 19999 available

### Steps

```bash
# 1. Clone the repository
git clone <repo-url> wiki && cd wiki

# 2. (Optional) Create a .env file for production overrides
cat > .env <<EOF
JWT_SECRET_KEY=your-secure-random-secret
APP_ADMIN_PASSWORD=your-strong-password
CORS_ORIGINS=https://your-wiki-domain.com
EOF

# 3. Start all services
docker compose up -d

# 4. Wait for Ollama to pull the embedding model (first run only)
docker compose logs -f ollama-pull

# 5. Verify health
curl http://localhost:8001/health
# → {"status": "ok", "environment": "development"}

# 6. Get a JWT token
curl -X POST http://localhost:8001/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "password"}'

# 7. Send a chat query
curl -X POST http://localhost:8001/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"query": "How does the agent work?"}'
```

### Local Development (without Docker)

```bash
cd backend

# Install dependencies with uv
uv sync

# Start Ollama separately for embeddings
ollama serve &
ollama pull nomic-embed-text

# Start Meilisearch separately
docker run -d -p 7700:7700 getmeili/meilisearch:latest

# Run the backend
uv run uvicorn main:app --host 0.0.0.0 --port 8001 --reload

# Run the test suite
uv run python -m pytest tests/ -v
```

---

## What's Next

- [System Architecture](system-architecture.md) — How components interact
- [Components](components.md) — Detailed module reference
- [Search & Retrieval](search-and-retrieval.md) — Full search pipeline
- [Configuration](configuration.md) — All environment variables
- [Deployment](deployment.md) — Production setup guide
- [Testing](testing.md) — Test strategy and how to run
