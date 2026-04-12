# AGENTS.md — Agent-Readable Context

This file helps AI agents understand this codebase quickly.

## Project Structure

```
backend/
├── main.py              # FastAPI app, middleware, endpoints
├── agent.py             # LangGraph ReAct agent, tools, model routing
├── search_tools.py      # LangChain tool wrappers for search
├── security.py          # Settings, auth, JWT
├── proposals.py         # Doc change proposals
├── git_workflow.py      # Git operations for approved proposals
│
├── search/              # Search pipeline
│   ├── orchestrator.py  # Parallel hybrid search orchestration
│   ├── semantic.py      # ChromaDB + Ollama embeddings
│   ├── lexical.py       # Ripgrep fallback (deprecated by Meilisearch)
│   ├── meilisearch_client.py  # Meilisearch BM25+vector
│   ├── reranker.py      # Jaccard token-overlap reranker
│   ├── cache.py         # L1 LRU + L2 SQLite search cache
│   ├── embedding_cache.py     # Persistent embedding cache
│   ├── indexer.py       # Dual-index builder (Meilisearch + ChromaDB)
│   ├── chunker.py       # Markdown + source code chunking
│   ├── symbols.py       # Tree-sitter symbol extraction
│   └── registry.py      # Repo metadata + query targeting
│
├── context_engine/      # Context management
│   ├── engine.py        # Prompt assembly with token budget
│   ├── compactor.py     # Tool output pruning
│   └── budget.py        # Token budget allocation
│
├── memory/              # Persistent memory
│   ├── base.py          # Abstract MemoryManager protocol
│   └── sqlite_memory.py # SQLite FTS5 implementation
│
└── observability/       # OTEL instrumentation
    ├── tracing.py       # Tracer init, @traced decorator
    ├── metrics.py       # Counters, histograms, gauges
    ├── tokens.py        # Token estimation
    ├── trace_store.py   # SQLite trace persistence
    └── config.py        # OTEL configuration
```

## Key Design Decisions

1. **Meilisearch for keyword search** — replaces ripgrep for BM25 ranking
2. **Parallel search** — Meilisearch + ChromaDB + Symbol run concurrently
3. **Jaccard reranker** — weighted scoring: 0.6×search + 0.3×jaccard + 0.1×recency
4. **Persistent SQLite caches** — search results (1h TTL) + embeddings (permanent)
5. **nomic-embed-text (768d)** — upgrade from all-minilm (384d)
6. **Context engine** — token budgeting with category allocation
7. **Memory** — SQLite FTS5, query/add/clear protocol

## Common Pitfalls

- ChromaDB requires Docker (`chromadb` import fails locally without it)
- Meilisearch vector store needs `MEILI_EXPERIMENTAL_VECTOR_STORE=true`
- Embedding dimension change (384→768) requires full reindex
- SQLite uses WAL mode — separate DB files for cache/memory/traces
- Settings are in `security.py` (not a dedicated config file)

## How to Run Tests

```bash
cd backend && uv run python -m pytest tests/ -v
```
