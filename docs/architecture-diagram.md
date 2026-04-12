# Architecture Diagram: FastAPI Wiki Agent

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Docker Compose                                  │
│                                                                              │
│  ┌──────────────┐     ┌──────────────────────────────────────────────────┐  │
│  │   Chat UI    │────▶│              FastAPI Backend (:8001)             │  │
│  │  (MkDocs)    │◀────│                                                  │  │
│  └──────────────┘     │  ┌────────────────────────────────────────────┐  │  │
│                       │  │           LangGraph ReAct Agent             │  │  │
│                       │  │  ┌──────────┐  ┌──────────┐  ┌──────────┐ │  │  │
│                       │  │  │smart_    │  │find_     │  │read_code_│ │  │  │
│                       │  │  │search    │  │symbol    │  │section   │ │  │  │
│                       │  │  └────┬─────┘  └────┬─────┘  └──────────┘ │  │  │
│                       │  └───────┼─────────────┼─────────────────────┘  │  │
│                       │          │             │                          │  │
│                       │  ┌───────▼─────────────▼─────────────────────┐  │  │
│                       │  │        Search Orchestrator v2              │  │  │
│                       │  │  ┌─────────┐ ┌─────────┐ ┌────────────┐  │  │  │
│                       │  │  │Meili-   │ │ChromaDB │ │  Symbol    │  │  │  │
│                       │  │  │search   │ │Semantic │ │  Search    │  │  │  │
│                       │  │  │(BM25)   │ │(768d)   │ │(tree-sit.) │  │  │  │
│                       │  │  └────┬────┘ └────┬────┘ └─────┬──────┘  │  │  │
│                       │  │       └──────┬─────┘───────────┘          │  │  │
│                       │  │              ▼                             │  │  │
│                       │  │  Merge → Dedup → Jaccard Rerank → Trim   │  │  │
│                       │  └──────────────────────────────────────────┘  │  │
│                       │          │                                      │  │
│                       │  ┌───────▼──────────────────────────────────┐  │  │
│                       │  │         Context Engine                    │  │  │
│                       │  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ │  │  │
│                       │  │  │  Token   │ │ Memory   │ │ Context  │ │  │  │
│                       │  │  │  Budget  │ │ Manager  │ │Compactor │ │  │  │
│                       │  │  │(category)│ │(FTS5)    │ │(pruning) │ │  │  │
│                       │  │  └──────────┘ └──────────┘ └──────────┘ │  │  │
│                       │  └──────────────────────────────────────────┘  │  │
│                       │                                                │  │
│                       │  ┌──────────────────────────────────────────┐  │  │
│                       │  │           Cache Layer                     │  │  │
│                       │  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ │  │  │
│                       │  │  │L1 LRU   │ │L2 SQLite │ │Embedding │ │  │  │
│                       │  │  │(memory)  │ │(1h TTL)  │ │(permanent)│ │  │  │
│                       │  │  └──────────┘ └──────────┘ └──────────┘ │  │  │
│                       │  └──────────────────────────────────────────┘  │  │
│                       └──────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────┐  ┌──────────────────┐   │
│  │   Ollama     │  │ Meilisearch  │  │  Jaeger  │  │   Prometheus     │   │
│  │  (:11434)    │  │   (:7700)    │  │ (:16686) │  │    (:9090)       │   │
│  │ nomic-embed  │  │  BM25+vector │  │ Tracing  │  │    Metrics       │   │
│  └──────────────┘  └──────────────┘  └──────────┘  └──────────────────┘   │
│                                                                              │
│  ┌──────────────┐  ┌──────────────┐                                        │
│  │ OTEL Collect │  │   Grafana    │                                        │
│  │(:4317/:4318) │  │  (:19999)    │                                        │
│  └──────────────┘  └──────────────┘                                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow: Query Processing

```
User Query
    │
    ▼
┌──────────────────┐
│   Chat UI        │  HTTP POST /chat
│   (MkDocs)       │─────────────────────────────────────────────────────────▶
└──────────────────┘
                                                            ┌─────────────────┐
                                                            │  FastAPI Backend │
                                                            │                 │
                                                            │  ┌───────────┐  │
                                                            │  │ LangGraph │  │
                                                            │  │   Agent   │  │
                                                            │  └─────┬─────┘  │
                                                            └────────┼────────┘
                                                                     │
                                                              Tool Call dispatch
                                                                     │
                              ┌──────────────────────────────────────┤
                              │                                       │
                    ┌─────────▼──────────┐               ┌───────────▼────────┐
                    │  smart_search tool │               │ find_symbol tool   │
                    └─────────┬──────────┘               └───────────┬────────┘
                              │                                       │
                              └──────────────┬────────────────────────┘
                                             │
                                             ▼
                                ┌────────────────────────┐
                                │  Search Orchestrator   │
                                │         v2             │
                                └────────┬───────────────┘
                                         │  Fan-out (parallel)
                         ┌───────────────┼───────────────┐
                         │               │               │
                ┌────────▼───────┐  ┌────▼────┐  ┌──────▼──────┐
                │  Meilisearch   │  │ChromaDB │  │Symbol Search│
                │   (BM25)       │  │(768d    │  │(tree-sitter)│
                │                │  │semantic)│  │             │
                └────────┬───────┘  └────┬────┘  └──────┬──────┘
                         │               │               │
                         └───────────────▼───────────────┘
                                         │
                                         ▼
                              ┌──────────────────────┐
                              │  Merge & Dedup       │
                              │  Jaccard Rerank      │
                              │  Trim to budget      │
                              └──────────┬───────────┘
                                         │
                                         ▼
                              ┌──────────────────────┐
                              │   Context Engine     │
                              │  Token Budget Mgmt   │
                              │  Memory Manager      │
                              │  Context Compactor   │
                              └──────────┬───────────┘
                                         │
                                         ▼
                              ┌──────────────────────┐
                              │   LLM (via Ollama)   │
                              │   nomic-embed / LLM  │
                              └──────────┬───────────┘
                                         │
                                         ▼
                                      Response
                                   streamed back
                                   to Chat UI
```

---

## Cache Flow

```
Incoming Request
       │
       ▼
┌──────────────────────────────────────────────────────┐
│                    Cache Layer                        │
│                                                      │
│   1. L1 LRU (in-memory)                              │
│      └─ Hit? ──────────────────────────────────────▶ Return cached result
│      └─ Miss ──▶                                     │
│                                                      │
│   2. L2 SQLite (1h TTL)                              │
│      └─ Hit? ──────────────────────────────────────▶ Populate L1, return
│      └─ Miss ──▶                                     │
│                                                      │
│   3. Embedding Cache (permanent)                     │
│      └─ Hit? ──────────────────────────────────────▶ Skip Ollama call, return
│      └─ Miss ──▶ Call Ollama → store in all layers  │
│                                                      │
└──────────────────────────────────────────────────────┘
       │ (on cache miss, full query executes)
       ▼
  Search Orchestrator → Context Engine → LLM
       │
       ▼
  Result stored in L1 + L2 + Embedding cache
```

---

## Component Status: New vs Existing

### ✅ Existing Components

| Component | Description |
|-----------|-------------|
| Chat UI (MkDocs) | Frontend chat interface |
| FastAPI Backend (:8001) | Core API server |
| LangGraph ReAct Agent | Agent loop with tool dispatch |
| `read_code_section` tool | File/section reader tool |
| Ollama (:11434) | Local LLM + embedding server |
| Meilisearch (:7700) | Full-text BM25 search engine |
| Jaeger (:16686) | Distributed tracing |
| Prometheus (:9090) | Metrics collection |
| OTEL Collector (:4317/:4318) | OpenTelemetry data pipeline |
| Grafana (:19999) | Metrics dashboards |

### 🆕 New Components (feat/search-improvement)

| Component | Description |
|-----------|-------------|
| `smart_search` tool | Unified search tool with auto-routing |
| `find_symbol` tool | Symbol-aware code lookup (tree-sitter) |
| Search Orchestrator v2 | Parallel fan-out across all search backends |
| ChromaDB Semantic Search | 768-dimensional vector search |
| Symbol Search (tree-sitter) | AST-based symbol extraction and matching |
| Jaccard Reranker | Token overlap-based result reranking |
| Context Engine | Structured context assembly for the agent |
| Token Budget (category) | Per-category token allocation |
| Memory Manager (FTS5) | SQLite FTS5-backed conversation memory |
| Context Compactor (pruning) | Context window pruning strategy |
| L1 LRU Cache | In-memory least-recently-used cache |
| L2 SQLite Cache (1h TTL) | Persistent short-term result cache |
| Embedding Cache (permanent) | Permanent store for computed embeddings |

---

## Port Reference

| Service | Port | Protocol |
|---------|------|----------|
| FastAPI Backend | 8001 | HTTP/WebSocket |
| Ollama | 11434 | HTTP |
| Meilisearch | 7700 | HTTP |
| Jaeger UI | 16686 | HTTP |
| Prometheus | 9090 | HTTP |
| OTEL gRPC | 4317 | gRPC |
| OTEL HTTP | 4318 | HTTP |
| Grafana | 19999 | HTTP |
