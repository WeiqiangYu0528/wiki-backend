# Search Improvement Design Spec

**Date:** 2026-04-11
**Status:** Approved
**Scope:** Full Context Engine — hybrid search, memory, caching, context management

---

## 1. Problem Statement

The current agent search system is functional but limited:
- **Keyword search** uses ripgrep (exact string match, no BM25 ranking)
- **No reranking** — results sorted by raw score only
- **Session-only cache** — embeddings and results lost on restart
- **No context budgeting** — search results can overflow the context window
- **No persistent memory** — agent can't learn from past searches or user preferences
- **No context compression** — old tool outputs waste tokens
- **Embedding model** (all-minilm, 384d) is lower quality than alternatives

## 2. Reference Systems Studied

Six open-source agent systems were analyzed in depth:

### 2.1 Claude Code (TypeScript)
- **Key patterns adopted:** Dual-limit LRU cache (count + bytes), async prefetching without blocking, multi-pass token accounting with waste detection, memoized context discovery with manual cache breaking, path normalization for consistent cache hits
- **Key insight:** Context becomes the cache key — identical prefix = API cache hit

### 2.2 Hermes Agent (Python)
- **Key patterns adopted:** FTS5 → Jaccard → HRR multi-stage ranking, 2-layer context compression (pruning + summarization), prompt caching breakpoints, session search with LLM summarization, trust weighting + temporal decay
- **Key insight:** Layered ranking (keyword + token overlap + embedding + trust + time) balances precision and performance

### 2.3 OpenCode (TypeScript)
- **Key patterns adopted:** Streaming ripgrep for bulk file discovery, 2-part system prompt for cache stability, backward-scanning compaction with protected recent turns, head/tail truncation with file fallback, simple token estimation (chars/4) with overflow detection
- **Key insight:** Pre-estimate tokens → save full content to disk → return preview + path

### 2.4 OpenClaw (TypeScript)
- **Key patterns adopted:** Pluggable context engine with `assemble()` / `compact()` lifecycle, hybrid BM25 + semantic search with weighted merge, MMR diversity enforcement, token budget allocation with safety margin, incremental tail-only compaction for prompt cache preservation
- **Key insight:** Context engine abstraction allows swapping retrieval strategies without changing agent code

### 2.5 DeepAgents (Python)
- **Key patterns adopted:** Memory middleware with AGENTS.md injection, summarization middleware with dual triggers (fraction/tokens), client connection pooling via cache key, lazy-load-once-per-state pattern, graceful degradation when tools unavailable
- **Key insight:** Memory as education — system prompt teaches agent when/how to update memories

### 2.6 AutoGen (Python/.NET)
- **Key patterns adopted:** Abstract Memory protocol (query/add/clear), pluggable storage backends (list, ChromaDB, Redis), task-centric memory (learn from past successes), simplified query interfaces (LLM only generates query string), MIME-type-aware content storage
- **Key insight:** Storage-agnostic interface allows swapping implementations without code changes

## 3. Design Decisions

### 3.1 Approach Selected: Full Context Engine

Combines the best patterns from all six reference systems:
- **Meilisearch** for hybrid BM25 + vector search (replaces ripgrep)
- **Jaccard reranker** (from Hermes) for result precision
- **Persistent SQLite cache** (from Claude Code) for cross-session efficiency
- **Pluggable context engine** (from OpenClaw) with token budgeting
- **Memory Manager** (from AutoGen) with query/add/clear protocol
- **Context compactor** (from OpenCode + Hermes) — pruning now, LLM summarization as optional plugin later
- **nomic-embed-text** (768d) upgrade from all-minilm (384d)

### 3.2 Why Not Simpler Approaches

- **Approach B (Lightweight):** Keeps ripgrep — no BM25 ranking, lower search quality ceiling
- **Approach A (Hybrid without full context engine):** Missing pluggable architecture and memory system

### 3.3 Constraints
- No paid chat API tokens
- Ollama for embeddings (nomic-embed-text, local/free)
- Must work in both local dev and production
- Meilisearch added as Docker Compose service (~256MB memory limit)
- Pruning for context compression (no LLM summarization in Phase 1)

---

## 4. Architecture

### 4.1 System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Chat UI (Frontend)                          │
└────────────────────────────────┬────────────────────────────────────┘
                                 │ HTTP/SSE
┌────────────────────────────────▼────────────────────────────────────┐
│                     FastAPI Backend (main.py)                       │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────────┐ │
│  │ OTEL Middle  │  │RequestId MW  │  │   Context Engine (NEW)    │ │
│  └──────────────┘  └──────────────┘  │  assemble() / compact()   │ │
│                                       └───────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────┤
│                    LangGraph Agent (agent.py)                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │ReAct Loop│  │Tool Exec │  │Token     │  │Memory Manager(NEW)│  │
│  │          │  │          │  │Budget    │  │query/add/clear    │  │
│  └──────────┘  └──────────┘  └──────────┘  └───────────────────┘  │
├─────────────────────────────────────────────────────────────────────┤
│                      Search Layer (Hybrid)                          │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Search Orchestrator v2                                      │   │
│  │  Meilisearch(BM25+Vec) + ChromaDB(Semantic) + Symbol(AST)   │   │
│  │  → Merge + Dedup → Jaccard Rerank → Budget Trim             │   │
│  └──────────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────────┤
│                        Data & Cache Layer                           │
│  SQLite (search cache, embedding cache, memory, traces)            │
│  Meilisearch (BM25 + vector index)                                 │
│  ChromaDB (deep semantic, nomic-embed-text 768d)                   │
├─────────────────────────────────────────────────────────────────────┤
│  Embedding: Ollama nomic-embed-text (768d)                         │
├─────────────────────────────────────────────────────────────────────┤
│  Observability: OTEL SDK → Collector → Jaeger + Prometheus + Grafana│
└─────────────────────────────────────────────────────────────────────┘
```

### 4.2 New Components

| Component | Inspired By | Purpose |
|-----------|-------------|---------|
| Context Engine | OpenClaw | Pluggable prompt assembly with token budget |
| Memory Manager | AutoGen + Hermes | Persistent query/add/clear memory interface |
| Meilisearch Integration | OpenClaw hybrid | BM25 + vector hybrid search |
| Jaccard Reranker | Hermes | Token-overlap reranking for precision |
| Token Budget | Claude Code + OpenCode | Enforce context limits, detect waste |
| Persistent Cache | Claude Code | Cross-session SQLite cache for embeddings + queries |
| Context Compactor | OpenCode + Hermes | Prune stale tool outputs (Phase 1) |
| nomic-embed-text | — | 768d embeddings (upgrade from 384d) |

---

## 5. Search Pipeline v2

### 5.1 Flow

```
User Query
    │
    ▼
1. Query Classification (existing, enhanced)
   → concept / symbol / exact + expansion hints
    │
    ▼
2. Cache Check (NEW — persistent SQLite)
   Key: hash(query + scope), TTL: 1 hour
   HIT → skip to step 6
    │ MISS
    ▼
3. Parallel Search (NEW — concurrent execution)
   a) Meilisearch Hybrid (BM25 + vector) → 15 candidates
   b) ChromaDB Deep Semantic → 10 candidates (concept queries)
   c) Symbol Search (AST) → 5 candidates (symbol queries)
    │
    ▼
4. Merge + Deduplicate
   Union by (file_path, section)
   Normalize scores to 0-1 range
   Source weights: Meilisearch 0.4, ChromaDB 0.4, Symbol 0.2
    │
    ▼
5. Rerank (NEW — Hermes Jaccard)
   score = 0.6 × search_score + 0.3 × jaccard_sim + 0.1 × recency
   → Top K results (default 8)
    │
    ▼
6. Token Budget Check (NEW)
   Budget = context_limit × 0.3 (30% for search)
   Trim lowest-scored results if over budget
    │
    ▼
7. Cache + Return
   Store in persistent SQLite cache
   Emit OTEL spans + metrics
```

### 5.2 Meilisearch Integration

- **Image:** `getmeili/meilisearch:v1.12`
- **Feature:** `MEILI_EXPERIMENTAL_VECTOR_STORE=true` for hybrid search
- **Index config:**
  - `embedders.default.source: userProvided` (we compute embeddings via Ollama)
  - `embedders.default.dimensions: 768`
  - `searchableAttributes: [content, section, heading, symbol]`
  - `filterableAttributes: [type, repo, file_path, kind]`
  - `sortableAttributes: [file_path, created_at]`

### 5.3 Reranker (Jaccard)

Adapted from Hermes's hybrid ranking pipeline:

```python
def rerank(query: str, results: list[SearchResult]) -> list[SearchResult]:
    query_tokens = set(tokenize(query.lower()))
    for result in results:
        result_tokens = set(tokenize(result.content.lower()))
        jaccard = len(query_tokens & result_tokens) / len(query_tokens | result_tokens)
        recency = 1.0 / (1.0 + days_since_modified(result))
        result.final_score = (
            0.6 * result.normalized_score +
            0.3 * jaccard +
            0.1 * recency
        )
    return sorted(results, key=lambda r: r.final_score, reverse=True)[:top_k]
```

### 5.4 Changes from Current System

| Aspect | Current | New |
|--------|---------|-----|
| Keyword search | ripgrep (exact string) | Meilisearch (BM25 ranked) |
| Execution | Sequential tier escalation | Parallel search + merge |
| Ranking | Simple score sort | Jaccard reranking |
| Cache | Session-only LRU | L1 memory + L2 SQLite (persistent) |
| Budget | max_results only | Token-aware budget enforcement |
| Embeddings | all-minilm (384d) | nomic-embed-text (768d) |

---

## 6. Context Engine

### 6.1 Interface (OpenClaw-inspired)

```python
class ContextEngine:
    def assemble(
        self,
        prompt: str,
        messages: list[Message],
        token_budget: int,
        model: str,
    ) -> AssembledContext:
        """
        Returns ordered messages + token count + system prompt addition.
        Calls memory_manager.query() for relevant memories.
        Applies token budget allocation.
        """

    def compact(
        self,
        messages: list[Message],
        token_budget: int,
    ) -> list[Message]:
        """
        Reduce message history to fit budget.
        Phase 1: Prune old tool outputs.
        Phase 2 (future): LLM summarization plugin.
        """
```

### 6.2 Token Budget Allocation

For a 128K context model:

| Category | % | Tokens | Description |
|----------|---|--------|-------------|
| System Prompt | 3% | ~4K | Agent identity + tools |
| Memory | 5% | ~6K | Retrieved memories |
| History | 35% | ~45K | Conversation turns |
| Search Results | 25% | ~32K | Retrieved context |
| Output Reserve | 30% | ~38K | Assistant response |
| Safety Buffer | 2% | ~3K | Estimation inaccuracy margin |

### 6.3 Context Compactor

**Phase 1 (Now): Tool Output Pruning**
- Scan backward from newest messages
- Protect last N turns (default: 4)
- Replace old tool results with: `"[Tool output pruned - {tool_name}, {size} chars]"`
- Keep tool call metadata (name, args summary)
- Trigger: history > 50% of context budget

**Phase 2 (Future Plugin): LLM Summarization**
- Compress pruned region into structured summary
- Template: Goal, Progress, Decisions, Files, Next Steps
- Uses cheap model (Ollama or Gemini Flash)
- Iterative: updates previous summary (Hermes pattern)
- Registered as optional plugin to ContextEngine

---

## 7. Memory Manager

### 7.1 Protocol (AutoGen-inspired)

```python
class MemoryManager(ABC):
    async def query(self, query: str, top_k: int = 5) -> list[MemoryItem]
    async def add(self, content: str, metadata: dict) -> None
    async def clear(self) -> None
```

### 7.2 SQLite Implementation

```sql
CREATE TABLE memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    embedding BLOB,           -- 768d float32 vector
    metadata JSON,            -- {source, type, tags}
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE VIRTUAL TABLE memories_fts USING fts5(content, content=memories, content_rowid=rowid);
```

**Query flow:**
1. FTS5 keyword search → candidates
2. Embedding cosine similarity → candidates
3. Weighted merge: 0.5 × FTS5 + 0.5 × semantic
4. Return top_k

**Sources of memories:**
- Agent decisions that worked well
- User corrections/preferences
- Successful search patterns
- Project-specific context

---

## 8. Caching Architecture

### 8.1 Multi-Level Cache

```
Level 1: In-Memory LRU (per-session)           ~1ms lookup
  Key: hash(query + scope)
  Size: 200 entries max (dual-limit: count + bytes)
  TTL: session lifetime
  Inspired by: Claude Code FileStateCache

Level 2: SQLite Persistent Cache                ~5ms lookup
  Table: search_cache
  Columns: query_hash, scope, results (JSON), token_count, expires_at
  TTL: 1 hour (configurable)
  Cross-session, survives restarts

Level 3: Embedding Cache (SQLite)               ~2ms lookup
  Table: embedding_cache
  Columns: text_hash, model, embedding (BLOB), created_at
  No TTL (embeddings don't change for same text+model)
  Replaces: in-memory LRU (128 entries) → unlimited persistent
```

### 8.2 Improvements vs Current

| Cache | Before | After |
|-------|--------|-------|
| Search Results | Session LRU, lost on restart | L1 memory + L2 SQLite (persistent) |
| Embeddings | In-memory LRU (128 entries) | SQLite (unlimited, persistent) |
| Cross-session | None | Full (SQLite survives restarts) |
| Re-embedding cost | Re-embed after 128 evictions | Never re-embed same text+model |

---

## 9. Indexing Pipeline v2

### 9.1 Dual Indexing

Chunks are indexed into both Meilisearch and ChromaDB in parallel:

**Meilisearch Document:**
```json
{
    "id": "wiki:path/file.md:0",
    "content": "chunk text...",
    "file_path": "path/file.md",
    "section": "## Heading",
    "type": "wiki",
    "repo": "claude-code",
    "_vectors": {"default": [0.1, 0.2, ...]}
}
```

**ChromaDB Document:** (existing format, updated to 768d embeddings)

### 9.2 Embedding Model Upgrade

- **Before:** all-minilm (384d, ~67MB)
- **After:** nomic-embed-text (768d, ~274MB)
- **Impact:** Requires full reindex (dimension change)
- **Migration:** Delete old ChromaDB collections, rebuild with new model

---

## 10. File Structure

### 10.1 New Files

```
backend/
├── context_engine/              # NEW PACKAGE
│   ├── __init__.py
│   ├── engine.py                # assemble(), compact(), token budget
│   ├── compactor.py             # Tool output pruning (Phase 1)
│   └── budget.py                # Token budget allocation + tracking
│
├── memory/                      # NEW PACKAGE
│   ├── __init__.py
│   ├── base.py                  # ABC: query/add/clear protocol
│   └── sqlite_memory.py         # FTS5 + embedding hybrid memory
│
├── search/
│   ├── meilisearch_client.py    # NEW: Meilisearch integration
│   ├── reranker.py              # NEW: Jaccard + weighted reranking
│   └── cache.py                 # NEW: Multi-level persistent cache
│
├── tests/                       # NEW DIRECTORY
│   ├── test_search_cache.py     # 8 tests
│   ├── test_reranker.py         # 6 tests
│   ├── test_context_engine.py   # 7 tests
│   ├── test_compactor.py        # 5 tests
│   ├── test_memory.py           # 6 tests
│   ├── test_meilisearch.py      # 5 tests
│   ├── test_token_budget.py     # 5 tests
│   └── test_embedding_cache.py  # 5 tests
│
├── AGENTS.md                    # NEW: Agent-readable context
├── README.md                    # NEW: Complete project documentation
│
├── search/README.md             # NEW: Search pipeline documentation
├── context_engine/README.md     # NEW: Context engine documentation
└── memory/README.md             # NEW: Memory system documentation
```

### 10.2 Modified Files

```
backend/
├── search/
│   ├── orchestrator.py          # Parallel search, reranker integration
│   ├── semantic.py              # nomic-embed-text, persistent cache
│   └── indexer.py               # Dual-index (Meilisearch + ChromaDB)
│
├── search_tools.py              # Budget-aware params
├── agent.py                     # Context engine integration
├── main.py                      # Init new components
└── docker-compose.yml           # Add meilisearch service
```

### 10.3 Deprecated Files

```
backend/search/lexical.py        # Replaced by Meilisearch
```

---

## 11. Docker Compose

### 11.1 New Service

```yaml
meilisearch:
  image: getmeili/meilisearch:v1.12
  ports: ["7700:7700"]
  volumes: ["meili_data:/meili_data"]
  environment:
    MEILI_ENV: development
    MEILI_NO_ANALYTICS: "true"
    MEILI_EXPERIMENTAL_VECTOR_STORE: "true"
  mem_limit: 256m
```

### 11.2 Updated Service

```yaml
# Ollama: pull nomic-embed-text instead of all-minilm
```

---

## 12. Documentation Deliverables

| Document | Location | Purpose | Audience |
|----------|----------|---------|----------|
| README.md | backend/README.md | Complete project docs | Human + Agent |
| AGENTS.md | backend/AGENTS.md | Agent context: file map, decisions, pitfalls | Agent (primary) |
| Design Spec | docs/superpowers/specs/ | This design: rationale, analysis, decisions | Human + Agent |
| Architecture Diagram | docs/architecture.excalidraw | Visual system architecture | Human |
| search/README.md | backend/search/README.md | Search pipeline specifics | Human + Agent |
| context_engine/README.md | backend/context_engine/README.md | Budget, assembly, compaction | Human + Agent |
| memory/README.md | backend/memory/README.md | Memory protocol, SQLite impl | Human + Agent |

---

## 13. Test Plan

| Test File | Count | Coverage |
|-----------|-------|----------|
| test_search_cache.py | 8 | L1/L2 cache hit/miss, TTL, persistence, eviction |
| test_reranker.py | 6 | Jaccard scoring, weighted merge, dedup, edge cases |
| test_context_engine.py | 7 | Budget allocation, assembly, memory injection, overflow |
| test_compactor.py | 5 | Tool output pruning, protected turns, threshold |
| test_memory.py | 6 | Add/query/clear, FTS5, embedding similarity, persistence |
| test_meilisearch.py | 5 | Index CRUD, hybrid search, filtering |
| test_token_budget.py | 5 | Budget calculation, trimming, overflow detection |
| test_embedding_cache.py | 5 | Persistent storage, batch dedup, model-aware keys |
| **TOTAL** | **~47** | + existing 10 observability tests |

---

## 14. Observability Integration

All new components integrate with the existing OTEL observability:

| Component | Spans | Metrics |
|-----------|-------|---------|
| Search Orchestrator v2 | `search.parallel`, `search.merge`, `search.rerank` | `search_latency`, `search_result_count`, `search_cache_hit` |
| Meilisearch | `meilisearch.query`, `meilisearch.index` | `meili_query_latency`, `meili_result_count` |
| Reranker | `rerank.jaccard` | `rerank_score_delta`, `rerank_items_dropped` |
| Cache | `cache.check`, `cache.store` | `cache_hit_rate`, `cache_size_bytes` |
| Context Engine | `context.assemble`, `context.compact` | `context_budget_used`, `context_tokens_pruned` |
| Memory | `memory.query`, `memory.add` | `memory_query_latency`, `memory_items_returned` |
| Embedding Cache | `embedding.cache_check` | `embedding_cache_hit_rate`, `embedding_cache_size` |

---

## 15. Risks and Tradeoffs

### 15.1 Risks
- **Meilisearch vector store is experimental** — may have edge cases. Mitigation: ChromaDB as fallback for semantic search.
- **Embedding dimension change requires full reindex** — one-time cost at migration. Mitigation: automated reindex script.
- **More moving parts** — Meilisearch adds a service. Mitigation: health checks, graceful degradation if unavailable.
- **SQLite concurrent writes** — memory + cache share SQLite. Mitigation: WAL mode, separate DB files.

### 15.2 Tradeoffs
- **Meilisearch vs SQLite FTS5:** Meilisearch is more powerful but adds a service. Chose Meilisearch because user explicitly requested dedicated search engine.
- **Parallel vs sequential search:** Parallel is faster but uses more resources. Chose parallel because latency matters for interactive use.
- **Persistent cache vs in-memory:** SQLite adds ~5ms overhead per lookup. Chose persistent because cross-session value exceeds latency cost.
- **Tool output pruning vs LLM summarization:** Pruning is simpler but loses information. Chose pruning first because user prefers lightweight, with LLM as future plugin.

### 15.3 Future Expansion
- LLM summarization plugin for context compactor
- Task-centric memory (AutoGen pattern — learn from past search successes)
- MMR diversity enforcement in reranker
- Temporal decay for search results (Hermes pattern)
- Prompt cache stability optimization (OpenClaw tail-only mutation)
- Cross-repo search planning (multi-step search strategies)
