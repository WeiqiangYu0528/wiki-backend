# Search Package

Parallel hybrid search pipeline for the wiki agent.

## Components

- **orchestrator.py** — Coordinates parallel search across Meilisearch, ChromaDB, and symbol index. Merges, deduplicates, reranks results with Jaccard scoring.
- **meilisearch_client.py** — BM25 + optional vector search via Meilisearch v1.12.
- **semantic.py** — ChromaDB vector search with Ollama nomic-embed-text (768d) embeddings.
- **reranker.py** — Jaccard token-overlap reranker: `0.6×search + 0.3×jaccard + 0.1×recency`.
- **cache.py** — L1 in-memory LRU (200 entries) + L2 SQLite persistent (1h TTL).
- **embedding_cache.py** — Permanent SQLite embedding cache. Never re-embeds same text+model.
- **indexer.py** — Dual-index builder: indexes to both Meilisearch and ChromaDB.
- **lexical.py** — Ripgrep-based fallback when Meilisearch is unavailable.
- **chunker.py** — Markdown and source code chunking.
- **symbols.py** — Tree-sitter AST symbol extraction.
- **registry.py** — Repo metadata and query targeting.

## Search Flow

```
Query → Cache Check → Parallel Search → Merge → Dedup → Rerank → Budget Trim → Format
          ↓                ↓
        L1/L2      Meilisearch + ChromaDB + Symbol
```

## Configuration

All settings are in `security.py`:
- `search_max_results` (default: 8)
- `search_max_chars` (default: 2000)
- `cache_l1_max_entries` (default: 200)
- `cache_l2_ttl_seconds` (default: 3600)
- `meilisearch_url` (default: http://localhost:7700)
