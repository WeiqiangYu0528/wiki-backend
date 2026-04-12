# System Architecture

## High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           MkDocs Material Site                           │
│                                                                          │
│   ┌──────────────────────────────────────────────────────────────────┐   │
│   │  Axiom Chat Widget (docs/javascripts/chatbox.js)                 │   │
│   │  - Floating chat panel embedded in every wiki page               │   │
│   │  - Sends POST /chat/stream with JWT auth                         │   │
│   │  - Renders streaming NDJSON (token/tool_call/citations/done)     │   │
│   │  - Passes page_context (current URL) for repo targeting          │   │
│   └──────────────────────┬───────────────────────────────────────────┘   │
│                          │ HTTPS / NDJSON stream                         │
└──────────────────────────┼───────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                        FastAPI Backend (port 8001)                        │
│                                                                          │
│   ┌─────────────┐  ┌──────────────┐  ┌────────────────┐                │
│   │  main.py     │  │  security.py │  │  proposals.py  │                │
│   │  - /health   │  │  - Settings  │  │  - CRUD store  │                │
│   │  - /login    │  │  - JWT       │  │  - Approve/    │                │
│   │  - /chat     │  │  - Auth      │  │    Reject      │                │
│   │  - /chat/    │  │  - MFA       │  └───────┬────────┘                │
│   │    stream    │  └──────────────┘          │                          │
│   └──────┬───────┘                             │                          │
│          │                            ┌────────▼────────┐                │
│          ▼                            │ git_workflow.py  │                │
│   ┌──────────────────────┐            │ - Branch/commit  │                │
│   │    LangGraph Agent   │            │ - Push/PR        │                │
│   │    (agent.py)        │            └─────────────────┘                │
│   │                      │                                               │
│   │  Tools:              │                                               │
│   │  • search_knowledge  │──────┐                                        │
│   │  • read_workspace    │      │                                        │
│   │  • read_source       │      │                                        │
│   │  • list_wiki_pages   │      │                                        │
│   │  • propose_doc_change│      │                                        │
│   └──────────────────────┘      │                                        │
│                                  │                                        │
│   ┌──────────────────────────────▼───────────────────────────────────┐   │
│   │              Search Orchestrator (search/orchestrator.py)         │   │
│   │                                                                   │   │
│   │   ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │   │
│   │   │  Meilisearch  │  │   ChromaDB   │  │   Ripgrep Lexical   │  │   │
│   │   │  BM25+Vector  │  │   Semantic   │  │   (fallback)        │  │   │
│   │   └──────────────┘  └──────────────┘  └──────────────────────┘  │   │
│   │                                                                   │   │
│   │   ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │   │
│   │   │   Symbols     │  │   Reranker   │  │   Cache (L1+L2)     │  │   │
│   │   └──────────────┘  └──────────────┘  └──────────────────────┘  │   │
│   └───────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│   ┌───────────────────────┐  ┌────────────────────────────────────────┐  │
│   │  Context Engine       │  │  Memory (SQLite FTS5)                  │  │
│   │  - Token budget       │  │  - Store/recall facts                  │  │
│   │  - History compaction │  │  - FTS5 full-text search               │  │
│   │  - Message assembly   │  │  - Top-5 injection into system prompt  │  │
│   └───────────────────────┘  └────────────────────────────────────────┘  │
│                                                                          │
│   ┌───────────────────────────────────────────────────────────────────┐  │
│   │  Observability (OTEL)                                             │  │
│   │  - Traces → BatchSpanProcessor → OTLP gRPC → Jaeger              │  │
│   │  - Metrics → PeriodicExportingMetricReader → Prometheus           │  │
│   │  - RequestTraceStore → SQLite audit log                           │  │
│   └───────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘

External Services (Docker Compose):
┌──────────────┐ ┌──────────────┐ ┌────────────┐ ┌──────────────┐
│   Ollama      │ │ Meilisearch  │ │   Jaeger   │ │  Prometheus  │
│  :11434       │ │  :7700       │ │  :16686    │ │  :9090       │
│  nomic-embed  │ │  BM25+vector │ │  traces    │ │  metrics     │
└──────────────┘ └──────────────┘ └────────────┘ └──────────────┘
┌──────────────┐ ┌──────────────────────────────────────────────┐
│   Grafana     │ │        OTEL Collector                        │
│  :19999       │ │  :4317 (gRPC) :4318 (HTTP) :8889 (Prom)    │
│  dashboards   │ │  receives OTLP, exports to Jaeger+Prom      │
└──────────────┘ └──────────────────────────────────────────────┘
```

---

## Component Interactions

### Request Flow: Synchronous Chat (`POST /chat`)

```
1. Client sends POST /chat with JSON body:
   { "query": "...", "history": [...], "model": "...", "page_context": "..." }

2. main.py:
   a. Validates JWT token from Authorization header
   b. Extracts user query and conversation history
   c. Resolves target model via agent.py model routing

3. agent.py:
   a. Context Engine assembles messages:
      - Calculates token budget (128K split into 6 slices)
      - Queries FTS5 memory for relevant memories → injects into system prompt
      - Compacts history if needed (prune old tool outputs beyond 4 protected turns)
      - Builds final message list: [system, ...history, user_query]
   b. LangGraph create_react_agent runs the ReAct loop:
      - LLM decides whether to call a tool or respond directly
      - If tool call → execute tool → feed result back → LLM decides again
      - Loop until LLM produces a final text response

4. Tool execution (if triggered):
   a. search_knowledge_base:
      - SearchOrchestrator classifies query (symbol/concept/exact)
      - Checks cache (L1 LRU → L2 SQLite)
      - If cache miss: dispatches to Meilisearch + ChromaDB + ripgrep in parallel
      - Deduplicates by file_path:section
      - Reranks with Jaccard similarity
      - Caches results (L1 + L2)
      - Returns formatted search results
   b. read_workspace_file / read_source_file:
      - Reads file content with line limits
      - Returns file content as tool result
   c. list_wiki_pages:
      - Enumerates markdown files in a namespace
   d. propose_doc_change:
      - Creates a change proposal stored in proposals.py

5. main.py returns JSON: {"reply": "..."}

6. Observability:
   - OTEL span covers entire request lifecycle
   - RequestTraceStore records summary (tokens, latency, tools, etc.)
   - Metrics counters/histograms updated
```

### Request Flow: Streaming Chat (`POST /chat/stream`)

```
1. Same auth and setup as synchronous chat

2. Response is NDJSON (newline-delimited JSON), each line is one event:
   - {"type": "token", "content": "partial text"}     — streaming LLM tokens
   - {"type": "tool_call", "name": "...", "args": {}}  — tool invocation notification
   - {"type": "citations", "sources": [...]}            — source references
   - {"type": "done"}                                   — stream complete
   - {"type": "error", "message": "..."}                — error occurred

3. The agent runs the same ReAct loop but yields events as they occur
```

---

## Data Flow Diagram

```
User Query
    │
    ▼
┌─────────────────────┐
│   JWT Validation     │ ← security.py verifies token
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐     ┌─────────────────────┐
│   Context Engine     │────▶│   Memory (FTS5)      │
│   - budget calc      │◀────│   - top-5 memories   │
│   - history compact  │     └─────────────────────┘
│   - message assembly │
└────────┬────────────┘
         │ [system, history, query]
         ▼
┌─────────────────────┐
│   LangGraph Agent    │
│   (ReAct loop)       │
│                      │
│   LLM ──► Tool? ────┼──── YES ──▶ Execute Tool ──▶ Feed back result
│    │                 │                                    │
│    ▼ NO              │◀───────────────────────────────────┘
│   Final Answer       │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   Response           │
│   - Sync: JSON       │
│   - Stream: NDJSON   │
└─────────────────────┘
```

---

## Service Topology (Docker Compose)

```
                    ┌─────────────────────────────────────────┐
                    │         Docker Compose Network           │
                    │                                          │
   Port 8001 ──────┤  backend ──────────────────────────────┐ │
                    │     │                                  │ │
                    │     ├── HTTP → ollama:11434            │ │
                    │     │         (embeddings)             │ │
                    │     │                                  │ │
                    │     ├── HTTP → meilisearch:7700        │ │
                    │     │         (BM25 + vector search)   │ │
                    │     │                                  │ │
                    │     ├── gRPC → otel-collector:4317     │ │
                    │     │         (traces + metrics)       │ │
                    │     │                                  │ │
                    │     └── HTTP → host.docker.internal    │ │
                    │               (external LLM chat)      │ │
                    │                                        │ │
   Port 11434 ─────┤  ollama                                │ │
                    │     └── GPU/CPU inference              │ │
                    │                                        │ │
                    │  ollama-pull (init container)          │ │
                    │     └── pulls nomic-embed-text         │ │
                    │                                        │ │
   Port 7700 ──────┤  meilisearch                           │ │
                    │     └── experimental vector store      │ │
                    │                                        │ │
                    │  otel-collector ───┬── Jaeger :16686   │ │
   Port 4317 ──────┤     :4317 (gRPC)   │                   │ │
   Port 4318 ──────┤     :4318 (HTTP)   │                   │ │
   Port 8889 ──────┤     :8889 (Prom)   └── Prometheus      │ │
                    │                                        │ │
   Port 16686 ─────┤  jaeger (all-in-one)                   │ │
                    │                                        │ │
   Port 9090 ──────┤  prometheus                            │ │
                    │     └── scrapes otel-collector:8889    │ │
                    │                                        │ │
   Port 19999 ─────┤  grafana                               │ │
                    │     └── datasource: prometheus:9090    │ │
                    └─────────────────────────────────────────┘
```

---

## Namespace Model

The system supports multiple wiki namespaces, each mapping to a separate
content repository or directory:

| Namespace       | Content Type                          |
|-----------------|---------------------------------------|
| `claude-code`   | Claude Code documentation             |
| `deepagents`    | Deep Agents framework docs            |
| `opencode`      | OpenCode project docs                 |
| `openclaw`      | OpenClaw legal AI docs                |
| `autogen`       | AutoGen multi-agent framework docs    |
| `hermes-agent`  | Hermes Agent docs                     |

The **registry** (`search/registry.py`) maps page URLs to namespaces. When a
user asks a question from a specific wiki page, the `page_context` URL is
resolved to a namespace, and the search is scoped to that namespace's content
first, with optional cross-namespace fallback.

---

## Security Architecture

```
Client ──► POST /login ──► security.py ──► Validate credentials
                                             │
                                             ├── Check username/password
                                             ├── (Optional) Verify TOTP code
                                             │
                                             ▼
                                          JWT Token (HS256)
                                             │
Client ──► POST /chat ──► Authorization: Bearer <token>
                              │
                              ▼
                          Decode JWT ──► Extract user identity
                              │
                              ▼
                          Process request
```

- JWT tokens are signed with HS256 and expire after 1440 minutes (24 hours) by
  default.
- MFA is optional: if `APP_MFA_SECRET` is set, TOTP verification is required
  during login.
- CORS origins are configurable via `CORS_ORIGINS`.

---

## Concurrency Model

- FastAPI runs on uvicorn with async I/O.
- The LangGraph agent executes tool calls sequentially within a single request
  (ReAct loop is serial by design).
- The Search Orchestrator dispatches to multiple backends **in parallel** using
  `asyncio.gather()` or equivalent concurrent execution.
- SQLite databases (cache, memory, trace store) use WAL mode for concurrent
  read access.
- Each request is independent — there is no shared mutable state between
  requests beyond the caches and memory store.

---

## Related Documentation

- [Components](components.md) — Detailed module descriptions
- [Search & Retrieval](search-and-retrieval.md) — Full search pipeline
- [Caching](caching.md) — Multi-level cache architecture
- [Observability](observability.md) — Tracing, metrics, dashboards
- [Deployment](deployment.md) — Docker Compose and production setup
